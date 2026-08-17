from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CatalogBookViewSet,
    DetectedBookViewSet,
    LibraryItemViewSet,
    ScanViewSet,
    health,
)

router = DefaultRouter()
router.register(r"catalog", CatalogBookViewSet, basename="catalog")
router.register(r"scans", ScanViewSet, basename="scan")
router.register(r"detections", DetectedBookViewSet, basename="detection")
router.register(r"library", LibraryItemViewSet, basename="library")

urlpatterns = [
    path("health/", health, name="health"),
    path("", include(router.urls)),
]
