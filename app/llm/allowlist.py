from __future__ import annotations

import copy
import hashlib
import hmac
import json
import secrets
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config.settings import CONFIG_DIR
from app.utils.hashing import content_hash

MANUAL_IMPORT_SOURCE = "manual_import"
_ISSUER_KEY = secrets.token_bytes(32)
_BLOCKED_FIELD_PARTS = frozenset({
    "raw_payload", "password", "secret", "api_key", "token", "authorization",
    "authors", "contributors", "email",
})
_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._~+/\-]{8,}|(?:api[_-]?key|password|secret|token)"
    r"\s*[:=]\s*\S{4,}|sk-[a-z0-9_-]{12,})"
)


class LLMInputBlocked(ValueError):
    """Raised when a source has no explicit, valid LLM field approval."""


class LLMAllowlistConfigurationError(ValueError):
    """Raised when the production allowlist is missing or unsafe to interpret."""


class SourceFieldApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fields: tuple[str, ...] = ()
    approved: bool = False
    purpose: str | None = None
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    terms_reference: str | None = None
    review_summary: str | None = None
    allowed_purposes: tuple[str, ...] = ("early_signal",)
    allowed_providers: tuple[str, ...] = ("fake",)

    def is_active(self) -> bool:
        return (
            self.approved
            and bool(self.fields)
            and all(
                value and value.strip()
                for value in (
                    self.purpose,
                    self.reviewed_at,
                    self.reviewed_by,
                    self.terms_reference,
                    self.review_summary,
                )
            )
        )


class LLMAllowlistConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    default_policy: str
    sources: dict[str, SourceFieldApproval]


@dataclass(frozen=True)
class CuratedLLMInput:
    source_name: str
    source_scope: str
    record_type: str
    fields: dict[str, Any]
    input_hash: str
    _authorization_seal: str | None = field(default=None, repr=False, compare=False)


def _serializable(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise LLMInputBlocked("LLM input contains unsupported data") from exc


def _payload(curated: CuratedLLMInput) -> dict[str, Any]:
    return {
        "source_name": curated.source_name,
        "source_scope": curated.source_scope,
        "record_type": curated.record_type,
        "fields": curated.fields,
    }


def _seal(payload: dict[str, Any], config: LLMAllowlistConfig) -> str:
    data = {"payload": payload, "policy": config.model_dump(mode="json")}
    return hmac.new(_ISSUER_KEY, _serializable(data), hashlib.sha256).hexdigest()


def _safe_fields(fields: dict[str, Any]) -> bool:
    def safe_value(value: Any) -> bool:
        if isinstance(value, str):
            return len(value) <= 20_000 and not _CREDENTIAL_PATTERN.search(value)
        return isinstance(value, (int, float, bool)) or (
            isinstance(value, list) and len(value) <= 100 and all(safe_value(item) for item in value)
        )

    return all(
        not any(part.removesuffix("[]").casefold() in _BLOCKED_FIELD_PARTS for part in path.split("."))
        and safe_value(value)
        for path, value in fields.items()
    )


def authorize_curated_input(
    curated: CuratedLLMInput, *, provider_name: str, purpose: str
) -> CuratedLLMInput:
    """Revalidate a builder-issued input against the current policy at call time."""
    config = load_llm_allowlist()
    if config.default_policy != "deny" or MANUAL_IMPORT_SOURCE in config.sources:
        raise LLMInputBlocked("LLM policy is not safe")
    approval = config.sources.get(curated.source_scope)
    if (
        curated.source_name == MANUAL_IMPORT_SOURCE
        or not curated.source_name.startswith("synthetic_")
        or curated.source_scope != curated.source_name
        or provider_name != "fake"
        or approval is None
        or not approval.is_active()
        or purpose not in approval.allowed_purposes
        or provider_name not in approval.allowed_providers
    ):
        raise LLMInputBlocked("LLM input is not authorized for this provider and purpose")
    snapshot = copy.deepcopy(curated)
    if (
        not snapshot.fields
        or not set(snapshot.fields).issubset(approval.fields)
        or not _safe_fields(snapshot.fields)
    ):
        raise LLMInputBlocked("LLM input contains unauthorized fields or values")
    payload = _payload(snapshot)
    seal = snapshot._authorization_seal
    if (
        not isinstance(seal, str)
        or not hmac.compare_digest(seal, _seal(payload, config))
        or not hmac.compare_digest(snapshot.input_hash, content_hash(payload))
    ):
        raise LLMInputBlocked("LLM input provenance or integrity validation failed")
    return snapshot


def load_llm_allowlist() -> LLMAllowlistConfig:
    """Load operator approvals; the checked-in configuration denies all."""
    import yaml

    path = CONFIG_DIR / "llm_allowlist.yaml"
    try:
        with path.open(encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}
    except FileNotFoundError as exc:
        raise LLMAllowlistConfigurationError("LLM allowlist configuration is missing") from exc
    except yaml.YAMLError as exc:
        raise LLMAllowlistConfigurationError("LLM allowlist configuration is invalid YAML") from exc
    try:
        config = LLMAllowlistConfig.model_validate(raw)
    except ValidationError:
        raise LLMAllowlistConfigurationError(
            "invalid LLM allowlist configuration"
        ) from None
    if config.default_policy != "deny":
        raise LLMAllowlistConfigurationError(
            "LLM allowlist default_policy must be 'deny'"
        )
    if MANUAL_IMPORT_SOURCE in config.sources:
        raise LLMAllowlistConfigurationError(
            "manual_import cannot be added to the LLM allowlist"
        )
    return config


def source_scope(source_name: str, raw_payload: dict[str, Any]) -> str:
    """Use a stable configured sub-source key where an adapter has multiple feeds."""
    variant = raw_payload.get("university_key") if source_name == "university" else None
    return f"{source_name}:{variant}" if isinstance(variant, str) and variant else source_name


def _read_path(payload: Any, path: str) -> Any:
    parts = path.split(".")
    values = [payload]
    contains_list = False
    for part in parts:
        is_list = part.endswith("[]")
        key = part[:-2] if is_list else part
        contains_list = contains_list or is_list
        next_values: list[Any] = []
        for value in values:
            if not isinstance(value, dict) or key not in value:
                continue
            found = value[key]
            if is_list:
                if isinstance(found, list):
                    next_values.extend(found)
            else:
                next_values.append(found)
        values = next_values
        if not values:
            return None
    if contains_list:
        return values
    return values[0] if values else None


def build_curated_input(
    *,
    source_name: str,
    record_type: str,
    raw_payload: dict[str, Any],
) -> CuratedLLMInput:
    """Select explicitly approved fields and hash exactly the provider input."""
    if source_name == MANUAL_IMPORT_SOURCE:
        raise LLMInputBlocked("manual_import records are excluded from LLM analysis")

    config = load_llm_allowlist()
    if config.default_policy != "deny" or MANUAL_IMPORT_SOURCE in config.sources:
        raise LLMInputBlocked("LLM policy is not safe")
    scope = source_scope(source_name, raw_payload)
    approval = config.sources.get(scope)
    if approval is None or not approval.is_active():
        raise LLMInputBlocked("LLM analysis is not approved for this source")

    fields = {
        path: value
        for path in approval.fields
        if (value := _read_path(raw_payload, path)) is not None
    }
    if not fields:
        raise LLMInputBlocked("no approved fields are present for this source")
    if not _safe_fields(fields):
        raise LLMInputBlocked("LLM input contains unsafe fields or values")
    fields = copy.deepcopy(fields)

    hashed_input = {
        "source_name": source_name,
        "source_scope": scope,
        "record_type": record_type,
        "fields": fields,
    }
    return CuratedLLMInput(
        source_name=source_name,
        source_scope=scope,
        record_type=record_type,
        fields=fields,
        input_hash=content_hash(hashed_input),
        _authorization_seal=_seal(hashed_input, config),
    )
