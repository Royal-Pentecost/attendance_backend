"""
The attendance stats rules — score, Sunday streak, arrival time — as they
play out over a few weeks of real services.

Sessions are back-dated with `.update()`, which does not fire signals, and
the stats are then read after the signal-driven recompute of the next real
change (or an explicit `stats.recompute`), exactly as in production.
"""
import datetime

from django.test import TestCase
from django.utils import timezone

from accounts.models import Assembly, Member
from attendance import stats
from attendance.models import AttendanceRecord, AttendanceSession, MemberAttendanceStat

# Sundays in October and November 2026, and a Wednesday between them.
SUN_OCT_4 = datetime.date(2026, 10, 4)
SUN_OCT_11 = datetime.date(2026, 10, 11)
SUN_OCT_18 = datetime.date(2026, 10, 18)
SUN_OCT_25 = datetime.date(2026, 10, 25)
WED_OCT_14 = datetime.date(2026, 10, 14)


class StreakAndScore(TestCase):
    def setUp(self):
        self.assembly = Assembly.objects.create(name="Royal Assembly", slug="royal", district="Ayigya")
        self.ama = Member.objects.create(member_id="MEM-901", full_name="Ama Test", assembly=self.assembly)
        self.kofi = Member.objects.create(member_id="MEM-902", full_name="Kofi Test", assembly=self.assembly)

    # ── helpers ──────────────────────────────────────────────────────────────
    def service(self, day, *, hour=7, closed=True, name="Sunday Divine Service"):
        """A session opened at `hour` on `day`, closed unless told otherwise."""
        with self.captureOnCommitCallbacks(execute=True):
            s = AttendanceSession.objects.create(
                assembly=self.assembly, service_name=name,
                geofence_center_lat="6.689225", geofence_center_lng="-1.570365", geofence_radius_meters=100,
            )
        opened = timezone.make_aware(datetime.datetime.combine(day, datetime.time(hour, 0)))
        AttendanceSession.objects.filter(pk=s.pk).update(
            opened_at=opened,
            closed_at=opened + datetime.timedelta(hours=3) if closed else None,
            is_active=not closed,
        )
        s.refresh_from_db()
        return s

    def mark(self, member, session, *, minutes_late=5, method=AttendanceRecord.METHOD_GPS):
        with self.captureOnCommitCallbacks(execute=True):
            r = AttendanceRecord.objects.create(session=session, member=member, method=method)
        AttendanceRecord.objects.filter(pk=r.pk).update(
            marked_at=session.opened_at + datetime.timedelta(minutes=minutes_late),
        )
        # The back-dated time is not a signal; recompute as the next change would.
        stats.recompute(self.assembly.pk, year=2026)
        return r

    def stat(self, member):
        return MemberAttendanceStat.objects.get(member=member, year=2026)

    def settle(self):
        stats.recompute(self.assembly.pk, year=2026)

    # ── the rules ────────────────────────────────────────────────────────────
    def test_streak_counts_consecutive_sundays(self):
        for d in (SUN_OCT_4, SUN_OCT_11, SUN_OCT_18):
            self.mark(self.ama, self.service(d))
        self.assertEqual(self.stat(self.ama).current_streak_weeks, 3)
        self.assertEqual(self.stat(self.ama).longest_streak_weeks, 3)

    def test_a_missed_sunday_resets_it_but_the_record_is_kept(self):
        self.mark(self.ama, self.service(SUN_OCT_4))
        self.mark(self.ama, self.service(SUN_OCT_11))
        self.service(SUN_OCT_18)                  # held, Ama absent
        self.mark(self.ama, self.service(SUN_OCT_25))
        self.settle()
        s = self.stat(self.ama)
        self.assertEqual(s.current_streak_weeks, 1)
        self.assertEqual(s.longest_streak_weeks, 2)

    def test_signing_in_moves_the_streak_while_the_service_is_still_open(self):
        self.mark(self.ama, self.service(SUN_OCT_4))
        today = self.service(SUN_OCT_11, closed=False)
        self.settle()
        # Not signed yet: the open service is not held against her.
        self.assertEqual(self.stat(self.ama).current_streak_weeks, 1)
        self.assertEqual(self.stat(self.ama).sessions_possible, 1)
        # Signs in: the streak jumps straight away, before anyone closes it.
        self.mark(self.ama, today)
        self.assertEqual(self.stat(self.ama).current_streak_weeks, 2)

    def test_closing_the_service_is_what_counts_it_against_the_absent(self):
        self.mark(self.kofi, self.service(SUN_OCT_4))
        today = self.service(SUN_OCT_11, closed=False)
        self.settle()
        self.assertEqual(self.stat(self.kofi).current_streak_weeks, 1)
        with self.captureOnCommitCallbacks(execute=True):
            today.closed_at = timezone.now()
            today.is_active = False
            today.save()                          # the signal recomputes everyone
        self.assertEqual(self.stat(self.kofi).current_streak_weeks, 0)

    def test_a_sunday_with_no_service_neither_adds_nor_breaks_it(self):
        self.mark(self.ama, self.service(SUN_OCT_4))
        # No session at all on 11 October — a district convention.
        self.mark(self.ama, self.service(SUN_OCT_18))
        self.assertEqual(self.stat(self.ama).current_streak_weeks, 2)

    def test_midweek_services_count_in_the_score_but_not_the_streak(self):
        self.mark(self.ama, self.service(SUN_OCT_4))
        self.mark(self.ama, self.service(WED_OCT_14, hour=18, name="Bible Study"))
        self.service(SUN_OCT_11)                  # missed Sunday
        self.settle()
        s = self.stat(self.ama)
        self.assertEqual((s.sessions_attended, s.sessions_possible), (2, 3))
        self.assertEqual((s.sundays_attended, s.sundays_possible), (1, 2))
        self.assertEqual(float(s.annual_score_percent), 66.67)
        # The Wednesday came after the missed Sunday but does not rescue it.
        self.assertEqual(s.current_streak_weeks, 0)

    def test_two_sessions_on_one_day_are_one_service(self):
        self.service(SUN_OCT_4)                   # opened by mistake, closed
        second = self.service(SUN_OCT_4, hour=8)
        self.mark(self.ama, second)
        s = self.stat(self.ama)
        self.assertEqual((s.sessions_attended, s.sessions_possible), (1, 1))
        self.assertEqual(s.current_streak_weeks, 1)

    def test_arrival_time_averages_own_sign_ins_and_ignores_manual_ones(self):
        self.mark(self.ama, self.service(SUN_OCT_4), minutes_late=4)
        self.mark(self.ama, self.service(SUN_OCT_11), minutes_late=10)
        self.mark(self.ama, self.service(SUN_OCT_18), minutes_late=95, method=AttendanceRecord.METHOD_MANUAL)
        s = self.stat(self.ama)
        self.assertEqual(s.average_arrival_minutes, 7.0)
        self.assertEqual(s.current_streak_weeks, 3)      # manual is still presence

    def test_undoing_a_mark_takes_the_credit_back(self):
        self.mark(self.ama, self.service(SUN_OCT_4))
        r = self.mark(self.ama, self.service(SUN_OCT_11))
        self.assertEqual(self.stat(self.ama).current_streak_weeks, 2)
        with self.captureOnCommitCallbacks(execute=True):
            r.delete()
        self.assertEqual(self.stat(self.ama).current_streak_weeks, 0)

    def test_everyone_on_the_roll_gets_a_row(self):
        self.mark(self.ama, self.service(SUN_OCT_4))
        self.settle()
        k = self.stat(self.kofi)
        self.assertEqual((k.sessions_attended, k.sessions_possible, k.current_streak_weeks), (0, 1, 0))
        self.assertIsNone(k.average_arrival_minutes)
