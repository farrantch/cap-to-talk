"""Hotword and glossary helpers."""

from __future__ import annotations

import re
from pathlib import Path

from rapidfuzz import fuzz, process


def load_terms(
    path: Path,
    *,
    max_terms: int | None = None,
    max_chars: int | None = None,
    max_term_length: int = 128,
) -> list[str]:
    if not path.exists():
        return []

    terms: list[str] = []
    seen: set[str] = set()
    total_chars = 0

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            term = line.strip()
            if not term or term.startswith("#") or len(term) > max_term_length:
                continue

            key = term.casefold()
            if key in seen:
                continue
            if max_terms is not None and len(terms) >= max_terms:
                break
            if max_chars is not None and total_chars + len(term) > max_chars:
                break

            seen.add(key)
            terms.append(term)
            total_chars += len(term)

    return terms


def glossary_normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def select_relevant_terms(
    text: str,
    master_terms: list[str],
    *,
    max_terms: int = 8,
) -> list[str]:
    transcript = glossary_normalize(text)
    if not transcript or not master_terms:
        return []

    padded_transcript = f" {transcript} "
    tokens = transcript.split()
    chunks = [
        " ".join(tokens[index : index + size])
        for size in (1, 2, 3, 4)
        for index in range(len(tokens) - size + 1)
    ]
    fuzzy_terms = [
        term
        for term in master_terms
        if len(re.sub(r"[^a-z0-9]", "", term.lower())) >= 5
    ]
    scores: dict[str, float] = {}

    for term in master_terms:
        normalized = glossary_normalize(term)
        if normalized and f" {normalized} " in padded_transcript:
            scores[term] = 100.0

    for chunk in chunks:
        matches = process.extract(
            chunk,
            fuzzy_terms,
            scorer=fuzz.ratio,
            processor=glossary_normalize,
            score_cutoff=76.0,
            limit=4,
        )
        for term, score, _ in matches:
            scores[term] = max(score, scores.get(term, 0.0))

    ranked = sorted(scores.items(), key=lambda item: (-item[1], len(item[0])))
    return [term for term, _ in ranked[:max_terms]]
