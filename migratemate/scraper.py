"""Adzuna USA job scraper (replaces MigrateMate). Port 8002."""
import logging
import os
import random
import re
import threading
import time
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import quote

import requests
from django.conf import settings
from django.db import IntegrityError, close_old_connections

from migratemate_site.apply_live import is_apply_url_live
from migratemate_site.apply_urls import is_blocked_apply_host, is_valid_apply_url as _valid_apply
from migratemate_site.scraper_process import (
    clear_stop_flag,
    is_stop_requested,
    pid_is_alive,
    request_stop,
    spawn_worker,
    terminate_pid,
)

from .models import MigratemateJob, MigratemateScraperState
from .time_utils import format_posted_time, is_within_24h_timestamp

logger = logging.getLogger("migratemate_scraper")

_stop_event = threading.Event()
ATS_DOMAINS = tuple(settings.ALLOWED_ATS)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

JOBS_PER_PAGE = 20
RESULTS_PER_PAGE = int(getattr(settings, "ADZUNA_RESULTS_PER_PAGE", 50))
MAX_PAGES = int(getattr(settings, "ADZUNA_MAX_PAGES_PER_KEYWORD", 40))
MAX_DAYS_OLD = int(getattr(settings, "ADZUNA_MAX_DAYS_OLD", 1))
DEFAULT_WHERE = getattr(settings, "ADZUNA_DEFAULT_WHERE", "United States")

EXPERIENCE_HARD_BLOCK = (
    "director",
    "vice president",
    " vp,",
    " vp ",
    "chief ",
    "head of",
    "principal engineer",
    "staff engineer",
    "distinguished engineer",
    "10+ years",
    "15+ years",
    "20+ years",
    "12+ years",
    "8+ years",
    "7+ years",
    "6+ years",
    "executive director",
)

ATS_URL_IN_TEXT = re.compile(
    r"https?://[^\s\"'<>\\]+?(?:"
    r"greenhouse\.io|lever\.co|myworkdayjobs\.com|myworkdaysite\.com|"
    r"ashbyhq\.com|smartrecruiters\.com|icims\.com|jobvite\.com|"
    r"oraclecloud\.com|workable\.com|recruitee\.com|bamboohr\.com"
    r")[^\s\"'<>\\]*",
    re.I,
)


def _should_stop():
    return _stop_event.is_set() or is_stop_requested()


def is_scraper_running():
    state = MigratemateScraperState.get_singleton()
    return pid_is_alive(state.worker_pid)


def is_valid_apply_url(url, company_url=""):
    return _valid_apply(url, ATS_DOMAINS, company_url=company_url)


NON_US_AREA_NAMES = frozenset(
    {
        "canada",
        "mexico",
        "united kingdom",
        "uk",
        "india",
        "australia",
        "germany",
        "france",
        "ireland",
        "singapore",
        "philippines",
        "brazil",
        "china",
        "japan",
        "spain",
        "italy",
        "netherlands",
        "poland",
        "puerto rico",
    }
)

NON_US_LOCATION_HINTS = (
    "canada",
    "toronto",
    "vancouver",
    "montreal",
    "mexico",
    "united kingdom",
    " london",
    "manchester",
    "india",
    "bangalore",
    "hyderabad",
    "australia",
    "sydney",
    "melbourne",
    "germany",
    "berlin",
    "ireland",
    "dublin",
    "singapore",
    "remote - uk",
    "remote - canada",
    "remote - india",
)


def _display_has_non_us_country(display):
    low = (display or "").lower()
    if not low:
        return False
    if any(h in low for h in NON_US_LOCATION_HINTS):
        if not any(x in low for x in ("usa", "united states", ", us", " u.s.", "u.s.a")):
            return True
    return False


def is_usa_job(location_obj):
    """Adzuna US API + area hierarchy; reject explicit non-US countries."""
    if not location_obj:
        return False
    area = location_obj.get("area") or []
    if area:
        top = str(area[0]).lower()
        if top in NON_US_AREA_NAMES:
            return False
        if any(str(a).upper() in ("US", "USA", "UNITED STATES") for a in area):
            return True
    display = location_obj.get("display_name") or ""
    if _display_has_non_us_country(display):
        return False
    # City/county only (e.g. "North Reading, Middlesex County") — OK on US Adzuna feed
    return bool(display.strip())


def is_usa_location_string(location):
    """Saved row audit: reject only if location text names a non-US country."""
    return not _display_has_non_us_country(location)


def is_experience_0_to_5(title, description=""):
    blob = f"{title} {description}".lower()
    if any(h in blob for h in EXPERIENCE_HARD_BLOCK):
        return False
    if re.search(r"\b([6-9]|1[0-9]|20)\+?\s*(?:years?|yrs?)\b", blob):
        return False
    if re.search(r"\b(?:minimum|min\.?|at least)\s*([6-9]|1[0-9])\s*(?:years?|yrs?)\b", blob):
        return False
    if re.search(r"\b(senior|sr\.)\b", blob):
        if not re.search(r"\b(junior|entry|new grad|associate|intern)\b", blob):
            return False
    if re.search(r"\bengineering manager\b", blob) or re.search(r"\btech lead\b", blob):
        return False
    if re.search(r"\b(manager|director)\b", blob) and not re.search(
        r"\b(product manager|project manager|program manager|account manager|"
        r"marketing manager|finance manager|supply chain manager)\b",
        blob,
    ):
        return False
    return True


def job_exists(title, company, location, apply_url, adzuna_job_id=""):
    close_old_connections()
    if adzuna_job_id and MigratemateJob.objects.filter(migratemate_job_id=adzuna_job_id).exists():
        return True
    if MigratemateJob.objects.filter(apply_url=apply_url).exists():
        return True
    return MigratemateJob.objects.filter(title=title, company=company, location=location).exists()


def _api_credentials():
    app_id = getattr(settings, "ADZUNA_APP_ID", "") or os.environ.get("ADZUNA_APP_ID", "")
    app_key = getattr(settings, "ADZUNA_APP_KEY", "") or os.environ.get("ADZUNA_APP_KEY", "")
    return app_id, app_key


def _title_match_score(want, found):
    if not want or not found:
        return 0.0
    return SequenceMatcher(None, want.lower(), found.lower()).ratio()


def _board_tokens(company):
    company = (company or "").strip()
    tokens = []
    slug = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")
    if slug and len(slug) >= 4:
        tokens.extend([slug, slug.replace("-", "")])
    clean = re.sub(r"[^a-z0-9]", "", company.lower())
    if clean and len(clean) >= 4:
        tokens.append(clean)
    return list(dict.fromkeys(t for t in tokens if t))


def _greenhouse_apply(session, job_title, company, gh_cache, min_score=0.62):
    best_url = None
    best_score = 0.0
    for token in _board_tokens(company)[:5]:
        if _should_stop():
            break
        if token in gh_cache:
            jobs = gh_cache[token]
        else:
            jobs = None
            try:
                r = session.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", timeout=10)
                if r.status_code < 400:
                    jobs = r.json().get("jobs") or []
            except Exception:
                pass
            gh_cache[token] = jobs
        if not jobs:
            continue
        for job in jobs:
            score = _title_match_score(job_title, job.get("title") or "")
            if score > best_score:
                best_score = score
                best_url = job.get("absolute_url") or ""
    if best_url and best_score >= min_score and is_valid_apply_url(best_url):
        return best_url
    return None


def _lever_apply(session, job_title, company, lever_cache, min_score=0.58):
    best_url = None
    best_score = 0.0
    for token in _board_tokens(company)[:5]:
        if _should_stop():
            break
        if token in lever_cache:
            posts = lever_cache[token]
        else:
            posts = None
            try:
                r = session.get(f"https://api.lever.co/v0/postings/{token}?mode=json", timeout=10)
                if r.status_code < 400:
                    data = r.json()
                    posts = data if isinstance(data, list) else []
            except Exception:
                pass
            lever_cache[token] = posts
        if not posts:
            continue
        for post in posts:
            score = _title_match_score(job_title, post.get("text") or post.get("title") or "")
            if score > best_score:
                best_score = score
                best_url = post.get("hostedUrl") or post.get("applyUrl") or ""
    if best_url and best_score >= min_score and is_valid_apply_url(best_url):
        return best_url
    return None


def _collect_redirect_candidates(session, redirect_url):
    candidates = []
    try:
        resp = session.get(redirect_url, allow_redirects=True, timeout=15)
        final = (resp.url or "").strip()
        if final and not is_blocked_apply_host(final) and is_valid_apply_url(final):
            candidates.append(final)
        text = (resp.text or "")[:120000]
        for m in ATS_URL_IN_TEXT.finditer(text):
            u = m.group(0).rstrip(".,;)'\"")
            if not is_blocked_apply_host(u) and is_valid_apply_url(u):
                candidates.append(u)
        for m in re.finditer(r"https?://[^\s\"'<>\\]+", text):
            u = m.group(0).rstrip(".,;)'\"")
            if not is_blocked_apply_host(u) and is_valid_apply_url(u):
                candidates.append(u)
    except Exception as exc:
        logger.debug("Redirect follow failed: %s", exc)
    return candidates


def _pick_live_apply(session, candidates):
    seen = set()
    for url in candidates:
        if not url or url in seen:
            continue
        seen.add(url)
        if "adzuna." in url.lower():
            continue
        if is_apply_url_live(session, url, ATS_DOMAINS):
            return url
    return None


def _resolve_apply_url(session, redirect_url, job_title, company, gh_cache, lever_cache):
    if not redirect_url:
        return None
    candidates = _collect_redirect_candidates(session, redirect_url)
    found = _pick_live_apply(session, candidates)
    if found:
        return found
    gh = _greenhouse_apply(session, job_title, company, gh_cache)
    if gh and is_apply_url_live(session, gh, ATS_DOMAINS):
        return gh
    lev = _lever_apply(session, job_title, company, lever_cache)
    if lev and is_apply_url_live(session, lev, ATS_DOMAINS):
        return lev
    return None


def _parse_created_ts(created_str):
    if not created_str:
        return None
    try:
        dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return None


class AdzunaScraper:
    def __init__(self, resume=False):
        self.resume = resume
        self.state = MigratemateScraperState.get_singleton()
        raw = self.state.processed_ids or ""
        self.processed = set(x for x in raw.split(",") if x)
        self.app_id, self.app_key = _api_credentials()
        self.country = getattr(settings, "ADZUNA_COUNTRY", "us")
        self._gh_cache = {}
        self._lever_cache = {}
        if resume:
            self._hydrate_processed_from_db()

    def _hydrate_processed_from_db(self):
        close_old_connections()
        before = len(self.processed)
        for jid in MigratemateJob.objects.exclude(migratemate_job_id="").values_list(
            "migratemate_job_id", flat=True
        ).iterator(chunk_size=5000):
            if jid:
                self.processed.add(str(jid))
        db_count = MigratemateJob.objects.count()
        if self.resume and self.state.jobs_saved < db_count:
            self.state.jobs_saved = db_count
        logger.info(
            "Resume: %s IDs in state, +%s from DB, jobs_saved=%s",
            before,
            len(self.processed) - before,
            self.state.jobs_saved,
        )

    def _save_state(self, **kwargs):
        close_old_connections()
        for k, v in kwargs.items():
            setattr(self.state, k, v)
        self.state.processed_ids = ",".join(sorted(self.processed)[-80000:])
        self.state.save()

    def _check_stop(self):
        if _should_stop():
            raise StopIteration

    def _human_delay(self, lo=0.08, hi=0.22):
        end = time.time() + random.uniform(lo, hi)
        while time.time() < end:
            if _should_stop():
                raise StopIteration
            time.sleep(0.1)

    def _search_page(self, session, keyword, page_num):
        if not self.app_id or not self.app_key:
            raise RuntimeError("Set ADZUNA_APP_ID and ADZUNA_APP_KEY in environment or settings")
        url = (
            f"{settings.ADZUNA_API_BASE}/jobs/{self.country}/search/{page_num}"
            f"?app_id={quote(self.app_id)}&app_key={quote(self.app_key)}"
            f"&what={quote(keyword)}&where={quote(DEFAULT_WHERE)}"
            f"&results_per_page={RESULTS_PER_PAGE}&max_days_old={MAX_DAYS_OLD}"
            f"&sort_by=date&content-type=application/json"
            f"&what_exclude={quote('senior director principal vp chief')}"
        )
        try:
            resp = session.get(url, timeout=45)
            if resp.status_code != 200:
                logger.warning("Adzuna API %s page %s status=%s", keyword, page_num, resp.status_code)
                return [], 0
            data = resp.json()
            results = data.get("results") or []
            count = int(data.get("count") or 0)
            return results, count
        except Exception as exc:
            logger.warning("Adzuna search error %s page %s: %s", keyword, page_num, exc)
            return [], 0

    def _process_keyword(self, session, keyword, ki, total, start_page=1):
        saved_before = self.state.jobs_saved
        page_num = max(1, start_page)
        empty_streak = 0

        while page_num <= MAX_PAGES and not _should_stop():
            results, count = self._search_page(session, keyword, page_num)
            if not results:
                empty_streak += 1
                if empty_streak >= 2:
                    break
                page_num += 1
                continue
            empty_streak = 0

            self._save_state(
                current_page=page_num,
                last_message=f"[{ki + 1}/{total}] {keyword} — page {page_num} ({count} matches)",
                current_keyword=keyword,
            )
            logger.info("[%s/%s] %s page %s: %s ads", ki + 1, total, keyword, page_num, len(results))

            for ad in results:
                if _should_stop():
                    raise StopIteration

                job_id = str(ad.get("id") or "")
                if not job_id or job_id in self.processed:
                    continue
                if not is_usa_job(ad.get("location")):
                    continue

                title = (ad.get("title") or "").strip()
                description = ad.get("description") or ""
                if not is_experience_0_to_5(title, description):
                    continue

                posted_ts = _parse_created_ts(ad.get("created"))
                if not posted_ts or not is_within_24h_timestamp(posted_ts):
                    continue

                posted_label = format_posted_time(posted_ts)
                if not posted_label:
                    continue

                company = (ad.get("company") or {}).get("display_name") or ""
                company = company.strip() or "Unknown"
                loc = ad.get("location") or {}
                location = (loc.get("display_name") or "").strip() or "United States"
                if not is_usa_location_string(location):
                    continue

                redirect = ad.get("redirect_url") or ""
                desc = ad.get("description") or ""
                desc_candidates = []
                for m in ATS_URL_IN_TEXT.finditer(desc):
                    u = m.group(0).rstrip(".,;)'\"")
                    if not is_blocked_apply_host(u) and is_valid_apply_url(u):
                        desc_candidates.append(u)
                apply_url = _pick_live_apply(session, desc_candidates)
                if not apply_url:
                    apply_url = _resolve_apply_url(
                        session, redirect, title, company, self._gh_cache, self._lever_cache
                    )
                if not apply_url:
                    self.processed.add(job_id)
                    self.state.jobs_skipped += 1
                    logger.info("Skipped (no valid ATS): %s @ %s", title, company)
                    self._save_state(jobs_skipped=self.state.jobs_skipped)
                    continue

                if job_exists(title, company, location, apply_url, adzuna_job_id=job_id):
                    self.processed.add(job_id)
                    self.state.jobs_skipped += 1
                    self._save_state(jobs_skipped=self.state.jobs_skipped)
                    continue

                close_old_connections()
                try:
                    MigratemateJob.objects.create(
                        title=title,
                        company=company,
                        location=location,
                        apply_url=apply_url,
                        source="Adzuna",
                        keyword=keyword,
                        posted_time=posted_label,
                        posted_at=posted_ts,
                        migratemate_job_id=job_id,
                    )
                except IntegrityError:
                    self.processed.add(job_id)
                    self.state.jobs_skipped += 1
                    self._save_state(jobs_skipped=self.state.jobs_skipped)
                    continue

                self.processed.add(job_id)
                self.state.jobs_saved += 1
                self._save_state(jobs_saved=self.state.jobs_saved)
                logger.info("Saved: %s @ %s (%s)", title, company, posted_label)

            page_num += 1
            self._human_delay(0.1, 0.2)

        return self.state.jobs_saved - saved_before

    def run(self):
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        close_old_connections()
        keywords = list(settings.KEYWORDS)
        total = len(keywords)
        start_idx = self.state.keyword_index if self.resume else 0

        if not self.app_id or not self.app_key:
            self._save_state(
                status=MigratemateScraperState.STATUS_STOPPED,
                last_message="Missing ADZUNA_APP_ID / ADZUNA_APP_KEY — register at developer.adzuna.com",
            )
            logger.error("Adzuna API credentials missing")
            return

        if not self.resume:
            self.processed.clear()
            self._save_state(
                status=MigratemateScraperState.STATUS_RUNNING,
                keyword_index=0,
                current_page=1,
                jobs_saved=0,
                jobs_skipped=0,
                last_message=f"Adzuna scraper started — {total} keywords",
            )
        else:
            self._hydrate_processed_from_db()
            kw = self.state.current_keyword or (keywords[start_idx] if start_idx < total else "")
            db_n = MigratemateJob.objects.count()
            self._save_state(
                status=MigratemateScraperState.STATUS_RUNNING,
                jobs_saved=db_n,
                last_message=f"Resume — {db_n} jobs kept, no overwrite, keyword {start_idx + 1}/{total}: '{kw}'",
            )

        logger.info("Adzuna scraper started resume=%s idx=%s", self.resume, start_idx + 1)
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

        try:
            for ki in range(start_idx, total):
                self._check_stop()
                keyword = keywords[ki]
                start_page = 1
                if self.resume and self.state.current_keyword == keyword and self.state.current_page > 1:
                    start_page = self.state.current_page

                try:
                    self._save_state(keyword_index=ki, current_keyword=keyword)
                    n = self._process_keyword(session, keyword, ki, total, start_page=start_page)
                    self._save_state(
                        keyword_index=ki + 1,
                        current_page=1,
                        last_message=f"[{ki + 1}/{total}] Done '{keyword}' (+{n} jobs)",
                    )
                except StopIteration:
                    raise
                except Exception as exc:
                    logger.exception("Keyword error %s: %s", keyword, exc)
                    self._save_state(
                        keyword_index=ki + 1,
                        last_message=f"Error on '{keyword}': {str(exc)[:120]}",
                    )
                self.resume = False
                if not _should_stop():
                    self._human_delay(0.15, 0.3)

            if not _should_stop():
                self._save_state(
                    status=MigratemateScraperState.STATUS_IDLE,
                    keyword_index=total,
                    current_keyword="",
                    last_message=f"Completed all {total} Adzuna keywords",
                )
        except StopIteration:
            self._save_state(
                status=MigratemateScraperState.STATUS_STOPPED,
                last_message=f"Stopped — Resume continues keyword {self.state.keyword_index + 1}",
            )
        except Exception as exc:
            if not _should_stop():
                logger.exception("Adzuna scraper error: %s", exc)
            self._save_state(status=MigratemateScraperState.STATUS_STOPPED, last_message=str(exc)[:500])


def start_scraper(resume=False):
    if is_scraper_running():
        return False, "Adzuna scraper already running"

    clear_stop_flag()
    _stop_event.clear()
    state = MigratemateScraperState.get_singleton()
    total = len(settings.KEYWORDS)
    if not resume:
        close_old_connections()
        deleted, _ = MigratemateJob.objects.all().delete()
        state.status = MigratemateScraperState.STATUS_RUNNING
        state.keyword_index = 0
        state.current_page = 1
        state.current_keyword = ""
        state.jobs_saved = 0
        state.jobs_skipped = 0
        state.processed_ids = ""
        state.last_message = f"Fresh start — deleted {deleted} jobs, keyword 1/{total}"
        start_msg = f"Started fresh: cleared {deleted} jobs"
    else:
        state.status = MigratemateScraperState.STATUS_RUNNING
        start_msg = None

    pid = spawn_worker(resume=resume)
    state.worker_pid = pid
    state.save()
    return True, start_msg or f"Resumed — existing jobs kept, no duplicates (PID {pid})"


def stop_scraper():
    state = MigratemateScraperState.get_singleton()
    if not is_scraper_running() and state.status != MigratemateScraperState.STATUS_RUNNING:
        return True, "Scraper is not running"

    request_stop()
    _stop_event.set()
    terminate_pid(state.worker_pid)
    state.worker_pid = 0
    state.status = MigratemateScraperState.STATUS_STOPPED
    state.last_message = "Stopped — click Resume to continue"
    state.save()
    return True, state.last_message
