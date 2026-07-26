"""Shared YAML configuration loading adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigLoadError(RuntimeError):
    """Raised when a configuration file cannot be loaded as a mapping."""


def default_config_path() -> Path:
    """Return the repository-level `config.yaml` path."""

    return Path(__file__).resolve().parents[3] / "config.yaml"


def load_yaml_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load a YAML config file without interpreting feature-specific fields."""

    config_path = Path(path) if path is not None else default_config_path()
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigLoadError(f"Cannot read config file: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigLoadError(f"Invalid YAML config file: {config_path}") from exc

    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigLoadError(f"Config root must be a mapping: {config_path}")
    return loaded
