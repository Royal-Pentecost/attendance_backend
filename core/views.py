from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
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
