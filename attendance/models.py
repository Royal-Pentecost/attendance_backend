"""
attendance/models.py

Covers: attendance sessions, GPS + manual attendance records (with audit
trail), and cached per-member/per-year stats used for the dashboard score
and leaderboard.
"""
from django.db import models

from core.models import BaseModel
from accounts.models import Assembly, Member


class AttendanceSession(BaseModel):
    """
    One row per opened service. Geofence is SNAPSHOTTED from Assembly at
    open-time, so editing an assembly's geofence later doesn't retroactively
    change historical sessions.
    """

    assembly = models.ForeignKey(Assembly, on_delete=models.CASCADE, related_name="attendance_sessions")
    service_name = models.CharField(max_length=150, help_text="e.g. 'Sunday Divine Service'")
    opened_by = models.ForeignKey(Member, on_delete=models.SET_NULL, null=True, related_name="opened_sessions")
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    geofence_center_lat = models.DecimalField(max_digits=9, decimal_places=6)
    geofence_center_lng = models.DecimalField(max_digits=9, decimal_places=6)
    geofence_radius_meters = models.PositiveIntegerField()

    class Meta:
        ordering = ["-opened_at"]

    def __str__(self):
        return f"{self.service_name} @ {self.assembly} ({self.opened_at:%Y-%m-%d})"


class AttendanceRecord(BaseModel):
    METHOD_GPS = "gps"
    METHOD_MANUAL = "manual"
    METHOD_CHOICES = [
        (METHOD_GPS, "GPS Check-in"),
        (METHOD_MANUAL, "Manually Signed"),
    ]

    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE, related_name="records")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="attendance_records")
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default=METHOD_GPS)
    marked_at = models.DateTimeField(auto_now_add=True)
    distance_from_center_meters = models.PositiveIntegerField(
        blank=True, null=True, help_text="Populated for GPS check-ins only.",
    )
    is_first_timer = models.BooleanField(default=False)

    # Audit trail for manual entries — who signed this member in.
    recorded_by = models.ForeignKey(
        Member, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="recorded_attendance_for_others",
        help_text="Set only for manually-signed records; the admin/elder who signed the member in.",
    )
    note = models.TextField(blank=True)

    class Meta:
        unique_together = [("session", "member")]
        ordering = ["-marked_at"]

    def __str__(self):
        return f"{self.member} @ {self.session} ({self.method})"


class MemberAttendanceStat(BaseModel):
    """
    Cached/materialized stats, recomputed by `attendance.stats` (wired up in
    `attendance.signals`) whenever an AttendanceRecord is created or removed,
    or a session opens, closes or is deleted. Keeps the dashboard
    and leaderboard fast without aggregating raw records on every request.
    Partitioned by year so historical leaderboards remain meaningful.
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="attendance_stats")
    assembly = models.ForeignKey(Assembly, on_delete=models.CASCADE, related_name="member_attendance_stats")
    year = models.PositiveIntegerField()

    sessions_attended = models.PositiveIntegerField(default=0)
    sessions_possible = models.PositiveIntegerField(default=0)
    annual_score_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    # Consecutive Sunday services attended. Counted in Sundays that actually
    # had a service, so a Sunday with no session neither adds nor breaks it.
    current_streak_weeks = models.PositiveIntegerField(default=0)
    longest_streak_weeks = models.PositiveIntegerField(default=0)
    sundays_attended = models.PositiveIntegerField(default=0)
    sundays_possible = models.PositiveIntegerField(default=0)
    # Mean minutes between a session opening and this member's own GPS sign-in.
    # Manual entries are left out: their time is when an admin typed them in,
    # not when the member arrived. Null until they have signed in themselves.
    average_arrival_minutes = models.FloatField(blank=True, null=True)
    last_attended_session = models.ForeignKey(
        AttendanceSession, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta:
        unique_together = [("member", "year")]
        ordering = ["-annual_score_percent"]

    def __str__(self):
        return f"{self.member} — {self.year}: {self.annual_score_percent}%"
