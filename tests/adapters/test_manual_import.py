"""Manual import adapter: synthetic data only, no network, no personal data in logs/errors."""
from __future__ import annotations

import json
import logging
import os
import socket
import time
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.adapters import registry
from app.adapters.base import AdapterConfigError
from app.adapters.manual_import import ManualImportAdapter, normalize_linkedin_url, validate_row
from app.config.settings import Settings, load_source_config
from app.database.models import Entity, Relationship, Signal, SourceRecord, SourceRecordRevision
from app.http.client import PoliteHttpClient
from tests.helpers import FakeAdapter

SETTINGS = Settings(_env_file=None)
HEADER = "linkedin_url,name,position,company,project_affiliation,verification_status,verification_method,checked_at,notes\n"
CSV = HEADER + (
    "https://www.linkedin.com/in/erika-beispiel-test,Erika Beispiel,Lead Engineer,Beispiel Robotics GmbH,Projekt Alpha,unverified,,,PRIVATE_NOTE_MARKER\n"
    "linkedin.com/in/max-muster-test/,Max Muster,CTO,beispiel robotics gmbh,,manually_verified,manual profile review,2026-11-01,\n"
    "https://de.linkedin.com/in/lena-probe-test?trk=x,Lena Probe,,Andere Firma AG,,,,,\n"
)
JSON_FILE = json.dumps([{"linkedin_url": "https://www.linkedin.com/in/ola-demo-test", "name": "Ola Demo", "company": "Andere Firma AG"}])
PII_MARKERS = ["Erika", "Beispiel", "Max Muster", "Lena", "Ola Demo", "Robotics", "Andere Firma", "erika-beispiel-test",
               "max-muster-test", "lena-probe-test", "ola-demo-test", "PRIVATE_NOTE_MARKER", "Geheim", "geheim@example.org"]


def blocked_client() -> PoliteHttpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"manual import must not use the network: {request.url.host}")

    return PoliteHttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None)


@pytest.fixture
def no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: object, **_k: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def make(directory: Path, factory=None, dry_run: bool | None = None, limit: int | None = None, **config) -> ManualImportAdapter:
    return ManualImportAdapter(factory, http=blocked_client(), settings=SETTINGS, import_dir=directory, limit=limit,
                               config={**load_source_config("manual_import"), **config},
                               dry_run=factory is None if dry_run is None else dry_run)


def write(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def names(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.is_file())


def assert_no_pii(*texts: str) -> None:
    for text in texts:
        for marker in PII_MARKERS:
            assert marker not in text, f"personal data leaked: {marker[:3]}..."


# --- configuration and validation -----------------------------------------------------------------------


def test_config_registry_and_defaults(tmp_path: Path) -> None:
    cfg = load_source_config("manual_import")
    assert cfg["extensions"] == [".csv", ".json"] and cfg["processed_retention_days"] > 0 and cfg["failed_retention_days"] > 0
    assert registry.get_adapter_class("manual_import") is ManualImportAdapter
    assert Settings(_env_file=None).manual_import_dir is None
    assert Settings(_env_file=None, manual_import_dir="x").manual_import_dir == "x"
    with pytest.raises(AdapterConfigError):
        make(tmp_path, extensions=[".csv", ".xlsx"])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.linkedin.com/in/Erika-Test/", "https://www.linkedin.com/in/erika-test"),
        ("linkedin.com/in/erika-test?utm=1#x", "https://www.linkedin.com/in/erika-test"),
        ("http://de.linkedin.com/in/erika-test", "https://www.linkedin.com/in/erika-test"),
        ("https://www.linkedin.com/company/acme", None),
        ("https://www.linkedin.com/in/ab", None),
        ("https://evil.example.com/in/erika-test", None),
        ("https://linkedin.com.evil.example/in/erika-test", None),
        ("ftp://www.linkedin.com/in/erika-test", None),
        ("not a url", None),
    ],
)
def test_linkedin_url_validation_is_syntactic(raw: str, expected: str | None) -> None:
    assert normalize_linkedin_url(raw) == expected


def test_row_validation_reports_fields_never_values() -> None:
    ok, problems = validate_row({"linkedin_url": "linkedin.com/in/erika-test", "name": " Erika  Beispiel "})
    assert problems == [] and ok["name"] == "Erika Beispiel" and ok["verification_status"] == "unverified"
    assert validate_row({"name": "Erika Beispiel"})[1] == ["linkedin_url: required"]
    assert "unknown field(s): email" in validate_row({"linkedin_url": "linkedin.com/in/erika-test", "name": "E", "email": "a@b.c"})[1][0]
    _, verified = validate_row({"linkedin_url": "linkedin.com/in/erika-test", "name": "E", "verification_status": "manually_verified"})
    assert verified == ["verification_method: required when manually_verified", "checked_at: required when manually_verified"]
    assert validate_row({"linkedin_url": "linkedin.com/in/erika-test", "name": "E", "verification_status": "source_asserted"})[1]
    assert validate_row({"linkedin_url": "linkedin.com/in/erika-test", "name": 5})[1] == ["name: must be text"]
    assert validate_row({"linkedin_url": "linkedin.com/in/erika-test", "name": "x" * 500})[1] == ["name: too long"]
    problems = validate_row({"linkedin_url": "https://example.com/Erika", "name": "Erika Beispiel"})[1]
    assert_no_pii(*problems)


# --- no network, missing directory, dry run -----------------------------------------------------------


def test_missing_directory_is_an_empty_success(tmp_path: Path) -> None:
    result = make(tmp_path / "nope").run()
    assert (result.status, result.records_fetched) == ("success", 0)


def test_dry_run_validates_without_network_or_file_changes(tmp_path: Path, no_socket: None) -> None:
    write(tmp_path, "people.csv", CSV)
    write(tmp_path, "more.json", JSON_FILE)
    write(tmp_path, "bad.csv", "linkedin_url,name\nhttps://example.com/p/x,Geheim Person\n")
    before = names(tmp_path)
    result = make(tmp_path).run()
    assert (result.status, result.records_fetched, result.records_failed, result.dry_run) == ("partial", 5, 1, True)
    assert names(tmp_path) == before and not (tmp_path / "processed").exists() and not (tmp_path / "failed").exists()


def test_only_top_level_files_with_allowed_extensions_are_read(tmp_path: Path) -> None:
    write(tmp_path, "people.csv", CSV)
    write(tmp_path, "notes.txt", "ignored")
    write(tmp_path, ".hidden.csv", CSV)
    write(tmp_path / "sub", "nested.csv", CSV)
    assert make(tmp_path).run().records_fetched == 3


# --- persistence ----------------------------------------------------------------------------------------


@pytest.mark.db
def test_import_is_idempotent_archives_files_and_models_people(session_factory, tmp_path: Path, no_socket: None) -> None:
    write(tmp_path, "erika_beispiel_list.csv", CSV)
    write(tmp_path, "more.json", JSON_FILE)
    first = make(tmp_path, session_factory).run()
    assert (first.status, first.records_created, first.records_failed) == ("success", 4, 0)
    assert names(tmp_path) == [] and all(
        "erika" not in p.name.lower() and "more" not in p.name for p in (tmp_path / "processed").iterdir()
    )
    assert len(names(tmp_path / "processed")) == 2

    with session_factory() as s:
        people = s.execute(select(Entity).where(Entity.entity_type == "person")).scalars().all()
        orgs = s.execute(select(Entity).where(Entity.entity_type == "organization")).scalars().all()
        assert len(people) == 4 and len(orgs) == 2  # same company spelled differently shares one source-scoped entity
        assert s.execute(select(func.count()).select_from(Signal)).scalar_one() == 0
        rels = s.execute(select(Relationship)).scalars().all()
        assert sorted(r.verification_status for r in rels) == ["manually_verified"] + ["unverified"] * 3
        verified = next(r for r in rels if r.verification_status == "manually_verified")
        assert verified.properties == {"position": "CTO", "verification_method": "manual profile review", "checked_at": "2026-11-01"}
        assert all(r.source_record_id is not None for r in rels)
        assert all(p.properties["origin"] == "manual_import" for p in people)

    # the same content again, under another file name, changes nothing
    write(tmp_path, "renamed.csv", CSV)
    again = make(tmp_path, session_factory).run()
    assert (again.status, again.records_created, again.records_updated, again.records_unchanged) == ("success", 0, 0, 3)
    with session_factory() as s:
        assert s.execute(select(func.count()).select_from(SourceRecord)).scalar_one() == 4
        assert s.execute(select(func.count()).select_from(SourceRecordRevision)).scalar_one() == 0
        assert s.execute(select(func.count()).select_from(Entity)).scalar_one() == 6


@pytest.mark.db
def test_dry_run_with_database_writes_nothing(session_factory, tmp_path: Path) -> None:
    write(tmp_path, "people.csv", CSV)
    result = make(tmp_path, session_factory, dry_run=True).run()
    assert (result.status, result.records_fetched) == ("success", 3)
    with session_factory() as s:
        assert s.execute(select(func.count()).select_from(SourceRecord)).scalar_one() == 0
        assert s.execute(select(func.count()).select_from(Entity)).scalar_one() == 0
    assert names(tmp_path) == ["people.csv"]


@pytest.mark.db
def test_rejected_files_go_to_failed_with_a_pii_free_reason_and_nothing_is_imported_from_them(
    session_factory, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    write(tmp_path, "good.csv", CSV)
    write(tmp_path, "extra_column.csv", "linkedin_url,name,email\nhttps://www.linkedin.com/in/geheim-test,Geheim Person,geheim@example.org\n")
    write(tmp_path, "bad_url.csv", "linkedin_url,name\nhttps://example.com/p/x,Geheim Person\n")
    write(tmp_path, "broken.json", '{"records": [{"name": "Geheim Person"')
    with caplog.at_level(logging.DEBUG):
        result = make(tmp_path, session_factory).run()
    assert (result.status, result.exit_code, result.records_failed) == ("partial", 10, 3)
    assert names(tmp_path) == []  # good file archived; rejected files moved out of the import root
    failed = names(tmp_path / "failed")
    assert len(failed) == 6 and sum(n.endswith(".problems.txt") for n in failed) == 3
    reasons = "\n".join((tmp_path / "failed" / n).read_text(encoding="utf-8") for n in failed if n.endswith(".problems.txt"))
    assert "unknown field(s): email" in reasons and "linkedin_url: not a linkedin.com/in/<profile> URL" in reasons
    assert_no_pii(reasons, result.error_message or "", caplog.text, repr([r.__dict__ for r in caplog.records]))
    with session_factory() as s:
        persons = s.execute(select(Entity).where(Entity.entity_type == "person")).scalars().all()
        assert len(persons) == 3  # only the valid file
        stored = json.dumps([r.raw_payload for r in s.execute(select(SourceRecord)).scalars() if r.record_type == "rejected_file"])
        assert stored.count("problem_count") == 3
        assert_no_pii(stored)


@pytest.mark.db
def test_no_pii_in_logs_for_a_successful_import(session_factory, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    write(tmp_path, "people.csv", CSV)
    with caplog.at_level(logging.DEBUG):
        result = make(tmp_path, session_factory).run()
    assert result.status == "success"
    assert_no_pii(caplog.text, repr([r.__dict__ for r in caplog.records]), result.model_dump_json())


@pytest.mark.db
def test_file_stays_in_place_when_a_record_fails_or_the_limit_cuts_it(session_factory, tmp_path: Path, monkeypatch) -> None:
    write(tmp_path, "people.csv", CSV)
    adapter = make(tmp_path, session_factory)
    original = adapter.normalize

    def flaky(raw):
        if "max-muster" in raw.payload["linkedin_url"]:
            raise ValueError("boom")
        return original(raw)

    monkeypatch.setattr(adapter, "normalize", flaky)
    result = adapter.run()
    assert (result.status, result.records_failed) == ("partial", 1)
    assert names(tmp_path) == ["people.csv"] and not (tmp_path / "processed").exists()

    limited = make(tmp_path, session_factory, limit=1).run()
    assert limited.records_fetched == 1 and names(tmp_path) == ["people.csv"]

    full = make(tmp_path, session_factory).run()  # retry succeeds and archives the file
    assert full.status == "success" and names(tmp_path) == [] and len(names(tmp_path / "processed")) == 1


@pytest.mark.db
def test_retention_removes_only_old_archived_files(session_factory, tmp_path: Path) -> None:
    for folder, age_days in (("processed", 45), ("processed", 1), ("failed", 20), ("failed", 2)):
        path = write(tmp_path / folder, f"{folder}_{age_days}.csv", "x")
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
    keep = write(tmp_path, "keep.txt", "not an import file")
    result = make(tmp_path, session_factory).run()
    assert result.status == "success"
    assert names(tmp_path / "processed") == ["processed_1.csv"] and names(tmp_path / "failed") == ["failed_2.csv"]
    assert keep.exists()
    dry = make(tmp_path, session_factory, dry_run=True, processed_retention_days=0).run()
    assert dry.status == "success" and names(tmp_path / "processed") == ["processed_1.csv"]


@pytest.mark.db
def test_people_are_never_matched_to_entities_of_other_sources(session_factory, tmp_path: Path) -> None:
    other = FakeAdapter(session_factory, [{"id": "1", "name": "r", "owner": "Erika Beispiel", "stars": 1}])
    assert other.run().status == "success"
    write(tmp_path, "people.csv", CSV)
    assert make(tmp_path, session_factory).run().status == "success"
    with session_factory() as s:
        same_name = s.execute(select(Entity).where(Entity.canonical_name == "Erika Beispiel")).scalars().all()
        assert len(same_name) == 2  # one per source; no automatic merge
        sources = s.execute(select(Relationship)).scalars().all()
        assert all(r.source_record_id is not None for r in sources)
