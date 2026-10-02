from rest_framework.routers import DefaultRouter

from attendance.views import (
    AttendanceSessionViewSet,
    AttendanceRecordViewSet,
    MemberAttendanceStatViewSet,
)

router = DefaultRouter()
router.register("sessions", AttendanceSessionViewSet, basename="attendancesession")
router.register("records", AttendanceRecordViewSet, basename="attendancerecord")
router.register("stats", MemberAttendanceStatViewSet, basename="memberattendancestat")

urlpatterns = router.urls
