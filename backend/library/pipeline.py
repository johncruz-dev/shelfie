"""
End-to-end scan pipeline: local detect → Gemini OCR → catalog match.

Called synchronously from POST /api/scans/ for the take-home (simple to demo).
Individual spine failures become DetectedBook.ocr_error rows — they do not crash
the whole scan unless the source image itself cannot be read.
"""

from __future__ import annotations

import time
from decimal import Decimal

import cv2
import numpy as np
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction

from .matching import classify_confidence, match_book
from .models import CatalogBook, DetectedBook, Scan
from .vision.gemini_ocr import read_spine
from .vision.spine_detect import crop_spine, detect_spines


def _bgr_from_scan_image(scan: Scan) -> np.ndarray:
    scan.image.open("rb")
    try:
        data = np.frombuffer(scan.image.read(), dtype=np.uint8)
    finally:
        scan.image.close()
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("uploaded image could not be decoded")
    return bgr


def _save_crop(detection: DetectedBook, crop_bgr: np.ndarray, index: int) -> None:
    ok, buf = cv2.imencode(".jpg", crop_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        return
    detection.crop_image.save(
        f"spine_{scan_id_safe(detection)}_{index}.jpg",
        ContentFile(buf.tobytes()),
        save=False,
    )


def scan_id_safe(detection: DetectedBook) -> str:
    return str(detection.scan_id or "scan")


def _review_status_for_confidence(confidence: float | None) -> str:
    if confidence is None:
        return DetectedBook.ReviewStatus.PENDING
    band = classify_confidence(confidence)
    if band == "high":
        return DetectedBook.ReviewStatus.AUTO_ACCEPTED
    return DetectedBook.ReviewStatus.PENDING


@transaction.atomic
def process_scan(scan: Scan) -> Scan:
    """
    Run detection → OCR → matching for an existing Scan with an uploaded image.

    Always leaves the Scan in completed or failed — never an uncaught blank state.
    """
    started = time.perf_counter()
    scan.status = Scan.Status.PROCESSING
    scan.error_message = ""
    scan.save(update_fields=["status", "error_message", "updated_at"])

    total_cost = Decimal("0")
    catalog = list(CatalogBook.objects.all())

    try:
        bgr = _bgr_from_scan_image(scan)
    except Exception as exc:
        scan.status = Scan.Status.FAILED
        scan.error_message = f"Could not read image: {exc}"
        scan.latency_ms = int((time.perf_counter() - started) * 1000)
        scan.save(
            update_fields=["status", "error_message", "latency_ms", "updated_at"]
        )
        return scan

    try:
        spines = detect_spines(bgr)
    except Exception as exc:
        scan.status = Scan.Status.FAILED
        scan.error_message = f"Spine detection failed: {exc}"
        scan.latency_ms = int((time.perf_counter() - started) * 1000)
        scan.save(
            update_fields=["status", "error_message", "latency_ms", "updated_at"]
        )
        return scan

    if not spines:
        scan.status = Scan.Status.COMPLETED
        scan.error_message = "No books detected in this photo. Try a clearer shelf shot."
        scan.latency_ms = int((time.perf_counter() - started) * 1000)
        scan.estimated_api_cost_usd = Decimal("0")
        scan.save(
            update_fields=[
                "status",
                "error_message",
                "latency_ms",
                "estimated_api_cost_usd",
                "updated_at",
            ]
        )
        return scan

    # Cap spines so free-tier Gemini RPM / demo time stay predictable.
    max_spines = int(getattr(settings, "SCAN_MAX_SPINES", 20))
    spines = spines[:max_spines]

    for index, spine in enumerate(spines):
        crop = crop_spine(bgr, spine)
        detection = DetectedBook(
            scan=scan,
            spine_index=index,
            bbox_json=spine.to_bbox_dict(),
            review_status=DetectedBook.ReviewStatus.PENDING,
        )

        ocr = read_spine(crop)
        total_cost += Decimal(str(ocr.estimated_cost_usd or 0))

        detection.raw_title = (ocr.title or "")[:512]
        detection.raw_author = (ocr.author or "")[:512]
        detection.ocr_confidence = ocr.confidence
        detection.ocr_error = (ocr.error or "")[:512]

        if ocr.readable and (ocr.title or ocr.author):
            candidates = match_book(
                ocr.title,
                ocr.author,
                catalog=catalog,
                limit=5,
            )
            detection.match_candidates_json = [c.to_dict() for c in candidates]
            if candidates:
                top = candidates[0]
                detection.match_confidence = top.confidence
                matched = next(
                    (b for b in catalog if b.catalog_id == top.catalog_id),
                    None,
                )
                detection.matched_book = matched
                detection.review_status = _review_status_for_confidence(top.confidence)
            else:
                detection.match_confidence = 0.0
                detection.review_status = DetectedBook.ReviewStatus.PENDING
        else:
            # Unreadable / OCR error → still shown in review, never silently dropped.
            detection.match_confidence = None
            detection.review_status = DetectedBook.ReviewStatus.PENDING
            if not detection.ocr_error:
                detection.ocr_error = "unreadable spine"

        detection.save()
        try:
            _save_crop(detection, crop, index)
            detection.save(update_fields=["crop_image"])
        except Exception:
            # Crop persistence is nice-to-have; don't fail the scan.
            pass

    scan.status = Scan.Status.COMPLETED
    scan.latency_ms = int((time.perf_counter() - started) * 1000)
    scan.estimated_api_cost_usd = total_cost
    if not scan.error_message:
        scan.error_message = ""
    scan.save(
        update_fields=[
            "status",
            "error_message",
            "latency_ms",
            "estimated_api_cost_usd",
            "updated_at",
        ]
    )
    return scan
