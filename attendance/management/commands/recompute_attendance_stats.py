"""
Rebuilds every member's attendance stats from the raw records.

Run once after deploying the stats code — before it existed nothing had ever
been written to that table — and again after any change to the rules in
`attendance.stats`. Safe to repeat: it overwrites, it never adds.
"""
from django.core.management.base import BaseCommand

from attendance import stats


class Command(BaseCommand):
    help = "Recompute scores, Sunday streaks and arrival times for every member."

    def handle(self, *args, **options):
        n = stats.recompute_all()
        self.stdout.write(self.style.SUCCESS(f"Recomputed attendance stats for {n} members."))
