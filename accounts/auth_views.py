"""
accounts/auth_views.py

Unauthenticated auth endpoints for the OTP login flow.
Kept separate from accounts/views.py (CRUD viewsets) because these endpoints
are AllowAny by design — the user doesn't have a token yet.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.authtoken.models import Token

from core.authentication import end_sessions, is_expired
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.auth_serializers import RequestOTPSerializer, VerifyOTPSerializer
from accounts.models import OTPVerification, User
from accounts.serializers import MemberSerializer
from accounts.services.otp import (
    generate_otp_code,
    get_otp_backend,
    hash_otp_code,
    verify_otp_code,
)


@extend_schema(
    tags=["Auth"],
    summary="Request login OTP",
    description=(
        "Request a one-time password (OTP) delivered via SMS to the given phone number. "
        "The number must belong to an existing member account — self-registration is not "
        "supported via this endpoint.\n\n"
        "Any previously pending (unused, unexpired) OTP for this phone+purpose is marked "
        "used before the new one is issued, so only one valid code can exist at a time.\n\n"
        "**Dev convenience (`debug_code`):** when the server runs with `DEBUG=True` AND "
        "`OTP_BACKEND=console`, the response also contains `debug_code` with the plaintext "
        "OTP so you don't have to read server logs. This field is **physically impossible** "
        "to appear in production: `prod.py` hardcodes `DEBUG=False` and `OTP_BACKEND=moolre`."
    ),
    request=RequestOTPSerializer,
    responses={
        200: OpenApiResponse(description="OTP sent successfully."),
        400: OpenApiResponse(description="Invalid phone number format."),
        404: OpenApiResponse(description="No account found for this phone number."),
    },
)
class RequestOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RequestOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone_number = serializer.validated_data["phone_number"]

        # Reject unknown numbers at request time (assumption: LOGIN only; no self-registration).
        try:
            User.objects.get(phone_number=phone_number)
        except User.DoesNotExist:
            return Response(
                {"detail": "No account found for this phone number."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Invalidate any still-valid OTP for this phone+purpose before issuing a new one.
        # Using is_used=True rather than deletion preserves the audit trail in OTPVerification.
        OTPVerification.objects.filter(
            phone_number=phone_number,
            purpose=OTPVerification.PURPOSE_LOGIN,
            is_used=False,
            expires_at__gt=timezone.now(),
        ).update(is_used=True)

        code = generate_otp_code(settings.OTP_LENGTH)
        otp = OTPVerification.objects.create(
            phone_number=phone_number,
            code_hash=hash_otp_code(code),
            purpose=OTPVerification.PURPOSE_LOGIN,
            expires_at=timezone.now() + timedelta(seconds=settings.OTP_EXPIRY_SECONDS),
        )

        reference = get_otp_backend().send(phone_number, code)
        if reference:
            otp.moolre_reference = reference
            otp.save(update_fields=["moolre_reference"])

        response_data = {
            "detail": "OTP sent",
            "expires_in": settings.OTP_EXPIRY_SECONDS,
        }

        # ⚠️  SECURITY: debug_code is added ONLY when BOTH are true:
        #     1. settings.DEBUG is True   → never True in prod (prod.py hardcodes False)
        #     2. OTP_BACKEND == "console" → never "console" in prod (prod.py hardcodes "moolre")
        # This double-guard makes it physically impossible for plaintext codes to leak in prod.
        if settings.DEBUG and getattr(settings, "OTP_BACKEND", "") == "console":
            response_data["debug_code"] = code

        return Response(response_data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Auth"],
    summary="Verify OTP and obtain auth token",
    description=(
        "Submit the OTP received via SMS alongside the phone number. "
        "On success, returns a DRF auth token and the member profile.\n\n"
        "Use the token for all subsequent requests: `Authorization: Token <token>`.\n\n"
        "The OTP is single-use — resubmitting the correct code after a successful verify "
        "is rejected. After too many failed attempts the code is locked."
    ),
    request=VerifyOTPSerializer,
    responses={
        200: OpenApiResponse(description="Login successful — token and member profile returned."),
        400: OpenApiResponse(
            description="Invalid, expired, or already-used OTP; wrong code; or too many attempts."
        ),
    },
)
class VerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone_number = serializer.validated_data["phone_number"]
        code = serializer.validated_data["code"]

        # Fetch the most recent unused, unexpired OTP for this phone+purpose.
        otp = (
            OTPVerification.objects.filter(
                phone_number=phone_number,
                purpose=OTPVerification.PURPOSE_LOGIN,
                is_used=False,
                expires_at__gt=timezone.now(),
            )
            .order_by("-created_at")
            .first()
        )

        if otp is None:
            return Response(
                {"detail": "No valid OTP found. Please request a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if otp.attempt_count >= settings.OTP_MAX_ATTEMPTS:
            return Response(
                {"detail": "Too many failed attempts. Please request a new OTP."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not verify_otp_code(code, otp.code_hash):
            otp.attempt_count += 1
            otp.save(update_fields=["attempt_count"])
            # No "X attempts remaining" in the response — avoid aiding brute-force.
            return Response(
                {"detail": "Incorrect code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Mark used immediately to prevent replay attacks.
        otp.is_used = True
        otp.save(update_fields=["is_used"])

        try:
            user = User.objects.get(phone_number=phone_number)
        except User.DoesNotExist:
            # Shouldn't happen (request-otp already validated existence), but be explicit.
            return Response(
                {"detail": "No account found for this phone number."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # An expired token is replaced, not handed back: re-using it would
        # sign the member in with a session the server is about to refuse.
        existing = Token.objects.filter(user=user).first()
        if existing and is_expired(existing):
            existing.delete()
        token, _ = Token.objects.get_or_create(user=user)

        try:
            member = user.member_profile
            member_data = MemberSerializer(member, context={"request": request}).data
        except Exception:
            member_data = None

        return Response(
            {"token": token.key, "member": member_data},
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    """
    Ends the sign-in on the server, not just on the phone.

    Signing out used to forget the token locally while the server went on
    accepting it for ever. Now the token is deleted, so it is dead everywhere
    it was copied — and the phone's push registration goes with it.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Auth"], summary="Sign out", request=None, responses={204: None})
    def post(self, request):
        end_sessions(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
