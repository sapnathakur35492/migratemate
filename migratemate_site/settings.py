"""Django settings for standalone Adzuna scraper project."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and val and key not in os.environ:
            os.environ[key] = val

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "migratemate-standalone-dev-key-change-in-production",
)

DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "migratemate",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "migratemate_site.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "migratemate_site.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 60},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

RUNSERVER_PORT = 8002

# Adzuna API (register at https://developer.adzuna.com/signup)
ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
ADZUNA_COUNTRY = "us"
ADZUNA_RESULTS_PER_PAGE = 50
ADZUNA_MAX_PAGES_PER_KEYWORD = 50
ADZUNA_MAX_DAYS_OLD = 1
ADZUNA_DEFAULT_WHERE = "United States"
ADZUNA_API_BASE = "https://api.adzuna.com/v1/api"

ALLOWED_ATS = [
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
    "oraclecloud.com",
    "successfactors.com",
    "pinpointhq.com",
    "amazon.jobs",
    "careers.microsoft.com",
    "jobs.apple.com",
    "workable.com",
    "recruitee.com",
    "rippling.com",
    "ultipro.com",
    "paylocity.com",
]

# Same 81 keywords as simplify/jobscraper/settings.py
KEYWORDS = [
    "Software engineer",
    "Software developer",
    "Backend developer",
    "Full stack developer",
    "Frontend developer",
    "Platform engineer",
    "System engineer",
    "Java backend developer",
    "Java developer",
    "iOS developer",
    "Android developer",
    "React native developer",
    "Cloud engineer",
    "Devops engineer",
    "Cloud developer",
    "Site reliability engineer",
    "Data analyst",
    "Data engineer",
    "Data science",
    "Machine learning engineer",
    "AI engineer",
    "Gen AI",
    "Analytics engineer",
    "Business intelligence analyst",
    "Security engineer",
    "Cybersecurity analyst",
    "Security analyst",
    "Application security engineer",
    "Network security engineer",
    "QA engineer",
    "Test engineer",
    "Automation test engineer",
    "QA analyst",
    "SDET",
    "Product manager",
    "Engineering manager",
    "UI designer",
    "UX designer",
    "Product designer",
    "SQL developer",
    "ETL developer",
    "Network engineer",
    "Systems administrator",
    "IT support engineer",
    "Technical support engineer",
    "Blockchain developer",
    "Robotics engineer",
    "Graphics engineer",
    "SAP developer",
    "SAP",
    "Salesforce developer",
    "Salesforce administrator",
    "Business analyst",
    "Supply chain",
    "Marketing manager",
    "Marketing analyst",
    "Project manager",
    "Program manager",
    "Aerospace engineer",
    "Mechanical engineer",
    "Civil engineer",
    "Physical therapist",
    "Supply chain manager",
    "Finance analyst",
    "Risk analyst",
    "Finance manager",
    "Product analyst",
    "Product owner",
    "Information security analyst",
    "AWS Azure",
    "AWS Java developer",
    "Quality engineer",
    ".NET developer",
    "Clinical research scientist",
    "Embedded systems engineer",
    "Drug safety associate",
    "AWS DevOps engineer",
    "Quality control",
    "Construction engineer",
    "Power Platform developer",
    "UI UX designer",
]

LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "file": {
            "level": "INFO",
            "class": "logging.FileHandler",
            "filename": LOGS_DIR / "scraper.log",
            "formatter": "verbose",
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "migratemate_scraper": {
            "handlers": ["file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        "scraper_process": {
            "handlers": ["file", "console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
