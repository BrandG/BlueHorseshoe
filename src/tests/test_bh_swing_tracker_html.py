"""Tests for bh_swing.trading.tracker_html — render produces valid HTML."""
from unittest.mock import MagicMock

import pytest

from bh_swing.trading import tracker_html


def _mock_trade(symbol="AAPL", action="BUY", qty=10, otype="LMT",
                lmt=150.0, stp=0.0, status="Submitted", order_id=42, parent_id=0):
    t = MagicMock()
    t.contract.symbol = symbol
    t.order.action = action
    t.order.totalQuantity = qty
    t.order.orderType = otype
    t.order.lmtPrice = lmt
    t.order.auxPrice = stp
    t.order.tif = "GTC"
    t.order.orderId = order_id
    t.order.parentId = parent_id
    t.orderStatus.status = status
    t.orderStatus.filled = 0
    return t


class TestRender:
    def test_writes_html_file(self, tmp_path):
        out = tmp_path / "tracker.html"
        path = tracker_html.render(
            account={"account_id": "DU1234", "net_liquidation": 10000.0,
                     "settled_cash": 8000.0, "available_funds": 9000.0,
                     "buying_power": 9000.0},
            positions=[],
            open_trades=[],
            recent_events=[],
            output_path=str(out),
        )
        assert path == str(out)
        content = out.read_text()
        assert "<!doctype html>" in content
        assert "BH Swing Tracker" in content
        assert "DU1234" in content
        assert "$10,000.00" in content

    def test_renders_positions(self, tmp_path):
        out = tmp_path / "tracker.html"
        tracker_html.render(
            account={},
            positions=[
                {"symbol": "AAPL", "position": 100, "avg_cost": 150.25,
                 "contract_type": "STK", "currency": "USD"},
                {"symbol": "FLAT", "position": 0, "avg_cost": 0,
                 "contract_type": "STK", "currency": "USD"},
            ],
            open_trades=[],
            recent_events=[],
            output_path=str(out),
        )
        content = out.read_text()
        assert "AAPL" in content
        assert "$150.25" in content
        # Flat positions should be filtered out
        assert "FLAT" not in content

    def test_renders_working_orders(self, tmp_path):
        out = tmp_path / "tracker.html"
        tracker_html.render(
            account={},
            positions=[],
            open_trades=[_mock_trade("AAPL", "BUY", 10, "LMT", lmt=150.0)],
            recent_events=[],
            output_path=str(out),
        )
        content = out.read_text()
        assert "AAPL" in content
        assert "BUY" in content
        assert "$150.00" in content

    def test_renders_journal_events(self, tmp_path):
        out = tmp_path / "tracker.html"
        tracker_html.render(
            account={},
            positions=[],
            open_trades=[],
            recent_events=[{
                "ts_utc": "2026-05-12T14:00:00+00:00",
                "event": "fill_detected",
                "symbol": "TSLA", "side": "buy",
                "quantity": "10", "price": "200.00", "note": "exec_time=...",
            }],
            output_path=str(out),
        )
        content = out.read_text()
        assert "fill_detected" in content
        assert "TSLA" in content
        assert "event-fill_detected" in content  # CSS class applied

    def test_empty_state_messages(self, tmp_path):
        out = tmp_path / "tracker.html"
        tracker_html.render(
            account={}, positions=[], open_trades=[], recent_events=[],
            output_path=str(out),
        )
        content = out.read_text()
        assert "No open positions" in content
        assert "No working orders" in content
        assert "No journal events" in content

    def test_html_escapes_user_content(self, tmp_path):
        """If broker ever returns a symbol with HTML-special chars, escape it."""
        out = tmp_path / "tracker.html"
        tracker_html.render(
            account={"account_id": "<script>x</script>"},
            positions=[],
            open_trades=[],
            recent_events=[],
            output_path=str(out),
        )
        content = out.read_text()
        assert "<script>x</script>" not in content
        assert "&lt;script&gt;" in content
