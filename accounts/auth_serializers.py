"""
accounts/auth_serializers.py

Input serializers for the unauthenticated OTP login endpoints.
Kept separate from accounts/serializers.py because these are auth-flow specific
(no model CRUD, no token required to submit them).
"""
from rest_framework import serializers


class RequestOTPSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)

    def validate_phone_number(self, value):
        value = value.strip()
        # Strip leading + for digit check; allow 7–15 digits (ITU-T E.164 range).
        digits_only = value.lstrip("+")
        if not digits_only.isdigit() or not (7 <= len(digits_only) <= 15):
            raise serializers.ValidationError(
                "Enter a valid phone number (7–15 digits, optional leading +)."
            )
        return value


class VerifyOTPSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)
    code = serializers.CharField(min_length=4, max_length=8)

    def validate_phone_number(self, value):
        return value.strip()

    def validate_code(self, value):
        value = value.strip()
        if not value.isdigit():
            raise serializers.ValidationError("OTP code must be numeric.")
        return value
