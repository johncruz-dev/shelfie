"""Generate synthetic bookshelf photos for pipeline / demo testing."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "photos"


def _spine(width: int, height: int, color, label: str) -> np.ndarray:
    img = np.full((height, width, 3), color, dtype=np.uint8)
    # Edge lines between spines
    img[:, 0:2] = (20, 20, 20)
    img[:, -2:] = (20, 20, 20)
    # Fake title text rotated vertically (drawn horizontal then rotate)
    canvas = np.full((width, height, 3), color, dtype=np.uint8)
    cv2.putText(
        canvas,
        label[:18],
        (8, height // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (245, 245, 245),
        1,
        cv2.LINE_AA,
    )
    rotated = cv2.rotate(canvas, cv2.ROTATE_90_COUNTERCLOCKWISE)
    # Blend text onto spine
    mask = np.any(rotated < 240, axis=2)
    img[mask] = rotated[mask]
    return img


def make_shelf(
    name: str,
    books: list[tuple[str, tuple[int, int, int]]],
    *,
    width: int = 960,
    height: int = 640,
) -> Path:
    shelf = np.full((height, width, 3), (48, 36, 28), dtype=np.uint8)
    # wood planks
    for y in (40, height - 40):
        cv2.rectangle(shelf, (20, y - 8), (width - 20, y + 8), (70, 52, 38), -1)

    n = len(books)
    usable_w = width - 80
    spine_w = max(28, usable_w // n - 4)
    spine_h = height - 120
    x = 40
    for label, color in books:
        w = spine_w + (6 if len(label) > 12 else 0)
        w = min(w, 90)
        patch = _spine(w, spine_h, color, label)
        y0 = (height - spine_h) // 2
        shelf[y0 : y0 + spine_h, x : x + w] = patch
        x += w + 3
        if x + 40 >= width:
            break

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    cv2.imwrite(str(path), shelf, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    return path


def main() -> None:
    paths = [
        make_shelf(
            "shelf_popular_mix.jpg",
            [
                ("1984", (40, 40, 40)),
                ("DUNE", (30, 90, 160)),
                ("HOBBIT", (40, 110, 70)),
                ("SAPIENS", (180, 120, 50)),
                ("IT", (90, 30, 30)),
                ("GATSBY", (50, 70, 140)),
                ("ALCHEMIST", (160, 100, 40)),
                ("MARTIAN", (200, 90, 40)),
            ],
        ),
        make_shelf(
            "shelf_tolkien_row.jpg",
            [
                ("HOBBIT", (55, 95, 55)),
                ("FELLOWSHIP", (70, 50, 30)),
                ("TWO TOWERS", (90, 60, 35)),
                ("RETURN KING", (60, 40, 25)),
                ("LOTR OMNI", (35, 35, 35)),
            ],
            width=800,
            height=560,
        ),
        make_shelf(
            "shelf_ambiguous.jpg",
            [
                ("THE ROAD", (55, 55, 55)),
                ("INFERNO", (120, 40, 40)),
                ("INFERNO", (40, 40, 120)),  # Brown vs Dante collision bait
                ("CARRIE", (150, 50, 70)),
                ("CARRIE SOTO", (80, 100, 140)),
                ("TWILIGHT", (30, 30, 50)),
            ],
            width=900,
            height=600,
        ),
        # Nearly empty / hard case
        make_shelf(
            "shelf_sparse.jpg",
            [("QUIET", (90, 90, 110))],
            width=640,
            height=480,
        ),
    ]
    for path in paths:
        print(f"Wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
