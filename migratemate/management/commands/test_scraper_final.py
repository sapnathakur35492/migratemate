"""Final QA: 24h filter, exp 0-5, ATS-only apply URLs, API + DB audit."""
import time
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from migratemate.models import MigratemateJob
from migratemate.scraper import (
    _api_credentials,
    is_experience_0_to_5,
    is_usa_location_string,
    is_valid_apply_url,
    is_usa_job,
)
from migratemate.time_utils import is_within_24h_timestamp
from migratemate_site.apply_live import is_apply_url_live
from migratemate_site.apply_urls import is_blocked_apply_host


class Command(BaseCommand):
    help = "Run final scraper quality tests (API, filters, saved jobs)."

    def handle(self, *args, **options):
        app_id, app_key = _api_credentials()
        if not app_id or not app_key:
            self.stderr.write(self.style.ERROR("Missing ADZUNA_APP_ID / ADZUNA_APP_KEY"))
            return

        ats = tuple(settings.ALLOWED_ATS)
        session = requests.Session()
        session.headers.update({"Accept": "application/json", "User-Agent": "AdzunaFinalTest/1.0"})
        failures = []

        # 1) API connectivity — sample keywords
        sample_kws = list(settings.KEYWORDS)[:5] + list(settings.KEYWORDS)[-3:]
        self.stdout.write(self.style.MIGRATE_HEADING("=== Adzuna API (24h, USA) ==="))
        for kw in sample_kws:
            url = (
                f"{settings.ADZUNA_API_BASE}/jobs/us/search/1"
                f"?app_id={quote(app_id)}&app_key={quote(app_key)}"
                f"&what={quote(kw)}&where={quote(settings.ADZUNA_DEFAULT_WHERE)}"
                f"&results_per_page=5&max_days_old=1&sort_by=date&content-type=application/json"
            )
            r = session.get(url, timeout=30)
            ok = r.status_code == 200 and len(r.json().get("results") or []) > 0
            self.stdout.write(f"  {'OK' if ok else 'FAIL'} {kw}: status={r.status_code} count={r.json().get('count', 0)}")
            if not ok:
                failures.append(f"API:{kw}")

        # 2) Unit filters
        self.stdout.write(self.style.MIGRATE_HEADING("=== Filters ==="))
        assert is_experience_0_to_5("Junior Software Engineer", "")
        assert not is_experience_0_to_5("Senior Director of Engineering", "")
        assert not is_experience_0_to_5("Engineer", "8+ years experience required")
        assert is_within_24h_timestamp(int(time.time()) - 3600)
        assert not is_within_24h_timestamp(int(time.time()) - 90000)
        self.stdout.write("  OK exp 0-5 + 24h timestamp checks")

        # 3) DB audit — every saved job
        self.stdout.write(self.style.MIGRATE_HEADING("=== Saved jobs audit ==="))
        jobs = list(MigratemateJob.objects.all().order_by("-id")[:500])
        total = MigratemateJob.objects.count()
        self.stdout.write(f"  Total jobs in DB: {total}")
        bad = 0
        dup_urls = set()
        dup_ids = set()
        live_session = requests.Session()
        live_session.headers.update({"User-Agent": "AdzunaAudit/1.0"})
        for j in jobs:
            url = j.apply_url or ""
            issues = []
            if not url.startswith("http"):
                issues.append("no_url")
            if is_blocked_apply_host(url) or "adzuna." in url.lower():
                issues.append("blocked_host")
            if not is_valid_apply_url(url, ats):
                issues.append("invalid_ats")
            if j.posted_at and not is_within_24h_timestamp(j.posted_at):
                issues.append("older_than_24h")
            if not is_experience_0_to_5(j.title, ""):
                issues.append("exp_filter")
            if not is_usa_location_string(j.location):
                issues.append("not_usa")
            if url in dup_urls:
                issues.append("duplicate_apply_url")
            dup_urls.add(url)
            if j.migratemate_job_id:
                if j.migratemate_job_id in dup_ids:
                    issues.append("duplicate_adzuna_id")
                dup_ids.add(j.migratemate_job_id)
            if issues:
                bad += 1
                failures.append(f"job#{j.id}:{','.join(issues)}")
                self.stdout.write(self.style.WARNING(f"  FAIL #{j.id} {j.title[:40]} — {issues} — {url[:70]}"))

        # Live check sample (max 15 to keep test fast)
        self.stdout.write(self.style.MIGRATE_HEADING("=== Live apply URL check (sample) ==="))
        dead = 0
        for j in jobs[:15]:
            if not is_apply_url_live(live_session, j.apply_url, ats):
                dead += 1
                failures.append(f"dead#{j.id}")
                self.stdout.write(self.style.WARNING(f"  DEAD apply: #{j.id} {j.apply_url[:80]}"))
        self.stdout.write(f"  Live sample: {15 - dead}/15 OK")

        # Keywords coverage
        kw_count = len(settings.KEYWORDS)
        distinct_kw = MigratemateJob.objects.values_list("keyword", flat=True).distinct().count()
        self.stdout.write(self.style.MIGRATE_HEADING("=== Summary ==="))
        self.stdout.write(f"  Keywords configured: {kw_count}")
        self.stdout.write(f"  Distinct keywords with saved jobs: {distinct_kw}")
        self.stdout.write(f"  DB jobs passing static rules: {len(jobs) - bad}/{len(jobs)} sampled")

        if failures:
            self.stderr.write(self.style.ERROR(f"FAILED ({len(failures)} issues): {failures[:20]}"))
        else:
            self.stdout.write(self.style.SUCCESS("ALL FINAL TESTS PASSED"))
