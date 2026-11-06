"""REST API over scraped data. Other apps can start jobs and read results."""
from __future__ import annotations

import os
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response

from .config import JobConfig
from .crawler import launch_job
from .exporters import to_csv_bytes, to_excel_bytes
from .storage import Store

EXCEL_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def require_key(x_api_key: str | None = Header(default=None)) -> None:
    """If SCRAPER_API_KEY is set, every request must send it as X-API-Key."""
    expected = os.environ.get("SCRAPER_API_KEY")
    if expected and not secrets.compare_digest(x_api_key or "", expected):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")


app = FastAPI(title="Web Scraping Tool API", version="0.1.0", dependencies=[Depends(require_key)])


def _job_or_404(store: Store, job_id: int) -> dict:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job {job_id}")
    return job


@app.get("/jobs")
def list_jobs() -> list[dict]:
    return [{key: value for key, value in job.items() if key != "config"} for job in Store().list_jobs()]


@app.post("/jobs", status_code=202)
def start_job(config: JobConfig) -> dict:
    store = Store()
    job_id = store.create_job(config)
    launch_job(job_id, str(store.path))
    return {"id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}")
def get_job(job_id: int) -> dict:
    return _job_or_404(Store(), job_id)


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int) -> dict:
    store = Store()
    _job_or_404(store, job_id)
    store.cancel(job_id)
    return store.get_job(job_id)


@app.get("/jobs/{job_id}/items")
def get_items(job_id: int, limit: int = Query(100, ge=1, le=10000), offset: int = Query(0, ge=0)) -> dict:
    store = Store()
    job = _job_or_404(store, job_id)
    return {"total": job["items"], "limit": limit, "offset": offset, "items": store.get_items(job_id, limit, offset)}


@app.get("/jobs/{job_id}/export.csv")
def export_csv(job_id: int) -> Response:
    store = Store()
    _job_or_404(store, job_id)
    return Response(
        to_csv_bytes(store.get_items(job_id)),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="job_{job_id}.csv"'},
    )


@app.get("/jobs/{job_id}/export.xlsx")
def export_xlsx(job_id: int) -> Response:
    store = Store()
    _job_or_404(store, job_id)
    return Response(
        to_excel_bytes(store.get_items(job_id)),
        media_type=EXCEL_TYPE,
        headers={"Content-Disposition": f'attachment; filename="job_{job_id}.xlsx"'},
    )
