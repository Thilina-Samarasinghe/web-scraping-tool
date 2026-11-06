"""Download pages, with retries and a size limit, using plain HTTP or a real browser."""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from .config import JobConfig

MAX_BYTES = 25 * 1024 * 1024
_RETRYABLE = {429, 500, 502, 503, 504}
_MAX_RETRY_WAIT = 120.0


class FetchError(Exception):
    """The page could not be retrieved."""


@dataclass
class Page:
    url: str  # final URL after redirects
    status: int
    html: str | bytes  # bytes when the parser should detect the encoding from the page itself


class HttpFetcher:
    def __init__(self, config: JobConfig):
        self.config = config
        self.client = httpx.Client(
            headers={"User-Agent": config.user_agent, "Accept": "text/html,application/xhtml+xml"},
            timeout=config.timeout_seconds,
            follow_redirects=True,
        )

    def fetch(self, url: str) -> Page:
        attempts = self.config.max_retries + 1
        last_error = "unknown error"
        page = None
        for attempt in range(attempts):
            wait = 2.0**attempt
            try:
                page, retry_after = self._get(url)
                if page.status not in _RETRYABLE:
                    return page
                last_error = f"HTTP {page.status}"
                wait = max(wait, retry_after)
            except httpx.HTTPError as exc:
                page = None
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts - 1:
                time.sleep(min(wait, _MAX_RETRY_WAIT))
        if page is not None:
            return page  # Let the crawler see the final status, such as repeated 429s.
        raise FetchError(f"Gave up after {attempts} attempt(s): {last_error}")

    def _get(self, url: str) -> tuple[Page, float]:
        with self.client.stream("GET", url) as response:
            header = response.headers.get("retry-after", "")
            retry_after = float(header) if header.isdigit() else 0.0
            content_type = response.headers.get("content-type", "").lower()
            if response.status_code < 400 and content_type and "html" not in content_type and "xml" not in content_type:
                raise FetchError(f"Skipped non-HTML content ({content_type.split(';')[0]})")
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise FetchError(f"Page is larger than {MAX_BYTES // (1024 * 1024)} MB")
                chunks.append(chunk)
            body = b"".join(chunks)
            html = body.decode(response.charset_encoding, errors="replace") if self._known_charset(response) else body
            return Page(str(response.url), response.status_code, html), retry_after

    @staticmethod
    def _known_charset(response: httpx.Response) -> bool:
        name = response.charset_encoding
        if not name:
            return False
        try:
            b"".decode(name)
        except LookupError:
            return False
        return True

    def close(self) -> None:
        self.client.close()


class BrowserFetcher:
    """Renders JavaScript with headless Chromium. Slower, so only used when asked for."""

    def __init__(self, config: JobConfig):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise FetchError(
                'JavaScript pages need Playwright. Run: pip install -e ".[js]" and then: playwright install chromium'
            ) from exc

        self.config = config
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(headless=True)
        except Exception:
            self._playwright.stop()
            raise
        self._context = self._browser.new_context(user_agent=config.user_agent)

    def fetch(self, url: str) -> Page:
        from playwright.sync_api import Error as PlaywrightError

        page = self._context.new_page()
        try:
            response = page.goto(url, wait_until="load", timeout=self.config.timeout_seconds * 1000)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except PlaywrightError:
                pass  # Pages with constant background traffic never go idle.
            return Page(page.url, response.status if response else 200, page.content())
        except PlaywrightError as exc:
            raise FetchError(f"Browser error: {str(exc).splitlines()[0]}") from exc
        finally:
            page.close()

    def close(self) -> None:
        self._browser.close()
        self._playwright.stop()


def make_fetcher(config: JobConfig):
    return BrowserFetcher(config) if config.render_js else HttpFetcher(config)
