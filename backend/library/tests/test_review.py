"""Tests for human-in-the-loop review and library persistence."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from library.models import CatalogBook, DetectedBook, LibraryItem, Scan


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def catalog(db):
    return CatalogBook.objects.create(
        catalog_id="CAT-036",
        title="Dune",
        author="Frank Herbert",
    )


@pytest.fixture
def other_book(db):
    return CatalogBook.objects.create(
        catalog_id="CAT-037",
        title="Dune Messiah",
        author="Frank Herbert",
    )


@pytest.fixture
def detection(db, catalog):
    scan = Scan.objects.create(
        image=SimpleUploadedFile("shelf.jpg", b"fake", content_type="image/jpeg"),
        status=Scan.Status.COMPLETED,
    )
    return DetectedBook.objects.create(
        scan=scan,
        spine_index=0,
        raw_title="Dune",
        raw_author="Frank Herbert",
        matched_book=catalog,
        match_confidence=0.91,
        review_status=DetectedBook.ReviewStatus.AUTO_ACCEPTED,
        match_candidates_json=[
            {
                "catalog_id": catalog.catalog_id,
                "title": catalog.title,
                "author": catalog.author,
                "confidence": 0.91,
            }
        ],
    )


@pytest.fixture
def pending_detection(db, catalog):
    scan = Scan.objects.create(
        image=SimpleUploadedFile("shelf2.jpg", b"fake", content_type="image/jpeg"),
        status=Scan.Status.COMPLETED,
    )
    return DetectedBook.objects.create(
        scan=scan,
        spine_index=0,
        raw_title="Dune Mess",
        raw_author="F Herbert",
        matched_book=catalog,
        match_confidence=0.55,
        review_status=DetectedBook.ReviewStatus.PENDING,
    )


@pytest.mark.django_db
def test_accept_detection_adds_library_item(api, detection, catalog):
    response = api.post(f"/api/detections/{detection.id}/accept/", {}, format="json")
    assert response.status_code == 200
    assert response.data["detection"]["review_status"] == "accepted"
    assert response.data["library_item"]["title"] == "Dune"
    assert LibraryItem.objects.filter(source_detection=detection).count() == 1


@pytest.mark.django_db
def test_correct_detection_saves_edits(api, pending_detection, other_book):
    response = api.post(
        f"/api/detections/{pending_detection.id}/correct/",
        {
            "title": "Dune Messiah",
            "author": "Frank Herbert",
            "catalog_id": other_book.catalog_id,
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.data["detection"]["review_status"] == "corrected"
    assert response.data["detection"]["corrected_title"] == "Dune Messiah"
    assert response.data["library_item"]["title"] == "Dune Messiah"
    assert response.data["library_item"]["catalog_book"]["catalog_id"] == "CAT-037"


@pytest.mark.django_db
def test_discard_detection_does_not_add_library(api, pending_detection):
    response = api.post(
        f"/api/detections/{pending_detection.id}/discard/", {}, format="json"
    )
    assert response.status_code == 200
    assert response.data["detection"]["review_status"] == "discarded"
    assert response.data["library_item"] is None
    assert LibraryItem.objects.count() == 0


@pytest.mark.django_db
def test_accept_high_confidence_bulk(api, detection):
    response = api.post(
        f"/api/scans/{detection.scan_id}/accept-high-confidence/", {}, format="json"
    )
    assert response.status_code == 200
    assert response.data["accepted"] == 1
    assert LibraryItem.objects.count() == 1


@pytest.mark.django_db
def test_library_list(api, detection):
    api.post(f"/api/detections/{detection.id}/accept/", {}, format="json")
    response = api.get("/api/library/")
    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["title"] == "Dune"
