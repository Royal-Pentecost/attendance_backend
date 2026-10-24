"""
content/models.py

Covers: recurring weekly service schedule, Bible study curriculum, events,
and notifications with audience targeting (all / assembly / day-born group /
single member) plus per-member read tracking.
"""
from django.db import models

from core.models import BaseModel
from accounts.models import Assembly, DayBornGroup, Member


class WeeklySchedule(BaseModel):
    """Recurring services like 'Youth Service', 'Morning Devotion'."""

    WEEKDAY_CHOICES = DayBornGroup.WEEKDAY_CHOICES

    assembly = models.ForeignKey(Assembly, on_delete=models.CASCADE, related_name="weekly_schedules")
    name = models.CharField(max_length=150)
    start_weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES)
    end_weekday = models.PositiveSmallIntegerField(
        choices=WEEKDAY_CHOICES, blank=True, null=True,
        help_text="Set for multi-day recurrences, e.g. 'Mon–Wed'. Leave blank for single-day.",
    )
    time = models.TimeField()
    location = models.CharField(max_length=150, blank=True)
    banner_image = models.ImageField(upload_to="schedules/banners/", blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["assembly", "start_weekday", "time"]

    def __str__(self):
        return f"{self.name} — {self.assembly}"


class BibleStudyWeek(BaseModel):
    """
    Curriculum content — treated as district-wide by default (assembly=null),
    since the study guide appeared shared across the district. Per-assembly
    override is available via the optional FK if that assumption is wrong.
    """

    assembly = models.ForeignKey(
        Assembly, on_delete=models.CASCADE, null=True, blank=True,
        related_name="bible_study_weeks",
        help_text="Leave blank for district-wide content shared by all assemblies.",
    )
    theme = models.CharField(max_length=150, help_text="e.g. 'Growing in Grace & Knowledge'")
    week_number = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=200, help_text="e.g. 'The Foundation of Faith'")
    scripture_reference = models.CharField(max_length=100, help_text="e.g. 'Hebrews 11:1-6'")
    page_range = models.CharField(max_length=50, blank=True, help_text="e.g. 'pp. 1-18'")
    study_date = models.DateField()
    pdf_file = models.FileField(upload_to="bible_study/pdfs/", blank=True, null=True)
    is_published = models.BooleanField(default=False)

    class Meta:
        ordering = ["study_date"]
        unique_together = [("assembly", "week_number", "study_date")]

    def __str__(self):
        return f"Week {self.week_number}: {self.title}"


class Event(BaseModel):
    SCOPE_ASSEMBLY = "assembly"
    SCOPE_DISTRICT = "district"
    SCOPE_CHOICES = [
        (SCOPE_ASSEMBLY, "Assembly"),
        (SCOPE_DISTRICT, "District"),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    event_date = models.DateField()
    # The photograph an admin attaches when publishing. Without somewhere to
    # put it, the picture stayed on the publishing phone and every member saw
    # the app's stock photo instead. Schedules already had `banner_image`.
    cover_image = models.ImageField(upload_to="events/covers/", blank=True, null=True)
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default=SCOPE_ASSEMBLY)
    assembly = models.ForeignKey(
        Assembly, on_delete=models.CASCADE, null=True, blank=True,
        related_name="events", help_text="Required if scope is 'assembly'; leave blank if 'district'.",
    )
    created_by = models.ForeignKey(Member, on_delete=models.SET_NULL, null=True, related_name="created_events")

    class Meta:
        ordering = ["event_date"]

    def __str__(self):
        return f"{self.title} ({self.event_date})"


class Notification(BaseModel):
    """
    A single broadcast notification. Audience is determined by which of the
    scoped FKs is set — exactly one of assembly/day_born_group/member should
    be populated for AUDIENCE_ASSEMBLY/GROUP/MEMBER, none for AUDIENCE_ALL.
    Per-member read state lives in NotificationRead, not here, since one
    Notification can target many members.
    """

    TYPE_SESSION_OPEN = "session_open"
    TYPE_EVENT = "event"
    TYPE_BIBLE_STUDY = "bible_study"
    TYPE_STREAK = "streak"
    TYPE_ELDER_AVAILABILITY = "elder_availability"
    TYPE_SYSTEM = "system"
    TYPE_CHOICES = [
        (TYPE_SESSION_OPEN, "Attendance Session Open"),
        (TYPE_EVENT, "Event"),
        (TYPE_BIBLE_STUDY, "Bible Study"),
        (TYPE_STREAK, "Streak Milestone"),
        (TYPE_ELDER_AVAILABILITY, "Elder Availability"),
        (TYPE_SYSTEM, "System"),
    ]

    AUDIENCE_ALL = "all"
    AUDIENCE_ASSEMBLY = "assembly"
    AUDIENCE_DAY_BORN_GROUP = "day_born_group"
    AUDIENCE_MEMBER = "member"
    AUDIENCE_CHOICES = [
        (AUDIENCE_ALL, "All Members"),
        (AUDIENCE_ASSEMBLY, "Single Assembly"),
        (AUDIENCE_DAY_BORN_GROUP, "Single Day-Born Group"),
        (AUDIENCE_MEMBER, "Single Member"),
    ]

    title = models.CharField(max_length=200)
    body = models.TextField()
    notification_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    audience_type = models.CharField(max_length=20, choices=AUDIENCE_CHOICES)

    assembly = models.ForeignKey(Assembly, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications")
    day_born_group = models.ForeignKey(DayBornGroup, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, null=True, blank=True, related_name="direct_notifications")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class NotificationRead(BaseModel):
    """Per-member read state for a (possibly broadcast) Notification."""

    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="read_receipts")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="notification_reads")
    read_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        unique_together = [("notification", "member")]

    def __str__(self):
        status = "read" if self.read_at else "unread"
        return f"{self.notification} — {self.member} ({status})"


class BibleStudyTranslation(BaseModel):
    """
    One week's study written out in one language.

    Kept separate from `BibleStudyWeek` for two reasons. The week describes a
    pamphlet — which study, which scripture, which pages — and that is true
    whatever language it is read in. And a study is publishable the moment those
    facts are known: the office should not have to type out aims and questions
    in two languages before the congregation can be told what this Sunday is
    about.

    So this is optional, and so is each language. A week with no translation
    still shows its title, scripture and page range; one with English only shows
    English to everybody; one with both follows the member's own
    `bible_study_language`.
    """

    LANG_EN = "en"
    LANG_TW = "tw"
    LANG_CHOICES = [(LANG_EN, "English"), (LANG_TW, "Twi")]

    week = models.ForeignKey(
        BibleStudyWeek, on_delete=models.CASCADE, related_name="translations",
    )
    language = models.CharField(max_length=5, choices=LANG_CHOICES)

    title = models.CharField(max_length=200, blank=True)
    # Lists, because the reader renders them as numbered points rather than a
    # paragraph. Stored as JSON so a question cannot be split by a stray newline.
    aims = models.JSONField(default=list, blank=True)
    questions = models.JSONField(default=list, blank=True)
    memory_verse = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["language"]
        constraints = [
            models.UniqueConstraint(
                fields=["week", "language"], name="one_translation_per_language",
            ),
        ]

    def __str__(self):
        return f"{self.week.title} [{self.language}]"
