from rest_framework.routers import DefaultRouter

from milestones.views import SpiritualMilestoneViewSet

router = DefaultRouter()
router.register("milestones", SpiritualMilestoneViewSet, basename="spiritualmilestone")

urlpatterns = router.urls
