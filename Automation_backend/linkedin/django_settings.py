# linkedin/django_settings.py
"""
Minimal Django settings for EshLead - Premium Unfold UI (Fixed).
"""
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from django.core.exceptions import ImproperlyConfigured

from linkedin.env_bootstrap import load_project_dotenv

load_project_dotenv()

from linkedin.unfold_sidebar import unfold_sidebar_navigation

# Playwright's sync API runs inside an async event loop
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

ROOT_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = ROOT_DIR

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if os.environ.get("ENV") == "production":
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set in production.")
    SECRET_KEY = "leadpilot-local-dev-key-change-in-production"

DEBUG = os.environ.get("DEBUG", "False").lower() == "true"
_IS_PRODUCTION = os.environ.get("ENV", "").lower() == "production"

# Local/dev without DEBUG: runserver and tests still work without exporting ALLOWED_HOSTS.
_default_allowed = (
    "" if _IS_PRODUCTION else "localhost,127.0.0.1"
)
raw_hosts = os.environ.get("ALLOWED_HOSTS", "*" if DEBUG else _default_allowed)
ALLOWED_HOSTS = [h.strip() for h in raw_hosts.split(",") if h.strip()]

if not ALLOWED_HOSTS and _IS_PRODUCTION:
    raise ImproperlyConfigured("ALLOWED_HOSTS must be set in production.")

# Django's test client uses host "testserver"; narrow .env ALLOWED_HOSTS often omits it.
if not _IS_PRODUCTION and ALLOWED_HOSTS != ["*"]:
    for _h in ("testserver", "localhost", "127.0.0.1"):
        if _h not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(_h)

INSTALLED_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.import_export",
    "unfold.contrib.simple_history",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "import_export",
    "simple_history",
    "linkedin",
    "crm",
    "chat",
    "google_integration",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
]

CORS_ALLOW_ALL_ORIGINS = os.environ.get("CORS_ALLOW_ALL", "false").lower() == "true"
ROOT_URLCONF = "linkedin.urls"

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

def _database_from_url(db_url: str) -> dict:
    parsed = urlparse(db_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured(
            "Unsupported database URL scheme. Use postgres:// or postgresql://"
        )

    query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
    options = {"sslmode": query.pop("sslmode", "require"), **query}

    config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/") or "postgres",
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or 5432),
    }
    if options:
        config["OPTIONS"] = options
    return config


supabase_url = os.environ.get("SUPABASE_URL")
if not supabase_url:
    raise ImproperlyConfigured(
        "SUPABASE_URL must be set to your Supabase Postgres connection string "
        "(project root `.env` is loaded automatically when using manage.py)."
    )

DATABASES = {"default": _database_from_url(supabase_url)}

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_BASE = os.environ.get("GOOGLE_REDIRECT_BASE", "")

if not _IS_PRODUCTION and (
    not os.environ.get("OAUTHLIB_INSECURE_TRANSPORT")
    and (GOOGLE_REDIRECT_BASE.startswith("http://") if GOOGLE_REDIRECT_BASE else True)
):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/static/"
STATIC_ROOT = ROOT_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = ROOT_DIR / "media"
LOGIN_URL = "/admin/login/"
LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
# Allow embedding Django admin pages when proxied through the same Next.js origin.
X_FRAME_OPTIONS = "SAMEORIGIN"

UNFOLD = {
    "SITE_TITLE": "EshLead",
    "SITE_HEADER": "EshLead Admin",
    "SITE_URL": "/",
    "DASHBOARD_CALLBACK": "linkedin.views.dashboard_callback",
    "SIDEBAR": {
        "show_search": True,
        "command_search": False,
        "show_all_applications": False,
        "navigation": unfold_sidebar_navigation,
    },
    "COLORS": {
        "primary": {
            "50": "250 245 255",
            "100": "243 232 255",
            "200": "233 213 255",
            "300": "216 180 254",
            "400": "192 132 252",
            "500": "168 85 247",
            "600": "147 51 234",
            "700": "126 34 206",
            "800": "107 33 168",
            "900": "88 28 135",
            "950": "59 7 100",
        },
    },
}

TESTING = sys.argv[1:2] == ["test"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": ROOT_DIR / "leadpilot.log",
            "maxBytes": 1024 * 1024 * 5,  # 5MB
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "linkedin": {
            "handlers": ["console", "file"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
    },
}

