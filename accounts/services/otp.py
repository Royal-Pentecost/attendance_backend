"""
accounts/services/otp.py

Swappable OTP delivery service. To add a new SMS provider: subclass OTPBackend,
register it in _BACKENDS, and set OTP_BACKEND in settings. No view or serializer
code changes required.
"""
import logging
import random
import string

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password

logger = logging.getLogger(__name__)


def generate_otp_code(length: int = 4) -> str:
    """Return a zero-padded numeric string of the given length."""
    return "".join(random.choices(string.digits, k=length))


def hash_otp_code(code: str) -> str:
    return make_password(code)


def verify_otp_code(code: str, code_hash: str) -> bool:
    return check_password(code, code_hash)


class OTPBackend:
    def send(self, phone_number: str, code: str) -> str:
        """Send the code; return a provider reference string (or '' if none)."""
        raise NotImplementedError


class ConsoleOTPBackend(OTPBackend):

    def send(self, phone_number: str, code: str) -> str:
        logger.info("[OTP] code for %s → %s", phone_number, code)
        return ""


class MoolreOTPBackend(OTPBackend):

    def __init__(self):
        self.api_key = getattr(settings, "MOOLRE_API_KEY", "")
        self.sender_id = getattr(settings, "MOOLRE_SENDER_ID", "")

    def send(self, phone_number: str, code: str) -> str:
        raise NotImplementedError("Moolre integration pending API keys")


_BACKENDS = {
    "console": ConsoleOTPBackend,
    "moolre": MoolreOTPBackend,
}


def get_otp_backend() -> OTPBackend:
    backend_name = getattr(settings, "OTP_BACKEND", "console")
    backend_class = _BACKENDS.get(backend_name)
    if backend_class is None:
        raise ValueError(
            f"Unknown OTP_BACKEND: {backend_name!r}. Valid choices: {list(_BACKENDS)}"
        )
    return backend_class()
