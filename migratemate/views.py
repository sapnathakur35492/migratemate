from django.conf import settings
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .models import MigratemateJob, MigratemateScraperState
from .scraper import JOBS_PER_PAGE, is_scraper_running, start_scraper, stop_scraper
from .time_utils import format_posted_time


def search_passes_total():
    total = len(settings.KEYWORDS)
    if getattr(settings, "MIGRATEMATE_BROWSE_EMPTY_QUERY", False):
        total += 1
    return total


def dashboard(request):
    state = MigratemateScraperState.get_singleton()
    return render(
        request,
        "migratemate/dashboard.html",
        {
            "state": state,
            "job_count": MigratemateJob.objects.count(),
            "keywords_count": search_passes_total(),
            "max_age_hours": getattr(settings, "MIGRATEMATE_MAX_AGE_HOURS", 24),
        },
    )


def jobs_api(request):
    page_num = max(1, int(request.GET.get("page", 1)))
    qs = MigratemateJob.objects.all().order_by("-created_at")
    paginator = Paginator(qs, JOBS_PER_PAGE)
    page = paginator.get_page(page_num)
    jobs = []
    for j in page.object_list:
        ts = j.posted_at or int(j.created_at.timestamp())
        posted = format_posted_time(ts) or j.posted_time
        jobs.append(
            {
                "id": j.id,
                "title": j.title,
                "company": j.company,
                "location": j.location,
                "posted_time": posted,
                "keyword": j.keyword,
                "source": j.source,
                "apply_url": j.apply_url,
            }
        )
    return JsonResponse(
        {
            "jobs": jobs,
            "total": paginator.count,
            "page": page.number,
            "total_pages": paginator.num_pages,
            "per_page": JOBS_PER_PAGE,
            "has_next": page.has_next(),
            "has_previous": page.has_previous(),
        }
    )


def status_api(request):
    state = MigratemateScraperState.get_singleton()
    running = is_scraper_running()
    status = state.status
    if running:
        status = MigratemateScraperState.STATUS_RUNNING
    elif status == MigratemateScraperState.STATUS_RUNNING:
        status = MigratemateScraperState.STATUS_STOPPED
    total_kw = search_passes_total()
    kw_done = state.keyword_index
    if status == MigratemateScraperState.STATUS_IDLE and kw_done >= total_kw:
        kw_done = total_kw
    elif running:
        kw_done = min(state.keyword_index + 1, total_kw)
    return JsonResponse(
        {
            "status": status,
            "running": running,
            "current_keyword": state.current_keyword,
            "current_page": state.current_page,
            "keyword_index": state.keyword_index,
            "keywords_done": kw_done,
            "keywords_total": total_kw,
            "jobs_saved": state.jobs_saved,
            "jobs_skipped": state.jobs_skipped,
            "last_message": state.last_message,
            "job_count": MigratemateJob.objects.count(),
        }
    )


@require_http_methods(["POST"])
def scraper_start(request):
    ok, msg = start_scraper(resume=False)
    return JsonResponse({"ok": ok, "message": msg})


@require_http_methods(["POST"])
def scraper_stop(request):
    ok, msg = stop_scraper()
    return JsonResponse({"ok": ok, "message": msg})


@require_http_methods(["POST"])
def scraper_resume(request):
    if is_scraper_running():
        return JsonResponse({"ok": False, "message": "Already running"})
    ok, msg = start_scraper(resume=True)
    return JsonResponse({"ok": ok, "message": msg})


@require_http_methods(["POST"])
def jobs_clear_all(request):
    if is_scraper_running():
        return JsonResponse({"ok": False, "message": "Stop scraper before clearing"})
    deleted, _ = MigratemateJob.objects.all().delete()
    return JsonResponse({"ok": True, "message": f"Deleted {deleted} jobs", "deleted": deleted})
