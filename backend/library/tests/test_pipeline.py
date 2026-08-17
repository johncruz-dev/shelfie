"""API tests for the scan pipeline (detect → OCR → match), fully mocked."""

from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

import numpy as np
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from library.models import CatalogBook, DetectedBook, Scan
from library.vision.gemini_ocr import SpineOCRResult
from library.vision.spine_detect import SpineDetection


def _jpeg_bytes(color=(40, 80, 120), size=(240, 160)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def catalog(db):
    return CatalogBook.objects.create(
        catalog_id="CAT-036",
        title="Dune",
        author="Frank Herbert",
        alternate_titles="",
    )


@pytest.mark.django_db
def test_create_scan_requires_image(api):
    response = api.post("/api/scans/", {}, format="multipart")
    assert response.status_code == 400
    assert "image" in response.data["detail"].lower()


@pytest.mark.django_db
def test_create_scan_zero_books_completed_gracefully(api):
    upload = SimpleUploadedFile("shelf.jpg", _jpeg_bytes(), content_type="image/jpeg")

    with (
        patch("library.pipeline.detect_spines", return_value=[]),
        patch("library.pipeline.read_spine") as ocr,
    ):
        response = api.post("/api/scans/", {"image": upload}, format="multipart")

    assert response.status_code == 201
    assert response.data["status"] == Scan.Status.COMPLETED
    assert "No books detected" in response.data["error_message"]
    assert response.data["summary"]["detection_count"] == 0
    assert response.data["detections"] == []
    ocr.assert_not_called()


@pytest.mark.django_db
def test_create_scan_pipeline_persists_detections(api, catalog):
    upload = SimpleUploadedFile("shelf.jpg", _jpeg_bytes(), content_type="image/jpeg")
    spines = [
        SpineDetection(x=10, y=5, w=30, h=100, confidence=0.8, source="yolo"),
        SpineDetection(x=50, y=5, w=28, h=100, confidence=0.7, source="yolo"),
    ]
    ocr_results = [
        SpineOCRResult(
            title="Dune",
            author="Frank Herbert",
            confidence=0.95,
            readable=True,
            estimated_cost_usd=0.0001,
            latency_ms=10,
        ),
        SpineOCRResult(
            title="",
            author="",
            confidence=0.0,
            readable=False,
            error="unreadable spine",
            estimated_cost_usd=0.0001,
            latency_ms=8,
        ),
    ]

    with (
        patch("library.pipeline.detect_spines", return_value=spines),
        patch("library.pipeline.read_spine", side_effect=ocr_results),
        patch("library.pipeline.crop_spine", return_value=np.zeros((40, 12, 3), dtype=np.uint8)),
    ):
        response = api.post("/api/scans/", {"image": upload}, format="multipart")

    assert response.status_code == 201
    assert response.data["status"] == Scan.Status.COMPLETED
    assert response.data["summary"]["detection_count"] == 2
    assert response.data["summary"]["high_confidence"] == 1
    assert response.data["summary"]["needs_review"] >= 1

    scan = Scan.objects.get(pk=response.data["id"])
    dets = list(scan.detections.order_by("spine_index"))
    assert len(dets) == 2
    assert dets[0].raw_title == "Dune"
    assert dets[0].matched_book_id == catalog.id
    assert dets[0].review_status == DetectedBook.ReviewStatus.AUTO_ACCEPTED
    assert dets[1].ocr_error == "unreadable spine"
    assert dets[1].review_status == DetectedBook.ReviewStatus.PENDING
    assert scan.estimated_api_cost_usd == Decimal("0.000200")
