"""Job settings. Every limit here is chosen by whoever runs the job."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

DEFAULT_USER_AGENT = "WebScrapingTool/0.1 (+self-hosted data extraction)"


class FieldRule(BaseModel):
    """One column in custom mode: a CSS selector plus how to read and clean it."""

    name: str = Field(min_length=1)
    css: str = Field(min_length=1)
    attr: str | None = None  # read this attribute instead of the text
    clean: str = "text"  # text | number | price | url

    @field_validator("clean")
    @classmethod
    def _known_cleaner(cls, value: str) -> str:
        if value not in {"text", "number", "price", "url"}:
            raise ValueError("clean must be one of: text, number, price, url")
        return value


class JobConfig(BaseModel):
    name: str = "Untitled scrape"
    start_urls: list[str] = Field(min_length=1)

    # What to extract. No fields means automatic detection.
    item_selector: str | None = None
    fields: list[FieldRule] = Field(default_factory=list)

    # Where to go next
    follow_pagination: bool = True
    next_selector: str | None = None  # blank means detect the "next" link
    follow_links: bool = False  # also crawl other same-site links
    url_pattern: str | None = None  # only crawl URLs matching this regex

    # How much to scrape
    max_pages: int = Field(default=50, ge=1)
    max_items: int | None = Field(default=None, ge=1)  # None means no item limit
    max_depth: int = Field(default=2, ge=0)
    delay_seconds: float = Field(default=1.0, ge=0)

    # How to fetch
    render_js: bool = False
    respect_robots: bool = True
    user_agent: str = DEFAULT_USER_AGENT
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=3, ge=0)

    @field_validator("start_urls")
    @classmethod
    def _http_only(cls, urls: list[str]) -> list[str]:
        for url in urls:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            valid_host = host and not any(ch.isspace() for ch in parsed.netloc) and ("." in host or host == "localhost")
            if parsed.scheme not in {"http", "https"} or not valid_host:
                raise ValueError(f"Not a valid http(s) URL: {url!r}")
        return urls

    @field_validator("url_pattern")
    @classmethod
    def _valid_regex(cls, pattern: str | None) -> str | None:
        if pattern:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"Invalid URL pattern: {exc}") from exc
        return pattern or None
