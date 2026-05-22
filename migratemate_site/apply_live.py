"""Verify ATS apply URLs are live (not 404 / removed)."""
import re
from urllib.parse import urlparse

from migratemate_site.apply_urls import (
    is_blocked_apply_host,
    is_relaxed_apply_url,
    is_valid_apply_url,
)

DEAD_PAGE_MARKERS = (
    "page not found",
    "404 error",
    "job no longer",
    "position filled",
    "expired",
    "couldn't find anything",
    "could not find anything",
    "has been removed",
    "might have closed",
    "no longer available",
    "sorry, we couldn't",
    "sorry, we could not",
    "job posting you're looking for",
    "not accepting applications",
)


def page_body_is_dead(body_low):
    if not body_low:
        return False
    return any(m in body_low for m in DEAD_PAGE_MARKERS)


def parse_lever_url(url):
    parsed = urlparse(url)
    if "lever.co" not in parsed.netloc.lower():
        return None, None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and re.match(r"^[0-9a-f-]{8,}$", parts[1], re.I):
        return parts[0], parts[1]
    return None, None


def lever_posting_live(session, url):
    site, posting_id = parse_lever_url(url)
    if not site or not posting_id:
        return False
    try:
        r = session.get(f"https://api.lever.co/v0/postings/{site}/{posting_id}", timeout=15)
        if r.status_code == 200:
            return True
        r = session.get(f"https://api.lever.co/v0/postings/{site}?mode=json", timeout=15)
        if r.status_code != 200:
            return False
        posts = r.json()
        return isinstance(posts, list) and any((p.get("id") or "") == posting_id for p in posts)
    except Exception:
        return False


def parse_greenhouse_parts(url):
    job_id = None
    m = re.search(r"gh_jid=(\d+)", url, re.I)
    if m:
        job_id = m.group(1)
    if not job_id:
        m = re.search(r"/jobs/(\d+)", url, re.I)
        if m:
            job_id = m.group(1)
    board = None
    m = re.search(r"greenhouse\.io/([^/]+)/jobs/", url, re.I)
    if m:
        board = m.group(1)
    return board, job_id


def greenhouse_job_live(session, url):
    board, job_id = parse_greenhouse_parts(url)
    if board and job_id:
        try:
            r = session.get(
                f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}",
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                return bool(data.get("id") or data.get("absolute_url"))
        except Exception:
            pass
    return False


def is_apply_url_live(session, url, ats_domains, company_url=""):
    if not url or not str(url).startswith("http"):
        return False
    if is_blocked_apply_host(url) or not is_valid_apply_url(url, ats_domains, company_url=company_url):
        return False
    low = url.lower()
    # Fast path: Lever/Greenhouse API confirms posting (skip slow HTML fetch)
    if "lever.co" in low:
        return lever_posting_live(session, url)
    if "greenhouse.io" in low:
        return greenhouse_job_live(session, url)
    try:
        resp = session.head(url, allow_redirects=True, timeout=10)
        final = resp.url
        status = resp.status_code
        if status >= 400 or status == 405:
            resp = session.get(url, allow_redirects=True, timeout=12)
            final = resp.url
            status = resp.status_code
        if status >= 400:
            return False
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if ctype.startswith("image/"):
            return False
        if is_blocked_apply_host(final) or not is_valid_apply_url(final, ats_domains, company_url=company_url):
            return False
        if resp.request.method == "GET":
            body = (resp.text or "").lower()[:25000]
            if body and page_body_is_dead(body):
                return False
        return True
    except Exception:
        return False


def is_apply_url_live_relaxed(session, url, ats_domains, company_url=""):
    """Fast check for volume mode — HEAD only, accepts relaxed employer URLs."""
    if not url or not str(url).startswith("http"):
        return False
    if is_blocked_apply_host(url) or not is_relaxed_apply_url(url, ats_domains, company_url=company_url):
        return False
    low = url.lower()
    if "lever.co" in low:
        return lever_posting_live(session, url)
    if "greenhouse.io" in low:
        return greenhouse_job_live(session, url)
    try:
        resp = session.head(url, allow_redirects=True, timeout=8)
        if resp.status_code >= 400 or resp.status_code == 405:
            resp = session.get(url, allow_redirects=True, timeout=10)
        if resp.status_code >= 400:
            return False
        final = resp.url or url
        if is_blocked_apply_host(final):
            return False
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if ctype.startswith("image/"):
            return False
        return True
    except Exception:
        return False


def trust_board_api_url(session, url, ats_domains):
    """Fast accept for Greenhouse/Lever URLs returned by board APIs."""
    if not url or not is_valid_apply_url(url, ats_domains):
        return False
    low = url.lower()
    if "lever.co" in low:
        return lever_posting_live(session, url)
    if "greenhouse.io" in low:
        return greenhouse_job_live(session, url)
    return False
