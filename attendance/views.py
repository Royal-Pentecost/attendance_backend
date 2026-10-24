"""
attendance/views.py

Assumptions flagged:
- GPS distance computation uses the Haversine formula (spherical Earth model,
  accurate to ~0.3% — sufficient for a geofence check).
- For GPS check-ins, `member` in the request body is IGNORED and always
  overridden to the requesting user's member profile.
- For manual check-ins, the admin must supply `member_id` in the request body.
- `AttendanceSession.close` is a dedicated POST action (not a PATCH on is_active)
  because closing is a business event, not just a field update.
- Assembly admins can only open sessions for their own assembly.
"""
import datetime
import math
import uuid

from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import Member
from accounts.permissions import IsAssemblyAdminOrSuperAdmin
from core.models import ActivityLog, record_activity
from core.push import announce
from content.models import Notification
from attendance.models import AttendanceSession, AttendanceRecord, MemberAttendanceStat
from attendance.serializers import (
    AttendanceSessionSerializer,
    AttendanceRecordSerializer,
    MemberAttendanceStatSerializer,
)


def _parse_date(request):
    """
    `?date=YYYY-MM-DD`, or None when absent.

    The dashboard asks "who signed in today", and without this the only way to
    answer was to download every record the church has ever taken — which the
    app caps at a few hundred rows, so within weeks today's would fall off the
    end of the list and the count would quietly read zero.
    """
    raw = (request.query_params.get("date") or "").strip()
    if not raw:
        return None
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        raise ValidationError({"date": ["Use the form YYYY-MM-DD."]})



def haversine_distance(lat1, lng1, lat2, lng2):
    """Returns distance in meters between two GPS coordinates (Haversine formula)."""
    R = 6_371_000
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lng2) - float(lng1))
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return round(2 * R * math.asin(math.sqrt(a)))


class AssemblyScopedMixin:
    def get_requesting_profile(self):
        try:
            return self.request.user.member_profile
        except Member.DoesNotExist:
            return None


@extend_schema_view(
    list=extend_schema(tags=["Attendance Sessions"]),
    create=extend_schema(
        tags=["Attendance Sessions"],
        description=(
            "Open a new attendance session for an assembly. "
            "**Requires assembly_admin or super_admin role.**\n\n"
            "The geofence (`geofence_center_lat`, `geofence_center_lng`, `geofence_radius_meters`) "
            "is snapshotted from the Assembly at open-time and stored on the session — "
            "editing the Assembly's geofence later does not retroactively change this session. "
            "`opened_by` is set server-side to the requesting admin. "
            "The Assembly must have its geofence fully configured before a session can be opened."
        ),
    ),
    retrieve=extend_schema(tags=["Attendance Sessions"]),
    update=extend_schema(tags=["Attendance Sessions"]),
    partial_update=extend_schema(tags=["Attendance Sessions"]),
    destroy=extend_schema(tags=["Attendance Sessions"]),
)
class AttendanceSessionViewSet(AssemblyScopedMixin, viewsets.ModelViewSet):
    """
    create: assembly_admin or super_admin; snapshots geofence from Assembly.
    close (POST /{id}/close/): assembly_admin or super_admin.
    list/retrieve: all authenticated members (scoped to their assembly).
    update/delete: assembly_admin or super_admin.
    """
    serializer_class = AttendanceSessionSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AttendanceSession.objects.none()
        profile = self.get_requesting_profile()
        if profile is None:
            return AttendanceSession.objects.all() if self.request.user.is_superuser else AttendanceSession.objects.none()
        if profile.role == Member.ROLE_SUPER_ADMIN:
            qs = AttendanceSession.objects.all()
        else:
            qs = AttendanceSession.objects.filter(assembly=profile.assembly)

        day = _parse_date(self.request)
        if day:
            qs = qs.filter(opened_at__date=day)
        # `?open=true` — the session(s) still taking attendance, whatever day
        # they were opened. Every phone polls for this; without the filter it
        # meant downloading every session the assembly had ever held.
        if (self.request.query_params.get("open") or "").lower() in ("1", "true", "yes"):
            qs = qs.filter(is_active=True, closed_at__isnull=True)
        return qs

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy", "close"):
            return [IsAuthenticated(), IsAssemblyAdminOrSuperAdmin()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        profile = self.get_requesting_profile()
        assembly = serializer.validated_data.get("assembly")

        if profile.role == Member.ROLE_ASSEMBLY_ADMIN and assembly != profile.assembly:
            raise PermissionDenied("Assembly admins can only open sessions for their own assembly.")

        # A service is not always held where the assembly's fence was drawn — a
        # convention in a school hall, a service under a canopy. So the centre
        # the admin's own device reports when they open the session wins, and the
        # assembly's stored fence is the fallback for when it has none.
        data = serializer.validated_data
        lat = data.get("geofence_center_lat") or assembly.geofence_center_lat
        lng = data.get("geofence_center_lng") or assembly.geofence_center_lng
        radius = data.get("geofence_radius_meters") or assembly.geofence_radius_meters

        if not all([lat, lng, radius]):
            raise ValidationError(
                "No geofence for this session. Either send the coordinates when "
                "opening it, or configure the assembly's own fence first."
            )

        anchored_to_admin = bool(data.get("geofence_center_lat"))

        session = serializer.save(
            opened_by=profile,
            geofence_center_lat=lat,
            geofence_center_lng=lng,
            geofence_radius_meters=radius,
        )

        # Every member of the assembly is told, app open or not: a member who
        # finds out after the service has missed their chance to sign.
        announce(
            kind=Notification.TYPE_SESSION_OPEN,
            title="Attendance is open",
            body=f"{session.service_name} has started. Open the app to sign in.",
            assembly=assembly,
            actor=profile,
            data={"sessionId": str(session.id)},
        )

        record_activity(
            actor=profile,
            action="Opened attendance session",
            affected_record=(
                f"{session.service_name} — {radius}m around "
                + ("the admin's position" if anchored_to_admin else "the assembly fence")
            ),
            assembly=assembly,
        )

    @extend_schema(
        tags=["Attendance Sessions"],
        summary="Close an attendance session",
        description=(
            "Mark an active attendance session as closed. "
            "**Requires assembly_admin or super_admin role.**\n\n"
            "Sets `is_active=False` and records `closed_at` as the current server time. "
            "Returns 400 if the session is already closed. "
            "Once closed, members can no longer check in to this session."
        ),
        request=None,
        responses={
            200: AttendanceSessionSerializer,
            400: OpenApiResponse(description="Session already closed"),
        },
    )
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """Close an active attendance session."""
        session = self.get_object()
        if not session.is_active:
            return Response(
                {"detail": "Session is already closed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        session.closed_at = timezone.now()
        session.is_active = False
        session.save(update_fields=["closed_at", "is_active", "updated_at"])

        record_activity(
            actor=self.get_requesting_profile(),
            action="Closed attendance session",
            affected_record=f"{session.service_name} — {session.records.count()} marked",
            assembly=session.assembly,
        )

        return Response(self.get_serializer(session).data)


@extend_schema_view(
    list=extend_schema(tags=["Attendance Records"]),
    create=extend_schema(
        tags=["Attendance Records"],
        description=(
            "Record attendance for a session. Two modes depending on `method`:\n\n"
            "**GPS check-in** (`method=gps`, default — any authenticated member):\n"
            "- Provide `session_id`, `lat`, and `lng`.\n"
            "- `member` is always overridden server-side to the requesting user's own profile "
            "  (client-supplied `member_id` is ignored).\n"
            "- `distance_from_center_meters` is computed from the provided coordinates and "
            "  stored automatically.\n\n"
            "**Manual sign-in** (`method=manual` — assembly_admin or super_admin only):\n"
            "- Provide `session_id` and `member_id` (the member being signed in).\n"
            "- `recorded_by` is set server-side to the requesting admin.\n"
            "- Assembly admins can only sign in members within their own assembly."
        ),
    ),
    retrieve=extend_schema(tags=["Attendance Records"]),
    update=extend_schema(
        tags=["Attendance Records"],
        description="Update an attendance record. **Requires assembly_admin or super_admin role.**",
    ),
    partial_update=extend_schema(
        tags=["Attendance Records"],
        description="Partially update an attendance record. **Requires assembly_admin or super_admin role.**",
    ),
    destroy=extend_schema(
        tags=["Attendance Records"],
        description="Delete an attendance record. **Requires assembly_admin or super_admin role.**",
    ),
)
class AttendanceRecordViewSet(AssemblyScopedMixin, viewsets.ModelViewSet):
    """
    GPS check-in (method='gps'):
      - Any authenticated member.
      - `member` is always overridden to the requesting user's member profile.
      - `lat` and `lng` must be provided; `distance_from_center_meters` computed server-side.

    Manual entry (method='manual'):
      - Assembly admin or super_admin only.
      - `member_id` must be provided in the request body.
      - `recorded_by` is set server-side to the requesting admin.

    list/retrieve: all members scoped to their assembly.
    update/delete: assembly_admin or super_admin.
    """
    serializer_class = AttendanceRecordSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AttendanceRecord.objects.none()
        profile = self.get_requesting_profile()
        if profile is None:
            return AttendanceRecord.objects.all() if self.request.user.is_superuser else AttendanceRecord.objects.none()
        if profile.role == Member.ROLE_SUPER_ADMIN:
            qs = AttendanceRecord.objects.all()
        else:
            qs = AttendanceRecord.objects.filter(session__assembly=profile.assembly)

        # Filtered after scoping, never instead of it: a session id from another
        # assembly simply matches nothing here.
        session = (self.request.query_params.get("session") or "").strip()
        if session:
            try:
                qs = qs.filter(session_id=uuid.UUID(session))
            except ValueError:
                # A malformed id would otherwise reach the UUID column and 500.
                raise ValidationError({"session": ["Not a valid session id."]})
        day = _parse_date(self.request)
        if day:
            qs = qs.filter(session__opened_at__date=day)
        return qs

    def get_permissions(self):
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsAssemblyAdminOrSuperAdmin()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        profile = self.get_requesting_profile()
        validated = serializer.validated_data

        method = validated.get("method", AttendanceRecord.METHOD_GPS)
        lat = validated.pop("lat", None)
        lng = validated.pop("lng", None)
        session = validated["session"]

        # A closed session is a finished service. Without this, a member could
        # sign in to last Sunday from their sofa on Wednesday.
        if not session.is_active or session.closed_at:
            raise ValidationError({"session_id": ["This attendance session has closed."]})

        if method == AttendanceRecord.METHOD_MANUAL:
            if profile.role not in (Member.ROLE_ASSEMBLY_ADMIN, Member.ROLE_SUPER_ADMIN):
                raise PermissionDenied("Only admins can create manual attendance records.")
            target_member = validated.get("member")
            if target_member is None:
                raise ValidationError({"member_id": "member_id is required for manual attendance entries."})
            if (
                profile.role == Member.ROLE_ASSEMBLY_ADMIN
                and target_member.assembly != profile.assembly
            ):
                raise PermissionDenied("Cannot record attendance for a member outside your assembly.")
            if AttendanceRecord.objects.filter(session=session, member=target_member).exists():
                raise ValidationError(
                    {"member_id": [f"{target_member.full_name} is already signed in for this service."]}
                )
            record = serializer.save(recorded_by=profile)

            # An override is a record, not a shortcut: who signed, for whom, and
            # the reason they gave.
            record_activity(
                actor=profile,
                action="Signed attendance for a member",
                affected_record=(
                    f"{target_member.full_name} ({target_member.member_id})"
                    + (f" — {record.note}" if record.note else "")
                ),
                severity=ActivityLog.SEVERITY_WARNING,
                assembly=target_member.assembly,
            )
        else:
            # GPS — always set member to the requesting user
            if AttendanceRecord.objects.filter(session=session, member=profile).exists():
                raise ValidationError({"session_id": ["You have already signed in for this service."]})

            # `validate` guarantees both are present for a GPS mark.
            distance = haversine_distance(
                lat, lng,
                session.geofence_center_lat, session.geofence_center_lng,
            )

            # The whole point of the geofence. The distance used to be computed,
            # stored, and never compared — so a mark from across town was
            # accepted exactly like one from the front pew.
            radius = session.geofence_radius_meters
            if radius and distance > radius:
                raise ValidationError({
                    "location": [
                        f"You are about {round(distance)}m from the service. "
                        f"Attendance can only be signed within {radius}m."
                    ]
                })

            serializer.save(member=profile, distance_from_center_meters=distance)


@extend_schema_view(
    list=extend_schema(
        tags=["Attendance Stats"],
        description=(
            "List cached attendance statistics, scoped to the requesting member's assembly. "
            "Used for dashboard score display and the attendance leaderboard. "
            "Stats are recomputed by a server-side signal when attendance records change — "
            "this endpoint is read-only."
        ),
    ),
    retrieve=extend_schema(tags=["Attendance Stats"]),
)
class MemberAttendanceStatViewSet(AssemblyScopedMixin, viewsets.ReadOnlyModelViewSet):
    """
    Read-only. Stats are maintained by signals, not written via the API.
    Scoped: members see their assembly's stats (for leaderboard display).
    """
    serializer_class = MemberAttendanceStatSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MemberAttendanceStat.objects.none()
        profile = self.get_requesting_profile()
        if profile is None:
            return MemberAttendanceStat.objects.all() if self.request.user.is_superuser else MemberAttendanceStat.objects.none()
        if profile.role == Member.ROLE_SUPER_ADMIN:
            return MemberAttendanceStat.objects.all()
        return MemberAttendanceStat.objects.filter(assembly=profile.assembly)
