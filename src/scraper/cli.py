"""Command line: run scrapes, export results, and start the dashboard and API."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import typer

from .config import JobConfig
from .crawler import run_job
from .exporters import to_api, to_csv_bytes, to_database, to_excel_bytes, to_json_bytes
from .storage import Store

app = typer.Typer(no_args_is_help=True, help="Scrape any website and export the data.")


@app.command()
def run(
    url: List[str] = typer.Argument(..., help="One or more start URLs"),
    max_pages: int = typer.Option(50, help="Stop after this many pages"),
    max_items: Optional[int] = typer.Option(None, help="Stop after this many rows (default: no limit)"),
    max_depth: int = typer.Option(2, help="How many links deep to go with --follow-links"),
    delay: float = typer.Option(1.0, help="Seconds to wait between requests"),
    follow_links: bool = typer.Option(False, help="Also crawl other pages on the same site"),
    js: bool = typer.Option(False, help="Render JavaScript with a real browser"),
    config: Optional[Path] = typer.Option(None, help="JSON settings file with custom selectors"),
    csv: Optional[Path] = typer.Option(None, help="Write a CSV file"),
    excel: Optional[Path] = typer.Option(None, help="Write an Excel file"),
    json_out: Optional[Path] = typer.Option(None, "--json", help="Write a JSON file"),
    db_url: Optional[str] = typer.Option(None, help="Database URL, e.g. sqlite:///out.db"),
    table: str = typer.Option("scraped_data", help="Database table name"),
    api_url: Optional[str] = typer.Option(None, help="POST the rows to this API endpoint"),
    db: Optional[Path] = typer.Option(None, help="Location of the tool's own job database"),
):
    """Scrape now and optionally export the results."""
    settings = json.loads(config.read_text(encoding="utf-8")) if config else {}
    settings.update(
        start_urls=list(url), max_pages=max_pages, max_items=max_items, max_depth=max_depth,
        delay_seconds=delay, follow_links=follow_links, render_js=js,
    )
    settings.setdefault("name", url[0])
    store = Store(db)
    job_id = store.create_job(JobConfig(**settings))
    status = run_job(job_id, store)
    job = store.get_job(job_id)
    typer.echo(
        f"Job {job_id}: {status}. {job['pages']} pages, {job['items']} rows, "
        f"{job['errors']} errors. {job['message'] or ''}"
    )
    rows = store.get_items(job_id)
    if rows:
        _export(rows, csv, excel, json_out, db_url, table, api_url)
    raise typer.Exit(0 if status == "completed" else 1)


@app.command()
def export(
    job_id: int,
    csv: Optional[Path] = typer.Option(None),
    excel: Optional[Path] = typer.Option(None),
    json_out: Optional[Path] = typer.Option(None, "--json"),
    db_url: Optional[str] = typer.Option(None),
    table: str = typer.Option("scraped_data"),
    api_url: Optional[str] = typer.Option(None),
    db: Optional[Path] = typer.Option(None, help="Location of the tool's own job database"),
):
    """Export the results of an earlier job."""
    rows = Store(db).get_items(job_id)
    if not rows:
        typer.echo(f"Job {job_id} has no rows.")
        raise typer.Exit(1)
    _export(rows, csv, excel, json_out, db_url, table, api_url)


def _export(rows, csv, excel, json_out, db_url, table, api_url) -> None:
    for path, render in ((csv, to_csv_bytes), (excel, to_excel_bytes), (json_out, to_json_bytes)):
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(render(rows))
            typer.echo(f"Wrote {len(rows)} rows to {path}")
    if db_url:
        typer.echo(f"Wrote {to_database(rows, db_url, table)} rows to table {table}")
    if api_url:
        typer.echo(f"Sent {to_api(rows, api_url)} rows to {api_url}")


@app.command("run-job", hidden=True)
def run_job_command(job_id: int, db: Optional[Path] = typer.Option(None)):
    """Used by the dashboard and API to run a queued job in its own process."""
    run_job(job_id, Store(db))


@app.command()
def jobs(db: Optional[Path] = typer.Option(None, help="Location of the tool's own job database")):
    """List all jobs."""
    for job in Store(db).list_jobs():
        typer.echo(f"{job['id']:>4}  {job['status']:<10} {job['pages']:>5} pages {job['items']:>7} rows  {job['name']}")


@app.command()
def dashboard(port: int = 8501):
    """Open the dashboard in your browser."""
    target = Path(__file__).with_name("dashboard.py")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(target), "--server.port", str(port),
         "--server.address", "127.0.0.1"],
        check=False,
    )


@app.command()
def api(host: str = "127.0.0.1", port: int = 8000):
    """Start the REST API. Interactive docs are at /docs."""
    import uvicorn

    uvicorn.run("scraper.api:app", host=host, port=port)


if __name__ == "__main__":
    app()
