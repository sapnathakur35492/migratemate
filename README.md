# MigrateMate USA Job Scraper

Standalone Django app — **port 8002**, own `db.sqlite3`, no shared code with Simplify or Jobright.

| | Simplify | Jobright | MigrateMate |
|---|----------|----------|-------------|
| Folder | `../simplify/` | `../Jobright_new/` | `MigrateMate_new/` |
| Port | **8000** | **8001** | **8002** |

See `../PROJECTS.md` for running all three.

## What it does

- Scrapes [migratemate.co/open-jobs](https://migratemate.co/open-jobs) via Playwright + Algolia API (`/api/jobs/search`).
- **~142 keywords** + **browse pass** + up to **3 query variants** per keyword.
- Up to **100 hits × 20 pages** per query (Algolia pagination).
- Filters: **USA**, **last 48 hours** (`MIGRATEMATE_MAX_AGE_HOURS`), non-intern roles.
- Apply URL: job description → **Greenhouse/Lever APIs** → career scan → detail panel — **company ATS only** (never `migratemate.co` portal links).
- Title + company verified before save (avoids wrong board matches).
- Typical yield: **lower saved count** than Simplify (strict ATS rule; many listings skipped).

## Setup

```powershell
cd MigrateMate_new
pip install -r requirements.txt
playwright install chromium
python manage.py migrate
python manage.py runserver 8002 --noreload
```

Or double-click `start_server.bat`.

Dashboard: **http://127.0.0.1:8002/**

## Dashboard

| Button | Action |
|--------|--------|
| **Start** | Clear all jobs, reset state, scrape from pass 1 |
| **Resume** | Continue from last keyword (no duplicates) |
| **Stop** | Save progress and stop background worker |
| **Clear All Jobs** | Delete jobs only (scraper must be stopped) |

Use **`--noreload`** while scraping so Django reload does not kill the browser worker.

## Management commands

```powershell
python manage.py run_scraper
python manage.py run_scraper --resume
python manage.py purge_invalid_apply_urls   # migratemate portal + invalid ATS URLs
```

## Configuration (`migratemate_site/settings.py`)

| Setting | Default | Purpose |
|---------|---------|---------|
| `MIGRATEMATE_HITS_PER_PAGE` | 100 | Algolia page size |
| `MIGRATEMATE_MAX_PAGES_PER_KEYWORD` | 20 | Max pages per query |
| `MIGRATEMATE_USE_QUERY_VARIANTS` | True | engineer/developer variants |
| `MIGRATEMATE_BROWSE_EMPTY_QUERY` | True | Full-site browse pass first |
| `MIGRATEMATE_MAX_AGE_HOURS` | 48 | Job age window |

## Logs

- `logs/scraper.log`, `logs/worker.log` — not committed (see `.gitignore`)
