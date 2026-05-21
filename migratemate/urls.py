from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/jobs/", views.jobs_api, name="jobs_api"),
    path("api/status/", views.status_api, name="status_api"),
    path("api/scraper/start/", views.scraper_start, name="scraper_start"),
    path("api/scraper/stop/", views.scraper_stop, name="scraper_stop"),
    path("api/scraper/resume/", views.scraper_resume, name="scraper_resume"),
    path("api/jobs/clear/", views.jobs_clear_all, name="jobs_clear_all"),
]
