from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def content_hash(payload: dict[str, Any], exclude_keys: frozenset[str] = frozenset()) -> str:
    data = {k: v for k, v in payload.items() if k not in exclude_keys}
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def deterministic_external_id(*parts: str | None) -> str:
    """Stable identifier for records without a source ID, derived from normalized key fields."""
    joined = "\x1f".join((p or "").strip().casefold() for p in parts)
    return "h:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:40]
