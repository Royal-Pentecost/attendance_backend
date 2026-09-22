"""
config/settings/dev.py

Local development settings. Uses SQLite — no Postgres driver required.
Select via: DJANGO_SETTINGS_MODULE=config.settings.dev
(manage.py and wsgi/asgi default to this when the variable is not set)
"""
from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
