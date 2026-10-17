"""
Django settings for the Mycelium backend (config project).

Environment variables are loaded from a local ``backend/.env`` file
(see ``backend/.env.example``). Required secrets must never be hardcoded.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load backend/.env if it exists. Existing environment values win over the file.
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    """Read a boolean environment variable ("true"/"1"/"yes" are truthy)."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=None):
    """Read a comma-separated environment variable into a list."""
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return list(default or [])
    return [item.strip() for item in value.split(",") if item.strip()]


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is not set. Copy backend/.env.example to backend/.env "
        "and provide a value for DJANGO_SECRET_KEY."
    )

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool("DJANGO_DEBUG", default=False)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "corsheaders",
    # Local
    "family",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "family.middleware.NoStoreApiMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases
#
# SQLite is the local development default: no server, no credentials.
# PostgreSQL is the production database (Render): set DB_ENGINE=postgresql
# and provide the POSTGRES_* credentials. Nothing remote is required or
# contacted unless opted in.

DB_ENGINE = os.getenv("DB_ENGINE", "sqlite").strip().lower()

if DB_ENGINE == "postgresql":
    REQUIRED_DB_VARS = [
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
    ]
    _missing_db_vars = [name for name in REQUIRED_DB_VARS if not os.getenv(name)]
    if _missing_db_vars:
        raise ImproperlyConfigured(
            "DB_ENGINE=postgresql but required environment variables are "
            "missing: "
            + ", ".join(_missing_db_vars)
            + ".\nProvide them via the hosting provider's environment "
            "(see backend/.env.example)."
        )
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB"),
            "USER": os.getenv("POSTGRES_USER"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
            "HOST": os.getenv("POSTGRES_HOST"),
            "PORT": os.getenv("POSTGRES_PORT"),
        }
    }
elif DB_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured(
        f'Unsupported DB_ENGINE="{DB_ENGINE}". Use "sqlite" or "postgresql".'
    )


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "UTC")

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media files (user uploads, e.g. family-member photos)
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Upload limits: photos are content-verified by Pillow via ImageField, and
# these caps bound request/file sizes (5 MiB is generous for member photos).
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# File storage: local disk by default. Set CLOUDINARY_URL (or the
# CLOUDINARY_CLOUD_NAME/_API_KEY/_API_SECRET trio) to store uploads in
# Cloudinary instead. Photo access stays ownership-checked in both modes.
USE_CLOUDINARY = bool(
    os.getenv("CLOUDINARY_URL")
    or os.getenv("CLOUDINARY_CLOUD_NAME")
)
if USE_CLOUDINARY:
    try:
        import cloudinary  # noqa: F401
    except ImportError:
        raise ImproperlyConfigured(
            "Cloudinary credentials are set but the 'cloudinary' packages "
            "are not installed. Install backend/requirements.txt first."
        )
    STORAGES = {
        "default": {"BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"
        },
    }
    CLOUDINARY_URL = os.getenv("CLOUDINARY_URL", "")
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"
        },
    }

# Production hardening. Leave off locally; enable on Render via
# DJANGO_SECURE=1 (with HTTPS, which Render provides).
SECURE_BEHIND_TLS = env_bool("DJANGO_SECURE", default=False)
if SECURE_BEHIND_TLS:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# Default primary key field type
# https://docs.djangoproject.com/en/6.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Cross-origin resource sharing
# Only the local frontend origin(s) listed in FRONTEND_ORIGIN are allowed.
# Credentials are enabled so the browser session cookie works across the
# local dev origins; never enable unrestricted origins in production.
CORS_ALLOWED_ORIGINS = env_list("FRONTEND_ORIGIN")
CORS_ALLOW_CREDENTIALS = True

# CSRF trusts the same narrow frontend origin(s) for session-based posts.
CSRF_TRUSTED_ORIGINS = env_list("FRONTEND_ORIGIN")


# Django REST Framework
# Authenticated by default (fail closed); the health check, registration,
# login, and CSRF endpoints explicitly allow anonymous access.
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_RATES": {
        "storyhelper": "20/hour",
    },
}


# Groq (AI story helper)
# The key is optional so the application starts and serves health checks
# even when no Groq key is configured. It is only ever read by backend code.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")


# Email (password reset and notifications are future work; no SMTP is
# required for local development — mail prints to the console).
EMAIL_BACKEND = os.getenv(
    "DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
try:
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
except ValueError:
    raise ImproperlyConfigured("EMAIL_PORT must be a number.")
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "mycelium@localhost")
