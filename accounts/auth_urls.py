from django.urls import path

from accounts.auth_views import LogoutView, RequestOTPView, VerifyOTPView

urlpatterns = [
    path("request-otp/", RequestOTPView.as_view(), name="auth-request-otp"),
    path("verify-otp/", VerifyOTPView.as_view(), name="auth-verify-otp"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
]
