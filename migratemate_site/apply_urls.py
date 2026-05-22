"""Apply URL rules: company career pages and ATS only — never LinkedIn/job boards."""
import re
from urllib.parse import urlparse

BLOCKED_HOST_PARTS = (
    "linkedin.com",
    "lnkd.in",
    "licdn.com",
    "indeed.com",
    "glassdoor.com",
    "ziprecruiter.com",
    "monster.com",
    "careerbuilder.com",
    "dice.com",
    "simplyhired.com",
    "talent.com",
    "jooble.org",
    "flexjobs.com",
    "theladders.com",
    "builtin.com",
    "wellfound.com",
    "angellist.com",
)

BLOCKED_SITE_PARTS = (
    "migratemate.co",
    "adzuna.com",
    "adzuna.co.uk",
    "zunastatic",
    "kxcdn.com",
    "jobright.ai",
    "jobright.com",
    "simplify.jobs",
)

EMPLOYER_PLATFORM_HOST_PARTS = (
    "greenhouse.io",
    "lever.co",
    "myworkdayjobs.com",
    "myworkdaysite.com",
    "ashbyhq.com",
    "smartrecruiters.com",
    "bamboohr.com",
    "icims.com",
    "jobvite.com",
    "taleo.net",
    "successfactors.com",
    "oraclecloud.com",
    "pinpointhq.com",
    "amazon.jobs",
    "careers.microsoft.com",
    "apply.careers.microsoft.com",
    "rippling.com",
    "workable.com",
    "recruitee.com",
    "jobs2web.com",
    "metacareers.com",
    "ultipro.com",
    "paylocity.com",
    "dayforcehcm.com",
    "csod.com",
    "jobs.apple.com",
)

CAREER_PATH_SEGMENTS = frozenset(
    {
        "jobs",
        "job",
        "careers",
        "career",
        "apply",
        "positions",
        "position",
        "openings",
        "opening",
        "requisition",
        "requisitions",
        "opportunities",
        "vacancies",
        "vacancy",
        "roles",
        "role",
        "join-us",
        "work-with-us",
        "open-positions",
        "postings",
        "posting",
        "employment",
        "recruit",
        "hiring",
        "jobdetail",
        "candidateexperience",
    }
)


def _host(url):
    return urlparse(url).netloc.lower().replace("www.", "", 1)


def _path_segments(url):
    path = urlparse(url).path.lower().strip("/")
    if not path:
        return []
    return [s for s in path.split("/") if s]


def is_blocked_apply_host(url):
    if not url:
        return True
    low = url.lower()
    for part in BLOCKED_SITE_PARTS:
        if part in low:
            return True
    host = _host(url)
    if not host:
        return True
    for blocked in BLOCKED_HOST_PARTS:
        b = blocked.split("/")[0]
        if b in host or host.endswith("." + b):
            return True
    return False


def _company_hosts(company_url):
    if not company_url or not str(company_url).startswith("http"):
        return set()
    netloc = urlparse(company_url).netloc.lower()
    if not netloc:
        return set()
    base = netloc.replace("www.", "", 1)
    return {netloc, base, f"www.{base}"}


def _host_on_company_domain(host, company_url):
    company_hosts = _company_hosts(company_url)
    if not company_hosts:
        return False
    h = host.replace("www.", "", 1)
    for ch in company_hosts:
        cb = ch.replace("www.", "", 1)
        if h == cb or h.endswith(f".{cb}"):
            return True
    return False


def _has_career_segment(url):
    segs = _path_segments(url)
    if not segs:
        return False
    if any(s in CAREER_PATH_SEGMENTS for s in segs):
        return True
    low = url.lower()
    return "jobdetail" in low or "candidateexperience" in low


def _is_ats_url(url, ats_domains):
    host = _host(url)
    for domain in ats_domains:
        d = domain.lower().lstrip(".")
        if host == d or host.endswith("." + d) or d in host:
            return True
    return False


def is_pure_board_ats_host(url):
    """Third-party job boards (not the company's own careers domain)."""
    host = _host(url)
    return "greenhouse.io" in host or "lever.co" in host


def _company_name_tokens(company):
    company = (company or "").strip().lower()
    if not company:
        return []
    slug = re.sub(r"[^a-z0-9]+", "-", company).strip("-")
    tokens = []
    if slug and len(slug) >= 3:
        tokens.append(slug.replace("-", ""))
        tokens.append(slug.split("-")[0])
    clean = re.sub(r"[^a-z0-9]", "", company)
    if clean and len(clean) >= 4:
        tokens.append(clean)
    return list(dict.fromkeys(t for t in tokens if len(t) >= 3))


def _host_matches_company_name(host, company):
    if not company or not host:
        return False
    h = host.replace("www.", "", 1).replace("-", "").replace(".", "")
    for token in _company_name_tokens(company):
        if token in h:
            return True
    return False


def is_company_career_apply_url(url, ats_domains, company=""):
    """
    Company's own careers site (e.g. careers.acme.com, acme.com/jobs/123).
    Excludes boards.greenhouse.io and jobs.lever.co.
    """
    if not url or not is_valid_apply_url(url, ats_domains):
        return False
    if is_pure_board_ats_host(url):
        return False
    host = _host(url)
    if host.startswith("careers.") or host.startswith("jobs.") or ".careers." in host:
        return True
    if company and _host_matches_company_name(host, company) and _has_career_segment(url):
        return True
    if _host_matches_company_name(host, company) and re.search(
        r"/(jobs?|careers?|positions?|openings?)/[^/]{4,}",
        urlparse(url).path,
        re.I,
    ):
        return True
    return False


def apply_url_priority(url, ats_domains, company=""):
    """0 = company career page, 1 = hosted ATS (Workday etc.), 2 = GH/Lever board."""
    if is_company_career_apply_url(url, ats_domains, company=company):
        return 0
    if is_pure_board_ats_host(url):
        return 2
    return 1


def _is_employer_platform_url(url):
    host = _host(url)
    for part in EMPLOYER_PLATFORM_HOST_PARTS:
        if part in host:
            return _has_career_segment(url)
    if host.endswith("google.com") and "/careers/" in url.lower():
        return True
    return False


GENERIC_CAREER_SLUGS = frozenset(
    {
        "careers",
        "jobs",
        "job",
        "open-positions",
        "positions",
        "opportunities",
        "employment",
        "hiring",
        "join-us",
        "work-with-us",
    }
)


_IMAGE_EXT = re.compile(r"\.(png|jpe?g|gif|svg|webp|ico|bmp|tiff?)(\?|#|$)", re.I)


def is_specific_job_apply_url(url):
    if not url:
        return False
    low = url.lower()
    if _IMAGE_EXT.search(low):
        return False
    if "migratemate.co" in low:
        return False
    if "error=true" in low or "error=404" in low:
        return False
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    segs = [s for s in path.split("/") if s]
    if "greenhouse.io" in low:
        if "gh_jid=" in low or "/jobs/" in low:
            return True
        if len(segs) <= 1:
            return False
        return bool(re.search(r"/jobs/\d+", low))
    if "lever.co" in low:
        if len(segs) >= 2 and segs[-1] not in GENERIC_CAREER_SLUGS:
            return len(segs[-1]) >= 6
        return False
    if "ashbyhq.com" in low:
        if len(segs) >= 2 and segs[-1] not in GENERIC_CAREER_SLUGS:
            return len(segs[-1]) >= 20 or bool(re.search(r"[0-9a-f-]{20,}", segs[-1]))
        return False
    if "myworkdayjobs.com" in low or "myworkdaysite.com" in low:
        return "jobdetail" in low or "/job/" in low or "_jr" in low or "/opportunity/" in low
    if "smartrecruiters.com" in low:
        return "/job/" in low or "/jobs/" in low
    if "oraclecloud.com" in low:
        return "jobdetail" in low or "requisition" in low
    if "icims.com" in low or "jobvite.com" in low:
        if "login" in low or "/intro" in low or "loginonly" in low:
            return False
        return len(segs) >= 3 and segs[-1] not in GENERIC_CAREER_SLUGS and bool(
            re.search(r"\d{4,}", segs[-1])
        )
    if _has_career_segment(url):
        if re.search(r"/(jobs?|positions?|openings?|requisitions?|jobdetail)/[^/]{4,}", parsed.path, re.I):
            return True
        if re.search(r"/careers/[^/]{12,}", parsed.path, re.I):
            last = segs[-1] if segs else ""
            if any(x in last for x in ("engineering", "team", "department", "overview", "life-at", "culture")):
                return False
            if last.isdigit() or re.search(r"\d{5,}", last):
                return True
            if len(last) >= 20 and re.search(r"\d", last):
                return True
            return len(last) >= 15 and re.search(r"\d{3,}", last)
        return False
    return False


def is_relaxed_apply_url(url, ats_domains, company_url=""):
    """
    Volume mode: accept company career pages, ATS hosts, and employer apply paths
    (not Indeed/LinkedIn/Adzuna). Less strict than is_specific_job_apply_url alone.
    """
    if not url or not str(url).strip().startswith("http"):
        return False
    url = url.strip()
    if is_blocked_apply_host(url) or _IMAGE_EXT.search(url.lower()):
        return False
    if is_valid_apply_url(url, ats_domains, company_url=company_url):
        return True
    host = _host(url)
    if _is_ats_url(url, ats_domains) or _is_employer_platform_url(url):
        return True
    if _has_career_segment(url):
        return True
    if re.search(r"/(job|jobs|career|careers|apply|position|opening|requisition)s?/", url, re.I):
        return True
    if company_url and _host_on_company_domain(host, company_url):
        return True
    return False


def is_valid_apply_url(url, ats_domains, company_url=""):
    if not url or not str(url).strip().startswith("http"):
        return False
    url = url.strip()
    if is_blocked_apply_host(url):
        return False
    if not is_specific_job_apply_url(url):
        return False
    host = _host(url)
    if _is_ats_url(url, ats_domains) or _is_employer_platform_url(url):
        return True
    if company_url and _host_on_company_domain(host, company_url):
        if _has_career_segment(url):
            return True
        if re.search(r"/(jobs?|positions?|openings?|requisitions?)/[^/]+", urlparse(url).path, re.I):
            return True
    if _has_career_segment(url) and re.search(
        r"/(jobs?|positions?|openings?|requisitions?|careers)/[^/]{8,}",
        urlparse(url).path,
        re.I,
    ):
        return True
    return False
