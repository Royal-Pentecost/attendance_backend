"""
config/urls.py
"""
from django.contrib import admin
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
