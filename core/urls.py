from rest_framework.routers import DefaultRouter

from core.views import ActivityLogViewSet, PushDeviceViewSet

router = DefaultRouter()
router.register("activity", ActivityLogViewSet, basename="activity")
router.register("push-devices", PushDeviceViewSet, basename="pushdevice")

urlpatterns = router.urls
