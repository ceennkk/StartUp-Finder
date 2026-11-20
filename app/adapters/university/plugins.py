from __future__ import annotations

import re
from typing import Any

from app.adapters.university.connectors import Connector, Item


class UniversityPlugin:
    """Per-university hook. Override `connector` for sites no generic connector can read, or `enrich` to add fields."""

    connector: Connector | None = None

    def enrich(self, item: Item, source: dict[str, Any]) -> Item:
        return item


class KitPlugin(UniversityPlugin):
    """KIT press releases: the URL carries year and running number (pi_2026_094_...)."""

    _NUMBER = re.compile(r"pi_(\d{4})_(\d+)_")

    def enrich(self, item: Item, source: dict[str, Any]) -> Item:
        match = self._NUMBER.search(item["url"])
        if match:
            item["extra"] = {**item.get("extra", {}), "press_release_number": f"{match.group(1)}/{match.group(2)}"}
        return item


PLUGINS: dict[str, type[UniversityPlugin]] = {"kit": KitPlugin}


def get_plugin(name: str | None) -> UniversityPlugin:
    if not name:
        return UniversityPlugin()
    try:
        return PLUGINS[name]()
    except KeyError:
        raise KeyError(f"unknown university plugin {name!r}; available: {', '.join(sorted(PLUGINS))}") from None
