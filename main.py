"""Crawl every category and subcategory on e-publishing.af.mil with 10 tabs, one log file and one HAR file per run, and one SQLite database."""  # Module docstring describing what the script does

import asyncio  # Standard library package that runs the workers at the same time
import base64  # Standard library package for storing binary response bodies inside the HAR file
import contextvars  # Standard library package that lets each worker tag its own log lines
import hashlib  # Standard library package for recognizing identical response bodies
import importlib.metadata  # Standard library package for reading the installed Playwright version
import json  # Standard library package for writing headers and HAR entries
import logging  # Standard library package for progress and debug messages
import os  # Standard library package for atomic file replacement
import platform  # Standard library package for describing the machine in the log
import re  # Standard library package for parsing ids out of onclick attributes
import shutil  # Standard library package for checking free disk space
import signal  # Standard library package for reacting to Ctrl+C and termination requests
import sqlite3  # Standard library package for the SQLite progress database
import sys  # Standard library package so log messages can go to the console
from dataclasses import (
    dataclass,
    field,
)  # Standard library package for small, readable data holders
from datetime import datetime, timezone  # Standard library packages for UTC timestamps
from pathlib import Path  # Standard library package for safe file paths
from urllib.parse import (
    parse_qsl,
    urlsplit,
)  # Standard library package for splitting URLs into query parameters

if sys.version_info < (
    3,
    11,
):  # asyncio.TaskGroup and asyncio.timeout only exist in Python 3.11 and newer
    raise SystemExit(
        "This script needs Python 3.11 or newer"
    )  # Stop early with a clear message

from playwright.async_api import (  # Import everything needed from Playwright in one place
    BrowserContext,  # Type hint for the one Chromium window with its profile
    ConsoleMessage,  # Type hint for browser console messages
    Dialog,  # Type hint for JavaScript alert, confirm and prompt boxes
    Download,  # Type hint for a file download started by a page
    Error as PlaywrightError,  # Base class of every Playwright error, timeouts included
    Page,  # Type hint for a browser tab
    Request,  # Type hint for a network request
    Response,  # Type hint for a network response
    TimeoutError as PlaywrightTimeoutError,  # Error raised when a Playwright wait runs out
    async_playwright,  # Entry point of the asynchronous Playwright API
)  # End of the Playwright imports

BASE_DIRECTORY = (
    Path(__file__).resolve().parent
)  # Every file lives next to this script, no matter which folder the script is started from
PRODUCT_INDEX_URL = (
    "https://www.e-publishing.af.mil/Product-Index/"  # Page where every crawl starts
)
TOP_LEVEL_MENU_TITLES = [
    "Publications",
    "Forms",
]  # The two column headings on the Product Index page
DATABASE_FILE_PATH = (
    BASE_DIRECTORY / "state.db"
)  # The one and only database, remembering progress between runs
LOCK_FILE_PATH = (
    BASE_DIRECTORY / "crawler.lock"
)  # File that stops two copies of this script from running together
LOG_DIRECTORY = BASE_DIRECTORY / "logs"  # Folder that receives one log file per run
BROWSER_PROFILE_DIRECTORY = (
    BASE_DIRECTORY / "browser_profile"
)  # Folder where Chromium keeps its cache and cookies on disk
RECORDED_URL_PREFIX = (
    "https://www.e-publishing.af.mil/"  # Only responses from this site are recorded
)
RECORDED_RESOURCE_TYPES = {
    "document",
    "xhr",
    "fetch",
}  # Pages and AJAX calls are recorded; fonts, images, CSS and scripts are not
CONSOLE_LOG_LEVEL = (
    logging.DEBUG
)  # The console stays readable; the log file always gets everything (DEBUG)
WORKER_COUNT = (
    10  # How many tabs crawl at the same time, all inside one Chromium window
)
WAIT_FOR_OTHER_WORKERS_SECONDS = (
    1.0  # How long an idle worker waits before asking the database for work again
)
MAX_ATTEMPTS = (
    3  # How many times a failing subcategory is tried across all runs before giving up
)
ACTION_TIMEOUT_MS = 30_000  # Maximum wait for a single click or lookup, in milliseconds
NAVIGATION_TIMEOUT_MS = 60_000  # Maximum wait for the index page to start loading; the site is slow when many tabs are open
NAVIGATION_ATTEMPTS = (
    3  # How many times a failed page load is tried before the visit counts as failed
)
NAVIGATION_RETRY_DELAY_SECONDS = (
    3.0  # Base pause before retrying a page load; it grows with every attempt
)
NAVIGATION_CONCURRENCY = 3  # How many tabs may load the index page at the very same moment, so the site is not flooded
WORKER_START_STAGGER_SECONDS = 1.0  # Each worker starts this much later than the previous one, so they do not all hit the site at once
VIEW_ALL_TIMEOUT_MS = (
    5_000  # Maximum wait for the "view all" control, which is often legitimately absent
)
AJAX_TIMEOUT_MS = (
    10_000  # Maximum wait for the page's own AJAX requests to finish after a click
)
AJAX_SETTLE_MS = 500  # Short pause after AJAX looks finished, to catch a second request started by the first one
SERIES_LIST_TIMEOUT_MS = 5_000  # Maximum wait for the publication series list to appear after opening a subcategory
CONSECUTIVE_FAILURE_LIMIT = 5  # A worker stops after this many failures in a row, because something systemic is wrong
BACKOFF_BASE_SECONDS = (
    5.0  # First pause after a failure; it doubles with every failure in a row
)
BACKOFF_MAX_SECONDS = 120.0  # The pause never grows beyond this
SUBCATEGORY_TIMEOUT_SECONDS = 300.0  # Hard limit for one whole visit, so a hung tab can never freeze a worker forever
RECORD_TIMEOUT_SECONDS = 30.0  # Hard limit for recording one response
HEADER_TIMEOUT_SECONDS = (
    10.0  # Hard limit for asking the browser for the raw headers of one request
)
DRAIN_TIMEOUT_SECONDS = (
    30.0  # How long to wait for unfinished recordings before moving on
)
MAX_RECORDED_BODY_BYTES = (
    50 * 1024 * 1024
)  # Bodies larger than this are logged but not stored
WRITER_QUEUE_SIZE = 200  # How many recorded responses may wait for the database; more makes recorders wait (limits memory use)
WRITER_BATCH_SIZE = (
    50  # How many recorded responses are saved in one database transaction
)
WRITER_FLUSH_INTERVAL_SECONDS = (
    0.5  # How long the writer collects responses before saving them
)
PROGRESS_INTERVAL_SECONDS = 60.0  # How often a progress line is logged
MIN_FREE_DISK_BYTES = (
    500 * 1024 * 1024
)  # The crawl stops cleanly when less disk space than this is left

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
# Pattern that matches the "view all" control; it must START the text so a publication title that merely contains these words is not clicked
VIEW_ALL_PATTERN = re.compile(
    r"^\s*(view\s+all|(\d+\s+)?all\s+(publications?|forms?))", re.IGNORECASE
)  # Match "00 ALL PUBLICATIONS" (the number is optional) or "view all" at the start, ignoring case
WAIT_FOR_RECORDING_SECONDS = 15.0  # After clicking "ALL PUBLICATIONS" the crawler waits at most this long for the GetPubsBySeriesView URL to be recorded, then moves on
PUBS_BY_SERIES_PATH = "GetPubsBySeriesView"  # Path part of the URL that the "ALL PUBLICATIONS" click must produce
AJAX_IDLE_SCRIPT = "() => !window.jQuery || window.jQuery.active === 0"  # JavaScript that is true when the page has no pending jQuery AJAX requests

current_worker_label: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_worker_label", default="main"
)  # Each worker task gets its own value


class WorkerLabelFilter(
    logging.Filter
):  # Adds a worker label to every log record that does not already have one
    def filter(self, record: logging.LogRecord) -> bool:  # Called for every log message
        if not hasattr(
            record, "worker"
        ):  # Records from callbacks carry their own label through "extra"
            record.worker = (
                current_worker_label.get()
            )  # Otherwise use the label of the task that is logging
        return True  # Keep the message


LOG_FORMAT = "%(asctime)s %(levelname)s [%(worker)s] %(name)s %(funcName)s:%(lineno)d %(message)s"  # Time, level, worker, logger, function, line and message
logger = logging.getLogger("epubs_crawler")  # Create a named logger for this script
background_tasks: set[
    asyncio.Task
] = set()  # Keeps small fire-and-forget tasks alive until they finish


class SiteBusyError(
    Exception
):  # Raised when the site answers with an error status such as 429 or 503
    pass  # No extra behavior needed


def configure_logging() -> Path:  # Send everything to a log file and the important lines to the console
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)  # Make sure the log folder exists
    log_file_path = (
        LOG_DIRECTORY / f"epubs_crawler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )  # One log file per run, named by start time
    formatter = logging.Formatter(LOG_FORMAT)  # One format for both destinations
    file_handler = logging.FileHandler(
        log_file_path, encoding="utf-8"
    )  # UTF-8 so odd characters in titles never break logging; every record is flushed immediately
    file_handler.setLevel(logging.DEBUG)  # The file receives everything
    file_handler.setFormatter(formatter)  # Apply the format
    file_handler.addFilter(
        WorkerLabelFilter()
    )  # Make the worker label available to the format string
    if hasattr(
        sys.stdout, "reconfigure"
    ):  # Text streams of Python 3.7 and newer can be reconfigured
        sys.stdout.reconfigure(
            errors="replace"
        )  # Never crash on characters the console cannot show
    console_handler = logging.StreamHandler(sys.stdout)  # Console destination
    console_handler.setLevel(
        CONSOLE_LOG_LEVEL
    )  # The console shows only the important lines
    console_handler.setFormatter(formatter)  # Apply the format
    console_handler.addFilter(
        WorkerLabelFilter()
    )  # Make the worker label available to the format string
    root_logger = (
        logging.getLogger()
    )  # The root logger also receives messages from asyncio and the warnings module
    root_logger.setLevel(logging.DEBUG)  # Let every message through to the handlers
    root_logger.addHandler(file_handler)  # Attach the file destination
    root_logger.addHandler(console_handler)  # Attach the console destination
    logging.captureWarnings(True)  # Send Python warnings into the log as well
    sys.excepthook = log_uncaught_exception  # Log crashes that nothing else catches
    return log_file_path  # Tell the caller where the log file is


def log_uncaught_exception(
    exception_type, exception_value, exception_traceback
) -> None:  # Called by Python for exceptions that end the program
    if issubclass(exception_type, KeyboardInterrupt):  # Ctrl+C is not a bug
        sys.__excepthook__(
            exception_type, exception_value, exception_traceback
        )  # Use the normal behavior
        return  # Nothing more to do
    logger.critical(
        "Uncaught exception",
        exc_info=(exception_type, exception_value, exception_traceback),
    )  # Write the full traceback to the log


def log_asyncio_exception(
    loop: asyncio.AbstractEventLoop, context: dict
) -> None:  # Called by asyncio for errors that nobody handled
    exception = context.get("exception")  # The exception object, if there is one
    logger.error(
        "Unhandled asyncio error: %s", context.get("message"), exc_info=exception
    )  # Write it to the log with its traceback


def log_environment() -> None:  # Record facts about the machine and settings at the top of the log
    try:  # The package metadata might be missing
        playwright_version = importlib.metadata.version(
            "playwright"
        )  # Installed Playwright version
    except importlib.metadata.PackageNotFoundError:  # If the version cannot be read
        playwright_version = "unknown"  # Say so
    logger.info(
        "Python %s | Playwright %s | %s",
        sys.version.split()[0],
        playwright_version,
        platform.platform(),
    )  # Versions and operating system
    logger.info(
        "Workers=%d navigation_concurrency=%d max_attempts=%d",
        WORKER_COUNT,
        NAVIGATION_CONCURRENCY,
        MAX_ATTEMPTS,
    )  # Main settings
    logger.info(
        "Database=%s profile=%s", DATABASE_FILE_PATH, BROWSER_PROFILE_DIRECTORY
    )  # Where the data lives
    free_bytes = shutil.disk_usage(BASE_DIRECTORY).free  # Free disk space
    logger.info("Free disk space: %.1f GB", free_bytes / 1024**3)  # Log it
    if free_bytes < MIN_FREE_DISK_BYTES:  # If there is hardly any space
        logger.warning(
            "Very little free disk space, the crawl will stop as soon as the monitor notices"
        )  # Warn early


def acquire_single_instance_lock(
    lock_file_path: Path,
):  # Make sure only one copy of the script runs against state.db and the browser profile
    lock_file = open(
        lock_file_path, "a+"
    )  # Open (or create) the lock file and keep the handle open for the whole run
    try:  # Locking fails when another copy holds the lock
        if os.name == "nt":  # Windows uses msvcrt for file locks
            import msvcrt  # Windows-only standard library package

            msvcrt.locking(
                lock_file.fileno(), msvcrt.LK_NBLCK, 1
            )  # Try to lock one byte without waiting
        else:  # Linux and macOS use fcntl for file locks
            import fcntl  # Unix-only standard library package

            fcntl.flock(
                lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB
            )  # Try to lock the file without waiting
    except OSError:  # If somebody else holds the lock
        lock_file.close()  # Release our handle
        raise SystemExit(
            "Another copy of the crawler is already running; stop it first"
        )  # Refuse to start
    return lock_file  # The caller keeps this object alive; the lock disappears when the process ends


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
    started_at: str  # When the request started, as an ISO timestamp
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


@dataclass  # Generate the constructor automatically
class CrawlState:  # Things every worker shares
    stop_event: asyncio.Event  # Set when the crawl should wind down (Ctrl+C, browser closed, disk full)
    navigation_gate: asyncio.Semaphore  # Limits how many tabs load the index page at once
    context_closed: bool = False  # True once the browser window is gone


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
            database_file_path, timeout=30
        )  # Open (or create) the single database file; wait up to 30 seconds if it is busy
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
        self.connection.execute(
            "PRAGMA foreign_keys=ON"
        )  # Make the database refuse rows that point to missing parents
        self.create_tables()  # Make sure all tables, columns and indexes exist
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
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_subcategories_status ON subcategories(status)"
            )  # Makes claiming work fast when there are many subcategories
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_network_entries_run ON network_entries(run_id, entry_id)"
            )  # Makes the HAR export of one run fast

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
            cursor = self.connection.execute(
                "UPDATE subcategories SET status = ? WHERE status = ?",
                (STATUS_PENDING, STATUS_IN_PROGRESS),
            )  # Unclaim subcategories
            if cursor.rowcount:  # Only mention it when something was recovered
                logger.warning(
                    "Recovered %d subcategories left in progress by a crashed run",
                    cursor.rowcount,
                )  # Log the recovery
            self.connection.execute(
                "UPDATE categories SET listing_status = ? WHERE listing_status IN (?, ?)",
                (LISTING_UNLISTED, LISTING_IN_PROGRESS, LISTING_FAILED),
            )  # Unclaim categories whose listing was interrupted or failed

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
        visited_count = self.connection.execute(
            "SELECT COUNT(*) FROM subcategories WHERE last_run_id = ? AND status IN (?, ?)",
            (run_id, STATUS_VIEWED_ALL, STATUS_NO_VIEW_ALL),
        ).fetchone()[
            0
        ]  # Count subcategories this run visited successfully
        failed_count = self.connection.execute(
            "SELECT COUNT(*) FROM subcategories WHERE last_run_id = ? AND status = ?",
            (run_id, STATUS_FAILED),
        ).fetchone()[
            0
        ]  # Count subcategories this run failed on
        with self.connection:  # Save the change immediately
            self.connection.execute(
                "UPDATE crawl_runs SET finished_at = ?, subcategories_visited = ?, subcategories_failed = ? WHERE run_id = ?",
                (current_utc_timestamp(), visited_count, failed_count, run_id),
            )  # Update the run row

    def save_network_entries(
        self, run_id: int, items: list[tuple[str, NetworkEntry]]
    ) -> None:  # Store a batch of requests and responses in ONE transaction (one disk flush instead of one per response)
        with self.connection:  # Save the whole batch together
            for worker_label, entry in items:  # Loop over the batch
                body_hash = (
                    hashlib.sha256(entry.body).hexdigest() if entry.body else None
                )  # Fingerprint the body so duplicates are stored once
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
        skipped_count = 0  # Count the entries that could not be converted
        temporary_path = har_file_path.with_name(
            har_file_path.name + ".tmp"
        )  # Write to a temporary file first so a crash never leaves a half-written HAR behind
        with temporary_path.open(
            "w", encoding="utf-8"
        ) as har_file:  # Open the temporary file for writing
            har_file.write(
                '{"log": {"version": "1.2", "creator": {"name": "epubs_crawler", "version": "1.1"}, "pages": [], "entries": ['
            )  # Start of the HAR document
            cursor = self.connection.execute(
                "SELECT e.*, b.body AS body FROM network_entries AS e LEFT JOIN network_bodies AS b ON b.body_hash = e.body_hash WHERE e.run_id = ? ORDER BY e.entry_id",
                (run_id,),
            )  # Read the run's entries in order, without loading them all at once
            for row in cursor:  # Handle one row at a time so memory use stays flat
                try:  # One bad row must not ruin the whole file
                    entry_text = json.dumps(build_har_entry(row))  # Convert the row
                except Exception:  # Any problem with this row
                    skipped_count += 1  # Count it
                    logger.exception(
                        "Skipped network entry %s in the HAR export", row["entry_id"]
                    )  # Log which one
                    continue  # Go on with the next row
                if entry_count > 0:  # Entries after the first need a separating comma
                    har_file.write(",")  # Write the separator
                har_file.write(entry_text)  # Write the entry straight to disk
                entry_count += 1  # Count it
            har_file.write("]}}")  # End of the HAR document
            har_file.flush()  # Push Python's buffer to the operating system
            os.fsync(har_file.fileno())  # Force the data onto the disk
        os.replace(
            temporary_path, har_file_path
        )  # Swap the finished file into place in one atomic step
        if skipped_count:  # Mention problems once more at the end
            logger.warning(
                "%d entries were skipped while writing %s", skipped_count, har_file_path
            )  # Log the total
        return entry_count  # Tell the caller how many entries were written

    def export_missing_har_files(
        self,
    ) -> None:  # Rebuild HAR files of earlier runs that were killed before they could export
        rows = self.connection.execute(
            "SELECT run_id, har_file_path FROM crawl_runs WHERE har_file_path IS NOT NULL AND run_id IN (SELECT DISTINCT run_id FROM network_entries)"
        ).fetchall()  # Runs with a HAR path and recorded entries
        for row in rows:  # Loop over those runs
            har_file_path = Path(row["har_file_path"])  # The expected HAR file
            if not har_file_path.exists():  # If the file was never written
                try:  # A failed rebuild must not stop the new run
                    entry_count = self.export_har(
                        row["run_id"], har_file_path
                    )  # Write it now from the database
                    logger.info(
                        "Rebuilt %s from the database (%d entries)",
                        har_file_path,
                        entry_count,
                    )  # Log the rebuild
                except Exception:  # Any problem while rebuilding
                    logger.exception(
                        "Could not rebuild %s", har_file_path
                    )  # Log it and move on

    def save_categories(
        self, categories: list[Category]
    ) -> None:  # Remember every category found on the index page
        unique_categories: dict[int, Category] = {}  # One entry per category id
        for category in categories:  # Loop over everything that was found
            if (
                category.category_id in unique_categories
            ):  # The same id appeared twice on the page
                logger.warning(
                    "Category id %d appears more than once (%s and %s)",
                    category.category_id,
                    unique_categories[category.category_id].category_name,
                    category.category_name,
                )  # Warn about it
            unique_categories[category.category_id] = category  # Keep the latest one
        rows = [
            (c.category_id, c.menu_title, c.category_name, current_utc_timestamp())
            for c in unique_categories.values()
        ]  # Build one row per category
        with self.connection:  # Save all rows in one transaction
            self.connection.executemany(  # Insert new categories and refresh names of known ones
                "INSERT INTO categories (category_id, menu_title, category_name, discovered_at) VALUES (?, ?, ?, ?) "  # Insert part
                "ON CONFLICT(category_id) DO UPDATE SET menu_title = excluded.menu_title, category_name = excluded.category_name",  # Update part
                rows,  # All the rows
            )  # End of the insert

    def category_count(self) -> int:  # Count the categories the database knows
        return int(
            self.connection.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        )  # Read the single number

    def claim_next_category_to_list(
        self,
    ) -> Category | None:  # Give one worker a category whose subcategories are not known yet
        with self.connection:  # Pick and claim in one transaction so two workers can never get the same category
            row = self.connection.execute(
                "SELECT category_id, menu_title, category_name FROM categories WHERE listing_status = ? ORDER BY rowid LIMIT 1",
                (LISTING_UNLISTED,),
            ).fetchone()  # Find the next unlisted category
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
        unique_subcategories = {
            s.organization_id: s for s in subcategories
        }  # One entry per organization id
        rows = [
            (category.category_id, s.organization_id, s.subcategory_name)
            for s in unique_subcategories.values()
        ]  # Build one row per subcategory
        with self.connection:  # Save everything in one transaction
            self.connection.executemany(  # Insert subcategories and refresh the names of known ones
                "INSERT INTO subcategories (category_id, organization_id, subcategory_name) VALUES (?, ?, ?) "  # Insert part
                "ON CONFLICT(category_id, organization_id) DO UPDATE SET subcategory_name = excluded.subcategory_name",  # Update part
                rows,  # All the rows
            )  # End of the insert
            self.connection.execute(
                "UPDATE categories SET listing_status = ?, subcategory_count = ? WHERE category_id = ?",
                (LISTING_LISTED, len(unique_subcategories), category.category_id),
            )  # Mark the category as fully listed

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
            self.connection.execute(
                "UPDATE subcategories SET status = ? WHERE category_id = ? AND organization_id = ?",
                (STATUS_PENDING, category.category_id, subcategory.organization_id),
            )  # Unclaim the subcategory

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
            self.connection.execute(
                "UPDATE subcategories SET status = ?, worker_id = ?, last_run_id = ? WHERE category_id = ? AND organization_id = ?",
                (
                    STATUS_IN_PROGRESS,
                    worker_id,
                    run_id,
                    row["category_id"],
                    row["organization_id"],
                ),
            )  # Claim the subcategory for this worker
        category = Category(
            row["menu_title"], row["category_id"], row["category_name"]
        )  # Build the category object
        return category, Subcategory(
            row["organization_id"], row["subcategory_name"]
        )  # Hand both objects to the worker

    def has_work_in_progress(
        self,
    ) -> bool:  # Check whether other workers are still busy and may create more work
        in_progress_count = self.connection.execute(
            "SELECT (SELECT COUNT(*) FROM subcategories WHERE status = ?) + (SELECT COUNT(*) FROM categories WHERE listing_status = ?)",
            (STATUS_IN_PROGRESS, LISTING_IN_PROGRESS),
        ).fetchone()[
            0
        ]  # Count claimed subcategories and categories
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

    def progress_text(self) -> str:  # One line describing how far the crawl has come
        status_rows = self.connection.execute(
            "SELECT status, COUNT(*) AS total FROM subcategories GROUP BY status"
        ).fetchall()  # Count per status
        unlisted_total = self.connection.execute(
            "SELECT COUNT(*) FROM categories WHERE listing_status != ?",
            (LISTING_LISTED,),
        ).fetchone()[
            0
        ]  # Categories whose subcategories are still unknown
        status_text = (
            ", ".join(f"{row['status']}={row['total']}" for row in status_rows)
            or "no subcategories yet"
        )  # Join the counts
        return f"subcategories: {status_text} | categories not listed: {unlisted_total}"  # Build the line

    def log_summary(self) -> None:  # Print an overview of everything stored so far
        logger.info("---- Crawl summary (all runs) ----")  # Heading
        status_rows = self.connection.execute(
            "SELECT status, COUNT(*) AS total FROM subcategories GROUP BY status"
        ).fetchall()  # Count per status
        for status_row in status_rows:  # Loop over the statuses
            logger.info(
                "Subcategories %-12s: %d", status_row["status"], status_row["total"]
            )  # Log one line per status
        logger.info(
            "Categories known       : %d", self.category_count()
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
        entry_total = self.connection.execute(
            "SELECT COUNT(*) FROM network_entries"
        ).fetchone()[
            0
        ]  # Count recorded responses
        body_total = self.connection.execute(
            "SELECT COUNT(*) FROM network_bodies"
        ).fetchone()[
            0
        ]  # Count distinct stored bodies
        logger.info(
            "Network entries stored : %d (%d distinct bodies)", entry_total, body_total
        )  # Log the traffic totals
        gave_up_rows = self.connection.execute(
            "SELECT category_id, subcategory_name, last_error FROM subcategories WHERE status = ? AND attempts >= ?",
            (STATUS_FAILED, self.max_attempts),
        ).fetchall()  # Find subcategories that used up all their attempts
        for gave_up_row in gave_up_rows:  # Loop over the failures
            logger.warning(
                "Gave up on category %s > %s: %s",
                gave_up_row["category_id"],
                gave_up_row["subcategory_name"],
                gave_up_row["last_error"],
            )  # Log each

    def close(self) -> None:  # Close the database file
        self.connection.close()  # Release the file


class NetworkWriter:  # Collects recorded responses from all tabs and saves them in batches, so the event loop is not blocked by one disk flush per response
    def __init__(
        self, database: CrawlDatabase, run_id: int
    ) -> None:  # Prepare the queue
        self.database = database  # The database that receives the batches
        self.run_id = run_id  # The run the entries belong to
        self.queue: asyncio.Queue[tuple[str, NetworkEntry] | None] = asyncio.Queue(
            maxsize=WRITER_QUEUE_SIZE
        )  # Bounded, so a slow disk slows the recorders instead of filling the memory
        self.task: asyncio.Task | None = None  # The background task that saves batches
        self.closed = False  # True once no more entries are accepted
        self.saved_count = 0  # How many entries reached the database
        self.lost_count = 0  # How many entries could not be saved

    def start(self) -> None:  # Start the background task
        self.task = asyncio.create_task(
            self.run(), name="network-writer"
        )  # Run the saving loop

    async def add(
        self, worker_label: str, entry: NetworkEntry
    ) -> None:  # Hand one recorded response to the writer
        if self.closed:  # Too late, the writer has already been shut down
            self.lost_count += 1  # Count it
            logger.warning(
                "Dropped a response recorded after shutdown: %s", entry.url
            )  # Say which one
            return  # Nothing more to do
        await self.queue.put(
            (worker_label, entry)
        )  # Wait for room in the queue if it is full

    async def run(self) -> None:  # The saving loop
        finished = False  # Becomes True when the shutdown marker arrives
        while not finished:  # Keep going until told to stop
            first_item = (
                await self.queue.get()
            )  # Wait for the first response of the next batch
            if first_item is None:  # The shutdown marker
                break  # Stop now
            batch = [first_item]  # Start the batch
            await asyncio.sleep(
                WRITER_FLUSH_INTERVAL_SECONDS
            )  # Let more responses pile up so one transaction can save many
            while len(batch) < WRITER_BATCH_SIZE:  # Fill the batch without waiting
                try:  # The queue may be empty
                    next_item = (
                        self.queue.get_nowait()
                    )  # Take the next response if there is one
                except asyncio.QueueEmpty:  # Nothing more right now
                    break  # Save what we have
                if next_item is None:  # The shutdown marker arrived inside the batch
                    finished = True  # Stop after saving this batch
                    break  # Save what we have
                batch.append(next_item)  # Add it to the batch
            self.save_batch(batch)  # Write the batch to the database

    def save_batch(
        self, batch: list[tuple[str, NetworkEntry]]
    ) -> None:  # Save one batch and never let a failure kill the writer
        try:  # Try the fast way first
            self.database.save_network_entries(
                self.run_id, batch
            )  # One transaction for the whole batch
            self.saved_count += len(batch)  # Count the saved entries
            logger.debug("Saved a batch of %d network entries", len(batch))  # Log it
            return  # Done
        except Exception:  # Something in the batch made the transaction fail
            logger.exception(
                "Saving a batch of %d entries failed, retrying them one by one",
                len(batch),
            )  # Log the problem
        for item in batch:  # Retry each entry alone to find the bad one
            try:  # One entry at a time
                self.database.save_network_entries(
                    self.run_id, [item]
                )  # Save just this entry
                self.saved_count += 1  # Count it
            except Exception:  # This entry is the problem
                self.lost_count += 1  # Count the loss
                logger.exception(
                    "Could not save the network entry for %s", item[1].url
                )  # Say which one

    async def close(
        self,
    ) -> None:  # Save everything that is still waiting and stop the background task
        self.closed = True  # Refuse new entries from now on
        if self.task is None:  # The writer was never started
            return  # Nothing to do
        if not self.task.done():  # The task is still running
            try:  # The queue could be full if the task is stuck
                await asyncio.wait_for(
                    self.queue.put(None), timeout=DRAIN_TIMEOUT_SECONDS
                )  # Send the shutdown marker
                await asyncio.wait_for(
                    self.task, timeout=DRAIN_TIMEOUT_SECONDS * 2
                )  # Wait for the last batch to be saved
            except Exception:  # Timeout or any other problem
                logger.exception(
                    "The network writer did not shut down cleanly"
                )  # Report it
        logger.info(
            "Network writer finished: %d saved, %d lost",
            self.saved_count,
            self.lost_count,
        )  # Log the totals


class WorkerTab:  # One worker's browser tab, which can be replaced when it crashes or hangs
    def __init__(
        self, worker_id: int, context: BrowserContext, writer: NetworkWriter
    ) -> None:  # Prepare the tab holder
        self.worker_id = worker_id  # Number of the worker, starting at 1
        self.label = f"worker {worker_id}"  # Label used in logs and in the HAR file
        self.context = context  # The shared Chromium window
        self.writer = writer  # Where recorded responses go
        self.page: Page | None = None  # The current tab
        self.crashed = False  # True when Chromium reported that this tab crashed
        self.dirty = False  # True when the tab should be replaced before the next visit
        self.pending: set[
            asyncio.Task
        ] = set()  # Recordings that are still being processed for this tab
        self.recorded_urls: list[
            str
        ] = []  # URLs this tab has handed to the writer during the current visit
        self.log = logging.LoggerAdapter(
            logger, {"worker": self.label}
        )  # Logger that always shows this worker's label

    async def open(self) -> None:  # Open a fresh tab
        self.page = await self.context.new_page()  # Ask Chromium for a new tab
        self.crashed = False  # A fresh tab has not crashed
        self.dirty = False  # A fresh tab is clean
        attach_debug_listeners(
            self, self.page
        )  # Start logging and recording this tab's traffic
        self.log.debug("Opened a fresh tab")  # Log it

    def needs_replacement(
        self,
    ) -> bool:  # Decide whether the tab must be replaced before the next visit
        return (
            self.page is None or self.page.is_closed() or self.crashed or self.dirty
        )  # Missing, closed, crashed or suspicious

    async def replace(self) -> None:  # Throw the old tab away and open a new one
        old_page = self.page  # Remember the old tab
        self.page = None  # Mark the holder as empty
        await self.drain()  # Let recordings of the old tab finish first
        if (
            old_page is not None and not old_page.is_closed()
        ):  # If the old tab is still open
            try:  # Closing can fail on a crashed tab
                await old_page.close()  # Close it
            except PlaywrightError:  # Ignore errors while closing
                self.log.debug(
                    "Could not close the old tab cleanly", exc_info=True
                )  # Log them quietly
        await self.open()  # Open the replacement

    async def drain(
        self,
    ) -> None:  # Wait until every response of this tab has been recorded
        pending = list(
            self.pending
        )  # Copy the set because tasks remove themselves from it
        if not pending:  # Nothing to wait for
            return  # Done
        _, still_pending = await asyncio.wait(
            pending, timeout=DRAIN_TIMEOUT_SECONDS
        )  # Wait, but not forever
        for task in still_pending:  # Anything that is still running is stuck
            task.cancel()  # Cancel it
            self.log.warning(
                "A response recording did not finish in %.0f seconds and was cancelled",
                DRAIN_TIMEOUT_SECONDS,
            )  # Log it


async def interruptible_sleep(
    seconds: float, stop_event: asyncio.Event
) -> None:  # Sleep, but wake up early when the crawl is asked to stop
    try:  # The wait ends with a timeout when nobody stops the crawl
        await asyncio.wait_for(
            stop_event.wait(), timeout=seconds
        )  # Wait for the stop signal or the time limit
    except asyncio.TimeoutError:  # The normal case: the sleep simply ran out
        pass  # Nothing to do


async def read_headers(
    read_all_headers, fallback_headers: dict[str, str], tab: WorkerTab, url: str
) -> dict[str, str]:  # Read raw headers, but never hang on them
    try:  # all_headers() can hang for some requests
        return await asyncio.wait_for(
            read_all_headers(), timeout=HEADER_TIMEOUT_SECONDS
        )  # Ask the browser, with a time limit
    except Exception:  # Timeout, closed tab or anything else
        tab.log.debug(
            "Raw headers unavailable for %s, using the basic headers",
            url,
            exc_info=True,
        )  # Log it quietly
        return dict(fallback_headers)  # Fall back to the headers Playwright already has


def read_post_data(
    request: Request,
) -> str | None:  # Read a request body without failing on binary data
    try:  # Binary bodies cannot always be decoded as text
        return request.post_data  # The body as text, or None when there is none
    except Exception:  # If the body is not valid text
        return None  # Record the request without a body


def should_record(
    response: Response,
) -> bool:  # Decide whether a response belongs in the database and the HAR file
    request = response.request  # The request that produced this response
    return (
        request.resource_type in RECORDED_RESOURCE_TYPES
        and response.url.lower().startswith(RECORDED_URL_PREFIX)
    )  # Only pages and AJAX calls of this site


async def record_network_response(
    response: Response, tab: WorkerTab
) -> None:  # Turn one response into a NetworkEntry and queue it for saving
    request = response.request  # The request that produced this response
    try:  # Recording must never break the crawl
        async with asyncio.timeout(
            RECORD_TIMEOUT_SECONDS
        ):  # Never let one recording hang forever
            body = b""  # Start with an empty body
            if (
                not 300 <= response.status < 400 and response.status != 204
            ):  # Redirects and "no content" responses have no body to read
                try:  # The body can disappear when the tab navigates away
                    body = await response.body()  # Read the response body
                except PlaywrightError as error:  # If the body is unavailable
                    tab.log.debug(
                        "Body unavailable for %s %s: %s",
                        response.status,
                        response.url,
                        error,
                    )  # Log why
            if len(body) > MAX_RECORDED_BODY_BYTES:  # Refuse to store giant bodies
                tab.log.warning(
                    "Body of %s is %d bytes, too large to store",
                    response.url,
                    len(body),
                )  # Log it
                body = b""  # Record the response without a body
            timing = request.timing  # Timing numbers of the request
            start_time_ms = timing.get(
                "startTime", 0
            )  # Request start in milliseconds since 1970
            response_end = timing.get(
                "responseEnd", -1
            )  # Milliseconds from the start of the request to the end of the response
            if (
                start_time_ms and start_time_ms > 0
            ):  # If the browser reported a start time
                started_at = datetime.fromtimestamp(
                    start_time_ms / 1000, tz=timezone.utc
                ).isoformat(
                    timespec="milliseconds"
                )  # Use the real start time
            else:  # Otherwise
                started_at = datetime.now(timezone.utc).isoformat(
                    timespec="milliseconds"
                )  # Use the time of recording
            request_headers = await read_headers(
                request.all_headers, request.headers, tab, response.url
            )  # Headers the browser sent
            response_headers = await read_headers(
                response.all_headers, response.headers, tab, response.url
            )  # Headers the server sent
            entry = NetworkEntry(  # Collect everything about this response
                started_at=started_at,  # When the request started
                duration_ms=float(response_end)
                if response_end and response_end > 0
                else 0.0,  # Request duration
                method=request.method,  # HTTP method
                url=response.url,  # URL
                resource_type=request.resource_type,  # document, xhr or fetch
                request_headers=request_headers,  # Headers the browser sent
                request_post_data=read_post_data(request),  # Request body, if any
                status=response.status,  # Status code
                status_text=response.status_text,  # Status text
                response_headers=response_headers,  # Headers the server sent
                mime_type=response_headers.get("content-type", ""),  # Content type
                body=body,  # Response body
            )  # End of the entry
        await tab.writer.add(tab.label, entry)  # Queue it for the database
        tab.recorded_urls.append(entry.url)  # Remember that this URL reached the writer
        tab.log.debug(
            "Recorded %s %s (status %s, %d body bytes)",
            entry.method,
            entry.url,
            entry.status,
            len(entry.body),
        )  # Log that it is in the HAR data
    except Exception:  # Any problem, including a closed tab or a timeout
        tab.log.warning(
            "Could not record the response for %s", response.url, exc_info=True
        )  # Report it and keep crawling


def attach_debug_listeners(
    tab: WorkerTab, page: Page
) -> None:  # Hook logging and recording into the page events
    tab.log.debug(
        "Attaching debug listeners to the page"
    )  # Log that the listeners are being attached

    def on_console(
        message: ConsoleMessage,
    ) -> None:  # Callback for text the web page prints to its console
        tab.log.debug(
            "Browser console [%s]: %s", message.type, message.text
        )  # Log the message type and text

    def on_page_error(
        error,
    ) -> None:  # Callback for uncaught JavaScript errors on the page
        tab.log.debug("Browser page error: %s", error)  # Log the error

    def on_request(
        request: Request,
    ) -> None:  # Callback for every outgoing network request
        tab.log.debug(
            "Request  -> %s %s (%s)", request.method, request.url, request.resource_type
        )  # Log the HTTP method, URL and type
        post_data = read_post_data(request)  # Read the body, if any
        if post_data:  # Only log bodies that exist
            tab.log.debug(
                "Request body for %s: %s", request.url, post_data[:1000]
            )  # Log the first part of it

    def on_request_failed(
        request: Request,
    ) -> None:  # Callback for requests that never got a response
        tab.log.warning(
            "Request FAILED %s %s: %s", request.method, request.url, request.failure
        )  # Log what went wrong

    def on_response(
        response: Response,
    ) -> None:  # Callback for every incoming network response; it must be a plain function so the tasks can be tracked
        tab.log.debug(
            "Response <- %s %s", response.status, response.url
        )  # Log the status code and the URL
        if not should_record(response):  # Skip fonts, images, scripts and other sites
            return  # Nothing to record
        task = asyncio.create_task(
            record_network_response(response, tab)
        )  # Record it in the background
        tab.pending.add(
            task
        )  # Remember it so the worker can wait for it before moving on
        task.add_done_callback(tab.pending.discard)  # Forget it when it is finished

    def on_frame_navigated(frame) -> None:  # Callback for every navigation
        if frame == page.main_frame:  # Only the top-level page is interesting
            tab.log.debug("Navigated to %s", frame.url)  # Log the new address

    def on_crash(
        _crashed_page: Page,
    ) -> None:  # Callback for a tab that Chromium killed
        tab.crashed = True  # Remember that this tab must be replaced
        tab.log.error("The tab CRASHED")  # Log it

    def on_page_close(_closed_page: Page) -> None:  # Callback for a tab that was closed
        tab.log.debug("The tab was closed")  # Log it

    async def on_dialog(
        dialog: Dialog,
    ) -> None:  # Callback for JavaScript alert, confirm and prompt boxes
        tab.log.warning(
            "Dialog [%s]: %s", dialog.type, dialog.message
        )  # Log what the page said
        try:  # Closing the dialog can fail if the tab is already gone
            await dialog.accept()  # Click OK so the page is not blocked forever
        except PlaywrightError:  # If the dialog vanished
            tab.log.debug("Could not close the dialog", exc_info=True)  # Log it quietly

    async def on_download(
        download: Download,
    ) -> None:  # Callback for downloads started by the page
        tab.log.warning("Download started and cancelled: %s", download.url)  # Log it
        try:  # Cancelling can fail if the download already ended
            await download.cancel()  # This crawler never saves files
        except PlaywrightError:  # If it could not be cancelled
            tab.log.debug(
                "Could not cancel the download", exc_info=True
            )  # Log it quietly

    page.on("console", on_console)  # Log the page's console output
    page.on("pageerror", on_page_error)  # Log JavaScript errors from the page
    page.on("request", on_request)  # Log every request
    page.on("requestfailed", on_request_failed)  # Log requests that failed
    page.on("response", on_response)  # Log and record every response
    page.on("framenavigated", on_frame_navigated)  # Log navigations
    page.on("crash", on_crash)  # Notice crashed tabs
    page.on("close", on_page_close)  # Log closed tabs
    page.on("dialog", on_dialog)  # Close dialogs so they cannot block the page
    page.on("download", on_download)  # Cancel downloads


async def close_if_popup(
    page: Page,
) -> None:  # Close any tab that a page opened by itself
    try:  # The tab may already be gone
        opener = await page.opener()  # Tabs we open ourselves have no opener
        if opener is not None:  # This tab was opened by another tab
            logger.warning("Closing an unexpected popup tab: %s", page.url)  # Log it
            await page.close()  # Close it
    except PlaywrightError:  # If the tab disappeared meanwhile
        logger.debug("Could not inspect a new tab", exc_info=True)  # Log it quietly


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
            AJAX_IDLE_SCRIPT, timeout=AJAX_TIMEOUT_MS
        )  # Wait for zero pending requests
        await page.wait_for_timeout(
            AJAX_SETTLE_MS
        )  # Give a follow-up request the chance to start
        await page.wait_for_function(
            AJAX_IDLE_SCRIPT, timeout=AJAX_TIMEOUT_MS
        )  # Check again, because the first request may have started a second one
        logger.debug("No AJAX requests are pending")  # Log that the wait finished
    except PlaywrightTimeoutError:  # If requests were still pending
        logger.info(
            "AJAX requests did not finish within the timeout, continuing anyway"
        )  # Report it and keep going


async def open_product_index(
    page: Page, state: CrawlState
) -> None:  # Load the starting page in one tab, retrying when the slow site times out or answers with an error
    for attempt_number in range(
        1, NAVIGATION_ATTEMPTS + 1
    ):  # Try a limited number of times
        logger.debug(
            "Opening %s (attempt %d of %d)",
            PRODUCT_INDEX_URL,
            attempt_number,
            NAVIGATION_ATTEMPTS,
        )  # Log the navigation
        try:  # A failure here usually means the site is busy
            async with state.navigation_gate:  # Only a few tabs may load the index page at the same moment
                response = await page.goto(
                    PRODUCT_INDEX_URL,
                    wait_until="domcontentloaded",
                    timeout=NAVIGATION_TIMEOUT_MS,
                )  # Navigate to the Product Index page
            if (
                response is not None and response.status >= 400
            ):  # The site answered, but with an error such as 429 or 503
                raise SiteBusyError(
                    f"The site answered HTTP {response.status} for the Product Index page"
                )  # Treat it like a failed load
            await page.locator(".main-nav h4").first.wait_for(
                state="visible", timeout=ACTION_TIMEOUT_MS
            )  # Wait for the headings
            await page.wait_for_function(
                "() => typeof epubs !== 'undefined'", timeout=ACTION_TIMEOUT_MS
            )  # Wait until the page's click handlers exist
            break  # The page is ready, so stop retrying
        except (
            PlaywrightError,
            SiteBusyError,
        ) as error:  # If the load failed in a way that may be temporary
            if (
                page.is_closed() or attempt_number == NAVIGATION_ATTEMPTS
            ):  # A closed tab cannot be retried, and the last attempt is final
                raise  # Give up and let the caller record the failure
            retry_delay = (
                NAVIGATION_RETRY_DELAY_SECONDS * attempt_number
            )  # Wait longer after every failed attempt
            logger.warning(
                "Page load failed (%s), retrying in %.1f seconds", error, retry_delay
            )  # Tell the user
            await interruptible_sleep(
                retry_delay, state.stop_event
            )  # Pause before the next attempt
    await log_current_page(page)  # Log where we ended up


async def collect_categories(
    page: Page,
) -> list[Category]:  # List every category under both headings
    categories: list[Category] = []  # Start with an empty list
    for menu_title in TOP_LEVEL_MENU_TITLES:  # Loop over "Publications" and "Forms"
        links_xpath = f"//div[contains(@class,'main-nav')]//h4[normalize-space()='{menu_title}']/following-sibling::ul[1]//a"  # Links under this heading
        link_data = await page.locator(f"xpath={links_xpath}").evaluate_all(
            "links => links.map(l => [l.getAttribute('onclick') || '', (l.textContent || '').split(/\\s+/).join(' ').trim()])"
        )  # Read every link in ONE step, so the page cannot change between reads
        logger.debug(
            "Found %d category links under %s", len(link_data), menu_title
        )  # Log the count
        for onclick_text, category_name in link_data:  # Loop over the links
            match = CATEGORY_ID_PATTERN.search(
                onclick_text
            )  # Pull the category id out of the onclick text
            if match is None:  # If the id could not be found
                logger.warning(
                    "Could not read a category id from: %s", onclick_text
                )  # Warn about it
                continue  # Skip this link
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
    await wait_for_ajax_to_finish(
        page
    )  # The subcategory list may be filled in by AJAX, so wait before reading it
    logger.debug(
        "Category pane #cat-%d is visible", category.category_id
    )  # Log that the pane opened


async def collect_subcategories(
    page: Page, category: Category
) -> list[Subcategory]:  # List the subcategories of the open category
    link_data = await page.locator(
        f"#cat-{category.category_id} a[onclick*='SelectOrg']"
    ).evaluate_all(
        "links => links.map(l => [l.getAttribute('onclick') || '', (l.textContent || '').split(/\\s+/).join(' ').trim()])"
    )  # Read every link in ONE step
    if not link_data:  # Having no subcategories is normal
        logger.info(
            "No subcategories in #cat-%d (this is normal), moving on",
            category.category_id,
        )  # Log it calmly
        return []  # Return an empty list so the caller moves on
    logger.debug(
        "Found %d subcategory links in #cat-%d", len(link_data), category.category_id
    )  # Log the count
    subcategories: list[Subcategory] = []  # Start with an empty list
    for onclick_text, subcategory_name in link_data:  # Loop over the links
        match = ORGANIZATION_ID_PATTERN.search(
            onclick_text
        )  # Pull the organization id out of the onclick text
        if match is None:  # If the id could not be found
            logger.warning(
                "Could not read an organization id from: %s", onclick_text
            )  # Warn about it
            continue  # Skip this link
        subcategories.append(
            Subcategory(int(match.group(1)), subcategory_name)
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


def is_all_publications_url(
    url: str, organization_id: int, category_id: int
) -> bool:  # Check for a URL like .../GetPubsBySeriesView/?orgID=10141&catID=1&series=-1
    parts = urlsplit(url)  # Split the URL into path and query
    if (
        PUBS_BY_SERIES_PATH.lower() not in parts.path.lower()
    ):  # The path must contain GetPubsBySeriesView
        return False  # Not the URL we are looking for
    query = {
        name.lower(): value for name, value in parse_qsl(parts.query)
    }  # Query parameters with lower-case names, so the order and the capitals do not matter
    return (
        query.get("orgid") == str(organization_id)
        and query.get("catid") == str(category_id)
        and query.get("series") == "-1"
    )  # Right organization, right category and series -1 (all publications)


async def click_view_all_publications(
    tab: WorkerTab, category: Category, subcategory: Subcategory
) -> bool:  # Click "00 ALL PUBLICATIONS", wait until the GetPubsBySeriesView URL is recorded (at most 15 seconds) and leave
    page = tab.page  # The tab of this worker
    logger.debug(
        "Looking for the 'ALL PUBLICATIONS' control inside #org-list and #pub-list"
    )  # Log what we are looking for
    view_all_control = (
        page.locator("#org-list, #pub-list").get_by_text(VIEW_ALL_PATTERN).first
    )  # Find the control
    try:  # The control is legitimately missing on some pages
        await view_all_control.wait_for(
            state="visible", timeout=VIEW_ALL_TIMEOUT_MS
        )  # Wait for it to show up
    except PlaywrightTimeoutError:  # If it never showed up
        logger.debug("'ALL PUBLICATIONS' control was not found")  # Log the miss
        return False  # Tell the caller nothing was clicked
    control_text = " ".join(
        (await view_all_control.inner_text(timeout=ACTION_TIMEOUT_MS)).split()
    )  # Read the control's text so the log shows exactly what was clicked
    logger.debug("Clicking the control with text: %s", control_text[:200])  # Log it
    await view_all_control.click(timeout=ACTION_TIMEOUT_MS)  # Click it
    loop = asyncio.get_running_loop()  # The event loop, used for its clock
    deadline = loop.time() + WAIT_FOR_RECORDING_SECONDS  # The moment the waiting ends
    while True:  # Keep checking until the URL is recorded or the time is up
        recorded_url = next(
            (
                url
                for url in tab.recorded_urls
                if is_all_publications_url(
                    url, subcategory.organization_id, category.category_id
                )
            ),
            None,
        )  # Look for the GetPubsBySeriesView URL among the recorded ones
        if recorded_url is not None:  # It was recorded
            logger.info(
                "Recorded %s", recorded_url
            )  # Log the exact URL that went into the HAR data
            break  # Go to the next subcategory
        if loop.time() >= deadline or state_stop_requested(
            tab
        ):  # Out of time (or the crawl is stopping)
            logger.warning(
                "GetPubsBySeriesView (orgID=%d, catID=%d, series=-1) was NOT recorded within %.0f seconds, moving on",
                subcategory.organization_id,
                category.category_id,
                WAIT_FOR_RECORDING_SECONDS,
            )  # Warn, then move on
            break  # Go to the next subcategory
        await asyncio.sleep(0.1)  # Check again in a moment
    return True  # The click worked, so the visit is complete


def state_stop_requested(
    tab: WorkerTab,
) -> bool:  # True when the tab is gone, so waiting is pointless
    return (
        tab.page is None or tab.page.is_closed() or tab.crashed
    )  # Closed or crashed tabs will never record anything


async def crawl_subcategory(
    tab: WorkerTab, category: Category, subcategory: Subcategory, state: CrawlState
) -> bool:  # Visit one full path and report if "ALL PUBLICATIONS" was clicked
    page = tab.page  # The tab of this worker
    path_text = f"{category.menu_title} > {category.category_name} > {subcategory.subcategory_name}"  # Readable path
    logger.debug("Crawling: %s", path_text)  # Log the full path
    tab.recorded_urls.clear()  # Forget the URLs of the previous visit
    await open_product_index(page, state)  # Start from a clean index page
    await click_category(page, category)  # Go into the category
    await click_subcategory(page, category, subcategory)  # Go into the subcategory
    viewed_all = await click_view_all_publications(
        tab, category, subcategory
    )  # Click "ALL PUBLICATIONS" if it exists
    if viewed_all:  # If the click worked
        logger.info("Viewed all: %s", path_text)  # Log success
    else:  # If the control was not found
        logger.info(
            "No 'ALL PUBLICATIONS' control (this is normal), moving on: %s", path_text
        )  # Log it calmly
    return viewed_all  # Tell the caller what happened


async def list_category(
    tab: WorkerTab, category: Category, database: CrawlDatabase, state: CrawlState
) -> bool:  # Read and store the subcategories of one category; True means success
    settled = False  # Becomes True once the database knows how this category ended
    try:  # A problem in one category must not stop the whole crawl
        async with asyncio.timeout(
            SUBCATEGORY_TIMEOUT_SECONDS
        ):  # Never let one category hang forever
            await open_product_index(
                tab.page, state
            )  # Load the index page in this worker's tab
            await click_category(tab.page, category)  # Open the category
            subcategories = await collect_subcategories(
                tab.page, category
            )  # Read its subcategories
        await tab.drain()  # Make sure the traffic of this visit is recorded before the tab moves on
        database.save_subcategories(category, subcategories)  # Remember them
        settled = True  # The database now holds the result
        logger.info(
            "Listed %s > %s (%d subcategories)",
            category.menu_title,
            category.category_name,
            len(subcategories),
        )  # Log success
        return True  # Report success
    except Exception as error:  # Playwright errors, timeouts and anything unexpected
        tab.dirty = True  # Replace the tab before using it again
        if (
            tab.page is None or tab.page.is_closed() or state.stop_event.is_set()
        ):  # If the tab or browser was closed, the category is not at fault
            logger.warning(
                "Listing interrupted because the tab or browser is gone: %s",
                category.category_name,
            )  # Log it; the finally block gives the category back
            return False  # Report that this did not work
        logger.exception(
            "Could not list category: %s > %s",
            category.menu_title,
            category.category_name,
        )  # Log with traceback
        database.mark_listing_failed(
            category
        )  # Remember the failure so it is retried on the next run
        settled = True  # The database now knows about the failure
        logger.debug(
            "Listing failure type: %s", type(error).__name__
        )  # Log the kind of error
        return False  # Report failure
    finally:  # Runs on success, failure, cancellation and crashes alike
        if not settled:  # If nothing recorded the outcome
            database.release_category(
                category
            )  # Give the category back so nobody is stuck waiting for it


async def run_worker(
    tab: WorkerTab, database: CrawlDatabase, run_id: int, state: CrawlState
) -> None:  # One worker that keeps asking the database for work
    current_worker_label.set(tab.label)  # Tag every log line of this worker
    await interruptible_sleep(
        (tab.worker_id - 1) * WORKER_START_STAGGER_SECONDS, state.stop_event
    )  # Start later than the previous worker
    logger.info("Worker started")  # Log the start
    consecutive_failures = 0  # Count failures in a row to detect a systemic problem
    while (
        not state.stop_event.is_set()
    ):  # Keep going until the database has no work left or the crawl is told to stop
        if (
            consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT
        ):  # If everything keeps failing
            logger.error(
                "%d failures in a row, stopping this worker so attempts are not wasted",
                consecutive_failures,
            )  # Explain why
            break  # Stop this worker
        if consecutive_failures > 0:  # After a failure, give the site some room
            backoff_seconds = min(
                BACKOFF_MAX_SECONDS,
                BACKOFF_BASE_SECONDS * 2 ** (consecutive_failures - 1),
            )  # Double the pause with every failure in a row
            logger.info(
                "Backing off for %.0f seconds after %d failure(s) in a row",
                backoff_seconds,
                consecutive_failures,
            )  # Log it
            await interruptible_sleep(backoff_seconds, state.stop_event)  # Wait
            if state.stop_event.is_set():  # The crawl was stopped while waiting
                break  # Leave the loop
        if (
            tab.needs_replacement()
        ):  # If the tab crashed, was closed or looks suspicious
            logger.info("Replacing this worker's tab")  # Log it
            try:  # Opening a tab fails when the whole browser is gone
                await tab.replace()  # Throw the old tab away and open a new one
            except Exception:  # The browser is probably gone
                logger.exception(
                    "Could not open a replacement tab, stopping this worker"
                )  # Log it
                break  # Stop this worker
        claimed_subcategory = database.claim_next_subcategory(
            tab.worker_id, run_id
        )  # Ask for a subcategory nobody else has taken
        if claimed_subcategory is not None:  # If one was handed out
            category, subcategory = claimed_subcategory  # Unpack the claim
            settled = False  # Becomes True once the database knows how this visit ended
            try:  # A problem in one subcategory must not stop the worker
                async with asyncio.timeout(
                    SUBCATEGORY_TIMEOUT_SECONDS
                ):  # Never let one visit hang forever
                    viewed_all = await crawl_subcategory(
                        tab, category, subcategory, state
                    )  # Visit it
                await tab.drain()  # Make sure the traffic of this visit is recorded before the tab moves on
                database.mark_visited(
                    category, subcategory, run_id, viewed_all
                )  # Remember that it is done
                settled = True  # The database now holds the result
                consecutive_failures = 0  # A success resets the counter
            except Exception as error:  # Playwright errors, timeouts and anything unexpected
                tab.dirty = True  # Replace the tab before using it again
                if (
                    tab.page is None or tab.page.is_closed() or state.context_closed
                ):  # If the tab or browser was closed, the subcategory is not at fault
                    logger.error(
                        "The tab or the browser was closed during a visit"
                    )  # Explain what happened; the finally block gives the subcategory back
                    consecutive_failures += (
                        1  # Count it so a constantly closing tab cannot loop forever
                    )
                else:  # The subcategory itself (or the site) caused the error
                    logger.exception(
                        "Failed subcategory: %s > %s",
                        category.category_name,
                        subcategory.subcategory_name,
                    )  # Log with traceback
                    database.mark_failed(
                        category,
                        subcategory,
                        run_id,
                        f"{type(error).__name__}: {error}",
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
            if await list_category(
                tab, category_to_list, database, state
            ):  # Read and store its subcategories
                consecutive_failures = 0  # A success resets the counter
            else:  # The listing failed or was interrupted
                consecutive_failures += 1  # Count the failure
            continue  # Ask for more work
        if (
            database.has_work_in_progress()
        ):  # If another worker is busy it may create more work
            await interruptible_sleep(
                WAIT_FOR_OTHER_WORKERS_SECONDS, state.stop_event
            )  # Wait a moment and ask again
            continue  # Ask for more work
        break  # Nothing left anywhere, so this worker is finished
    logger.info("Worker finished")  # Log the end


async def monitor_progress(
    database: CrawlDatabase, writer: NetworkWriter, state: CrawlState
) -> None:  # Log progress regularly and stop the crawl cleanly if the disk is almost full
    while not state.stop_event.is_set():  # Keep going until the crawl stops
        await interruptible_sleep(
            PROGRESS_INTERVAL_SECONDS, state.stop_event
        )  # Wait for the next check
        try:  # The monitor must never crash the crawl
            logger.info(
                "Progress | %s | responses saved=%d lost=%d waiting=%d",
                database.progress_text(),
                writer.saved_count,
                writer.lost_count,
                writer.queue.qsize(),
            )  # Log the overview
            free_bytes = shutil.disk_usage(BASE_DIRECTORY).free  # Free disk space
            if free_bytes < MIN_FREE_DISK_BYTES:  # If the disk is nearly full
                logger.critical(
                    "Only %.0f MB of disk space left, stopping the crawl cleanly",
                    free_bytes / 1024**2,
                )  # Explain why
                state.stop_event.set()  # Ask every worker to stop
        except Exception:  # Anything unexpected
            logger.exception(
                "The progress monitor hit an error"
            )  # Log it and keep monitoring


def install_signal_handlers(
    loop: asyncio.AbstractEventLoop, state: CrawlState, main_task: asyncio.Task
) -> None:  # Make Ctrl+C and termination requests stop the crawl cleanly
    def request_stop(signal_name: str) -> None:  # Called when a signal arrives
        if state.stop_event.is_set():  # The second signal means "stop right now"
            logger.warning(
                "%s received again, aborting immediately", signal_name
            )  # Log it
            main_task.cancel()  # Cancel everything
            return  # Nothing more to do
        logger.warning(
            "%s received: finishing the current visits, then stopping (send it again to abort at once)",
            signal_name,
        )  # Log it
        state.stop_event.set()  # Ask every worker to stop after its current visit

    for signal_number in (
        signal.SIGINT,
        signal.SIGTERM,
    ):  # The two signals that normally end a program
        try:  # Not every platform supports this
            loop.add_signal_handler(
                signal_number, request_stop, signal_number.name
            )  # Register the handler
        except (
            NotImplementedError,
            RuntimeError,
            ValueError,
        ):  # Windows cannot do this
            logger.debug(
                "Signal handler for %s is not supported here", signal_number.name
            )  # Python's default Ctrl+C behavior is used instead


async def main(log_file_path: Path) -> None:  # Program entry point
    loop = asyncio.get_running_loop()  # The running event loop
    loop.set_exception_handler(
        log_asyncio_exception
    )  # Log errors that asyncio would otherwise only print
    state = CrawlState(
        stop_event=asyncio.Event(),
        navigation_gate=asyncio.Semaphore(NAVIGATION_CONCURRENCY),
    )  # Shared state for all workers
    install_signal_handlers(
        loop, state, asyncio.current_task()
    )  # Make Ctrl+C stop the crawl cleanly
    logger.info(
        "Logging everything to %s", log_file_path
    )  # Tell the user where the log is
    log_environment()  # Record versions and settings
    database = CrawlDatabase(
        DATABASE_FILE_PATH, MAX_ATTEMPTS
    )  # Open the one and only progress database
    database.export_missing_har_files()  # Rebuild HAR files of earlier runs that were killed before exporting
    run_id = database.start_run()  # Record that a new run has begun
    har_file_path = (
        BASE_DIRECTORY / f"epubs_product_index_run{run_id}.har"
    )  # Give every run its own HAR file so older ones are kept
    database.set_run_har_file_path(
        run_id, har_file_path
    )  # Remember which HAR file belongs to this run
    logger.info(
        "Run %d started, HAR file will be %s", run_id, har_file_path
    )  # Log the run
    writer = NetworkWriter(
        database, run_id
    )  # Create the batch writer for recorded traffic
    writer.start()  # Start its background task
    monitor_task: asyncio.Task | None = None  # The progress monitor, created later
    try:  # Make sure the run is closed out in the database even if something fails
        logger.debug("Starting Playwright")  # Log the startup
        async with async_playwright() as playwright:  # Start Playwright and make sure it shuts down cleanly
            browser_context = await playwright.chromium.launch_persistent_context(  # Launch ONE Chromium window with a profile stored on disk
                user_data_dir=str(
                    BROWSER_PROFILE_DIRECTORY
                ),  # Keep the cache and cookies in this folder instead of in memory
                headless=False,  # Show the browser window
                args=[  # Extra Chromium switches
                    "--start-maximized",  # Open the window maximized
                    "--disable-backgrounding-occluded-windows",  # Do not slow down tabs that are hidden behind others
                    "--disable-renderer-backgrounding",  # Do not slow down tabs that are not in front
                    "--disable-background-timer-throttling",  # Keep timers running in background tabs
                    "--disable-session-crashed-bubble",  # No "restore pages" popup after a crashed run
                    "--hide-crash-restore-bubble",  # Same, for newer Chromium versions
                    "--no-first-run",  # Skip first-run screens
                ],  # End of the switches
                no_viewport=True,  # Let pages fill the maximized window instead of a fixed size
                accept_downloads=False,  # Never save files by accident
                service_workers="block",  # Service workers could hide requests from the recorder
            )  # End of the launch options
            tabs: list[WorkerTab] = []  # Every worker's tab holder

            def on_context_closed(
                _closed_context: BrowserContext,
            ) -> None:  # Called when the browser window goes away
                state.context_closed = True  # Remember it
                state.stop_event.set()  # Tell every worker to stop
                logger.error("The browser was closed or crashed")  # Log it

            def on_new_page(
                new_page: Page,
            ) -> None:  # Called for every new tab, including the ones we open ourselves
                task = asyncio.create_task(
                    close_if_popup(new_page)
                )  # Close it if a page opened it by itself
                background_tasks.add(
                    task
                )  # Keep a reference so the task is not garbage collected
                task.add_done_callback(
                    background_tasks.discard
                )  # Forget it when finished

            browser_context.on(
                "close", on_context_closed
            )  # Watch for the window closing
            browser_context.on("page", on_new_page)  # Watch for popups
            try:  # Make sure the traffic is drained and the browser closed even if something fails
                browser_context.set_default_timeout(
                    ACTION_TIMEOUT_MS
                )  # Apply the default wait to every action
                browser_context.set_default_navigation_timeout(
                    NAVIGATION_TIMEOUT_MS
                )  # Apply the longer wait to every navigation
                restored_pages = list(
                    browser_context.pages
                )  # Tabs Chromium may have restored from a crashed run
                for worker_number in range(1, WORKER_COUNT + 1):  # One tab per worker
                    tab = WorkerTab(
                        worker_number, browser_context, writer
                    )  # Create the holder
                    await tab.open()  # Open its tab
                    tabs.append(tab)  # Remember it
                for (
                    restored_page
                ) in restored_pages:  # Close every tab that was not opened by this run
                    try:  # Closing can fail
                        await restored_page.close()  # Close it
                    except PlaywrightError:  # Ignore errors while closing
                        logger.debug(
                            "Could not close a restored tab", exc_info=True
                        )  # Log them quietly
                monitor_task = asyncio.create_task(
                    monitor_progress(database, writer, state), name="progress-monitor"
                )  # Start the progress monitor
                try:  # A failure here is survivable when earlier runs already stored categories
                    await open_product_index(
                        tabs[0].page, state
                    )  # Load the starting page once to read the headings
                    categories = await collect_categories(
                        tabs[0].page
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
                except Exception:  # The index page could not be read
                    logger.exception(
                        "Could not read the category list from the index page"
                    )  # Log it
                    if (
                        database.category_count() == 0
                    ):  # Nothing is known from earlier runs either
                        raise  # There is nothing to crawl, so fail the run
                    logger.warning(
                        "Continuing with the %d categories remembered from earlier runs",
                        database.category_count(),
                    )  # Carry on with what we know
                async with asyncio.TaskGroup() as task_group:  # Run the workers at the same time and stop all of them if one crashes
                    for tab in tabs:  # Pair each tab with a worker
                        task_group.create_task(
                            run_worker(tab, database, run_id, state), name=tab.label
                        )  # Start the worker
            finally:  # Always run this cleanup
                logger.debug(
                    "Waiting for unfinished recordings"
                )  # Log the cleanup step
                for tab in tabs:  # Loop over every tab
                    try:  # Draining must not hide the real error
                        await tab.drain()  # Let this tab's recordings finish while the browser is still open
                    except Exception:  # Anything unexpected
                        logger.exception(
                            "Could not drain the recordings of %s", tab.label
                        )  # Log it
                logger.debug("Closing the browser context")  # Log the cleanup step
                try:  # Closing can fail if the window or the Playwright driver is already gone
                    await browser_context.close()  # Close the browser
                except Exception:  # Playwright reports a dead driver with a plain Exception
                    logger.exception(
                        "Could not close the browser context cleanly"
                    )  # Report it without hiding the original error
    finally:  # Always run this cleanup
        if monitor_task is not None:  # If the monitor was started
            monitor_task.cancel()  # Stop it
            await asyncio.gather(
                monitor_task, return_exceptions=True
            )  # Wait until it is really gone
        await writer.close()  # Save every response that is still waiting
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
        logger.info("Log file: %s", log_file_path)  # Remind the user where the log is


if __name__ == "__main__":  # Only run when the file is executed directly
    log_path = (
        configure_logging()
    )  # Start logging to the file first, so even startup problems are recorded
    lock_handle = acquire_single_instance_lock(
        LOCK_FILE_PATH
    )  # Refuse to run twice at the same time
    try:  # Catch the very last errors
        asyncio.run(main(log_path))  # Start the crawl
    except KeyboardInterrupt:  # Ctrl+C on platforms without signal handlers
        logger.warning("Interrupted by the user")  # Log it
    except BaseException:  # Anything that escaped, including exception groups from the task group
        logger.critical(
            "The crawl ended with an error", exc_info=True
        )  # Write the full traceback to the log
        raise  # Show it on the console and exit with an error code
    finally:  # Always run this cleanup
        lock_handle.close()  # Release the lock
        logging.shutdown()  # Flush and close every log handler
