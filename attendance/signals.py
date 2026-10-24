"""
attendance/signals.py

Keeps MemberAttendanceStat current. The model has always said it was
"recomputed via signal" — but no signal existed, so every score and streak in
the church stayed at zero however often anyone attended.

Each recompute runs after the surrounding transaction commits, so it reads
the change that triggered it rather than the moment before it.
"""
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from attendance import stats
from attendance.models import AttendanceRecord, AttendanceSession


def _assembly_of(session_id):
    return (
        AttendanceSession.objects.filter(pk=session_id).values_list("assembly_id", flat=True).first()
    )


@receiver(post_save, sender=AttendanceRecord)
@receiver(post_delete, sender=AttendanceRecord)
def record_changed(sender, instance, **kwargs):
    """A mark added or undone moves only that member's figures."""
    member_id, session_id = instance.member_id, instance.session_id

    def run():
        assembly_id = _assembly_of(session_id)
        # Gone with its session: the session's own signal recomputes everyone.
        if assembly_id:
            stats.recompute(assembly_id, member_ids=[member_id])

    transaction.on_commit(run)


@receiver(post_save, sender=AttendanceSession)
def session_saved(sender, instance, created, **kwargs):
    """
    Closing a service settles it: everyone who did not sign in has now missed
    it, and their score and streak have to say so. Opening one changes nobody —
    a running service is not a miss — so creation is skipped.
    """
    if created:
        return
    assembly_id = instance.assembly_id
    transaction.on_commit(lambda: stats.recompute(assembly_id))


@receiver(post_delete, sender=AttendanceSession)
def session_deleted(sender, instance, **kwargs):
    """A deleted session was never held, so nobody missed it."""
    assembly_id = instance.assembly_id
    transaction.on_commit(lambda: stats.recompute(assembly_id))
