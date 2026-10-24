from pathlib import Path

from decouple import config

# pentecost-attendance-backend/ (three levels up from this file)
BASE_DIR = Path(__file__).resolve().parent.parent.parent



SECRET_KEY = config(
    "SECRET_KEY",
    default="django-insecure-local-dev-only-change-before-deploying",
)


INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    # Local migration dependency order: core → accounts → attendance/content/milestones
    "core",
    "accounts",
    "attendance",
    "content",
    "milestones",
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

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

# Authentication

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Django REST Framework

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# drf-spectacular — OpenAPI schema generation

SPECTACULAR_SETTINGS = {
    "TITLE": "Pentecost Attendance API",
    "DESCRIPTION": "API for the Pentecost Attendance platform multi-branch church membership and attendance tracking.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "WeekdayEnum": "accounts.models.DayBornGroup.WEEKDAY_CHOICES",
    },
}

# Internationalisation

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static & media files

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Primary key default type

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# OTP / SMS

OTP_LENGTH = 4
OTP_EXPIRY_SECONDS = 300   # 5 minutes
OTP_MAX_ATTEMPTS = 5

# Email (console backend — dev-safe default; prod.py can override)

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}


JAZZMIN_SETTINGS = {
    # Branding
    "site_title": "Pentecost Attendance Admin",
    "site_header": "Pentecost Attendance",
    "site_brand": "Pentecost Attendance",
    "welcome_sign": "Welcome to the Pentecost Attendance admin",
    "copyright": "",  # TODO: fill in before launch, e.g. "Church of Pentecost, Ayigya District"

    "search_model": ["accounts.Member"],

    # ── Top menu ─────────────────────────────────────────────────────────────
    "topmenu_links": [
        {"name": "Home", "url": "admin:index", "permissions": ["auth.view_user"]},
        {"name": "Site", "url": "/", "new_window": True},
        {"name": "Django Docs", "url": "https://docs.djangoproject.com/en/stable/", "new_window": True},
    ],

    "order_with_respect_to": [
        "accounts",
        "attendance",
        "content",
        "milestones",
    ],

    "icons": {
        "auth": "fas fa-shield-alt",
        "auth.Group": "fas fa-users-cog",
        # accounts
        "accounts": "fas fa-users",
        "accounts.User": "fas fa-id-badge",
        "accounts.Member": "fas fa-user",
        "accounts.Elder": "fas fa-user-tie",
        "accounts.ElderOfficeHours": "fas fa-clock",
        "accounts.Assembly": "fas fa-church",
        "accounts.DayBornGroup": "fas fa-calendar-day",
        "accounts.OTPVerification": "fas fa-key",
        "accounts.ImportBatch": "fas fa-file-csv",
        # attendance
        "attendance": "fas fa-clipboard-list",
        "attendance.AttendanceSession": "fas fa-door-open",
        "attendance.AttendanceRecord": "fas fa-clipboard-check",
        "attendance.MemberAttendanceStat": "fas fa-chart-line",
        # content
        "content": "fas fa-newspaper",
        "content.WeeklySchedule": "fas fa-calendar-alt",
        # fa-book-bible is FA6/FA-Pro only; in FA5 Free the equivalent is fas fa-bible
        "content.BibleStudyWeek": "fas fa-bible",
        "content.Event": "fas fa-calendar-check",
        "content.Notification": "fas fa-bell",
        "content.NotificationRead": "fas fa-envelope-open",
        # milestones
        "milestones": "fas fa-award",
        "milestones.SpiritualMilestone": "fas fa-water",
    },
    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",

    # ── UI options ────────────────────────────────────────────────────────────
    #"show_ui_builder": True,   # dev convenience; set False before production launch
    "related_modal_active": True,
    "navigation_expanded": True,
    "hide_apps": [],
    "hide_models": [],
}

JAZZMIN_UI_TWEAKS = {
    # Bootswatch "flatly" — clean, professional, readable at a glance.
    # Other options: litera, lux, cosmo, simplex, united.
    # Change via the UI Builder button in the admin (only visible when show_ui_builder=True).
    "theme": "flatly",
    "default_theme_mode": "auto",
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": "navbar-primary",
    "accent": "accent-primary",
    "navbar": "navbar-white navbar-light",
    "no_navbar_border": False,
    "sidebar": "sidebar-dark-primary",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": False,
    "sidebar_nav_compact_style": False,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": False,
    "button_classes": {
        "primary": "btn-primary",
        "secondary": "btn-secondary",
        "info": "btn-outline-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success",
    },
}


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

# ── Push notifications (core/push.py) ─────────────────────────────────────────
# Sent through Expo's push service. Set EXPO_PUSH_ENABLED=0 to silence them
# (tests, a staging copy of production data). EXPO_ACCESS_TOKEN is only needed
# if "enhanced push security" is switched on for the project in Expo.
EXPO_PUSH_ENABLED = config("EXPO_PUSH_ENABLED", default=True, cast=bool)
EXPO_ACCESS_TOKEN = config("EXPO_ACCESS_TOKEN", default="")
