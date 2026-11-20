from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def stable_id(kind: str, identity: dict[str, Any]) -> str:
    """Build a reproducible identifier from an explicitly chosen immutable identity."""
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", kind) or not identity:
        raise ValueError("A valid identifier kind and nonempty identity are required")
    try:
        canonical = json.dumps(
            identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("Identifier identity must be JSON serializable") from exc
    return f"{kind}:{hashlib.sha256(canonical).hexdigest()}"
