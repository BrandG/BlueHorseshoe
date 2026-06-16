"""Tests for the positions.json data-sanity guard (bud.positions.validate_positions).

These cover the three fat-finger classes seen in real hand-edits of the FTMO
book: an impossible entry price, a lot size carried over from another account,
and a stop/target on the wrong side of entry for the position's direction.
"""
from bud.positions import validate_positions


def _buy(sym="EURUSD.sim", entry=1.1000, stop=1.0950, target=1.1100, lots=0.04):
    return {"ftmo_symbol": sym, "side": "buy", "entry": entry,
            "stop": stop, "target": target, "lots": lots}


def _sell(sym="EURUSD.sim", entry=1.1000, stop=1.1050, target=1.0900, lots=0.04):
    return {"ftmo_symbol": sym, "side": "sell", "entry": entry,
            "stop": stop, "target": target, "lots": lots}


def test_clean_book_has_no_warnings():
    book = [_buy(sym="EURUSD.sim"), _sell(sym="GBPUSD.sim"), _buy(sym="USDCHF.sim", entry=0.79, stop=0.785, target=0.80)]
    prices = {"EURUSD.sim": 1.1001, "GBPUSD.sim": 1.1000, "USDCHF.sim": 0.7905}
    assert validate_positions(book, price_lookup=prices) == []


def test_entry_far_off_market_is_flagged():
    # USDCHF entry typed as 1.79501 but market is ~0.794 (the real +1.0 typo).
    book = [_buy(sym="USDCHF.sim", entry=1.79501, stop=1.7917, target=1.80017)]
    warnings = validate_positions(book, price_lookup={"USDCHF.sim": 0.7944})
    assert any("off the current market" in w for w in warnings)


def test_entry_within_tolerance_not_flagged():
    # A normal drawdown (entry a few % above market) must NOT trip the typo check.
    book = [_buy(sym="EURUSD.sim", entry=1.1000, stop=1.0900, target=1.1200)]
    assert validate_positions(book, price_lookup={"EURUSD.sim": 1.0950}) == []


def test_buy_with_stop_above_entry_is_flagged():
    book = [{"ftmo_symbol": "EURUSD.sim", "side": "buy",
             "entry": 1.1000, "stop": 1.1050, "target": 1.1100, "lots": 0.04}]
    warnings = validate_positions(book)
    assert any("side=buy but stop" in w for w in warnings)


def test_sell_with_buy_geometry_is_flagged():
    # The real USDSGD mistake: side=sell but stop below + target above entry.
    book = [{"ftmo_symbol": "USDSGD.sim", "side": "sell",
             "entry": 1.28312, "stop": 1.27934, "target": 1.28742, "lots": 0.04}]
    warnings = validate_positions(book)
    assert any("side=sell but stop" in w for w in warnings)
    assert any("side=sell but target" in w for w in warnings)


def test_lot_outlier_vs_book_median_is_flagged():
    # Four 0.04 lots + one 0.48 (leftover demo size) -> the 0.48 is flagged.
    book = [_buy(sym="A.sim"), _buy(sym="B.sim"), _buy(sym="C.sim"),
            _buy(sym="D.sim"), _buy(sym="USDJPY.sim", entry=160.0, stop=158.0, target=162.0, lots=0.48)]
    warnings = validate_positions(book)
    assert any("USDJPY.sim" in w and "book median" in w for w in warnings)


def test_uniform_lots_no_outlier():
    book = [_buy(sym="A.sim"), _buy(sym="B.sim"), _buy(sym="C.sim")]
    assert not any("book median" in w for w in validate_positions(book))


def test_missing_price_lookup_skips_market_check_only():
    # No prices -> entry-vs-market is skipped, but geometry/lot checks still run.
    book = [{"ftmo_symbol": "USDSGD.sim", "side": "sell",
             "entry": 1.28312, "stop": 1.27934, "target": 1.28742, "lots": 0.04}]
    warnings = validate_positions(book)  # no price_lookup
    assert warnings  # geometry issue still caught
    assert not any("off the current market" in w for w in warnings)


def test_non_positive_and_bad_side_fields_flagged():
    book = [{"ftmo_symbol": "X.sim", "side": "long", "entry": 0, "stop": -1, "lots": 0}]
    warnings = validate_positions(book)
    assert any("not 'buy' or 'sell'" in w for w in warnings)
    assert any("entry" in w and "non-positive" in w for w in warnings)
    assert any("stop" in w and "non-positive" in w for w in warnings)
    assert any("lots" in w and "non-positive" in w for w in warnings)
