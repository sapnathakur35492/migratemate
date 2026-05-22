# Adzuna USA Job Scraper

Standalone Django app that scrapes US jobs from the [Adzuna API](https://developer.adzuna.com/), saves only **live ATS / company career apply links**, and exposes a web dashboard on port **8002**.

## Features

- **81 keywords** — same list as the Simplify project (`simplify/jobscraper/settings.py`)
- **USA only** — Adzuna `us` country + location filters (non-US countries rejected)
- **Last 24 hours** — `max_days_old=1` + posted timestamp check
- **Experience 0–5 years** — title/description filter + API `what_exclude` for senior roles
- **ATS apply URLs only** — Greenhouse, Lever, Workday, Ashby, etc. (no LinkedIn, Indeed, or Adzuna portal links)
- **Start / Stop / Resume** — Resume keeps existing jobs; no overwrite or duplicates (`apply_url` unique, Adzuna job ID tracked)
- **Export CSV** — all jobs with columns: `title`, `company`, `location`, `posted_time`, `keyword`, `source`, `apply_url`, `posted_at`, `adzuna_job_id`, `scraped_at`

## Requirements

- Python 3.10+
- Adzuna API credentials ([signup](https://developer.adzuna.com/signup))

## Quick start

```powershell
cd MigrateMate_new
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Edit .env — set ADZUNA_APP_ID and ADZUNA_APP_KEY
python manage.py migrate
python manage.py runserver 8002 --noreload
```

Open **http://127.0.0.1:8002/**

Or use `start_server.bat` (after `.env` is configured).

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ADZUNA_APP_ID` | Yes | Adzuna application ID |
| `ADZUNA_APP_KEY` | Yes | Adzuna API key |
| `DJANGO_SECRET_KEY` | No | Production secret (optional in dev) |

Never commit `.env` — use `.env.example` as a template.

## Dashboard actions

| Action | Behavior |
|--------|----------|
| **Start** | Clears all jobs, runs all 81 keywords from the beginning |
| **Stop** | Stops worker; jobs stay in the database |
| **Resume** | Continues from last keyword/page; existing jobs kept, duplicates skipped |
| **Export CSV** | Downloads every saved job (all columns) |
| **Clear All Jobs** | Deletes all jobs (scraper must be stopped) |

## CLI commands

```powershell
python manage.py run_scraper              # Run scraper in foreground
python manage.py run_scraper --resume     # Resume from saved state
python manage.py purge_invalid_apply_urls # Remove dead / invalid apply URLs
```

Optional QA (dev):

```powershell
python manage.py test_scraper_final
python manage.py test_resume_csv
```

## Configuration

Edit `migratemate_site/settings.py`:

| Setting | Default | Notes |
|---------|---------|--------|
| `KEYWORDS` | 81 titles | Synced with Simplify |
| `ADZUNA_RESULTS_PER_PAGE` | 50 | API maximum |
| `ADZUNA_MAX_PAGES_PER_KEYWORD` | 50 | Pages per keyword |
| `ADZUNA_MAX_DAYS_OLD` | 1 | Last 24 hours |
| `ALLOWED_ATS` | Greenhouse, Lever, … | Allowed apply hosts |

## Project layout

```
MigrateMate_new/
├── manage.py
├── requirements.txt
├── .env.example
├── migratemate/              # App: models, scraper, views, dashboard
├── migratemate_site/         # Django settings, apply URL rules
└── logs/                     # Runtime logs (gitignored)
```

## Git push checklist

- [ ] `.env` is **not** staged (listed in `.gitignore`)
- [ ] `db.sqlite3` and `logs/` are **not** staged
- [ ] `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` only in local `.env`

```powershell
git add README.md requirements.txt .env.example
git add migratemate migratemate_site manage.py start_server.bat .gitignore
git commit -m "Adzuna USA scraper: dashboard, CSV export, resume without duplicates"
git push
```

## Related projects (same machine, different ports)

| Project | Port | Source |
|---------|------|--------|
| Simplify | 8000 | simplify.jobs |
| Jobright | 8001 | jobright.ai |
| **Adzuna (this)** | **8002** | Adzuna API |
