# Web Scraping Tool

Scrape a website and export the data to CSV, Excel, JSON, a SQL database or an API. You can use the dashboard or the command line, and each user sets their own limits for each job.

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Only needed for pages that require JavaScript (a large download):

```powershell
pip install -e ".[js]"
playwright install chromium
```

## Dashboard

```powershell
scraper dashboard
```

Then open http://127.0.0.1:8501.

| Page | What it does |
|---|---|
| **Home** | Paste a link, click **Extract data**, see the table and download it |
| **Advanced scrape** | Set limits, follow links, choose fields, test one page, then start |
| **Jobs** | Watch progress, read logs, stop or delete jobs |
| **Data and export** | Search rows, download CSV, Excel or JSON, write to a database, or send to an API |

## Command line

```powershell
# Automatic detection, with your own limits
scraper run https://books.toscrape.com/ --max-pages 5 --csv exports/books.csv --excel exports/books.xlsx

# Write to a database
scraper run https://books.toscrape.com/ --max-pages 5 --db-url sqlite:///exports/books.db --table books

# Custom selectors from a settings file
scraper run https://books.toscrape.com/ --config examples/books.json --csv exports/books.csv

# Export an earlier job
scraper jobs
scraper export 1 --excel exports/job1.xlsx
```

## Limits each user controls

| Setting | Dashboard | Command line |
|---|---|---|
| Pages per job | Max pages | `--max-pages` |
| Rows per job | Max rows | `--max-items` |
| Wait between requests | Seconds between requests | `--delay` |
| How far to follow links | Link depth | `--max-depth`, `--follow-links` |
| Browser rendering | Page needs JavaScript | `--js` |

## How extraction works

- **Automatic:** finds the richest data on each page from tables, repeated blocks such as product cards, and JSON-LD. If none exist, it saves a one-row page summary.
- **Custom:** you give CSS selectors for each column. Use this when automatic results aren't right.

## REST API

```powershell
scraper api    # interactive docs at http://127.0.0.1:8000/docs
```

| Request | Purpose |
|---|---|
| `POST /jobs` | Start a job |
| `GET /jobs`, `GET /jobs/{id}` | List jobs or check one |
| `POST /jobs/{id}/cancel` | Stop a job |
| `GET /jobs/{id}/items?limit=&offset=` | Read rows as JSON |
| `GET /jobs/{id}/export.csv`, `/export.xlsx` | Download a file |

The API and dashboard only listen on your own computer by default. **Before exposing the API to a network, set an `SCRAPER_API_KEY` environment variable** (clients send it as `X-API-Key`). The dashboard has no login, so don't expose it without adding one.

## Databases

SQLite works straight away. For other databases, install a driver and use its URL:

```powershell
pip install "psycopg[binary]"   # postgresql+psycopg://user:password@host/dbname
pip install pymysql             # mysql+pymysql://user:password@host/dbname
```

## What it won't do

- **Blocked sites:** it doesn't bypass CAPTCHAs, logins or anti-bot systems. It stops after three refusals in a row and tells you why.
- **Disallowed pages:** it follows `robots.txt` by default. Only turn this off for sites you own or have permission to scrape.
- **Your responsibility:** check each site's terms of service and privacy laws such as GDPR before collecting data, especially personal data.

## Tests

```powershell
pytest
```

Tests use a local test website, so they never contact real sites.
