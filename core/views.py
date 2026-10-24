from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from accounts.permissions import IsSuperAdmin
from core.models import ActivityLog
from core.serializers import ActivityLogSerializer


@extend_schema_view(
    list=extend_schema(
        summary="Administrative activity trail",
        description=(
            "Everything consequential that an administrator did, newest first. "
            "Super admins only, and read-only: entries are written by the server "
            "as actions happen, so there is no way to post, edit or delete one."
        ),
    ),
)
class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    The audit trail.

    Read-only on purpose. A log the client can write to proves nothing, and a
    log it can delete from proves less — so the only path in is `record_activity`
    on the server side.
    """

    serializer_class = ActivityLogSerializer
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    queryset = ActivityLog.objects.select_related("actor", "assembly").all()

    def get_queryset(self):
        qs = super().get_queryset()
        severity = self.request.query_params.get("severity")
        if severity:
            qs = qs.filter(severity=severity)
        return qs


class PushDeviceViewSet(viewsets.ViewSet):
    """
    Where a phone tells the server it can be woken.

    POST {token, platform} after sign-in claims the token for the signed-in
    member — a phone handed to someone else follows its new owner. POST
    remove/ {token} on sign-out stops the pushes to that phone.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Register this phone for push notifications")
    def create(self, request):
        from rest_framework import status
        from rest_framework.response import Response
        from core.models import PushDevice

        member = getattr(request.user, "member_profile", None)
        token = (request.data.get("token") or "").strip()
        platform = (request.data.get("platform") or "").strip().lower()
        if member is None:
            return Response({"detail": "No member profile for this login."}, status=status.HTTP_400_BAD_REQUEST)
        # Expo's tokens look like ExponentPushToken[...]; refuse anything else
        # rather than store a value no send can ever reach.
        if not (token.startswith("ExponentPushToken[") or token.startswith("ExpoPushToken[")) or len(token) > 200:
            return Response({"token": ["Not an Expo push token."]}, status=status.HTTP_400_BAD_REQUEST)
        if platform not in ("android", "ios"):
            platform = ""
        device, created = PushDevice.objects.update_or_create(
            token=token, defaults={"member": member, "platform": platform},
        )
        return Response({"id": str(device.id), "registered": True},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @extend_schema(summary="Stop push notifications to this phone")
    @action(detail=False, methods=["post"])
    def remove(self, request):
        from rest_framework.response import Response
        from core.models import PushDevice

        member = getattr(request.user, "member_profile", None)
        token = (request.data.get("token") or "").strip()
        n = PushDevice.objects.filter(token=token, member=member).delete()[0] if member else 0
        return Response({"removed": n})
