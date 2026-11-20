from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.domain import SignalType


class DiscoveryCategory(StrEnum):
    RESEARCH = "research"
    TECHNOLOGY = "technology"
    DEVELOPER_ACTIVITY = "developer_activity"
    ORGANIZATION_ACTIVITY = "organization_activity"
    PUBLIC_ANNOUNCEMENT = "public_announcement"
    PUBLIC_RESEARCH_OR_PROGRAM_CONTEXT = "public_research_or_program_context"
    PITCH_ACTIVITY = "pitch_activity"


class SignalStrength(StrEnum):
    EXPLICIT_SOURCE_EVENT = "explicit_source_event"
    WEAK = "weak"


@dataclass(frozen=True)
class SourceSignalClassificationRule:
    category: DiscoveryCategory
    strength: SignalStrength
    interpretation: str


SOURCE_SIGNAL_CLASSIFICATIONS: dict[SignalType, SourceSignalClassificationRule] = {
    SignalType.NEW_PUBLICATION: SourceSignalClassificationRule(
        DiscoveryCategory.RESEARCH,
        SignalStrength.EXPLICIT_SOURCE_EVENT,
        "A publication record was observed; this does not establish a founding or startup.",
    ),
    SignalType.NEW_RESEARCH_PROJECT: SourceSignalClassificationRule(
        DiscoveryCategory.RESEARCH,
        SignalStrength.EXPLICIT_SOURCE_EVENT,
        "A research project item was observed; project participation is not a company.",
    ),
    SignalType.NEW_REPOSITORY: SourceSignalClassificationRule(
        DiscoveryCategory.TECHNOLOGY,
        SignalStrength.EXPLICIT_SOURCE_EVENT,
        "A repository was observed; repository creation is not a product or startup.",
    ),
    SignalType.NEW_MODEL: SourceSignalClassificationRule(
        DiscoveryCategory.TECHNOLOGY,
        SignalStrength.EXPLICIT_SOURCE_EVENT,
        "A model asset was observed; publication is not a product or startup.",
    ),
    SignalType.NEW_DATASET: SourceSignalClassificationRule(
        DiscoveryCategory.TECHNOLOGY,
        SignalStrength.EXPLICIT_SOURCE_EVENT,
        "A dataset asset was observed; publication is not a product or startup.",
    ),
    SignalType.NEW_SPACE: SourceSignalClassificationRule(
        DiscoveryCategory.TECHNOLOGY,
        SignalStrength.EXPLICIT_SOURCE_EVENT,
        "A Space asset was observed; publication is not a product or startup.",
    ),
    SignalType.NEW_CONTRIBUTOR: SourceSignalClassificationRule(
        DiscoveryCategory.DEVELOPER_ACTIVITY,
        SignalStrength.EXPLICIT_SOURCE_EVENT,
        "A contributor was listed; this does not establish team or founder status.",
    ),
    SignalType.NEW_PRESS_RELEASE: SourceSignalClassificationRule(
        DiscoveryCategory.PUBLIC_ANNOUNCEMENT,
        SignalStrength.EXPLICIT_SOURCE_EVENT,
        "A configured announcement was observed; its subject is not automatically a startup.",
    ),
    SignalType.NEW_FUNDING_PROJECT: SourceSignalClassificationRule(
        DiscoveryCategory.PUBLIC_RESEARCH_OR_PROGRAM_CONTEXT,
        SignalStrength.EXPLICIT_SOURCE_EVENT,
        "Public research/program funding is not an external startup equity round.",
    ),
    SignalType.NEW_PITCH_PRESENTATION: SourceSignalClassificationRule(
        DiscoveryCategory.PITCH_ACTIVITY,
        SignalStrength.WEAK,
        "Pitch activity is not a verified founding or startup event.",
    ),
}

OBSERVATION_CLASSIFICATIONS: dict[tuple[str, str], SourceSignalClassificationRule] = {
    **{
        ("github", metric): SourceSignalClassificationRule(
            DiscoveryCategory.TECHNOLOGY,
            SignalStrength.WEAK,
            "One repository metric was observed; a single value does not establish growth or a startup.",
        )
        for metric in ("stars", "forks", "open_issues_and_prs", "subscribers")
    },
    **{
        ("github", metric): SourceSignalClassificationRule(
            DiscoveryCategory.DEVELOPER_ACTIVITY,
            SignalStrength.WEAK,
            "One developer-activity count was observed; a single value does not establish team growth.",
        )
        for metric in ("contributors", "commits", "pull_requests")
    },
    **{
        ("huggingface", metric): SourceSignalClassificationRule(
            DiscoveryCategory.TECHNOLOGY,
            SignalStrength.WEAK,
            "One Hub usage/activity metric was observed; a single value does not establish growth or a startup.",
        )
        for metric in ("downloads", "downloads_all_time", "likes")
    },
    **{
        ("huggingface", metric): SourceSignalClassificationRule(
            DiscoveryCategory.ORGANIZATION_ACTIVITY,
            SignalStrength.WEAK,
            "One organization-level count was observed; it does not establish a startup or team.",
        )
        for metric in ("followers", "models", "datasets", "spaces", "public_members")
    },
    ("openalex", "citation_count"): SourceSignalClassificationRule(
        DiscoveryCategory.RESEARCH,
        SignalStrength.WEAK,
        "One citation count was observed; it does not establish research quality or a founding event.",
    ),
}


@dataclass(frozen=True)
class SourceRecordContext:
    source_name: str
    record_type: str
    anchor_signal_type: str


@dataclass(frozen=True)
class TextField:
    source_name: str
    record_type: str
    path: str


@dataclass(frozen=True)
class TextRule:
    rule_id: str
    rule_version: str
    signal_type: SignalType
    category: str
    contexts: frozenset[SourceRecordContext]
    fields: tuple[TextField, ...]
    patterns: tuple[re.Pattern[str], ...]


def _contexts(*items: tuple[str, str, str]) -> frozenset[SourceRecordContext]:
    return frozenset(SourceRecordContext(*item) for item in items)


_STARTUP_TEXT_FIELDS = (
    TextField("exist", "success_story", "title"),
    TextField("exist", "success_story", "subtitle"),
    TextField("exist", "success_story", "summary"),
    TextField("university", "news", "title"),
    TextField("university", "news", "summary"),
    TextField("university", "press_release", "title"),
    TextField("university", "press_release", "summary"),
)
_TECH_TEXT_FIELDS = (
    TextField("github", "repository", "repository.description"),
    TextField("github", "repository", "readme.text"),
    TextField("huggingface", "model", "description"),
    TextField("huggingface", "model", "card_text"),
    TextField("huggingface", "dataset", "description"),
    TextField("huggingface", "dataset", "card_text"),
    TextField("huggingface", "space", "description"),
    TextField("huggingface", "space", "card_text"),
)
_TEXT_CONTEXTS = _contexts(
    ("exist", "success_story", SignalType.NEW_FUNDING_PROJECT.value),
    ("university", "news", SignalType.NEW_PRESS_RELEASE.value),
    ("university", "press_release", SignalType.NEW_PRESS_RELEASE.value),
)
_TECH_CONTEXTS = _contexts(
    ("github", "repository", SignalType.NEW_REPOSITORY.value),
    ("huggingface", "model", SignalType.NEW_MODEL.value),
    ("huggingface", "dataset", SignalType.NEW_DATASET.value),
    ("huggingface", "space", SignalType.NEW_SPACE.value),
)

TEXT_RULES: tuple[TextRule, ...] = (
    TextRule(
        rule_id="founding-activity-mention",
        rule_version="1",
        signal_type=SignalType.FOUNDING_ACTIVITY_MENTION,
        category="founding_activity_mention",
        contexts=_TEXT_CONTEXTS | _TECH_CONTEXTS,
        fields=_STARTUP_TEXT_FIELDS + _TECH_TEXT_FIELDS,
        patterns=(
            re.compile(r"\b(?:co[- ]?founded|founded|founder of|established)\b", re.IGNORECASE),
            re.compile(
                r"\b(?:gegründet|gründete|gründung|mitgegründet|mitbegründer(?:in|innen)?)\b",
                re.IGNORECASE,
            ),
        ),
    ),
    TextRule(
        rule_id="spinout-mention",
        rule_version="1",
        signal_type=SignalType.SPINOUT_MENTION,
        category="spinout_mention",
        contexts=_TEXT_CONTEXTS,
        fields=_STARTUP_TEXT_FIELDS,
        patterns=(
            re.compile(r"\bspin[- ]?(?:off|out)\b", re.IGNORECASE),
            re.compile(r"\b(?:ausgründung|ausgegründet|ausgegründete)\b", re.IGNORECASE),
        ),
    ),
    TextRule(
        rule_id="commercialization-mention",
        rule_version="1",
        signal_type=SignalType.COMMERCIALIZATION_MENTION,
        category="commercialization_mention",
        contexts=_TEXT_CONTEXTS | _TECH_CONTEXTS,
        fields=_STARTUP_TEXT_FIELDS + _TECH_TEXT_FIELDS,
        patterns=(
            re.compile(
                r"\b(?:commerciali[sz](?:e|ed|ing|ation|ierung)|commercial launch|product launch|market launch|go[- ]to[- ]market)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:markteinführung|marktstart|produktstart|vermarkt(?:et|ung)|auf den markt)\b",
                re.IGNORECASE,
            ),
        ),
    ),
)

DISCOVERY_RULE_IDS = tuple(rule.rule_id for rule in TEXT_RULES)

_NEGATION_PREFIX = re.compile(
    r"\b(?:not|never|no|nicht|kein(?:e|en|er|es)?|ohne)\b(?:[\W_]+\w+){0,4}[\W_]*$",
    re.IGNORECASE,
)


def _value_at_path(payload: dict[str, object], path: str) -> str | None:
    value: object = payload
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value if isinstance(value, str) and value.strip() else None


def find_text_rule_match(
    rule: TextRule, source_name: str, record_type: str, payload: dict[str, object], signal_type: str
) -> tuple[str, str] | None:
    context = SourceRecordContext(source_name, record_type, signal_type)
    if context not in rule.contexts:
        return None
    for field in rule.fields:
        if (field.source_name, field.record_type) != (source_name, record_type):
            continue
        text = _value_at_path(payload, field.path)
        if text is None:
            continue
        for pattern in rule.patterns:
            match = pattern.search(text)
            if match is None:
                continue
            prefix = text[max(0, match.start() - 48) : match.start()]
            if _NEGATION_PREFIX.search(prefix):
                continue
            return field.path, match.group(0)
    return None
