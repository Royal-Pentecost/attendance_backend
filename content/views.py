"""
content/views.py

Assumptions flagged:
- BibleStudyWeek queryset: members see district-wide content (assembly=null)
  PLUS their own assembly's content, if any.
- Event queryset: members see district-scoped events (scope='district') PLUS
  their own assembly's events.
- Notification queryset: filtered to notifications actually targeting the
  requesting member (audience_type=all, or their assembly, day_born_group, or
  direct member FK).
- NotificationRead.perform_create: member is always set to the requesting user
  (clients cannot mark reads on behalf of other members).
- `created_by` on Event is set server-side to the requesting admin.
"""
from django.db import models as django_models
from django.utils import timezone

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from accounts.models import Member
from accounts.permissions import IsAssemblyAdminOrSuperAdmin
from content.models import WeeklySchedule, BibleStudyWeek, Event, Notification, NotificationRead
from content.models import BibleStudyTranslation, DailyVerse
from content.serializers import (
    BibleStudyTranslationSerializer,
    DailyVerseSerializer,
    WeeklyScheduleSerializer,
    BibleStudyWeekSerializer,
    EventSerializer,
    NotificationSerializer,
    NotificationReadSerializer,
)


class AssemblyScopedMixin:
    def get_requesting_profile(self):
        try:
            return self.request.user.member_profile
        except Member.DoesNotExist:
            return None


@extend_schema_view(
    list=extend_schema(tags=["Weekly Schedules"]),
    create=extend_schema(tags=["Weekly Schedules"]),
    retrieve=extend_schema(tags=["Weekly Schedules"]),
    update=extend_schema(tags=["Weekly Schedules"]),
    partial_update=extend_schema(tags=["Weekly Schedules"]),
    destroy=extend_schema(tags=["Weekly Schedules"]),
)
class WeeklyScheduleViewSet(AssemblyScopedMixin, viewsets.ModelViewSet):
    """
    Scoped to the requesting member's assembly.
    Write: assembly_admin or super_admin.
    """
    serializer_class = WeeklyScheduleSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WeeklySchedule.objects.none()
        profile = self.get_requesting_profile()
        if profile is None:
            return WeeklySchedule.objects.all() if self.request.user.is_superuser else WeeklySchedule.objects.none()
        if profile.role == Member.ROLE_SUPER_ADMIN:
            return WeeklySchedule.objects.all()
        return WeeklySchedule.objects.filter(assembly=profile.assembly)

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsAssemblyAdminOrSuperAdmin()]
        return [IsAuthenticated()]


@extend_schema_view(
    list=extend_schema(
        tags=["Bible Study"],
        description=(
            "List Bible study weeks visible to the requesting member: district-wide entries "
            "(assembly=null) plus any assembly-specific entries for their own assembly."
        ),
    ),
    create=extend_schema(tags=["Bible Study"]),
    retrieve=extend_schema(tags=["Bible Study"]),
    update=extend_schema(tags=["Bible Study"]),
    partial_update=extend_schema(tags=["Bible Study"]),
    destroy=extend_schema(tags=["Bible Study"]),
)
class BibleStudyWeekViewSet(AssemblyScopedMixin, viewsets.ModelViewSet):
    """
    Members see district-wide content (assembly=null) + their own assembly's content.
    Write: assembly_admin or super_admin.
    """
    serializer_class = BibleStudyWeekSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return BibleStudyWeek.objects.none()
        profile = self.get_requesting_profile()
        if profile is None:
            return BibleStudyWeek.objects.all() if self.request.user.is_superuser else BibleStudyWeek.objects.none()
        if profile.role == Member.ROLE_SUPER_ADMIN:
            return BibleStudyWeek.objects.all()
        return BibleStudyWeek.objects.filter(
            django_models.Q(assembly=profile.assembly) | django_models.Q(assembly__isnull=True)
        )

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsAssemblyAdminOrSuperAdmin()]
        return [IsAuthenticated()]


@extend_schema_view(
    list=extend_schema(
        tags=["Events"],
        description=(
            "List events visible to the requesting member: their assembly's events "
            "plus any district-scoped events (scope='district')."
        ),
    ),
    create=extend_schema(
        tags=["Events"],
        description=(
            "Create an event. **Requires assembly_admin or super_admin role.**\n\n"
            "`created_by` is set server-side. "
            "If `scope='assembly'`, `assembly_id` is required. "
            "If `scope='district'`, `assembly_id` must be omitted."
        ),
    ),
    retrieve=extend_schema(tags=["Events"]),
    update=extend_schema(tags=["Events"]),
    partial_update=extend_schema(tags=["Events"]),
    destroy=extend_schema(tags=["Events"]),
)
class EventViewSet(AssemblyScopedMixin, viewsets.ModelViewSet):
    """
    Members see their assembly's events + district-wide events.
    `created_by` is set server-side.
    Write: assembly_admin or super_admin.
    """
    serializer_class = EventSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Event.objects.none()
        profile = self.get_requesting_profile()
        if profile is None:
            return Event.objects.all() if self.request.user.is_superuser else Event.objects.none()
        if profile.role == Member.ROLE_SUPER_ADMIN:
            return Event.objects.all()
        return Event.objects.filter(
            django_models.Q(assembly=profile.assembly) | django_models.Q(scope=Event.SCOPE_DISTRICT)
        )

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsAssemblyAdminOrSuperAdmin()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        profile = self.get_requesting_profile()
        serializer.save(created_by=profile)


@extend_schema_view(
    list=extend_schema(
        tags=["Notifications"],
        description=(
            "List notifications targeted at the requesting member. Includes notifications with:\n"
            "- `audience_type=all` (broadcast to everyone)\n"
            "- `audience_type=assembly` matching the member's assembly\n"
            "- `audience_type=day_born_group` matching the member's day-born group\n"
            "- `audience_type=member` targeted directly at this member"
        ),
    ),
    create=extend_schema(
        tags=["Notifications"],
        description=(
            "Create a notification. **Requires assembly_admin or super_admin role.**\n\n"
            "Exactly one of the audience FK fields must be set, matching `audience_type`:\n"
            "- `all` → no FK set\n"
            "- `assembly` → `assembly_id` required, others null\n"
            "- `day_born_group` → `day_born_group_id` required, others null\n"
            "- `member` → `member_id` required, others null\n\n"
            "The serializer validates this constraint and returns 400 if violated."
        ),
    ),
    retrieve=extend_schema(tags=["Notifications"]),
    update=extend_schema(tags=["Notifications"]),
    partial_update=extend_schema(tags=["Notifications"]),
    destroy=extend_schema(tags=["Notifications"]),
)
class NotificationViewSet(AssemblyScopedMixin, viewsets.ModelViewSet):
    """
    Read: filtered to notifications that target the requesting member
          (audience_type=all, or their assembly/day_born_group/direct member).
    Write: assembly_admin or super_admin.
    """
    serializer_class = NotificationSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        profile = self.get_requesting_profile()
        if profile is None:
            return Notification.objects.all() if self.request.user.is_superuser else Notification.objects.none()
        if profile.role == Member.ROLE_SUPER_ADMIN:
            return Notification.objects.all()
        return Notification.objects.filter(
            django_models.Q(audience_type=Notification.AUDIENCE_ALL)
            | django_models.Q(audience_type=Notification.AUDIENCE_ASSEMBLY, assembly=profile.assembly)
            | django_models.Q(audience_type=Notification.AUDIENCE_DAY_BORN_GROUP, day_born_group=profile.day_born_group)
            | django_models.Q(audience_type=Notification.AUDIENCE_MEMBER, member=profile)
        )

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsAssemblyAdminOrSuperAdmin()]
        return [IsAuthenticated()]


@extend_schema_view(
    list=extend_schema(
        tags=["Notification Reads"],
        description=(
            "List read receipts. Members see only their own; "
            "assembly admins see all receipts for their assembly's members; "
            "super admins see all."
        ),
    ),
    create=extend_schema(
        tags=["Notification Reads"],
        description=(
            "Mark a notification as read for the requesting member. "
            "`member` and `read_at` are always set server-side — "
            "you cannot mark a notification as read on behalf of another member. "
            "Returns 400 if a read receipt already exists for this member + notification pair."
        ),
    ),
    retrieve=extend_schema(tags=["Notification Reads"]),
)
class NotificationReadViewSet(AssemblyScopedMixin, viewsets.ModelViewSet):
    """
    Members can mark notifications as read (create a NotificationRead).
    `member` and `read_at` are always set server-side.
    Only the member's own read receipts are visible.
    Assembly admins/super_admins see all read receipts within their scope.
    """
    serializer_class = NotificationReadSerializer
    http_method_names = ["get", "post", "head", "options"]  # no PUT/PATCH/DELETE

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return NotificationRead.objects.none()
        profile = self.get_requesting_profile()
        if profile is None:
            return NotificationRead.objects.all() if self.request.user.is_superuser else NotificationRead.objects.none()
        if profile.role == Member.ROLE_SUPER_ADMIN:
            return NotificationRead.objects.all()
        if profile.role == Member.ROLE_ASSEMBLY_ADMIN:
            return NotificationRead.objects.filter(member__assembly=profile.assembly)
        return NotificationRead.objects.filter(member=profile)

    def perform_create(self, serializer):
        profile = self.get_requesting_profile()
        serializer.save(member=profile, read_at=timezone.now())


@extend_schema_view(
    list=extend_schema(summary="Study text, per language"),
    create=extend_schema(summary="Write a study in one language"),
)
class BibleStudyTranslationViewSet(AssemblyScopedMixin, viewsets.ModelViewSet):
    """
    The written-out study, one row per language.

    Separate from the week itself so a study can be published the moment its
    title, scripture and page range are known — the aims and questions can
    follow when somebody has time to type them, in either language or both.
    """

    serializer_class = BibleStudyTranslationSerializer
    queryset = BibleStudyTranslation.objects.select_related("week").all()

    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(self, "swagger_fake_view", False):
            return qs.none()
        # Only the text of weeks this member can see — their assembly's and the
        # district's. It returned every assembly's text to anyone signed in.
        profile = self.get_requesting_profile()
        if profile is None:
            qs = qs if self.request.user.is_superuser else qs.none()
        elif profile.role != Member.ROLE_SUPER_ADMIN:
            qs = qs.filter(
                django_models.Q(week__assembly=profile.assembly) | django_models.Q(week__assembly__isnull=True)
            )
        week = self.request.query_params.get("week")
        return qs.filter(week_id=week) if week else qs

    def get_permissions(self):
        # Writing a study is an admin's job. With no rule here, any member could
        # rewrite or delete the text every other member reads.
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsAssemblyAdminOrSuperAdmin()]
        return [IsAuthenticated()]


class DailyVerseViewSet(AssemblyScopedMixin, viewsets.ModelViewSet):
    """
    The morning verse. Read: the member's assembly and district-wide verses,
    newest first — the app shows the first. Write: assembly_admin or super_admin.
    """
    serializer_class = DailyVerseSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DailyVerse.objects.none()
        profile = self.get_requesting_profile()
        if profile is None:
            return DailyVerse.objects.all() if self.request.user.is_superuser else DailyVerse.objects.none()
        if profile.role == Member.ROLE_SUPER_ADMIN:
            return DailyVerse.objects.all()
        return DailyVerse.objects.filter(
            django_models.Q(assembly=profile.assembly) | django_models.Q(assembly__isnull=True)
        )

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsAssemblyAdminOrSuperAdmin()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.get_requesting_profile())
