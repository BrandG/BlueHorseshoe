"""Shared FTMO trade-envelope config + position loaders.

These small, pure helpers define the FTMO trading envelope (account/risk/
instruments/clusters config and open-position state) consumed by the live
briefing tools. They were extracted from the retired ``bh_lite.py`` so that
``bud.briefing_ftmo`` no longer depends on the dormant bh_lite scoring module.
See docs/planning/BH_LITE_SUNDOWN.md.

State files live next to this module under ``src/bud/`` after Tier 3
(2026-05-30): ``config.json`` (shared envelope) and ``positions.json``
(live FTMO position state).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Sequence

LOG = logging.getLogger("bud.envelope")

# State files live in src/bud/ alongside this module.
_BUD_DIR = os.path.dirname(__file__)
DEFAULT_CONFIG_PATH = os.path.join(_BUD_DIR, "config.json")
DEFAULT_POSITIONS_PATH = os.path.join(_BUD_DIR, "positions.json")


class PositionsUnreadable(Exception):
    """positions.json exists but couldn't be parsed into a position list.

    Lets callers tell "no open positions" (a legitimately empty list) apart from
    "couldn't read the positions file" (corrupt / mid-write / wrong shape), so a
    read failure isn't silently reported as a flat, position-free briefing.
    """


def load_config(path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Load the FTMO envelope JSON config."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_positions_strict(path: str = DEFAULT_POSITIONS_PATH) -> List[dict]:
    """Load open positions, raising :class:`PositionsUnreadable` when the file
    exists but can't be parsed as a JSON list.

    A missing or whitespace-only file is treated as "no positions" (returns []);
    only genuine corruption / wrong shape raises, so a caller can surface the
    difference instead of guessing.
    """
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as exc:
        raise PositionsUnreadable(f"could not read {path}: {exc}") from exc
    if not raw.strip():
        return []
    try:
        positions = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PositionsUnreadable(
            f"{path} is not valid JSON ({exc}); position data unavailable") from exc
    if not isinstance(positions, list):
        raise PositionsUnreadable(
            f"{path} did not contain a JSON list; position data unavailable")
    return positions


def load_positions(path: str = DEFAULT_POSITIONS_PATH) -> List[dict]:
    """Load open positions. Returns empty list if file missing, empty, or
    unreadable (logging a warning in the unreadable case). Use
    :func:`load_positions_strict` when the caller needs to react to a read
    failure rather than silently treat it as "no positions"."""
    try:
        return load_positions_strict(path)
    except PositionsUnreadable as exc:
        LOG.warning("%s", exc)
        return []


def symbol_to_clusters_map(clusters: Dict[str, Sequence[str]]) -> Dict[str, List[str]]:
    """Invert cluster config into ftmo_symbol -> list of cluster_names.

    A symbol can belong to multiple clusters; order preserved from config iteration.
    """
    mapping: Dict[str, List[str]] = {}
    for cluster_name, symbols in clusters.items():
        for symbol in symbols:
            mapping.setdefault(symbol, []).append(cluster_name)
    return mapping
