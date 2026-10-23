"""
core/models.py

Shared abstract base model used by every app in this project.
Put this in an app called `core` (or `common`) and import BaseModel
wherever a model needs a UUID primary key + timestamps.
"""
import uuid

from django.db import models


class BaseModel(models.Model):
    """
    Abstract base: UUID primary key + created/updated timestamps.
    Every concrete model in this project should inherit from this
    instead of Django's default auto-incrementing integer pk.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ActivityLog(BaseModel):
    """
    A record of something consequential that someone did.

    Written by the server, never by the client: an audit trail a caller can
    forge is not an audit trail. Every entry is appended — there is no update or
    delete path, because the value of the log is that it cannot be tidied up
    afterwards by whoever is being audited.

    `actor` may be null. A member can be deleted while the record of what they
    did must survive, and some entries are the system's own.
    """

    SEVERITY_INFO = "info"
    SEVERITY_WARNING = "warning"
    SEVERITY_CRITICAL = "critical"
    SEVERITY_CHOICES = [
        (SEVERITY_INFO, "Info"),
        (SEVERITY_WARNING, "Warning"),
        (SEVERITY_CRITICAL, "Critical"),
    ]

    actor = models.ForeignKey(
        "accounts.Member",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity",
    )
    # Kept as text as well as a relation, so the trail still reads correctly
    # after the member record is gone.
    actor_name = models.CharField(max_length=150, blank=True)

    action = models.CharField(max_length=150)
    affected_record = models.CharField(max_length=255, blank=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default=SEVERITY_INFO)

    assembly = models.ForeignKey(
        "accounts.Assembly",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["assembly", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.actor_name or 'system'}: {self.action}"


def record_activity(actor, action, affected_record="", severity=ActivityLog.SEVERITY_INFO, assembly=None):
    """
    Appends one entry.

    Deliberately forgiving: logging is a side effect of the thing the member
    actually asked for, so a failure here must never turn a successful action
    into an error they see.
    """
    try:
        return ActivityLog.objects.create(
            actor=actor,
            actor_name=getattr(actor, "full_name", "") or "",
            action=action,
            affected_record=affected_record,
            severity=severity,
            assembly=assembly or getattr(actor, "assembly", None),
        )
    except Exception:  # noqa: BLE001 - never break the caller over a log line
        return None
