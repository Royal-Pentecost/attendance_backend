"""
config/settings/prod.py

Production settings. Requires all environment variables to be set.
Select via: DJANGO_SETTINGS_MODULE=config.settings.prod
"""
from decouple import config, Csv

from .base import *  # noqa: F401, F403

DEBUG = False

# In prod, SECRET_KEY has no fallback — decouple raises UndefinedValueError
# if the variable is missing, which prevents a silent mis-deployment.
SECRET_KEY = config("SECRET_KEY")

ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())

# ---------------------------------------------------------------------------
# Database — PostgreSQL via psycopg (psycopg3)
# Django 6.x uses 'django.db.backends.postgresql' with psycopg3 automatically
# when psycopg (not psycopg2) is installed.
# ---------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
    }
}

# ---------------------------------------------------------------------------
# Security hardening
# ---------------------------------------------------------------------------

SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# ---------------------------------------------------------------------------
# Email — override in prod via environment or a real MAILERS config
# ---------------------------------------------------------------------------

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
    },
}
