"""
accounts/serializers.py

Serializer write pattern used throughout this project:
  - FK reads:  a nested read-only mini-serializer (e.g. assembly = AssemblyMiniSerializer(read_only=True))
  - FK writes: a PrimaryKeyRelatedField with an `_id` suffix
                 (e.g. assembly_id = PrimaryKeyRelatedField(source='assembly', ...))
This keeps field names stable for consumers while allowing natural PK input for writes.
"""
import re

from django.db import transaction
from rest_framework import serializers

from .models import Assembly, DayBornGroup, Member, Elder, ElderOfficeHours, ImportBatch, User


def normalise_phone(raw: str) -> str:
    """
    Ghanaian local form, `0XXXXXXXXX`.

    Login compares the stored number to what was typed, character for character.
    A member saved as `+233537096725` is therefore told their account does not
    exist when they type their own number the way they know it — so every number
    entering the system is folded to one shape here, and nowhere else.

    Raises `ValidationError` on anything that is not a Ghanaian mobile number.
    """
    digits = re.sub(r"[^\d+]", "", (raw or "").strip())
    if digits.startswith("+233"):
        digits = "0" + digits[4:]
    elif digits.startswith("233") and len(digits) == 12:
        digits = "0" + digits[3:]

    if not re.fullmatch(r"0\d{9}", digits):
        raise serializers.ValidationError(
            "Enter a 10-digit Ghanaian number starting with 0, e.g. 024XXXXXXX."
        )
    return digits


# ---------------------------------------------------------------------------
# Mini / nested display serializers (read-only, used inside other serializers)
# ---------------------------------------------------------------------------

class AssemblyMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assembly
        fields = ["id", "name", "slug"]


class DayBornGroupMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = DayBornGroup
        fields = ["id", "name", "weekday"]


class MemberMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Member
        fields = ["id", "full_name", "member_id"]


class ElderMiniSerializer(serializers.ModelSerializer):
    member = MemberMiniSerializer(read_only=True)

    class Meta:
        model = Elder
        fields = ["id", "office", "title", "member"]


# ---------------------------------------------------------------------------
# Full serializers
# ---------------------------------------------------------------------------

class AssemblySerializer(serializers.ModelSerializer):
    presiding_elder = ElderMiniSerializer(read_only=True)
    presiding_elder_id = serializers.PrimaryKeyRelatedField(
        source="presiding_elder",
        queryset=Elder.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )

    class Meta:
        model = Assembly
        fields = [
            "id", "name", "slug", "district", "founded_year", "is_active",
            "banner_image",
            "geofence_center_lat", "geofence_center_lng", "geofence_radius_meters",
            "presiding_elder", "presiding_elder_id",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class DayBornGroupSerializer(serializers.ModelSerializer):
    assembly = AssemblyMiniSerializer(read_only=True)
    assembly_id = serializers.PrimaryKeyRelatedField(
        source="assembly",
        queryset=Assembly.objects.all(),
        write_only=True,
    )
    leader = MemberMiniSerializer(read_only=True)
    leader_id = serializers.PrimaryKeyRelatedField(
        source="leader",
        queryset=Member.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )

    class Meta:
        model = DayBornGroup
        fields = [
            "id", "name", "weekday", "assembly", "assembly_id",
            "meeting_time", "meeting_location", "leader", "leader_id",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class MemberSerializer(serializers.ModelSerializer):
    """
    General-purpose read / limited-update serializer for Member.
    `role` and `user` are intentionally read-only here — role changes must go
    through the Django admin or a future dedicated endpoint; this prevents
    members from escalating their own roles via a self-update PATCH.
    Use MemberCreateSerializer for admin member creation.
    """
    assembly = AssemblyMiniSerializer(read_only=True)
    assembly_id = serializers.PrimaryKeyRelatedField(
        source="assembly",
        queryset=Assembly.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )
    day_born_group = DayBornGroupMiniSerializer(read_only=True)
    day_born_group_id = serializers.PrimaryKeyRelatedField(
        source="day_born_group",
        queryset=DayBornGroup.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )
    assigned_elder = ElderMiniSerializer(read_only=True)
    assigned_elder_id = serializers.PrimaryKeyRelatedField(
        source="assigned_elder",
        queryset=Elder.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )
    # Lives on the User, shown and corrected here. Members change SIM, and the
    # roll arrived with 229 people who have no number yet — both are corrections
    # an admin has to be able to make without opening the Django admin.
    # Blank clears it, which removes the login but keeps the person on the roll.
    #
    # Not a dotted `source`: most of the roll has no user at all, and DRF reading
    # `user.phone_number` through a null raises rather than returning nothing.
    phone_number = serializers.CharField(required=False, allow_blank=True, max_length=20)

    class Meta:
        model = Member
        fields = [
            "id", "member_id", "full_name", "phone_number",
            "date_of_birth", "sex", "residence", "church_roles", "marital_status", "profile_photo",
            "role",
            "assembly", "assembly_id",
            "day_born_group", "day_born_group_id",
            "assigned_elder", "assigned_elder_id",
            "is_profile_complete", "bible_study_language", "dark_mode_enabled",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "member_id", "role", "created_at", "updated_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["phone_number"] = instance.user.phone_number if instance.user_id else ""
        return data

    def validate_phone_number(self, value):
        if not (value or "").strip():
            return ""  # Deliberate: clearing the number is how a login is removed.
        digits = normalise_phone(value)
        taken = User.objects.filter(phone_number=digits)
        if self.instance and self.instance.user_id:
            taken = taken.exclude(pk=self.instance.user_id)
        if taken.exists():
            raise serializers.ValidationError("Another member already uses this phone number.")
        return digits

    def validate_church_roles(self, value):
        """
        A list of names, set by an admin.

        Members may correct their own record, and without this a member could
        appoint themselves to the choir committee or the church secretariat.
        """
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise serializers.ValidationError("Send a list of role names.")
        cleaned = [v.strip() for v in value if v.strip()]
        actor = getattr(getattr(self.context.get("request"), "user", None), "member_profile", None)
        is_admin = getattr(actor, "role", None) in (Member.ROLE_ASSEMBLY_ADMIN, Member.ROLE_SUPER_ADMIN)
        current = list(self.instance.church_roles) if self.instance else []
        if cleaned != current and not is_admin:
            raise serializers.ValidationError("Only an admin can change church roles.")
        return cleaned

    @transaction.atomic
    def update(self, instance, validated_data):
        # Popped before `super()`, or ModelSerializer sets a stray attribute on
        # Member that goes nowhere — the number would appear to save and be gone
        # on the next read.
        has_phone = "phone_number" in validated_data
        phone = validated_data.pop("phone_number", None)

        member = super().update(instance, validated_data)

        if has_phone:
            if phone:
                if member.user_id:
                    member.user.phone_number = phone
                    member.user.save(update_fields=["phone_number"])
                else:
                    member.user = User.objects.create_user(phone_number=phone)
                    member.save(update_fields=["user", "updated_at"])
            elif member.user_id:
                # Removing the number removes the login, but the person stays on
                # the roll — deleting the user would cascade the member away.
                user = member.user
                member.user = None
                member.save(update_fields=["user", "updated_at"])
                user.delete()

        return member


def next_member_id() -> str:
    """
    The next free `MEM-###`.

    The roll was imported with ids assigned by hand in a spreadsheet, so the
    sequence has gaps and the only safe answer is "one past the highest", not
    "one past the count". Reads the whole column because the ids are text —
    `MEM-99` sorts after `MEM-328` — so the database cannot order them for us.
    """
    highest = 0
    for existing in Member.objects.values_list("member_id", flat=True):
        found = re.fullmatch(r"MEM-(\d+)", (existing or "").strip().upper())
        if found:
            highest = max(highest, int(found.group(1)))
    return f"MEM-{highest + 1:03d}"


class MemberCreateSerializer(serializers.ModelSerializer):
    """
    Admin-only member creation serializer.

    Three things differ from `MemberSerializer`:

    - **`phone_number` creates the login.** A member is a person on the roll; a
      user is a login. Most of the congregation has neither, so the number is
      optional — but when an admin types one it has to become a `User`, or the
      field is collected on the form and silently discarded, and the new member
      can never sign in.
    - **`member_id` is generated when omitted.** Making an admin invent one by
      hand is how you get a duplicate-id 400 at the end of a long form.
    - **`role` is checked against the caller's own.** Creation is open to
      assembly admins, and a writable `role` let one of them create a
      `super_admin` and hand themselves the phone number for it. Promotion goes
      through `POST /members/{id}/set-role/`, which is super-admin only and
      writes an audit entry; this closes the back door around it.
    """
    # Write-only: the number is read back through `user`, not echoed here.
    phone_number = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=20,
        help_text="Creates the member's login. Leave blank for a member with no phone.",
    )
    assembly = AssemblyMiniSerializer(read_only=True)
    assembly_id = serializers.PrimaryKeyRelatedField(
        source="assembly",
        queryset=Assembly.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )
    day_born_group_id = serializers.PrimaryKeyRelatedField(
        source="day_born_group",
        queryset=DayBornGroup.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )
    assigned_elder_id = serializers.PrimaryKeyRelatedField(
        source="assigned_elder",
        queryset=Elder.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
    )

    class Meta:
        model = Member
        fields = [
            "id", "user", "phone_number", "member_id", "full_name",
            "date_of_birth", "sex", "residence", "church_roles", "marital_status", "profile_photo",
            "role",
            "assembly", "assembly_id",
            "day_born_group_id", "assigned_elder_id",
            "is_profile_complete", "bible_study_language", "dark_mode_enabled",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "user", "created_at", "updated_at"]
        extra_kwargs = {
            # Generated in `create` when the admin leaves it blank.
            "member_id": {"required": False},
        }

    def validate_phone_number(self, value):
        if not (value or "").strip():
            return ""  # Most of the roll has no number; that is not an error.
        digits = normalise_phone(value)
        if User.objects.filter(phone_number=digits).exists():
            raise serializers.ValidationError("A member already uses this phone number.")
        return digits

    def validate_member_id(self, value):
        wanted = (value or "").strip().upper()
        if wanted and Member.objects.filter(member_id__iexact=wanted).exists():
            raise serializers.ValidationError(f"{wanted} is already taken.")
        return wanted

    def validate_role(self, value):
        """
        Nobody creates a member more privileged than themselves.

        Without this an assembly admin can POST `role: "super_admin"` with a
        phone number they control and sign in with the keys to every assembly.
        """
        actor = getattr(self.context.get("request"), "user", None)
        profile = getattr(actor, "member_profile", None)
        if value != Member.ROLE_MEMBER and getattr(profile, "role", None) != Member.ROLE_SUPER_ADMIN:
            raise serializers.ValidationError(
                "Only a super admin may create an admin. Add the member, then promote them."
            )
        return value

    @transaction.atomic
    def create(self, validated_data):
        phone = validated_data.pop("phone_number", "")
        if not validated_data.get("member_id"):
            validated_data["member_id"] = next_member_id()

        # Atomic with the member: a login with no profile behind it would let
        # someone past the OTP screen and into an app that has nobody to show.
        if phone:
            validated_data["user"] = User.objects.create_user(phone_number=phone)

        return super().create(validated_data)


class ElderSerializer(serializers.ModelSerializer):
    member = MemberMiniSerializer(read_only=True)
    member_id = serializers.PrimaryKeyRelatedField(
        source="member",
        queryset=Member.objects.all(),
        write_only=True,
    )

    class Meta:
        model = Elder
        fields = [
            "id", "member", "member_id", "office", "title",
            "contact_phone", "contact_email", "whatsapp_number",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ElderOfficeHoursSerializer(serializers.ModelSerializer):
    elder = ElderMiniSerializer(read_only=True)
    elder_id = serializers.PrimaryKeyRelatedField(
        source="elder",
        queryset=Elder.objects.all(),
        write_only=True,
    )

    class Meta:
        model = ElderOfficeHours
        fields = [
            "id", "elder", "elder_id", "weekday", "start_time", "end_time",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ImportBatchSerializer(serializers.ModelSerializer):
    uploaded_by = MemberMiniSerializer(read_only=True)
    assembly = AssemblyMiniSerializer(read_only=True)
    assembly_id = serializers.PrimaryKeyRelatedField(
        source="assembly",
        queryset=Assembly.objects.all(),
        write_only=True,
    )

    class Meta:
        model = ImportBatch
        fields = [
            "id", "uploaded_by", "assembly", "assembly_id", "source_file",
            "status", "row_count", "success_count", "error_count", "error_log",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "uploaded_by", "status", "row_count",
            "success_count", "error_count", "error_log",
            "created_at", "updated_at",
        ]
