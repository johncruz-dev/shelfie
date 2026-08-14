from django.db import models


class CatalogBook(models.Model):
    """Canonical catalog entry loaded from catalog.csv."""

    catalog_id = models.CharField(max_length=32, unique=True)
    title = models.CharField(max_length=512)
    author = models.CharField(max_length=512)
    alternate_titles = models.TextField(
        blank=True,
        help_text="Pipe-separated synonyms / alternate titles",
    )
    isbn13 = models.CharField(max_length=32, blank=True)
    year = models.CharField(max_length=16, blank=True)
    edition_notes = models.TextField(blank=True)
    series = models.CharField(max_length=256, blank=True)
    ambiguity_tag = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["catalog_id"]

    def __str__(self) -> str:
        return f"{self.catalog_id}: {self.title} — {self.author}"

    @property
    def alternate_title_list(self) -> list[str]:
        if not self.alternate_titles.strip():
            return []
        return [part.strip() for part in self.alternate_titles.split("|") if part.strip()]


class Scan(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    image = models.ImageField(upload_to="scans/%Y/%m/%d/")
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING,
    )
    error_message = models.TextField(blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    estimated_api_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Scan {self.pk} ({self.status})"


class DetectedBook(models.Model):
    """One spine read from a scan, optionally matched to the catalog."""

    class ReviewStatus(models.TextChoices):
        PENDING = "pending", "Needs review"
        ACCEPTED = "accepted", "Accepted"
        CORRECTED = "corrected", "Corrected"
        DISCARDED = "discarded", "Discarded"
        AUTO_ACCEPTED = "auto_accepted", "Auto-accepted (high confidence)"

    scan = models.ForeignKey(Scan, related_name="detections", on_delete=models.CASCADE)
    spine_index = models.PositiveIntegerField(default=0)
    bbox_json = models.JSONField(
        default=dict,
        blank=True,
        help_text="Bounding box from local detector: {x,y,w,h} or similar",
    )
    crop_image = models.ImageField(upload_to="crops/%Y/%m/%d/", blank=True, null=True)

    raw_title = models.CharField(max_length=512, blank=True)
    raw_author = models.CharField(max_length=512, blank=True)
    ocr_confidence = models.FloatField(null=True, blank=True)
    ocr_error = models.CharField(max_length=512, blank=True)

    matched_book = models.ForeignKey(
        CatalogBook,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="detections",
    )
    match_confidence = models.FloatField(null=True, blank=True)
    match_candidates_json = models.JSONField(
        default=list,
        blank=True,
        help_text="Top alternate catalog candidates for review UI",
    )

    review_status = models.CharField(
        max_length=32,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
    )
    corrected_title = models.CharField(max_length=512, blank=True)
    corrected_author = models.CharField(max_length=512, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["spine_index", "id"]

    def __str__(self) -> str:
        label = self.raw_title or "(unread spine)"
        return f"Detection {self.pk}: {label}"


class LibraryItem(models.Model):
    """A book the user confirmed into their personal library."""

    catalog_book = models.ForeignKey(
        CatalogBook,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="library_items",
    )
    source_detection = models.ForeignKey(
        DetectedBook,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="library_items",
    )
    title = models.CharField(max_length=512)
    author = models.CharField(max_length=512, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.title} — {self.author}"
