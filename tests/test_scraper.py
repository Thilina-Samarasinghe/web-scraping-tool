import io
import sqlite3

import openpyxl
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from scraper.cleaners import to_number
from scraper.config import FieldRule, JobConfig
from scraper.crawler import run_job
from scraper.exporters import to_csv_bytes, to_database, to_excel_bytes
from scraper.storage import Store


def scrape(tmp_path, **settings):
    store = Store(tmp_path / "jobs.db")
    settings.setdefault("delay_seconds", 0)
    job_id = store.create_job(JobConfig(**settings))
    status = run_job(job_id, store)
    return status, store.get_job(job_id), store.get_items(job_id)


@pytest.mark.parametrize(
    "text, expected",
    [("£51.77", 51.77), ("1,299.50", 1299.5), ("1.299,50", 1299.5), ("1 299", 1299), ("12,5", 12.5),
     ("1,299", 1299), ("0.125", 0.125), ("Rs. 2,500", 2500), ("none", None), ("", None)],
)
def test_to_number(text, expected):
    assert to_number(text) == expected


def test_auto_detects_cards_and_follows_pagination(tmp_path, site):
    status, job, rows = scrape(tmp_path, start_urls=[f"{site}/list/1"])
    assert status == "completed"
    assert job["pages"] == 3
    assert len(rows) == 15
    assert rows[0]["title"] == "Item 1"
    assert rows[0]["price"] == "£1.50"
    assert rows[0]["url"] == f"{site}/item/1"
    assert rows[0]["image"] == f"{site}/img/1.png"


def test_auto_detects_tables(tmp_path, site):
    _, _, rows = scrape(tmp_path, start_urls=[f"{site}/table"])
    assert [(row["Name"], row["Age"]) for row in rows] == [("Ann", "30"), ("Ben", "41")]


def test_page_without_lists_gives_a_summary_row(tmp_path, site):
    _, _, rows = scrape(tmp_path, start_urls=[f"{site}/blank"])
    assert len(rows) == 1
    assert rows[0]["title"] == "T" and rows[0]["heading"] == "Hello"


def test_custom_selectors(tmp_path, site):
    _, _, rows = scrape(
        tmp_path,
        start_urls=[f"{site}/list/1"],
        follow_pagination=False,
        item_selector="article.card",
        fields=[
            FieldRule(name="name", css="h3 a", attr="title"),
            FieldRule(name="cost", css=".price", clean="price"),
            FieldRule(name="link", css="h3 a", attr="href", clean="url"),
        ],
    )
    assert len(rows) == 5
    assert list(rows[0]) == ["name", "cost", "link", "source_url"]  # Columns keep the order you gave.
    assert rows[0]["name"] == "Item 1" and rows[0]["cost"] == 1.5 and rows[0]["link"] == f"{site}/item/1"


def test_user_limits_are_respected(tmp_path, site):
    _, job, _ = scrape(tmp_path, start_urls=[f"{site}/list/1"], max_pages=2)
    assert job["pages"] == 2 and "page limit" in job["message"]

    _, job, rows = scrape(tmp_path, start_urls=[f"{site}/list/1"], max_items=7)
    assert len(rows) == 7 and "item limit" in job["message"]


def test_robots_txt_is_respected_and_can_be_overridden(tmp_path, site):
    status, job, rows = scrape(tmp_path, start_urls=[f"{site}/private"])
    assert status == "failed" and not rows and "robots.txt" in job["message"]

    status, _, rows = scrape(tmp_path, start_urls=[f"{site}/private"], respect_robots=False)
    assert status == "completed" and rows


def test_repeated_refusals_stop_the_job(tmp_path, site):
    urls = [f"{site}/forbidden?{n}" for n in range(6)]
    status, job, _ = scrape(tmp_path, start_urls=urls, max_retries=0)
    assert status == "failed"
    assert job["pages"] == 3 and "refused" in job["message"]


def test_cancelled_job_stays_cancelled(tmp_path, site):
    store = Store(tmp_path / "jobs.db")
    job_id = store.create_job(JobConfig(start_urls=[f"{site}/list/1"]))
    store.cancel(job_id)
    assert run_job(job_id, store) == "cancelled"
    assert store.get_job(job_id)["pages"] == 0


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://not a link", "https://nodot", "example.com"])
def test_invalid_urls_are_rejected(url):
    with pytest.raises(ValidationError):
        JobConfig(start_urls=[url])


def test_duplicate_rows_are_dropped(tmp_path, site):
    # The same content reached through two URLs should only be stored once.
    _, job, rows = scrape(tmp_path, start_urls=[f"{site}/table", f"{site}/table?again"], follow_pagination=False)
    assert job["pages"] == 2
    assert [row["Name"] for row in rows] == ["Ann", "Ben"]


def test_csv_and_excel_neutralise_formulas(tmp_path, site):
    _, _, rows = scrape(tmp_path, start_urls=[f"{site}/evil"])
    csv_frame = pd.read_csv(io.BytesIO(to_csv_bytes(rows)), encoding="utf-8-sig")
    assert csv_frame["A"][0].startswith("'=")
    assert csv_frame["B"][0] == -5  # Real negative numbers are left alone.

    sheet = openpyxl.load_workbook(io.BytesIO(to_excel_bytes(rows))).active
    assert sheet["A2"].data_type == "s" and sheet["A2"].value.startswith("'=")


def test_database_export(tmp_path):
    target = tmp_path / "out.db"
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    assert to_database(rows, f"sqlite:///{target.as_posix()}", "things") == 2
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT COUNT(*) FROM things").fetchone()[0] == 2
    with pytest.raises(ValueError):
        to_database(rows, f"sqlite:///{target.as_posix()}", "bad; DROP TABLE things")


def test_rest_api(tmp_path, site, monkeypatch):
    monkeypatch.setenv("SCRAPER_DB", str(tmp_path / "api.db"))
    from scraper.api import app

    store = Store()
    job_id = store.create_job(JobConfig(start_urls=[f"{site}/table"], delay_seconds=0))
    run_job(job_id, store)

    client = TestClient(app)
    assert client.get("/jobs").json()[0]["id"] == job_id
    body = client.get(f"/jobs/{job_id}/items").json()
    assert body["total"] == 2 and body["items"][0]["Name"] == "Ann"
    assert client.get(f"/jobs/{job_id}/export.csv").status_code == 200
    assert client.get(f"/jobs/{job_id}/export.xlsx").status_code == 200
    assert client.get("/jobs/99999").status_code == 404

    monkeypatch.setenv("SCRAPER_API_KEY", "secret")
    assert client.get("/jobs").status_code == 401
    assert client.get("/jobs", headers={"X-API-Key": "secret"}).status_code == 200
