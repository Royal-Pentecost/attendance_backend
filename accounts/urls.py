from rest_framework.routers import DefaultRouter

from accounts.views import (
    AssemblyViewSet,
    DayBornGroupViewSet,
    MemberViewSet,
    ElderViewSet,
    ElderOfficeHoursViewSet,
    ImportBatchViewSet,
)

router = DefaultRouter()
router.register("assemblies", AssemblyViewSet, basename="assembly")
router.register("day-born-groups", DayBornGroupViewSet, basename="dayborngroup")
router.register("members", MemberViewSet, basename="member")
router.register("elders", ElderViewSet, basename="elder")
router.register("elder-office-hours", ElderOfficeHoursViewSet, basename="elderofficehours")
router.register("import-batches", ImportBatchViewSet, basename="importbatch")

urlpatterns = router.urls
