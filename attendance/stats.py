"""
attendance/stats.py

Computes MemberAttendanceStat — the score, the Sunday streak and the arrival
time behind the dashboard card and the leaderboard.

The rules, in one place:

* **A service day** is the date a session was opened. Two sessions on the same
  day (an admin who closed one by mistake and opened another) are one service,
  not two chances to be absent.
* **A day only counts once it is settled** — every session on it closed. While
  a service is still running, nobody has missed it yet, so it is left out of
  "possible" for anyone who has not signed in. A member who *has* signed in
  gets the credit straight away; that is what makes the streak move the moment
  they mark attendance.
* **The streak is Sundays only**, counted in Sundays that actually had a
  service. A Sunday with no session — the assembly at a district convention,
  say — neither adds to it nor breaks it. It runs across years, because a
  member who has not missed a Sunday since November has not missed one.
* **The annual score is every service this year**: days attended over days
  held.
* **Arrival time** is minutes from the session opening to the member's own GPS
  sign-in, averaged over the year. Manual entries are presence but not timing:
  the time on them is when an admin typed them in.
"""
from __future__ import annotations

import datetime
from collections import defaultdict
from decimal import Decimal
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from accounts.models import Assembly, Member
from attendance.models import AttendanceRecord, AttendanceSession, MemberAttendanceStat

SUNDAY = 6  # date.weekday()


@dataclass
class _Day:
    date: datetime.date
    settled: bool          # every session on it is closed
    session_ids: set


def _service_days(assembly_id) -> tuple[dict, dict]:
    """
    The assembly's service days, and which day each session belongs to.

    Dates are taken in the server's timezone (UTC — Ghana's own), so a
    service that opens at 07:00 is that Sunday everywhere.
    """
    days: dict[datetime.date, _Day] = {}
    day_of_session: dict = {}
    sessions = AttendanceSession.objects.filter(assembly_id=assembly_id).values_list(
        "id", "opened_at", "closed_at", "is_active",
    )
    for sid, opened_at, closed_at, is_active in sessions:
        d = timezone.localtime(opened_at).date()
        closed = bool(closed_at) or not is_active
        day = days.get(d)
        if day is None:
            days[d] = _Day(date=d, settled=closed, session_ids={sid})
        else:
            day.session_ids.add(sid)
            day.settled = day.settled and closed
        day_of_session[sid] = d
    return days, day_of_session


def _figures(days: dict, day_of_session: dict, records: list, year: int) -> dict:
    """One member's figures from their records — no queries."""
    attended_days = {day_of_session[r["session_id"]] for r in records if r["session_id"] in day_of_session}

    # A day counts once it is settled, or as soon as this member has attended
    # it — never as a miss while the service is still open.
    counted = sorted(d for d, day in days.items() if day.settled or d in attended_days)

    this_year = [d for d in counted if d.year == year]
    attended_this_year = [d for d in this_year if d in attended_days]

    sundays = [d for d in counted if d.weekday() == SUNDAY]
    run = longest = 0
    for d in sundays:
        run = run + 1 if d in attended_days else 0
        longest = max(longest, run)
    # `run` is now the run ending at the most recent counted Sunday.
    current = run

    sundays_this_year = [d for d in sundays if d.year == year]

    arrivals = [
        max(0.0, (r["marked_at"] - r["opened_at"]).total_seconds() / 60)
        for r in records
        if r["method"] == AttendanceRecord.METHOD_GPS
        and r["session_id"] in day_of_session
        and day_of_session[r["session_id"]].year == year
    ]

    latest = max(records, key=lambda r: r["marked_at"], default=None)

    possible = len(this_year)
    attended = len(attended_this_year)
    return {
        "sessions_attended": attended,
        "sessions_possible": possible,
        "annual_score_percent": Decimal(attended * 100 / possible).quantize(Decimal("0.01")) if possible else Decimal("0"),
        "current_streak_weeks": current,
        "longest_streak_weeks": longest,
        "sundays_attended": sum(1 for d in sundays_this_year if d in attended_days),
        "sundays_possible": len(sundays_this_year),
        "average_arrival_minutes": round(sum(arrivals) / len(arrivals), 1) if arrivals else None,
        "last_attended_session_id": latest["session_id"] if latest else None,
    }


def _records(assembly_id, member_ids=None) -> dict:
    """Every mark in the assembly's sessions, grouped by member."""
    qs = AttendanceRecord.objects.filter(session__assembly_id=assembly_id)
    if member_ids is not None:
        qs = qs.filter(member_id__in=member_ids)
    grouped = defaultdict(list)
    for row in qs.values("member_id", "session_id", "method", "marked_at", "session__opened_at"):
        row["opened_at"] = row.pop("session__opened_at")
        grouped[row["member_id"]].append(row)
    return grouped


FIELDS = [
    "sessions_attended", "sessions_possible", "annual_score_percent",
    "current_streak_weeks", "longest_streak_weeks",
    "sundays_attended", "sundays_possible", "average_arrival_minutes",
    "last_attended_session_id",
]


@transaction.atomic
def recompute(assembly_id, member_ids=None, year: int | None = None) -> int:
    """
    Rewrites the stats for one assembly — every member, or just `member_ids`.

    Two queries for the inputs and two for the writes, whatever the size of
    the roll: a session closing recomputes all 328 members, and that has to
    be quick enough to sit inside the request that closed it.
    """
    year = year or timezone.localdate().year
    days, day_of_session = _service_days(assembly_id)
    records = _records(assembly_id, member_ids)

    members = Member.objects.filter(assembly_id=assembly_id)
    if member_ids is not None:
        members = members.filter(id__in=member_ids)
    member_ids = list(members.values_list("id", flat=True))

    existing = {
        s.member_id: s
        for s in MemberAttendanceStat.objects.filter(member_id__in=member_ids, year=year)
    }
    to_create, to_update = [], []
    now = timezone.now()  # bulk_update does not apply auto_now itself
    for mid in member_ids:
        figures = _figures(days, day_of_session, records.get(mid, []), year)
        stat = existing.get(mid)
        if stat is None:
            to_create.append(MemberAttendanceStat(member_id=mid, assembly_id=assembly_id, year=year, **figures))
        else:
            for k, v in figures.items():
                setattr(stat, k, v)
            stat.assembly_id = assembly_id
            stat.updated_at = now
            to_update.append(stat)

    if to_create:
        MemberAttendanceStat.objects.bulk_create(to_create)
    if to_update:
        MemberAttendanceStat.objects.bulk_update(to_update, FIELDS + ["assembly_id", "updated_at"])
    return len(member_ids)


def recompute_member(member: Member, assembly_id) -> None:
    """After one member's mark is added or removed — the common case."""
    recompute(assembly_id, member_ids=[member.pk])


def recompute_all() -> int:
    """Every assembly. For a backfill, or after changing these rules."""
    return sum(recompute(a) for a in Assembly.objects.values_list("id", flat=True))
