"""
Fill in phone numbers, residence and marital status from the church's newer
register, for members already on the roll. Nobody is added.

    python manage.py apply_register "NEW REGISTER.xlsx"            # report only
    python manage.py apply_register "NEW REGISTER.xlsx" --commit   # write
    python manage.py apply_register "NEW REGISTER.xlsx" --report out.csv

The register and the roll were typed separately, so a person is recognised by
name rather than by any shared ID:

* Word order is ignored ("AGYEI ABENA ADUTWUMWAA" is Abena Adutumwaa Agyei),
  titles are dropped (ELD., DCNS., MRS.) and small typos are allowed
  (Akomea/Akomeah, Joeph/Joseph).
* Every word of the shorter name must be found in the longer one — or all but
  one, when that one is a near-spelling (Kobina/Bobena) and at least two other
  words match exactly. One shared word is never enough: a congregation has
  many Mensahs.
* Sex must agree, and birth dates must not clearly disagree. The same date
  written day-first in one sheet and month-first in the other (07/09 against
  09/07) is the same person, as is the same day and month with a mistyped year.
* If a name could be two people on the roll, or two register rows claim the
  same member with different details, nothing is changed and it is reported.

What changes, for a match:

* Residence and marital status are taken from the register.
* A phone number is added only where the member has none. A number already on
  file is the one they sign in with; replacing it would lock them out, so a
  different number in the register is reported, not applied. A number used by
  another member, or shared by two register rows (spouses often give one), is
  reported too — a number can be one login only.
"""
from __future__ import annotations

import csv
import datetime
import difflib
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.management.commands.load_royal_assembly import clean_residence
from accounts.models import Member, User

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}

TITLES = {"eld", "elder", "dcn", "dcns", "deacon", "deaconess", "deac", "pastor", "ps", "rev",
          "mr", "mrs", "miss", "ms", "dr", "pres", "presiding", "prof", "madam", "mad", "opanin"}

MARITAL = {"single": "single", "married": "married", "widow": "widowed", "widowed": "widowed",
           "widower": "widowed", "divorced": "divorced", "divorce": "divorced"}


class _DryRun(Exception):
    pass


# ── reading ──────────────────────────────────────────────────────────────────

def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_register(path: str) -> list[dict]:
    """The first sheet's people, keyed by header: name, sex, dob, residence, marital, phone."""
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise CommandError(f"Could not open {path}: {exc}") from exc
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    first = wb.find("m:sheets", NS)[0]
    target = rels[first.get("{%s}id" % NS["r"])].lstrip("/")
    target = target if target.startswith("xl/") else "xl/" + target

    rows = []
    for r in ET.fromstring(z.read(target)).iter("{%s}row" % NS["m"]):
        d = {}
        for c in r.findall("m:c", NS):
            v = c.find("m:v", NS)
            if v is not None:
                d[_col(c.get("r"))] = shared[int(v.text)] if c.get("t") == "s" else v.text
        rows.append(d)

    # Find the header row rather than assuming its position: the sheet opens
    # with the church's name and a title above it.
    wanted = {"name": "name", "sex": "sex", "date of birth": "dob", "residence": "residence",
              "marital status": "marital", "tel. number": "phone", "tel number": "phone", "phone": "phone"}
    for i, row in enumerate(rows):
        heads = {(v or "").strip().lower(): k for k, v in row.items()}
        if "name" in heads:
            cols = {wanted[h]: k for h, k in heads.items() if h in wanted}
            break
    else:
        raise CommandError("No header row with a NAME column was found.")

    people = []
    for n, row in enumerate(rows[i + 1:], start=i + 2):
        name = (row.get(cols["name"]) or "").strip()
        if not name:
            continue
        people.append({"row": n, **{k: (row.get(c) or "").strip() for k, c in cols.items()}})
    return people


# ── matching ─────────────────────────────────────────────────────────────────

def tokens(name: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", (name or "").lower()) if w not in TITLES and len(w) > 1]


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _close(a: str, b: str, threshold: float) -> bool:
    """
    A spelling slip, not a different name.

    One word sitting inside the other with two or more letters added is a
    different surname — Aidoo and Abaidoo, Amoah and Damoah — however alike
    they look. One added letter (Akomea/Akomeah, Kwasi/Akwasi) is a slip.
    """
    short, long_ = sorted((a, b), key=len)
    if short != long_ and short in long_ and len(long_) - len(short) >= 2:
        return False
    return _ratio(a, b) >= threshold


def name_match(a: list[str], b: list[str]) -> str | None:
    """'exact', 'similar' or None, by the rules in the module docstring."""
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 2:
        return None
    pool = list(long_)
    exact = typo = 0
    leftover = []
    for w in short:
        if w in pool:
            pool.remove(w); exact += 1
            continue
        near = next((x for x in pool if min(len(w), len(x)) >= 4 and _close(w, x, 0.8)), None)
        if near:
            pool.remove(near); typo += 1
        else:
            leftover.append(w)
    if not leftover:
        return "exact" if typo == 0 and len(a) == len(b) else "similar"
    # One word spelled further off (Bobena/Kobina), with two exact words beside it.
    if len(leftover) == 1 and exact >= 2 and any(_close(leftover[0], x, 0.6) for x in pool):
        return "similar"
    return None


def parse_dob(raw: str) -> datetime.date | None:
    raw = (raw or "").strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    if re.fullmatch(r"\d{4,5}(\.0+)?", raw):  # an Excel date value
        return datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(raw)))
    return None


def dates_agree(a: datetime.date | None, b: datetime.date | None) -> bool:
    if not a or not b or a == b:
        return True
    swapped = a.year == b.year and (a.day, a.month) == (b.month, b.day)
    year_typo = (a.month, a.day) == (b.month, b.day)
    return swapped or year_typo


def parse_phones(raw: str) -> list[str]:
    out = []
    for part in re.split(r"[/,;&]|\bor\b", raw or ""):
        d = re.sub(r"\D", "", part)
        if len(d) == 9:
            d = "0" + d                      # Excel dropped the leading zero
        elif len(d) == 12 and d.startswith("233"):
            d = "0" + d[3:]
        if re.fullmatch(r"0\d{9}", d) and d not in out:
            out.append(d)
    return out


# ── command ──────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Add phone numbers, residence and marital status from the newer register to matching members."

    def add_arguments(self, parser):
        parser.add_argument("spreadsheet")
        parser.add_argument("--commit", action="store_true", help="Write. Without it, only report.")
        parser.add_argument("--report", help="Write every decision to this CSV file.")

    def handle(self, *args, **options):
        people = read_register(options["spreadsheet"])
        self.stdout.write(f"Read {len(people)} people from the register.")
        try:
            with transaction.atomic():
                decisions = self._apply(people)
                if not options["commit"]:
                    raise _DryRun()
        except _DryRun:
            self._summary(decisions, committed=False)
            self.stdout.write(self.style.WARNING("\nDry run — nothing was written. Re-run with --commit."))
        else:
            self._summary(decisions, committed=True)
            self.stdout.write(self.style.SUCCESS("\nDone."))
        if options.get("report"):
            with open(options["report"], "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=["register_row", "register_name", "outcome", "member_id",
                                                   "roll_name", "changed", "note"])
                w.writeheader()
                w.writerows(decisions)
            self.stdout.write(f"Report: {options['report']}")

    def _apply(self, people: list[dict]) -> list[dict]:
        members = list(Member.objects.select_related("user"))
        roll_tokens = {m.pk: tokens(m.full_name) for m in members}
        by_pk = {m.pk: m for m in members}

        # A number given by two register rows (spouses, a parent for a child)
        # cannot be both their logins, so it is not handed to either.
        reg_phone_count = Counter(p for person in people for p in parse_phones(person.get("phone", ""))[:1])

        matches = []
        decisions = []
        for person in people:
            rt = tokens(person["name"])
            rsex = (person.get("sex") or "").upper()[:1]
            rdob = parse_dob(person.get("dob"))
            found = []
            for m in members:
                kind = name_match(rt, roll_tokens[m.pk])
                if not kind:
                    continue
                if rsex and m.sex and rsex != m.sex:
                    continue
                if not dates_agree(rdob, m.date_of_birth):
                    continue
                found.append((kind, m))
            base = {"register_row": person["row"], "register_name": person["name"], "member_id": "",
                    "roll_name": "", "changed": "", "note": ""}
            if not found:
                decisions.append({**base, "outcome": "no match"})
            elif len(found) > 1:
                decisions.append({**base, "outcome": "ambiguous",
                                  "note": "could be: " + "; ".join(f"{m.member_id} {m.full_name}" for _, m in found)})
            else:
                matches.append((person, found[0][0], found[0][1]))

        # Two register rows for one member: fine if they agree, a question if not.
        claimed = defaultdict(list)
        for person, kind, m in matches:
            claimed[m.pk].append((person, kind))

        for pk, claims in claimed.items():
            m = by_pk[pk]
            person, kind = claims[0]
            if len(claims) > 1:
                # One word-for-word row and the rest loose: the exact one is this
                # member, and the loose ones are other people with a similar name
                # ("MRS. REBECCA AMOFA" over "AMOAH REBECCA").
                exact_claims = [c for c in claims if c[1] == "exact"]
                if len(exact_claims) == 1 and len(claims) > 1:
                    for p, k in claims:
                        if (p, k) is not exact_claims[0]:
                            decisions.append({"register_row": p["row"], "register_name": p["name"], "outcome": "no match",
                                              "member_id": "", "roll_name": "", "changed": "",
                                              "note": f"closer row used for {m.member_id} {m.full_name}"})
                    claims = exact_claims
                    person, kind = claims[0]
                details = {(p.get("residence", "").lower(), tuple(parse_phones(p.get("phone", ""))[:1])) for p, _ in claims}
                if len(claims) > 1 and len(details) > 1:
                    for p, k in claims:
                        decisions.append({"register_row": p["row"], "register_name": p["name"], "outcome": "conflict",
                                          "member_id": m.member_id, "roll_name": m.full_name, "changed": "",
                                          "note": "two register rows match this member with different details"})
                    continue
            changed, notes = self._update(m, person, reg_phone_count)
            for p, k in claims:
                decisions.append({"register_row": p["row"], "register_name": p["name"],
                                  "outcome": f"matched ({k})", "member_id": m.member_id, "roll_name": m.full_name,
                                  "changed": ", ".join(changed) if p is person else "(duplicate row)",
                                  "note": "; ".join(notes) if p is person else ""})
        return sorted(decisions, key=lambda d: d["register_row"])

    def _update(self, m: Member, person: dict, reg_phone_count: Counter) -> tuple[list[str], list[str]]:
        changed, notes, fields = [], [], []

        residence = clean_residence(person.get("residence", ""))
        if residence and residence != m.residence:
            m.residence = residence
            fields.append("residence"); changed.append("residence")

        marital = MARITAL.get((person.get("marital") or "").strip().lower())
        if marital and marital != m.marital_status:
            m.marital_status = marital
            fields.append("marital_status"); changed.append("marital status")

        numbers = parse_phones(person.get("phone", ""))
        if len(numbers) > 1:
            notes.append(f"register also lists {', '.join(numbers[1:])}")
        if numbers:
            phone = numbers[0]
            current = m.user.phone_number if m.user_id else ""
            if current == phone:
                pass
            elif current:
                notes.append(f"register has {phone}; kept the number they sign in with")
            elif reg_phone_count[phone] > 1:
                notes.append(f"{phone} is given by more than one person in the register; not assigned")
            elif User.objects.filter(phone_number=phone).exists():
                owner = Member.objects.filter(user__phone_number=phone).first()
                notes.append(f"{phone} already belongs to {owner.member_id if owner else 'another login'}; not assigned")
            else:
                m.user = User.objects.create_user(phone_number=phone)
                fields.append("user"); changed.append("phone")
        elif person.get("phone"):
            notes.append(f"unreadable phone {person['phone']!r}")

        if fields:
            m.save(update_fields=fields + ["updated_at"])
        return changed, notes

    def _summary(self, decisions: list[dict], committed: bool):
        verb = "" if committed else "would be "
        outcomes = Counter(d["outcome"].split(" (")[0] for d in decisions)
        changes = Counter(c.strip() for d in decisions for c in d["changed"].split(",") if c.strip() and "(" not in c)
        self.stdout.write("")
        self.stdout.write(f"  Matched rows   : {outcomes['matched']}")
        self.stdout.write(f"  No match       : {outcomes['no match']}  (not on the roll — not added)")
        self.stdout.write(f"  Ambiguous      : {outcomes['ambiguous']}  (left alone)")
        self.stdout.write(f"  Conflicting    : {outcomes['conflict']}  (left alone)")
        self.stdout.write(f"  Phones {verb}added     : {changes['phone']}")
        self.stdout.write(f"  Residences {verb}set   : {changes['residence']}")
        self.stdout.write(f"  Marital status {verb}set: {changes['marital status']}")
        kept = sum(1 for d in decisions if "kept the number" in d["note"])
        skipped = sum(1 for d in decisions if "not assigned" in d["note"])
        self.stdout.write(f"  Different number on file, kept: {kept}")
        self.stdout.write(f"  Numbers not assigned (shared or taken): {skipped}")
