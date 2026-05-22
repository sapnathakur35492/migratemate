import os

from django.core.management.base import BaseCommand

from migratemate.models import MigratemateScraperState
from migratemate.scraper import AdzunaScraper
from migratemate_site.scraper_process import clear_stop_flag


class Command(BaseCommand):
    help = "Run Adzuna scraper in this process (used by dashboard Start button)."

    def add_arguments(self, parser):
        parser.add_argument("--resume", action="store_true", help="Resume from saved keyword index")

    def handle(self, *args, **options):
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        clear_stop_flag()
        state = MigratemateScraperState.get_singleton()
        state.worker_pid = os.getpid()
        state.status = MigratemateScraperState.STATUS_RUNNING
        state.save(update_fields=["worker_pid", "status"])

        self.stdout.write(self.style.SUCCESS(f"Adzuna worker started PID={os.getpid()}"))

        try:
            AdzunaScraper(resume=options["resume"]).run()
        finally:
            state = MigratemateScraperState.get_singleton()
            if state.worker_pid == os.getpid():
                state.worker_pid = 0
                if state.status == MigratemateScraperState.STATUS_RUNNING:
                    state.status = MigratemateScraperState.STATUS_IDLE
                state.save(update_fields=["worker_pid", "status"])
            self.stdout.write("Adzuna worker exited.")
