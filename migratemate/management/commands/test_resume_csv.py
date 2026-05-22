"""Test CSV export row count and duplicate guards."""
import csv
import io

from django.core.management.base import BaseCommand
from django.test import Client

from migratemate.models import MigratemateJob
from migratemate.scraper import is_usa_location_string, job_exists
from migratemate.views import CSV_COLUMNS


class Command(BaseCommand):
    help = "Verify CSV export and resume duplicate protection."

    def handle(self, *args, **options):
        client = Client()
        resp = client.get("/api/jobs/export.csv")
        if resp.status_code != 200:
            self.stderr.write(self.style.ERROR(f"CSV export failed: {resp.status_code}"))
            return
        text = resp.content.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        header = rows[0]
        db_count = MigratemateJob.objects.count()
        data_rows = len(rows) - 1
        if header != list(CSV_COLUMNS):
            self.stderr.write(self.style.ERROR(f"Bad header: {header}"))
            return
        if data_rows != db_count:
            self.stderr.write(self.style.ERROR(f"CSV {data_rows} rows != DB {db_count}"))
            return
        self.stdout.write(self.style.SUCCESS(f"CSV OK: {data_rows} jobs, {len(header)} columns"))

        dup_urls = MigratemateJob.objects.values("apply_url").distinct().count()
        if dup_urls != db_count and db_count > 0:
            self.stderr.write(self.style.ERROR(f"Duplicate apply_url: {db_count - dup_urls}"))
            return
        self.stdout.write(self.style.SUCCESS("No duplicate apply_url in DB"))

        non_usa = [j for j in MigratemateJob.objects.all() if not is_usa_location_string(j.location)]
        if non_usa:
            self.stderr.write(self.style.ERROR(f"Non-USA locations: {len(non_usa)}"))
            return
        self.stdout.write(self.style.SUCCESS("All saved locations pass USA audit"))

        if db_count:
            j = MigratemateJob.objects.first()
            if not job_exists(j.title, j.company, j.location, j.apply_url, j.migratemate_job_id):
                self.stderr.write(self.style.ERROR("job_exists failed on existing row"))
                return
            self.stdout.write(self.style.SUCCESS("Resume duplicate guard OK"))

        self.stdout.write(self.style.SUCCESS("ALL resume/CSV checks passed"))
