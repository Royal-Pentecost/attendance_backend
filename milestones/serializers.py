"""milestones/serializers.py"""
from rest_framework import serializers

from accounts.models import Member
from accounts.serializers import MemberMiniSerializer
from .models import SpiritualMilestone


class SpiritualMilestoneSerializer(serializers.ModelSerializer):
    member = MemberMiniSerializer(read_only=True)
    member_id = serializers.PrimaryKeyRelatedField(
        source="member",
        queryset=Member.objects.all(),
        write_only=True,
    )
    verified_by = MemberMiniSerializer(read_only=True)

    class Meta:
        model = SpiritualMilestone
        fields = [
            "id", "member", "member_id", "milestone_type", "date_occurred",
            "certificate_file", "notes", "verified_by",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "verified_by", "created_at", "updated_at"]
