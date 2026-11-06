"""Crawl every category and subcategory on e-publishing.af.mil with 2 tabs, a HAR file and one SQLite database."""  # Module docstring describing what the script does

import asyncio  # Standard library package that runs the two workers at the same time
import base64  # Standard library package for storing binary response bodies inside the HAR file
import hashlib  # Standard library package for recognizing identical response bodies
import contextvars  # Standard library package that lets each worker tag its own log lines
import json  # Standard library package for writing headers and HAR entries
import logging  # Standard library package for progress and debug messages
import re  # Standard library package for parsing ids out of onclick attributes
import sqlite3  # Standard library package for the SQLite progress database
import sys  # Standard library package so log messages can go to the console
from dataclasses import (
    dataclass,
)  # Standard library package for small, readable data holders
from datetime import datetime, timezone  # Standard library packages for UTC timestamps
from pathlib import Path  # Standard library package for safe file paths
from urllib.parse import (
    parse_qsl,
    urlsplit,
)  # Standard library package for splitting URLs into query parameters

from playwright.async_api import (
    ConsoleMessage,
)  # Type hint for browser console messages
from playwright.async_api import (
    Error as PlaywrightError,
)  # Base class of every Playwright error, timeouts included
from playwright.async_api import Page  # Type hint for a browser tab
from playwright.async_api import Request  # Type hint for a network request
from playwright.async_api import Response  # Type hint for a network response
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)  # Error raised when a wait runs out
from playwright.async_api import (
    async_playwright,
)  # Entry point of the asynchronous Playwright API

PRODUCT_INDEX_URL = (
    "https://www.e-publishing.af.mil/Product-Index/"  # Page where every crawl starts
)
TOP_LEVEL_MENU_TITLES = [
    "Publications",
    "Forms",
]  # The two column headings on the Product Index page
DATABASE_FILE_PATH = Path(
    "state.db"
)  # The one and only database, remembering progress between runs
RECORDED_URL_PREFIX = (
    "https://www.e-publishing.af.mil/"  # Only responses from this site are recorded
)
RECORDED_RESOURCE_TYPES = {
    "document",
    "xhr",
    "fetch",
}  # Pages and AJAX calls are recorded; fonts, images, CSS and scripts are not
BROWSER_PROFILE_DIRECTORY = Path(
    "browser_profile"
)  # Folder where Chromium keeps its cache and cookies on disk
WORKER_COUNT = 2  # How many tabs crawl at the same time, all inside one Chromium window
WAIT_FOR_OTHER_WORKERS_SECONDS = (
    1.0  # How long an idle worker waits before asking the database for work again
)
MAX_ATTEMPTS = (
    3  # How many times a failing subcategory is tried across all runs before giving up
)
ACTION_TIMEOUT_MS = 30_000  # Maximum wait for a single click or lookup, in milliseconds
NAVIGATION_TIMEOUT_MS = 60_000  # Maximum wait for the index page to start loading; the site is slow when many tabs are open
NAVIGATION_ATTEMPTS = (
    3  # How many times a timed-out page load is tried before the visit counts as failed
)
NAVIGATION_RETRY_DELAY_SECONDS = (
    3.0  # Base pause before retrying a page load; it grows with every attempt
)
WORKER_START_STAGGER_SECONDS = 1.0  # Each worker starts this much later than the previous one, so they do not all hit the site at once
VIEW_ALL_TIMEOUT_MS = (
    5_000  # Maximum wait for the "view all" control, which is often legitimately absent
)
AJAX_TIMEOUT_MS = (
    10_000  # Maximum wait for the page's own AJAX requests to finish after a click
)
SERIES_LIST_TIMEOUT_MS = 5_000  # Maximum wait for the publication series list to appear after opening a subcategory
CONSECUTIVE_FAILURE_LIMIT = 5  # A worker stops after this many failures in a row, because something systemic is wrong

STATUS_PENDING = "pending"  # Subcategory is known but has not been visited yet
STATUS_IN_PROGRESS = "in_progress"  # Subcategory is currently being visited by a worker
STATUS_VIEWED_ALL = "viewed_all"  # Subcategory was visited and "view all" was clicked
STATUS_NO_VIEW_ALL = "no_view_all"  # Subcategory was visited and had no "view all" control (this is normal)
STATUS_FAILED = "failed"  # Visiting the subcategory raised an error

LISTING_UNLISTED = "unlisted"  # The category's subcategory list has not been read yet
LISTING_IN_PROGRESS = (
    "listing"  # A worker is reading the category's subcategory list right now
)
LISTING_LISTED = "listed"  # The category's subcategory list has been read and stored
LISTING_FAILED = (
    "listing_failed"  # Reading the list failed; it is retried on the next run
)

# Pattern that reads the category id from onclick="epubs.SelectCat(1, 'Air Force - Publications')"
CATEGORY_ID_PATTERN = re.compile(
    r"SelectCat\((\d+),"
)  # Capture the digits after SelectCat(
# Pattern that reads the organization id from onclick="epubs.SelectOrg(10141, 1, false, 'Departmental', ...)"
ORGANIZATION_ID_PATTERN = re.compile(
    r"SelectOrg\((\d+),"
)  # Capture the digits after SelectOrg(
# Pattern that matches the "view all" control shown after a subcategory is opened
VIEW_ALL_PATTERN = re.compile(
    r"view\s+all|all\s+publication|all\s+form", re.IGNORECASE
)  # Match any "view all" wording, ignoring case

current_worker_label: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_worker_label", default="main"
)  # Each worker task gets its own value


class WorkerLabelFilter(
    logging.Filter
):  # Adds the current worker's label to every log record
    def filter(self, record: logging.LogRecord) -> bool:  # Called for every log message
        record.worker = (
            current_worker_label.get()
        )  # Attach the label of the worker that is logging
        return True  # Keep the message


console_handler = logging.StreamHandler(
    sys.stdout
)  # Send log messages to the console only
console_handler.addFilter(
    WorkerLabelFilter()
)  # Make the worker label available to the format string
logging.basicConfig(  # Configure the logging system
    level=logging.DEBUG,  # Show everything, including debug messages
    format="%(asctime)s %(levelname)s [%(worker)s] %(funcName)s:%(lineno)d %(message)s",  # Include worker label, function name and line number
    handlers=[console_handler],  # Use only the console handler
)  # End of the logging configuration
logger = logging.getLogger("epubs_crawler")  # Create a named logger for this script


@dataclass  # Generate the constructor automatically
class Category:  # One category link such as "Publications > Air Force"
    menu_title: str  # Either "Publications" or "Forms"
    category_id: int  # The number passed to epubs.SelectCat
    category_name: str  # The visible text, for example "Air Force"


@dataclass  # Generate the constructor automatically
class Subcategory:  # One subcategory link such as "Departmental"
    organization_id: int  # The number passed to epubs.SelectOrg
    subcategory_name: str  # The visible text, for example "Departmental"


@dataclass  # Generate the constructor automatically
class NetworkEntry:  # One recorded request and response pair
    started_at: str  # When the response arrived, as an ISO timestamp
    duration_ms: float  # How long the request took in milliseconds
    method: str  # HTTP method such as GET or POST
    url: str  # The requested URL
    resource_type: str  # document, xhr or fetch
    request_headers: dict[str, str]  # Headers the browser sent
    request_post_data: str | None  # The request body, if there was one
    status: int  # HTTP status code
    status_text: str  # HTTP status text
    response_headers: dict[str, str]  # Headers the server sent
    mime_type: str  # Content-Type of the response
    body: bytes  # The response body


def to_har_headers(
    headers: dict[str, str]
) -> list[dict[str, str]]:  # Convert a header dictionary to the HAR list format
    return [
        {"name": name, "value": value} for name, value in headers.items()
    ]  # One name/value pair per header


def build_har_entry(
    row: sqlite3.Row,
) -> dict:  # Turn one database row into one HAR entry
    request_headers = json.loads(
        row["request_headers"]
    )  # Read the stored request headers
    response_headers = json.loads(
        row["response_headers"]
    )  # Read the stored response headers
    body = row["body"] or b""  # The stored body, or nothing for empty responses
    content = {
        "size": row["body_size"],
        "mimeType": row["mime_type"],
    }  # Describe the response content
    try:  # Text bodies are stored as plain text
        content["text"] = body.decode("utf-8")  # Decode the body as UTF-8
    except UnicodeDecodeError:  # Binary bodies are stored as base64
        content["text"] = base64.b64encode(body).decode(
            "ascii"
        )  # Encode the body as base64 text
        content["encoding"] = "base64"  # Tell HAR readers how to decode it
    request = {  # Describe the request
        "method": row["method"],  # HTTP method
        "url": row["url"],  # Requested URL
        "httpVersion": "HTTP/1.1",  # The real version is not recorded
        "cookies": [],  # Cookies are not recorded separately
        "headers": to_har_headers(request_headers),  # Request headers
        "queryString": [
            {"name": name, "value": value}
            for name, value in parse_qsl(urlsplit(row["url"]).query)
        ],  # Query parameters
        "headersSize": -1,  # Unknown
        "bodySize": len(row["request_post_data"].encode("utf-8"))
        if row["request_post_data"]
        else 0,  # Size of the request body
    }  # End of the request
    if row["request_post_data"] is not None:  # Only add post data when there is some
        request["postData"] = {
            "mimeType": request_headers.get("content-type", ""),
            "text": row["request_post_data"],
        }  # Request body
    response = {  # Describe the response
        "status": row["status"],  # HTTP status code
        "statusText": row["status_text"],  # HTTP status text
        "httpVersion": "HTTP/1.1",  # The real version is not recorded
        "cookies": [],  # Cookies are not recorded separately
        "headers": to_har_headers(response_headers),  # Response headers
        "content": content,  # Response body
        "redirectURL": response_headers.get(
            "location", ""
        ),  # Where a redirect points to
        "headersSize": -1,  # Unknown
        "bodySize": row["body_size"],  # Size of the response body
    }  # End of the response
    return {  # Assemble the entry
        "startedDateTime": row["started_at"],  # When it happened
        "time": row["duration_ms"],  # How long it took
        "request": request,  # The request
        "response": response,  # The response
        "cache": {},  # Cache details are not recorded
        "timings": {
            "send": 0,
            "wait": row["duration_ms"],
            "receive": 0,
        },  # Only the total time is known
        "_workerLabel": row[
            "worker_label"
        ],  # Custom field: which worker's tab made the request
        "_resourceType": row["resource_type"],  # Custom field: document, xhr or fetch
    }  # End of the entry


def current_utc_timestamp() -> str:  # Give the current time in a sortable text format
    return datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )  # For example 2026-11-05T14:30:00+00:00


class CrawlDatabase:  # Remembers every category, subcategory, run and error, and hands out work to the workers
    def __init__(
        self, database_file_path: Path, max_attempts: int
    ) -> None:  # Open the database and create the tables
        logger.debug(
            "Opening SQLite database at %s", database_file_path
        )  # Log which file is used
        self.max_attempts = (
            max_attempts  # Remember the retry limit for failing subcategories
        )
        self.connection = sqlite3.connect(
            database_file_path
        )  # Open (or create) the single database file
        self.connection.row_factory = sqlite3.Row  # Let rows be read by column name
        self.connection.execute(
            "PRAGMA journal_mode=DELETE"
        )  # Use a rollback journal so the database stays one single file
        self.connection.execute(
            "PRAGMA synchronous=FULL"
        )  # Force every commit to be flushed to the disk
        self.connection.execute(
            "PRAGMA temp_store=FILE"
        )  # Keep temporary tables and indexes on disk instead of in memory
        self.create_tables()  # Make sure all tables and columns exist
        self.recover_interrupted_work()  # Give back work that a crashed run had claimed

    def create_tables(
        self,
    ) -> None:  # Create the tables on the first run and upgrade older databases
        create_runs_sql = (  # SQL that creates the table of crawl runs
            "CREATE TABLE IF NOT EXISTS crawl_runs ("  # Start of the runs table
            "run_id INTEGER PRIMARY KEY AUTOINCREMENT, "  # Unique id of each run
            "started_at TEXT NOT NULL, "  # When the run started
            "finished_at TEXT, "  # When the run ended (empty if it crashed)
            "har_file_path TEXT, "  # Which HAR file this run recorded
            "subcategories_visited INTEGER NOT NULL DEFAULT 0, "  # How many subcategories this run visited successfully
            "subcategories_failed INTEGER NOT NULL DEFAULT 0)"  # How many subcategories this run failed on
        )  # End of the runs table SQL
        create_categories_sql = (  # SQL that creates the table of categories
            "CREATE TABLE IF NOT EXISTS categories ("  # Start of the categories table
            "category_id INTEGER PRIMARY KEY, "  # The id used by the website
            "menu_title TEXT NOT NULL, "  # Publications or Forms
            "category_name TEXT NOT NULL, "  # Visible name such as Air Force
            "listing_status TEXT NOT NULL DEFAULT 'unlisted', "  # unlisted, listing, listed or listing_failed
            "subcategory_count INTEGER NOT NULL DEFAULT 0, "  # How many subcategories were found
            "discovered_at TEXT NOT NULL)"  # When this category was first seen
        )  # End of the categories table SQL
        create_subcategories_sql = (  # SQL that creates the table of subcategories
            "CREATE TABLE IF NOT EXISTS subcategories ("  # Start of the subcategories table
            "category_id INTEGER NOT NULL REFERENCES categories(category_id), "  # Parent category
            "organization_id INTEGER NOT NULL, "  # The id used by the website
            "subcategory_name TEXT NOT NULL, "  # Visible name such as Departmental
            "status TEXT NOT NULL DEFAULT 'pending', "  # pending, in_progress, viewed_all, no_view_all or failed
            "attempts INTEGER NOT NULL DEFAULT 0, "  # How many times it has been visited
            "worker_id INTEGER, "  # Which worker claimed it most recently
            "last_error TEXT, "  # The most recent error message, if any
            "first_visited_at TEXT, "  # When it was first visited
            "last_visited_at TEXT, "  # When it was last visited
            "last_run_id INTEGER REFERENCES crawl_runs(run_id), "  # Which run visited it last
            "PRIMARY KEY (category_id, organization_id))"  # One row per category and organization pair
        )  # End of the subcategories table SQL
        create_network_bodies_sql = (  # SQL that creates the table of response bodies
            "CREATE TABLE IF NOT EXISTS network_bodies ("  # Start of the bodies table
            "body_hash TEXT PRIMARY KEY, "  # SHA-256 of the body, so identical bodies are stored only once
            "body BLOB NOT NULL)"  # The response body itself
        )  # End of the bodies table SQL
        create_network_entries_sql = (  # SQL that creates the table of recorded requests
            "CREATE TABLE IF NOT EXISTS network_entries ("  # Start of the entries table
            "entry_id INTEGER PRIMARY KEY AUTOINCREMENT, "  # Order in which entries were recorded
            "run_id INTEGER NOT NULL REFERENCES crawl_runs(run_id), "  # Which run recorded it
            "worker_label TEXT NOT NULL, "  # Which worker's tab made the request
            "started_at TEXT NOT NULL, "  # When it happened
            "duration_ms REAL NOT NULL, "  # How long it took
            "method TEXT NOT NULL, "  # HTTP method
            "url TEXT NOT NULL, "  # Requested URL
            "resource_type TEXT NOT NULL, "  # document, xhr or fetch
            "request_headers TEXT NOT NULL, "  # Request headers as JSON
            "request_post_data TEXT, "  # Request body, if any
            "status INTEGER NOT NULL, "  # HTTP status code
            "status_text TEXT NOT NULL, "  # HTTP status text
            "response_headers TEXT NOT NULL, "  # Response headers as JSON
            "mime_type TEXT NOT NULL, "  # Content-Type of the response
            "body_hash TEXT REFERENCES network_bodies(body_hash), "  # Link to the stored body
            "body_size INTEGER NOT NULL)"  # Size of the body in bytes
        )  # End of the entries table SQL
        with self.connection:  # Run all statements in one transaction
            self.connection.execute(
                create_network_bodies_sql
            )  # Create the bodies table
            self.connection.execute(
                create_network_entries_sql
            )  # Create the entries table
            self.connection.execute(create_runs_sql)  # Create the runs table
            self.connection.execute(
                create_categories_sql
            )  # Create the categories table
            self.connection.execute(
                create_subcategories_sql
            )  # Create the subcategories table
            self.add_column_if_missing(
                "categories", "listing_status", "TEXT NOT NULL DEFAULT 'unlisted'"
            )  # Upgrade databases from older versions
            self.add_column_if_missing(
                "subcategories", "worker_id", "INTEGER"
            )  # Upgrade databases from older versions
            category_columns = {
                row["name"]
                for row in self.connection.execute("PRAGMA table_info(categories)")
            }  # Read the column names
            if (
                "subcategories_listed" in category_columns
            ):  # Older databases used a yes/no column instead
                self.connection.execute(
                    "UPDATE categories SET listing_status = ? WHERE subcategories_listed = 1 AND listing_status = ?",
                    (LISTING_LISTED, LISTING_UNLISTED),
                )  # Carry the old answers over

    def add_column_if_missing(
        self, table_name: str, column_name: str, column_definition: str
    ) -> None:  # Add a column to an older table
        existing_columns = {
            row["name"]
            for row in self.connection.execute(f"PRAGMA table_info({table_name})")
        }  # Read the column names
        if column_name not in existing_columns:  # Only add it when it is not there yet
            self.connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
            )  # Add the column
            logger.info(
                "Added column %s.%s to the database", table_name, column_name
            )  # Log the upgrade

    def recover_interrupted_work(
        self,
    ) -> None:  # Make work claimed by a crashed run available again
        with self.connection:  # Save both changes together
            self.connection.execute(
                "UPDATE subcategories SET status = ? WHERE status = ?",
                (STATUS_PENDING, STATUS_IN_PROGRESS),
            )  # Unclaim subcategories
            self.connection.execute(  # Unclaim categories whose listing was interrupted or failed
                "UPDATE categories SET listing_status = ? WHERE listing_status IN (?, ?)",  # Statement
                (
                    LISTING_UNLISTED,
                    LISTING_IN_PROGRESS,
                    LISTING_FAILED,
                ),  # Values for the placeholders
            )  # End of the update

    def start_run(self) -> int:  # Record the start of a new crawl run
        with self.connection:  # Save the change immediately
            cursor = self.connection.execute(
                "INSERT INTO crawl_runs (started_at) VALUES (?)",
                (current_utc_timestamp(),),
            )  # Add the run
        logger.debug("Started crawl run %d", cursor.lastrowid)  # Log the run id
        return int(cursor.lastrowid)  # Hand the run id back to the caller

    def set_run_har_file_path(
        self, run_id: int, har_file_path: Path
    ) -> None:  # Remember which HAR file a run writes
        with self.connection:  # Save the change immediately
            self.connection.execute(
                "UPDATE crawl_runs SET har_file_path = ? WHERE run_id = ?",
                (str(har_file_path), run_id),
            )  # Store the path

    def finish_run(
        self, run_id: int
    ) -> None:  # Record the end of a crawl run together with its totals
        visited_count = self.connection.execute(  # Count subcategories this run visited successfully
            "SELECT COUNT(*) FROM subcategories WHERE last_run_id = ? AND status IN (?, ?)",  # Query for this run's successes
            (
                run_id,
                STATUS_VIEWED_ALL,
                STATUS_NO_VIEW_ALL,
            ),  # Values for the placeholders
        ).fetchone()[
            0
        ]  # Read the single number
        failed_count = self.connection.execute(  # Count subcategories this run failed on
            "SELECT COUNT(*) FROM subcategories WHERE last_run_id = ? AND status = ?",  # Query for this run's failures
            (run_id, STATUS_FAILED),  # Values for the placeholders
        ).fetchone()[
            0
        ]  # Read the single number
        with self.connection:  # Save the change immediately
            self.connection.execute(  # Update the run row
                "UPDATE crawl_runs SET finished_at = ?, subcategories_visited = ?, subcategories_failed = ? WHERE run_id = ?",  # Statement
                (
                    current_utc_timestamp(),
                    visited_count,
                    failed_count,
                    run_id,
                ),  # Values for the placeholders
            )  # End of the update

    def save_network_entry(
        self, run_id: int, worker_label: str, entry: NetworkEntry
    ) -> None:  # Store one request and response on disk right away
        body_hash = (
            hashlib.sha256(entry.body).hexdigest() if entry.body else None
        )  # Fingerprint the body so duplicates are stored once
        with self.connection:  # Save both inserts together
            if body_hash is not None:  # Only store non-empty bodies
                self.connection.execute(
                    "INSERT OR IGNORE INTO network_bodies (body_hash, body) VALUES (?, ?)",
                    (body_hash, entry.body),
                )  # Store the body once
            self.connection.execute(  # Store the entry itself
                "INSERT INTO network_entries (run_id, worker_label, started_at, duration_ms, method, url, resource_type, request_headers, "  # Columns, part 1
                "request_post_data, status, status_text, response_headers, mime_type, body_hash, body_size) "  # Columns, part 2
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",  # One placeholder per column
                (
                    run_id,
                    worker_label,
                    entry.started_at,
                    entry.duration_ms,
                    entry.method,
                    entry.url,
                    entry.resource_type,  # Values, part 1
                    json.dumps(entry.request_headers),
                    entry.request_post_data,
                    entry.status,
                    entry.status_text,  # Values, part 2
                    json.dumps(entry.response_headers),
                    entry.mime_type,
                    body_hash,
                    len(entry.body),
                ),  # Values, part 3
            )  # End of the entry insert

    def export_har(
        self, run_id: int, har_file_path: Path
    ) -> int:  # Write a run's recorded traffic to a HAR file, one entry at a time
        entry_count = 0  # Count the entries written
        with har_file_path.open(
            "w", encoding="utf-8"
        ) as har_file:  # Open the HAR file for writing
            har_file.write(
                '{"log": {"version": "1.2", "creator": {"name": "epubs_crawler", "version": "1.0"}, "entries": ['
            )  # Start of the HAR document
            cursor = self.connection.execute(  # Read the run's entries in order, without loading them all at once
                "SELECT e.*, b.body AS body FROM network_entries AS e LEFT JOIN network_bodies AS b ON b.body_hash = e.body_hash "  # Entries with their bodies
                "WHERE e.run_id = ? ORDER BY e.entry_id",  # Only this run, in recorded order
                (run_id,),  # Value for the placeholder
            )  # End of the query
            for row in cursor:  # Handle one row at a time so memory use stays flat
                if entry_count > 0:  # Entries after the first need a separating comma
                    har_file.write(",")  # Write the separator
                har_file.write(
                    json.dumps(build_har_entry(row))
                )  # Write the entry straight to disk
                entry_count += 1  # Count it
            har_file.write("]}}")  # End of the HAR document
        return entry_count  # Tell the caller how many entries were written

    def export_missing_har_files(
        self,
    ) -> None:  # Rebuild HAR files of earlier runs that were killed before they could export
        rows = self.connection.execute(  # Find runs that have recorded traffic
            "SELECT run_id, har_file_path FROM crawl_runs WHERE har_file_path IS NOT NULL "  # Runs with a HAR path
            "AND run_id IN (SELECT DISTINCT run_id FROM network_entries)"  # That have recorded entries
        ).fetchall()  # Read all rows
        for row in rows:  # Loop over those runs
            har_file_path = Path(row["har_file_path"])  # The expected HAR file
            if not har_file_path.exists():  # If the file was never written
                entry_count = self.export_har(
                    row["run_id"], har_file_path
                )  # Write it now from the database
                logger.info(
                    "Rebuilt %s from the database (%d entries)",
                    har_file_path,
                    entry_count,
                )  # Log the rebuild

    def save_categories(
        self, categories: list[Category]
    ) -> None:  # Remember every category found on the index page
        rows = [
            (c.category_id, c.menu_title, c.category_name, current_utc_timestamp())
            for c in categories
        ]  # Build one row per category
        with self.connection:  # Save all rows in one transaction
            self.connection.executemany(  # Insert new categories and refresh names of known ones
                "INSERT INTO categories (category_id, menu_title, category_name, discovered_at) VALUES (?, ?, ?, ?) "  # Insert part
                "ON CONFLICT(category_id) DO UPDATE SET menu_title = excluded.menu_title, category_name = excluded.category_name",  # Update part
                rows,  # All the rows
            )  # End of the insert

    def claim_next_category_to_list(
        self,
    ) -> Category | None:  # Give one worker a category whose subcategories are not known yet
        with self.connection:  # Pick and claim in one transaction so two workers can never get the same category
            row = self.connection.execute(  # Find the next unlisted category
                "SELECT category_id, menu_title, category_name FROM categories WHERE listing_status = ? ORDER BY rowid LIMIT 1",  # Query
                (LISTING_UNLISTED,),  # Value for the placeholder
            ).fetchone()  # Read the single row
            if row is None:  # If there is nothing to list
                return None  # Tell the worker there is no work of this kind
            self.connection.execute(
                "UPDATE categories SET listing_status = ? WHERE category_id = ?",
                (LISTING_IN_PROGRESS, row["category_id"]),
            )  # Claim it
        return Category(
            row["menu_title"], row["category_id"], row["category_name"]
        )  # Hand the category to the worker

    def save_subcategories(
        self, category: Category, subcategories: list[Subcategory]
    ) -> None:  # Store a category's subcategories
        rows = [
            (category.category_id, s.organization_id, s.subcategory_name)
            for s in subcategories
        ]  # Build one row per subcategory
        with self.connection:  # Save everything in one transaction
            self.connection.executemany(  # Insert subcategories, ignoring ones we already know
                "INSERT OR IGNORE INTO subcategories (category_id, organization_id, subcategory_name) VALUES (?, ?, ?)",  # Statement
                rows,  # All the rows
            )  # End of the insert
            self.connection.execute(  # Mark the category as fully listed
                "UPDATE categories SET listing_status = ?, subcategory_count = ? WHERE category_id = ?",  # Statement
                (
                    LISTING_LISTED,
                    len(subcategories),
                    category.category_id,
                ),  # Values for the placeholders
            )  # End of the update

    def mark_listing_failed(
        self, category: Category
    ) -> None:  # Record that a category's list could not be read
        with self.connection:  # Save the change immediately
            self.connection.execute(
                "UPDATE categories SET listing_status = ? WHERE category_id = ?",
                (LISTING_FAILED, category.category_id),
            )  # Update

    def release_category(
        self, category: Category
    ) -> None:  # Give a claimed category back without counting a failure
        with self.connection:  # Save the change immediately
            self.connection.execute(
                "UPDATE categories SET listing_status = ? WHERE category_id = ?",
                (LISTING_UNLISTED, category.category_id),
            )  # Unclaim it

    def release_subcategory(
        self, category: Category, subcategory: Subcategory
    ) -> None:  # Give a claimed subcategory back without counting an attempt
        with self.connection:  # Save the change immediately
            self.connection.execute(  # Unclaim the subcategory
                "UPDATE subcategories SET status = ? WHERE category_id = ? AND organization_id = ?",  # Statement
                (
                    STATUS_PENDING,
                    category.category_id,
                    subcategory.organization_id,
                ),  # Values for the placeholders
            )  # End of the update

    def claim_next_subcategory(
        self, worker_id: int, run_id: int
    ) -> tuple[
        Category, Subcategory
    ] | None:  # Give one worker a subcategory nobody else has
        with self.connection:  # Pick and claim in one transaction so two workers can never get the same subcategory
            row = self.connection.execute(  # Find the next subcategory that needs a visit
                "SELECT s.category_id, s.organization_id, s.subcategory_name, c.menu_title, c.category_name "  # Columns to read
                "FROM subcategories AS s JOIN categories AS c ON c.category_id = s.category_id "  # Join the parent category
                "WHERE s.status = ? OR (s.status = ? AND s.attempts < ? AND COALESCE(s.last_run_id, 0) != ?) "  # Pending, or failed in an earlier run
                "ORDER BY (s.status = ?), s.rowid LIMIT 1",  # Pending first, then retries, in the website's order
                (
                    STATUS_PENDING,
                    STATUS_FAILED,
                    self.max_attempts,
                    run_id,
                    STATUS_FAILED,
                ),  # Values for the placeholders
            ).fetchone()  # Read the single row
            if row is None:  # If there is nothing to visit
                return None  # Tell the worker there is no work of this kind
            self.connection.execute(  # Claim the subcategory for this worker
                "UPDATE subcategories SET status = ?, worker_id = ?, last_run_id = ? WHERE category_id = ? AND organization_id = ?",  # Statement
                (
                    STATUS_IN_PROGRESS,
                    worker_id,
                    run_id,
                    row["category_id"],
                    row["organization_id"],
                ),  # Values for the placeholders
            )  # End of the claim
        category = Category(
            row["menu_title"], row["category_id"], row["category_name"]
        )  # Build the category object
        return category, Subcategory(
            row["organization_id"], row["subcategory_name"]
        )  # Hand both objects to the worker

    def has_work_in_progress(
        self,
    ) -> bool:  # Check whether other workers are still busy and may create more work
        in_progress_count = self.connection.execute(  # Count claimed subcategories and categories
            "SELECT (SELECT COUNT(*) FROM subcategories WHERE status = ?) + (SELECT COUNT(*) FROM categories WHERE listing_status = ?)",  # Query
            (STATUS_IN_PROGRESS, LISTING_IN_PROGRESS),  # Values for the placeholders
        ).fetchone()[
            0
        ]  # Read the single number
        return in_progress_count > 0  # True while anybody is still working

    def mark_visited(
        self,
        category: Category,
        subcategory: Subcategory,
        run_id: int,
        viewed_all: bool,
    ) -> None:  # Record a successful visit
        status = (
            STATUS_VIEWED_ALL if viewed_all else STATUS_NO_VIEW_ALL
        )  # Choose the status from the result
        now = current_utc_timestamp()  # Take one timestamp for the whole update
        with self.connection:  # Save the change immediately
            self.connection.execute(  # Update the subcategory row
                "UPDATE subcategories SET status = ?, attempts = attempts + 1, last_error = NULL, "  # First half of the statement
                "first_visited_at = COALESCE(first_visited_at, ?), last_visited_at = ?, last_run_id = ? "  # Second half of the statement
                "WHERE category_id = ? AND organization_id = ?",  # Which row to update
                (
                    status,
                    now,
                    now,
                    run_id,
                    category.category_id,
                    subcategory.organization_id,
                ),  # Values for the placeholders
            )  # End of the update

    def mark_failed(
        self, category: Category, subcategory: Subcategory, run_id: int, error_text: str
    ) -> None:  # Record a failed visit
        now = current_utc_timestamp()  # Take one timestamp for the whole update
        with self.connection:  # Save the change immediately
            self.connection.execute(  # Update the subcategory row
                "UPDATE subcategories SET status = ?, attempts = attempts + 1, last_error = ?, "  # First half of the statement
                "first_visited_at = COALESCE(first_visited_at, ?), last_visited_at = ?, last_run_id = ? "  # Second half of the statement
                "WHERE category_id = ? AND organization_id = ?",  # Which row to update
                (
                    STATUS_FAILED,
                    error_text[:2000],
                    now,
                    now,
                    run_id,
                    category.category_id,
                    subcategory.organization_id,
                ),  # Values
            )  # End of the update

    def log_summary(self) -> None:  # Print an overview of everything stored so far
        logger.info("---- Crawl summary (all runs) ----")  # Heading
        status_rows = self.connection.execute(
            "SELECT status, COUNT(*) AS total FROM subcategories GROUP BY status"
        ).fetchall()  # Count per status
        for status_row in status_rows:  # Loop over the statuses
            logger.info(
                "Subcategories %-12s: %d", status_row["status"], status_row["total"]
            )  # Log one line per status
        category_total = self.connection.execute(
            "SELECT COUNT(*) FROM categories"
        ).fetchone()[
            0
        ]  # Count categories
        logger.info(
            "Categories known       : %d", category_total
        )  # Log the category total
        unlisted_total = self.connection.execute(
            "SELECT COUNT(*) FROM categories WHERE listing_status != ?",
            (LISTING_LISTED,),
        ).fetchone()[
            0
        ]  # Count categories whose subcategories are still unknown
        logger.info(
            "Categories not listed  : %d", unlisted_total
        )  # Log how many categories still need listing
        gave_up_rows = self.connection.execute(  # Find subcategories that used up all their attempts
            "SELECT category_id, subcategory_name, last_error FROM subcategories WHERE status = ? AND attempts >= ?",  # Query
            (STATUS_FAILED, self.max_attempts),  # Values for the placeholders
        ).fetchall()  # Read all rows
        for gave_up_row in gave_up_rows:  # Loop over the failures
            logger.warning(
                "Gave up on category %s > %s: %s",
                gave_up_row["category_id"],
                gave_up_row["subcategory_name"],
                gave_up_row["last_error"],
            )  # Log each

    def close(self) -> None:  # Close the database file
        self.connection.close()  # Release the file


def read_post_data(
    request: Request,
) -> str | None:  # Read a request body without failing on binary data
    try:  # Binary bodies cannot always be decoded as text
        return request.post_data  # The body as text, or None when there is none
    except Exception:  # If the body is not valid text
        return None  # Record the request without a body


async def record_network_response(
    response: Response, worker_label: str, database: CrawlDatabase, run_id: int
) -> None:  # Save one response to the database if it is worth keeping
    request = response.request  # The request that produced this response
    if (
        request.resource_type not in RECORDED_RESOURCE_TYPES
        or not response.url.startswith(RECORDED_URL_PREFIX)
    ):  # Skip fonts, images, scripts and other sites
        return  # Nothing to record
    try:  # Recording must never break the crawl
        try:  # Redirect responses have no body
            body = await response.body()  # Read the response body
        except PlaywrightError:  # If the body is unavailable
            body = b""  # Record the response without a body
        response_end = request.timing.get(
            "responseEnd", -1
        )  # Milliseconds from the start of the request to the end of the response
        entry = NetworkEntry(  # Collect everything about this response
            started_at=datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"
            ),  # Time of recording
            duration_ms=float(response_end)
            if response_end and response_end > 0
            else 0.0,  # Request duration
            method=request.method,  # HTTP method
            url=response.url,  # URL
            resource_type=request.resource_type,  # document, xhr or fetch
            request_headers=await request.all_headers(),  # Headers the browser sent
            request_post_data=read_post_data(request),  # Request body, if any
            status=response.status,  # Status code
            status_text=response.status_text,  # Status text
            response_headers=await response.all_headers(),  # Headers the server sent
            mime_type=response.headers.get("content-type", ""),  # Content type
            body=body,  # Response body
        )  # End of the entry
        database.save_network_entry(
            run_id, worker_label, entry
        )  # Write it to disk immediately
    except Exception:  # Any problem, including a closed tab
        logger.warning(
            "Could not record the response for %s", response.url, exc_info=True
        )  # Report it and keep crawling


def attach_debug_listeners(
    page: Page, worker_label: str, database: CrawlDatabase, run_id: int
) -> None:  # Hook logging and recording into the page events
    logger.debug(
        "Attaching debug listeners to the page of %s", worker_label
    )  # Log that the listeners are being attached

    def on_console(
        message: ConsoleMessage,
    ) -> None:  # Callback for text the web page prints to its console
        current_worker_label.set(worker_label)  # Tag the log line with the tab's worker
        logger.debug(
            "Browser console [%s]: %s", message.type, message.text
        )  # Log the message type and text

    def on_page_error(
        error: Exception,
    ) -> None:  # Callback for uncaught JavaScript errors on the page
        current_worker_label.set(worker_label)  # Tag the log line with the tab's worker
        logger.debug("Browser page error: %s", error)  # Log the error

    def on_request(
        request: Request,
    ) -> None:  # Callback for every outgoing network request
        current_worker_label.set(worker_label)  # Tag the log line with the tab's worker
        logger.debug(
            "Request  -> %s %s", request.method, request.url
        )  # Log the HTTP method and the URL

    async def on_response(
        response: Response,
    ) -> None:  # Callback for every incoming network response
        current_worker_label.set(worker_label)  # Tag the log line with the tab's worker
        logger.debug(
            "Response <- %s %s", response.status, response.url
        )  # Log the status code and the URL
        await record_network_response(
            response, worker_label, database, run_id
        )  # Save worthwhile responses to the database

    page.on("console", on_console)  # Log the page's console output
    page.on("pageerror", on_page_error)  # Log JavaScript errors from the page
    page.on("request", on_request)  # Log every request
    page.on("response", on_response)  # Log every response


async def log_current_page(
    page: Page,
) -> None:  # Log where a tab is, without ever failing the visit
    try:  # Reading the title can fail while the page is navigating
        logger.debug(
            "Current page URL: %s | title: %s", page.url, await page.title()
        )  # Log the URL and title
    except PlaywrightError:  # If the title could not be read
        logger.debug(
            "Current page URL: %s | title unavailable", page.url
        )  # Log just the URL


async def wait_for_ajax_to_finish(
    page: Page,
) -> None:  # Wait until the page's own jQuery AJAX requests are done
    logger.debug(
        "Waiting for jQuery AJAX requests to finish (timeout %d ms)", AJAX_TIMEOUT_MS
    )  # Log what we are waiting for
    try:  # The wait can time out on a slow response
        await page.wait_for_function(
            "() => !window.jQuery || window.jQuery.active === 0",
            timeout=AJAX_TIMEOUT_MS,
        )  # Wait for zero pending requests
        logger.debug("No AJAX requests are pending")  # Log that the wait finished
    except PlaywrightTimeoutError:  # If requests were still pending
        logger.info(
            "AJAX requests did not finish within the timeout, continuing anyway"
        )  # Report it and keep going


async def open_product_index(
    page: Page,
) -> None:  # Load the starting page in one tab, retrying when the slow site times out
    for attempt_number in range(
        1, NAVIGATION_ATTEMPTS + 1
    ):  # Try a limited number of times
        logger.debug(
            "Opening %s (attempt %d of %d)",
            PRODUCT_INDEX_URL,
            attempt_number,
            NAVIGATION_ATTEMPTS,
        )  # Log the navigation
        try:  # A timeout here usually means the site is busy
            await page.goto(
                PRODUCT_INDEX_URL,
                wait_until="domcontentloaded",
                timeout=NAVIGATION_TIMEOUT_MS,
            )  # Navigate to the Product Index page
            break  # The page started loading, so stop retrying
        except PlaywrightTimeoutError:  # If the site did not answer in time
            if attempt_number == NAVIGATION_ATTEMPTS:  # If this was the last attempt
                raise  # Give up and let the caller record the failure
            retry_delay = (
                NAVIGATION_RETRY_DELAY_SECONDS * attempt_number
            )  # Wait longer after every failed attempt
            logger.warning(
                "Page load timed out, retrying in %.1f seconds", retry_delay
            )  # Tell the user
            await asyncio.sleep(retry_delay)  # Pause before the next attempt
    await page.locator(".main-nav h4").first.wait_for(
        state="visible", timeout=ACTION_TIMEOUT_MS
    )  # Wait for the headings
    await page.wait_for_function(
        "() => typeof epubs !== 'undefined'", timeout=ACTION_TIMEOUT_MS
    )  # Wait until the page's click handlers exist
    await log_current_page(page)  # Log where we ended up


async def collect_categories(
    page: Page,
) -> list[Category]:  # List every category under both headings
    categories: list[Category] = []  # Start with an empty list
    for menu_title in TOP_LEVEL_MENU_TITLES:  # Loop over "Publications" and "Forms"
        links_xpath = f"//div[contains(@class,'main-nav')]//h4[normalize-space()='{menu_title}']/following-sibling::ul[1]//a"  # Links under this heading
        category_links = page.locator(
            f"xpath={links_xpath}"
        )  # Locate every category link under the heading
        link_count = await category_links.count()  # Count how many links were found
        logger.debug(
            "Found %d category links under %s", link_count, menu_title
        )  # Log the count
        for link_index in range(link_count):  # Loop over the links by position
            category_link = category_links.nth(
                link_index
            )  # Pick the link at this position
            onclick_text = (
                await category_link.get_attribute("onclick") or ""
            )  # Read the onclick attribute
            match = CATEGORY_ID_PATTERN.search(
                onclick_text
            )  # Pull the category id out of it
            if match is None:  # If the id could not be found
                logger.warning(
                    "Could not read a category id from: %s", onclick_text
                )  # Warn about it
                continue  # Skip this link
            category_name = (
                await category_link.inner_text()
            ).strip()  # Read the visible name
            categories.append(
                Category(menu_title, int(match.group(1)), category_name)
            )  # Remember the category
            logger.debug(
                "Category: %s > %s (id %s)", menu_title, category_name, match.group(1)
            )  # Log the category
    return categories  # Hand the list back to the caller


async def click_category(
    page: Page, category: Category
) -> None:  # Open one category in one tab
    logger.debug(
        "Clicking category: %s > %s", category.menu_title, category.category_name
    )  # Log the click
    category_link_selector = f"a[onclick*='SelectCat({category.category_id},']"  # Selector for this category's link
    await page.locator(category_link_selector).first.click(
        timeout=ACTION_TIMEOUT_MS
    )  # Click the link
    await page.locator(f"#cat-{category.category_id}").wait_for(
        state="visible", timeout=ACTION_TIMEOUT_MS
    )  # Wait for its pane
    logger.debug(
        "Category pane #cat-%d is visible", category.category_id
    )  # Log that the pane opened


async def collect_subcategories(
    page: Page, category: Category
) -> list[Subcategory]:  # List the subcategories of the open category
    subcategory_links = page.locator(
        f"#cat-{category.category_id} a[onclick*='SelectOrg']"
    )  # Links inside the pane
    link_count = await subcategory_links.count()  # Count how many links were found
    if link_count == 0:  # Having no subcategories is normal
        logger.info(
            "No subcategories in #cat-%d (this is normal), moving on",
            category.category_id,
        )  # Log it calmly
        return []  # Return an empty list so the caller moves on
    logger.debug(
        "Found %d subcategory links in #cat-%d", link_count, category.category_id
    )  # Log the count
    subcategories: list[Subcategory] = []  # Start with an empty list
    for link_index in range(link_count):  # Loop over the links by position
        subcategory_link = subcategory_links.nth(
            link_index
        )  # Pick the link at this position
        onclick_text = (
            await subcategory_link.get_attribute("onclick") or ""
        )  # Read the onclick attribute
        match = ORGANIZATION_ID_PATTERN.search(
            onclick_text
        )  # Pull the organization id out of it
        if match is None:  # If the id could not be found
            logger.warning(
                "Could not read an organization id from: %s", onclick_text
            )  # Warn about it
            continue  # Skip this link
        subcategories.append(
            Subcategory(
                int(match.group(1)), (await subcategory_link.inner_text()).strip()
            )
        )  # Remember it
    return subcategories  # Hand the list back to the caller


async def click_subcategory(
    page: Page, category: Category, subcategory: Subcategory
) -> None:  # Open one subcategory in one tab
    logger.debug(
        "Clicking subcategory: %s", subcategory.subcategory_name
    )  # Log the click
    subcategory_selector = f"#cat-{category.category_id} a[onclick*='SelectOrg({subcategory.organization_id},']"  # Selector for the exact link
    await page.locator(subcategory_selector).first.click(
        timeout=ACTION_TIMEOUT_MS
    )  # Click the link
    await wait_for_ajax_to_finish(
        page
    )  # Wait for the series list request, because no new page load happens
    try:  # An empty series list is legitimate
        await page.locator("#org-list > *").first.wait_for(
            state="attached", timeout=SERIES_LIST_TIMEOUT_MS
        )  # Wait for the list to appear
    except PlaywrightTimeoutError:  # If nothing appeared
        logger.info(
            "The series list stayed empty (this is normal), continuing"
        )  # Report it and keep going
    await log_current_page(page)  # Log where we ended up


async def click_view_all_publications(
    page: Page,
) -> bool:  # Click the "view all" control if there is one
    logger.debug(
        "Looking for the 'view all' control inside #org-list and #pub-list"
    )  # Log what we are looking for
    view_all_control = (
        page.locator("#org-list, #pub-list").get_by_text(VIEW_ALL_PATTERN).first
    )  # Find the control
    try:  # The control is legitimately missing on some pages
        await view_all_control.click(timeout=VIEW_ALL_TIMEOUT_MS)  # Click it
    except PlaywrightTimeoutError:  # If it never showed up
        logger.debug(
            "'View all' control was not found or not clickable"
        )  # Log the miss
        return False  # Tell the caller nothing was clicked
    await wait_for_ajax_to_finish(
        page
    )  # Wait for the full list of publications to load
    return True  # Tell the caller the click worked


async def crawl_subcategory(
    page: Page, category: Category, subcategory: Subcategory
) -> bool:  # Visit one full path and report if "view all" was clicked
    path_text = f"{category.menu_title} > {category.category_name} > {subcategory.subcategory_name}"  # Readable path
    logger.debug("Crawling: %s", path_text)  # Log the full path
    await open_product_index(page)  # Start from a clean index page
    await click_category(page, category)  # Go into the category
    await click_subcategory(page, category, subcategory)  # Go into the subcategory
    viewed_all = await click_view_all_publications(
        page
    )  # Click "view all" if it exists
    if viewed_all:  # If the click worked
        logger.info("Viewed all: %s", path_text)  # Log success
    else:  # If the control was not found
        logger.info(
            "No 'view all' control (this is normal), moving on: %s", path_text
        )  # Log it calmly
    return viewed_all  # Tell the caller what happened


async def list_category(
    page: Page, category: Category, database: CrawlDatabase
) -> bool:  # Read and store the subcategories of one category; False means the tab is gone
    settled = False  # Becomes True once the database knows how this category ended
    try:  # A problem in one category must not stop the whole crawl
        await open_product_index(page)  # Load the index page in this worker's tab
        await click_category(page, category)  # Open the category
        database.save_subcategories(
            category, await collect_subcategories(page, category)
        )  # Read and remember its subcategories
        settled = True  # The database now holds the result
        logger.info(
            "Listed %s > %s", category.menu_title, category.category_name
        )  # Log success
    except PlaywrightError:  # If the category could not be opened or read
        if (
            page.is_closed()
        ):  # If the tab or browser was closed, the category is not at fault
            return False  # Tell the worker to stop; the finally block gives the category back
        logger.exception(
            "Could not list category: %s > %s",
            category.menu_title,
            category.category_name,
        )  # Log with traceback
        database.mark_listing_failed(
            category
        )  # Remember the failure so it is retried on the next run
        settled = True  # The database now knows about the failure
    finally:  # Runs on success, failure, cancellation and crashes alike
        if not settled:  # If nothing recorded the outcome
            database.release_category(
                category
            )  # Give the category back so nobody is stuck waiting for it
    return True  # The tab is still usable


async def run_worker(
    worker_id: int, page: Page, database: CrawlDatabase, run_id: int
) -> None:  # One worker that keeps asking the database for work
    current_worker_label.set(f"worker {worker_id}")  # Tag every log line of this worker
    await asyncio.sleep(
        (worker_id - 1) * WORKER_START_STAGGER_SECONDS
    )  # Start later than the previous worker
    logger.info("Worker started")  # Log the start
    consecutive_failures = 0  # Count failures in a row to detect a systemic problem
    while True:  # Keep going until the database has no work left
        if (
            consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT
        ):  # If everything keeps failing
            logger.error(
                "%d failures in a row, stopping this worker so attempts are not wasted",
                consecutive_failures,
            )  # Explain why
            break  # Stop this worker
        claimed_subcategory = database.claim_next_subcategory(
            worker_id, run_id
        )  # Ask for a subcategory nobody else has taken
        if claimed_subcategory is not None:  # If one was handed out
            category, subcategory = claimed_subcategory  # Unpack the claim
            settled = False  # Becomes True once the database knows how this visit ended
            try:  # A problem in one subcategory must not stop the worker
                viewed_all = await crawl_subcategory(
                    page, category, subcategory
                )  # Visit it
                database.mark_visited(
                    category, subcategory, run_id, viewed_all
                )  # Remember that it is done
                settled = True  # The database now holds the result
                consecutive_failures = 0  # A success resets the counter
            except PlaywrightError as error:  # If anything went wrong on this path
                if (
                    page.is_closed()
                ):  # If the tab or browser was closed, the subcategory is not at fault
                    logger.error(
                        "The tab was closed, stopping this worker"
                    )  # Explain why
                    break  # Stop this worker; the finally block gives the subcategory back
                logger.exception(
                    "Failed subcategory: %s > %s",
                    category.category_name,
                    subcategory.subcategory_name,
                )  # Log with traceback
                database.mark_failed(
                    category, subcategory, run_id, str(error)
                )  # Remember the failure so it can be retried later
                settled = True  # The database now knows about the failure
                consecutive_failures += 1  # Count the failure
            finally:  # Runs on success, failure, cancellation and crashes alike
                if not settled:  # If nothing recorded the outcome
                    database.release_subcategory(
                        category, subcategory
                    )  # Give it back without counting an attempt
            continue  # Ask for more work
        category_to_list = (
            database.claim_next_category_to_list()
        )  # Ask for a category whose subcategories are still unknown
        if category_to_list is not None:  # If one was handed out
            if not await list_category(
                page, category_to_list, database
            ):  # Read and store its subcategories
                logger.error("The tab was closed, stopping this worker")  # Explain why
                break  # Stop this worker
            continue  # Ask for more work
        if (
            database.has_work_in_progress()
        ):  # If another worker is busy it may create more work
            await asyncio.sleep(
                WAIT_FOR_OTHER_WORKERS_SECONDS
            )  # Wait a moment and ask again
            continue  # Ask for more work
        break  # Nothing left anywhere, so this worker is finished
    logger.info("Worker finished")  # Log the end


async def main() -> None:  # Program entry point
    database = CrawlDatabase(
        DATABASE_FILE_PATH, MAX_ATTEMPTS
    )  # Open the one and only progress database
    database.export_missing_har_files()  # Rebuild HAR files of earlier runs that were killed before exporting
    run_id = database.start_run()  # Record that a new run has begun
    har_file_path = Path(
        f"epubs_product_index_run{run_id}.har"
    )  # Give every run its own HAR file so older ones are kept
    database.set_run_har_file_path(
        run_id, har_file_path
    )  # Remember which HAR file belongs to this run
    try:  # Make sure the run is closed out in the database even if something fails
        logger.debug("Starting Playwright")  # Log the startup
        async with async_playwright() as playwright:  # Start Playwright and make sure it shuts down cleanly
            browser_context = await playwright.chromium.launch_persistent_context(  # Launch ONE Chromium window with a profile stored on disk
                user_data_dir=str(
                    BROWSER_PROFILE_DIRECTORY
                ),  # Keep the cache and cookies in this folder instead of in memory
                headless=True,  # Show the browser window
                args=["--start-maximized"],  # Open the window maximized
                no_viewport=True,  # Let the pages fill the maximized window instead of a fixed size
            )  # End of the launch options
            try:  # Make sure the HAR file is written even if something fails
                browser_context.set_default_timeout(
                    ACTION_TIMEOUT_MS
                )  # Apply the default wait to every action
                browser_context.set_default_navigation_timeout(
                    NAVIGATION_TIMEOUT_MS
                )  # Apply the longer wait to every navigation
                pages = [
                    browser_context.pages[0]
                    if browser_context.pages
                    else await browser_context.new_page()
                ]  # Worker 1 reuses the first tab
                while (
                    len(pages) < WORKER_COUNT
                ):  # Every further worker gets a new tab, not a new browser
                    pages.append(await browser_context.new_page())  # Open the extra tab
                for worker_number, page in enumerate(
                    pages, start=1
                ):  # Loop over all tabs with their worker numbers
                    attach_debug_listeners(
                        page, f"worker {worker_number}", database, run_id
                    )  # Start logging and recording network traffic to the database
                await open_product_index(
                    pages[0]
                )  # Load the starting page once to read the headings
                categories = await collect_categories(
                    pages[0]
                )  # List every category under Publications and Forms
                if (
                    not categories
                ):  # If nothing was found, the page layout probably changed
                    logger.error(
                        "No categories found, the page layout may have changed"
                    )  # Tell the user
                database.save_categories(
                    categories
                )  # Remember the categories in the database
                logger.info(
                    "Found %d categories in total", len(categories)
                )  # Log the total
                async with asyncio.TaskGroup() as task_group:  # Run the workers at the same time and stop all of them if one crashes
                    for worker_number, page in enumerate(
                        pages, start=1
                    ):  # Pair each tab with a worker number
                        task_group.create_task(
                            run_worker(worker_number, page, database, run_id)
                        )  # Start the worker
            finally:  # Always run this cleanup
                logger.debug("Closing the browser context")  # Log the cleanup step
                try:  # Closing can fail if the window or the Playwright driver is already gone
                    await browser_context.close()  # Close the browser
                except Exception:  # Playwright reports a dead driver with a plain Exception
                    logger.exception(
                        "Could not close the browser context cleanly"
                    )  # Report it without hiding the original error
    finally:  # Always run this cleanup
        database.finish_run(run_id)  # Record the end time and totals of this run
        try:  # A failed export must not hide the real error or skip the summary
            entry_count = database.export_har(
                run_id, har_file_path
            )  # Write this run's recorded traffic to its HAR file, one entry at a time
            logger.info(
                "HAR saved to %s (%d entries)", har_file_path.resolve(), entry_count
            )  # Tell the user where the HAR file is
        except Exception:  # Any problem while writing the file
            logger.exception(
                "Could not write the HAR file, the traffic is still in the database"
            )  # The data is safe in state.db
        database.log_summary()  # Print the overall progress
        database.close()  # Close the database file


if __name__ == "__main__":  # Only run when the file is executed directly
    asyncio.run(main())  # Start the crawl
