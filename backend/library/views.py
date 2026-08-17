from rest_framework import status, viewsets
from rest_framework.decorators import api_view
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .matching import classify_confidence
from .models import CatalogBook, LibraryItem, Scan
from .pipeline import process_scan
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


class ScanViewSet(viewsets.ModelViewSet):
    """
    POST /api/scans/ with multipart field `image` runs the full pipeline and
    returns the completed Scan (detections included).
    """

    queryset = Scan.objects.prefetch_related("detections__matched_book").all()
    serializer_class = ScanSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request, *args, **kwargs):
        image = request.FILES.get("image")
        if image is None:
            return Response(
                {
                    "detail": "Missing image file. Upload multipart field named 'image'.",
                    "hint": "The app still works — pick a photo and try again.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        scan = Scan.objects.create(image=image, status=Scan.Status.PENDING)
        try:
            process_scan(scan)
        except Exception as exc:
            scan.refresh_from_db()
            scan.status = Scan.Status.FAILED
            scan.error_message = f"Unexpected pipeline error: {exc}"
            scan.save(update_fields=["status", "error_message", "updated_at"])

        scan = (
            Scan.objects.prefetch_related("detections__matched_book")
            .get(pk=scan.pk)
        )
        data = ScanSerializer(scan, context={"request": request}).data
        data["summary"] = _scan_summary(scan)
        return Response(data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        data = self.get_serializer(instance).data
        data["summary"] = _scan_summary(instance)
        return Response(data)


class LibraryItemViewSet(viewsets.ModelViewSet):
    queryset = LibraryItem.objects.select_related("catalog_book").all()
    serializer_class = LibraryItemSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


def _scan_summary(scan: Scan) -> dict:
    detections = list(scan.detections.all())
    high = low = unmatched = ocr_failed = 0
    for det in detections:
        if det.ocr_error and not det.raw_title and not det.raw_author:
            ocr_failed += 1
        conf = det.match_confidence
        if conf is None:
            unmatched += 1
            continue
        band = classify_confidence(conf)
        if band == "high":
            high += 1
        elif band == "low":
            low += 1
        else:
            unmatched += 1
    return {
        "detection_count": len(detections),
        "high_confidence": high,
        "needs_review": low + unmatched + ocr_failed,
        "low_confidence": low,
        "unmatched": unmatched,
        "ocr_failed": ocr_failed,
        "latency_ms": scan.latency_ms,
        "estimated_api_cost_usd": (
            float(scan.estimated_api_cost_usd)
            if scan.estimated_api_cost_usd is not None
            else None
        ),
        "message": scan.error_message or None,
    }
