"""Let a member exist without a login.

The phone number is the login identity, and most of the congregation has no
number on file yet. Rather than inventing placeholder numbers to satisfy a
NOT NULL constraint, a member without a phone simply has no user attached until
one is collected.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="member",
            name="user",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="member_profile",
                to="accounts.user",
            ),
        ),
    ]
