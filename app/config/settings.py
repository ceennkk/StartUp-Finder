from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path(__file__).parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str | None = None
    database_url_direct: str | None = None
    test_database_url: str | None = None

    github_token: str | None = None
    openalex_api_key: str | None = None
    hf_token: str | None = None

    contact_email: str | None = None
    manual_import_dir: str | None = None
    http_timeout_seconds: float = Field(default=30.0, gt=0)
    http_max_retries: int = Field(default=5, ge=0)

    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    observation_bucket: Literal["day", "hour"] = "day"

    @property
    def user_agent(self) -> str:
        contact = f"; contact: {self.contact_email}" if self.contact_email else ""
        return f"VentureRadar-Ingestion/0.1 (research collector for public sources{contact})"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml(name: str) -> dict[str, Any]:
    with (CONFIG_DIR / name).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_search_terms(adapter: str) -> dict[str, Any]:
    return load_yaml("search_terms.yaml").get(adapter, {})


def load_source_config(adapter: str) -> dict[str, Any]:
    return load_yaml("sources.yaml").get(adapter, {})
