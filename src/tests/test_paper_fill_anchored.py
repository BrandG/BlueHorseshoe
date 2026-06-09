"""Tests for fill-anchored paper execution and arcade fill calculator."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bluehorseshoe.reporting.html_reporter import HTMLReporter
from bluehorseshoe.trading.paper_trader import PaperTradeConfig, PaperTrader


def _candidate(symbol="AAPL", close=100.0, stop=97.0, target=105.88, t1=102.0):
    return {
        "symbol": symbol,
        "strategy": "DeepOS",
        "close": close,
        "stop_loss": stop,
        "target": target,
        "t1_target": t1,
        "score": 50.0,
        "ml_prob": 0.65,
    }


def _trade(status="Filled", filled=10, avg=98.25):
    return SimpleNamespace(
        orderStatus=SimpleNamespace(
            status=status,
            filled=filled,
            avgFillPrice=avg,
        )
    )


def _db():
    paper = MagicMock()
    paper.find_one.return_value = None
    staged = MagicMock()
    orders = MagicMock()
    db = MagicMock()
    db.__getitem__.side_effect = {
        "paper_trades": paper,
        "staged_orders": staged,
        "trade_orders": orders,
    }.__getitem__
    return db, paper, staged, orders


def _client():
    client = MagicMock()
    client.get_account_summary.return_value = {"account_id": "DU123"}
    client.get_positions.return_value = []
    client.get_open_trades.return_value = []
    client.place_bracket_order.return_value = {
        "order_ids": [1, 2, 3],
        "status": "submitted",
        "error": None,
    }
    client.place_entry_only.return_value = {
        "order_id": 10,
        "trade": _trade(),
        "status": "submitted",
        "error": None,
    }
    client.place_oca_exits.return_value = {
        "order_ids": {"STOP": 20, "T1": 21, "T2": 22},
        "status": "submitted",
        "error": None,
    }
    return client


def _trader(tmp_path, client=None, db=None, max_positions=1):
    return PaperTrader(
        ibkr_client=client or _client(),
        config=PaperTradeConfig(
            total_investment=1000.0,
            max_positions=max_positions,
            logs_path=str(tmp_path),
            fill_anchored_execution=True,
            fractional_shares=False,
        ),
        database=db,
    )


def test_stage_orders_writes_offsets_without_broker_orders(tmp_path):
    db, paper, staged, _ = _db()
    client = _client()
    trader = _trader(tmp_path, client=client, db=db)

    results = trader.stage_orders([_candidate()], "2026-06-08")

    assert results[0].status == "staged"
    client.place_bracket_order.assert_not_called()
    client.place_entry_only.assert_not_called()
    doc = staged.update_one.call_args.args[1]["$set"]
    assert doc["rank"] == 1
    assert doc["entry_model"] == pytest.approx(100.0)
    assert doc["R"] == pytest.approx(3.0)
    assert doc["tp_offset"] == pytest.approx(5.88)
    assert doc["t1_offset"] == pytest.approx(2.0)
    assert doc["total_qty"] == 10.0
    assert doc["t1_qty"] == 5.0
    assert doc["t2_qty"] == 5.0
    paper.update_one.assert_not_called()


def test_execute_open_anchors_children_to_actual_fill_with_paired_oca_stops(tmp_path):
    db, _, staged, orders = _db()
    doc = {
        "_id": "stage1",
        "date": "2026-06-08",
        "symbol": "AAPL",
        "strategy": "DeepOS",
        "total_qty": 10,
        "t1_qty": 5,
        "t2_qty": 5,
        "entry_model": 100.0,
        "R": 3.0,
        "tp_offset": 5.88,
        "t1_offset": 2.0,
        "status": "staged",
        "idea_id": "idea_2026-06-08_AAPL_deepos",
    }
    staged.find.return_value = [doc]
    client = _client()
    client.place_entry_only.return_value["trade"] = _trade(avg=98.25)
    client.place_oca_exits.side_effect = [
        {
            "order_ids": {"T1": 21, "STOP_A": 22},
            "status": "submitted",
            "error": None,
        },
        {
            "order_ids": {"T2": 23, "STOP_B": 24},
            "status": "submitted",
            "error": None,
        },
    ]
    trader = _trader(tmp_path, client=client, db=db)

    results = trader.execute_open("2026-06-08", timeout_s=0.01, poll_interval_s=0.01)

    assert results[0].status == "submitted"
    client.place_entry_only.assert_called_once_with("AAPL", 10, 102.0, tif="DAY")
    assert client.place_oca_exits.call_count == 2
    first_call, second_call = client.place_oca_exits.call_args_list
    assert first_call.args[1] != second_call.args[1]
    assert first_call.args[2] == [
        {"leg": "T1", "order_type": "LMT", "quantity": 5, "price": 100.25},
        {"leg": "STOP_A", "order_type": "STP", "quantity": 5, "price": 95.25},
    ]
    assert second_call.args[2] == [
        {"leg": "T2", "order_type": "LMT", "quantity": 5, "price": 104.13},
        {"leg": "STOP_B", "order_type": "STP", "quantity": 5, "price": 95.25},
    ]
    all_legs = first_call.args[2] + second_call.args[2]
    stop_qty = sum(leg["quantity"] for leg in all_legs if leg["order_type"] == "STP")
    assert stop_qty == results[0].quantity
    assert all(len(call.args[2]) == 2 for call in client.place_oca_exits.call_args_list)
    assert results[0].t1_order_ids == [10, 21, 22]
    assert results[0].t2_order_ids == [10, 23, 24]
    assert orders.update_one.call_count == 2


def test_execute_open_partial_fill_cancels_remainder_and_scales_children(tmp_path):
    db, _, staged, _ = _db()
    staged.find.return_value = [{
        "_id": "stage1",
        "date": "2026-06-08",
        "symbol": "AAPL",
        "strategy": "DeepOS",
        "total_qty": 10,
        "t1_qty": 5,
        "t2_qty": 5,
        "entry_model": 100.0,
        "R": 3.0,
        "tp_offset": 5.88,
        "t1_offset": 2.0,
        "status": "staged",
    }]
    client = _client()
    client.place_entry_only.return_value["trade"] = _trade(status="Submitted", filled=4, avg=98.25)
    trader = _trader(tmp_path, client=client, db=db)

    results = trader.execute_open("2026-06-08", timeout_s=0.01, poll_interval_s=0.01)

    assert results[0].status == "partial"
    client.cancel_order.assert_called_once_with(10)
    assert client.place_oca_exits.call_count == 2
    placed_legs = [
        leg
        for call in client.place_oca_exits.call_args_list
        for leg in call.args[2]
    ]
    assert [leg["quantity"] for leg in placed_legs] == [2, 2, 2, 2]


def test_execute_open_caps_new_positions_by_rank(tmp_path):
    db, _, staged, _ = _db()
    staged.find.return_value = [
        {
            "_id": f"stage{rank}",
            "date": "2026-06-08",
            "symbol": symbol,
            "strategy": "DeepOS",
            "total_qty": 10,
            "t1_qty": 5,
            "t2_qty": 5,
            "entry_model": 100.0,
            "R": 3.0,
            "tp_offset": 5.88,
            "t1_offset": 2.0,
            "status": "staged",
            "rank": rank,
        }
        for rank, symbol in [(3, "C"), (1, "A"), (4, "D"), (2, "B")]
    ]
    client = _client()
    trader = _trader(tmp_path, client=client, db=db, max_positions=3)
    trader._get_occupied_symbols = MagicMock(return_value={"OLD"})  # pylint: disable=protected-access

    results = trader.execute_open("2026-06-08", timeout_s=0.01, poll_interval_s=0.01)

    assert [call.args[0] for call in client.place_entry_only.call_args_list] == ["A", "B"]
    assert [(r.symbol, r.status, r.error) for r in results] == [
        ("A", "submitted", None),
        ("B", "submitted", None),
        ("C", "skipped", "position cap reached"),
        ("D", "skipped", "position cap reached"),
    ]
    skipped_updates = [
        call.args[1]["$set"]
        for call in staged.update_one.call_args_list
        if call.args[1]["$set"].get("error") == "position cap reached"
    ]
    assert len(skipped_updates) == 2


def test_execute_open_full_quantity_with_lagging_status_is_submitted(tmp_path):
    db, _, staged, _ = _db()
    staged.find.return_value = [{
        "_id": "stage1",
        "date": "2026-06-08",
        "symbol": "AAPL",
        "strategy": "DeepOS",
        "total_qty": 10,
        "t1_qty": 5,
        "t2_qty": 5,
        "entry_model": 100.0,
        "R": 3.0,
        "tp_offset": 5.88,
        "t1_offset": 2.0,
        "status": "staged",
    }]
    client = _client()
    client.place_entry_only.return_value["trade"] = _trade(status="Submitted", filled=10, avg=98.25)
    trader = _trader(tmp_path, client=client, db=db)

    results = trader.execute_open("2026-06-08", timeout_s=0.01, poll_interval_s=0.01)

    assert results[0].status == "submitted"
    client.cancel_order.assert_not_called()


def test_execute_open_no_fill_expires_and_places_no_exits(tmp_path):
    db, _, staged, _ = _db()
    staged.find.return_value = [{
        "_id": "stage1",
        "date": "2026-06-08",
        "symbol": "AAPL",
        "strategy": "DeepOS",
        "total_qty": 10,
        "t1_qty": 5,
        "t2_qty": 5,
        "entry_model": 100.0,
        "R": 3.0,
        "tp_offset": 5.88,
        "t1_offset": 2.0,
        "status": "staged",
    }]
    client = _client()
    client.place_entry_only.return_value["trade"] = _trade(status="Submitted", filled=0, avg=0)
    trader = _trader(tmp_path, client=client, db=db)

    results = trader.execute_open("2026-06-08", timeout_s=0.01, poll_interval_s=0.01)

    assert results[0].status == "skipped"
    assert results[0].error == "no fill before timeout"
    client.cancel_order.assert_called_once_with(10)
    client.place_oca_exits.assert_not_called()


def test_flag_off_legacy_execute_still_places_bracket(tmp_path):
    client = _client()
    trader = PaperTrader(
        ibkr_client=client,
        config=PaperTradeConfig(
            total_investment=1000.0,
            max_positions=1,
            logs_path=str(tmp_path),
            fill_anchored_execution=False,
            fractional_shares=False,
        ),
        database=None,
    )

    results = trader.execute([_candidate()], "2026-06-08")

    assert results[0].status == "submitted"
    assert client.place_bracket_order.call_count == 2
    client.place_entry_only.assert_not_called()


def test_arcade_fill_calculator_hooks_and_offsets():
    html = HTMLReporter().generate_arcade_report(
        "2026-06-08",
        {"status": "BULL", "details": {}},
        [_candidate(close=100.0, stop=97.0, target=105.88, t1=102.0)],
    )

    assert '"risk_per_share": 3.0' in html
    assert '"target_offset": 5.879999999999995' in html or '"target_offset": 5.88' in html
    # daf3b56 moved the fill calculator into the row dropdown, switching from
    # setAttribute('data-r', ...) to an inline data-r="..." attribute (the value
    # is templated by JS at render time, so assert the static attribute hook).
    assert 'fill-calc-detail" data-r=' in html
    assert '" data-tpoff=' in html
    assert 'class="fill-input"' in html
    assert 'class="calc-stop"' in html
    assert 'class="calc-target"' in html
    assert "risk/sh $" in html


def test_arcade_inline_qty_sizing_hooks():
    """Header investment input + per-row conviction-weighted QTY column."""
    html = HTMLReporter().generate_arcade_report(
        "2026-06-08",
        {"status": "BULL", "details": {}},
        [
            _candidate(symbol="AAA", close=100.0, stop=97.0, target=105.88, t1=102.0),
            _candidate(symbol="BBB", close=50.0, stop=48.5, target=52.94, t1=51.0),
        ],
    )

    # Both candidates are embedded for the client-side allocator to size.
    assert '"symbol": "AAA"' in html
    assert '"symbol": "BBB"' in html
    # Investment input lives next to the regime badge.
    assert 'id="inlineInvest"' in html
    assert "onInlineInvestChange()" in html
    # QTY column: header + the per-row cell hook (selKey is templated at render time).
    assert "QTY x2" in html
    assert 'class="col-qty" data-selkey=' in html
    # Live recompute reuses the conviction-weighted allocator and persists the amount.
    assert "function recomputeInlineQtys()" in html
    assert "allocatePortfolio(" in html
    assert "bh_inline_invest" in html
    # Header input and the Portfolio modal share one investment amount.
    assert "function isPortfolioModalOpen()" in html
    assert "if (isPortfolioModalOpen()) updatePortfolio()" in html
