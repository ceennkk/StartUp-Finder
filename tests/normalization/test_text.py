from __future__ import annotations

from datetime import UTC, datetime, timezone, timedelta

from app.normalization.text import clean_text, name_key, normalize_doi, strip_html
from app.utils.dates import parse_datetime
from app.utils.hashing import content_hash, deterministic_external_id


def test_clean_text() -> None:
    assert clean_text("  a \n b\t") == "a b"
    assert clean_text("   ") is None
    assert clean_text(None) is None


def test_strip_html() -> None:
    assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_name_key_is_accent_and_case_insensitive() -> None:
    assert name_key("Müller") == name_key("MULLER")


def test_normalize_doi() -> None:
    assert normalize_doi("https://doi.org/10.1000/ABC") == "10.1000/abc"
    assert normalize_doi(None) is None


def test_parse_datetime_to_utc() -> None:
    assert parse_datetime("2024-05-01T12:00:00+02:00") == datetime(2024, 5, 1, 10, tzinfo=UTC)
    assert parse_datetime("2024-05-01T12:00:00Z") == datetime(2024, 5, 1, 12, tzinfo=UTC)
    assert parse_datetime("2024-05-01") == datetime(2024, 5, 1, tzinfo=UTC)
    assert parse_datetime("not a date") is None
    assert parse_datetime("") is None
    assert parse_datetime(None) is None


def test_content_hash_ignores_key_order_and_excluded_keys() -> None:
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})
    assert content_hash({"a": 1, "s": 5}, frozenset({"s"})) == content_hash({"a": 1, "s": 9}, frozenset({"s"}))


def test_deterministic_external_id_is_stable() -> None:
    assert deterministic_external_id("Title", "2024") == deterministic_external_id(" title ", "2024")
    assert deterministic_external_id("a", None) != deterministic_external_id("a", "b")
