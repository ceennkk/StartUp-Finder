from __future__ import annotations

from enum import StrEnum


class EntityType(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"
    UNIVERSITY = "university"
    RESEARCH_PROJECT = "research_project"
    PUBLICATION = "publication"
    REPOSITORY = "repository"
    MODEL = "model"
    DATASET = "dataset"
    SPACE = "space"
    STARTUP = "startup"
    EVENT = "event"
    FUNDING_PROGRAM = "funding_program"
    TECHNOLOGY = "technology"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class SourceType(StrEnum):
    API = "api"
    HTML = "html"
    RSS = "rss"
    SITEMAP = "sitemap"
    MANUAL = "manual"


class VerificationStatus(StrEnum):
    SOURCE_ASSERTED = "source_asserted"
    UNVERIFIED = "unverified"
    MANUALLY_VERIFIED = "manually_verified"


class AliasType(StrEnum):
    NAME = "name"
    SOURCE_IDENTIFIER = "source_identifier"
    DOI = "doi"
    ORCID = "orcid"
    ROR = "ror"
    URL = "url"
    LOGIN = "login"


class RelationshipType(StrEnum):
    WORKS_AT = "WORKS_AT"
    STUDIES_AT = "STUDIES_AT"
    CONTRIBUTED_TO = "CONTRIBUTED_TO"
    AUTHORED = "AUTHORED"
    PARTICIPATED_IN = "PARTICIPATED_IN"
    COLLABORATES_WITH = "COLLABORATES_WITH"
    DEVELOPED = "DEVELOPED"
    USES = "USES"
    FUNDED_BY = "FUNDED_BY"
    PRESENTED_AT = "PRESENTED_AT"
    MEMBER_OF = "MEMBER_OF"
    OWNED_BY = "OWNED_BY"
    PUBLISHED_BY = "PUBLISHED_BY"


class SignalType(StrEnum):
    NEW_REPOSITORY = "NEW_REPOSITORY"
    NEW_PUBLICATION = "NEW_PUBLICATION"
    NEW_FUNDING_PROJECT = "NEW_FUNDING_PROJECT"
    NEW_MODEL = "NEW_MODEL"
    NEW_DATASET = "NEW_DATASET"
    NEW_SPACE = "NEW_SPACE"
    NEW_CONTRIBUTOR = "NEW_CONTRIBUTOR"
    NEW_PITCH_PRESENTATION = "NEW_PITCH_PRESENTATION"
    NEW_RESEARCH_PROJECT = "NEW_RESEARCH_PROJECT"
    NEW_PRESS_RELEASE = "NEW_PRESS_RELEASE"
    FOUNDING_ACTIVITY_MENTION = "FOUNDING_ACTIVITY_MENTION"
    SPINOUT_MENTION = "SPINOUT_MENTION"
    COMMERCIALIZATION_MENTION = "COMMERCIALIZATION_MENTION"


def values(enum_cls: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_cls]
