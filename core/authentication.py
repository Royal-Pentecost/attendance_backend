"""
Sign-ins that end.

DRF's tokens never expire on their own, so the app's "28 days" was only a
promise the phone made to itself: a copied token kept working for ever. This
enforces it on the server — a token older than SESSION_DAYS is deleted the next
time it is used and the request is refused, which sends the app back to login.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


def session_days() -> int:
    return getattr(settings, "SESSION_DAYS", 28)


def is_expired(token) -> bool:
    return token.created < timezone.now() - timedelta(days=session_days())


class ExpiringTokenAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if is_expired(token):
            token.delete()
            raise AuthenticationFailed("Your sign-in has expired. Please sign in again.")
        return user, token


def end_sessions(user) -> None:
    """
    Signs a login out everywhere: its token, and the phones registered for
    pushes under it — a phone that can no longer sign in should not keep
    receiving the assembly's notifications.
    """
    from rest_framework.authtoken.models import Token
    from core.models import PushDevice

    if user is None:
        return
    Token.objects.filter(user=user).delete()
    member = getattr(user, "member_profile", None)
    if member is not None:
        PushDevice.objects.filter(member=member).delete()
