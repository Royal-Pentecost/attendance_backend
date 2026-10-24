from django.apps import AppConfig


class AttendanceConfig(AppConfig):
    name = 'attendance'

    def ready(self):
        # Registers the receivers that keep attendance stats current.
        from attendance import signals  # noqa: F401
