"""
milestones/models.py

Covers: the Spiritual Milestones Register (baptisms, confirmations,
certifications). Authorization to CREATE/EDIT these is enforced at the
permission-class level in the API layer, not the model — but `verified_by`
is what makes that check possible: allow if verified_by-eligible user
is_admin OR is the member's assigned_elder.
"""
from django.db import models

from core.models import BaseModel
from accounts.models import Member


class SpiritualMilestone(BaseModel):
    TYPE_BAPTISM = "baptism"
    TYPE_CONFIRMATION = "confirmation"
    TYPE_CERTIFICATION = "certification"
    TYPE_OTHER = "other"
    TYPE_CHOICES = [
        (TYPE_BAPTISM, "Baptism"),
        (TYPE_CONFIRMATION, "Confirmation"),
        (TYPE_CERTIFICATION, "Certification"),
        (TYPE_OTHER, "Other"),
    ]

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="spiritual_milestones")
    milestone_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    date_occurred = models.DateField()
    certificate_file = models.FileField(upload_to="milestones/certificates/", blank=True, null=True)
    notes = models.TextField(blank=True)

    # Audit: who recorded this. Permission check (in the API layer) is:
    #   request.member.role in (ASSEMBLY_ADMIN, SUPER_ADMIN)
    #   OR request.member == member.assigned_elder.member
    verified_by = models.ForeignKey(
        Member, on_delete=models.SET_NULL, null=True, related_name="verified_milestones",
    )

    class Meta:
        ordering = ["-date_occurred"]

    def __str__(self):
        return f"{self.member} — {self.get_milestone_type_display()} ({self.date_occurred})"
