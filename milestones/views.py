"""
milestones/views.py

Assumptions flagged:
- Read access for SpiritualMilestone is scoped to: the member themselves,
  their assigned elder, and assembly admins. Plain members cannot see other
  members' milestones.
- `verified_by` is always set server-side to the requesting user's profile.
- For create, elders are validated in perform_create (not just at object level)
  because there's no object yet to check against.
"""
from django.db import models as django_models

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from accounts.models import Member
from accounts.permissions import IsAssignedElderOrAdmin
from milestones.models import SpiritualMilestone
from milestones.serializers import SpiritualMilestoneSerializer


class AssemblyScopedMixin:
    def get_requesting_profile(self):
        try:
            return self.request.user.member_profile
        except Member.DoesNotExist:
            return None


@extend_schema_view(
    list=extend_schema(
        tags=["Milestones"],
        description=(
            "List spiritual milestones visible to the requesting user:\n"
            "- **Member**: their own milestones only.\n"
            "- **Elder**: own milestones + milestones for all members assigned to them.\n"
            "- **Assembly admin**: all milestones for members in their assembly.\n"
            "- **Super admin**: all milestones system-wide."
        ),
    ),
    create=extend_schema(
        tags=["Milestones"],
        description=(
            "Record a new spiritual milestone (baptism, confirmation, etc.).\n\n"
            "**Access rules:**\n"
            "- `super_admin`: can record for any member.\n"
            "- `assembly_admin`: can record for any member within their assembly.\n"
            "- **Elder**: can record only for members where `member.assigned_elder == self`. "
            "  Returns 403 if the target member is not assigned to the requesting elder.\n\n"
            "`verified_by` is always set server-side to the requesting user — "
            "it cannot be supplied by the client."
        ),
    ),
    retrieve=extend_schema(tags=["Milestones"]),
    update=extend_schema(
        tags=["Milestones"],
        description=(
            "Update a milestone. Same access rules as create: "
            "admin (scoped to their assembly) or the assigned elder for this member."
        ),
    ),
    partial_update=extend_schema(
        tags=["Milestones"],
        description=(
            "Partially update a milestone. Same access rules as update."
        ),
    ),
    destroy=extend_schema(
        tags=["Milestones"],
        description="Delete a milestone. Same access rules as update.",
    ),
)
class SpiritualMilestoneViewSet(AssemblyScopedMixin, viewsets.ModelViewSet):
    """
    Read: member sees own milestones; elder sees assigned members' milestones;
          assembly_admin sees all milestones in their assembly.
    Write: IsAssignedElderOrAdmin — admin or the member's assigned elder.
    `verified_by` is set server-side to the requesting user's member profile.
    """
    serializer_class = SpiritualMilestoneSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SpiritualMilestone.objects.none()
        profile = self.get_requesting_profile()
        if profile is None:
            return SpiritualMilestone.objects.all() if self.request.user.is_superuser else SpiritualMilestone.objects.none()
        if profile.role == Member.ROLE_SUPER_ADMIN:
            return SpiritualMilestone.objects.all()
        if profile.role == Member.ROLE_ASSEMBLY_ADMIN:
            return SpiritualMilestone.objects.filter(member__assembly=profile.assembly)
        # Regular member: own milestones + milestones of members assigned to this elder (if any)
        own_qs = SpiritualMilestone.objects.filter(member=profile)
        if hasattr(profile, "elder_profile"):
            elder_qs = SpiritualMilestone.objects.filter(member__assigned_elder=profile.elder_profile)
            return (own_qs | elder_qs).distinct()
        return own_qs

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsAssignedElderOrAdmin()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        profile = self.get_requesting_profile()
        target_member = serializer.validated_data.get("member")

        if profile.role == Member.ROLE_SUPER_ADMIN:
            serializer.save(verified_by=profile)
            return

        if profile.role == Member.ROLE_ASSEMBLY_ADMIN:
            if target_member.assembly != profile.assembly:
                raise PermissionDenied("Cannot create a milestone for a member outside your assembly.")
            serializer.save(verified_by=profile)
            return

        # Elder — validate assignment
        assigned_elder = target_member.assigned_elder
        if assigned_elder is None or assigned_elder.member_id != profile.pk:
            raise PermissionDenied("You can only record milestones for members assigned to you.")
        serializer.save(verified_by=profile)
