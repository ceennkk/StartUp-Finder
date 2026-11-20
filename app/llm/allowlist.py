from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config.settings import CONFIG_DIR
from app.utils.hashing import content_hash

MANUAL_IMPORT_SOURCE = "manual_import"


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
    except ValidationError as exc:
        raise LLMAllowlistConfigurationError(
            f"invalid LLM allowlist configuration: {exc}"
        ) from exc
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
    scope = source_scope(source_name, raw_payload)
    approval = config.sources.get(scope)
    if approval is None or not approval.is_active():
        raise LLMInputBlocked(f"LLM analysis is not approved for source {scope!r}")

    fields = {
        path: value
        for path in approval.fields
        if (value := _read_path(raw_payload, path)) is not None
    }
    if not fields:
        raise LLMInputBlocked(f"no approved fields are present for source {scope!r}")

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
    )
