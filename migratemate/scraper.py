import json
import logging
import os
import random
import re
import threading
import time
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from django.conf import settings
from django.db import IntegrityError, close_old_connections
from playwright.sync_api import sync_playwright

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
from .time_utils import format_posted_time, is_within_24h_timestamp, slugify_keyword

logger = logging.getLogger("migratemate_scraper")

_stop_event = threading.Event()
_active_browser = None
_active_lock = threading.Lock()

JOBS_PER_PAGE = 20
HITS_PER_PAGE = int(getattr(settings, "MIGRATEMATE_HITS_PER_PAGE", 100))
MAX_PAGES_PER_KEYWORD = int(getattr(settings, "MIGRATEMATE_MAX_PAGES_PER_KEYWORD", 20))
USE_QUERY_VARIANTS = getattr(settings, "MIGRATEMATE_USE_QUERY_VARIANTS", True)
MAX_QUERIES_PER_KEYWORD = int(getattr(settings, "MIGRATEMATE_MAX_QUERIES_PER_KEYWORD", 3))
BROWSE_EMPTY_QUERY = getattr(settings, "MIGRATEMATE_BROWSE_EMPTY_QUERY", True)
BROWSE_KEYWORD_LABEL = "Recent listings (browse)"
BASE_URL = "https://migratemate.co"
OPEN_JOBS = f"{BASE_URL}/open-jobs"
SEARCH_API = f"{BASE_URL}/api/jobs/search"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

ATS_DOMAINS = tuple(settings.ALLOWED_ATS)
CAREER_PATH_SUFFIXES = ("", "/careers", "/jobs", "/career", "/join-us", "/work-with-us", "/open-positions")

SEARCH_FETCH_JS = """async (body) => {
    const r = await fetch('/api/jobs/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        credentials: 'include',
    });
    if (!r.ok) {
        return { ok: false, status: r.status, error: (await r.text()).slice(0, 500) };
    }
    return { ok: true, data: await r.json() };
}"""


def _close_active_browser():
    global _active_browser
    with _active_lock:
        browser = _active_browser
        _active_browser = None
    if browser:
        try:
            browser.close()
        except Exception:
            pass


def _should_stop():
    return _stop_event.is_set() or is_stop_requested()


def is_scraper_running():
    state = MigratemateScraperState.get_singleton()
    return pid_is_alive(state.worker_pid)


def is_usa_location(location):
    loc = (location or "").lower()
    if not loc:
        return False
    if any(
        x in loc
        for x in (
            "usa",
            "united states",
            "u.s.",
            ", us",
            "remote in usa",
            "remote, us",
        )
    ):
        return True
    if ", " in loc:
        return True
    us_states = (
        "alabama",
        "alaska",
        "arizona",
        "arkansas",
        "california",
        "colorado",
        "connecticut",
        "delaware",
        "florida",
        "georgia",
        "hawaii",
        "idaho",
        "illinois",
        "indiana",
        "iowa",
        "kansas",
        "kentucky",
        "louisiana",
        "maine",
        "maryland",
        "massachusetts",
        "michigan",
        "minnesota",
        "mississippi",
        "missouri",
        "montana",
        "nebraska",
        "nevada",
        "hampshire",
        "jersey",
        "mexico",
        "york",
        "carolina",
        "dakota",
        "ohio",
        "oklahoma",
        "oregon",
        "pennsylvania",
        "rhode island",
        "south carolina",
        "south dakota",
        "tennessee",
        "texas",
        "utah",
        "vermont",
        "virginia",
        "washington",
        "west virginia",
        "wisconsin",
        "wyoming",
        "district of columbia",
    )
    return any(s in loc for s in us_states)


def is_valid_apply_url(url, company_url=""):
    return _valid_apply(url, ATS_DOMAINS, company_url=company_url)


def _find_ats_in_text(text, company_url=""):
    if not text:
        return []
    found = []
    soup = BeautifulSoup(text, "html.parser")
    for a in soup.find_all("a", href=True):
        u = a["href"].strip()
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            continue
        if is_blocked_apply_host(u):
            continue
        if is_valid_apply_url(u, company_url=company_url):
            found.append(u)
    for m in re.finditer(r"https?://[^\s\"'<>\\]+", text):
        u = m.group(0).rstrip(".,;)")
        if is_blocked_apply_host(u):
            continue
        if is_valid_apply_url(u, company_url=company_url):
            found.append(u)
    return found


def _is_direct_ats_job_url(url):
    low = (url or "").lower()
    if "greenhouse.io" in low and re.search(r"/jobs/\d+", low):
        return True
    if "lever.co" in low and re.search(r"lever\.co/[^/]+/[0-9a-f-]{8,}", low):
        return True
    if "ashbyhq.com" in low and re.search(r"[0-9a-f-]{20,}", low):
        return True
    return False


def _queries_for_keyword(keyword):
    if not keyword:
        return [""]
    queries = [keyword]
    if USE_QUERY_VARIANTS:
        low = keyword.lower()
        if "engineer" in low and "developer" not in low:
            queries.append(
                keyword.replace("engineer", "developer").replace("Engineer", "Developer")
            )
        elif "developer" in low and "engineer" not in low:
            queries.append(
                keyword.replace("developer", "engineer").replace("Developer", "Engineer")
            )
        if "analyst" in low:
            queries.append(keyword.replace("analyst", "analysis").replace("Analyst", "Analysis"))
    out = []
    seen = set()
    for q in queries:
        k = q.strip().lower()
        if k not in seen:
            seen.add(k)
            out.append(q)
    return out[:MAX_QUERIES_PER_KEYWORD]


def _is_job_page_ok(request_ctx, url, company_url="", job_title="", company_name=""):
    if _is_direct_ats_job_url(url) and is_valid_apply_url(url, company_url=company_url):
        if job_title and not _apply_page_matches_job(request_ctx, url, job_title, company_name):
            return False, url
        return True, url
    if is_blocked_apply_host(url) or not is_valid_apply_url(url, company_url=company_url):
        return False, url
    try:
        resp = request_ctx.get(url, max_redirects=12, timeout=25000)
        final = resp.url
        if resp.status >= 400:
            return False, final
        if is_blocked_apply_host(final):
            return False, final
        if not is_valid_apply_url(final, company_url=company_url):
            return False, final
        if job_title and not _apply_page_matches_job(request_ctx, final, job_title, company_name):
            return False, final
        if company_url:
            fu = urlparse(final)
            if _host_on_company(fu.netloc, company_url) and fu.path in ("", "/"):
                return False, final
        body = (resp.text() or "").lower()[:8000]
        if any(x in body for x in ("page not found", "404 error", "job no longer", "position filled", "expired")):
            return False, final
        return True, final
    except Exception as exc:
        logger.warning("URL verify failed %s: %s", url[:80], exc)
        return False, url


def _host_on_company(host, company_url):
    from migratemate_site.apply_urls import _host_on_company_domain

    return _host_on_company_domain(host.lower(), company_url)


def _company_slug(hit):
    logo = hit.get("company_logo_url") or ""
    m = re.search(r"/company-logos/([^./]+)", logo)
    if m:
        return m.group(1)
    return slugify_keyword(hit.get("company") or "")


GENERIC_BOARD_TOKENS = frozenset(
    {
        "community",
        "health",
        "group",
        "services",
        "global",
        "national",
        "solutions",
        "partners",
        "consulting",
        "management",
        "systems",
        "care",
        "center",
        "centre",
        "parkland",
        "united",
        "american",
        "general",
        "digital",
        "technology",
        "tech",
        "international",
        "holdings",
        "industries",
        "corporation",
        "company",
        "inc",
        "llc",
        "ltd",
    }
)


def _board_tokens(company, slug):
    """Prefer MigrateMate logo slug + full company slug — avoid generic single-word tokens."""
    tokens = []
    if slug and len(slug) >= 4 and slug not in GENERIC_BOARD_TOKENS:
        tokens.append(slug)
        compact = slug.replace("-", "")
        if len(compact) >= 5 and compact not in GENERIC_BOARD_TOKENS:
            tokens.append(compact)
    full = slugify_keyword(company or "")
    if full and len(full) >= 5 and full not in GENERIC_BOARD_TOKENS:
        tokens.append(full)
        compact_full = full.replace("-", "")
        if len(compact_full) >= 6:
            tokens.append(compact_full)
    return list(dict.fromkeys(t for t in tokens if t))


def _title_match_score(want, found):
    if not want or not found:
        return 0.0
    return SequenceMatcher(None, want.lower(), found.lower()).ratio()


def _company_name_overlap(company, other):
    if not company or not other:
        return False
    cw = set(re.findall(r"[a-z]{4,}", company.lower()))
    ow = set(re.findall(r"[a-z]{4,}", other.lower()))
    if not cw or not ow:
        return False
    return len(cw & ow) >= 2


def _gh_board_matches_company(request_ctx, token, company):
    try:
        resp = request_ctx.get(
            f"https://boards-api.greenhouse.io/v1/boards/{token}",
            timeout=12000,
        )
        if resp.status >= 400:
            return False
        name = (resp.json().get("name") or "").strip()
        if not name:
            return False
        if _title_match_score(company, name) >= 0.42:
            return True
        return _company_name_overlap(company, name)
    except Exception:
        return False


def _lever_site_matches_company(request_ctx, token, company):
    try:
        resp = request_ctx.get(f"https://api.lever.co/v0/postings/{token}?mode=json", timeout=12000)
        if resp.status >= 400:
            return False
        postings = resp.json()
        if not isinstance(postings, list) or not postings:
            return False
        site = (postings[0].get("categories", {}) or {}).get("team") or ""
        host = token.replace("-", " ")
        return _company_name_overlap(company, site) or _company_name_overlap(company, host)
    except Exception:
        return False


def _apply_page_matches_job(request_ctx, url, job_title, company=""):
    if not job_title:
        return True
    try:
        resp = request_ctx.get(url, timeout=20000)
        if resp.status >= 400:
            return False
        text = (resp.text() or "")[:20000].lower()
        title_low = job_title.lower()
        if _title_match_score(job_title, text) >= 0.38:
            return True
        keywords = [w for w in re.findall(r"[a-z]{4,}", title_low) if w not in ("senior", "lead", "staff", "manager")]
        if not keywords:
            return True
        hits = sum(1 for w in keywords[:6] if w in text)
        need = max(2, min(4, len(keywords) // 2 + 1))
        if hits >= need:
            return True
        if company and _company_name_overlap(company, text):
            return hits >= max(1, len(keywords) // 3)
        return False
    except Exception:
        return False


def _greenhouse_apply(request_ctx, tokens, job_title, company="", min_score=0.68):
    best_url = None
    best_score = 0.0
    for token in tokens[:6]:
        if _should_stop():
            break
        if not _gh_board_matches_company(request_ctx, token, company):
            continue
        api = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
        try:
            resp = request_ctx.get(api, timeout=15000)
            if resp.status >= 400:
                continue
            jobs = resp.json().get("jobs") or []
        except Exception:
            continue
        for job in jobs:
            gh_title = job.get("title") or ""
            score = _title_match_score(job_title, gh_title)
            if score > best_score:
                best_score = score
                best_url = job.get("absolute_url") or ""
    if best_url and best_score >= min_score and is_valid_apply_url(best_url):
        if _apply_page_matches_job(request_ctx, best_url, job_title, company):
            return best_url
    return None


def _lever_apply(request_ctx, tokens, job_title, company="", min_score=0.65):
    best_url = None
    best_score = 0.0
    for token in tokens[:6]:
        if _should_stop():
            break
        if not _lever_site_matches_company(request_ctx, token, company):
            continue
        api = f"https://api.lever.co/v0/postings/{token}?mode=json"
        try:
            resp = request_ctx.get(api, timeout=15000)
            if resp.status >= 400:
                continue
            postings = resp.json()
            if not isinstance(postings, list):
                continue
        except Exception:
            continue
        for post in postings:
            lev_title = post.get("text") or post.get("title") or ""
            score = _title_match_score(job_title, lev_title)
            if score > best_score:
                best_score = score
                best_url = post.get("hostedUrl") or post.get("applyUrl") or ""
    if best_url and best_score >= min_score and is_valid_apply_url(best_url):
        if _apply_page_matches_job(request_ctx, best_url, job_title, company):
            return best_url
    return None


def _company_url_guesses(company, slug):
    urls = []
    clean = re.sub(r"[^a-z0-9]", "", (company or "").lower())
    slug_compact = (slug or "").replace("-", "")
    if slug_compact:
        urls.extend(
            [
                f"https://www.{slug_compact}.com",
                f"https://{slug}.com" if slug else "",
            ]
        )
    if clean and clean != slug_compact:
        urls.append(f"https://www.{clean}.com")
    return [u for u in urls if u and u.startswith("http")]


def job_exists(title, company, location, apply_url):
    close_old_connections()
    if MigratemateJob.objects.filter(apply_url=apply_url).exists():
        return True
    return MigratemateJob.objects.filter(title=title, company=company, location=location).exists()


class MigratemateScraper:
    def __init__(self, resume=False):
        self.resume = resume
        self.state = MigratemateScraperState.get_singleton()
        raw = self.state.processed_ids or ""
        self.processed = set(x for x in raw.split(",") if x)
        self._session_ready = False
        if resume:
            self._hydrate_processed_from_db()

    def _hydrate_processed_from_db(self):
        close_old_connections()
        before = len(self.processed)
        for jid in MigratemateJob.objects.exclude(migratemate_job_id="").values_list(
            "migratemate_job_id", flat=True
        ).iterator(chunk_size=5000):
            if jid:
                self.processed.add(jid)
        logger.info(
            "Resume: %s IDs in state, +%s from DB (total %s)",
            before,
            len(self.processed) - before,
            len(self.processed),
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

    def _human_delay(self, lo=0.25, hi=0.9):
        end = time.time() + random.uniform(lo, hi)
        while time.time() < end:
            if _should_stop():
                raise StopIteration
            time.sleep(0.12)

    def _ensure_session(self, page):
        if self._session_ready:
            return
        page.goto(OPEN_JOBS, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(4000)
        self._session_ready = True

    def _search_keyword_page(self, page, query, page_num):
        body = {
            "context": "demo",
            "indexName": "live-demo",
            "requests": [
                {
                    "indexName": "live-demo",
                    "params": {
                        "query": query,
                        "hitsPerPage": HITS_PER_PAGE,
                        "page": page_num,
                        "facetFilters": [["intern_y_n:NO"]],
                    },
                }
            ],
        }
        for attempt in range(2):
            out = page.evaluate(SEARCH_FETCH_JS, body)
            if out.get("ok"):
                data = out["data"]
                if "results" in data and data["results"]:
                    return data["results"][0]
                return data
            status = out.get("status")
            if status == 403 and attempt == 0:
                logger.info("Search 403 — refreshing session")
                self._session_ready = False
                self._ensure_session(page)
                page.wait_for_timeout(2000)
                continue
            err = (out.get("error") or "")[:200]
            logger.warning(
                "Search failed query=%s page=%s status=%s %s",
                query[:40] or "(browse)",
                page_num,
                status,
                err,
            )
            return None
        return None

    def _fetch_hits_for_query(self, page, query):
        merged = {}
        page_num = 0
        max_pages = MAX_PAGES_PER_KEYWORD
        while page_num < max_pages:
            self._check_stop()
            res = self._search_keyword_page(page, query, page_num)
            if not res:
                break
            hits = res.get("hits") or []
            nb_pages = int(res.get("nbPages") or 1)
            max_pages = min(max_pages, nb_pages)
            if not hits:
                break
            for hit in hits:
                oid = hit.get("objectID")
                if oid:
                    merged[oid] = hit
            page_num += 1
            if page_num >= nb_pages:
                break
            self._human_delay(0.2, 0.5)
        return list(merged.values())

    def _load_keyword_hits(self, page, keyword):
        merged = {}
        for query in _queries_for_keyword(keyword):
            if _should_stop():
                break
            for hit in self._fetch_hits_for_query(page, query):
                oid = hit.get("objectID")
                if oid and oid not in merged:
                    merged[oid] = hit
            self._human_delay(0.15, 0.35)
        return list(merged.values())

    def _scan_company_careers(self, request_ctx, company_url, job_title):
        urls = []
        if not company_url or not company_url.startswith("http"):
            return urls
        base = company_url.rstrip("/")
        title_words = [w.lower() for w in re.findall(r"[a-zA-Z]{4,}", job_title or "")][:4]

        for suffix in CAREER_PATH_SUFFIXES:
            if _should_stop():
                break
            try:
                target = base + suffix
                resp = request_ctx.get(target, timeout=20000)
                if resp.status >= 400:
                    continue
                soup = BeautifulSoup(resp.text(), "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if href.startswith("//"):
                        href = "https:" + href
                    elif href.startswith("/"):
                        href = urljoin(target, href)
                    if is_blocked_apply_host(href) or not is_valid_apply_url(href, company_url=company_url):
                        continue
                    text = (a.get_text() or "").lower()
                    if any(d in href.lower() for d in ATS_DOMAINS):
                        urls.append(href)
                    elif title_words and any(w in text for w in title_words):
                        urls.append(href)
            except Exception:
                continue
        return urls

    def _extract_apply_url(self, page, context, hit):
        self._check_stop()
        job_id = hit.get("objectID")
        title = hit.get("title") or ""
        company = hit.get("company") or ""
        slug = _company_slug(hit)
        company_urls = _company_url_guesses(company, slug)
        company_url = company_urls[0] if company_urls else ""

        candidates = []
        tokens = _board_tokens(company, slug)
        desc = hit.get("formatted_description") or ""
        candidates.extend(_find_ats_in_text(desc, company_url))

        gh = _greenhouse_apply(context.request, tokens, title, company)
        if gh:
            candidates.append(gh)
        lev = _lever_apply(context.request, tokens, title, company)
        if lev:
            candidates.append(lev)

        if not candidates and company_urls:
            for guess in company_urls[:2]:
                candidates.extend(self._scan_company_careers(context.request, guess, title))
                if candidates:
                    break

        if not candidates:
            try:
                page.goto(f"{OPEN_JOBS}?selectedJob={job_id}", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2000)
                for label, selector in (
                    ("Apply", 'button:has-text("Apply")'),
                    ("Apply Now", 'a:has-text("Apply Now")'),
                ):
                    try:
                        with context.expect_page(timeout=10000) as pinfo:
                            page.locator(selector).first.click(timeout=5000)
                        popup = pinfo.value
                        popup.wait_for_load_state("domcontentloaded", timeout=15000)
                        if popup.url and "migratemate" not in popup.url.lower():
                            candidates.insert(0, popup.url)
                        candidates.extend(_find_ats_in_text(popup.content(), company_url))
                        popup.close()
                    except Exception:
                        pass
                candidates.extend(_find_ats_in_text(page.content(), company_url))
                for sel in (
                    'a[href*="greenhouse"]',
                    'a[href*="lever.co"]',
                    'a[href*="myworkday"]',
                    'a[href*="amazon.jobs"]',
                    'a[href*="ashbyhq.com"]',
                ):
                    loc = page.locator(sel)
                    for i in range(min(3, loc.count())):
                        href = loc.nth(i).get_attribute("href")
                        if href and is_valid_apply_url(href, company_url=company_url):
                            candidates.append(href)
            except Exception as exc:
                logger.debug("Panel scrape %s: %s", job_id, exc)

        seen = set()
        for url in candidates:
            if not url or url in seen:
                continue
            seen.add(url)
            if "migratemate.co" in url.lower():
                continue
            ok, final = _is_job_page_ok(
                context.request, url, company_url, job_title=title, company_name=company
            )
            if ok:
                logger.info("ATS OK %s -> %s", job_id, final[:90])
                return final
        return None

    def _process_keyword(self, page, context, keyword, ki, total, display_keyword=None):
        saved_before = self.state.jobs_saved
        self._ensure_session(page)
        label = display_keyword or keyword or BROWSE_KEYWORD_LABEL
        hits = self._load_keyword_hits(page, keyword)
        if not hits:
            logger.info("No jobs for keyword: %s", label)
            return 0

        self._save_state(
            current_page=1,
            last_message=f"[{ki + 1}/{total}] {label} — {len(hits)} unique hits",
            current_keyword=label,
        )

        for hit in hits:
            if _should_stop():
                raise StopIteration

            job_id = hit.get("objectID")
            if not job_id or job_id in self.processed:
                continue
            if not is_usa_location(hit.get("location")):
                continue
            posted_ts = hit.get("date_posted_num")
            if not is_within_24h_timestamp(posted_ts):
                continue

            posted_label = format_posted_time(posted_ts) if posted_ts else hit.get("date_posted", "Recently")
            if not posted_label:
                continue

            self.processed.add(job_id)
            self._human_delay(0.12, 0.35)

            apply_url = self._extract_apply_url(page, context, hit)
            if not apply_url:
                self.state.jobs_skipped += 1
                logger.info("Skipped (no valid ATS): %s @ %s", hit.get("title"), hit.get("company"))
                self._save_state(jobs_skipped=self.state.jobs_skipped)
                continue

            title = (hit.get("title") or "").strip()
            company = (hit.get("company") or "").strip()
            location = (hit.get("location") or "United States").strip()

            if job_exists(title, company, location, apply_url):
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
                    source="MigrateMate",
                    keyword=label,
                    posted_time=posted_label,
                    posted_at=int(posted_ts) if posted_ts else int(time.time()),
                    migratemate_job_id=job_id,
                )
            except IntegrityError:
                self.state.jobs_skipped += 1
                self._save_state(jobs_skipped=self.state.jobs_skipped)
                logger.info("Duplicate skipped (DB): %s", apply_url[:80])
                continue

            self.state.jobs_saved += 1
            self._save_state(jobs_saved=self.state.jobs_saved)
            logger.info("Saved: %s @ %s (%s)", title, company, posted_label)

        return self.state.jobs_saved - saved_before

    def run(self):
        global _active_browser
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        close_old_connections()
        keywords = list(settings.KEYWORDS)
        work_items = []
        if BROWSE_EMPTY_QUERY:
            work_items.append(("", BROWSE_KEYWORD_LABEL))
        work_items.extend((k, k) for k in keywords)
        total = len(work_items)
        start_idx = self.state.keyword_index if self.resume else 0

        if not self.resume:
            self.processed.clear()
            self._save_state(
                status=MigratemateScraperState.STATUS_RUNNING,
                keyword_index=0,
                current_page=1,
                jobs_saved=0,
                jobs_skipped=0,
                last_message=f"MigrateMate scraper started — {total} search passes",
            )
        else:
            kw = self.state.current_keyword or (
                work_items[start_idx][1] if start_idx < total else ""
            )
            self._save_state(
                status=MigratemateScraperState.STATUS_RUNNING,
                last_message=f"Resuming pass {start_idx + 1}/{total}: '{kw}'",
            )

        logger.info("MigrateMate scraper started resume=%s idx=%s", self.resume, start_idx + 1)

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                with _active_lock:
                    _active_browser = browser

                for ki in range(start_idx, total):
                    self._check_stop()
                    query, label = work_items[ki]
                    context = browser.new_context(user_agent=USER_AGENT, locale="en-US", viewport={"width": 1400, "height": 900})
                    page = context.new_page()
                    self._session_ready = False

                    try:
                        self._save_state(
                            current_keyword=label,
                            keyword_index=ki,
                            current_page=1,
                            last_message=f"[{ki + 1}/{total}] Searching: {label}",
                        )
                        n = self._process_keyword(page, context, query, ki, total, display_keyword=label)
                        self._save_state(
                            keyword_index=ki + 1,
                            current_page=1,
                            last_message=f"[{ki + 1}/{total}] Done '{label}' (+{n} jobs)",
                        )
                    except StopIteration:
                        raise
                    except Exception as exc:
                        logger.exception("Keyword error %s: %s", label, exc)
                        self._save_state(
                            keyword_index=ki + 1,
                            last_message=f"Error on '{label}': {str(exc)[:120]}",
                        )
                    finally:
                        try:
                            context.close()
                        except Exception:
                            pass
                        self.resume = False
                        if not _should_stop():
                            self._human_delay(0.5, 1.0)

                try:
                    browser.close()
                except Exception:
                    pass
                with _active_lock:
                    _active_browser = None

                if not _should_stop():
                    self._save_state(
                        status=MigratemateScraperState.STATUS_IDLE,
                        keyword_index=total,
                        current_keyword="",
                        last_message=f"Completed all {total} MigrateMate keywords",
                    )

        except StopIteration:
            kw = self.state.current_keyword or "—"
            ki = self.state.keyword_index
            self._save_state(
                status=MigratemateScraperState.STATUS_STOPPED,
                keyword_index=ki,
                last_message=f"Stopped — Resume continues keyword {ki + 1}: '{kw}' (no duplicates)",
            )
            logger.info("MigrateMate stopped at keyword %s", kw)
        except Exception as exc:
            if _should_stop():
                self._save_state(status=MigratemateScraperState.STATUS_STOPPED, last_message="Stopped by user")
            else:
                self._save_state(status=MigratemateScraperState.STATUS_STOPPED, last_message=str(exc)[:500])
                logger.exception("MigrateMate scraper error: %s", exc)
        finally:
            _close_active_browser()


def start_scraper(resume=False):
    if is_scraper_running():
        return False, "MigrateMate scraper already running (separate process)"

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
        start_msg = f"Started fresh: cleared {deleted} jobs, keyword 1/{total}"
    else:
        state.status = MigratemateScraperState.STATUS_RUNNING
        kw = state.current_keyword or "—"
        idx = state.keyword_index
        state.last_message = f"Resuming keyword {idx + 1}/{total}: '{kw}' (no duplicates)"
        start_msg = None

    pid = spawn_worker(resume=resume)
    state.worker_pid = pid
    state.save()
    if start_msg:
        return True, start_msg
    return True, f"Resumed (PID {pid}) — continues from saved keyword"


def stop_scraper():
    state = MigratemateScraperState.get_singleton()
    if not is_scraper_running() and state.status != MigratemateScraperState.STATUS_RUNNING:
        return True, "MigrateMate scraper is not running"

    request_stop()
    _stop_event.set()
    terminate_pid(state.worker_pid)
    state.worker_pid = 0
    kw = state.current_keyword or "—"
    idx = state.keyword_index
    state.status = MigratemateScraperState.STATUS_STOPPED
    state.last_message = f"Stopped — click Resume for keyword {idx + 1}: '{kw}'"
    state.save()
    return True, state.last_message
