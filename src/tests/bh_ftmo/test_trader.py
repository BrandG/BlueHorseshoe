from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from bud import auto_trader as trader
from bud import entry_location
from bud.auto_rising3bar import PairSpec
from bud.briefing import Cell
from bh_ftmo.trading import safety


class FakeTrader:
    def __init__(self, trades: list[dict] | None = None) -> None:
        self.trades = trades or []
        self.market_orders: list[dict] = []
        self.limit_orders: list[dict] = []
        self.closed: list[tuple[str, str]] = []

    def create_market_order_with_bracket(self, **kwargs):
        self.market_orders.append(kwargs)
        return {"orderCreateTransaction": {"id": f"m{len(self.market_orders)}"}}

    def create_limit_order_with_bracket(self, **kwargs):
        self.limit_orders.append(kwargs)
        return {"orderCreateTransaction": {"id": f"l{len(self.limit_orders)}"}}

    def get_open_trades(self):
        return self.trades

    def close_position(self, instrument: str, *, side: str = "all"):
        self.closed.append((instrument, side))
        return {}


def candidate(
    pair: str,
    *,
    source: str = trader.R3B_SOURCE,
    direction: str = "long",
    entry_mode: str = "market",
    risk_pct: float = 0.01,
    meta: dict | None = None,
) -> trader.OrderCandidate:
    default_meta = {"strategy": "stoch"} if source == trader.V2_SOURCE else {}
    if meta is not None:
        default_meta.update(meta)
    return trader.OrderCandidate(
        source=source,
        pair=pair,
        direction=direction,
        entry_mode=entry_mode,
        entry=1.0,
        stop=0.99 if direction == "long" else 1.01,
        target=1.01 if direction == "long" else 0.99,
        risk_pct=risk_pct,
        client_tag=f"{source}:tag",
        price_precision=5,
        gtd=None,
        meta=default_meta,
    )


def run_place(candidates, *, account=None, positions=None, dry_run=True):
    rows: list[dict] = []
    trader.place_candidates(
        trader=FakeTrader(),
        candidates=candidates,
        account_summary=account or {
            "NAV": 10000,
            "marginUsed": 0,
            "marginRate": 0.02,
        },
        open_positions=positions or [],
        mid_by_pair={
            "EUR_USD": 1.0,
            "GBP_USD": 1.0,
            "AUD_USD": 1.0,
            "NZD_USD": 1.0,
            "USD_CAD": 1.0,
        },
        account_ccy="USD",
        equity=10000,
        dry_run=dry_run,
        journal=rows.append,
    )
    return rows


def test_margin_budget_skips_when_headroom_runs_out_and_continues():
    rows = run_place(
        [
            candidate("EUR_USD"),
            candidate("GBP_USD"),
            candidate("AUD_USD"),
            candidate("NZD_USD"),
        ],
        account={"NAV": 10000, "marginUsed": 3900, "marginRate": 0.005},
    )

    assert [r["event"] for r in rows] == [
        "would_open",
        "would_open",
        "skip_margin_budget",
        "skip_margin_budget",
    ]


def test_skip_already_open_for_pair_in_open_pair_set():
    rows = run_place(
        [candidate("EUR_USD")],
        positions=[{"instrument": "EUR_USD", "long": {"units": "1"}, "short": {"units": "0"}}],
    )

    assert rows[0]["event"] == "skip_already_open"


def test_same_tick_conflict_v2_wins_over_rising3bar():
    rows = run_place([
        candidate("EUR_USD", source=trader.R3B_SOURCE),
        candidate("EUR_USD", source=trader.V2_SOURCE, entry_mode="mid"),
    ])

    assert [r["event"] for r in rows] == ["skip_conflict", "would_open"]
    assert rows[0]["source"] == trader.R3B_SOURCE
    assert rows[1]["source"] == trader.V2_SOURCE


def test_high_ny_skip_dark_mode_journals_and_still_places(monkeypatch):
    monkeypatch.setattr(entry_location, "HIGH_NY_SKIP_ENABLED", False)
    monkeypatch.setattr(trader, "HIGH_NY_SKIP_ENABLED", False)
    rows = run_place([
        candidate(
            "EUR_USD",
            source=trader.V2_SOURCE,
            meta={"high_ny_skip": True, "atr_pct": 0.8},
        )
    ])

    assert [r["event"] for r in rows] == ["would_skip_high_atr_ny", "would_open"]
    assert rows[0]["note"] == "atr_pct=0.80 session=ny"


def test_high_ny_skip_enabled_journals_and_blocks_open(monkeypatch):
    monkeypatch.setattr(entry_location, "HIGH_NY_SKIP_ENABLED", True)
    monkeypatch.setattr(trader, "HIGH_NY_SKIP_ENABLED", True)
    rows = run_place([
        candidate(
            "EUR_USD",
            source=trader.V2_SOURCE,
            meta={"high_ny_skip": True, "atr_pct": 0.8},
        )
    ])

    assert [r["event"] for r in rows] == ["skip_high_atr_ny"]
    assert rows[0]["note"] == "atr_pct=0.80 session=ny"


def test_high_ny_skip_absent_meta_does_not_journal_location_row(monkeypatch):
    monkeypatch.setattr(entry_location, "HIGH_NY_SKIP_ENABLED", False)
    monkeypatch.setattr(trader, "HIGH_NY_SKIP_ENABLED", False)
    rows = run_place([candidate("EUR_USD", source=trader.V2_SOURCE)])

    assert [r["event"] for r in rows] == ["would_open"]


def test_direction_gate_uses_shared_mutating_counts():
    positions = [
        {"instrument": f"LONG_{i}", "long": {"units": "1"}, "short": {"units": "0"}}
        for i in range(12)
    ]
    rows = run_place(
        [
            candidate("USD_CAD", direction="short"),
            candidate("EUR_USD", direction="long"),
        ],
        positions=positions,
    )

    assert [r["event"] for r in rows] == ["would_open", "would_open"]


def test_close_aged_positions_handles_rising_and_v2_limit_but_not_v2_mid():
    now = datetime(2026, 5, 27, tzinfo=UTC)
    old = (now - timedelta(days=6)).isoformat().replace("+00:00", "Z")
    fake = FakeTrader([
        {
            "clientExtensions": {"tag": "rising3bar:202605010100"},
            "openTime": old,
            "instrument": "EUR_USD",
            "currentUnits": "100",
        },
        {
            "clientExtensions": {"tag": "v2:macd:long:202605010100"},
            "openTime": old,
            "instrument": "AUD_JPY",
            "currentUnits": "100",
        },
        {
            "clientExtensions": {"tag": "v2:stoch:long:202605010100"},
            "openTime": old,
            "instrument": "CHF_JPY",
            "currentUnits": "100",
        },
    ])
    config = {
        "bh_ftmo_trader": {
            "max_position_age_days_by_source": {
                "rising_3bar": 5,
                "v2": {"limit": 5, "mid": None},
            }
        }
    }

    closed = trader.close_aged_positions(
        fake, config, dry_run=False, now=now, journal=lambda row: None,
    )

    assert closed == 2
    assert fake.closed == [("EUR_USD", "long"), ("AUD_JPY", "long")]


def test_both_sources_emit_candidates_from_synthetic_bars(monkeypatch):
    bars = pd.DataFrame({
        "timestamp": pd.date_range("2026-05-01", periods=80, freq="4h", tz=UTC),
        "open_bid": [0.99] * 80,
        "high_bid": [1.01] * 80,
        "low_bid": [0.98] * 80,
        "close_bid": [1.0] * 80,
        "open_ask": [1.0] * 80,
        "high_ask": [1.02] * 80,
        "low_ask": [0.99] * 80,
        "close_ask": [1.01] * 80,
    })
    monkeypatch.setattr(trader, "evaluate_trigger_on_last_bar", lambda mid: (True, 25.0))
    monkeypatch.setattr(trader, "evaluate_cell", lambda cell, mid: True)
    monkeypatch.setattr(trader, "compute_entry_stop_target", lambda cell, mid: (1.0, 0.99, 1.005))

    r3b = trader.Rising3BarSource([PairSpec("EUR_USD", 0.0001, 5)])
    v2 = trader.V2CellSource([Cell("stoch", "GBP_USD", "long", "mid", {})])
    bars_by_pair = {"EUR_USD": bars, "GBP_USD": bars}
    mid_by_pair = {"EUR_USD": 1.005, "GBP_USD": 1.005}

    assert len(r3b.candidates(
        bars_by_pair=bars_by_pair, mid_by_pair=mid_by_pair,
        account_ccy="USD", equity=10000,
    )) == 1
    assert len(v2.candidates(
        bars_by_pair=bars_by_pair, mid_by_pair=mid_by_pair,
        account_ccy="USD", equity=10000,
    )) == 1


def test_v2_source_sets_high_ny_skip_candidate_meta(monkeypatch):
    bars = pd.DataFrame({
        "timestamp": pd.date_range("2026-05-01", periods=80, freq="4h", tz=UTC),
        "open_bid": [0.99] * 80,
        "high_bid": [1.01] * 80,
        "low_bid": [0.98] * 80,
        "close_bid": [1.0] * 80,
        "open_ask": [1.0] * 80,
        "high_ask": [1.02] * 80,
        "low_ask": [0.99] * 80,
        "close_ask": [1.01] * 80,
    })
    monkeypatch.setattr(trader, "evaluate_cell", lambda cell, mid: True)
    monkeypatch.setattr(trader, "compute_entry_stop_target", lambda cell, mid: (1.0, 0.99, 1.005))
    monkeypatch.setattr(trader, "is_high_ny_skip", lambda strategy, direction, bar_ts, mid: True)
    monkeypatch.setattr(trader, "atr_pct_w252", lambda mid: 0.8)

    v2 = trader.V2CellSource([Cell("stoch", "GBP_USD", "long", "mid", {})])
    candidates = v2.candidates(
        bars_by_pair={"GBP_USD": bars},
        mid_by_pair={"GBP_USD": 1.005},
        account_ccy="USD",
        equity=10000,
    )

    assert len(candidates) == 1
    assert candidates[0].meta["high_ny_skip"] is True
    assert candidates[0].meta["atr_pct"] == pytest.approx(0.8)


def test_safety_margin_helpers():
    assert safety.margin_headroom({"NAV": 100000, "marginUsed": 39000}, 0.40) == 1000
    assert safety.margin_headroom({"NAV": 100000, "marginUsed": 41000}, 0.40) == -1000
    assert safety.estimate_order_margin(
        units=-10000, entry_price=1.25, quote_to_account=1.1, margin_rate=0.02,
    ) == pytest.approx(275.0)
