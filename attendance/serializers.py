"""attendance/serializers.py"""
from rest_framework import serializers

from accounts.models import Assembly, Member
from accounts.serializers import AssemblyMiniSerializer, MemberMiniSerializer
from .models import AttendanceSession, AttendanceRecord, MemberAttendanceStat


class AttendanceSessionSerializer(serializers.ModelSerializer):
    assembly = AssemblyMiniSerializer(read_only=True)
    assembly_id = serializers.PrimaryKeyRelatedField(
        source="assembly",
        queryset=Assembly.objects.all(),
        write_only=True,
    )
    opened_by = MemberMiniSerializer(read_only=True)

    class Meta:
        model = AttendanceSession
        fields = [
            "id", "assembly", "assembly_id", "service_name",
            "opened_by", "opened_at", "closed_at", "is_active",
            # Snapshotted geofence — read-only; set server-side from Assembly at open-time
            "geofence_center_lat", "geofence_center_lng", "geofence_radius_meters",
            "created_at", "updated_at",
        ]
        # The geofence is writable on create so an admin's device can anchor the
        # session where the service is actually being held. The view still has
        # the last word: it falls back to the assembly's own fence when no
        # coordinates are sent, and only admins may open a session at all.
        read_only_fields = [
            "id", "opened_by", "opened_at",
            "created_at", "updated_at",
        ]
        # Optional on the way in. The model columns are NOT NULL, so DRF made
        # all three required — and the view's fallback to the assembly's own
        # fence could never run, because a request without coordinates was
        # rejected before reaching it. An admin whose phone had no usable GPS
        # fix therefore could not open a session at all.
        extra_kwargs = {
            "geofence_center_lat": {"required": False},
            "geofence_center_lng": {"required": False},
            "geofence_radius_meters": {"required": False},
        }


class AttendanceRecordSerializer(serializers.ModelSerializer):
    session_id = serializers.PrimaryKeyRelatedField(
        source="session",
        queryset=AttendanceSession.objects.all(),
        write_only=True,
    )
    session = serializers.PrimaryKeyRelatedField(read_only=True)
    member = MemberMiniSerializer(read_only=True)
    member_id = serializers.PrimaryKeyRelatedField(
        source="member",
        queryset=Member.objects.all(),
        write_only=True,
        required=False,
        help_text="Required for manual entries. Ignored for GPS check-ins (always set to requester).",
    )
    recorded_by = MemberMiniSerializer(read_only=True)

    # GPS coordinates — write-only input fields; not stored directly.
    # The view computes distance_from_center_meters from these and discards them.
    lat = serializers.DecimalField(
        max_digits=9, decimal_places=6, write_only=True, required=False,
    )
    lng = serializers.DecimalField(
        max_digits=9, decimal_places=6, write_only=True, required=False,
    )

    class Meta:
        model = AttendanceRecord
        fields = [
            "id", "session", "session_id", "member", "member_id",
            "method", "marked_at",
            "distance_from_center_meters",  # read-only; computed server-side
            "is_first_timer", "recorded_by",  # recorded_by read-only; set server-side
            "note",
            "lat", "lng",  # write-only GPS input
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "marked_at", "distance_from_center_meters", "recorded_by",
            "created_at", "updated_at",
        ]
        # DRF derives a UniqueTogetherValidator from the model's
        # ("session", "member") constraint, and that validator makes every field
        # it covers *required* — so `member_id` became mandatory and every GPS
        # check-in, which never sends it, was rejected. The member on a GPS mark
        # is the requester and is only known in the view, so the one-mark-per-
        # session rule is enforced there instead, where it can say so plainly.
        validators = []

    def validate(self, data):
        # Only validate GPS coords on creation (updates don't re-supply them)
        if self.instance is None:
            method = data.get("method", AttendanceRecord.METHOD_GPS)
            if method == AttendanceRecord.METHOD_GPS:
                lat = data.get("lat")
                lng = data.get("lng")
                if lat is None or lng is None:
                    raise serializers.ValidationError(
                        {"lat/lng": "lat and lng are required for GPS check-ins."}
                    )
        return data


class MemberAttendanceStatSerializer(serializers.ModelSerializer):
    """Read-only. This model is maintained by signals, never written via the API."""
    member = MemberMiniSerializer(read_only=True)
    assembly = AssemblyMiniSerializer(read_only=True)

    class Meta:
        model = MemberAttendanceStat
        fields = [
            "id", "member", "assembly", "year",
            "sessions_attended", "sessions_possible", "annual_score_percent",
            "current_streak_weeks", "longest_streak_weeks", "last_attended_session",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "member", "assembly", "year",
            "sessions_attended", "sessions_possible", "annual_score_percent",
            "current_streak_weeks", "longest_streak_weeks", "last_attended_session",
            "created_at", "updated_at",
        ]
