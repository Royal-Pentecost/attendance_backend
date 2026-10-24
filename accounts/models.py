"""
accounts/models.py

Covers: custom phone-based User, Assembly, Member profile, Elder profile,
Elder office hours, Day-Born groups, OTP verification (Moolre-backed),
and CSV import batch tracking.

Requires:
    AUTH_USER_MODEL = "accounts.User"   # in settings.py
    core.models.BaseModel               # shared UUID + timestamp base
"""
import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.auth.base_user import BaseUserManager
from django.db import models

from core.models import BaseModel


# ---------------------------------------------------------------------------
# Custom auth user — phone number is the identity, not email/username.
# ---------------------------------------------------------------------------

class UserManager(BaseUserManager):
    def create_user(self, phone_number, password=None, **extra_fields):
        if not phone_number:
            raise ValueError("Phone number is required")
        user = self.model(phone_number=phone_number, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(phone_number, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Auth identity only. Profile data (name, assembly, role, etc.) lives on
    Member. This split keeps auth concerns (OTP, login) separate from
    church-domain concerns (membership, assembly, role).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_number = models.CharField(max_length=20, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # Django admin access only
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.phone_number


# ---------------------------------------------------------------------------
# OTP verification — generated server-side, delivered via Moolre.
# ---------------------------------------------------------------------------

class OTPVerification(BaseModel):
    """
    One row per OTP attempt. Store a hash of the code, never the plaintext.
    `purpose` allows reuse of this model for future flows (e.g. phone change)
    without a new table.
    """

    PURPOSE_LOGIN = "login"
    PURPOSE_PHONE_CHANGE = "phone_change"
    PURPOSE_CHOICES = [
        (PURPOSE_LOGIN, "Login"),
        (PURPOSE_PHONE_CHANGE, "Phone Change"),
    ]

    phone_number = models.CharField(max_length=20, db_index=True)
    code_hash = models.CharField(max_length=128)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES, default=PURPOSE_LOGIN)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    moolre_reference = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"OTP for {self.phone_number} ({self.purpose})"


# ---------------------------------------------------------------------------
# Assembly — first-class, fully functional per-assembly entity (v1 requirement).
# ---------------------------------------------------------------------------

class Assembly(BaseModel):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True)
    district = models.CharField(max_length=150)
    founded_year = models.PositiveIntegerField(blank=True, null=True)
    is_active = models.BooleanField(
        default=False,
        help_text="Whether this assembly is live/selectable, vs 'coming soon'.",
    )
    banner_image = models.ImageField(upload_to="assemblies/banners/", blank=True, null=True)

    # Geofence — current/live configuration. Sessions snapshot this at
    # open-time so historical sessions aren't affected by later edits.
    geofence_center_lat = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    geofence_center_lng = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    geofence_radius_meters = models.PositiveIntegerField(blank=True, null=True)

    presiding_elder = models.ForeignKey(
        "accounts.Elder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="presiding_over_assemblies",
    )

    class Meta:
        verbose_name_plural = "Assemblies"
        ordering = ["name"]

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# Day-Born groups — drive real permissions/notifications, not just display.
# ---------------------------------------------------------------------------

class DayBornGroup(BaseModel):
    WEEKDAY_CHOICES = [
        (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"),
        (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
    ]

    # Traditional Akan day-names, for reference/display (e.g. "Wukuada").
    name = models.CharField(max_length=50)
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES)
    assembly = models.ForeignKey(Assembly, on_delete=models.CASCADE, related_name="day_born_groups")
    meeting_time = models.TimeField(blank=True, null=True)
    meeting_location = models.CharField(max_length=150, blank=True)

    # Leadership of a day-born group is a MEMBER-level assignment,
    # not restricted to ordained elders.
    leader = models.ForeignKey(
        "accounts.Member",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_day_born_groups",
    )

    class Meta:
        unique_together = [("assembly", "weekday")]
        ordering = ["assembly", "weekday"]

    def __str__(self):
        return f"{self.name} ({self.get_weekday_display()}) — {self.assembly}"


# ---------------------------------------------------------------------------
# Member — the church-domain profile. Role lives here, not on User.
# ---------------------------------------------------------------------------

class Member(BaseModel):
    ROLE_MEMBER = "member"
    ROLE_ASSEMBLY_ADMIN = "assembly_admin"
    ROLE_SUPER_ADMIN = "super_admin"
    ROLE_CHOICES = [
        (ROLE_MEMBER, "Member"),
        (ROLE_ASSEMBLY_ADMIN, "Assembly Admin"),
        (ROLE_SUPER_ADMIN, "Super Admin"),
    ]

    # A member is a person on the roll; a user is a login. Most of the
    # congregation has no phone number on file yet, and since the phone *is* the
    # login identity, those members exist without a user until a number is
    # collected. Everything that reads a profile goes User -> member_profile, so
    # a member with no user is simply never the one making a request.
    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="member_profile",
        null=True,
        blank=True,
    )
    member_id = models.CharField(
        max_length=20, unique=True, db_index=True,
        help_text="Display ID, e.g. MEM-0042. Generated on creation.",
    )
    full_name = models.CharField(max_length=150)
    date_of_birth = models.DateField(blank=True, null=True)

    # Needed to address a member correctly — "Mr" or "Mrs" before the surname,
    # unless they hold an office, in which case the office wins. Blank is a real
    # answer here: the roll arrived with two members whose sex was not recorded,
    # and guessing it from a first name would be worse than leaving it off.
    SEX_MALE = "M"
    SEX_FEMALE = "F"
    SEX_CHOICES = [(SEX_MALE, "Male"), (SEX_FEMALE, "Female")]
    sex = models.CharField(max_length=1, choices=SEX_CHOICES, blank=True)
    # Where they live, as the church records it ("Ayigya Zongo", "KNUST") — how
    # an elder finds a member to visit. Free text; the roll is not consistent.
    residence = models.CharField(max_length=150, blank=True)
    # Ministries and departments they serve in: ["Royal Youth Choir",
    # "Royal Drama Troupe"]. A list, because one member often serves in two.
    church_roles = models.JSONField(default=list, blank=True)
    profile_photo = models.ImageField(upload_to="members/photos/", blank=True, null=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_MEMBER)

    assembly = models.ForeignKey(
        Assembly, on_delete=models.SET_NULL, null=True, blank=True, related_name="members",
    )
    day_born_group = models.ForeignKey(
        DayBornGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="members",
    )
    assigned_elder = models.ForeignKey(
        "accounts.Elder", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_members",
        help_text="Elder responsible for this member's counseling/milestones.",
    )

    is_profile_complete = models.BooleanField(default=False)
    bible_study_language = models.CharField(
        max_length=10, choices=[("en", "English"), ("tw", "Twi")], default="en",
    )
    dark_mode_enabled = models.BooleanField(default=False)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} ({self.member_id})"

    def save(self, *args, **kwargs):
        # Auto-assign day_born_group from date_of_birth if not manually set.
        # (Actual weekday-from-DOB calculation to be implemented in a
        # service/signal, not here — keeping model logic minimal.)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Elder — profile extension of Member, not a separate identity.
# ---------------------------------------------------------------------------

class Elder(BaseModel):
    OFFICE_PRESIDING = "presiding"
    OFFICE_COUNSELING = "counseling"
    OFFICE_OTHER = "other"
    OFFICE_CHOICES = [
        (OFFICE_PRESIDING, "Presiding Elder"),
        (OFFICE_COUNSELING, "Counseling Elder"),
        (OFFICE_OTHER, "Other"),
    ]

    member = models.OneToOneField(Member, on_delete=models.CASCADE, related_name="elder_profile")
    office = models.CharField(max_length=20, choices=OFFICE_CHOICES, default=OFFICE_OTHER)
    title = models.CharField(max_length=100, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True)
    whatsapp_number = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["member__full_name"]

    def __str__(self):
        return f"{self.get_office_display()}: {self.member.full_name}"


class ElderOfficeHours(BaseModel):
    """
    Separate rows per weekday so 'Tuesdays & Thursdays, 10:00 AM – 2:00 PM'
    is queryable (e.g. 'is this elder available today') rather than a
    free-text field.
    """
    WEEKDAY_CHOICES = DayBornGroup.WEEKDAY_CHOICES

    elder = models.ForeignKey(Elder, on_delete=models.CASCADE, related_name="office_hours")
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["weekday", "start_time"]

    def __str__(self):
        return f"{self.elder} — {self.get_weekday_display()} {self.start_time}-{self.end_time}"


# ---------------------------------------------------------------------------
# CSV import audit trail.
# ---------------------------------------------------------------------------

class ImportBatch(BaseModel):
    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETE = "complete"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_COMPLETE, "Complete"),
        (STATUS_FAILED, "Failed"),
    ]

    uploaded_by = models.ForeignKey(Member, on_delete=models.SET_NULL, null=True, related_name="import_batches")
    assembly = models.ForeignKey(Assembly, on_delete=models.CASCADE, related_name="import_batches")
    source_file = models.FileField(upload_to="imports/member_batches/")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    row_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    error_log = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Import {self.id} by {self.uploaded_by} ({self.status})"
