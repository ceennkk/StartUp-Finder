"""Smoke tests against the real services. Run with: pytest -m live (needs network, GITHUB_TOKEN for GitHub)."""
from __future__ import annotations

import pytest

from app.adapters import registry
from app.config.settings import get_settings

pytestmark = pytest.mark.live


@pytest.mark.parametrize("name", ["openalex", "arxiv", "exist", "university", "github", "huggingface"])
def test_live_dry_run_fetches_and_normalizes(name: str) -> None:
    if name == "github" and not get_settings().github_token:
        pytest.skip("GITHUB_TOKEN not set")
    adapter = registry.get_adapter_class(name)(None, limit=3, dry_run=True)
    result = adapter.run()
    assert result.status == "success", result.error_message
    assert result.records_fetched > 0 and result.records_failed == 0
