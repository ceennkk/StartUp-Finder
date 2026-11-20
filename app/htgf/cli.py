from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.htgf.workflow import run

DEFAULT_DIR = Path("data") / "candidates"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run offline HTGF assessment")
    parser.add_argument("--input", type=Path, default=DEFAULT_DIR / "htgf_input.json")
    parser.add_argument("--discovery", type=Path, default=DEFAULT_DIR / "candidate_discovery.json")
    parser.add_argument("--validation", type=Path, default=DEFAULT_DIR / "candidate_validation.json")
    parser.add_argument("--history", type=Path, default=DEFAULT_DIR / "htgf_assessments.json")
    parser.add_argument("--csv", type=Path, default=DEFAULT_DIR / "htgf_overview.csv")
    parser.add_argument("--report", type=Path, default=DEFAULT_DIR / "htgf_research_report.md")
    args = parser.parse_args()
    try:
        result = run(args.input, args.discovery, args.validation, args.history, args.csv, args.report)
    except (OSError, ValueError, KeyError) as exc:
        print(f"HTGF assessment failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False))
