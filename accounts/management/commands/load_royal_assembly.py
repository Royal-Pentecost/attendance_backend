"""Load the Royal Assembly membership roll from the church's spreadsheet.

Run it twice and nothing is duplicated — members are matched on their MEM-ID, so
this doubles as the way to re-apply the sheet after corrections.

    python manage.py load_royal_assembly "CHURCH OF PENTECOST ROYAL ASS DATA.xlsx"
    python manage.py load_royal_assembly "...xlsx" --commit

Without --commit it reports what it *would* do and writes nothing.

The .xlsx is read with the standard library rather than openpyxl, so the command
has no dependency the server does not already have.
"""

from __future__ import annotations

import json
import re
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from accounts.models import Assembly, DayBornGroup, Elder, Member, User

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

ASSEMBLY_NAME = "Royal Assembly"
ASSEMBLY_DISTRICT = "Ayigya"

# Column positions in the sheet, zero-based. The header sits on row 4.
COL = {
    "member_id": 0, "first": 1, "middle": 2, "last": 3, "sex": 4,
    "dob": 5, "residence": 6, "day_born": 7, "phone": 8,
    "title": 9, "church_roles": 10, "app_role": 11,
}
FIRST_DATA_ROW = 5

# Monday = 0 … Sunday = 6, matching DayBornGroup.WEEKDAY_CHOICES.
WEEKDAY = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

# The Akan name each day-born group is known by.
AKAN = {
    0: "Dwowda", 1: "Benada", 2: "Wukuda", 3: "Yawda",
    4: "Fida", 5: "Memeneda", 6: "Kwasida",
}

APP_ROLE = {
    "member": Member.ROLE_MEMBER,
    "admin": Member.ROLE_ASSEMBLY_ADMIN,
    "super-admin": Member.ROLE_SUPER_ADMIN,
    "super admin": Member.ROLE_SUPER_ADMIN,
    "superadmin": Member.ROLE_SUPER_ADMIN,
}

# As typed in the sheet -> as it should read. The sheet has some spelling slips.
TITLE_FIXES = {
    "decon": "Deacon",
    "deconess": "Deaconess",
    "preciding elder": "Presiding Elder",
    "member": "Member",
    "elder": "Elder",
    "deacon": "Deacon",
    "deaconess": "Deaconess",
    "presiding elder": "Presiding Elder",
}

# Anyone holding one of these is a church leader, not an ordinary member.
LEADER_TITLES = {"Elder", "Deacon", "Deaconess", "Presiding Elder"}

# Corrections agreed with the church office. Keyed on MEM-ID so re-running the
# command after the sheet is fixed simply makes these no-ops.
# Corrections agreed with the church office, keyed on MEM-ID.
#
# Only the *clearings* live here, because a cleared number is not personal data.
# Real numbers are never committed — this repository is public, and a member's
# phone number has no business in source control. Supply those through
# `--corrections corrections.json`, a file of {"MEM-196": "0XXXXXXXXX"} that
# .gitignore keeps out of the repository.
PHONE_OVERRIDES: dict[str, str | None] = {
    # One number was recorded against two people; it is cleared on both until
    # the office confirms whose it is.
    "MEM-048": None,
    "MEM-311": None,
}


# ─── Spreadsheet reading ─────────────────────────────────────────────────────

def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_sheet(path: str) -> list[dict[int, str]]:
    """Returns one dict of {column index: text} per non-empty row."""
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise CommandError(f"Could not open {path}: {exc}") from exc

    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.iter(f"{NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))

    rows = []
    root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    for row in root.iter(f"{NS}row"):
        if int(row.get("r")) < FIRST_DATA_ROW:
            continue
        cells: dict[int, str] = {}
        for c in row.iter(f"{NS}c"):
            v = c.find(f"{NS}v")
            if c.get("t") == "s" and v is not None:
                text = shared[int(v.text)]
            elif c.get("t") == "inlineStr":
                text = "".join(t.text or "" for t in c.iter(f"{NS}t"))
            elif v is not None:
                text = v.text
            else:
                continue
            text = (text or "").strip()
            if text:
                cells[_col_index(c.get("r"))] = text
        if cells:
            rows.append(cells)
    return rows


# ─── Field cleaning ──────────────────────────────────────────────────────────

def clean_phone(raw: str) -> str | None:
    """
    Ghanaian local form, 0XXXXXXXXX.

    The server stores whatever it is given and compares it exactly at login, so
    every number has to reach the database in one single form or the member can
    never sign in.
    """
    if not raw:
        return None
    digits = re.sub(r"[^0-9+]", "", raw)
    if digits.startswith("+233"):
        digits = "0" + digits[4:]
    elif digits.startswith("233") and len(digits) == 12:
        digits = "0" + digits[3:]
    return digits if re.fullmatch(r"0\d{9}", digits) else None


# Excel counts days from this date — its own calendar is off by one for 1900,
# which is why the epoch is the 30th and not the 31st.
EXCEL_EPOCH = date(1899, 12, 30)


def parse_dob(raw: str):
    """
    A birth date, or None when the sheet does not really hold one.

    Three forms appear in this file. Most are written DD/MM/YYYY, but a third of
    them were typed as real dates and so arrive as **Excel serial numbers** —
    reading those as text drops them silently, which is how 35 birthdays went
    missing on the first pass. The rest are partial (`00/00/1973`, `01/08/`,
    `27/01`): a year with no day, or a day with no year. Those stay None rather
    than being rounded to the first of January, because an invented birthday is
    worse than a blank one — the office can fill them in later.
    """
    if not raw:
        return None

    raw = raw.strip()

    if re.fullmatch(r"\d+(\.\d+)?", raw):
        serial = int(float(raw))
        # Guard against a stray number that is not a date at all.
        if not 1 <= serial <= 80000:
            return None
        return EXCEL_EPOCH + timedelta(days=serial)

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def full_name(row: dict[int, str]) -> str:
    parts = [row.get(COL["first"], ""), row.get(COL["middle"], ""), row.get(COL["last"], "")]
    return " ".join(p for p in parts if p).strip()


def clean_sex(raw: str) -> str:
    """The sheet writes M or F; anything else is treated as not recorded."""
    v = (raw or "").strip().upper()[:1]
    return v if v in ("M", "F") else ""


# Spellings in the sheet -> the name the church uses.
ROLE_NAMES = {
    "royal youth choir": "Royal Youth Choir",
    "royal drama troupe": "Royal Drama Troupe",
    "church secetary": "Church Secretary",
    "church secretary": "Church Secretary",
}


def clean_residence(raw: str) -> str:
    """'AYIGYA ZONGO' -> 'Ayigya Zongo'. KNUST and other initialisms stay upper."""
    text = " ".join((raw or "").split())
    if not text:
        return ""
    return " ".join(w if len(w) <= 5 and w.isupper() and w in {"KNUST", "CCC"} else w.capitalize() for w in text.split(" "))


def clean_roles(raw: str, residence: str) -> list[str]:
    """
    "Royal Youth choir, Royal Drama Troupe" -> ["Royal Youth Choir", "Royal Drama Troupe"].

    A value that is just the member's residence is a slip into the wrong column
    (MEM-068 has "AYIGYA" under roles and under residence), not a role.
    """
    roles = []
    for part in (raw or "").split(","):
        name = " ".join(part.split())
        if not name or name.lower() == (residence or "").strip().lower():
            continue
        name = ROLE_NAMES.get(name.lower(), name.title())
        if name not in roles:
            roles.append(name)
    return roles


def clean_title(raw: str) -> str:
    return TITLE_FIXES.get((raw or "").strip().lower(), (raw or "").strip() or "Member")


def clean_role(raw: str) -> str:
    """A blank App Role means an ordinary member."""
    return APP_ROLE.get((raw or "").strip().lower(), Member.ROLE_MEMBER)


# ─── The command ─────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Load the Royal Assembly roll from the church spreadsheet. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument("spreadsheet", help="Path to the .xlsx file")
        parser.add_argument(
            "--commit", action="store_true",
            help="Actually write. Without this the command only reports.",
        )
        parser.add_argument(
            "--details-only", action="store_true",
            help=(
                "Update only residence and church roles on members already loaded. "
                "Leaves names, phones, roles and everything corrected in the app alone."
            ),
        )
        parser.add_argument(
            "--corrections",
            help=(
                'JSON file of phone corrections, {"MEM-196": "0241234567"}. '
                "Kept out of the repository because it holds real numbers."
            ),
        )

    def handle(self, *args, **options):
        overrides = dict(PHONE_OVERRIDES)
        if options.get("corrections"):
            try:
                with open(options["corrections"], encoding="utf-8") as fh:
                    overrides.update(json.load(fh))
            except (OSError, ValueError) as exc:
                raise CommandError(f"Could not read corrections file: {exc}") from exc

        rows = read_sheet(options["spreadsheet"])
        if not rows:
            raise CommandError("No data rows found — is this the right sheet?")

        self.stdout.write(f"Read {len(rows)} rows.")

        # Everything happens in one transaction so a bad row cannot leave the
        # roll half-loaded; a dry run rolls the same work back.
        try:
            with transaction.atomic():
                stats = self._details(rows) if options["details_only"] else self._load(rows, overrides)
                if not options["commit"]:
                    raise _DryRun()
        except _DryRun:
            if options["details_only"]:
                self._report_details(stats, committed=False)
            else:
                self._report(stats, committed=False)
            self.stdout.write(self.style.WARNING("\nDry run — nothing was written. Re-run with --commit."))
            return

        if options["details_only"]:
            self._report_details(stats, committed=True)
        else:
            self._report(stats, committed=True)
        self.stdout.write(self.style.SUCCESS("\nDone."))

    # ── loading ──────────────────────────────────────────────────────────────

    def _load(self, rows, overrides):
        stats = {
            "members_created": 0, "members_updated": 0,
            "users_created": 0, "elders": 0,
            "no_phone": 0, "bad_phone": [], "skipped": [], "bad_dob": [],
        }

        assembly, _ = Assembly.objects.get_or_create(
            slug=slugify(ASSEMBLY_NAME),
            defaults={"name": ASSEMBLY_NAME, "district": ASSEMBLY_DISTRICT},
        )

        groups = {}
        for weekday, akan in AKAN.items():
            english = [k for k, v in WEEKDAY.items() if v == weekday][0].capitalize()
            group, _ = DayBornGroup.objects.get_or_create(
                assembly=assembly, weekday=weekday,
                defaults={"name": f"{akan} ({english}-born)"},
            )
            groups[weekday] = group

        for row in rows:
            member_id = row.get(COL["member_id"], "").strip()
            name = full_name(row)
            if not member_id or not name:
                stats["skipped"].append(member_id or "(no id)")
                continue

            # Agreed corrections win over whatever the sheet currently says.
            if member_id in overrides:
                phone = overrides[member_id]
            else:
                raw = row.get(COL["phone"], "")
                phone = clean_phone(raw)
                if raw and not phone:
                    stats["bad_phone"].append(f"{member_id} ({raw})")

            user = None
            if phone:
                user, created = User.objects.get_or_create(phone_number=phone)
                if created:
                    stats["users_created"] += 1
            else:
                stats["no_phone"] += 1

            raw_dob = row.get(COL["dob"], "")
            dob = parse_dob(raw_dob)
            if raw_dob and not dob:
                stats["bad_dob"].append(f"{member_id} ({raw_dob})")

            weekday = WEEKDAY.get(row.get(COL["day_born"], "").strip().lower())
            title = clean_title(row.get(COL["title"], ""))

            member, created = Member.objects.update_or_create(
                member_id=member_id,
                defaults={
                    "user": user,
                    "full_name": name,
                    "date_of_birth": dob,
                    "sex": clean_sex(row.get(COL["sex"], "")),
                    "residence": clean_residence(row.get(COL["residence"], "")),
                    "church_roles": clean_roles(row.get(COL["church_roles"], ""), row.get(COL["residence"], "")),
                    "role": clean_role(row.get(COL["app_role"], "")),
                    "assembly": assembly,
                    "day_born_group": groups.get(weekday) if weekday is not None else None,
                },
            )
            stats["members_created" if created else "members_updated"] += 1

            # Leaders get an Elder profile. The office vocabulary on the server
            # is narrower than the church's titles, so the exact title is kept
            # as text and only the presiding elder maps to a distinct office.
            if title in LEADER_TITLES:
                Elder.objects.update_or_create(
                    member=member,
                    defaults={
                        "office": Elder.OFFICE_PRESIDING if title == "Presiding Elder" else Elder.OFFICE_OTHER,
                        "title": title,
                        "contact_phone": phone or "",
                    },
                )
                stats["elders"] += 1

        return stats

    def _details(self, rows):
        """Residence and church roles only, matched by member ID."""
        stats = {"updated": 0, "unchanged": 0, "missing": [], "with_roles": 0, "with_residence": 0}
        for row in rows:
            member_id = row.get(COL["member_id"], "").strip()
            if not member_id or not member_id.upper().startswith("MEM-"):
                continue  # header and title rows
            member = Member.objects.filter(member_id=member_id).first()
            if member is None:
                stats["missing"].append(member_id)
                continue
            residence = clean_residence(row.get(COL["residence"], ""))
            roles = clean_roles(row.get(COL["church_roles"], ""), row.get(COL["residence"], ""))
            stats["with_roles"] += bool(roles)
            stats["with_residence"] += bool(residence)
            if member.residence == residence and member.church_roles == roles:
                stats["unchanged"] += 1
                continue
            member.residence, member.church_roles = residence, roles
            member.save(update_fields=["residence", "church_roles", "updated_at"])
            stats["updated"] += 1
        return stats

    def _report_details(self, stats, committed: bool):
        verb = "Updated" if committed else "Would update"
        self.stdout.write("")
        self.stdout.write(f"  {verb} members : {stats['updated']}  ({stats['unchanged']} already up to date)")
        self.stdout.write(f"  With a residence: {stats['with_residence']}")
        self.stdout.write(f"  With church roles: {stats['with_roles']}")
        if stats["missing"]:
            self.stdout.write(self.style.WARNING(f"  Not on the roll, skipped: {', '.join(stats['missing'])}"))

    # ── reporting ────────────────────────────────────────────────────────────

    def _report(self, stats, committed: bool):
        verb = "Created" if committed else "Would create"
        self.stdout.write("")
        self.stdout.write(f"  {verb} members : {stats['members_created']}")
        self.stdout.write(f"  Updated members: {stats['members_updated']}")
        self.stdout.write(f"  {verb} logins  : {stats['users_created']}")
        self.stdout.write(f"  Leader profiles: {stats['elders']}")
        self.stdout.write(f"  Without a phone: {stats['no_phone']}  (no login until a number is added)")

        if stats["bad_phone"]:
            self.stdout.write(self.style.WARNING(
                f"\n  Unusable phone numbers, left blank ({len(stats['bad_phone'])}):"))
            for item in stats["bad_phone"]:
                self.stdout.write(f"    {item}")

        if stats["bad_dob"]:
            self.stdout.write(self.style.WARNING(
                f"\n  Incomplete birth dates, left blank ({len(stats['bad_dob'])}):"))
            for item in stats["bad_dob"]:
                self.stdout.write(f"    {item}")

        if stats["skipped"]:
            self.stdout.write(self.style.WARNING(
                f"\n  Skipped rows with no id or no name ({len(stats['skipped'])}):"))
            for item in stats["skipped"]:
                self.stdout.write(f"    {item}")


class _DryRun(Exception):
    """Unwinds the transaction when the command is only reporting."""
