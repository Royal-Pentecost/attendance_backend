from django.contrib import admin

from .models import SpiritualMilestone


@admin.register(SpiritualMilestone)
class SpiritualMilestoneAdmin(admin.ModelAdmin):
    list_display = ["member", "milestone_type", "date_occurred", "verified_by"]
    list_filter = ["milestone_type"]
    search_fields = ["member__full_name", "member__member_id", "notes"]
    readonly_fields = ["id", "created_at", "updated_at"]
    list_select_related = ["member", "verified_by"]
    # member, verified_by → Member (unbounded) → raw_id widget
    raw_id_fields = ["member", "verified_by"]
