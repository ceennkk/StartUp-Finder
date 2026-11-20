from __future__ import annotations

from typing import Any

from app.domain import EntityType
from app.ingestion.types import AliasDraft, EntityDraft
from app.normalization.text import clean_text


def organization_draft(
    *,
    key: str,
    identifier: str,
    name: str | None,
    is_university: bool = False,
    aliases: list[AliasDraft] | None = None,
    properties: dict[str, Any] | None = None,
    description: str | None = None,
    is_primary: bool = False,
) -> EntityDraft | None:
    """Organization entity scoped to one source identifier; spelling variants are kept as aliases."""
    cleaned = clean_text(name)
    if not cleaned:
        return None
    return EntityDraft(
        key=key,
        identifier=identifier,
        entity_type=EntityType.UNIVERSITY if is_university else EntityType.ORGANIZATION,
        canonical_name=cleaned,
        description=clean_text(description),
        aliases=aliases or [],
        properties={k: v for k, v in (properties or {}).items() if v is not None},
        is_primary=is_primary,
    )
