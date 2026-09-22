from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    Assembly,
    DayBornGroup,
    Elder,
    ElderOfficeHours,
    ImportBatch,
    Member,
    OTPVerification,
    User,
)


# ── Inline: ElderOfficeHours under Elder ───────────────────────────────────────

class ElderOfficeHoursInline(admin.TabularInline):
    model = ElderOfficeHours
    extra = 0
    fields = ("weekday", "start_time", "end_time")
    # id/created_at/updated_at omitted from the inline to keep it compact;
    # they are visible in the standalone ElderOfficeHoursAdmin below.


# ── User ───────────────────────────────────────────────────────────────────────
# Most user-facing management (name, assembly, role, photo, etc.) should happen
# via the Member admin below. This view is for auth/permissions management only.

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["phone_number"]
    list_display = ["phone_number", "is_active", "is_staff", "is_superuser", "date_joined"]
    list_filter = ["is_active", "is_staff", "is_superuser"]
    search_fields = ["phone_number"]
    readonly_fields = ["id", "date_joined", "last_login"]

    fieldsets = (
        (None, {"fields": ("id", "phone_number", "password")}),
        ("Status", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Permissions", {"fields": ("groups", "user_permissions")}),
        ("Timestamps", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("phone_number", "password1", "password2"),
        }),
    )
    filter_horizontal = ("groups", "user_permissions")


# ── Assembly ───────────────────────────────────────────────────────────────────

@admin.register(Assembly)
class AssemblyAdmin(admin.ModelAdmin):
    list_display = ["name", "district", "is_active", "founded_year", "presiding_elder"]
    list_filter = ["is_active", "district"]
    search_fields = ["name", "slug", "district"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["id", "created_at", "updated_at"]
    # presiding_elder → Elder (small, bounded by assembly count) → regular dropdown


# ── DayBornGroup ───────────────────────────────────────────────────────────────

@admin.register(DayBornGroup)
class DayBornGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "weekday", "assembly", "leader", "meeting_time", "meeting_location"]
    list_filter = ["assembly", "weekday"]
    search_fields = ["name", "meeting_location"]
    readonly_fields = ["id", "created_at", "updated_at"]
    list_select_related = ["assembly", "leader"]
    # leader → Member (unbounded) → raw_id widget
    raw_id_fields = ["leader"]


# ── Member ─────────────────────────────────────────────────────────────────────

@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ["full_name", "member_id", "role", "assembly", "is_profile_complete", "bible_study_language"]
    list_filter = ["role", "assembly", "is_profile_complete", "bible_study_language"]
    search_fields = ["full_name", "member_id", "user__phone_number"]
    readonly_fields = ["id", "created_at", "updated_at"]
    list_select_related = ["assembly", "user"]
    # user → User (unbounded) → raw_id widget
    raw_id_fields = ["user"]
    # assigned_elder → Elder   (small, bounded) → regular dropdown
    # day_born_group → DayBornGroup (≤7/assembly) → regular dropdown
    # assembly       → Assembly (small)            → regular dropdown


# ── Elder ──────────────────────────────────────────────────────────────────────

@admin.register(Elder)
class ElderAdmin(admin.ModelAdmin):
    list_display = ["__str__", "office", "contact_phone", "contact_email", "whatsapp_number"]
    list_filter = ["office"]
    search_fields = ["member__full_name", "contact_phone", "contact_email"]
    readonly_fields = ["id", "created_at", "updated_at"]
    list_select_related = ["member"]
    # member → Member (unbounded) → raw_id widget
    raw_id_fields = ["member"]
    inlines = [ElderOfficeHoursInline]


# ── ElderOfficeHours (standalone; also appears as inline under ElderAdmin) ─────

@admin.register(ElderOfficeHours)
class ElderOfficeHoursAdmin(admin.ModelAdmin):
    list_display = ["elder", "weekday", "start_time", "end_time"]
    list_filter = ["weekday"]
    search_fields = ["elder__member__full_name"]
    readonly_fields = ["id", "created_at", "updated_at"]
    list_select_related = ["elder__member"]


# ── OTPVerification ────────────────────────────────────────────────────────────

@admin.register(OTPVerification)
class OTPVerificationAdmin(admin.ModelAdmin):
    list_display = ["phone_number", "purpose", "is_used", "expires_at", "attempt_count", "created_at"]
    list_filter = ["purpose", "is_used"]
    search_fields = ["phone_number", "moolre_reference"]
    readonly_fields = ["id", "created_at", "updated_at", "code_hash"]
    # code_hash is a hashed credential — readonly prevents accidental editing.


# ── ImportBatch ────────────────────────────────────────────────────────────────

@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ["id", "assembly", "status", "row_count", "success_count", "error_count", "created_at"]
    list_filter = ["status", "assembly"]
    search_fields = ["uploaded_by__full_name", "uploaded_by__member_id"]
    readonly_fields = ["id", "created_at", "updated_at"]
    list_select_related = ["assembly", "uploaded_by"]
    # uploaded_by → Member (unbounded) → raw_id widget
    raw_id_fields = ["uploaded_by"]
