"""Typed helpers for reading configuration from environment variables."""

from __future__ import annotations

import os
from typing import List, Optional


class ConfigurationError(RuntimeError):
    """Raised when a required environment variable is missing or malformed."""


def env_str(name: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    """Return the environment variable ``name`` stripped of whitespace."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        if required and default is None:
            raise ConfigurationError(f"Required environment variable {name} is not set")
        return default
    return value.strip()


def env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable (true/false/1/0/yes/no/on/off)."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    normalised = value.strip().lower()
    if normalised in {"1", "true", "yes", "on", "y", "t"}:
        return True
    if normalised in {"0", "false", "no", "off", "n", "f"}:
        return False
    raise ConfigurationError(f"Environment variable {name} must be a boolean, got {value!r}")


def env_int(name: str, default: int) -> int:
    """Parse an integer environment variable."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ConfigurationError(f"Environment variable {name} must be an integer, got {value!r}") from exc


def env_float(name: str, default: float) -> float:
    """Parse a floating point environment variable."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value.strip())
    except ValueError as exc:
        raise ConfigurationError(f"Environment variable {name} must be a number, got {value!r}") from exc


def env_list(name: str, default: Optional[List[str]] = None, separator: str = ",") -> List[str]:
    """Parse a delimited list environment variable, dropping empty items."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return list(default or [])
    return [item.strip() for item in value.split(separator) if item.strip()]
