from __future__ import annotations

from typing import Any

from app.domain import AliasType, EntityType
from app.ingestion.types import AliasDraft, EntityDraft
from app.normalization.text import clean_text


def person_draft(
    *,
    key: str,
    identifier: str,
    name: str | None,
    aliases: list[AliasDraft] | None = None,
    properties: dict[str, Any] | None = None,
    is_primary: bool = False,
) -> EntityDraft | None:
    """Person entity scoped to one source identifier. Persons are never matched by name."""
    cleaned = clean_text(name)
    if not cleaned:
        return None
    return EntityDraft(
        key=key,
        identifier=identifier,
        entity_type=EntityType.PERSON,
        canonical_name=cleaned,
        aliases=aliases or [],
        properties={k: v for k, v in (properties or {}).items() if v is not None},
        is_primary=is_primary,
    )


def external_alias(alias_type: AliasType, value: str | None) -> AliasDraft | None:
    cleaned = clean_text(value)
    return AliasDraft(alias=cleaned, alias_type=alias_type, external_identifier=cleaned) if cleaned else None
