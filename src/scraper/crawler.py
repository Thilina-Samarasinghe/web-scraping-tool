"""The crawl loop: fetch, extract, store, find the next pages, and stop at the user's limits."""
from __future__ import annotations

import re
import subprocess
import sys
import time
from collections import deque
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx

from .config import JobConfig
from .extractor import extract, find_links, find_next_page, parse
from .fetchers import FetchError, make_fetcher
from .storage import Store

# This many refusals (401/403/429) in a row means the site does not want us here, so stop.
MAX_CONSECUTIVE_BLOCKS = 3


class RobotsChecker:
    """Reads each host's robots.txt once."""

    def __init__(self, user_agent: str, timeout: float):
        self.user_agent = user_agent
        self.timeout = timeout
        self._parsers: dict[str, RobotFileParser | None] = {}

    def _load(self, origin: str) -> RobotFileParser | None:
        try:
            response = httpx.get(
                f"{origin}/robots.txt",
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout,
                follow_redirects=True,
            )
        except httpx.HTTPError:
            return None  # No answer at all: the page fetch will report the real problem.
        parser = RobotFileParser()
        if response.status_code in (401, 403) or response.status_code >= 500:
            parser.disallow_all = True
        elif response.status_code >= 400:
            parser.allow_all = True
        else:
            parser.parse(response.text.splitlines())
            parser.modified()  # Without this, an empty robots.txt would refuse every URL.
        return parser

    def _parser(self, url: str) -> RobotFileParser | None:
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._parsers:
            self._parsers[origin] = self._load(origin)
        return self._parsers[origin]

    def allowed(self, url: str) -> bool:
        parser = self._parser(url)
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str) -> float:
        parser = self._parser(url)
        delay = parser.crawl_delay(self.user_agent) if parser else None
        return float(delay) if delay else 0.0


def normalize(url: str) -> str:
    parts = urlparse(url)
    return urlunparse(parts._replace(fragment="", path=parts.path or "/"))


def same_site(a: str, b: str) -> bool:
    return urlparse(a).netloc.lower().removeprefix("www.") == urlparse(b).netloc.lower().removeprefix("www.")


def run_job(job_id: int, store: Store) -> str:
    """Run a stored job to completion and return its final status."""
    config = store.get_config(job_id)
    if not store.mark_started(job_id):
        return "cancelled"
    fetcher = None
    try:
        fetcher = make_fetcher(config)
        status, message = _crawl(job_id, config, store, fetcher)
    except Exception as exc:  # The job must always reach a final state the user can see.
        status, message = "failed", f"{type(exc).__name__}: {exc}"
        store.log(job_id, "error", message)
    finally:
        if fetcher is not None:
            fetcher.close()
    store.finish(job_id, status, message)
    return store.get_job(job_id)["status"]


def _crawl(job_id: int, config: JobConfig, store: Store, fetcher) -> tuple[str, str]:
    robots = RobotsChecker(config.user_agent, config.timeout_seconds) if config.respect_robots else None
    pattern = re.compile(config.url_pattern) if config.url_pattern else None
    queue = deque((url, 0) for url in config.start_urls)
    seen = {normalize(url) for url in config.start_urls}
    pages = items = blocked_in_a_row = page_errors = robots_skipped = 0
    stop_reason = "All reachable pages were scraped"
    last_request = 0.0

    while queue:
        if store.is_cancelled(job_id):
            return "cancelled", "Stopped by user"
        if pages >= config.max_pages:
            stop_reason = f"Reached your page limit ({config.max_pages})"
            break
        if config.max_items is not None and items >= config.max_items:
            stop_reason = f"Reached your item limit ({config.max_items})"
            break

        url, depth = queue.popleft()
        if robots and not robots.allowed(url):
            robots_skipped += 1
            store.log(job_id, "warning", "Skipped: disallowed by robots.txt", url)
            continue

        delay = max(config.delay_seconds, robots.crawl_delay(url) if robots else 0.0)
        pause = last_request + delay - time.monotonic()
        if pause > 0:
            time.sleep(pause)
        last_request = time.monotonic()

        try:
            page = fetcher.fetch(url)
        except FetchError as exc:
            page_errors += 1
            store.log(job_id, "error", str(exc), url)
            continue

        pages += 1
        store.add_page(job_id)
        if page.status >= 400:
            page_errors += 1
            store.log(job_id, "error", f"HTTP {page.status}", url)
            blocked_in_a_row = blocked_in_a_row + 1 if page.status in (401, 403, 429) else 0
            if blocked_in_a_row >= MAX_CONSECUTIVE_BLOCKS:
                return "failed", f"Stopped: the site refused {blocked_in_a_row} requests in a row (HTTP {page.status})"
            continue
        blocked_in_a_row = 0

        if not same_site(page.url, url):
            store.log(job_id, "warning", f"Skipped: redirected to another site ({page.url})", url)
            continue

        soup = parse(page.html)
        next_url = find_next_page(soup, page.url, config.next_selector) if config.follow_pagination else None
        links = find_links(soup, page.url) if config.follow_links else []
        rows = extract(soup, page.url, config)
        if config.max_items is not None:
            rows = rows[: config.max_items - items]
        added = store.add_items(job_id, page.url, rows)
        items += added
        store.log(job_id, "info", f"Found {len(rows)} rows, {added} new", page.url)

        # Pagination goes first and keeps the same depth: it is more of the same listing.
        if next_url and same_site(next_url, url) and normalize(next_url) not in seen:
            seen.add(normalize(next_url))
            queue.appendleft((next_url, depth))
        if depth < config.max_depth:
            for link in links:
                key = normalize(link)
                if key in seen or not same_site(link, url) or (pattern and not pattern.search(link)):
                    continue
                seen.add(key)
                queue.append((link, depth + 1))

    if pages == 0 and robots_skipped:
        return "failed", "robots.txt does not allow scraping these pages"
    if pages == 0 and page_errors:
        return "failed", "No pages could be downloaded. See the log for details"
    if items == 0:
        stop_reason += ". No data was found: the page may need JavaScript or custom selectors"
    return "completed", stop_reason


def launch_job(job_id: int, db_path: str | None = None) -> subprocess.Popen:
    """Run a job in its own process so it survives dashboard reruns and can use Playwright."""
    args = [sys.executable, "-m", "scraper.cli", "run-job", str(job_id)]
    if db_path:
        args += ["--db", str(db_path)]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
