from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app.htgf.history import append_history, load_history
from tests.htgf.test_assessment import sample


class HistoryTests(unittest.TestCase):
    def test_append_idempotence_and_input_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            item = sample()
            state = {"candidate-a": {"source_sha256": "abc"}}
            first, count = append_history(path, [item], state)
            self.assertEqual(count, 1)
            original = copy.deepcopy(first["candidates"]["candidate-a"][0])
            self.assertEqual(append_history(path, [item], state)[1], 0)
            state["candidate-a"]["source_sha256"] = "changed"
            self.assertEqual(append_history(path, [item], state)[1], 1)
            versions = load_history(path)["candidates"]["candidate-a"]
            self.assertEqual(len(versions), 2)
            self.assertEqual(versions[0], original)
            self.assertEqual(versions[0]["input_state"]["assessment_input"], item)
            self.assertNotEqual(versions[0]["assessment_id"], versions[1]["assessment_id"])

    def test_failure_does_not_replace_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            item = sample()
            state = {"candidate-a": {"source_sha256": "abc"}}
            append_history(path, [item], state)
            original = path.read_bytes()
            item["assessment_date"] = "2026-11-21"
            with patch("app.htgf.history.os.replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    append_history(path, [item], state)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(list(Path(directory).glob("*.tmp")))

    def test_concurrent_processes_do_not_lose_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "history.json"
            commands = []
            for index in range(4):
                item = sample()
                item["candidate_id"] = f"candidate-{index}"
                payload = root / f"input-{index}.json"
                payload.write_text(json.dumps(item), encoding="utf-8")
                script = (
                    "import json,sys; from pathlib import Path; "
                    "from app.htgf.history import append_history; "
                    "item=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')); "
                    "append_history(Path(sys.argv[2]),[item],{item['candidate_id']: {}})"
                )
                commands.append([sys.executable, "-c", script, str(payload), str(path)])
            def execute(command: list[str]) -> subprocess.CompletedProcess:
                return subprocess.run(command, capture_output=True, text=True, timeout=30)
            with ThreadPoolExecutor(max_workers=4) as executor:
                completed = list(executor.map(execute, commands))
            for process in completed:
                self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(len(load_history(path)["candidates"]), 4)

    def test_invalid_history_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text('{"schema_version": "unexpected", "candidates": {}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                append_history(path, [sample()], {"candidate-a": {}})


if __name__ == "__main__":
    unittest.main()
