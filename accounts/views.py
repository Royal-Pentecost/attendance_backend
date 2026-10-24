"""
accounts/views.py

Assumptions flagged:
- Role changes after Member creation are NOT possible via this API (role is
  read-only in MemberSerializer). Use Django admin or a future dedicated endpoint.
- ImportBatch creation triggers no background task here — it only records the
  file upload. Actual processing would be kicked off by a separate signal or task.
"""
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import Assembly, DayBornGroup, Member, Elder, ElderOfficeHours, ImportBatch
from core.authentication import end_sessions
from core.models import ActivityLog, record_activity
from accounts.permissions import (
    IsSuperAdmin,
    IsAssemblyAdminOrSuperAdmin,
    IsSelfOrAssemblyAdmin,
)
from accounts.serializers import (
    AssemblySerializer,
    DayBornGroupSerializer,
    MemberSerializer,
    MemberCreateSerializer,
    ElderSerializer,
    ElderOfficeHoursSerializer,
    ImportBatchSerializer,
)


# ---------------------------------------------------------------------------
# Helper mixin — resolves the requesting user's Member profile
# ---------------------------------------------------------------------------

class AssemblyScopedMixin:
    """Provides get_requesting_profile() used by all scoped viewsets."""

    def get_requesting_profile(self):
        try:
            return self.request.user.member_profile
        except Member.DoesNotExist:
            return None


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(tags=["Assemblies"]),
    create=extend_schema(
        tags=["Assemblies"],
        description="Create a new assembly branch. **Requires super_admin role.**",
    ),
    retrieve=extend_schema(tags=["Assemblies"]),
    update=extend_schema(
        tags=["Assemblies"],
        description="Update an assembly. **Requires super_admin role.**",
    ),
    partial_update=extend_schema(
        tags=["Assemblies"],
        description="Partially update an assembly. **Requires super_admin role.**",
    ),
    destroy=extend_schema(
        tags=["Assemblies"],
        description="Delete an assembly. **Requires super_admin role.**",
    ),
)
class AssemblyViewSet(AssemblyScopedMixin, viewsets.ModelViewSet):
    """
    list/retrieve: any authenticated user (members see all assemblies for
                   selection purposes; in practice they'd query their own).
    create/update/delete: super_admin only (creating a new assembly branch is
                           a top-level admin action, not per-assembly).
    """
    serializer_class = AssemblySerializer

    def perform_update(self, serializer):
        before = self.get_object()
        was = (before.geofence_center_lat, before.geofence_center_lng, before.geofence_radius_meters)

        assembly = serializer.save()

        now = (assembly.geofence_center_lat, assembly.geofence_center_lng, assembly.geofence_radius_meters)
        if now != was:
            # The boundary decides who may sign attendance at all, so moving it
            # is a change to the rule everyone else is measured against.
            record_activity(
                actor=self.get_requesting_profile(),
                action="Changed attendance boundary",
                affected_record=f"{assembly.name}: {was[0]},{was[1]} r{was[2]} to {now[0]},{now[1]} r{now[2]}",
                severity=ActivityLog.SEVERITY_WARNING,
                assembly=assembly,
            )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Assembly.objects.none()
        profile = self.get_requesting_profile()
        if profile is None:
            return Assembly.objects.all() if self.request.user.is_superuser else Assembly.objects.none()
        # All authenticated members can list assemblies (they need this to find their own)
        return Assembly.objects.all()

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsSuperAdmin()]
        return [IsAuthenticated()]


# ---------------------------------------------------------------------------
# DayBornGroup
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(tags=["Day-Born Groups"]),
    create=extend_schema(tags=["Day-Born Groups"]),
    retrieve=extend_schema(tags=["Day-Born Groups"]),
    update=extend_schema(tags=["Day-Born Groups"]),
    partial_update=extend_schema(tags=["Day-Born Groups"]),
    destroy=extend_schema(tags=["Day-Born Groups"]),
)
class DayBornGroupViewSet(AssemblyScopedMixin, viewsets.ModelViewSet):
    """
    Scoped to the requesting member's assembly for non-super-admins.
    Write access restricted to assembly_admin or super_admin.
    """
    serializer_class = DayBornGroupSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DayBornGroup.objects.none()
        profile = self.get_requesting_profile()
        if profile is None:
            return DayBornGroup.objects.all() if self.request.user.is_superuser else DayBornGroup.objects.none()
        if profile.role == Member.ROLE_SUPER_ADMIN:
            return DayBornGroup.objects.all()
        return DayBornGroup.objects.filter(assembly=profile.assembly)

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsAssemblyAdminOrSuperAdmin()]
        return [IsAuthenticated()]


# ---------------------------------------------------------------------------
# Member
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(tags=["Members"]),
    create=extend_schema(
        tags=["Members"],
        description=(
            "Create a new member profile. **Requires assembly_admin or super_admin role.**\n\n"
            "Uses `MemberCreateSerializer`. Pass `phone_number` to give the member a login — "
            "the User account is created alongside the profile. Omit it for the many members "
            "on the roll with no phone on file; they can be given one later.\n\n"
            "`member_id` is generated as the next free `MEM-###` when omitted. "
            "`assembly` defaults to the creating admin's own.\n\n"
            "`role` may only be set above `member` by a super admin. Everyone else promotes "
            "through `POST /members/{id}/set-role/`, which is audited."
        ),
    ),
    retrieve=extend_schema(tags=["Members"]),
    update=extend_schema(
        tags=["Members"],
        description=(
            "Update a member profile. **Requires the member themselves (self-update) "
            "OR assembly_admin for members within the same assembly.**\n\n"
            "`role` is read-only on update to prevent self-escalation."
        ),
    ),
    partial_update=extend_schema(
        tags=["Members"],
        description=(
            "Partially update a member profile. Same permission rules as full update: "
            "self OR assembly_admin within the same assembly."
        ),
    ),
    destroy=extend_schema(
        tags=["Members"],
        description="Delete a member profile. **Requires assembly_admin or super_admin role.**",
    ),
)
class MemberViewSet(AssemblyScopedMixin, viewsets.ModelViewSet):
    """
    list/retrieve: scoped to own assembly.
    create/delete: assembly_admin or super_admin.
    update/partial_update: self OR assembly_admin (IsSelfOrAssemblyAdmin at object level).

    Role changes do not go through update/partial_update — `role` is read-only on
    MemberSerializer so a member cannot escalate themselves with a self-PATCH.
    They go through `set-role` below, which only a super admin may call.
    """

    def get_serializer_class(self):
        if self.action == "create":
            return MemberCreateSerializer
        return MemberSerializer

    def perform_create(self, serializer):
        profile = self.get_requesting_profile()

        # An admin adding someone to the roll means their own assembly. Left
        # unset, the new member falls outside the assembly filter in
        # `get_queryset` and vanishes from the directory of the admin who had
        # just typed them in.
        extra = {}
        if serializer.validated_data.get("assembly") is None and profile and profile.assembly:
            extra["assembly"] = profile.assembly

        member = serializer.save(**extra)

        record_activity(
            actor=profile,
            action="Added member",
            affected_record=(
                f"{member.full_name} ({member.member_id})"
                + (" with login" if member.user_id else " — no phone on file")
            ),
            assembly=member.assembly,
        )

    def perform_update(self, serializer):
        tracked = ("full_name", "date_of_birth", "sex")
        before = {f: getattr(serializer.instance, f) for f in tracked}
        had_phone = serializer.instance.user.phone_number if serializer.instance.user_id else ""

        member = serializer.save()

        # Name the fields that actually moved. "Updated member" on its own tells
        # whoever reads the trail nothing they can check a correction against.
        changed = [f.replace("_", " ") for f, was in before.items() if getattr(member, f) != was]
        has_phone = member.user.phone_number if member.user_id else ""
        if has_phone != had_phone:
            changed.append(
                "phone added" if not had_phone else
                "phone removed" if not has_phone else "phone number"
            )
        record_activity(
            actor=self.get_requesting_profile(),
            action="Corrected member record" if changed else "Updated member",
            affected_record=(
                f"{member.full_name} ({member.member_id})"
                + (f": {', '.join(changed)}" if changed else "")
            ),
            assembly=member.assembly,
        )

    def perform_destroy(self, instance):
        # Captured before the row goes; afterwards there is nothing to name.
        description = f"{instance.full_name} ({instance.member_id})"
        assembly = instance.assembly
        actor = self.get_requesting_profile()

        # The login goes with the profile. Left behind, the number still passes
        # OTP and the holder is handed a token with no member attached — signed
        # in to an app that has nobody to show them. Deleting the user cascades
        # to the member, so this one call removes both.
        if instance.user_id:
            instance.user.delete()
        else:
            instance.delete()
        record_activity(
            actor=actor,
            action="Removed member",
            affected_record=description,
            severity=ActivityLog.SEVERITY_CRITICAL,
            assembly=assembly,
        )

    @extend_schema(
        summary="Change a member's role",
        description=(
            "Grants or revokes administrative privileges. Super admins only — a "
            "PATCH to the member itself cannot change `role`, which is what stops "
            "a member promoting themselves."
        ),
        request={"application/json": {"type": "object", "properties": {"role": {"type": "string"}}}},
        responses={200: MemberSerializer},
    )
    @action(detail=True, methods=["post"], url_path="set-role",
            permission_classes=[IsAuthenticated, IsSuperAdmin])
    def set_role(self, request, pk=None):
        member = self.get_object()
        role = request.data.get("role")

        valid = dict(Member.ROLE_CHOICES)
        if role not in valid:
            return Response(
                {"role": [f"Must be one of: {', '.join(valid)}."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # A super admin removing their own last privilege would lock the church
        # out of its own administration.
        if member == getattr(request.user, "member_profile", None) and role != Member.ROLE_SUPER_ADMIN:
            return Response(
                {"role": ["You cannot remove your own super admin role."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        was = member.role
        member.role = role
        member.save(update_fields=["role", "updated_at"])

        # Taking privileges away takes effect now, not at the next sign-in:
        # their token is deleted, so the very next request their phone makes
        # is refused and the app returns to login. Granting needs no such
        # step — the new role is read fresh on every request.
        rank = {Member.ROLE_MEMBER: 0, Member.ROLE_ASSEMBLY_ADMIN: 1, Member.ROLE_SUPER_ADMIN: 2}
        if rank.get(role, 0) < rank.get(was, 0):
            end_sessions(member.user)

        # Granting or removing administrative access is the most consequential
        # thing anyone does in this system, so it is always on the trail.
        record_activity(
            actor=getattr(request.user, "member_profile", None),
            action="Granted admin role" if role != Member.ROLE_MEMBER else "Revoked admin role",
            affected_record=f"{member.full_name} ({member.member_id}): {was} to {role}",
            severity=ActivityLog.SEVERITY_CRITICAL,
            assembly=member.assembly,
        )

        return Response(MemberSerializer(member, context={"request": request}).data)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Member.objects.none()
        profile = self.get_requesting_profile()
        if profile is None:
            return Member.objects.all() if self.request.user.is_superuser else Member.objects.none()
        if profile.role == Member.ROLE_SUPER_ADMIN:
            return Member.objects.all()
        return Member.objects.filter(assembly=profile.assembly)

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsAssemblyAdminOrSuperAdmin()]
        if self.action in ("update", "partial_update"):
            return [IsAuthenticated(), IsSelfOrAssemblyAdmin()]
        if self.action == "destroy":
            return [IsAuthenticated(), IsAssemblyAdminOrSuperAdmin()]
        return [IsAuthenticated()]


# ---------------------------------------------------------------------------
# Elder
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(tags=["Elders"]),
    create=extend_schema(tags=["Elders"]),
    retrieve=extend_schema(tags=["Elders"]),
    update=extend_schema(tags=["Elders"]),
    partial_update=extend_schema(tags=["Elders"]),
    destroy=extend_schema(tags=["Elders"]),
)
class ElderViewSet(AssemblyScopedMixin, viewsets.ModelViewSet):
    """
    Scoped to the requesting member's assembly.
    Write access restricted to assembly_admin or super_admin.
    """
    serializer_class = ElderSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Elder.objects.none()
        profile = self.get_requesting_profile()
        if profile is None:
            return Elder.objects.all() if self.request.user.is_superuser else Elder.objects.none()
        if profile.role == Member.ROLE_SUPER_ADMIN:
            return Elder.objects.all()
        return Elder.objects.filter(member__assembly=profile.assembly)

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsAssemblyAdminOrSuperAdmin()]
        return [IsAuthenticated()]


# ---------------------------------------------------------------------------
# ElderOfficeHours
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(tags=["Elder Office Hours"]),
    create=extend_schema(tags=["Elder Office Hours"]),
    retrieve=extend_schema(tags=["Elder Office Hours"]),
    update=extend_schema(tags=["Elder Office Hours"]),
    partial_update=extend_schema(tags=["Elder Office Hours"]),
    destroy=extend_schema(tags=["Elder Office Hours"]),
)
class ElderOfficeHoursViewSet(AssemblyScopedMixin, viewsets.ModelViewSet):
    """
    Scoped to the requesting member's assembly.
    Write access restricted to assembly_admin or super_admin.
    """
    serializer_class = ElderOfficeHoursSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ElderOfficeHours.objects.none()
        profile = self.get_requesting_profile()
        if profile is None:
            return ElderOfficeHours.objects.all() if self.request.user.is_superuser else ElderOfficeHours.objects.none()
        if profile.role == Member.ROLE_SUPER_ADMIN:
            return ElderOfficeHours.objects.all()
        return ElderOfficeHours.objects.filter(elder__member__assembly=profile.assembly)

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsAssemblyAdminOrSuperAdmin()]
        return [IsAuthenticated()]


# ---------------------------------------------------------------------------
# ImportBatch
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(tags=["Import Batches"]),
    create=extend_schema(
        tags=["Import Batches"],
        description=(
            "Upload a CSV file to create a member import batch for an assembly. "
            "**Requires assembly_admin or super_admin role.**\n\n"
            "`uploaded_by` is set server-side to the requesting admin. "
            "`status` starts as `pending` — actual row processing is handled by "
            "a background task, not this endpoint. Poll the batch detail to track progress."
        ),
    ),
    retrieve=extend_schema(tags=["Import Batches"]),
)
class ImportBatchViewSet(AssemblyScopedMixin, viewsets.ModelViewSet):
    """
    Assembly admins can create and view batches for their own assembly.
    `uploaded_by` is set server-side (never client-supplied).
    Status transitions are handled by background tasks (not this viewset).
    """
    serializer_class = ImportBatchSerializer
    http_method_names = ["get", "post", "head", "options"]  # no PUT/PATCH/DELETE on batches

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ImportBatch.objects.none()
        profile = self.get_requesting_profile()
        if profile is None:
            return ImportBatch.objects.all() if self.request.user.is_superuser else ImportBatch.objects.none()
        if profile.role == Member.ROLE_SUPER_ADMIN:
            return ImportBatch.objects.all()
        return ImportBatch.objects.filter(assembly=profile.assembly)

    def get_permissions(self):
        return [IsAuthenticated(), IsAssemblyAdminOrSuperAdmin()]

    def perform_create(self, serializer):
        profile = self.get_requesting_profile()
        assembly = serializer.validated_data.get("assembly")
        if profile.role == Member.ROLE_ASSEMBLY_ADMIN and assembly != profile.assembly:
            raise PermissionDenied("You can only create import batches for your own assembly.")
        serializer.save(uploaded_by=profile)
