from django.contrib import admin

from .models import MigratemateJob, MigratemateScraperState


@admin.register(MigratemateJob)
class MigratemateJobAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "location", "keyword", "posted_time", "created_at")
    search_fields = ("title", "company", "keyword", "apply_url")
    list_filter = ("keyword", "company")


@admin.register(MigratemateScraperState)
class MigratemateScraperStateAdmin(admin.ModelAdmin):
    list_display = ("status", "current_keyword", "keyword_index", "jobs_saved", "jobs_skipped", "updated_at")
