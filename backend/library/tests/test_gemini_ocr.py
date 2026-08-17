"""Tests for Gemini spine OCR — mocked network, real JSON/error handling."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from library.vision.gemini_ocr import (
    SpineOCRResult,
    _extract_json_object,
    estimate_cost_usd,
    read_spine,
)


@pytest.fixture
def tiny_spine():
    return np.full((80, 20, 3), 180, dtype=np.uint8)


def test_estimate_cost_positive():
    assert estimate_cost_usd(input_tokens=258 + 120, output_tokens=40) > 0


def test_extract_json_object_plain_and_fenced():
    assert _extract_json_object('{"title": "Dune", "author": "Frank Herbert"}')["title"] == "Dune"
    fenced = '```json\n{"title": "It", "author": "Stephen King", "readable": true, "confidence": 0.9}\n```'
    assert _extract_json_object(fenced)["author"] == "Stephen King"


def test_extract_json_object_rejects_garbage():
    with pytest.raises(ValueError):
        _extract_json_object("not json at all")


def test_missing_api_key_returns_error(tiny_spine, settings):
    settings.GEMINI_API_KEY = ""
    result = read_spine(tiny_spine)
    assert isinstance(result, SpineOCRResult)
    assert result.error == "GEMINI_API_KEY not configured"
    assert result.readable is False


def test_successful_ocr(tiny_spine, settings):
    settings.GEMINI_API_KEY = "test-key"
    settings.GEMINI_MODEL = "gemini-2.5-flash"

    fake_response = MagicMock()
    fake_response.text = (
        '{"title": "The Hobbit", "author": "J.R.R. Tolkien", '
        '"readable": true, "confidence": 0.93}'
    )
    fake_response.usage_metadata = MagicMock(
        prompt_token_count=400,
        candidates_token_count=50,
    )

    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response

    with patch("google.genai.Client", return_value=fake_client):
        result = read_spine(tiny_spine)

    assert result.error == ""
    assert result.readable is True
    assert result.title == "The Hobbit"
    assert result.author == "J.R.R. Tolkien"
    assert result.confidence == pytest.approx(0.93)
    assert result.estimated_cost_usd > 0
    assert result.latency_ms >= 0


def test_malformed_json_is_graceful(tiny_spine, settings):
    settings.GEMINI_API_KEY = "test-key"
    fake_response = MagicMock()
    fake_response.text = "sure, the book is probably dune by frank"
    fake_response.usage_metadata = None
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response

    with patch("google.genai.Client", return_value=fake_client):
        result = read_spine(tiny_spine)

    assert result.readable is False
    assert "malformed JSON" in result.error
    assert result.raw_text.startswith("sure")


def test_timeout_is_graceful(tiny_spine, settings):
    settings.GEMINI_API_KEY = "test-key"
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = TimeoutError("timed out")

    with patch("google.genai.Client", return_value=fake_client):
        result = read_spine(tiny_spine, timeout_sec=1)

    assert result.readable is False
    assert "timeout" in result.error.lower()


def test_unreadable_spine_flag(tiny_spine, settings):
    settings.GEMINI_API_KEY = "test-key"
    fake_response = MagicMock()
    fake_response.text = '{"title": "", "author": "", "readable": false, "confidence": 0}'
    fake_response.usage_metadata = None
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response

    with patch("google.genai.Client", return_value=fake_client):
        result = read_spine(tiny_spine)

    assert result.readable is False
    assert result.error == "unreadable spine"
