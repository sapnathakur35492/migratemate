from django.db import models


class MigratemateJob(models.Model):
    title = models.CharField(max_length=500)
    company = models.CharField(max_length=300)
    location = models.CharField(max_length=300)
    apply_url = models.URLField(unique=True, max_length=2000)
    source = models.CharField(max_length=100, default="MigrateMate")
    keyword = models.CharField(max_length=200)
    posted_time = models.CharField(max_length=100)
    posted_at = models.PositiveIntegerField(default=0, db_index=True)
    migratemate_job_id = models.CharField(max_length=64, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["company", "title", "location"]),
        ]

    def __str__(self):
        return f"{self.title} @ {self.company}"


class MigratemateScraperState(models.Model):
    STATUS_IDLE = "idle"
    STATUS_RUNNING = "running"
    STATUS_STOPPED = "stopped"
    STATUS_CHOICES = [
        (STATUS_IDLE, "Idle"),
        (STATUS_RUNNING, "Running"),
        (STATUS_STOPPED, "Stopped"),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_IDLE)
    current_keyword = models.CharField(max_length=200, blank=True)
    current_page = models.PositiveIntegerField(default=1)
    keyword_index = models.PositiveIntegerField(default=0)
    jobs_saved = models.PositiveIntegerField(default=0)
    jobs_skipped = models.PositiveIntegerField(default=0)
    processed_ids = models.TextField(blank=True, default="")
    last_message = models.CharField(max_length=500, blank=True)
    worker_pid = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "MigrateMate scraper state"

    @classmethod
    def get_singleton(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
