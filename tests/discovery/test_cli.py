from __future__ import annotations

import json
from contextlib import contextmanager

from typer.testing import CliRunner

import app.cli as cli_module
from app.cli import cli
from app.discovery.types import DiscoveryResult

runner = CliRunner()


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def _mock_database(monkeypatch, *, persistent: bool = False) -> None:
    session = _Session()
    monkeypatch.setattr(cli_module, "make_engine", lambda: object())
    monkeypatch.setattr(cli_module, "make_session_factory", lambda _engine: lambda: session)
    if persistent:
        @contextmanager
        def fake_scope(_factory):
            yield session

        monkeypatch.setattr(cli_module, "session_scope", fake_scope)


def test_preview_is_read_only_and_returns_discovery_classifications(monkeypatch) -> None:
    result_data = DiscoveryResult()
    monkeypatch.setattr(cli_module, "load_discovery", lambda *args, **kwargs: result_data)
    monkeypatch.setattr(
        cli_module,
        "persist_discovery",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("preview must not persist")),
    )
    _mock_database(monkeypatch)

    result = runner.invoke(cli, ["discovery", "preview", "--limit", "3"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "preview"
    assert payload["persisted"] is False
    assert payload["derived_signals"] == []


def test_run_uses_explicit_persistence_command(monkeypatch) -> None:
    result_data = DiscoveryResult()
    monkeypatch.setattr(cli_module, "load_discovery", lambda *args, **kwargs: result_data)
    monkeypatch.setattr(cli_module, "persist_discovery", lambda *args, **kwargs: 2)
    _mock_database(monkeypatch, persistent=True)

    result = runner.invoke(cli, ["discovery", "run", "--source", "exist"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "run"
    assert payload["persisted"] is True
    assert payload["derived_signals_upserted"] == 2
    assert payload["source_records_reconciled"] == 0


def test_preview_rejects_non_positive_limit() -> None:
    result = runner.invoke(cli, ["discovery", "preview", "--limit", "0"])
    assert result.exit_code != 0
