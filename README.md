# Web Scraping Tool

Paste a website link and get its data as a table. Download it as CSV, Excel or JSON, save it to a database, or send it to an API. Use it from a dashboard in your browser, from the command line, or from your own programs through a REST API.

## Features

| Area | What you get |
|---|---|
| **Dashboard** | Paste a link and extract in one click, plus advanced options, live job progress, logs, data search and exports |
| **Works on most sites** | Automatically detects tables, product lists, search results, cards and structured data (JSON-LD) |
| **Custom extraction** | Choose exactly which fields to collect with CSS selectors |
| **JavaScript pages** | Optional real-browser rendering for sites that load content with JavaScript |
| **Crawling** | Follows "next page" links automatically and can also follow other links on the same site |
| **Your limits** | Each job sets its own maximum pages, maximum rows, link depth and delay between requests |
| **Exports** | CSV, Excel, JSON, any SQL database (SQLite, PostgreSQL, MySQL) and your own API endpoint |
| **REST API** | Other programs can start jobs, check progress and download results |
| **Command line** | Everything is scriptable, for example for scheduled runs |
| **Polite and safe** | Respects `robots.txt` and crawl delays, retries with backoff, and stops when a site refuses access |
| **Clean data** | Removes duplicate rows, cleans text, turns prices into numbers, and makes spreadsheet exports safe |

## Contents

- [Installation](#installation)
- [Open the dashboard](#open-the-dashboard)
- [Dashboard pages](#dashboard-pages)
- [How extraction works](#how-extraction-works)
- [Limits and settings](#limits-and-settings)
- [Exporting data](#exporting-data)
- [Command line](#command-line)
- [Settings files](#settings-files)
- [REST API](#rest-api)
- [Built-in protections](#built-in-protections)
- [Where data is stored](#where-data-is-stored)
- [Project structure](#project-structure)
- [Running the tests](#running-the-tests)
- [Troubleshooting](#troubleshooting)
- [Responsible use](#responsible-use)

## Installation

Requires **Python 3.10 or newer**. These steps are for Windows PowerShell.

```powershell
cd "D:\web scarping\web-scraping-tool"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### Optional: JavaScript pages

Only needed for sites that load their content with JavaScript. It's a large download, so use a stable connection.

```powershell
pip install -e ".[js]"
playwright install --only-shell chromium
```

### Optional: other databases

SQLite works without anything extra. For other databases, install a driver:

```powershell
pip install -e ".[postgres]"   # PostgreSQL
pip install -e ".[mysql]"      # MySQL / MariaDB
```

> **Always activate the environment first.** Every time you open a new PowerShell window, run `.venv\Scripts\Activate.ps1` in the project folder. You'll see `(.venv)` at the start of the prompt.

## Open the dashboard

```powershell
cd "D:\web scarping\web-scraping-tool"
.venv\Scripts\Activate.ps1
scraper dashboard
```

Your browser opens **http://127.0.0.1:8501**. Keep the PowerShell window open while you use the dashboard, and press `Ctrl + C` there to stop it. To use a different port, run `scraper dashboard --port 8502`.

## Dashboard pages

### 🏠 Home: quick extract

The fastest way to get data:

1. Paste a link. You can leave out `https://`, so `books.toscrape.com` works.
2. Choose **Pages to scrape**. More than 1 follows the site's "next page" links.
3. Tick **Page needs JavaScript** if the results come back empty.
4. Click **Extract data**.

A live counter shows the pages and rows found so far. When it finishes, the results appear in a table with **Download CSV**, **Download Excel** and **Download JSON** buttons. If no list or table is found, the page tells you what to try next. Before you scrape anything, the Home page lists your five most recent scrapes.

### ⚙️ Advanced scrape

Full control over a job:

- **Several start URLs**, one per line
- **How much to scrape:** max pages, max rows, seconds between requests, link depth
- **Where to go:** follow "next page" links, follow other links on the site, render JavaScript
- **Extract specific fields:** a selector for each item plus a table of columns (name, CSS selector, optional attribute, clean as text, number, price or URL)
- **Advanced:** a custom next-page selector, a regex that limits which URLs to follow, and the `robots.txt` setting
- **Test 1 page** previews the results before you click **Start scraping** for the full job

### 📋 Jobs

- Totals for jobs, jobs running now, pages scraped and rows collected
- A table of all jobs that updates live every 2 seconds
- A chart of rows collected per job
- A log for each job showing every page fetched, every warning and every error
- **Stop job** for running jobs and **Delete job** for finished ones

### 📊 Data and export

- Choose a job and browse all its rows
- **Search rows** filters across every column
- **Files tab:** download CSV, Excel or JSON
- **Database tab:** write the rows to any SQL database, choosing whether to append, replace or fail if the table already exists
- **API tab:** send the rows to your own endpoint, with an optional bearer token

## How extraction works

### Automatic mode (default)

On every page, the tool looks for data in three places and keeps whichever has the most:

| Source | Example |
|---|---|
| **HTML tables** | Price lists, rankings, schedules. Table headers become column names |
| **Repeated blocks** | Product cards, search results, article lists. Picks up `title`, `price`, `url`, `image` and `text` |
| **Structured data (JSON-LD)** | Product, article or event data that many sites embed for search engines |

Menus, headers, footers and navigation links are ignored. If a page has none of these, you get one summary row with its `title`, `heading`, `description`, `text` and `url`.

### Custom mode

Use this when automatic mode misses fields. You give:

- **Item selector:** the CSS selector for each repeated item, such as `article.product_pod`. Leave it blank to get one row per page.
- **Fields:** a name, a CSS selector, and optionally an attribute (such as `href`, `title` or `src`) and a cleaner:

| Cleaner | What it does | Example |
|---|---|---|
| `text` | Trims and tidies whitespace | `"  In   stock "` → `"In stock"` |
| `number` | Extracts a number | `"1,299 views"` → `1299` |
| `price` | Extracts a price as a number | `"£51.77"` → `51.77`, `"1.299,50 €"` → `1299.5` |
| `url` | Makes a link absolute | `"../page-2.html"` → `"https://site.com/page-2.html"` |

**Tip:** to find a selector, right-click an element in your browser, choose **Inspect**, and look at its tag and class.

### Finding more pages

- **Pagination:** finds "next" links automatically (`rel="next"`, `.next a`, or links labelled "Next", "›" or "»"). You can also give your own next-page selector.
- **Link following:** visits other pages on the same site, up to the link depth you choose, optionally only URLs matching a regex such as `/products/`.

## Limits and settings

| Setting | Default | Dashboard | Command line |
|---|---|---|---|
| Max pages per job | 50 (1 on Home) | Max pages | `--max-pages` |
| Max rows per job | No limit | Max rows (0 = no limit) | `--max-items` |
| Seconds between requests | 1 | Seconds between requests | `--delay` |
| Follow other links | Off | Follow other links on the site | `--follow-links` |
| Link depth | 2 | Link depth | `--max-depth` |
| Render JavaScript | Off | Page needs JavaScript | `--js` |
| Respect `robots.txt` | On | Advanced → Respect robots.txt | settings file |
| Request timeout | 30 seconds | — | settings file |
| Retries per page | 3 | — | settings file |

A job stops at whichever limit it reaches first, and its result says which one.

## Exporting data

| Format | Dashboard | Command line | Notes |
|---|---|---|---|
| CSV | Download CSV | `--csv file.csv` | UTF-8, opens correctly in Excel |
| Excel | Download Excel | `--excel file.xlsx` | Frozen header row, sized columns |
| JSON | Download JSON | `--json file.json` | A list of objects |
| SQL database | Database tab | `--db-url URL --table NAME` | Appends to the table by default |
| Your API | API tab | `--api-url URL` | Sends `POST {"items": [...]}` in batches of 500 |

Database URL examples:

```
sqlite:///exports/data.db
postgresql+psycopg://user:password@localhost:5432/mydb
mysql+pymysql://user:password@localhost:3306/mydb
```

## Command line

Activate the environment first. `scraper --help` lists every command, and `scraper run --help` lists every option.

```powershell
# Quick scrape to Excel
scraper run https://books.toscrape.com/ --max-pages 5 --excel exports/books.xlsx

# Several formats at once
scraper run https://books.toscrape.com/ --max-pages 5 --csv exports/books.csv --json exports/books.json

# Save to a database
scraper run https://books.toscrape.com/ --max-pages 5 --db-url sqlite:///exports/books.db --table books

# Send to your own API
scraper run https://books.toscrape.com/ --max-pages 2 --api-url https://example.com/api/import

# Crawl a site by following links, slowly
scraper run https://example.com/ --follow-links --max-depth 2 --max-pages 100 --delay 2

# A JavaScript page
scraper run https://quotes.toscrape.com/js/ --js --max-pages 3 --csv exports/quotes.csv

# Custom selectors from a settings file
scraper run https://books.toscrape.com/ --config examples/books.json --csv exports/books.csv

# List jobs, and export an earlier one
scraper jobs
scraper export 1 --excel exports/job1.xlsx

# Start the dashboard or the API
scraper dashboard
scraper api
```

| Command | Purpose |
|---|---|
| `scraper run URL...` | Scrape now and optionally export the results |
| `scraper export JOB_ID` | Export an earlier job to files, a database or an API |
| `scraper jobs` | List all jobs with status, pages and rows |
| `scraper dashboard [--port N]` | Open the dashboard |
| `scraper api [--host H] [--port N]` | Start the REST API |

`run` exits with code `0` when the job completes and `1` otherwise, which is useful in scripts.

## Settings files

`--config` takes a JSON file with any job settings. Command-line options for URLs and limits override the file. Example (`examples/books.json`):

```json
{
  "name": "Books (custom selectors)",
  "item_selector": "article.product_pod",
  "fields": [
    {"name": "title", "css": "h3 a", "attr": "title"},
    {"name": "price", "css": ".price_color", "clean": "price"},
    {"name": "in_stock", "css": ".availability"},
    {"name": "link", "css": "h3 a", "attr": "href", "clean": "url"}
  ]
}
```

All available settings:

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `name` | text | `"Untitled scrape"` | Job name shown in the dashboard |
| `start_urls` | list | required | Where to start (`http` or `https` only) |
| `item_selector` | CSS | none | Selector for each item in custom mode |
| `fields` | list | `[]` | Columns for custom mode. Empty means automatic mode |
| `follow_pagination` | true/false | `true` | Follow "next page" links |
| `next_selector` | CSS | auto | Your own next-page link selector |
| `follow_links` | true/false | `false` | Follow other links on the same site |
| `url_pattern` | regex | none | Only follow URLs matching this |
| `max_pages` | number | `50` | Page limit |
| `max_items` | number | none | Row limit |
| `max_depth` | number | `2` | How many links deep to follow |
| `delay_seconds` | number | `1.0` | Wait between requests |
| `render_js` | true/false | `false` | Use a real browser |
| `respect_robots` | true/false | `true` | Obey `robots.txt` |
| `user_agent` | text | `WebScrapingTool/0.1 ...` | How the tool identifies itself to sites |
| `timeout_seconds` | number | `30` | Time limit per request |
| `max_retries` | number | `3` | Retries for temporary failures |

## REST API

```powershell
scraper api
```

Interactive documentation, where you can try every request in the browser, is at **http://127.0.0.1:8000/docs**.

| Request | Purpose |
|---|---|
| `POST /jobs` | Start a job. The body takes the settings from [Settings files](#settings-files). Returns its `id` |
| `GET /jobs` | List all jobs |
| `GET /jobs/{id}` | Status, pages, rows, errors and result message |
| `POST /jobs/{id}/cancel` | Stop a running job |
| `GET /jobs/{id}/items?limit=100&offset=0` | Rows as JSON, page by page (up to 10,000 per request) |
| `GET /jobs/{id}/export.csv` | Download as CSV |
| `GET /jobs/{id}/export.xlsx` | Download as Excel |

PowerShell example:

```powershell
$job = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/jobs -ContentType "application/json" `
  -Body '{"start_urls": ["https://books.toscrape.com/"], "max_pages": 2}'
Invoke-RestMethod http://127.0.0.1:8000/jobs/$($job.id)
Invoke-RestMethod "http://127.0.0.1:8000/jobs/$($job.id)/items?limit=5"
```

### API security

The API only listens on your own computer by default. **Before making it reachable from a network**, set an API key so that every request has to include it:

```powershell
$env:SCRAPER_API_KEY = "choose-a-long-random-value"
scraper api --host 0.0.0.0
```

Clients then send the header `X-API-Key: choose-a-long-random-value`. The dashboard has no login, so keep it on `127.0.0.1`.

## Built-in protections

| Protection | What it does |
|---|---|
| `robots.txt` | Skips pages a site disallows and obeys its `Crawl-delay` |
| Polite pacing | Waits between requests, using your delay or the site's crawl delay, whichever is longer |
| Retries | Retries timeouts and server errors (429, 5xx) with increasing waits, and obeys `Retry-After` |
| Stop on refusal | Stops after three refusals in a row (401, 403 or 429) instead of repeatedly hitting the site |
| Stay on site | Only follows links on the same site, and skips pages that redirect to another website |
| Size limit | Skips pages over 25 MB and non-HTML files such as PDFs and images |
| Safe URLs | Only accepts `http` and `https` links |
| No duplicates | Identical rows within a job are stored once |
| Spreadsheet safety | Cells that look like formulas (`=`, `+`, `-`, `@`) are made harmless in CSV and Excel |
| Separate processes | Each job runs in its own process, so a crash can't take down the dashboard. Errors inside a job are recorded and the job is marked failed |

## Where data is stored

- **Jobs, rows and logs:** `data/scraper.db`, a SQLite file in the project folder. To store it somewhere else, set `$env:SCRAPER_DB = "D:\path\to\file.db"` before starting.
- **Exports:** wherever you choose. The examples use `exports/`.

Both `data/` and `exports/` are excluded from git.

## Project structure

```
web-scraping-tool/
├── src/scraper/
│   ├── dashboard.py   # Streamlit dashboard (Home, Advanced scrape, Jobs, Data and export)
│   ├── cli.py         # "scraper" command
│   ├── api.py         # REST API (FastAPI)
│   ├── crawler.py     # Crawl loop, limits, robots.txt, background jobs
│   ├── fetchers.py    # HTTP and browser (Playwright) page downloads
│   ├── extractor.py   # Automatic and custom extraction, pagination
│   ├── cleaners.py    # Text, number, price and URL cleaning
│   ├── exporters.py   # CSV, Excel, JSON, database and API exports
│   ├── storage.py     # SQLite store for jobs, rows and logs
│   └── config.py      # Job settings and validation
├── tests/             # Tests that run against a local test website
├── examples/          # Example settings files
├── .streamlit/        # Dashboard theme
└── pyproject.toml     # Dependencies and the "scraper" command
```

## Running the tests

```powershell
pytest
```

The tests run against a small website started on your own computer, so they never contact real sites.

## Troubleshooting

| Problem | Fix |
|---|---|
| `running scripts is disabled on this system` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then activate again |
| `scraper` or `playwright` is not recognized | The environment isn't active. Run `.venv\Scripts\Activate.ps1` in the project folder |
| `Port 8501 is already in use` | The dashboard is already open in another window. Use it, or run `scraper dashboard --port 8502` |
| Only one summary row, or no data | The page probably needs JavaScript: tick **Page needs JavaScript** (or use `--js`), or use custom selectors |
| "JavaScript pages need Playwright" | Install it: `pip install -e ".[js]"`, then `playwright install --only-shell chromium` |
| "disallowed by robots.txt" | The site asks scrapers not to visit those pages. Only turn this off for sites you own or have permission for |
| "the site refused N requests in a row" | The site is blocking automated access. Increase the delay, or ask the site owner for access or an API |
| Missing fields in automatic mode | Use **Advanced scrape** → **Extract specific fields** with CSS selectors |
| Database export fails | Check the URL format and install the driver (`.[postgres]` or `.[mysql]`) |
| Slow installs | Use `pip install --default-timeout=120 --retries 8 ...` on slow connections |

## Responsible use

- **Check the rules:** read each site's terms of service before scraping it. Many offer an official API, which is usually more reliable.
- **Be gentle:** keep delays reasonable and limits sensible, because heavy scraping can slow a site down for everyone.
- **Personal data:** names, emails and similar details can fall under privacy laws such as GDPR, even when they're publicly visible.
- **No bypassing:** this tool deliberately doesn't get around CAPTCHAs, logins or anti-bot systems.
