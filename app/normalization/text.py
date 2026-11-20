from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

_WS = re.compile(r"\s+")


def clean_text(value: str | None) -> str | None:
    """NFC-normalize and collapse whitespace. Empty input becomes None; nothing is invented."""
    if value is None:
        return None
    text = _WS.sub(" ", unicodedata.normalize("NFC", value)).strip()
    return text or None


def strip_html(value: str | None) -> str | None:
    if not value:
        return None
    return clean_text(BeautifulSoup(value, "html.parser").get_text(" "))


def name_key(value: str) -> str:
    """Case/accent-insensitive comparison key, for alias lookup only (never for merging entities)."""
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _WS.sub(" ", stripped).strip().casefold()


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
            break
    return doi.lower() or None
