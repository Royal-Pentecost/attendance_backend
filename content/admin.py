from django.contrib import admin

from .models import BibleStudyWeek, Event, Notification, NotificationRead, WeeklySchedule


# ── WeeklySchedule ─────────────────────────────────────────────────────────────

@admin.register(WeeklySchedule)
class WeeklyScheduleAdmin(admin.ModelAdmin):
    list_display = ["name", "assembly", "start_weekday", "end_weekday", "time", "location", "is_active"]
    list_filter = ["is_active", "assembly", "start_weekday"]
    search_fields = ["name", "location"]
    readonly_fields = ["id", "created_at", "updated_at"]
    list_select_related = ["assembly"]


# ── BibleStudyWeek ─────────────────────────────────────────────────────────────

@admin.register(BibleStudyWeek)
class BibleStudyWeekAdmin(admin.ModelAdmin):
    list_display = ["week_number", "title", "study_date", "is_published", "assembly", "theme"]
    list_filter = ["is_published", "assembly"]
    search_fields = ["title", "theme", "scripture_reference"]
    readonly_fields = ["id", "created_at", "updated_at"]
    list_select_related = ["assembly"]
    # assembly is nullable (null = district-wide) — blank option shown by default in dropdown


# ── Event ──────────────────────────────────────────────────────────────────────

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "event_date", "scope", "assembly", "created_by"]
    list_filter = ["scope", "assembly"]
    search_fields = ["title", "description"]
    readonly_fields = ["id", "created_at", "updated_at"]
    list_select_related = ["assembly", "created_by"]
    # created_by → Member (unbounded) → raw_id widget
    raw_id_fields = ["created_by"]


# ── Notification ───────────────────────────────────────────────────────────────
# NotificationRead is intentionally NOT inlined here.
# Reason: a broadcast to "all" or "assembly" can produce hundreds of read receipts.
# Loading all of them inline every time a notification detail is opened would be
# slow and unmanageable. Use the standalone NotificationReadAdmin below, filtered
# by notification, to inspect receipts for a specific notification.

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["title", "notification_type", "audience_type", "assembly", "created_at"]
    list_filter = ["notification_type", "audience_type", "assembly"]
    search_fields = ["title", "body"]
    readonly_fields = ["id", "created_at", "updated_at"]
    list_select_related = ["assembly", "day_born_group"]
    # member → Member (unbounded) → raw_id widget (nullable; only set for AUDIENCE_MEMBER)
    # day_born_group → DayBornGroup (small) → regular dropdown
    # assembly       → Assembly    (small) → regular dropdown
    raw_id_fields = ["member"]


# ── NotificationRead ───────────────────────────────────────────────────────────

@admin.register(NotificationRead)
class NotificationReadAdmin(admin.ModelAdmin):
    list_display = ["notification", "member", "read_at", "created_at"]
    list_filter = ["notification__notification_type", "notification__audience_type"]
    search_fields = ["member__full_name", "member__member_id", "notification__title"]
    readonly_fields = ["id", "created_at", "updated_at"]
    list_select_related = ["member", "notification"]
    # member → Member (unbounded) → raw_id widget
    # notification → Notification (could be many) → raw_id widget
    raw_id_fields = ["member", "notification"]
