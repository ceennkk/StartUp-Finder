from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.adapters.base import BaseAdapter

# Adapters are imported lazily so a missing optional dependency only affects that collector.
ADAPTERS: dict[str, str] = {
    "openalex": "app.adapters.openalex:OpenAlexAdapter",
    "github": "app.adapters.github:GitHubAdapter",
    "arxiv": "app.adapters.arxiv:ArxivAdapter",
    "huggingface": "app.adapters.huggingface:HuggingFaceAdapter",
    "exist": "app.adapters.exist:ExistAdapter",
    "university": "app.adapters.university:UniversityAdapter",
    "cordis": "app.adapters.cordis:CordisAdapter",
    "manual_import": "app.adapters.manual_import:ManualImportAdapter",
}


def register(name: str, dotted_path: str) -> None:
    ADAPTERS[name] = dotted_path


def available() -> list[str]:
    return sorted(ADAPTERS)


def get_adapter_class(name: str) -> type[BaseAdapter]:
    try:
        module_path, class_name = ADAPTERS[name].split(":")
    except KeyError:
        raise KeyError(f"unknown collector {name!r}; available: {', '.join(available()) or 'none'}") from None
    return getattr(import_module(module_path), class_name)
