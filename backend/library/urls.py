from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CatalogBookViewSet, LibraryItemViewSet, ScanViewSet, health

router = DefaultRouter()
router.register(r"catalog", CatalogBookViewSet, basename="catalog")
router.register(r"scans", ScanViewSet, basename="scan")
router.register(r"library", LibraryItemViewSet, basename="library")

urlpatterns = [
    path("health/", health, name="health"),
    path("", include(router.urls)),
]
