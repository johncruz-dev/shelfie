from rest_framework import serializers

from .models import CatalogBook, DetectedBook, LibraryItem, Scan


class CatalogBookSerializer(serializers.ModelSerializer):
    class Meta:
        model = CatalogBook
        fields = [
            "id",
            "catalog_id",
            "title",
            "author",
            "alternate_titles",
            "isbn13",
            "year",
            "edition_notes",
            "series",
            "ambiguity_tag",
        ]


class DetectedBookSerializer(serializers.ModelSerializer):
    matched_book = CatalogBookSerializer(read_only=True)

    class Meta:
        model = DetectedBook
        fields = [
            "id",
            "spine_index",
            "bbox_json",
            "crop_image",
            "raw_title",
            "raw_author",
            "ocr_confidence",
            "ocr_error",
            "matched_book",
            "match_confidence",
            "match_candidates_json",
            "review_status",
            "corrected_title",
            "corrected_author",
        ]


class ScanSerializer(serializers.ModelSerializer):
    detections = DetectedBookSerializer(many=True, read_only=True)

    class Meta:
        model = Scan
        fields = [
            "id",
            "image",
            "status",
            "error_message",
            "latency_ms",
            "estimated_api_cost_usd",
            "created_at",
            "updated_at",
            "detections",
        ]
        read_only_fields = [
            "status",
            "error_message",
            "latency_ms",
            "estimated_api_cost_usd",
            "created_at",
            "updated_at",
            "detections",
        ]


class LibraryItemSerializer(serializers.ModelSerializer):
    catalog_book = CatalogBookSerializer(read_only=True)

    class Meta:
        model = LibraryItem
        fields = [
            "id",
            "title",
            "author",
            "notes",
            "catalog_book",
            "source_detection",
            "created_at",
        ]
        read_only_fields = ["created_at"]
