"""Streamlit dashboard: start scrapes, watch progress, browse data and export it."""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from scraper.config import FieldRule, JobConfig
from scraper.crawler import launch_job
from scraper.exporters import to_api, to_csv_bytes, to_database, to_excel_bytes, to_json_bytes
from scraper.storage import Store

ACTIVE = {"queued", "running"}
STATUS_LABELS = {
    "queued": "⏳ Queued",
    "running": "🔄 Running",
    "completed": "✅ Completed",
    "failed": "❌ Failed",
    "cancelled": "⏹️ Stopped",
}
EXCEL_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

st.set_page_config(page_title="Web Scraping Tool", page_icon="🕸️", layout="wide")
store = Store()


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def jobs_frame(jobs: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ID": job["id"],
                "Name": job["name"],
                "Status": status_label(job["status"]),
                "Pages": job["pages"],
                "Rows": job["items"],
                "Errors": job["errors"],
                "Result": job["message"] or "",
                "Created (UTC)": job["created_at"],
            }
            for job in jobs
        ]
    )


def job_title(job: dict) -> str:
    return f"#{job['id']} · {job['name']} · {job['items']} rows"


def wait_for_job(job_id: int, process, label: str) -> dict:
    """Show live progress until the worker process finishes, then return the job."""
    with st.status(label, expanded=False) as progress:
        job = store.get_job(job_id)
        while job["status"] in ACTIVE and process.poll() is None:
            pages = f"{job['pages']} page{'' if job['pages'] == 1 else 's'}"
            progress.update(label=f"{label} {pages}, {job['items']:,} rows so far")
            time.sleep(0.5)
            job = store.get_job(job_id)
        job = store.get_job(job_id)
        if job["status"] in ACTIVE:  # The worker died without recording a result.
            store.finish(job_id, "failed", f"The scraping process stopped unexpectedly (exit code {process.returncode})")
            job = store.get_job(job_id)
        progress.update(label="Finished", state="complete" if job["status"] == "completed" else "error")
    return job


# --- Home: paste a link, get the data ------------------------------------------------------

def page_home() -> None:
    st.title("🕸️ Web Scraping Tool")
    st.caption("Paste a website link to get its data as a table you can download.")

    with st.form("quick_extract"):
        url = st.text_input("Website link", placeholder="https://books.toscrape.com/")
        pages_col, js_col, button_col = st.columns([2, 2, 1], vertical_alignment="bottom")
        pages = pages_col.number_input(
            "Pages to scrape", min_value=1, max_value=1000, value=1,
            help="More than 1 follows the site's “next page” links.",
        )
        render_js = js_col.checkbox(
            "Page needs JavaScript", help="Tick this if the result comes back empty. It is slower."
        )
        submitted = button_col.form_submit_button("Extract data", type="primary", width="stretch")

    if submitted:
        url = url.strip()
        if url and "://" not in url:
            url = "https://" + url
        try:
            config = JobConfig(
                name=url, start_urls=[url], max_pages=int(pages), follow_pagination=pages > 1, render_js=render_js
            )
        except ValidationError:
            st.session_state.pop("home_job", None)  # Don't show an older result under the error.
            st.error("Please enter a full website link, for example https://example.com")
        else:
            job_id = store.create_job(config)
            process = launch_job(job_id, str(store.path))
            wait_for_job(job_id, process, "Extracting data…")
            st.session_state["home_job"] = job_id
            st.session_state["selected_job"] = job_id

    job = store.get_job(st.session_state["home_job"]) if "home_job" in st.session_state else None
    if job:
        _show_home_result(job)
    else:
        _show_recent_jobs()


def _show_home_result(job: dict) -> None:
    rows = store.get_items(job["id"])
    if job["status"] != "completed":
        st.error(f"{status_label(job['status'])}: {job['message'] or 'see the Jobs page for details'}")
    elif not rows or (len(rows) == 1 and "heading" in rows[0]):
        st.warning(
            "No list or table was found on this page, so only a page summary was saved. "
            "Try ticking **Page needs JavaScript**, or use **Advanced scrape** to pick the fields yourself."
        )
    else:
        st.success(f"Found **{len(rows):,} rows** from {job['pages']} page{'s' if job['pages'] != 1 else ''}.")

    for entry in [e for e in store.get_logs(job["id"]) if e["level"] != "info"][:5]:
        st.caption(f"⚠️ {entry['message']}")

    if not rows:
        return
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=min(38 + 35 * len(rows), 460))

    base = f"job_{job['id']}"
    csv_col, excel_col, json_col, _ = st.columns([1, 1, 1, 3])
    csv_col.download_button("Download CSV", to_csv_bytes(rows), f"{base}.csv", "text/csv", width="stretch")
    excel_col.download_button("Download Excel", to_excel_bytes(rows), f"{base}.xlsx", EXCEL_TYPE, width="stretch")
    json_col.download_button("Download JSON", to_json_bytes(rows), f"{base}.json", "application/json", width="stretch")
    st.caption(f"Saved as job #{job['id']}. To send it to a database or an API, open **Data and export**.")


def _show_recent_jobs() -> None:
    jobs = store.list_jobs()[:5]
    if not jobs:
        st.info("**How it works:** paste a link above and click **Extract data**. The tool finds tables, "
                "product lists and other repeated content automatically.")
        return
    st.subheader("Recent scrapes")
    recent = jobs_frame(jobs)[["ID", "Name", "Status", "Pages", "Rows", "Created (UTC)"]]
    st.dataframe(recent, width="stretch", hide_index=True)


# --- Advanced scrape -----------------------------------------------------------------------

def page_new_scrape() -> None:
    st.title("Advanced scrape")
    st.caption("Choose exactly how much to collect, which links to follow, and which fields to extract.")

    with st.form("new_job"):
        name = st.text_input("Job name", placeholder="Book prices")
        urls = st.text_area("Website URLs (one per line)", placeholder="https://books.toscrape.com/", height=90)

        st.subheader("How much to scrape")
        left, middle, right, far = st.columns(4)
        max_pages = left.number_input("Max pages", min_value=1, value=50, step=10)
        limit_items = middle.number_input("Max rows (0 = no limit)", min_value=0, value=0, step=100)
        delay = right.number_input("Seconds between requests", min_value=0.0, value=1.0, step=0.5)
        depth = far.number_input("Link depth", min_value=0, value=2, help="Only used when following links.")

        st.subheader("Where to go")
        left, middle, right = st.columns(3)
        follow_pagination = left.checkbox("Follow “next page” links", value=True)
        follow_links = middle.checkbox("Follow other links on the site")
        render_js = right.checkbox("Page needs JavaScript", help="Uses a real browser. Slower, but sees dynamic content.")

        with st.expander("Extract specific fields (optional)"):
            st.caption("Leave the table empty for automatic detection. Selectors are CSS, e.g. `h3 a` or `.price`.")
            item_selector = st.text_input("Selector for each item", placeholder="article.product_pod")
            fields = st.data_editor(
                pd.DataFrame(columns=["name", "css", "attr", "clean"]).astype(str),
                num_rows="dynamic",
                width="stretch",
                column_config={
                    "name": st.column_config.TextColumn("Column name"),
                    "css": st.column_config.TextColumn("CSS selector"),
                    "attr": st.column_config.TextColumn("Attribute (optional)", help="e.g. href, title, src"),
                    "clean": st.column_config.SelectboxColumn("Clean as", options=["text", "number", "price", "url"]),
                },
            )

        with st.expander("Advanced"):
            next_selector = st.text_input("Next-page selector", placeholder="Blank = detect automatically")
            url_pattern = st.text_input("Only follow URLs matching (regex)", placeholder="/catalogue/")
            respect_robots = st.checkbox(
                "Respect robots.txt",
                value=True,
                help="Leave this on unless you own the site or have permission from its owner.",
            )

        test_col, run_col, _ = st.columns([1, 1, 4])
        test = test_col.form_submit_button("Test 1 page")
        start = run_col.form_submit_button("Start scraping", type="primary")

    if not (test or start):
        return

    try:
        rules = [
            FieldRule(name=row["name"], css=row["css"], attr=row.get("attr") or None, clean=row.get("clean") or "text")
            for row in fields.fillna("").to_dict("records")
            if str(row.get("name", "")).strip() and str(row.get("css", "")).strip()
        ]
        start_urls = [line.strip() for line in urls.splitlines() if line.strip()]
        config = JobConfig(
            name=name.strip() or (start_urls[0] if start_urls else "Untitled scrape"),
            start_urls=start_urls,
            item_selector=item_selector.strip() or None,
            fields=rules,
            follow_pagination=follow_pagination and not test,
            next_selector=next_selector.strip() or None,
            follow_links=follow_links and not test,
            url_pattern=url_pattern.strip() or None,
            max_pages=1 if test else int(max_pages),
            max_items=int(limit_items) or None,
            max_depth=int(depth),
            delay_seconds=float(delay),
            render_js=render_js,
            respect_robots=respect_robots,
        )
    except ValidationError as exc:
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"]) or "input"
            st.error(f"{location}: {error['msg']}")
        return

    if test:
        config.name = f"Test: {config.name}"
    job_id = store.create_job(config)
    process = launch_job(job_id, str(store.path))
    if test:
        _show_test_result(job_id, process)
    else:
        st.session_state["selected_job"] = job_id
        st.success(f"Job #{job_id} started. Open **Jobs** to watch it run.")


def _show_test_result(job_id: int, process) -> None:
    job = wait_for_job(job_id, process, "Testing one page…")
    rows = store.get_items(job_id, limit=50)
    if job["status"] == "completed":
        summary = f"Test finished: found {job['items']} rows on the first page."
        if not rows:
            summary += " Try ticking “Page needs JavaScript”, or add custom selectors."
        st.write(f"**{status_label(job['status'])}** · {summary}")
    else:
        st.write(f"**{status_label(job['status'])}** · {job['message'] or ''}")
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch")
    for entry in store.get_logs(job_id):
        if entry["level"] != "info":
            st.warning(entry["message"])


# --- Overview and jobs ---------------------------------------------------------------------

def page_jobs() -> None:
    st.title("Jobs")
    jobs = store.list_jobs()
    if not jobs:
        st.info("No jobs yet. Paste a link on **Home** to start.")
        return

    total, running, pages, rows = st.columns(4)
    total.metric("Jobs", f"{len(jobs):,}")
    running.metric("Running now", f"{sum(job['status'] in ACTIVE for job in jobs):,}")
    pages.metric("Pages scraped", f"{sum(job['pages'] for job in jobs):,}")
    rows.metric("Rows collected", f"{sum(job['items'] for job in jobs):,}")

    _live_table()

    finished = [job for job in jobs if job["items"]][:15]
    if finished:
        st.subheader("Rows collected per job")
        chart = pd.DataFrame(
            {"Job": [f"#{job['id']} {job['name'][:30]}" for job in finished], "Rows": [job["items"] for job in finished]}
        )
        st.bar_chart(chart, x="Job", y="Rows", horizontal=True, color="#2a78d6", height=60 + 32 * len(finished))

    st.subheader("Job details")
    by_id = {job["id"]: job for job in jobs}
    ids = list(by_id)
    remembered = st.session_state.get("selected_job")
    chosen = st.selectbox(
        "Job",
        ids,
        index=ids.index(remembered) if remembered in by_id else 0,
        format_func=lambda job_id: job_title(by_id[job_id]),
    )
    st.session_state["selected_job"] = chosen
    job = by_id[chosen]

    if job["status"] in ACTIVE:
        if st.button("Stop job"):
            store.cancel(chosen)
            st.rerun()
    elif st.button("Delete job"):
        store.delete_job(chosen)
        st.session_state.pop("selected_job", None)
        st.rerun()

    logs = store.get_logs(chosen)
    if logs:
        st.dataframe(
            pd.DataFrame(logs).rename(columns={"at": "Time (UTC)", "level": "Level", "url": "URL", "message": "Message"}),
            width="stretch",
            hide_index=True,
            height=min(38 + 35 * len(logs), 400),
        )


@st.fragment(run_every="2s")
def _live_table() -> None:
    """Refreshes every 2 seconds without disturbing the rest of the page."""
    st.dataframe(jobs_frame(store.list_jobs()), width="stretch", hide_index=True)


# --- Data and export -----------------------------------------------------------------------

def page_data() -> None:
    st.title("Data and export")
    jobs = [job for job in store.list_jobs() if job["items"]]
    if not jobs:
        st.info("Nothing to show yet. Finish a scrape first.")
        return

    by_id = {job["id"]: job for job in jobs}
    ids = list(by_id)
    remembered = st.session_state.get("selected_job")
    chosen = st.selectbox(
        "Job",
        ids,
        index=ids.index(remembered) if remembered in by_id else 0,
        format_func=lambda job_id: job_title(by_id[job_id]),
    )
    st.session_state["selected_job"] = chosen

    rows = store.get_items(chosen)
    frame = pd.DataFrame(rows)

    search = st.text_input("Search rows", placeholder="Type to filter…")
    shown = frame
    if search:
        matches = frame.astype(str).apply(lambda col: col.str.contains(search, case=False, regex=False)).any(axis=1)
        shown = frame[matches]
    st.caption(f"Showing {len(shown):,} of {len(frame):,} rows and {frame.shape[1]} columns")
    st.dataframe(shown, width="stretch", hide_index=True, height=420)

    st.subheader("Export")
    tab_files, tab_db, tab_api = st.tabs(["Files", "Database", "API"])

    with tab_files:
        csv_col, excel_col, json_col, _ = st.columns([1, 1, 1, 3])
        base = f"job_{chosen}"
        csv_col.download_button("Download CSV", to_csv_bytes(rows), f"{base}.csv", "text/csv")
        excel_col.download_button("Download Excel", to_excel_bytes(rows), f"{base}.xlsx", EXCEL_TYPE)
        json_col.download_button("Download JSON", to_json_bytes(rows), f"{base}.json", "application/json")

    with tab_db:
        st.caption(
            "SQLite works straight away. PostgreSQL and MySQL need their driver: "
            "`pip install \"psycopg[binary]\"` or `pip install pymysql`."
        )
        with st.form("to_db"):
            db_url = st.text_input(
                "Database URL",
                placeholder="sqlite:///exports/data.db   or   postgresql+psycopg://user:password@host/db",
                type="password",
            )
            left, right = st.columns(2)
            table = left.text_input("Table", value="scraped_data")
            mode = right.selectbox("If the table exists", ["append", "replace", "fail"])
            if st.form_submit_button("Write to database"):
                try:
                    count = to_database(rows, db_url.strip(), table.strip(), mode)
                    st.success(f"Wrote {count:,} rows to `{table}`.")
                except Exception as exc:  # Show driver and connection errors to the user.
                    st.error(f"Could not write to the database: {_without_secrets(exc, db_url)}")

    with tab_api:
        st.caption("Send the rows to your own endpoint as JSON: `POST {\"items\": [...]}`, in batches of 500.")
        with st.form("to_api"):
            api_url = st.text_input("Endpoint URL", placeholder="https://example.com/api/import")
            token = st.text_input("Bearer token (optional)", type="password")
            if st.form_submit_button("Send to API"):
                try:
                    st.success(f"Sent {to_api(rows, api_url.strip(), token.strip() or None):,} rows.")
                except Exception as exc:  # Show network and HTTP errors to the user.
                    st.error(f"Could not send: {_without_secrets(exc, token)}")
        st.divider()
        st.caption("Other apps can also read this data from the built-in API. Start it with `scraper api`, then use:")
        st.code(f"GET http://127.0.0.1:8000/jobs/{chosen}/items?limit=100\nGET http://127.0.0.1:8000/docs")


def _without_secrets(exc: Exception, secret: str) -> str:
    text = str(exc)
    return text.replace(secret, "***") if secret else text


pages = st.navigation(
    [
        st.Page(page_home, title="Home", icon="🏠", default=True),
        st.Page(page_new_scrape, title="Advanced scrape", icon="⚙️", url_path="advanced"),
        st.Page(page_jobs, title="Jobs", icon="📋", url_path="jobs"),
        st.Page(page_data, title="Data and export", icon="📊", url_path="data"),
    ]
)
pages.run()
