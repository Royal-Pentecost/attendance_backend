from .base import *  # noqa: F401, F403

DEBUG = True

# The phone running Expo Go reaches this machine over the LAN, and a laptop's
# address changes every time it rejoins a network — so pinning a list here just
# means the server starts rejecting the phone after a reconnect. Development
# only; prod.py keeps its own strict list.
ALLOWED_HOSTS = ["*"]

# No SMS in development: request-otp returns the code in the response instead.
OTP_BACKEND = "console"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Let the browser-based preview call this server.
#
# A phone does not enforce CORS, so Expo Go needs none of this — but the web
# preview is a real browser on a different port and would be blocked. Rather than
# add a dependency that cannot be installed offline, development allows any
# origin through a few lines of middleware. This file is never used in
# production, where prod.py applies.
MIDDLEWARE = ["config.settings.dev.AllowAnyOriginMiddleware"] + MIDDLEWARE  # noqa: F405


class AllowAnyOriginMiddleware:
    """Reflects the caller's origin and answers preflight requests. Dev only."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "OPTIONS":
            from django.http import HttpResponse

            response = HttpResponse(status=200)
        else:
            response = self.get_response(request)

        origin = request.headers.get("Origin")
        if origin:
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Credentials"] = "true"
            response["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Accept"
            response["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            response["Access-Control-Max-Age"] = "86400"
        return response
