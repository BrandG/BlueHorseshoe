"""
Shared invalid-symbol loading helpers.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

from bluehorseshoe.core.config import REPO_ROOT

DEFAULT_INVALID_SYMBOLS_FILE = Path(REPO_ROOT) / "src" / "historical_data" / "invalid_symbols.txt"


def resolve_invalid_symbols_path(base_path: str | None = None) -> Path:
    """Resolve the canonical invalid-symbol file path."""
    if base_path:
        return Path(base_path) / "invalid_symbols.txt"
    return DEFAULT_INVALID_SYMBOLS_FILE


def load_invalid_symbols(path: str | Path | None = None) -> list[str]:
    """Load invalid symbols as an ordered list."""
    resolved = Path(path) if path is not None else DEFAULT_INVALID_SYMBOLS_FILE
    if not resolved.exists():
        return []
    try:
        with open(resolved, "r", encoding="utf-8") as handle:
            return [line.strip() for line in handle if line.strip()]
    except OSError as exc:
        logging.error("Error reading invalid symbols file %s: %s", resolved, exc)
        return []


def load_invalid_symbol_set(path: str | Path | None = None) -> set[str]:
    """Load invalid symbols as a normalized uppercase set."""
    return {symbol.upper() for symbol in load_invalid_symbols(path=path)}

