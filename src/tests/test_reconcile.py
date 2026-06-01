"""Tests for the BH FTMO closed-trade outcome reconciler."""
# pylint: disable=missing-function-docstring,redefined-outer-name
# pylint: disable=missing-class-docstring,too-few-public-methods

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from bud import reconcile


class FakeTrader:
    def __init__(self, trades: list[dict]) -> None:
        self.trades = trades

    def get_closed_trades(self) -> list[dict]:
        return self.trades


@pytest.fixture
def outcome_paths(tmp_path, monkeypatch) -> tuple[Path, Path]:
    journal_path = tmp_path / "bh_ftmo_trader_journal.csv"
    outcomes_path = tmp_path / "bh_ftmo_outcomes.csv"
    monkeypatch.setattr(reconcile, "JOURNAL_PATH", journal_path)
    monkeypatch.setattr(reconcile, "OUTCOMES_PATH", outcomes_path)
    return journal_path, outcomes_path


def _trade(
    *,
    trade_id: str = "10",
    tag: str | None = "v2:macd:long:202605311600",
    close_price: str = "1.1200",
    instrument: str = "EUR_USD",
    open_price: str = "1.1000",
) -> dict:
    trade = {
        "id": trade_id,
        "instrument": instrument,
        "initialUnits": "10000",
        "price": open_price,
        "averageClosePrice": close_price,
        "realizedPL": "100.00",
        "financing": "-1.25",
        "openTime": "2026-05-31T16:00:00.000000000Z",
        "closeTime": "2026-06-01T16:00:00.000000000Z",
    }
    if tag is not None:
        trade["clientExtensions"] = {"tag": tag}
    return trade


def _write_journal(path: Path, *, target_price: str = "1.1200", stop_price: str = "1.0900") -> None:
    fields = [
        "ts_utc", "run_mode", "event", "source", "strategy", "pair", "direction",
        "entry_mode", "trigger_bar_ts", "trigger_bar_close_ts", "entry_price",
        "entry_mid", "stop_price", "target_price", "gtd_time_utc", "units",
        "equity", "risk_dollars", "quote_to_account", "est_margin", "headroom",
        "rsi_at_entry", "rsi_oversold", "risk_multiplier", "order_id", "status",
        "note",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "event": "order_placed",
            "source": "v2",
            "strategy": "macd",
            "pair": "EUR_USD",
            "direction": "long",
            "entry_mode": "limit",
            "trigger_bar_close_ts": "2026-05-31T16:00:00+00:00",
            "entry_price": "1.1000",
            "stop_price": stop_price,
            "target_price": target_price,
            "units": "10000",
            "risk_dollars": "50.00",
            "order_id": "123",
            "status": "submitted",
        })


def _read_outcomes(path: Path) -> list[dict[str, str]]:
    with open(path, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_matching_placement_writes_realized_r_and_target_reason(outcome_paths):
    journal_path, outcomes_path = outcome_paths
    _write_journal(journal_path)

    written = reconcile.reconcile_outcomes(FakeTrader([_trade()]))

    assert written == 1
    rows = _read_outcomes(outcomes_path)
    assert len(rows) == 1
    assert rows[0]["trade_id"] == "10"
    assert rows[0]["tag"] == "v2:macd:long:202605311600"
    assert rows[0]["realized_r"] == "2"
    assert rows[0]["r_multiple_price"] == "2"
    assert rows[0]["close_reason"] == "target"


def test_rerun_dedupes_on_trade_id(outcome_paths):
    journal_path, outcomes_path = outcome_paths
    _write_journal(journal_path)

    assert reconcile.reconcile_outcomes(FakeTrader([_trade()])) == 1
    assert reconcile.reconcile_outcomes(FakeTrader([_trade()])) == 0

    assert len(_read_outcomes(outcomes_path)) == 1


def test_untagged_trade_is_skipped(outcome_paths):
    _, outcomes_path = outcome_paths

    written = reconcile.reconcile_outcomes(FakeTrader([_trade(tag=None)]))

    assert written == 0
    assert not outcomes_path.exists()


def test_tagged_trade_without_matching_placement_keeps_null_r(outcome_paths):
    _, outcomes_path = outcome_paths

    written = reconcile.reconcile_outcomes(FakeTrader([_trade()]))

    assert written == 1
    row = _read_outcomes(outcomes_path)[0]
    assert row["risk_dollars"] == ""
    assert row["realized_r"] == ""
    assert row["r_multiple_price"] == ""
    assert row["close_reason"] == "unknown"


def test_dry_run_returns_zero_and_writes_nothing(outcome_paths):
    journal_path, outcomes_path = outcome_paths
    _write_journal(journal_path)

    written = reconcile.reconcile_outcomes(FakeTrader([_trade()]), dry_run=True)

    assert written == 0
    assert not outcomes_path.exists()


@pytest.mark.parametrize(
    ("close_price", "expected"),
    [
        ("1.1203", "target"),
        ("1.0902", "stop"),
        ("1.1050", "aged_or_manual"),
    ],
)
def test_close_reason_price_inference(outcome_paths, close_price, expected):
    journal_path, outcomes_path = outcome_paths
    _write_journal(journal_path)

    written = reconcile.reconcile_outcomes(
        FakeTrader([_trade(trade_id=close_price, close_price=close_price)])
    )

    assert written == 1
    assert _read_outcomes(outcomes_path)[0]["close_reason"] == expected


def _write_placements(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "ts_utc", "run_mode", "event", "source", "strategy", "pair", "direction",
        "entry_mode", "trigger_bar_ts", "trigger_bar_close_ts", "entry_price",
        "entry_mid", "stop_price", "target_price", "gtd_time_utc", "units",
        "equity", "risk_dollars", "quote_to_account", "est_margin", "headroom",
        "rsi_at_entry", "rsi_oversold", "risk_multiplier", "order_id", "status",
        "note",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_shared_tag_joins_each_trade_to_its_own_pair(outcome_paths):
    # Two pairs, same strategy/direction/bar -> identical tag v2:cci:long:<ts>.
    # Each closed trade must join to ITS pair's placement, not the last-written one.
    journal_path, outcomes_path = outcome_paths
    base = {
        "event": "order_placed", "source": "v2", "strategy": "cci", "direction": "long",
        "entry_mode": "limit", "trigger_bar_close_ts": "2026-05-31T16:00:00+00:00",
    }
    _write_placements(journal_path, [
        {**base, "pair": "EUR_USD", "stop_price": "1.0900", "target_price": "1.1200", "risk_dollars": "50.00"},
        {**base, "pair": "USD_JPY", "stop_price": "150.000", "target_price": "156.000", "risk_dollars": "80.00"},
    ])

    written = reconcile.reconcile_outcomes(FakeTrader([
        _trade(trade_id="1", tag="v2:cci:long:202605311600", instrument="EUR_USD",
               open_price="1.1000", close_price="1.1200"),
        _trade(trade_id="2", tag="v2:cci:long:202605311600", instrument="USD_JPY",
               open_price="153.000", close_price="156.000"),
    ]))

    assert written == 2
    by_pair = {r["pair"]: r for r in _read_outcomes(outcomes_path)}
    assert by_pair["EUR_USD"]["risk_dollars"] == "50.00"
    assert by_pair["EUR_USD"]["close_reason"] == "target"
    assert by_pair["USD_JPY"]["risk_dollars"] == "80.00"
    assert by_pair["USD_JPY"]["close_reason"] == "target"
