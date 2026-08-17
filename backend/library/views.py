from rest_framework import status, viewsets
from rest_framework.decorators import api_view, action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .matching import classify_confidence
from .models import CatalogBook, DetectedBook, LibraryItem, Scan
from .pipeline import process_scan
from .review import (
    ReviewError,
    accept_detection,
    accept_high_confidence,
    correct_detection,
    discard_detection,
)
from .serializers import (
    CatalogBookSerializer,
    DetectedBookSerializer,
    LibraryItemSerializer,
    ScanSerializer,
)


@api_view(["GET"])
def health(request):
    return Response(
        {
            "status": "ok",
            "catalog_count": CatalogBook.objects.count(),
            "library_count": LibraryItem.objects.count(),
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

    @action(detail=True, methods=["post"], url_path="accept-high-confidence")
    def accept_high_confidence(self, request, pk=None):
        result = accept_high_confidence(int(pk))
        return Response(result)


class DetectedBookViewSet(viewsets.GenericViewSet):
    """Review actions for individual spine detections."""

    queryset = DetectedBook.objects.select_related("matched_book", "scan").all()
    serializer_class = DetectedBookSerializer
    http_method_names = ["get", "post", "head", "options"]

    def retrieve(self, request, *args, **kwargs):
        detection = self.get_object()
        return Response(
            DetectedBookSerializer(detection, context={"request": request}).data
        )

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        detection = self.get_object()
        try:
            detection, library_item = accept_detection(
                detection,
                catalog_id=request.data.get("catalog_id"),
                add_to_library=request.data.get("add_to_library", True),
            )
        except ReviewError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_review_payload(request, detection, library_item))

    @action(detail=True, methods=["post"])
    def correct(self, request, pk=None):
        detection = self.get_object()
        try:
            detection, library_item = correct_detection(
                detection,
                title=request.data.get("title", ""),
                author=request.data.get("author", ""),
                catalog_id=request.data.get("catalog_id"),
                add_to_library=request.data.get("add_to_library", True),
            )
        except ReviewError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_review_payload(request, detection, library_item))

    @action(detail=True, methods=["post"])
    def discard(self, request, pk=None):
        detection = discard_detection(self.get_object())
        return Response(_review_payload(request, detection, None))


class LibraryItemViewSet(viewsets.ModelViewSet):
    queryset = LibraryItem.objects.select_related("catalog_book").all()
    serializer_class = LibraryItemSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def create(self, request, *args, **kwargs):
        """
        Accept either a plain library row or {detection_id, ...} to confirm
        from a scan detection.
        """
        detection_id = request.data.get("detection_id")
        if detection_id:
            try:
                detection = DetectedBook.objects.select_related("matched_book").get(
                    pk=detection_id
                )
            except DetectedBook.DoesNotExist:
                return Response(
                    {"detail": "detection not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            try:
                detection, library_item = accept_detection(
                    detection,
                    catalog_id=request.data.get("catalog_id"),
                    add_to_library=True,
                )
            except ReviewError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            return Response(
                LibraryItemSerializer(library_item, context={"request": request}).data,
                status=status.HTTP_201_CREATED,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


def _review_payload(request, detection, library_item):
    payload = {
        "detection": DetectedBookSerializer(detection, context={"request": request}).data,
    }
    if library_item is not None:
        payload["library_item"] = LibraryItemSerializer(
            library_item, context={"request": request}
        ).data
    else:
        payload["library_item"] = None
    return payload


def _scan_summary(scan: Scan) -> dict:
    detections = list(scan.detections.all())
    high = low = unmatched = ocr_failed = 0
    pending_review = 0
    for det in detections:
        if det.review_status == DetectedBook.ReviewStatus.PENDING:
            pending_review += 1
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
        "needs_review": pending_review,
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
