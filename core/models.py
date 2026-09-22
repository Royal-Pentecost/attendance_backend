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
