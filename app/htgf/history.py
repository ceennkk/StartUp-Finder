from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from app.htgf.assessment import assess

SCHEMA_VERSION = "1.0"


def digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def load_history(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "candidates": {}}
    history = read_json(path)
    if history.get("schema_version") != SCHEMA_VERSION or not isinstance(history.get("candidates"), dict):
        raise ValueError("Invalid or unsupported HTGF history")
    for candidate_id, versions in history["candidates"].items():
        if not isinstance(candidate_id, str) or not isinstance(versions, list):
            raise ValueError("Invalid HTGF history entries")
        for version in versions:
            if not isinstance(version, dict) or version.get("candidate_id") != candidate_id:
                raise ValueError(f"Invalid HTGF history entry for {candidate_id}")
            if not all(key in version for key in ("assessment_id", "input_sha256", "assessment_date", "assessed_at")):
                raise ValueError(f"Incomplete HTGF history entry for {candidate_id}")
    return history


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with lock_path.open("a+b") as file:
        if os.name == "nt":
            import msvcrt

            if file.tell() == 0:
                file.write(b"\0")
                file.flush()
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def append_history(path: Path, inputs: list[dict[str, Any]], source_state: dict[str, Any]) -> tuple[dict[str, Any], int]:
    if len({item.get("candidate_id") for item in inputs}) != len(inputs):
        raise ValueError("Duplicate candidate IDs in assessment input")
    with locked(path):
        history = load_history(path)
        added = 0
        for item in inputs:
            result = assess(item)
            candidate_id = result["candidate_id"]
            if candidate_id not in source_state:
                raise ValueError(f"Missing input state for {candidate_id}")
            input_state = {"assessment_input": item, "source_state": source_state[candidate_id]}
            fingerprint = digest(input_state)
            versions = history["candidates"].setdefault(candidate_id, [])
            if any(existing["input_sha256"] == fingerprint for existing in versions):
                continue
            result.update({
                "schema_version": SCHEMA_VERSION,
                "assessment_id": f"htgf-{fingerprint}",
                "assessed_at": datetime.now(UTC).isoformat(),
                "input_sha256": fingerprint,
                "input_state": input_state,
            })
            versions.append(result)
            added += 1
        if added:
            atomic_write(path, json.dumps(history, ensure_ascii=False, indent=2) + "\n")
        return history, added
