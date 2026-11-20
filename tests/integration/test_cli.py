from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from app.cli import cli
from app.config.settings import get_settings

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch):
    # Environment variables win over .env, so a developer's real credentials never leak into tests.
    for name in ("DATABASE_URL", "DATABASE_URL_DIRECT", "GITHUB_TOKEN"):
        monkeypatch.setenv(name, "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_unknown_collector_exits_with_config_code() -> None:
    result = runner.invoke(cli, ["collect", "does-not-exist", "--dry-run"])
    assert result.exit_code == 2
    assert "unknown collector" in json.loads(result.stdout)["error"]


def test_missing_database_url_exits_with_config_code() -> None:
    for args in (["database", "status"], ["database", "init"], ["ingestion", "history"], ["collect", "arxiv"]):
        result = runner.invoke(cli, args)
        assert result.exit_code == 2, args
        assert "DATABASE_URL" in json.loads(result.stdout)["error"]


def test_missing_credentials_exit_with_config_code_in_dry_run() -> None:
    result = runner.invoke(cli, ["collect", "github", "--dry-run"])
    assert result.exit_code == 2 and "GITHUB_TOKEN" in json.loads(result.stdout)["error"]


def test_unreachable_database_exits_with_db_code(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:9/none")
    get_settings.cache_clear()
    result = runner.invoke(cli, ["database", "status"])
    assert result.exit_code == 3


@pytest.mark.db
def test_status_and_history_against_a_migrated_database(monkeypatch, session_factory, engine) -> None:
    from tests.helpers import FakeAdapter

    FakeAdapter(session_factory, [{"id": "1", "name": "a", "owner": "o", "stars": 1}]).run()
    monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
    get_settings.cache_clear()

    status = runner.invoke(cli, ["database", "status"])
    payload = json.loads(status.stdout)
    assert status.exit_code == 0 and payload["up_to_date"] is True
    assert payload["row_counts"]["source_records"] == 1

    history = runner.invoke(cli, ["ingestion", "history", "--limit", "5"])
    runs = json.loads(history.stdout)
    assert history.exit_code == 0 and runs[0]["source"] == "fake" and runs[0]["status"] == "success"
