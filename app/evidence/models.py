from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Source(EvidenceModel):
    schema_version: Literal["1.0"] = "1.0"
    source_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2048)
    publisher: str = Field(min_length=1, max_length=300)
    source_type: str = Field(min_length=1, max_length=100)
    policy_reference: str | None = Field(default=None, max_length=500)


class Document(EvidenceModel):
    schema_version: Literal["1.0"] = "1.0"
    document_id: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=200)
    content_hash: str = Field(min_length=1, max_length=128)
    published_on: date | None = None
    retrieved_on: date | None = None
    fields: dict[str, Any]


class Evidence(EvidenceModel):
    schema_version: Literal["1.0"] = "1.0"
    evidence_id: str = Field(min_length=1, max_length=200)
    document_id: str = Field(min_length=1, max_length=200)
    field_path: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=500)


class ClaimKind(StrEnum):
    FACT_CANDIDATE = "fact_candidate"
    HYPOTHESIS = "hypothesis"
    CLASSIFICATION_PROPOSAL = "classification_proposal"


class Claim(EvidenceModel):
    schema_version: Literal["1.0"] = "1.0"
    claim_id: str = Field(min_length=1, max_length=200)
    candidate_id: str = Field(min_length=1, max_length=200)
    claim_type: str = Field(min_length=1, max_length=100)
    kind: ClaimKind
    statement: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    uncertainties: list[str] = Field(default_factory=list, max_length=20)
    conflict_ids: list[str] = Field(default_factory=list, max_length=20)


class Conflict(EvidenceModel):
    schema_version: Literal["1.0"] = "1.0"
    conflict_id: str = Field(min_length=1, max_length=200)
    claim_ids: list[str] = Field(min_length=2, max_length=20)
    description: str = Field(min_length=1, max_length=500)
    status: Literal["open"] = "open"


class ClaimExtraction(EvidenceModel):
    schema_version: Literal["1.0"] = "1.0"
    claims: list[Claim] = Field(default_factory=list, max_length=50)
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)
    conflicts: list[Conflict] = Field(default_factory=list, max_length=50)
