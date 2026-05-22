import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from migratemate.models import MigratemateJob
from migratemate_site.apply_live import is_apply_url_live
from migratemate_site.apply_urls import is_blocked_apply_host, is_valid_apply_url


class Command(BaseCommand):
    help = "Remove Adzuna portal, invalid ATS, and dead (404) apply URLs."

    def handle(self, *args, **options):
        ats = tuple(settings.ALLOWED_ATS)
        session = requests.Session()
        session.headers.update({"User-Agent": "MigrateMate-Purge/1.0"})
        deleted = 0
        for job in MigratemateJob.objects.iterator():
            url = job.apply_url or ""
            reason = None
            if "adzuna." in url.lower() or "migratemate.co" in url.lower():
                reason = "aggregator portal"
            elif is_blocked_apply_host(url) or not is_valid_apply_url(url, ats):
                reason = "invalid ATS"
            elif not is_apply_url_live(session, url, ats):
                reason = "dead/404"
            if reason:
                self.stdout.write(f"Removed ({reason}): {job.title} -> {url[:90]}")
                job.delete()
                deleted += 1
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} jobs"))
