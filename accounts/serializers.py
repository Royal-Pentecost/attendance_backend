"""
accounts/serializers.py

Serializer write pattern used throughout this project:
  - FK reads:  a nested read-only mini-serializer (e.g. assembly = AssemblyMiniSerializer(read_only=True))
  - FK writes: a PrimaryKeyRelatedField with an `_id` suffix
                 (e.g. assembly_id = PrimaryKeyRelatedField(source='assembly', ...))
This keeps field names stable for consumers while allowing natural PK input for writes.
"""
from rest_framework import serializers

from .models import Assembly, DayBornGroup, Member, Elder, ElderOfficeHours, ImportBatch


# ---------------------------------------------------------------------------
# Mini / nested display serializers (read-only, used inside other serializers)
# ---------------------------------------------------------------------------

class AssemblyMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assembly
        fields = ["id", "name", "slug"]


class DayBornGroupMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = DayBornGroup
        fields = ["id", "name", "weekday"]


class MemberMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Member
        fields = ["id", "full_name", "member_id"]


class ElderMiniSerializer(serializers.ModelSerializer):
    member = MemberMiniSerializer(read_only=True)

    class Meta:
        model = Elder
        fields = ["id", "office", "title", "member"]


# ---------------------------------------------------------------------------
# Full serializers
# ---------------------------------------------------------------------------

class AssemblySerializer(serializers.ModelSerializer):
    presiding_elder = ElderMiniSerializer(read_only=True)
    presiding_elder_id = serializers.PrimaryKeyRelatedField(
        source="presiding_elder",
        queryset=Elder.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )

    class Meta:
        model = Assembly
        fields = [
            "id", "name", "slug", "district", "founded_year", "is_active",
            "banner_image",
            "geofence_center_lat", "geofence_center_lng", "geofence_radius_meters",
            "presiding_elder", "presiding_elder_id",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class DayBornGroupSerializer(serializers.ModelSerializer):
    assembly = AssemblyMiniSerializer(read_only=True)
    assembly_id = serializers.PrimaryKeyRelatedField(
        source="assembly",
        queryset=Assembly.objects.all(),
        write_only=True,
    )
    leader = MemberMiniSerializer(read_only=True)
    leader_id = serializers.PrimaryKeyRelatedField(
        source="leader",
        queryset=Member.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )

    class Meta:
        model = DayBornGroup
        fields = [
            "id", "name", "weekday", "assembly", "assembly_id",
            "meeting_time", "meeting_location", "leader", "leader_id",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class MemberSerializer(serializers.ModelSerializer):
    """
    General-purpose read / limited-update serializer for Member.
    `role` and `user` are intentionally read-only here — role changes must go
    through the Django admin or a future dedicated endpoint; this prevents
    members from escalating their own roles via a self-update PATCH.
    Use MemberCreateSerializer for admin member creation.
    """
    assembly = AssemblyMiniSerializer(read_only=True)
    assembly_id = serializers.PrimaryKeyRelatedField(
        source="assembly",
        queryset=Assembly.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )
    day_born_group = DayBornGroupMiniSerializer(read_only=True)
    day_born_group_id = serializers.PrimaryKeyRelatedField(
        source="day_born_group",
        queryset=DayBornGroup.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )
    assigned_elder = ElderMiniSerializer(read_only=True)
    assigned_elder_id = serializers.PrimaryKeyRelatedField(
        source="assigned_elder",
        queryset=Elder.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )

    class Meta:
        model = Member
        fields = [
            "id", "member_id", "full_name", "date_of_birth", "profile_photo",
            "role",
            "assembly", "assembly_id",
            "day_born_group", "day_born_group_id",
            "assigned_elder", "assigned_elder_id",
            "is_profile_complete", "bible_study_language", "dark_mode_enabled",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "member_id", "role", "created_at", "updated_at"]


class MemberCreateSerializer(serializers.ModelSerializer):
    """
    Admin-only member creation serializer.
    `user` and `role` are writable here, unlike MemberSerializer.
    `member_id` should be set explicitly — it is NOT auto-generated by the model.
    """
    assembly = AssemblyMiniSerializer(read_only=True)
    assembly_id = serializers.PrimaryKeyRelatedField(
        source="assembly",
        queryset=Assembly.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )
    day_born_group_id = serializers.PrimaryKeyRelatedField(
        source="day_born_group",
        queryset=DayBornGroup.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )
    assigned_elder_id = serializers.PrimaryKeyRelatedField(
        source="assigned_elder",
        queryset=Elder.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )

    class Meta:
        model = Member
        fields = [
            "id", "user", "member_id", "full_name", "date_of_birth", "profile_photo",
            "role",
            "assembly", "assembly_id",
            "day_born_group_id", "assigned_elder_id",
            "is_profile_complete", "bible_study_language", "dark_mode_enabled",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ElderSerializer(serializers.ModelSerializer):
    member = MemberMiniSerializer(read_only=True)
    member_id = serializers.PrimaryKeyRelatedField(
        source="member",
        queryset=Member.objects.all(),
        write_only=True,
    )

    class Meta:
        model = Elder
        fields = [
            "id", "member", "member_id", "office", "title",
            "contact_phone", "contact_email", "whatsapp_number",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ElderOfficeHoursSerializer(serializers.ModelSerializer):
    elder = ElderMiniSerializer(read_only=True)
    elder_id = serializers.PrimaryKeyRelatedField(
        source="elder",
        queryset=Elder.objects.all(),
        write_only=True,
    )

    class Meta:
        model = ElderOfficeHours
        fields = [
            "id", "elder", "elder_id", "weekday", "start_time", "end_time",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ImportBatchSerializer(serializers.ModelSerializer):
    uploaded_by = MemberMiniSerializer(read_only=True)
    assembly = AssemblyMiniSerializer(read_only=True)
    assembly_id = serializers.PrimaryKeyRelatedField(
        source="assembly",
        queryset=Assembly.objects.all(),
        write_only=True,
    )

    class Meta:
        model = ImportBatch
        fields = [
            "id", "uploaded_by", "assembly", "assembly_id", "source_file",
            "status", "row_count", "success_count", "error_count", "error_log",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "uploaded_by", "status", "row_count",
            "success_count", "error_count", "error_log",
            "created_at", "updated_at",
        ]
