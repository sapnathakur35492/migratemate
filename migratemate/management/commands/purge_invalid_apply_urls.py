from django.conf import settings
from django.core.management.base import BaseCommand

from migratemate.models import MigratemateJob
from migratemate_site.apply_urls import is_blocked_apply_host, is_valid_apply_url


class Command(BaseCommand):
    help = "Remove migratemate portal links and other invalid apply URLs."

    def handle(self, *args, **options):
        deleted = 0
        for job in MigratemateJob.objects.iterator():
            url = job.apply_url or ""
            if "migratemate.co" in url.lower():
                reason = "migratemate portal"
            elif is_blocked_apply_host(url) or not is_valid_apply_url(url, settings.ALLOWED_ATS):
                reason = "invalid ATS"
            else:
                continue
            self.stdout.write(f"Removed ({reason}): {job.title} -> {url[:90]}")
            job.delete()
            deleted += 1
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} invalid apply URLs"))
