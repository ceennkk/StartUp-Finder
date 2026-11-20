from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.htgf.workflow import run
from tests.htgf.test_assessment import sample


class WorkflowTests(unittest.TestCase):
    def setup_files(self, root: Path) -> tuple[Path, ...]:
        inputs = root / "input.json"
        discovery = root / "discovery.json"
        validation = root / "validation.json"
        inputs.write_text(json.dumps({"schema_version": "1.0", "candidates": [sample()]}), encoding="utf-8")
        discovery.write_text(json.dumps({"candidates": [{"candidate_id": "candidate-a", "name": "A"}]}), encoding="utf-8")
        validation.write_text(json.dumps({"candidates": [{"candidate_id": "candidate-a", "name": "A", "funding_status": "funding_round_confirmed"}]}), encoding="utf-8")
        return inputs, discovery, validation, root / "history.json", root / "overview.csv", root / "report.md"

    def test_outputs_and_funding_are_independent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            files = self.setup_files(Path(directory))
            result = run(*files)
            self.assertEqual(result["status_counts"], {"htgf_eligible": 1})
            with files[4].open(encoding="utf-8", newline="") as file:
                row = next(csv.DictReader(file))
            self.assertEqual(row["htgf_eligibility_status"], "htgf_eligible")
            self.assertEqual(row["funding_status"], "funding_round_confirmed")
            self.assertIn("funding_round_confirmed", files[5].read_text(encoding="utf-8"))
            self.assertEqual(run(*files)["added_assessments"], 0)
            data = json.loads(files[2].read_text(encoding="utf-8"))
            data["candidates"][0]["funding_status"] = "funding_unclear"
            files[2].write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(run(*files)["status_counts"], {"htgf_eligible": 1})

    def test_refuses_protected_or_duplicate_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            files = self.setup_files(Path(directory))
            for altered in (
                (*files[:3], files[0], *files[4:]),
                (*files[:4], files[3], files[5]),
                (*files[:4], Path(directory) / "candidate_overview.csv", files[5]),
                (*files[:4], files[3].with_name(files[3].name + ".lock"), files[5]),
            ):
                with self.assertRaises(ValueError):
                    run(*altered)

    def test_cli_runs_without_database_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            files = self.setup_files(Path(directory))
            command = [sys.executable, "-m", "app.htgf"]
            for flag, path in zip(("--input", "--discovery", "--validation", "--history", "--csv", "--report"), files):
                command.extend((flag, str(path)))
            env = dict(os.environ)
            env["DATABASE_URL"] = "not-a-database-url"
            env["DATABASE_URL_DIRECT"] = "not-a-database-url"
            result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status_counts"], {"htgf_eligible": 1})

    def test_import_never_initializes_database(self) -> None:
        code = (
            "import sys; import app.htgf.assessment,app.htgf.history,app.htgf.workflow; "
            "assert 'app.database.connection' not in sys.modules"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(
        all(importlib.util.find_spec(name) for name in ("alembic", "sqlalchemy", "pydantic_settings", "typer")),
        "Project CLI dependencies are not installed in this interpreter",
    )
    def test_project_cli_never_connects_to_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            files = self.setup_files(Path(directory))
            code = (
                "import sys; import app.cli as c; "
                "c.make_engine=lambda *a,**k: (_ for _ in ()).throw(AssertionError('DB access')); "
                "sys.argv=['app.cli','htgf','run']+sys.argv[1:]; c.main()"
            )
            command = [sys.executable, "-c", code]
            for flag, path in zip(("--input", "--discovery", "--validation", "--history", "--csv", "--report"), files):
                command.extend((flag, str(path)))
            env = dict(os.environ, DATABASE_URL="invalid", DATABASE_URL_DIRECT="invalid")
            result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status_counts"], {"htgf_eligible": 1})


if __name__ == "__main__":
    unittest.main()
