"""SQLite store for jobs, scraped rows and logs. Shared by the CLI, dashboard and API."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import JobConfig

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    config TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    pages INTEGER NOT NULL DEFAULT 0,
    items INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    data TEXT NOT NULL,
    hash TEXT NOT NULL,
    UNIQUE (job_id, hash)
);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    level TEXT NOT NULL,
    url TEXT,
    message TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def default_db_path() -> Path:
    return Path(os.environ.get("SCRAPER_DB", "data/scraper.db"))


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    # --- Jobs ---
    def create_job(self, config: JobConfig) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO jobs (name, config, created_at) VALUES (?, ?, ?)",
                (config.name, config.model_dump_json(), now()),
            )
            return cursor.lastrowid

    def get_job(self, job_id: int) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_jobs(self) -> list[dict]:
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY id DESC")]

    def get_config(self, job_id: int) -> JobConfig:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(f"No job {job_id}")
        return JobConfig.model_validate_json(job["config"])

    def mark_started(self, job_id: int) -> bool:
        """Returns False if the job was cancelled before it could start."""
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE jobs SET status='running', started_at=? WHERE id=? AND status='queued'", (now(), job_id)
            )
            return cursor.rowcount == 1

    def finish(self, job_id: int, status: str, message: str | None = None) -> None:
        """Record the outcome. A job the user cancelled stays cancelled."""
        with self._connect() as db:
            db.execute(
                "UPDATE jobs SET status=?, message=?, finished_at=? WHERE id=? AND status IN ('queued','running')",
                (status, message, now(), job_id),
            )

    def cancel(self, job_id: int) -> None:
        self.finish(job_id, "cancelled", "Stopped by user")

    def is_cancelled(self, job_id: int) -> bool:
        job = self.get_job(job_id)
        return job is None or job["status"] == "cancelled"

    def delete_job(self, job_id: int) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    def add_page(self, job_id: int) -> None:
        with self._connect() as db:
            db.execute("UPDATE jobs SET pages = pages + 1 WHERE id=?", (job_id,))

    # --- Items ---
    def add_items(self, job_id: int, source_url: str, rows: list[dict]) -> int:
        """Store rows, ignoring exact duplicates within the job. Returns how many were new."""
        added = 0
        with self._connect() as db:
            for row in rows:
                # Keep the column order for display; sort keys only for the duplicate check.
                data = json.dumps(row, ensure_ascii=False, default=str)
                canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                digest = hashlib.sha256(canonical.encode()).hexdigest()
                cursor = db.execute(
                    "INSERT OR IGNORE INTO items (job_id, source_url, data, hash) VALUES (?, ?, ?, ?)",
                    (job_id, source_url, data, digest),
                )
                added += cursor.rowcount
            if added:
                db.execute("UPDATE jobs SET items = items + ? WHERE id=?", (added, job_id))
        return added

    def get_items(self, job_id: int, limit: int | None = None, offset: int = 0) -> list[dict]:
        query = "SELECT source_url, data FROM items WHERE job_id=? ORDER BY id LIMIT ? OFFSET ?"
        with self._connect() as db:
            rows = db.execute(query, (job_id, -1 if limit is None else limit, offset)).fetchall()
        return [{**json.loads(row["data"]), "source_url": row["source_url"]} for row in rows]

    # --- Logs ---
    def log(self, job_id: int, level: str, message: str, url: str | None = None) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO logs (job_id, at, level, url, message) VALUES (?, ?, ?, ?, ?)",
                (job_id, now(), level, url, message),
            )
            if level == "error":
                db.execute("UPDATE jobs SET errors = errors + 1 WHERE id=?", (job_id,))

    def get_logs(self, job_id: int, limit: int = 200) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT at, level, url, message FROM logs WHERE job_id=? ORDER BY id DESC LIMIT ?", (job_id, limit)
            )
            return [dict(row) for row in rows]
