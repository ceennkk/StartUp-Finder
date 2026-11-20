"""Manual import of reference lists (people and their organisations) from local CSV/JSON files.

Local files only: no network access, no lookups, no scraping. LinkedIn profile URLs are stored as plain reference
strings that someone else collected; they are never opened. Personal data must never appear in logs or error
messages: only counts, row numbers and field names are reported.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from app.adapters.base import AdapterConfigError, BaseAdapter
from app.config.settings import load_source_config
from app.domain import AliasType, RelationshipType, SourceType, VerificationStatus
from app.ingestion.types import (
    AliasDraft,
    NormalizedBundle,
    RawRecord,
    RelationshipDraft,
    RunResult,
    SourceSpec,
    ValidationProblem,
)
from app.normalization.organizations import organization_draft
from app.normalization.persons import person_draft
from app.normalization.text import clean_text, name_key
from app.utils.dates import parse_datetime, utcnow

log = logging.getLogger(__name__)

DEFAULT_IMPORT_DIR = "data/manual_imports"
PROCESSED_DIR, FAILED_DIR = "processed", "failed"
FIELDS = (
    "linkedin_url", "name", "position", "company", "project_affiliation",
    "verification_status", "verification_method", "checked_at", "notes", "row_id",
)
REQUIRED = ("linkedin_url", "name")
MAX_LENGTH = {"name": 200, "position": 200, "company": 200, "project_affiliation": 500,
              "verification_method": 200, "notes": 1000, "row_id": 100}
_LINKEDIN_HOST = re.compile(r"^(www\.|[a-z]{2}\.)?linkedin\.com$")
_LINKEDIN_SLUG = re.compile(r"^[\w%.\-]{3,100}$")
_SAFE_NAME = re.compile(r"^[a-z_]{1,40}$")


def normalize_linkedin_url(value: str) -> str | None:
    """Canonical https://www.linkedin.com/in/<slug>; purely syntactic, the URL is never requested."""
    parts = urlsplit(value.strip() if "://" in value else "https://" + value.strip())
    if parts.scheme not in ("http", "https") or not _LINKEDIN_HOST.match((parts.hostname or "").lower()):
        return None
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) != 2 or segments[0].lower() != "in":
        return None
    slug = unquote(segments[1]).lower()
    return f"https://www.linkedin.com/in/{slug}" if _LINKEDIN_SLUG.match(slug) else None


def _cell(value: Any) -> str | None | bool:
    """Cleaned text, None for empty cells, False for non-string values."""
    if value is None:
        return None
    if not isinstance(value, str):
        return False
    return clean_text(value)


def validate_row(row: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Return the cleaned row or problems that name fields only, never values."""
    problems: list[str] = []
    unknown = sorted(k for k in row if k not in FIELDS)
    if unknown:
        problems.append("unknown field(s): " + ", ".join(k if _SAFE_NAME.match(str(k)) else "?" for k in unknown))
    cleaned: dict[str, Any] = {}
    for field in FIELDS:
        value = _cell(row.get(field))
        if value is False:
            problems.append(f"{field}: must be text")
            continue
        if value is None and field in REQUIRED:
            problems.append(f"{field}: required")
            continue
        if value is not None and len(value) > MAX_LENGTH.get(field, 1000):
            problems.append(f"{field}: too long")
            continue
        cleaned[field] = value
    if problems:
        return None, problems

    url = normalize_linkedin_url(cleaned["linkedin_url"])
    if url is None:
        return None, ["linkedin_url: not a linkedin.com/in/<profile> URL"]
    cleaned["linkedin_url"] = url

    status = (cleaned.get("verification_status") or VerificationStatus.UNVERIFIED.value).lower()
    if status not in (VerificationStatus.UNVERIFIED.value, VerificationStatus.MANUALLY_VERIFIED.value):
        problems.append("verification_status: must be unverified or manually_verified")
    cleaned["verification_status"] = status
    if cleaned.get("checked_at"):
        checked = parse_datetime(cleaned["checked_at"])
        if checked is None:
            problems.append("checked_at: not an ISO date")
        else:
            cleaned["checked_at"] = checked.date().isoformat()
    if status == VerificationStatus.MANUALLY_VERIFIED.value:
        for field in ("verification_method", "checked_at"):
            if not cleaned.get(field):
                problems.append(f"{field}: required when manually_verified")
    return (None, problems) if problems else (cleaned, [])


def parse_file(content: bytes, extension: str, max_rows: int) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse one file into row dicts; problems never contain file content."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], ["file: not valid UTF-8"]
    try:
        if extension == ".csv":
            rows = list(csv.DictReader(io.StringIO(text, newline=""), skipinitialspace=True))
            if any(None in row for row in rows):
                return [], ["file: rows with more cells than header columns"]
        else:
            data = json.loads(text)
            rows = data.get("records") if isinstance(data, dict) else data
            if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
                return [], ["file: JSON must be a list of objects (or {\"records\": [...]})"]
    except (csv.Error, ValueError):
        return [], ["file: cannot be parsed"]
    if len(rows) > max_rows:
        return [], [f"file: more than {max_rows} rows"]
    return rows, []


class ManualImportAdapter(BaseAdapter):
    name = "manual_import"
    source = SourceSpec(
        source_name="manual_import",
        source_type=SourceType.MANUAL,
        description="Manually supplied reference lists (local CSV/JSON files); no network access.",
    )

    def __init__(self, *args: Any, config: dict[str, Any] | None = None, import_dir: str | Path | None = None,
                 **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.config = config if config is not None else load_source_config("manual_import")
        self.import_dir = Path(import_dir or self.settings.manual_import_dir or DEFAULT_IMPORT_DIR)
        self.extensions = {e.lower() for e in self.config.get("extensions", [".csv", ".json"])}
        if not self.extensions <= {".csv", ".json"}:
            raise AdapterConfigError("manual_import.extensions may only contain .csv and .json")
        self.max_file_bytes = int(self.config.get("max_file_bytes", 5_000_000))
        self.max_rows = int(self.config.get("max_rows_per_file", 5000))
        self.processed_days = int(self.config.get("processed_retention_days", 30))
        self.failed_days = int(self.config.get("failed_retention_days", 14))
        self._digests: dict[Path, str] = {}
        self._rejected: dict[Path, list[str]] = {}
        self._completed: list[Path] = []
        self._failed_files: set[Path] = set()
        self._current: Path | None = None

    # --- reading ----------------------------------------------------------------------------------------

    def _candidates(self) -> list[Path]:
        return sorted(
            p for p in self.import_dir.iterdir()
            if p.is_file() and not p.is_symlink() and not p.name.startswith(".") and p.suffix.lower() in self.extensions
        )

    def fetch(self) -> Iterator[RawRecord]:
        if not self.import_dir.is_dir():
            log.info("manual import directory does not exist; nothing to import")
            return
        files = self._candidates()
        log.info("manual import scan", extra={"files": len(files)})
        for path in files:
            if path.stat().st_size > self.max_file_bytes:
                digest, rows, problems = _size_digest(path), [], ["file: too large"]
            else:
                content = path.read_bytes()
                digest = hashlib.sha256(content).hexdigest()
                rows, problems = parse_file(content, path.suffix.lower(), self.max_rows)
            self._digests[path] = digest
            cleaned_rows: list[dict[str, Any]] = []
            for number, row in enumerate(rows, start=1):
                cleaned, row_problems = validate_row(row)
                if cleaned is None:
                    problems += [f"row {number}: {p}" for p in row_problems]
                else:
                    cleaned["_row"] = number
                    cleaned_rows.append(cleaned)
            if problems:
                self._rejected[path] = problems[:100]
                record = RawRecord(
                    external_id=f"rejected:{digest[:24]}",
                    record_type="rejected_file",
                    payload={"file_sha256": digest, "problem_count": len(problems), "problems": problems[:100]},
                )
                self._current = path
                yield record
                continue
            if not cleaned_rows:
                self._completed.append(path)
            for index, row in enumerate(cleaned_rows):
                if index == len(cleaned_rows) - 1:
                    self._completed.append(path)  # complete once its last row has been handed to the pipeline
                number = row.pop("_row")
                key = hashlib.sha256(f"{row['linkedin_url']}|{name_key(row.get('company') or '')}".encode()).hexdigest()
                record = RawRecord(
                    external_id=key[:24],
                    record_type="reference_person",
                    payload={**row, "import_batch": {"file_sha256": digest, "row": number}},
                    canonical_url=row["linkedin_url"],
                    volatile_keys=frozenset({"import_batch"}),
                )
                self._current = path
                yield record

    # --- normalization -------------------------------------------------------------------------------------

    def normalize(self, raw: RawRecord) -> NormalizedBundle:
        if raw.record_type == "rejected_file":
            raise ValidationProblem(f"file rejected with {raw.payload['problem_count']} problem(s)")
        p = raw.payload
        url = p["linkedin_url"]
        person_id = f"person:{hashlib.sha256(url.encode()).hexdigest()[:16]}"
        person = person_draft(
            key="person",
            identifier=person_id,
            name=p["name"],
            aliases=[AliasDraft(alias=url, alias_type=AliasType.URL)],
            properties={
                "linkedin_url": url,
                "position": p.get("position"),
                "project_affiliation": p.get("project_affiliation"),
                "origin": "manual_import",
            },
            is_primary=True,
        )
        if person is None:
            raise ValidationProblem("person has no name")
        person.extraction_method = "manual_import"
        entities = [person]
        relationships: list[RelationshipDraft] = []
        company = p.get("company")
        if company:
            org_key = f"org:{name_key(company)}"
            org = organization_draft(key=org_key, identifier=org_key, name=company)
            if org is not None:
                org.extraction_method = "manual_import"
                entities.append(org)
                relationships.append(
                    RelationshipDraft(
                        source_key="person",
                        target_key=org_key,
                        relationship_type=RelationshipType.WORKS_AT,
                        verification_status=VerificationStatus(p["verification_status"]),
                        properties={k: v for k, v in {
                            "position": p.get("position"),
                            "verification_method": p.get("verification_method"),
                            "checked_at": p.get("checked_at"),
                        }.items() if v is not None},
                    )
                )
        return NormalizedBundle(entities=entities, relationships=relationships)

    # --- file lifecycle -------------------------------------------------------------------------------------

    def _process(self, repo: Any, session: Any, run_id: Any, raw: RawRecord, result: Any) -> None:
        try:
            super()._process(repo, session, run_id, raw, result)
        except Exception:
            if self._current is not None:
                self._failed_files.add(self._current)
            raise

    def run(self) -> RunResult:
        result = super().run()
        if self.dry_run or not self.import_dir.is_dir():
            return result
        try:
            now = utcnow()
            for path, problems in self._rejected.items():
                self._archive(path, FAILED_DIR, now, problems)
            if result.status != "failed":
                for path in self._completed:
                    if path not in self._failed_files and path not in self._rejected:
                        self._archive(path, PROCESSED_DIR, now)
            self._purge(PROCESSED_DIR, self.processed_days)
            self._purge(FAILED_DIR, self.failed_days)
        except OSError as exc:
            log.warning("manual import file handling failed", extra={"error": type(exc).__name__})
            result.error_message = (result.error_message + "; " if result.error_message else "") + "file handling failed"
        return result

    def _archive(self, path: Path, folder: str, now: Any, problems: list[str] | None = None) -> None:
        if not path.exists():
            return
        target_dir = self.import_dir / folder
        target_dir.mkdir(exist_ok=True)
        stem = f"{now:%Y%m%dT%H%M%SZ}_{self._digests[path][:12]}"
        target = target_dir / f"{stem}{path.suffix.lower()}"
        counter = 1
        while target.exists():
            target = target_dir / f"{stem}_{counter}{path.suffix.lower()}"
            counter += 1
        shutil.move(str(path), target)
        os.utime(target)  # retention counts from the archive date
        if problems:
            target.with_name(target.name + ".problems.txt").write_text("\n".join(problems) + "\n", encoding="utf-8")
        log.info("manual import file archived", extra={"folder": folder, "file_ref": self._digests[path][:12]})

    def _purge(self, folder: str, days: int) -> None:
        directory = self.import_dir / folder
        if not directory.is_dir() or days < 0:
            return
        cutoff = time.time() - days * 86400
        removed = 0
        for item in directory.iterdir():
            if item.is_file() and not item.is_symlink() and item.stat().st_mtime < cutoff:
                item.unlink()
                removed += 1
        if removed:
            log.info("manual import retention purge", extra={"folder": folder, "removed": removed})


def _size_digest(path: Path) -> str:
    """Digest of an oversized file's name and size; its content is not read."""
    return hashlib.sha256(f"{path.name}|{path.stat().st_size}".encode()).hexdigest()
