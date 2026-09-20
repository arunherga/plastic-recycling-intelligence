"""Configuration loading.

Everything the agent does is driven by ``config.yaml``. This module is the only
place that knows where that file lives and what the defaults are, so tests can
build a ``Config`` from a dict without touching disk.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"


class Config:
    """Thin, dotted-path wrapper around the parsed YAML."""

    def __init__(self, data: dict[str, Any], root: Path | None = None) -> None:
        self._data = data or {}
        self.root = root or REPO_ROOT

    # -- access -----------------------------------------------------------
    def get(self, path: str, default: Any = None) -> Any:
        """Fetch a nested value with a dotted path, e.g. ``"ai.enabled"``."""
        node: Any = self._data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def path(self, relative: str) -> Path:
        """Resolve a config-declared relative path against the repo root."""
        p = Path(relative)
        return p if p.is_absolute() else self.root / p

    # -- convenience ------------------------------------------------------
    @property
    def user_agent(self) -> str:
        return self.get("app.user_agent", "plastic-recycling-intelligence/1.0")

    @property
    def http_timeout(self) -> int:
        return int(self.get("app.http_timeout_seconds", 20))

    @property
    def queries(self) -> list[str]:
        return list(self.get("queries", []) or [])

    def source_config(self, name: str) -> dict[str, Any]:
        return dict(self.get(f"sources.{name}", {}) or {})

    def source_enabled(self, name: str) -> bool:
        return bool(self.source_config(name).get("enabled", False))


def load_config(path: str | Path | None = None) -> Config:
    """Load configuration from disk.

    The path can be overridden with the ``PRI_CONFIG`` environment variable,
    which keeps local experiments out of the committed config file.
    """
    candidate = path or os.environ.get("PRI_CONFIG") or DEFAULT_CONFIG_PATH
    config_path = Path(candidate)
    with config_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return Config(data, root=config_path.resolve().parent)
