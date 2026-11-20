from __future__ import annotations

import csv
import io
from collections import Counter
from pathlib import Path
from typing import Any

from app.htgf.history import append_history, atomic_write, digest, load_history, locked, read_json

PROTECTED_NAMES = {
    "candidate_discovery.json", "candidate_validation.json",
    "candidate_overview.csv", "candidate_research_report.md",
}


def _index(document: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    entries = document.get("candidates")
    if not isinstance(entries, list):
        raise ValueError(f"{label} candidates must be a list")
    result: dict[str, dict[str, Any]] = {}
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("candidate_id"), str):
            raise ValueError(f"{label} contains an invalid candidate")
        key = item["candidate_id"]
        if key in result:
            raise ValueError(f"{label} contains duplicate candidate_id: {key}")
        result[key] = item
    return result


def _check_paths(inputs: list[Path], outputs: list[Path]) -> None:
    resolved_inputs = {path.resolve() for path in inputs}
    resolved_outputs = [path.resolve() for path in outputs]
    if len(set(resolved_outputs)) != len(resolved_outputs):
        raise ValueError("History, CSV and report must be different files")
    for path in resolved_outputs:
        if path in resolved_inputs or path.name.casefold() in PROTECTED_NAMES:
            raise ValueError(f"Refusing to overwrite an input or protected candidate file: {path}")
    lock_path = outputs[0].with_name(outputs[0].name + ".lock").resolve()
    if lock_path in resolved_inputs or lock_path in resolved_outputs:
        raise ValueError("The history lock file must not overlap any input or output")


def latest(history: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        candidate_id: max(versions, key=lambda version: (
            version["assessment_date"], version["assessed_at"], version["assessment_id"]
        ))
        for candidate_id, versions in history["candidates"].items() if versions
    }


def joined(history: dict[str, Any], discovery: dict[str, Any], validation: dict[str, Any]) -> list[dict[str, Any]]:
    discovered = _index(discovery, "discovery")
    validated = _index(validation, "validation")
    rows = []
    for candidate_id, result in latest(history).items():
        if candidate_id not in discovered or candidate_id not in validated:
            raise ValueError(f"Assessment candidate {candidate_id} missing from input files")
        if result["name"] != discovered[candidate_id].get("name") or result["name"] != validated[candidate_id].get("name"):
            raise ValueError(f"Candidate identity mismatch for {candidate_id}")
        rows.append({
            "candidate_id": candidate_id,
            "candidate": result["name"],
            "technology_fields": "; ".join(result["technology_fields"]),
            "tech_startup_status": result["tech_startup_status"],
            "technology_status": result["technology_status"],
            "company_age_status": result["company_age_status"],
            "germany_presence_status": result["germany_presence_status"],
            "htgf_eligibility_status": result["htgf_eligibility_status"],
            "funding_status": validated[candidate_id].get("funding_status", ""),
            "assessment_date": result["assessment_date"],
            "assessment": result,
        })
    return sorted(rows, key=lambda row: row["candidate"].casefold())


def render_csv(rows: list[dict[str, Any]]) -> str:
    fields = [
        "candidate_id", "candidate", "technology_fields", "tech_startup_status",
        "technology_status", "company_age_status", "germany_presence_status",
        "htgf_eligibility_status", "funding_status", "assessment_date",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_report(rows: list[dict[str, Any]]) -> str:
    counts = Counter(row["htgf_eligibility_status"] for row in rows)
    germany = {
        "registered_seat_in_germany", "relocation_to_germany_planned",
        "german_permanent_establishment_planned",
    }
    lines = [
        "# HTGF Eligibility Assessment",
        "",
        "Orientation against the three supplied HTGF questions, not an official funding or investment decision.",
        "HTGF fit and funding status are independent; public grants are not equity funding rounds.",
        "Missing or conflicting evidence is not treated as positive. No web, LLM or database access was used.",
        "",
        "## Summary",
        "",
        f"- Candidates assessed: {len(rows)}",
        f"- Technology criterion satisfied: {sum(row['technology_status'] == 'satisfied' for row in rows)}",
        f"- Within three years (verified register): {sum(row['company_age_status'] == 'within_three_years' for row in rows)}",
        f"- Germany connection supported: {sum(row['germany_presence_status'] in germany for row in rows)}",
    ]
    for status in ("htgf_eligible", "htgf_not_eligible", "htgf_unclear", "pre_company_candidate"):
        lines.append(f"- `{status}`: {counts[status]}")
    lines += [
        "",
        "## Assessments",
        "",
        "| Candidate | Technology fields | Tech criterion | Company age | Germany connection | HTGF fit | Funding |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| " + " | ".join(_md(row[key]) for key in (
                "candidate", "technology_fields", "technology_status", "company_age_status",
                "germany_presence_status", "htgf_eligibility_status", "funding_status",
            )) + " |"
        )
    lines += ["", "## Evidence and open questions", ""]
    for row in rows:
        assessment = row["assessment"]
        lines += [
            f"### {_md(row['candidate'])} (`{row['candidate_id']}`)",
            "",
            f"Assessment date: {row['assessment_date']}; result: `{row['htgf_eligibility_status']}`.",
            "",
        ]
        for label, key, status in (
            ("Technology", "technology", row["technology_status"]),
            ("Company age", "company_age", row["company_age_status"]),
            ("Germany", "germany", row["germany_presence_status"]),
        ):
            section = assessment["criteria"][key]
            lines.append(f"- **{label}** (`{status}`): {_md(section['rationale'])}")
            for source in section["evidence"]:
                lines.append(
                    f"  - [{_md(source['title'])}]({source['url']}) — {_md(source['publisher'])}, "
                    f"{source['source_type']}, trust: {source['reliability']}; accessed {source['accessed_on']}: "
                    f"{_md(source['claim'])}"
                )
                lines.extend(f"  - Source contradiction: {_md(c)}" for c in source["contradictions"])
            lines.extend(f"  - Open: {_md(question)}" for question in section["uncertainties"])
            lines.extend(f"  - Contradiction: {_md(c)}" for c in section["contradictions"])
        lines.append("")
    lines.extend([
        "## Interpretation",
        "",
        "Calendar years are used for company age; the registration must be evidenced by the official register for the uniquely identified legal entity.",
        "A German research partner, founder or programme alone does not establish a registered seat or a concrete Germany plan.",
        "Technology areas are not necessarily exclusive. Existing discovery ranking and funding assessments are unchanged.",
        "",
    ])
    return "\n".join(lines)


def run(
    input_path: Path, discovery_path: Path, validation_path: Path,
    history_path: Path, csv_path: Path, report_path: Path,
) -> dict[str, Any]:
    _check_paths([input_path, discovery_path, validation_path], [history_path, csv_path, report_path])
    manifest = read_json(input_path)
    if (
        manifest.get("schema_version") != "1.0"
        or not isinstance(manifest.get("candidates"), list)
        or not manifest["candidates"]
    ):
        raise ValueError("Invalid assessment input schema")
    discovery, validation = read_json(discovery_path), read_json(validation_path)
    discovered, validated = _index(discovery, "discovery"), _index(validation, "validation")
    candidates = manifest["candidates"]
    state = {}
    for item in candidates:
        if not isinstance(item, dict) or not isinstance(item.get("candidate_id"), str):
            raise ValueError("Invalid candidate in assessment input")
        key = item["candidate_id"]
        if key not in discovered or key not in validated:
            raise ValueError(f"Candidate {key} missing from discovery or validation")
        if item.get("name") != discovered[key].get("name") or item.get("name") != validated[key].get("name"):
            raise ValueError(f"Candidate identity mismatch for {key}")
        state[key] = {
            "discovery_candidate_sha256": digest(discovered[key]),
            "validation_candidate_sha256": digest(validated[key]),
            "assessment_input_schema": manifest["schema_version"],
        }
    _, added = append_history(history_path, candidates, state)
    with locked(history_path):
        history = load_history(history_path)
        rows = joined(history, discovery, validation)
        atomic_write(csv_path, render_csv(rows))
        atomic_write(report_path, render_report(rows))
    return {
        "added_assessments": added,
        "candidates": len(rows),
        "status_counts": dict(sorted(Counter(row["htgf_eligibility_status"] for row in rows).items())),
    }
