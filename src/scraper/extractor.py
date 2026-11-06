"""Pull structured rows out of HTML, using your selectors or automatic detection."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .cleaners import apply_cleaner, clean_text
from .config import JobConfig

_SKIP_REGIONS = {"nav", "header", "footer", "aside", "script", "style", "noscript", "form", "select"}
# Currency-first ("£1.50", "Rs. 2,500") is far more common, so it is tried before "1,50 €".
_PRICE_PATTERNS = (
    re.compile(r"(?:[$€£¥₹]|\b(?:USD|EUR|GBP|LKR|Rs\.?))\s?\d(?:[\d,.]*\d)?"),
    re.compile(r"\d(?:[\d,.]*\d)?\s?(?:[$€£¥₹]|\b(?:USD|EUR|GBP|LKR)\b)"),
)
_NEXT_TEXT = re.compile(r"^\s*(next(\s+page)?|older|›|»|→|>|>>)\s*(›|»|→|>|>>)?\s*$", re.I)
_JSONLD_SKIP = {
    "BreadcrumbList", "WebSite", "WebPage", "Organization", "SearchAction",
    "SiteNavigationElement", "ImageObject", "ItemList", "ListItem",
}
MIN_REPEATS = 3


def parse(html: str | bytes) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def extract(soup: BeautifulSoup, url: str, config: JobConfig) -> list[dict]:
    if config.fields:
        return extract_custom(soup, url, config)
    return extract_auto(soup, url)


# --- Custom mode ---------------------------------------------------------------------------

def extract_custom(soup: BeautifulSoup, url: str, config: JobConfig) -> list[dict]:
    blocks = soup.select(config.item_selector) if config.item_selector else [soup]
    rows = []
    for block in blocks:
        row = {}
        for rule in config.fields:
            node = block.select_one(rule.css)
            raw = None
            if node is not None:
                raw = node.get(rule.attr) if rule.attr else node.get_text(" ", strip=True)
                if isinstance(raw, list):  # e.g. class="a b"
                    raw = " ".join(raw)
            row[rule.name] = apply_cleaner(rule.clean, raw, url)
        if any(value is not None for value in row.values()):
            rows.append(row)
    return rows


# --- Automatic mode ------------------------------------------------------------------------

def extract_auto(soup: BeautifulSoup, url: str) -> list[dict]:
    """Choose the richest source on the page, falling back to a one-row page summary."""
    candidates = [_from_tables(soup, url), _from_repeating_blocks(soup, url), _from_json_ld(soup)]
    best = max(candidates, key=_richness)
    return best if best else [_page_summary(soup, url)]


def _richness(rows: list[dict]) -> int:
    return sum(1 for row in rows for value in row.values() if value not in (None, ""))


def _from_json_ld(soup: BeautifulSoup) -> list[dict]:
    rows: list[dict] = []

    def visit(node) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            for key in ("@graph", "itemListElement", "item"):
                if isinstance(node.get(key), (list, dict)):
                    visit(node[key])
            kinds = node.get("@type")
            kinds = kinds if isinstance(kinds, list) else [kinds]
            if node.get("name") and not any(kind in _JSONLD_SKIP for kind in kinds):
                rows.append(_flatten_json_ld(node))

    for script in soup.find_all("script", type=re.compile(r"ld\+json", re.I)):
        try:
            visit(json.loads(script.string or ""))
        except (json.JSONDecodeError, TypeError):
            continue
    return rows


def _flatten_json_ld(node: dict) -> dict:
    row = {}
    for key, value in node.items():
        if key.startswith("@"):
            continue
        if isinstance(value, dict):
            for sub_key in ("name", "price", "priceCurrency", "ratingValue", "url"):
                if sub_key in value:
                    row[sub_key if key == "offers" else f"{key}_{sub_key}"] = value[sub_key]
        elif isinstance(value, list):
            if value and all(isinstance(v, (str, int, float)) for v in value):
                row[key] = ", ".join(str(v) for v in value)
        else:
            row[key] = value
    return row


def _in_skipped_region(tag: Tag) -> bool:
    return any(parent.name in _SKIP_REGIONS for parent in tag.parents)


def _from_tables(soup: BeautifulSoup, url: str) -> list[dict]:
    best: list[dict] = []
    for table in soup.find_all("table"):
        if _in_skipped_region(table) or table.find("table"):
            continue
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [clean_text(cell.get_text(" ")) for cell in rows[0].find_all(["th", "td"])]
        if len(headers) < 2:
            continue
        headers = _unique_headers(headers)
        parsed = []
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) != len(headers):
                continue
            record = {header: clean_text(cell.get_text(" ")) for header, cell in zip(headers, cells)}
            link = row.find("a", href=True)
            if link:
                record["url"] = urljoin(url, link["href"])
            parsed.append(record)
        if len(parsed) > len(best):
            best = parsed
    return best


def _unique_headers(headers: list[str | None]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for index, header in enumerate(headers):
        name = header or f"column_{index + 1}"
        seen[name] = seen.get(name, 0) + 1
        result.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return result


def _from_repeating_blocks(soup: BeautifulSoup, url: str) -> list[dict]:
    """Find the largest group of same-shaped siblings, such as product cards or result rows."""
    body = soup.body or soup
    best_rows: list[dict] = []
    best_score = 0
    for parent in body.find_all(True):
        if parent.name in _SKIP_REGIONS | {"table", "tbody", "thead", "tr"} or _in_skipped_region(parent):
            continue
        groups: dict[tuple, list[Tag]] = defaultdict(list)
        for child in parent.find_all(True, recursive=False):
            if child.name not in _SKIP_REGIONS:
                groups[(child.name, tuple(sorted(child.get("class", []))))].append(child)
        for blocks in groups.values():
            if len(blocks) < MIN_REPEATS or _looks_like_navigation(blocks):
                continue
            rows = [row for row in (_block_to_row(block, url) for block in blocks) if row]
            if len(rows) < MIN_REPEATS:
                continue
            score = _richness(rows)
            if score > best_score:
                best_rows, best_score = rows, score
    return best_rows


def _looks_like_navigation(blocks: list[Tag]) -> bool:
    """Link lists hold only short link text: menus, tag clouds, pagers."""
    total = linked = 0
    for block in blocks:
        total += len(block.get_text(" ", strip=True))
        linked += sum(len(a.get_text(" ", strip=True)) for a in block.find_all("a"))
    has_media = any(block.find("img") for block in blocks)
    return total == 0 or (not has_media and linked / total > 0.9 and total / len(blocks) < 40)


def _block_to_row(block: Tag, url: str) -> dict:
    row: dict = {}
    heading = block.find(["h1", "h2", "h3", "h4", "h5", "h6"])
    link = (heading.find("a", href=True) if heading else None) or block.find("a", href=True)
    if heading:
        titled = heading.find("a", title=True)  # Link titles often hold the untruncated text.
        row["title"] = clean_text(titled["title"] if titled else heading.get_text(" "))
    elif link:
        row["title"] = clean_text(link.get("title") or link.get_text(" "))
    text = clean_text(block.get_text(" ")) or ""
    price = next((match for pattern in _PRICE_PATTERNS if (match := pattern.search(text))), None)
    if price:
        row["price"] = clean_text(price.group())
    if link and urlparse(urljoin(url, link["href"])).scheme in {"http", "https"}:
        row["url"] = urljoin(url, link["href"])
    image = block.find("img")
    if image:
        source = image.get("src") or image.get("data-src")
        if source and not source.startswith("data:"):
            row["image"] = urljoin(url, source)
    if text and text != row.get("title"):
        row["text"] = text[:1000]
    if not row.get("title") and not row.get("text"):
        return {}
    return row


def _page_summary(soup: BeautifulSoup, url: str) -> dict:
    description = soup.find("meta", attrs={"name": "description"})
    heading = soup.find("h1")
    title = clean_text(soup.title.get_text()) if soup.title else None
    heading_text = clean_text(heading.get_text(" ")) if heading else None
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    body = soup.body.get_text(" ") if soup.body else ""
    return {
        "title": title,
        "heading": heading_text,
        "description": clean_text(description.get("content")) if description else None,
        "text": (clean_text(body) or "")[:5000] or None,
        "url": url,
    }


# --- Finding more pages --------------------------------------------------------------------

def find_next_page(soup: BeautifulSoup, url: str, selector: str | None = None) -> str | None:
    if selector:
        node = soup.select_one(selector)
    else:
        node = soup.select_one(
            "a[rel~=next][href], link[rel~=next][href], .next a[href], a.next[href], "
            ".pagination-next[href], a[aria-label~=Next][href]"
        )
        if node is None:
            links = soup.find_all("a", href=True)
            node = next((a for a in links if _NEXT_TEXT.match(a.get_text(" ", strip=True))), None)
    href = node.get("href") if node is not None else None
    return urljoin(url, href) if href else None


def find_links(soup: BeautifulSoup, url: str) -> list[str]:
    links = []
    for anchor in soup.find_all("a", href=True):
        target = urljoin(url, anchor["href"]).split("#")[0]
        if urlparse(target).scheme in {"http", "https"}:
            links.append(target)
    return links
