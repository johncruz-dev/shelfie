from django.contrib import admin

from .models import CatalogBook, DetectedBook, LibraryItem, Scan


@admin.register(CatalogBook)
class CatalogBookAdmin(admin.ModelAdmin):
    list_display = ("catalog_id", "title", "author", "year", "ambiguity_tag")
    search_fields = ("catalog_id", "title", "author", "isbn13", "alternate_titles")
    list_filter = ("ambiguity_tag",)


class DetectedBookInline(admin.TabularInline):
    model = DetectedBook
    extra = 0
    fields = (
        "spine_index",
        "raw_title",
        "raw_author",
        "matched_book",
        "match_confidence",
        "review_status",
    )
    readonly_fields = ("spine_index", "raw_title", "raw_author", "match_confidence")


@admin.register(Scan)
class ScanAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "latency_ms", "estimated_api_cost_usd", "created_at")
    list_filter = ("status",)
    inlines = [DetectedBookInline]


@admin.register(DetectedBook)
class DetectedBookAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "scan",
        "raw_title",
        "raw_author",
        "matched_book",
        "match_confidence",
        "review_status",
    )
    list_filter = ("review_status",)


@admin.register(LibraryItem)
class LibraryItemAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "author", "catalog_book", "created_at")
    search_fields = ("title", "author")
