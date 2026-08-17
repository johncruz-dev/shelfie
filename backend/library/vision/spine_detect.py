"""
Local spine detection (CPU).

Routing:
- Primary: pretrained YOLOv4-tiny (COCO) via OpenCV DNN — class "book" (73).
  Off-the-shelf Darknet weights; no training/fine-tuning; CPU only.
- Fallback: OpenCV vertical-edge projection when YOLO finds nothing useful
  on a dense upright shelf (common when COCO "book" fires as one blob).

Hosted Gemini is not used here — this stage only localizes crops for later VLM OCR.
"""

from __future__ import annotations

import urllib.request
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from django.conf import settings

COCO_BOOK_CLASS = 73

# Official AlexeyAB / YOLO darknet tiny weights (COCO 80-class).
_YOLO_CFG_URL = (
    "https://raw.githubusercontent.com/AlexeyAB/darknet/master/cfg/yolov4-tiny.cfg"
)
_YOLO_WEIGHTS_URL = (
    "https://github.com/AlexeyAB/darknet/releases/download/darknet_yolo_v4_pre/"
    "yolov4-tiny.weights"
)


@dataclass(frozen=True)
class SpineDetection:
    x: int
    y: int
    w: int
    h: int
    confidence: float
    source: str  # "yolo" | "opencv_fallback"

    def to_bbox_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def xyxy(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.x + self.w, self.y + self.h


class SpineDetectionError(Exception):
    """Unrecoverable I/O problems only — never raised for zero books."""


def _models_dir() -> Path:
    configured = getattr(settings, "SPINE_MODEL_DIR", None)
    if configured:
        path = Path(configured)
    else:
        path = Path(settings.BASE_DIR) / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)


def ensure_yolo_files() -> tuple[Path, Path]:
    root = _models_dir()
    cfg = root / "yolov4-tiny.cfg"
    weights = root / "yolov4-tiny.weights"
    _download(_YOLO_CFG_URL, cfg)
    _download(_YOLO_WEIGHTS_URL, weights)
    return cfg, weights


def _load_bgr(image: str | Path | np.ndarray) -> np.ndarray:
    if isinstance(image, np.ndarray):
        if image.ndim == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        return image
    path = Path(image)
    if not path.exists():
        raise SpineDetectionError(f"Image not found: {path}")
    bgr = cv2.imread(str(path))
    if bgr is None:
        raise SpineDetectionError(f"Failed to read image: {path}")
    return bgr


@lru_cache(maxsize=1)
def _get_yolo_net():
    cfg, weights = ensure_yolo_files()
    net = cv2.dnn.readNetFromDarknet(str(cfg), str(weights))
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    return net


def _yolo_output_names(net) -> list[str]:
    layers = net.getLayerNames()
    try:
        out_layers = net.getUnconnectedOutLayers()
        # OpenCV may return scalar or nested indices depending on version.
        indices = [int(i) for i in np.array(out_layers).reshape(-1)]
    except Exception:
        indices = []
    return [layers[i - 1] for i in indices]


def _nms(
    boxes: list[list[int]],
    scores: list[float],
    conf: float,
    iou: float,
) -> list[int]:
    if not boxes:
        return []
    idxs = cv2.dnn.NMSBoxes(boxes, scores, conf, iou)
    if idxs is None or len(idxs) == 0:
        return []
    return [int(i) for i in np.array(idxs).reshape(-1)]


def _yolo_book_boxes(
    bgr: np.ndarray,
    *,
    conf: float,
    iou: float,
) -> list[SpineDetection]:
    net = _get_yolo_net()
    h, w = bgr.shape[:2]
    blob = cv2.dnn.blobFromImage(
        bgr,
        scalefactor=1 / 255.0,
        size=(416, 416),
        mean=(0, 0, 0),
        swapRB=True,
        crop=False,
    )
    net.setInput(blob)
    outputs = net.forward(_yolo_output_names(net))

    boxes: list[list[int]] = []
    scores: list[float] = []

    for output in outputs:
        for detection in output:
            class_scores = detection[5:]
            class_id = int(np.argmax(class_scores))
            score = float(class_scores[class_id])
            if class_id != COCO_BOOK_CLASS or score < conf:
                continue
            cx, cy, bw, bh = detection[0:4]
            x = int((cx - bw / 2) * w)
            y = int((cy - bh / 2) * h)
            box_w = int(bw * w)
            box_h = int(bh * h)
            x = max(0, x)
            y = max(0, y)
            box_w = min(box_w, w - x)
            box_h = min(box_h, h - y)
            if box_w < 8 or box_h < 8:
                continue
            boxes.append([x, y, box_w, box_h])
            scores.append(score)

    keep = _nms(boxes, scores, conf, iou)
    detections = [
        SpineDetection(
            x=boxes[i][0],
            y=boxes[i][1],
            w=boxes[i][2],
            h=boxes[i][3],
            confidence=round(scores[i], 4),
            source="yolo",
        )
        for i in keep
    ]
    return _sort_left_to_right(detections)


def _opencv_vertical_spines(
    bgr: np.ndarray,
    *,
    min_spine_width_ratio: float = 0.02,
    max_spines: int = 40,
) -> list[SpineDetection]:
    """
    Split an upright shelf row into vertical strips via a vertical-edge profile.
    Used only when YOLO returns nothing useful.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    if w < 32 or h < 32:
        return []

    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    sobelx = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3)
    energy = np.abs(sobelx).mean(axis=0)
    kernel = max(5, w // 80 | 1)
    energy = np.convolve(energy, np.ones(kernel) / kernel, mode="same")

    threshold = float(np.percentile(energy, 35))
    inside = energy <= threshold

    segments: list[tuple[int, int]] = []
    start = None
    for i, flag in enumerate(inside):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            segments.append((start, i))
            start = None
    if start is not None:
        segments.append((start, w))

    min_w = max(12, int(w * min_spine_width_ratio))
    max_w = int(w * 0.35)
    y0, y1 = int(h * 0.05), int(h * 0.95)
    detections: list[SpineDetection] = []

    for x0, x1 in segments:
        bw = x1 - x0
        if bw < min_w or bw > max_w:
            continue
        detections.append(
            SpineDetection(
                x=x0,
                y=y0,
                w=bw,
                h=y1 - y0,
                confidence=0.35,
                source="opencv_fallback",
            )
        )
        if len(detections) >= max_spines:
            break

    return _sort_left_to_right(detections)


def _sort_left_to_right(dets: list[SpineDetection]) -> list[SpineDetection]:
    return sorted(dets, key=lambda d: (d.x, d.y))


def _coverage_ratio(det: SpineDetection, image_area: int) -> float:
    return (det.w * det.h) / max(image_area, 1)


def detect_spines(
    image: str | Path | np.ndarray,
    *,
    conf: float | None = None,
    iou: float | None = None,
    use_yolo: bool = True,
    use_opencv_fallback: bool = True,
) -> list[SpineDetection]:
    """
    Detect book / spine regions.

    Empty list = zero books found (normal product outcome, not an error).
    """
    bgr = _load_bgr(image)
    h, w = bgr.shape[:2]
    image_area = h * w

    yolo_conf = conf if conf is not None else float(
        getattr(settings, "SPINE_YOLO_CONF", 0.25)
    )
    yolo_iou = iou if iou is not None else float(
        getattr(settings, "SPINE_YOLO_IOU", 0.45)
    )

    detections: list[SpineDetection] = []
    if use_yolo:
        try:
            detections = _yolo_book_boxes(bgr, conf=yolo_conf, iou=yolo_iou)
        except Exception:
            detections = []

    needs_fallback = False
    if use_opencv_fallback:
        if not detections:
            needs_fallback = True
        elif len(detections) == 1 and _coverage_ratio(detections[0], image_area) > 0.55:
            needs_fallback = True

    if needs_fallback:
        fallback = _opencv_vertical_spines(bgr)
        if fallback:
            detections = fallback

    return detections


def crop_spine(bgr: np.ndarray, det: SpineDetection, pad: float = 0.02) -> np.ndarray:
    h, w = bgr.shape[:2]
    pad_x = int(det.w * pad)
    pad_y = int(det.h * pad)
    x1 = max(0, det.x - pad_x)
    y1 = max(0, det.y - pad_y)
    x2 = min(w, det.x + det.w + pad_x)
    y2 = min(h, det.y + det.h + pad_y)
    return bgr[y1:y2, x1:x2].copy()


def crop_all_spines(
    image: str | Path | np.ndarray,
    detections: list[SpineDetection] | None = None,
) -> list[tuple[SpineDetection, np.ndarray]]:
    bgr = _load_bgr(image)
    dets = detections if detections is not None else detect_spines(bgr)
    return [(det, crop_spine(bgr, det)) for det in dets]
