"""
core/push.py

Push notifications through Expo's push service, which hands them to Google
(Android) and Apple (iOS). A phone only receives one if the app has registered
its token — see PushDevice — and the build carries Firebase credentials.

`announce()` is the one entry point: it records the notification for the
in-app inbox and pushes it to the phones of everyone it concerns. Sending
happens after the surrounding transaction commits and on a background thread,
so publishing an event never waits on Expo, and a slow or failed send never
undoes what was published.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
BATCH = 100  # Expo accepts at most 100 messages per request.


def _post(messages: list[dict]) -> list[dict]:
    """One request to Expo; returns its per-message tickets (empty on failure)."""
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    token = getattr(settings, "EXPO_ACCESS_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(EXPO_PUSH_URL, data=json.dumps(messages).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()).get("data", [])
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("Expo push request failed: %s", exc)
        return []


def send(tokens: list[str], title: str, body: str, data: dict | None = None) -> dict:
    """
    Sends to the given tokens now and returns a tally. Dead tokens are removed.
    Synchronous — call `announce()` from request code instead.
    """
    from core.models import PushDevice

    tally = {"sent": 0, "failed": 0, "removed": 0}
    if not tokens or not getattr(settings, "EXPO_PUSH_ENABLED", True):
        return tally

    for i in range(0, len(tokens), BATCH):
        chunk = tokens[i:i + BATCH]
        messages = [{
            "to": t,
            "title": title,
            "body": body,
            "data": data or {},
            "sound": "default",
            # "high" so Android shows it at once rather than batching it until
            # the phone next wakes — attendance opening is time-sensitive.
            "priority": "high",
            "channelId": "default",
        } for t in chunk]
        tickets = _post(messages)
        dead = []
        for t, ticket in zip(chunk, tickets):
            if ticket.get("status") == "ok":
                tally["sent"] += 1
            else:
                tally["failed"] += 1
                if (ticket.get("details") or {}).get("error") == "DeviceNotRegistered":
                    dead.append(t)
        if len(tickets) < len(chunk):
            tally["failed"] += len(chunk) - len(tickets)
        if dead:
            tally["removed"] += PushDevice.objects.filter(token__in=dead).delete()[0]
    logger.info("Push '%s': %s", title, tally)
    return tally


def announce(*, kind: str, title: str, body: str, assembly=None, actor=None, data: dict | None = None) -> None:
    """
    Tell a whole assembly — or everyone, when `assembly` is None — that
    something happened: an inbox entry for every member, and a push to every
    registered phone except the actor's own.
    """
    from accounts.models import Member
    from content.models import Notification
    from core.models import PushDevice

    Notification.objects.create(
        title=title,
        body=body,
        notification_type=kind,
        audience_type=Notification.AUDIENCE_ASSEMBLY if assembly else Notification.AUDIENCE_ALL,
        assembly=assembly,
    )

    members = Member.objects.all()
    if assembly is not None:
        members = members.filter(assembly=assembly)
    if actor is not None:
        members = members.exclude(pk=actor.pk)
    tokens = list(PushDevice.objects.filter(member__in=members).values_list("token", flat=True))
    payload = {"kind": kind, **(data or {})}

    def later():
        threading.Thread(target=send, args=(tokens, title, body, payload), daemon=True).start()

    transaction.on_commit(later)
