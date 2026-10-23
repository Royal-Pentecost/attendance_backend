"""Record a member's sex, so they can be addressed correctly.

The greeting says "Mr Plange" or "Mrs Mensah" unless the member holds an office,
and there is no honest way to derive that from a name. Blank stays valid — two
members on the roll have no sex recorded, and a guess would be worse than a
plain first name.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_member_user_optional"),
    ]

    operations = [
        migrations.AddField(
            model_name="member",
            name="sex",
            field=models.CharField(
                blank=True,
                choices=[("M", "Male"), ("F", "Female")],
                max_length=1,
            ),
        ),
    ]
