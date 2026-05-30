"""Tests for the shared FTMO trade-envelope helpers (extracted from bh_lite)."""
import json

from bud.envelope import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_POSITIONS_PATH,
    load_config,
    load_positions,
    symbol_to_clusters_map,
)


def test_default_paths_point_at_bud_state_files():
    assert DEFAULT_CONFIG_PATH.endswith("config.json")
    assert "bud" in DEFAULT_CONFIG_PATH
    assert DEFAULT_POSITIONS_PATH.endswith("positions.json")
    assert "bud" in DEFAULT_POSITIONS_PATH


def test_load_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"account": {"size": 100000}, "risk": {}}))
    config = load_config(str(path))
    assert config["account"]["size"] == 100000
    assert "risk" in config


def test_load_positions_missing_file(tmp_path):
    assert load_positions(str(tmp_path / "missing.json")) == []


def test_load_positions_empty_and_malformed(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text("[]")
    assert load_positions(str(empty)) == []

    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    assert load_positions(str(bad)) == []


def test_load_positions_with_data(tmp_path):
    positions = [{"ftmo_symbol": "EURUSD.sim", "risk_usd": 50.0}]
    path = tmp_path / "positions.json"
    path.write_text(json.dumps(positions))
    assert load_positions(str(path)) == positions


def test_symbol_to_clusters_map_multi_membership():
    clusters = {
        "euro_majors_usd": ["EURUSD.sim", "GBPUSD.sim"],
        "eur_crosses": ["EURUSD.sim", "EURGBP.sim"],
    }
    mapping = symbol_to_clusters_map(clusters)
    # EURUSD belongs to both clusters, order preserved from config iteration.
    assert mapping["EURUSD.sim"] == ["euro_majors_usd", "eur_crosses"]
    assert mapping["GBPUSD.sim"] == ["euro_majors_usd"]
    assert mapping["EURGBP.sim"] == ["eur_crosses"]
