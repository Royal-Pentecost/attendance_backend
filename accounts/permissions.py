"""
accounts/permissions.py

Custom DRF permission classes for role-based and object-level access control.

Convention: all classes assume request.user is authenticated (IsAuthenticated
is applied globally in REST_FRAMEWORK settings). Each class gracefully returns
False (403) when request.user has no Member profile — this covers Django
superusers created via createsuperuser before a Member record was attached.
"""
from rest_framework.permissions import BasePermission

from accounts.models import Member


def _get_object_assembly(obj):
    """
    Resolve the assembly from an object by trying common attribute paths.
    Returns the Assembly instance or None if no assembly can be determined.

    Order tried:
      1. obj.assembly          — direct FK (Assembly, DayBornGroup, AttendanceSession, WeeklySchedule, etc.)
      2. obj.member.assembly   — via member FK (SpiritualMilestone, AttendanceRecord, ImportBatch, etc.)
      3. obj.session.assembly  — via session FK (AttendanceRecord)
    """
    if hasattr(obj, "assembly") and obj.assembly is not None:
        return obj.assembly
    if hasattr(obj, "member") and obj.member is not None:
        if hasattr(obj.member, "assembly"):
            return obj.member.assembly
    if hasattr(obj, "session") and obj.session is not None:
        if hasattr(obj.session, "assembly"):
            return obj.session.assembly
    return None


class IsSuperAdmin(BasePermission):
    """
    Allows access only to Members whose role is `super_admin`.

    Super admins have global, unrestricted access across all assemblies and
    all models. This is the highest privilege level in the system.

    Falls back to 403 (False) if:
    - The user is not authenticated (handled upstream by IsAuthenticated).
    - The user has no linked Member profile (e.g. a raw Django superuser
      created via `createsuperuser` who hasn't been given a Member record yet).
    """

    def has_permission(self, request, view):
        try:
            return request.user.member_profile.role == Member.ROLE_SUPER_ADMIN
        except Member.DoesNotExist:
            return False


class IsAssemblyAdminOrSuperAdmin(BasePermission):
    """
    Allows access to Members with role `assembly_admin` OR `super_admin`.

    Assembly admins can act on data within their OWN assembly only; that
    assembly-scoping is enforced in viewset `get_queryset()` and object-level
    permission checks — NOT in this class. This class is purely a role gate.

    Falls back to 403 if the user has no Member profile.
    """

    def has_permission(self, request, view):
        try:
            return request.user.member_profile.role in (
                Member.ROLE_ASSEMBLY_ADMIN,
                Member.ROLE_SUPER_ADMIN,
            )
        except Member.DoesNotExist:
            return False


class IsSameAssembly(BasePermission):
    """
    Object-level permission. Grants access if the requesting member belongs to
    the same assembly as the object being accessed.

    Assembly resolution tries these attribute paths in order:
      1. obj.assembly          (direct FK — most models)
      2. obj.member.assembly   (via member relation)
      3. obj.session.assembly  (via session relation)

    Returns False if no assembly can be resolved from the object.

    Super admins bypass this check (they have global access regardless).
    Falls back to 403 if the user has no Member profile.

    Note: This is an *object-level* permission only (has_object_permission).
    Pair it with a viewset that calls check_object_permissions, or apply it
    alongside queryset scoping for belt-and-suspenders protection.
    """

    def has_object_permission(self, request, view, obj):
        try:
            profile = request.user.member_profile
        except Member.DoesNotExist:
            return False

        if profile.role == Member.ROLE_SUPER_ADMIN:
            return True

        obj_assembly = _get_object_assembly(obj)
        if obj_assembly is None:
            return False

        return profile.assembly_id == obj_assembly.pk


class IsSelfOrAssemblyAdmin(BasePermission):
    """
    Object-level permission for Member objects. Grants access if ANY of:
    - The object being accessed IS the requesting member (self-access).
    - The requesting member has role `assembly_admin` AND belongs to the same
      assembly as the target member (admin manages members in their assembly).
    - The requesting member has role `super_admin` (global access).

    Use on MemberViewSet for update / partial_update / destroy actions.
    Falls back to 403 if the user has no Member profile.
    """

    def has_object_permission(self, request, view, obj):
        # obj is a Member instance
        try:
            profile = request.user.member_profile
        except Member.DoesNotExist:
            return False

        if obj.pk == profile.pk:
            return True

        if profile.role == Member.ROLE_SUPER_ADMIN:
            return True

        if (
            profile.role == Member.ROLE_ASSEMBLY_ADMIN
            and profile.assembly_id is not None
            and profile.assembly_id == obj.assembly_id
        ):
            return True

        return False


class IsAssignedElderOrAdmin(BasePermission):
    """
    Object-level permission for SpiritualMilestone objects. Grants access if:
    - The requesting member is `super_admin` (global access), OR
    - The requesting member is `assembly_admin` in the SAME assembly as the
      milestone's member (assembly-scoped admin access), OR
    - The requesting member is the elder assigned to the milestone's member
      (obj.member.assigned_elder.member == request.user.member_profile).

    For write actions (create / update / destroy), has_permission also checks
    that the requester is an admin OR has an elder profile — preventing plain
    members from even reaching the object-level check on write actions.
    For read actions, has_permission allows all authenticated users through,
    and queryset scoping (in the viewset) handles the real filtering.

    Falls back to 403 if the user has no Member profile.
    """

    def has_permission(self, request, view):
        try:
            profile = request.user.member_profile
        except Member.DoesNotExist:
            return False

        write_actions = ("create", "update", "partial_update", "destroy")
        if getattr(view, "action", None) not in write_actions:
            return True  # reads are scoped by get_queryset

        if profile.role in (Member.ROLE_ASSEMBLY_ADMIN, Member.ROLE_SUPER_ADMIN):
            return True

        # Allow elders through to object-level (which checks the specific assignment)
        return hasattr(profile, "elder_profile")

    def has_object_permission(self, request, view, obj):
        # obj is a SpiritualMilestone instance
        try:
            profile = request.user.member_profile
        except Member.DoesNotExist:
            return False

        if profile.role == Member.ROLE_SUPER_ADMIN:
            return True

        if (
            profile.role == Member.ROLE_ASSEMBLY_ADMIN
            and profile.assembly_id is not None
            and profile.assembly_id == obj.member.assembly_id
        ):
            return True

        # Check assigned elder
        assigned_elder = obj.member.assigned_elder
        if assigned_elder is not None and assigned_elder.member_id == profile.pk:
            return True

        return False
