"""Human-in-the-loop review helpers for detected spines."""

from __future__ import annotations

from django.db import transaction

from .models import CatalogBook, DetectedBook, LibraryItem


class ReviewError(ValueError):
    pass


def _resolve_catalog(catalog_id: str | int | None) -> CatalogBook | None:
    if catalog_id in (None, ""):
        return None
    try:
        if isinstance(catalog_id, int) or str(catalog_id).isdigit():
            return CatalogBook.objects.get(pk=int(catalog_id))
        return CatalogBook.objects.get(catalog_id=str(catalog_id))
    except CatalogBook.DoesNotExist as exc:
        raise ReviewError(f"Catalog book not found: {catalog_id}") from exc


def _library_title_author(
    detection: DetectedBook,
    *,
    title: str | None = None,
    author: str | None = None,
) -> tuple[str, str]:
    catalog = detection.matched_book
    final_title = (
        (title or "").strip()
        or (detection.corrected_title or "").strip()
        or (catalog.title if catalog else "")
        or (detection.raw_title or "").strip()
    )
    final_author = (
        (author or "").strip()
        or (detection.corrected_author or "").strip()
        or (catalog.author if catalog else "")
        or (detection.raw_author or "").strip()
    )
    if not final_title:
        raise ReviewError("Cannot add to library without a title")
    return final_title, final_author


@transaction.atomic
def accept_detection(
    detection: DetectedBook,
    *,
    catalog_id: str | int | None = None,
    add_to_library: bool = True,
) -> tuple[DetectedBook, LibraryItem | None]:
    """Confirm a detection (high-confidence or user-approved match)."""
    if catalog_id is not None:
        detection.matched_book = _resolve_catalog(catalog_id)

    if detection.matched_book is None and not (detection.raw_title or detection.corrected_title):
        raise ReviewError("Nothing to accept — no match and no title")

    detection.review_status = DetectedBook.ReviewStatus.ACCEPTED
    detection.save(update_fields=["matched_book", "review_status"])

    library_item = None
    if add_to_library:
        library_item = _upsert_library_item(detection)
    return detection, library_item


@transaction.atomic
def correct_detection(
    detection: DetectedBook,
    *,
    title: str = "",
    author: str = "",
    catalog_id: str | int | None = None,
    add_to_library: bool = True,
) -> tuple[DetectedBook, LibraryItem | None]:
    """User corrects OCR / match, then optionally saves to library."""
    title = (title or "").strip()
    author = (author or "").strip()
    if not title and catalog_id is None and detection.matched_book is None:
        raise ReviewError("Provide a title or a catalog_id when correcting")

    if catalog_id is not None:
        detection.matched_book = _resolve_catalog(catalog_id)

    if title:
        detection.corrected_title = title[:512]
    if author or title:
        detection.corrected_author = author[:512]

    detection.review_status = DetectedBook.ReviewStatus.CORRECTED
    detection.save(
        update_fields=[
            "matched_book",
            "corrected_title",
            "corrected_author",
            "review_status",
        ]
    )

    library_item = None
    if add_to_library:
        library_item = _upsert_library_item(detection, title=title or None, author=author or None)
    return detection, library_item


@transaction.atomic
def discard_detection(detection: DetectedBook) -> DetectedBook:
    """Explicitly discard — never silent drop."""
    detection.review_status = DetectedBook.ReviewStatus.DISCARDED
    detection.save(update_fields=["review_status"])
    # Remove any library items created earlier from this detection.
    LibraryItem.objects.filter(source_detection=detection).delete()
    return detection


def _upsert_library_item(
    detection: DetectedBook,
    *,
    title: str | None = None,
    author: str | None = None,
) -> LibraryItem:
    final_title, final_author = _library_title_author(detection, title=title, author=author)
    existing = LibraryItem.objects.filter(source_detection=detection).first()
    if existing:
        existing.title = final_title
        existing.author = final_author
        existing.catalog_book = detection.matched_book
        existing.save(update_fields=["title", "author", "catalog_book"])
        return existing
    return LibraryItem.objects.create(
        title=final_title,
        author=final_author,
        catalog_book=detection.matched_book,
        source_detection=detection,
    )


@transaction.atomic
def accept_high_confidence(scan_id: int) -> dict:
    """Bulk-add auto_accepted detections from a scan into the library."""
    detections = list(
        DetectedBook.objects.filter(
            scan_id=scan_id,
            review_status=DetectedBook.ReviewStatus.AUTO_ACCEPTED,
        ).select_related("matched_book")
    )
    added = 0
    for detection in detections:
        accept_detection(detection, add_to_library=True)
        added += 1
    return {"accepted": added, "scan_id": scan_id}
