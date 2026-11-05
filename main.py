"""Crawl every category and subcategory on e-publishing.af.mil, record a HAR file and remember progress in state.db."""  # Module docstring describing what the script does

import logging  # Standard library package for progress and debug messages
import re  # Standard library package for parsing ids out of onclick attributes
import sqlite3  # Standard library package for the SQLite progress database
import sys  # Standard library package so log messages can go to the console
from dataclasses import dataclass  # Standard library package for small, readable data holders
from datetime import datetime, timezone  # Standard library packages for UTC timestamps
from pathlib import Path  # Standard library package for safe file paths

from playwright.sync_api import ConsoleMessage  # Type hint for browser console messages
from playwright.sync_api import Error as PlaywrightError  # Base class of every Playwright error, timeouts included
from playwright.sync_api import Page  # Type hint for a browser page
from playwright.sync_api import Request  # Type hint for a network request
from playwright.sync_api import Response  # Type hint for a network response
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError  # Error raised when a wait runs out
from playwright.sync_api import sync_playwright  # Entry point of the synchronous Playwright API

PRODUCT_INDEX_URL = "https://www.e-publishing.af.mil/Product-Index/"  # Page where every crawl starts
TOP_LEVEL_MENU_TITLES = ["Publications", "Forms"]  # The two column headings on the Product Index page
DATABASE_FILE_PATH = Path("state.db")  # Where progress is remembered between runs
MAX_ATTEMPTS = 3  # How many times a failing subcategory is tried across all runs before giving up
ACTION_TIMEOUT_MS = 15_000  # Maximum wait for a single click or lookup, in milliseconds
PAGE_SETTLE_TIMEOUT_MS = 10_000  # Maximum wait for the network to go quiet after a navigation or click
VIEW_ALL_TIMEOUT_MS = 5_000  # Maximum wait for the "view all" control, which is often legitimately absent

STATUS_PENDING = "pending"  # Subcategory is known but has not been visited yet
STATUS_VIEWED_ALL = "viewed_all"  # Subcategory was visited and "view all" was clicked
STATUS_NO_VIEW_ALL = "no_view_all"  # Subcategory was visited and had no "view all" control (this is normal)
STATUS_FAILED = "failed"  # Visiting the subcategory raised an error

# Pattern that reads the category id from onclick="epubs.SelectCat(1, 'Air Force - Publications')"
CATEGORY_ID_PATTERN = re.compile(r"SelectCat\((\d+),")  # Capture the digits after SelectCat(
# Pattern that reads the organization id from onclick="epubs.SelectOrg(10141, 1, false, 'Departmental', ...)"
ORGANIZATION_ID_PATTERN = re.compile(r"SelectOrg\((\d+),")  # Capture the digits after SelectOrg(
# Pattern that matches the "view all" control shown after a subcategory is opened
VIEW_ALL_PATTERN = re.compile(r"view\s+all|all\s+publication|all\s+form", re.IGNORECASE)  # Match any "view all" wording, ignoring case

logging.basicConfig(  # Configure the logging system
    level=logging.DEBUG,  # Show everything, including debug messages
    format="%(asctime)s %(levelname)s %(funcName)s:%(lineno)d %(message)s",  # Include the function name and line number
    stream=sys.stdout,  # Send all log messages to the console
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


def current_utc_timestamp() -> str:  # Give the current time in a sortable text format
    return datetime.now(timezone.utc).isoformat(timespec="seconds")  # For example 2026-11-05T14:30:00+00:00


class CrawlDatabase:  # Remembers every category, subcategory, run and error in a SQLite file
    def __init__(self, database_file_path: Path, max_attempts: int) -> None:  # Open the database and create the tables
        logger.debug("Opening SQLite database at %s", database_file_path)  # Log which file is used
        self.max_attempts = max_attempts  # Remember the retry limit for failing subcategories
        self.connection = sqlite3.connect(database_file_path)  # Open (or create) the database file
        self.connection.row_factory = sqlite3.Row  # Let rows be read by column name
        self.connection.execute("PRAGMA journal_mode=WAL")  # Make writes safer if the script is interrupted
        self.create_tables()  # Make sure all tables exist

    def create_tables(self) -> None:  # Create the tables on the first run
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
            "subcategories_listed INTEGER NOT NULL DEFAULT 0, "  # 1 once its subcategory list has been read
            "subcategory_count INTEGER NOT NULL DEFAULT 0, "  # How many subcategories were found
            "discovered_at TEXT NOT NULL)"  # When this category was first seen
        )  # End of the categories table SQL
        create_subcategories_sql = (  # SQL that creates the table of subcategories
            "CREATE TABLE IF NOT EXISTS subcategories ("  # Start of the subcategories table
            "category_id INTEGER NOT NULL REFERENCES categories(category_id), "  # Parent category
            "organization_id INTEGER NOT NULL, "  # The id used by the website
            "subcategory_name TEXT NOT NULL, "  # Visible name such as Departmental
            "status TEXT NOT NULL DEFAULT 'pending', "  # pending, viewed_all, no_view_all or failed
            "attempts INTEGER NOT NULL DEFAULT 0, "  # How many times it has been visited
            "last_error TEXT, "  # The most recent error message, if any
            "first_visited_at TEXT, "  # When it was first visited
            "last_visited_at TEXT, "  # When it was last visited
            "last_run_id INTEGER REFERENCES crawl_runs(run_id), "  # Which run visited it last
            "PRIMARY KEY (category_id, organization_id))"  # One row per category and organization pair
        )  # End of the subcategories table SQL
        with self.connection:  # Run all statements in one transaction
            self.connection.execute(create_runs_sql)  # Create the runs table
            self.connection.execute(create_categories_sql)  # Create the categories table
            self.connection.execute(create_subcategories_sql)  # Create the subcategories table

    def start_run(self) -> int:  # Record the start of a new crawl run
        with self.connection:  # Save the change immediately
            cursor = self.connection.execute("INSERT INTO crawl_runs (started_at) VALUES (?)", (current_utc_timestamp(),))  # Add the run
        logger.debug("Started crawl run %d", cursor.lastrowid)  # Log the run id
        return int(cursor.lastrowid)  # Hand the run id back to the caller

    def set_run_har_file_path(self, run_id: int, har_file_path: Path) -> None:  # Remember which HAR file a run writes
        with self.connection:  # Save the change immediately
            self.connection.execute("UPDATE crawl_runs SET har_file_path = ? WHERE run_id = ?", (str(har_file_path), run_id))  # Store the path

    def finish_run(self, run_id: int) -> None:  # Record the end of a crawl run together with its totals
        visited_count = self.connection.execute(  # Count subcategories this run visited successfully
            "SELECT COUNT(*) FROM subcategories WHERE last_run_id = ? AND status IN (?, ?)",  # Query for this run's successes
            (run_id, STATUS_VIEWED_ALL, STATUS_NO_VIEW_ALL),  # Values for the placeholders
        ).fetchone()[0]  # Read the single number
        failed_count = self.connection.execute(  # Count subcategories this run failed on
            "SELECT COUNT(*) FROM subcategories WHERE last_run_id = ? AND status = ?",  # Query for this run's failures
            (run_id, STATUS_FAILED),  # Values for the placeholders
        ).fetchone()[0]  # Read the single number
        with self.connection:  # Save the change immediately
            self.connection.execute(  # Update the run row
                "UPDATE crawl_runs SET finished_at = ?, subcategories_visited = ?, subcategories_failed = ? WHERE run_id = ?",  # Statement
                (current_utc_timestamp(), visited_count, failed_count, run_id),  # Values for the placeholders
            )  # End of the update

    def save_categories(self, categories: list[Category]) -> None:  # Remember every category found on the index page
        rows = [(c.category_id, c.menu_title, c.category_name, current_utc_timestamp()) for c in categories]  # Build one row per category
        with self.connection:  # Save all rows in one transaction
            self.connection.executemany(  # Insert new categories and refresh names of known ones
                "INSERT INTO categories (category_id, menu_title, category_name, discovered_at) VALUES (?, ?, ?, ?) "  # Insert part
                "ON CONFLICT(category_id) DO UPDATE SET menu_title = excluded.menu_title, category_name = excluded.category_name",  # Update part
                rows,  # All the rows
            )  # End of the insert

    def are_subcategories_listed(self, category: Category) -> bool:  # Check whether this category's subcategory list is already stored
        row = self.connection.execute(  # Look up the category
            "SELECT subcategories_listed FROM categories WHERE category_id = ?", (category.category_id,)  # Query and its value
        ).fetchone()  # Read the single row
        return bool(row and row["subcategories_listed"])  # True only if the row exists and the flag is 1

    def save_subcategories(self, category: Category, subcategories: list[Subcategory]) -> None:  # Remember the subcategories of a category
        rows = [(category.category_id, s.organization_id, s.subcategory_name) for s in subcategories]  # Build one row per subcategory
        with self.connection:  # Save everything in one transaction
            self.connection.executemany(  # Insert subcategories, ignoring ones we already know
                "INSERT OR IGNORE INTO subcategories (category_id, organization_id, subcategory_name) VALUES (?, ?, ?)",  # Statement
                rows,  # All the rows
            )  # End of the insert
            self.connection.execute(  # Mark the category as fully listed
                "UPDATE categories SET subcategories_listed = 1, subcategory_count = ? WHERE category_id = ?",  # Statement
                (len(subcategories), category.category_id),  # Values for the placeholders
            )  # End of the update

    def get_subcategories_to_visit(self, category: Category) -> list[Subcategory]:  # List what still needs visiting in a category
        rows = self.connection.execute(  # Ask for pending rows and failed rows that still have attempts left
            "SELECT organization_id, subcategory_name FROM subcategories "  # Columns and table
            "WHERE category_id = ? AND (status = ? OR (status = ? AND attempts < ?)) ORDER BY rowid",  # Filter, keeping the website's order
            (category.category_id, STATUS_PENDING, STATUS_FAILED, self.max_attempts),  # Values for the placeholders
        ).fetchall()  # Read all rows
        return [Subcategory(row["organization_id"], row["subcategory_name"]) for row in rows]  # Convert rows to Subcategory objects

    def count_known_subcategories(self, category: Category) -> int:  # Count every stored subcategory of a category
        return int(self.connection.execute(  # Run the count query
            "SELECT COUNT(*) FROM subcategories WHERE category_id = ?", (category.category_id,)  # Query and its value
        ).fetchone()[0])  # Read the single number

    def mark_visited(self, category: Category, subcategory: Subcategory, run_id: int, viewed_all: bool) -> None:  # Record a successful visit
        status = STATUS_VIEWED_ALL if viewed_all else STATUS_NO_VIEW_ALL  # Choose the status from the result
        now = current_utc_timestamp()  # Take one timestamp for the whole update
        with self.connection:  # Save the change immediately
            self.connection.execute(  # Update the subcategory row
                "UPDATE subcategories SET status = ?, attempts = attempts + 1, last_error = NULL, "  # First half of the statement
                "first_visited_at = COALESCE(first_visited_at, ?), last_visited_at = ?, last_run_id = ? "  # Second half of the statement
                "WHERE category_id = ? AND organization_id = ?",  # Which row to update
                (status, now, now, run_id, category.category_id, subcategory.organization_id),  # Values for the placeholders
            )  # End of the update

    def mark_failed(self, category: Category, subcategory: Subcategory, run_id: int, error_text: str) -> None:  # Record a failed visit
        now = current_utc_timestamp()  # Take one timestamp for the whole update
        with self.connection:  # Save the change immediately
            self.connection.execute(  # Update the subcategory row
                "UPDATE subcategories SET status = ?, attempts = attempts + 1, last_error = ?, "  # First half of the statement
                "first_visited_at = COALESCE(first_visited_at, ?), last_visited_at = ?, last_run_id = ? "  # Second half of the statement
                "WHERE category_id = ? AND organization_id = ?",  # Which row to update
                (STATUS_FAILED, error_text[:2000], now, now, run_id, category.category_id, subcategory.organization_id),  # Values
            )  # End of the update

    def log_summary(self) -> None:  # Print an overview of everything stored so far
        logger.info("---- Crawl summary (all runs) ----")  # Heading
        status_rows = self.connection.execute("SELECT status, COUNT(*) AS total FROM subcategories GROUP BY status").fetchall()  # Count per status
        for status_row in status_rows:  # Loop over the statuses
            logger.info("Subcategories %-12s: %d", status_row["status"], status_row["total"])  # Log one line per status
        category_total = self.connection.execute("SELECT COUNT(*) FROM categories").fetchone()[0]  # Count categories
        logger.info("Categories known       : %d", category_total)  # Log the category total
        gave_up_rows = self.connection.execute(  # Find subcategories that used up all their attempts
            "SELECT category_id, subcategory_name, last_error FROM subcategories WHERE status = ? AND attempts >= ?",  # Query
            (STATUS_FAILED, self.max_attempts),  # Values for the placeholders
        ).fetchall()  # Read all rows
        for gave_up_row in gave_up_rows:  # Loop over the failures
            logger.warning("Gave up on category %s > %s: %s", gave_up_row["category_id"], gave_up_row["subcategory_name"], gave_up_row["last_error"])  # Log each

    def close(self) -> None:  # Close the database file
        self.connection.close()  # Release the file


def log_browser_console_message(message: ConsoleMessage) -> None:  # Callback for text the web page prints to its console
    logger.debug("Browser console [%s]: %s", message.type, message.text)  # Log the message type and text


def log_browser_page_error(error: Exception) -> None:  # Callback for uncaught JavaScript errors on the page
    logger.debug("Browser page error: %s", error)  # Log the error


def log_network_request(request: Request) -> None:  # Callback for every outgoing network request
    logger.debug("Request  -> %s %s", request.method, request.url)  # Log the HTTP method and the URL


def log_network_response(response: Response) -> None:  # Callback for every incoming network response
    logger.debug("Response <- %s %s", response.status, response.url)  # Log the status code and the URL


def attach_debug_listeners(page: Page) -> None:  # Hook the logging callbacks into the page events
    logger.debug("Attaching debug listeners to the page")  # Log that the listeners are being attached
    page.on("console", log_browser_console_message)  # Log the page's console output
    page.on("pageerror", log_browser_page_error)  # Log JavaScript errors from the page
    page.on("request", log_network_request)  # Log every request
    page.on("response", log_network_response)  # Log every response


def wait_for_page_to_settle(page: Page) -> None:  # Wait until the page has finished loading its data
    logger.debug("Waiting for network idle (timeout %d ms)", PAGE_SETTLE_TIMEOUT_MS)  # Log what we are waiting for
    try:  # Some pages never go fully idle because of analytics scripts
        page.wait_for_load_state("networkidle", timeout=PAGE_SETTLE_TIMEOUT_MS)  # Wait for the network to go quiet
        logger.debug("Network is idle")  # Log that the wait finished
    except PlaywrightTimeoutError:  # If the network never went quiet
        logger.info("Network did not go idle within the timeout, continuing anyway")  # Report it and keep going


def open_product_index(page: Page) -> None:  # Load the starting page
    logger.debug("Opening %s", PRODUCT_INDEX_URL)  # Log the navigation
    page.goto(PRODUCT_INDEX_URL, wait_until="domcontentloaded")  # Navigate to the Product Index page
    page.locator(".main-nav h4").first.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)  # Wait for the headings
    wait_for_page_to_settle(page)  # Give the page's scripts time to finish
    logger.debug("Current page URL: %s | title: %s", page.url, page.title())  # Log where we ended up


def collect_categories(page: Page) -> list[Category]:  # List every category under both headings
    categories: list[Category] = []  # Start with an empty list
    for menu_title in TOP_LEVEL_MENU_TITLES:  # Loop over "Publications" and "Forms"
        links_xpath = f"//div[contains(@class,'main-nav')]//h4[normalize-space()='{menu_title}']/following-sibling::ul[1]//a"  # Links under this heading
        category_links = page.locator(f"xpath={links_xpath}")  # Locate every category link under the heading
        link_count = category_links.count()  # Count how many links were found
        logger.debug("Found %d category links under %s", link_count, menu_title)  # Log the count
        for link_index in range(link_count):  # Loop over the links by position
            category_link = category_links.nth(link_index)  # Pick the link at this position
            onclick_text = category_link.get_attribute("onclick") or ""  # Read the onclick attribute
            match = CATEGORY_ID_PATTERN.search(onclick_text)  # Pull the category id out of it
            if match is None:  # If the id could not be found
                logger.warning("Could not read a category id from: %s", onclick_text)  # Warn about it
                continue  # Skip this link
            category_name = category_link.inner_text().strip()  # Read the visible name
            categories.append(Category(menu_title, int(match.group(1)), category_name))  # Remember the category
            logger.debug("Category: %s > %s (id %s)", menu_title, category_name, match.group(1))  # Log the category
    return categories  # Hand the list back to the caller


def click_category(page: Page, category: Category) -> None:  # Open one category
    logger.debug("Clicking category: %s > %s", category.menu_title, category.category_name)  # Log the click
    category_link_selector = f"a[onclick*='SelectCat({category.category_id},']"  # Selector for this category's link
    page.locator(category_link_selector).first.click(timeout=ACTION_TIMEOUT_MS)  # Click the link
    page.locator(f"#cat-{category.category_id}").wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)  # Wait for its pane
    logger.debug("Category pane #cat-%d is visible", category.category_id)  # Log that the pane opened


def collect_subcategories(page: Page, category: Category) -> list[Subcategory]:  # List the subcategories of the open category
    subcategory_links = page.locator(f"#cat-{category.category_id} a[onclick*='SelectOrg']")  # Links inside the pane
    link_count = subcategory_links.count()  # Count how many links were found
    if link_count == 0:  # Having no subcategories is normal
        logger.info("No subcategories in #cat-%d (this is normal), moving on", category.category_id)  # Log it calmly
        return []  # Return an empty list so the caller moves on
    logger.debug("Found %d subcategory links in #cat-%d", link_count, category.category_id)  # Log the count
    subcategories: list[Subcategory] = []  # Start with an empty list
    for link_index in range(link_count):  # Loop over the links by position
        subcategory_link = subcategory_links.nth(link_index)  # Pick the link at this position
        onclick_text = subcategory_link.get_attribute("onclick") or ""  # Read the onclick attribute
        match = ORGANIZATION_ID_PATTERN.search(onclick_text)  # Pull the organization id out of it
        if match is None:  # If the id could not be found
            logger.warning("Could not read an organization id from: %s", onclick_text)  # Warn about it
            continue  # Skip this link
        subcategories.append(Subcategory(int(match.group(1)), subcategory_link.inner_text().strip()))  # Remember it
    return subcategories  # Hand the list back to the caller


def click_subcategory(page: Page, category: Category, subcategory: Subcategory) -> None:  # Open one subcategory
    logger.debug("Clicking subcategory: %s", subcategory.subcategory_name)  # Log the click
    subcategory_selector = f"#cat-{category.category_id} a[onclick*='SelectOrg({subcategory.organization_id},']"  # Selector for the exact link
    page.locator(subcategory_selector).first.click(timeout=ACTION_TIMEOUT_MS)  # Click the link
    wait_for_page_to_settle(page)  # Wait for the series list to load
    logger.debug("Current page URL: %s | title: %s", page.url, page.title())  # Log where we ended up


def click_view_all_publications(page: Page) -> bool:  # Click the "view all" control if there is one
    logger.debug("Looking for the 'view all' control inside #org-list and #pub-list")  # Log what we are looking for
    view_all_control = page.locator("#org-list, #pub-list").get_by_text(VIEW_ALL_PATTERN).first  # Find the control
    try:  # The control is legitimately missing on some pages
        view_all_control.click(timeout=VIEW_ALL_TIMEOUT_MS)  # Click it
    except PlaywrightTimeoutError:  # If it never showed up
        logger.debug("'View all' control was not found or not clickable")  # Log the miss
        return False  # Tell the caller nothing was clicked
    wait_for_page_to_settle(page)  # Wait for the full list of publications to load
    return True  # Tell the caller the click worked


def crawl_subcategory(page: Page, category: Category, subcategory: Subcategory) -> bool:  # Visit one full path and report if "view all" was clicked
    path_text = f"{category.menu_title} > {category.category_name} > {subcategory.subcategory_name}"  # Readable path
    logger.debug("Crawling: %s", path_text)  # Log the full path
    open_product_index(page)  # Start from a clean index page
    click_category(page, category)  # Go into the category
    click_subcategory(page, category, subcategory)  # Go into the subcategory
    viewed_all = click_view_all_publications(page)  # Click "view all" if it exists
    if viewed_all:  # If the click worked
        logger.info("Viewed all: %s", path_text)  # Log success
    else:  # If the control was not found
        logger.info("No 'view all' control (this is normal), moving on: %s", path_text)  # Log it calmly
    return viewed_all  # Tell the caller what happened


def crawl_category(page: Page, category: Category, database: CrawlDatabase, run_id: int) -> None:  # Visit every unvisited subcategory of one category
    if not database.are_subcategories_listed(category):  # Only open the category if we never read its subcategories
        try:  # A problem in one category must not stop the whole crawl
            open_product_index(page)  # Reload so the page is in a clean state
            click_category(page, category)  # Open the category to read its subcategories
            database.save_subcategories(category, collect_subcategories(page, category))  # Read and remember them
        except PlaywrightError:  # If the category could not be opened or read
            logger.exception("Skipping category: %s > %s", category.menu_title, category.category_name)  # Log with traceback
            return  # Go back to the caller, which moves on to the next category
    subcategories_to_visit = database.get_subcategories_to_visit(category)  # Ask the database what is still left
    known_total = database.count_known_subcategories(category)  # Ask the database how many exist in total
    if not subcategories_to_visit:  # If nothing is left to do
        logger.info("Skipping %s > %s: nothing left to visit (%d known)", category.menu_title, category.category_name, known_total)  # Say why
        return  # Move on without opening any page
    logger.info("%s > %s: %d to visit, %d already done or exhausted", category.menu_title, category.category_name, len(subcategories_to_visit), known_total - len(subcategories_to_visit))  # Log the plan
    for subcategory in subcategories_to_visit:  # Loop over what is left
        try:  # A problem in one subcategory must not stop the crawl
            viewed_all = crawl_subcategory(page, category, subcategory)  # Visit this subcategory
            database.mark_visited(category, subcategory, run_id, viewed_all)  # Remember that it is done
        except PlaywrightError as error:  # If anything went wrong on this path
            logger.exception("Failed subcategory: %s > %s", category.category_name, subcategory.subcategory_name)  # Log with traceback
            database.mark_failed(category, subcategory, run_id, str(error))  # Remember the failure so it can be retried later


def main() -> None:  # Program entry point
    database = CrawlDatabase(DATABASE_FILE_PATH, MAX_ATTEMPTS)  # Open the progress database
    run_id = database.start_run()  # Record that a new run has begun
    har_file_path = Path(f"epubs_product_index_run{run_id}.har")  # Give every run its own HAR file so older ones are kept
    database.set_run_har_file_path(run_id, har_file_path)  # Remember which HAR file belongs to this run
    try:  # Make sure the run is closed out in the database even if something fails
        logger.debug("Starting Playwright")  # Log the startup
        with sync_playwright() as playwright:  # Start Playwright and make sure it shuts down cleanly
            browser = playwright.chromium.launch(  # Launch Chromium
                headless=False,  # Show the browser window
                args=["--start-maximized"],  # Open the window maximized
            )  # End of the launch options
            try:  # Make sure the browser is closed even if something fails
                browser_context = browser.new_context(  # Create a fresh browser profile
                    no_viewport=True,  # Let the page fill the maximized window instead of a fixed size
                    record_har_path=str(har_file_path),  # Record all network traffic to this run's HAR file
                    record_har_content="embed",  # Store the response bodies inside the HAR file
                )  # End of the context options
                try:  # Make sure the HAR file is written even if something fails
                    browser_context.set_default_timeout(ACTION_TIMEOUT_MS)  # Apply the default wait to every action
                    page = browser_context.new_page()  # Open a new tab
                    attach_debug_listeners(page)  # Start logging console messages, errors and network traffic
                    open_product_index(page)  # Load the starting page once to read the headings
                    categories = collect_categories(page)  # List every category under Publications and Forms
                    if not categories:  # If nothing was found, the page layout probably changed
                        logger.error("No categories found, the page layout may have changed")  # Tell the user
                    database.save_categories(categories)  # Remember the categories in the database
                    logger.info("Found %d categories in total", len(categories))  # Log the total
                    for category in categories:  # Loop over each category
                        crawl_category(page, category, database, run_id)  # Visit what is left in this category
                finally:  # Always run this cleanup
                    logger.debug("Closing the browser context to write the HAR file")  # Log the cleanup step
                    browser_context.close()  # Closing the context is what writes the HAR file to disk
            finally:  # Always run this cleanup
                browser.close()  # Close the browser
        logger.info("HAR saved to %s", har_file_path.resolve())  # Tell the user where the HAR file is
    finally:  # Always run this cleanup
        database.finish_run(run_id)  # Record the end time and totals of this run
        database.log_summary()  # Print the overall progress
        database.close()  # Close the database file


if __name__ == "__main__":  # Only run when the file is executed directly
    main()  # Start the crawl
