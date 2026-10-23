from rest_framework import serializers

from core.models import ActivityLog


class ActivityLogSerializer(serializers.ModelSerializer):
    """Read-only by design — the trail is written by the server, never posted to."""

    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "actor",
            "actor_name",
            "action",
            "affected_record",
            "severity",
            "assembly",
            "created_at",
        ]
        read_only_fields = fields
