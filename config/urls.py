"""
config/urls.py
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

urlpatterns = [
    path("admin/", admin.site.urls),

    # DRF browsable-API login/logout (for testing in browser while logged into /admin/)
    path("api-auth/", include("rest_framework.urls")),

    # OTP-based auth flow (request-otp / verify-otp)
    path("api/v1/auth/", include("accounts.auth_urls")),

    # App API routes (versioned)
    path("api/v1/accounts/", include("accounts.urls")),
    path("api/v1/attendance/", include("attendance.urls")),
    path("api/v1/content/", include("content.urls")),
    path("api/v1/milestones/", include("milestones.urls")),

    # OpenAPI schema + documentation UIs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

# Uploaded files — profile photographs, study PDFs, publication covers.
#
# Django's development server does not serve MEDIA_ROOT unless told to, so
# without this every `profile_photo` URL the API returns is a 404: the file
# uploads fine and then cannot be fetched, which looks like a broken app rather
# than a missing route. In production the web server or object store serves
# these, which is why it is guarded by DEBUG.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
