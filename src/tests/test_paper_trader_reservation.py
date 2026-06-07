"""Tests for the deep_oversold slot reservation in PaperTrader.

Covers _select_with_reservation (pure selection: reserved budgets + spillover +
global cap) and _occupied_by_strategy (per-strategy occupancy mapping via the
paper_trades collection). All mocked — no broker, no real DB.
"""
from unittest.mock import MagicMock

from bluehorseshoe.trading.paper_trader import PaperTradeConfig, PaperTrader


def _cand(symbol, strategy, score):
    return {"symbol": symbol, "strategy": strategy, "score": score,
            "close": 50.0, "stop_loss": 47.5, "target": 55.0}


def _trader(slots_deep=3, db=None, conviction_sizing=True, max_position_mult=2.5):
    client = MagicMock(spec=["get_account_summary", "get_positions", "get_open_trades"])
    config = PaperTradeConfig(total_investment=10000.0, max_positions=10,
                              logs_path="/tmp", slots_deep_oversold=slots_deep,
                              conviction_sizing=conviction_sizing,
                              max_position_mult=max_position_mult)
    return PaperTrader(ibkr_client=client, config=config, database=db)


def _counts(selected):
    deep = sum(1 for c in selected if c["strategy"] == "DeepOS")
    return deep, len(selected) - deep


class TestSelectWithReservation:

    def test_reserves_three_for_deepos(self):
        trader = _trader()
        eligible = ([_cand(f"D{i}", "DeepOS", 25 - i) for i in range(6)] +
                    [_cand(f"L{i}", "Baseline", 9 - i * 0.1) for i in range(10)])
        sel = trader._select_with_reservation(eligible, set(), 10)
        deep, legacy = _counts(sel)
        assert (deep, legacy) == (3, 7)

    def test_spillover_fills_legacy_when_deepos_thin(self):
        """Only 1 DeepOS candidate → its 2 idle reserved slots spill to legacy."""
        trader = _trader()
        eligible = ([_cand("D0", "DeepOS", 20)] +
                    [_cand(f"L{i}", "MeanRev", 9 - i * 0.1) for i in range(12)])
        sel = trader._select_with_reservation(eligible, set(), 10)
        deep, legacy = _counts(sel)
        assert (deep, legacy) == (1, 9)

    def test_spillover_fills_deepos_when_legacy_thin(self):
        """Only 2 legacy candidates → DeepOS gets its 3 + 5 spillover = 8."""
        trader = _trader()
        eligible = ([_cand(f"D{i}", "DeepOS", 25 - i) for i in range(8)] +
                    [_cand(f"L{i}", "Baseline", 9 - i) for i in range(2)])
        sel = trader._select_with_reservation(eligible, set(), 10)
        deep, legacy = _counts(sel)
        assert (deep, legacy) == (8, 2)

    def test_reservation_disabled_is_global_topn(self):
        trader = _trader(slots_deep=0)
        eligible = [_cand(f"D{i}", "DeepOS", 25 - i) for i in range(15)]
        sel = trader._select_with_reservation(eligible, set(), 10)
        assert len(sel) == 10

    def test_global_topn_is_edge_weighted(self):
        """Higher validated edge wins the slot even with a LOWER raw score.

        DeepOS 20 * 0.142 = 2.84 vs DeepOS+HA 16 * 0.404 = 6.46 → HA wins.
        """
        trader = _trader(slots_deep=0)
        eligible = [_cand("DEEP", "DeepOS", 20), _cand("HA", "DeepOS+HA", 16)]
        sel = trader._select_with_reservation(eligible, set(), 1)
        assert [c["symbol"] for c in sel] == ["HA"]

    def test_unvalidated_source_fills_only_leftover(self):
        """An unregistered sleeve (Connors, edge_weight 0) sinks below any validated
        sleeve regardless of raw score: DeepOS 10*0.142=1.42 > Connors 99*0.0=0."""
        trader = _trader(slots_deep=0)
        eligible = [_cand("CONN", "Connors", 99), _cand("DEEP", "DeepOS", 10)]
        sel = trader._select_with_reservation(eligible, set(), 1)
        assert [c["symbol"] for c in sel] == ["DEEP"]

    def test_global_cap_binds(self):
        """slots_available=2 caps everything even with full reserved budgets."""
        trader = _trader()
        eligible = ([_cand(f"D{i}", "DeepOS", 30 - i) for i in range(3)] +
                    [_cand(f"L{i}", "Baseline", 8) for i in range(7)])
        sel = trader._select_with_reservation(eligible, set(), 2)
        assert len(sel) == 2

    def test_no_slots_returns_empty(self):
        trader = _trader()
        eligible = [_cand("D0", "DeepOS", 20)]
        assert trader._select_with_reservation(eligible, {"X", "Y"}, 0) == []


class TestConvictionSizing:
    """_position_sizes: pot split proportional to sleeve edge_weight (base=$1000)."""

    def test_single_sleeve_is_flat(self):
        # One sleeve → equal weights → reduces exactly to flat $1000 each.
        trader = _trader()
        cands = [_cand(f"D{i}", "DeepOS", 20 - i) for i in range(3)]
        sizes = trader._position_sizes(cands)
        assert all(abs(v - 1000.0) < 1e-6 for v in sizes.values())

    def test_mixed_book_tilts_to_higher_edge(self):
        # [HA, DeepOS]: pot=2000, HA 0.404 vs DeepOS 0.142 → HA ~1479.85, DeepOS ~520.15.
        trader = _trader()
        ha, deep = _cand("HA", "DeepOS+HA", 16), _cand("DEEP", "DeepOS", 22)
        sizes = trader._position_sizes([ha, deep])
        assert sizes[id(ha)] > sizes[id(deep)]
        assert abs(sizes[id(ha)] + sizes[id(deep)] - 2000.0) < 1e-6  # pot conserved
        assert abs(sizes[id(ha)] - 2000.0 * 0.404 / 0.546) < 1e-3

    def test_cap_bounds_concentration(self):
        # cap = 1.0 * base = 1000 → HA's 1479.85 is clamped to 1000.
        trader = _trader(max_position_mult=1.0)
        ha, deep = _cand("HA", "DeepOS+HA", 16), _cand("DEEP", "DeepOS", 22)
        sizes = trader._position_sizes([ha, deep])
        assert abs(sizes[id(ha)] - 1000.0) < 1e-6

    def test_disabled_is_flat(self):
        trader = _trader(conviction_sizing=False)
        ha, deep = _cand("HA", "DeepOS+HA", 16), _cand("DEEP", "DeepOS", 22)
        sizes = trader._position_sizes([ha, deep])
        assert sizes[id(ha)] == 1000.0 and sizes[id(deep)] == 1000.0

    def test_all_unvalidated_falls_back_to_flat(self):
        # Connors only (edge_weight 0) → total_w 0 → flat fallback (slot not wasted).
        trader = _trader()
        c1, c2 = _cand("X", "Connors", 50), _cand("Y", "Connors", 40)
        sizes = trader._position_sizes([c1, c2])
        assert sizes[id(c1)] == 1000.0 and sizes[id(c2)] == 1000.0

    def test_unvalidated_among_validated_sizes_to_zero(self):
        # Connors (0) in a validated set → $0 (its slot's capital flows to DeepOS).
        trader = _trader()
        conn, deep = _cand("CONN", "Connors", 99), _cand("DEEP", "DeepOS", 10)
        sizes = trader._position_sizes([conn, deep])
        assert sizes[id(conn)] == 0.0
        assert abs(sizes[id(deep)] - 2000.0) < 1e-6  # gets the whole pot


class TestPreviewFractionalPlan:
    """preview_fractional_plan: report-side sizing — unfloored, conviction-weighted, empty book."""

    def test_fractional_unfloored_and_conviction_weighted(self):
        trader = _trader(slots_deep=0)
        ha = _cand("HA", "DeepOS+HA", 16)
        deep = _cand("DEEP", "DeepOS", 22)
        plan = trader.preview_fractional_plan([ha, deep])
        # both selected (empty book, 2 < 10 slots); HA out-dollars DeepOS (higher edge)
        assert plan[id(ha)]["dollars"] > plan[id(deep)]["dollars"]
        # shares ≈ dollars/price (within 4dp/2dp rounding), NOT floored to int
        assert abs(plan[id(ha)]["shares"] - plan[id(ha)]["dollars"] / 50.0) < 1e-2
        assert plan[id(ha)]["shares"] != int(plan[id(ha)]["shares"])  # genuinely fractional

    def test_tracking_only_excluded(self):
        # Baseline is tracking-only (paper_tradeable False) → never in the plan.
        trader = _trader(slots_deep=0)
        base = _cand("BL", "Baseline", 99)
        deep = _cand("DEEP", "DeepOS", 10)
        plan = trader.preview_fractional_plan([base, deep])
        assert id(base) not in plan
        assert id(deep) in plan


class TestTrackingOnlyExclusion:
    """submit_orders drops paper_tradeable=False sleeves (e.g. ADX-Down) before any live order."""

    def _live_trader(self):
        client = MagicMock()
        client.get_account_summary.return_value = {"account_id": "DU123"}  # reachable
        client.get_positions.return_value = []
        client.get_open_trades.return_value = []
        client.place_bracket_order.return_value = {"status": "submitted", "order_ids": [1, 2]}
        config = PaperTradeConfig(total_investment=10000.0, max_positions=10,
                                  logs_path="/tmp", slots_deep_oversold=3)
        return PaperTrader(ibkr_client=client, config=config, database=None), client

    def test_adx_down_candidate_is_never_submitted(self):
        trader, client = self._live_trader()
        cands = [_cand("DEEP1", "DeepOS", 20), _cand("ADXD1", "ADX-Down", 25)]
        results = trader.execute(cands, "2026-06-07")
        # The tracking-only sleeve must not appear in results or reach the broker.
        assert all(r.strategy != "ADX-Down" for r in results)
        ordered_symbols = {c.kwargs.get("symbol") for c in client.place_bracket_order.call_args_list}
        assert "ADXD1" not in ordered_symbols
        assert "DEEP1" in ordered_symbols  # the live sleeve still trades


class TestOccupiedByStrategy:

    def test_counts_deepos_positions_on_book(self):
        db = MagicMock()
        coll = MagicMock()
        db.__getitem__.return_value = coll
        # AAA & BBB opened by DeepOS; CCC by Baseline.
        coll.find_one.side_effect = lambda flt, **kw: {
            "AAA": {"strategy": "DeepOS"},
            "BBB": {"strategy": "DeepOS"},
            "CCC": {"strategy": "Baseline"},
        }.get(flt["symbol"])
        trader = _trader(db=db)
        assert trader._occupied_by_strategy({"AAA", "BBB", "CCC"}, "DeepOS") == 2

    def test_unknown_symbols_bucket_as_legacy(self):
        db = MagicMock()
        coll = MagicMock()
        db.__getitem__.return_value = coll
        coll.find_one.return_value = None  # no record for any symbol
        trader = _trader(db=db)
        assert trader._occupied_by_strategy({"XXX", "YYY"}, "DeepOS") == 0

    def test_occupancy_reduces_deepos_open_slots(self):
        """1 DeepOS already on the book → only 2 of the 3 reserved slots remain."""
        db = MagicMock()
        coll = MagicMock()
        db.__getitem__.return_value = coll
        coll.find_one.side_effect = lambda flt, **kw: (
            {"strategy": "DeepOS"} if flt["symbol"] == "HELD" else {"strategy": "Baseline"}
        )
        trader = _trader(db=db)
        eligible = ([_cand(f"D{i}", "DeepOS", 25 - i) for i in range(6)] +
                    [_cand(f"L{i}", "Baseline", 9 - i * 0.1) for i in range(10)])
        # 2 occupied: HELD (DeepOS) + OTHER (legacy). slots_available = 10 - 2 = 8.
        sel = trader._select_with_reservation(eligible, {"HELD", "OTHER"}, 8)
        deep, legacy = _counts(sel)
        # DeepOS: 3 reserved - 1 occ = 2 open. legacy: 7 reserved - 1 occ = 6 open. 2+6=8.
        assert (deep, legacy) == (2, 6)
