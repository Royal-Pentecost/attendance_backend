"""content/serializers.py"""
from rest_framework import serializers

from accounts.models import Assembly, DayBornGroup, Member
from accounts.serializers import AssemblyMiniSerializer, DayBornGroupMiniSerializer, MemberMiniSerializer
from .models import WeeklySchedule, BibleStudyWeek, BibleStudyTranslation, Event, Notification, NotificationRead


class WeeklyScheduleSerializer(serializers.ModelSerializer):
    assembly = AssemblyMiniSerializer(read_only=True)
    assembly_id = serializers.PrimaryKeyRelatedField(
        source="assembly",
        queryset=Assembly.objects.all(),
        write_only=True,
    )

    class Meta:
        model = WeeklySchedule
        fields = [
            "id", "assembly", "assembly_id", "name",
            "start_weekday", "end_weekday", "time", "location",
            "banner_image", "is_active",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class BibleStudyTranslationSerializer(serializers.ModelSerializer):
    """One week's study in one language. Every field optional but `language`."""

    class Meta:
        model = BibleStudyTranslation
        fields = ["id", "week", "language", "title", "aims", "questions", "memory_verse", "notes"]
        read_only_fields = ["id"]


class BibleStudyWeekSerializer(serializers.ModelSerializer):
    assembly = AssemblyMiniSerializer(read_only=True)
    assembly_id = serializers.PrimaryKeyRelatedField(
        source="assembly",
        queryset=Assembly.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
        help_text="Omit for district-wide content.",
    )
    # Nested so one request gives the reader everything it needs. A week with no
    # translations is still perfectly valid — it just shows its title, scripture
    # and page range, which is what the printed pamphlet gives you anyway.
    translations = BibleStudyTranslationSerializer(many=True, read_only=True)

    class Meta:
        model = BibleStudyWeek
        fields = [
            "id", "assembly", "assembly_id", "theme", "week_number", "title",
            "scripture_reference", "page_range", "study_date",
            "pdf_file", "is_published", "translations",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class EventSerializer(serializers.ModelSerializer):
    assembly = AssemblyMiniSerializer(read_only=True)
    assembly_id = serializers.PrimaryKeyRelatedField(
        source="assembly",
        queryset=Assembly.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
        help_text="Required when scope is 'assembly'.",
    )
    created_by = MemberMiniSerializer(read_only=True)

    class Meta:
        model = Event
        fields = [
            "id", "title", "description", "event_date", "scope",
            "assembly", "assembly_id", "created_by",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def validate(self, data):
        scope = data.get("scope", Event.SCOPE_ASSEMBLY)
        assembly = data.get("assembly")
        if scope == Event.SCOPE_ASSEMBLY and not assembly:
            raise serializers.ValidationError(
                {"assembly": "assembly is required when scope is 'assembly'."}
            )
        if scope == Event.SCOPE_DISTRICT and assembly:
            raise serializers.ValidationError(
                {"assembly": "assembly must be null for district-scoped events."}
            )
        return data


class NotificationSerializer(serializers.ModelSerializer):
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
    member = MemberMiniSerializer(read_only=True)
    member_id = serializers.PrimaryKeyRelatedField(
        source="member",
        queryset=Member.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )

    class Meta:
        model = Notification
        fields = [
            "id", "title", "body", "notification_type", "audience_type",
            "assembly", "assembly_id",
            "day_born_group", "day_born_group_id",
            "member", "member_id",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, data):
        audience_type = data.get("audience_type")
        assembly = data.get("assembly")
        day_born_group = data.get("day_born_group")
        member = data.get("member")

        if audience_type == Notification.AUDIENCE_ALL:
            if assembly or day_born_group or member:
                raise serializers.ValidationError(
                    "audience_type 'all' must have assembly, day_born_group, and member all null."
                )
        elif audience_type == Notification.AUDIENCE_ASSEMBLY:
            if not assembly:
                raise serializers.ValidationError(
                    {"assembly": "assembly is required when audience_type is 'assembly'."}
                )
            if day_born_group or member:
                raise serializers.ValidationError(
                    "day_born_group and member must be null when audience_type is 'assembly'."
                )
        elif audience_type == Notification.AUDIENCE_DAY_BORN_GROUP:
            if not day_born_group:
                raise serializers.ValidationError(
                    {"day_born_group": "day_born_group is required when audience_type is 'day_born_group'."}
                )
            if assembly or member:
                raise serializers.ValidationError(
                    "assembly and member must be null when audience_type is 'day_born_group'."
                )
        elif audience_type == Notification.AUDIENCE_MEMBER:
            if not member:
                raise serializers.ValidationError(
                    {"member": "member is required when audience_type is 'member'."}
                )
            if assembly or day_born_group:
                raise serializers.ValidationError(
                    "assembly and day_born_group must be null when audience_type is 'member'."
                )
        return data


class NotificationReadSerializer(serializers.ModelSerializer):
    notification_id = serializers.PrimaryKeyRelatedField(
        source="notification",
        queryset=Notification.objects.all(),
        write_only=True,
    )
    notification = serializers.PrimaryKeyRelatedField(read_only=True)
    member = MemberMiniSerializer(read_only=True)

    class Meta:
        model = NotificationRead
        fields = [
            "id", "notification", "notification_id", "member", "read_at",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "member", "read_at", "created_at", "updated_at"]
