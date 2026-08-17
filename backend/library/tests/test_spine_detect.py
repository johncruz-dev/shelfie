"""Tests for local spine detection (OpenCV fallback + YOLO wiring)."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from library.vision.spine_detect import (
    SpineDetection,
    SpineDetectionError,
    crop_spine,
    detect_spines,
)


def _striped_shelf(width=400, height=200, spines=6) -> np.ndarray:
    """Synthetic upright spines: alternating gray bars with dark gaps."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    spine_w = width // spines
    for i in range(spines):
        x0 = i * spine_w + 2
        x1 = (i + 1) * spine_w - 2
        shade = 80 + (i * 25) % 120
        img[:, x0:x1] = (shade, shade, shade)
        img[:, x0] = 20
        img[:, x1] = 20
    return img


def test_opencv_fallback_finds_multiple_spines_on_synthetic_shelf():
    img = _striped_shelf()
    dets = detect_spines(img, use_yolo=False, use_opencv_fallback=True)
    assert len(dets) >= 3
    assert all(d.source == "opencv_fallback" for d in dets)
    xs = [d.x for d in dets]
    assert xs == sorted(xs)


def test_zero_books_returns_empty_not_raise():
    blank = np.full((120, 160, 3), 200, dtype=np.uint8)
    dets = detect_spines(blank, use_yolo=False, use_opencv_fallback=True)
    assert dets == []


def test_missing_file_raises_detection_error(tmp_path):
    with pytest.raises(SpineDetectionError):
        detect_spines(tmp_path / "nope.jpg", use_yolo=False)


def test_crop_spine_respects_bounds():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    det = SpineDetection(x=10, y=10, w=30, h=50, confidence=0.9, source="yolo")
    crop = crop_spine(img, det, pad=0.0)
    assert crop.shape == (50, 30, 3)


def test_yolo_path_used_when_available():
    img = _striped_shelf()

    # One COCO "book" detection in YOLO output format: [cx,cy,w,h,obj, ...80 class scores]
    # Values are normalized 0-1 relative to network input; decoder scales by image size.
    row = np.zeros(85, dtype=np.float32)
    row[0:4] = [0.1, 0.5, 0.08, 0.9]  # box in center-left
    row[5 + 73] = 0.91  # book class score

    fake_net = MagicMock()
    fake_net.getLayerNames.return_value = ["a", "b", "out"]
    fake_net.getUnconnectedOutLayers.return_value = np.array([3])
    fake_net.forward.return_value = [np.array([row])]

    with (
        patch("library.vision.spine_detect._get_yolo_net", return_value=fake_net),
        patch("library.vision.spine_detect._yolo_output_names", return_value=["out"]),
    ):
        dets = detect_spines(img, use_yolo=True, use_opencv_fallback=False)

    assert len(dets) == 1
    assert dets[0].source == "yolo"
    assert dets[0].confidence == pytest.approx(0.91, abs=1e-3)
    fake_net.setInput.assert_called_once()


def test_giant_yolo_blob_triggers_opencv_fallback():
    img = _striped_shelf(width=400, height=200, spines=5)
    row = np.zeros(85, dtype=np.float32)
    row[0:4] = [0.5, 0.5, 0.98, 0.98]  # almost full-frame
    row[5 + 73] = 0.95

    fake_net = MagicMock()
    fake_net.forward.return_value = [np.array([row])]

    with (
        patch("library.vision.spine_detect._get_yolo_net", return_value=fake_net),
        patch("library.vision.spine_detect._yolo_output_names", return_value=["out"]),
    ):
        dets = detect_spines(img, use_yolo=True, use_opencv_fallback=True)

    assert len(dets) >= 3
    assert all(d.source == "opencv_fallback" for d in dets)
