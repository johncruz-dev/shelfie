import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from library.models import CatalogBook


class Command(BaseCommand):
    help = "Load catalog.csv into CatalogBook (upsert by catalog_id)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            type=str,
            default=str(settings.CATALOG_CSV_PATH),
            help="Path to catalog.csv",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete existing catalog rows before loading",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"Catalog file not found: {path}")

        if options["clear"]:
            deleted, _ = CatalogBook.objects.all().delete()
            self.stdout.write(f"Cleared {deleted} existing catalog rows.")

        created = 0
        updated = 0

        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            required = {"catalog_id", "title", "author"}
            if not required.issubset(set(reader.fieldnames or [])):
                raise CommandError(
                    f"catalog.csv missing required columns {required}; got {reader.fieldnames}"
                )

            for row in reader:
                catalog_id = (row.get("catalog_id") or "").strip()
                if not catalog_id:
                    continue

                defaults = {
                    "title": (row.get("title") or "").strip(),
                    "author": (row.get("author") or "").strip(),
                    "alternate_titles": (row.get("alternate_titles") or "").strip(),
                    "isbn13": (row.get("isbn13") or "").strip(),
                    "year": (row.get("year") or "").strip(),
                    "edition_notes": (row.get("edition_notes") or "").strip(),
                    "series": (row.get("series") or "").strip(),
                    "ambiguity_tag": (row.get("ambiguity_tag") or "").strip(),
                }
                _, was_created = CatalogBook.objects.update_or_create(
                    catalog_id=catalog_id,
                    defaults=defaults,
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Catalog load complete: {created} created, {updated} updated "
                f"({CatalogBook.objects.count()} total)."
            )
        )
