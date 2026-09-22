from django.contrib import admin

from .models import AttendanceRecord, AttendanceSession, MemberAttendanceStat


# ── AttendanceSession ──────────────────────────────────────────────────────────

@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ["service_name", "assembly", "is_active", "opened_at", "closed_at", "opened_by"]
    list_filter = ["is_active", "assembly"]
    search_fields = ["service_name"]
    readonly_fields = ["id", "created_at", "updated_at", "opened_at"]
    list_select_related = ["assembly", "opened_by"]
    # opened_by → Member (unbounded) → raw_id widget
    # opened_at is auto_now_add — included in readonly_fields so it shows in the change form
    raw_id_fields = ["opened_by"]


# ── AttendanceRecord ───────────────────────────────────────────────────────────

@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ["member", "session", "method", "marked_at", "is_first_timer", "recorded_by"]
    list_filter = ["method", "is_first_timer", "session__assembly"]
    search_fields = ["member__full_name", "member__member_id"]
    readonly_fields = ["id", "created_at", "updated_at", "marked_at"]
    list_select_related = ["member", "session__assembly", "recorded_by"]
    # member, recorded_by → Member (unbounded) → raw_id widget
    # session → AttendanceSession (grows with every service) → raw_id widget
    #   (extra beyond the Member/User rule — a plain dropdown of thousands of sessions
    #    would be unusable; calling it out explicitly)
    raw_id_fields = ["member", "session", "recorded_by"]


# ── MemberAttendanceStat ───────────────────────────────────────────────────────

@admin.register(MemberAttendanceStat)
class MemberAttendanceStatAdmin(admin.ModelAdmin):
    list_display = [
        "member", "assembly", "year",
        "sessions_attended", "sessions_possible", "annual_score_percent",
        "current_streak_weeks",
    ]
    list_filter = ["assembly", "year"]
    search_fields = ["member__full_name", "member__member_id"]
    readonly_fields = ["id", "created_at", "updated_at"]
    list_select_related = ["member", "assembly"]
    # member → Member (unbounded) → raw_id widget
    # last_attended_session → AttendanceSession (grows unboundedly) → raw_id widget
    raw_id_fields = ["member", "last_attended_session"]
