from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

import cv2
import numpy as np
from django.conf import settings

# Rough Gemini 2.5 Flash paid rates used for *estimates* in README / Scan records.
# Free tier is $0; we still report an equivalent paid estimate for grading.
_FLASH_INPUT_PER_MTOK = 0.15
_FLASH_OUTPUT_PER_MTOK = 0.60
# ~258 tokens per image tile is Gemini's documented ballpark for default media resolution.
_IMAGE_TOKEN_ESTIMATE = 258
_PROMPT_TOKEN_ESTIMATE = 120


SPINE_OCR_PROMPT = """You are reading text printed on a single book spine photo.
Return ONLY a JSON object with this shape:
{
  "title": "string or empty",
  "author": "string or empty",
  "readable": true,
  "confidence": 0.0
}

Rules:
- confidence is 0..1 for how sure you are of the title/author text.
- If the spine is blank, blurry, sideways-unreadable, or not a book, set readable=false,
  title="", author="", confidence=0.
- Do not invent famous books. Prefer empty strings over guesses.
- Prefer the main title, not series subtitles unless that is all that appears.
"""


@dataclass(frozen=True)
class SpineOCRResult:
    title: str = ""
    author: str = ""
    confidence: float | None = None
    readable: bool = False
    error: str = ""
    raw_text: str = ""
    latency_ms: int = 0
    estimated_cost_usd: float = 0.0
    input_tokens_est: int = 0
    output_tokens_est: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_cost_usd(*, input_tokens: int, output_tokens: int) -> float:
    return round(
        (input_tokens / 1_000_000) * _FLASH_INPUT_PER_MTOK
        + (output_tokens / 1_000_000) * _FLASH_OUTPUT_PER_MTOK,
        6,
    )


def _encode_image(image: np.ndarray | bytes, *, mime: str = "image/jpeg") -> tuple[bytes, str]:
    if isinstance(image, (bytes, bytearray)):
        return bytes(image), mime
    if not isinstance(image, np.ndarray) or image.size == 0:
        raise ValueError("empty spine image")
    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        raise ValueError("failed to encode spine image")
    return buf.tobytes(), "image/jpeg"


def _extract_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty model response")

    # Strip common markdown fences.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("malformed JSON from model")
        data = json.loads(text[start : end + 1])

    if not isinstance(data, dict):
        raise ValueError("model JSON was not an object")
    return data


def _parse_ocr_payload(data: dict[str, Any]) -> tuple[str, str, bool, float | None]:
    title = str(data.get("title") or "").strip()
    author = str(data.get("author") or "").strip()
    readable = data.get("readable")
    if readable is None:
        readable = bool(title or author)
    else:
        readable = bool(readable)

    confidence = data.get("confidence")
    conf_val: float | None
    try:
        conf_val = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        conf_val = None
    if conf_val is not None:
        conf_val = max(0.0, min(1.0, conf_val))

    if not readable:
        return "", "", False, conf_val if conf_val is not None else 0.0
    return title, author, True, conf_val


def read_spine(
    image: np.ndarray | bytes,
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout_sec: float | None = None,
) -> SpineOCRResult:
    """
    OCR one spine crop with Gemini.

    Always returns SpineOCRResult — check `.error` / `.readable` instead of try/except.
    """
    key = (api_key if api_key is not None else getattr(settings, "GEMINI_API_KEY", "")) or ""
    model_name = model or getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")
    timeout = timeout_sec if timeout_sec is not None else float(
        getattr(settings, "GEMINI_TIMEOUT_SEC", 30)
    )

    if not key.strip():
        return SpineOCRResult(error="GEMINI_API_KEY not configured")

    try:
        image_bytes, mime = _encode_image(image)
    except Exception as exc:
        return SpineOCRResult(error=f"image encode failed: {exc}")

    input_tokens = _PROMPT_TOKEN_ESTIMATE + _IMAGE_TOKEN_ESTIMATE
    started = time.perf_counter()

    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        return SpineOCRResult(error=f"google-genai import failed: {exc}")

    try:
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=model_name,
            contents=[
                types.Part.from_text(text=SPINE_OCR_PROMPT),
                types.Part.from_bytes(data=image_bytes, mime_type=mime),
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                http_options=types.HttpOptions(timeout=int(timeout * 1000)),
            ),
        )
    except Exception as exc:
        latency = int((time.perf_counter() - started) * 1000)
        name = type(exc).__name__.lower()
        msg = str(exc).lower()
        if "timeout" in name or "timeout" in msg or "timed out" in msg:
            err = f"model timeout after {timeout:.0f}s"
        else:
            err = f"gemini request failed: {exc}"
        return SpineOCRResult(
            error=err,
            latency_ms=latency,
            input_tokens_est=input_tokens,
            estimated_cost_usd=estimate_cost_usd(input_tokens=input_tokens, output_tokens=0),
        )

    latency = int((time.perf_counter() - started) * 1000)
    raw = (getattr(response, "text", None) or "").strip()
    output_tokens = max(1, len(raw) // 4)

    # Prefer provider usage metadata when present.
    usage = getattr(response, "usage_metadata", None)
    if usage is not None:
        prompt_tokens = getattr(usage, "prompt_token_count", None) or input_tokens
        candidates = getattr(usage, "candidates_token_count", None) or output_tokens
        input_tokens = int(prompt_tokens)
        output_tokens = int(candidates)

    cost = estimate_cost_usd(input_tokens=input_tokens, output_tokens=output_tokens)

    try:
        data = _extract_json_object(raw)
        title, author, readable, confidence = _parse_ocr_payload(data)
    except Exception as exc:
        return SpineOCRResult(
            error=f"malformed JSON from model: {exc}",
            raw_text=raw[:2000],
            latency_ms=latency,
            estimated_cost_usd=cost,
            input_tokens_est=input_tokens,
            output_tokens_est=output_tokens,
        )

    if not readable or not (title or author):
        return SpineOCRResult(
            title=title,
            author=author,
            confidence=confidence if confidence is not None else 0.0,
            readable=False,
            error="unreadable spine",
            raw_text=raw[:2000],
            latency_ms=latency,
            estimated_cost_usd=cost,
            input_tokens_est=input_tokens,
            output_tokens_est=output_tokens,
        )

    return SpineOCRResult(
        title=title,
        author=author,
        confidence=confidence,
        readable=True,
        raw_text=raw[:2000],
        latency_ms=latency,
        estimated_cost_usd=cost,
        input_tokens_est=input_tokens,
        output_tokens_est=output_tokens,
    )


def read_spines(images: list[np.ndarray | bytes]) -> list[SpineOCRResult]:
    """OCR many spine crops sequentially (keeps free-tier RPM simpler)."""
    return [read_spine(image) for image in images]
