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
import os
from typing import Dict, List, Sequence

# State files live in src/bud/ alongside this module.
_BUD_DIR = os.path.dirname(__file__)
DEFAULT_CONFIG_PATH = os.path.join(_BUD_DIR, "config.json")
DEFAULT_POSITIONS_PATH = os.path.join(_BUD_DIR, "positions.json")


def load_config(path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Load the FTMO envelope JSON config."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_positions(path: str = DEFAULT_POSITIONS_PATH) -> List[dict]:
    """Load open positions. Returns empty list if file missing or empty."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            positions = json.load(f)
        return positions if isinstance(positions, list) else []
    except (json.JSONDecodeError, OSError):
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
