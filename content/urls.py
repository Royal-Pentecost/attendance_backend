from rest_framework.routers import DefaultRouter

from content.views import (
    BibleStudyTranslationViewSet,
    DailyVerseViewSet,
    WeeklyScheduleViewSet,
    BibleStudyWeekViewSet,
    EventViewSet,
    NotificationViewSet,
    NotificationReadViewSet,
)

router = DefaultRouter()
router.register("schedules", WeeklyScheduleViewSet, basename="weeklyschedule")
router.register("bible-study-weeks", BibleStudyWeekViewSet, basename="biblestudyweek")
router.register("events", EventViewSet, basename="event")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("notification-reads", NotificationReadViewSet, basename="notificationread")

router.register("bible-study-text", BibleStudyTranslationViewSet, basename="biblestudytranslation")
router.register("daily-verses", DailyVerseViewSet, basename="dailyverse")

urlpatterns = router.urls
