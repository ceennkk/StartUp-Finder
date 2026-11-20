from __future__ import annotations

from typing import Any

from app.normalization.text import clean_text


def abstract_from_inverted_index(index: dict[str, list[int]] | None) -> str | None:
    """Rebuild abstract text from an OpenAlex inverted index; None when the source has no abstract."""
    if not index:
        return None
    words: dict[int, str] = {}
    for word, positions in index.items():
        for pos in positions:
            words[pos] = word
    return clean_text(" ".join(words[i] for i in sorted(words)))


def compact(mapping: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in mapping.items() if v not in (None, [], {}, "")}
