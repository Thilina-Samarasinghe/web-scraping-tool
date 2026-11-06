"""Send scraped rows to CSV, Excel, JSON, any SQL database or a remote API."""
from __future__ import annotations

import io
import json
import re

import httpx
import pandas as pd
from sqlalchemy import create_engine

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_NUMERIC = re.compile(r"^[+-]?[\d.,\s]+%?$")
_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_cell(value):
    """Web text is untrusted. Stop cells like =HYPERLINK(...) running as spreadsheet formulas."""
    if isinstance(value, str):
        value = _CONTROL_CHARS.sub("", value)
        if value.startswith(_FORMULA_START) and not _NUMERIC.match(value):
            return "'" + value
    return value


def to_dataframe(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _spreadsheet_frame(rows: list[dict]) -> pd.DataFrame:
    return to_dataframe(rows).astype(object).apply(lambda column: column.map(_safe_cell))


def to_csv_bytes(rows: list[dict]) -> bytes:
    # The byte order mark makes Excel read non-English text correctly.
    return _spreadsheet_frame(rows).to_csv(index=False).encode("utf-8-sig")


def to_excel_bytes(rows: list[dict]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        _spreadsheet_frame(rows).to_excel(writer, index=False, sheet_name="Data")
        sheet = writer.sheets["Data"]
        sheet.freeze_panes = "A2"
        for column in sheet.columns:
            longest = max((len(str(cell.value)) for cell in column[:200] if cell.value is not None), default=8)
            sheet.column_dimensions[column[0].column_letter].width = min(longest + 2, 60)
    return buffer.getvalue()


def to_json_bytes(rows: list[dict]) -> bytes:
    return json.dumps(rows, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def to_database(rows: list[dict], db_url: str, table: str, if_exists: str = "append") -> int:
    """Write to any SQLAlchemy database, such as sqlite:///out.db or postgresql+psycopg://..."""
    if not _TABLE_NAME.match(table):
        raise ValueError("Table name may only contain letters, numbers and underscores")
    if if_exists not in {"append", "replace", "fail"}:
        raise ValueError("if_exists must be append, replace or fail")
    engine = create_engine(db_url)
    try:
        to_dataframe(rows).to_sql(table, engine, if_exists=if_exists, index=False, chunksize=1000)
    finally:
        engine.dispose()
    return len(rows)


def to_api(rows: list[dict], url: str, token: str | None = None, batch_size: int = 500) -> int:
    """POST rows as JSON to your API endpoint in batches. Returns how many were sent."""
    if not url.startswith(("http://", "https://")):
        raise ValueError("API URL must start with http:// or https://")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    sent = 0
    with httpx.Client(timeout=60, headers=headers) as client:
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            client.post(url, json={"items": batch}).raise_for_status()
            sent += len(batch)
    return sent
