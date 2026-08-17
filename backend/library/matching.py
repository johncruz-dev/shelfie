"""
Catalog matching: normalize messy OCR/catalog strings and score confidence.

Exact equality fails on this catalog (editions, US/UK titles, author variants,
substring traps). Confidence blends title and author fuzzy scores, with
penalties when a short query is only a substring of a longer catalog title.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Iterable

from django.conf import settings
from rapidfuzz import fuzz

from .models import CatalogBook

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")
_LEADING_ARTICLE_RE = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)
_INITIALS_RE = re.compile(r"\b([A-Za-z])\.")


@dataclass(frozen=True)
class MatchCandidate:
    catalog_id: str
    title: str
    author: str
    confidence: float
    title_score: float
    author_score: float
    matched_via: str  # "title" | "alternate" | "both"

    def to_dict(self) -> dict:
        return asdict(self)


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_title(value: str) -> str:
    text = strip_accents(value or "").lower().replace("&", " and ")
    text = _PUNCT_RE.sub(" ", text)
    text = _LEADING_ARTICLE_RE.sub("", text)
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def normalize_author(value: str) -> str:
    """
    Normalize author forms:
    - accents removed
    - "Last, First" -> "first last"
    - initials with/without periods collapsed
    """
    text = strip_accents(value or "").strip()
    if "," in text:
        last, first = [part.strip() for part in text.split(",", 1)]
        text = f"{first} {last}".strip()
    text = text.lower().replace("&", " and ")
    text = _INITIALS_RE.sub(r"\1", text)  # "j.k." / "j. k." -> "jk" / "j k"
    text = _PUNCT_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    # Collapse spaced single initials: "j k rowling" -> "jk rowling"
    parts = text.split()
    collapsed: list[str] = []
    buffer = ""
    for part in parts:
        if len(part) == 1 and part.isalpha():
            buffer += part
        else:
            if buffer:
                collapsed.append(buffer)
                buffer = ""
            collapsed.append(part)
    if buffer:
        collapsed.append(buffer)
    return " ".join(collapsed)


def _title_similarity(query: str, candidate: str) -> float:
    if not query or not candidate:
        return 0.0
    if query == candidate:
        return 1.0

    ratio = fuzz.token_set_ratio(query, candidate) / 100.0
    partial = fuzz.partial_ratio(query, candidate) / 100.0

    # Prefer full-ish matches; partial alone is dangerous for short titles ("It", "Dune").
    score = 0.65 * ratio + 0.35 * partial

    # Substring length trap: "It" inside "It Can't Happen Here" should not win easily.
    if query in candidate or candidate in query:
        shorter, longer = sorted([query, candidate], key=len)
        length_ratio = len(shorter) / max(len(longer), 1)
        if length_ratio < 0.55:
            score *= 0.55 + 0.45 * length_ratio

    return max(0.0, min(1.0, score))


def _author_similarity(query: str, candidate: str) -> float:
    if not query:
        # OCR often misses author; don't destroy an otherwise strong title match.
        return 0.55
    if not candidate:
        return 0.0
    if query == candidate:
        return 1.0

    # Token set handles order differences and middle-name omissions.
    score = fuzz.token_set_ratio(query, candidate) / 100.0
    # Bonus if surname tokens overlap strongly.
    q_tokens = set(query.split())
    c_tokens = set(candidate.split())
    if q_tokens and c_tokens:
        overlap = len(q_tokens & c_tokens) / len(q_tokens | c_tokens)
        score = 0.75 * score + 0.25 * overlap
    return max(0.0, min(1.0, score))


def _best_title_score(raw_title: str, book: CatalogBook) -> tuple[float, str]:
    query = normalize_title(raw_title)
    best = 0.0
    via = "title"
    primary = _title_similarity(query, normalize_title(book.title))
    best = primary
    for alt in book.alternate_title_list:
        alt_score = _title_similarity(query, normalize_title(alt))
        if alt_score > best:
            best = alt_score
            via = "alternate"
    if via == "alternate" and primary >= best - 0.02:
        via = "both"
    elif via == "title" and book.alternate_title_list and best >= 0.9:
        # High primary match; alts unused but fine.
        via = "title"
    return best, via


def score_book(raw_title: str, raw_author: str, book: CatalogBook) -> MatchCandidate:
    title_score, via = _best_title_score(raw_title, book)
    author_score = _author_similarity(normalize_author(raw_author), normalize_author(book.author))

    # Title carries more weight (spines are title-heavy); author breaks ties / shared titles.
    if raw_author.strip():
        confidence = 0.72 * title_score + 0.28 * author_score
    else:
        confidence = 0.85 * title_score + 0.15 * author_score

    # Soft penalty when title is weak even if author is strong (common name collisions).
    if title_score < 0.55:
        confidence *= 0.85

    confidence = round(max(0.0, min(1.0, confidence)), 4)
    return MatchCandidate(
        catalog_id=book.catalog_id,
        title=book.title,
        author=book.author,
        confidence=confidence,
        title_score=round(title_score, 4),
        author_score=round(author_score, 4),
        matched_via=via,
    )


def match_book(
    raw_title: str,
    raw_author: str = "",
    *,
    catalog: Iterable[CatalogBook] | None = None,
    limit: int = 5,
) -> list[MatchCandidate]:
    """Return top catalog candidates sorted by confidence (desc)."""
    books = list(catalog) if catalog is not None else list(CatalogBook.objects.all())
    if not (raw_title or "").strip() and not (raw_author or "").strip():
        return []

    scored = [score_book(raw_title, raw_author, book) for book in books]
    scored.sort(key=lambda c: (c.confidence, c.title_score, c.author_score), reverse=True)
    return scored[: max(1, limit)]


def classify_confidence(confidence: float) -> str:
    high = getattr(settings, "MATCH_HIGH_CONFIDENCE", 0.82)
    low = getattr(settings, "MATCH_LOW_CONFIDENCE", 0.45)
    if confidence >= high:
        return "high"
    if confidence >= low:
        return "low"
    return "unmatched"
