"""Shared FTMO trade-envelope config + position loaders.

These small, pure helpers define the FTMO trading envelope (account/risk/
instruments/clusters config and open-position state) consumed by the live
briefing tools. They were extracted from ``bh_lite.py`` so that
``bh_briefing_ftmo.py`` no longer depends on the (superseded, dormant) bh_lite
scoring module. See docs/planning/BH_LITE_SUNDOWN.md.

The JSON filenames (``bh_lite_config.json`` / ``bh_lite_positions.json``) are
retained as-is; renaming them has blast radius across the briefing code and is
deferred.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Sequence

# The bh_lite_*.json files still live at src/ (Tier 3 will move them with the
# rest of the config envelope). envelope.py moved to src/bud/, so anchor to
# this file's grandparent (== src/) rather than its parent (== src/bud/).
_SRC_DIR = os.path.dirname(os.path.dirname(__file__))
DEFAULT_CONFIG_PATH = os.path.join(_SRC_DIR, "bh_lite_config.json")
DEFAULT_POSITIONS_PATH = os.path.join(_SRC_DIR, "bh_lite_positions.json")


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
