"""Unit tests for `bud.positions` sync helpers (OANDA open-trade → positions.json).

These cover the pure mapping/aggregation logic only — no network, no OANDA.
"""
from bud.positions import _trade_to_position, _trades_to_positions


def _trade(instrument, units, *, price=None, sl=None, tp=None, tag=None,
           open_time="2026-06-12T01:00:00.000000000Z"):
    t = {"instrument": instrument, "currentUnits": str(units), "openTime": open_time}
    if price is not None:
        t["price"] = str(price)
    if sl is not None:
        t["stopLossOrder"] = {"price": str(sl)}
    if tp is not None:
        t["takeProfitOrder"] = {"price": str(tp)}
    if tag is not None:
        t["clientExtensions"] = {"tag": tag}
    return t


def test_long_trade_maps_to_buy_with_lots_and_levels():
    pos = _trade_to_position(_trade("USD_JPY", 47941, price=160.199, sl=158.569,
                                    tp=160.971, tag="v2:rsi:long:202606120100"))
    assert pos["ftmo_symbol"] == "USDJPY.sim"
    assert pos["side"] == "buy"
    assert pos["lots"] == 0.48  # 47941 / 100_000, rounded
    assert pos["entry"] == 160.199
    assert pos["stop"] == 158.569
    assert pos["target"] == 160.971
    assert pos["opened"] == "2026-06-12"
    assert pos["source"] == "v2:rsi:long:202606120100"


def test_short_trade_is_sell_and_untagged_is_manual():
    pos = _trade_to_position(_trade("USD_SGD", -49839, price=1.28045, sl=1.29325))
    assert pos["side"] == "sell"
    assert pos["lots"] == 0.5
    assert pos["source"] == "manual"          # no clientExtensions tag
    assert "target" not in pos                # no takeProfit on this trade


def test_zero_units_or_missing_instrument_dropped():
    assert _trade_to_position(_trade("EUR_USD", 0)) is None
    assert _trade_to_position({"currentUnits": "100"}) is None


def test_only_untagged_excludes_bot_trades():
    trades = [
        _trade("CAD_JPY", 85330, price=114.5, tag=None),                 # manual
        _trade("EUR_GBP", 41239, price=0.8634, tag="v2:stoch:long:..."),  # bot
    ]
    both = _trades_to_positions(trades, only_untagged=False)
    assert {p["ftmo_symbol"] for p in both} == {"CADJPY.sim", "EURGBP.sim"}

    manual_only = _trades_to_positions(trades, only_untagged=True)
    assert {p["ftmo_symbol"] for p in manual_only} == {"CADJPY.sim"}


def test_multiple_same_symbol_trades_aggregate_lots():
    trades = [
        _trade("EUR_USD", 50000, price=1.16),
        _trade("EUR_USD", 30000, price=1.17),
    ]
    out = _trades_to_positions(trades, only_untagged=False)
    assert len(out) == 1
    assert out[0]["lots"] == 0.8          # (50000 + 30000) / 100_000
    assert out[0]["multi_trade"] is True


def test_output_sorted_by_symbol():
    trades = [_trade("USD_JPY", 100, price=1), _trade("AUD_USD", 100, price=1)]
    out = _trades_to_positions(trades, only_untagged=False)
    assert [p["ftmo_symbol"] for p in out] == ["AUDUSD.sim", "USDJPY.sim"]


def test_risk_usd_populated_for_configured_instrument():
    # EUR/USD is in the envelope config (pip_size 0.0001, $10/pip/lot).
    # 0.41 lots, ~117.7 pip stop -> non-trivial positive risk, filled at sync
    # time (not left for the back-heal).
    trades = [_trade("EUR_USD", -41000, price=1.15727, sl=1.16904)]
    out = _trades_to_positions(trades, only_untagged=False)
    assert out[0]["risk_usd"] > 0


def test_risk_usd_absent_without_stop():
    # No stop -> can't compute risk; field stays absent rather than wrong.
    trades = [_trade("EUR_USD", -41000, price=1.15727)]
    out = _trades_to_positions(trades, only_untagged=False)
    assert "risk_usd" not in out[0]
