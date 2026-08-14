from rest_framework import status, viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import CatalogBook, LibraryItem, Scan
from .serializers import CatalogBookSerializer, LibraryItemSerializer, ScanSerializer


@api_view(["GET"])
def health(request):
    return Response(
        {
            "status": "ok",
            "catalog_count": CatalogBook.objects.count(),
        }
    )


class CatalogBookViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CatalogBook.objects.all()
    serializer_class = CatalogBookSerializer
    lookup_field = "catalog_id"


class ScanViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only for now; upload/process endpoint lands in a later commit."""

    queryset = Scan.objects.prefetch_related("detections__matched_book").all()
    serializer_class = ScanSerializer


class LibraryItemViewSet(viewsets.ModelViewSet):
    queryset = LibraryItem.objects.select_related("catalog_book").all()
    serializer_class = LibraryItemSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
