"""Tests for IBKR client — all mocked, no live gateway needed."""
import math
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import pytest

from bluehorseshoe.data.ibkr_client import (
    IBKRClient,
    IBKRConfig,
    QuoteData,
    _modify_rejection,
    _safe_float,
    _safe_int,
)


# ── Safe conversion helpers ──────────────────────────────────────────

class TestSafeConversions:
    def test_safe_float_normal(self):
        assert _safe_float(42.5) == 42.5

    def test_safe_float_int(self):
        assert _safe_float(10) == 10.0

    def test_safe_float_none(self):
        assert _safe_float(None) is None

    def test_safe_float_nan(self):
        assert _safe_float(float("nan")) is None

    def test_safe_float_string(self):
        assert _safe_float("bad") is None

    def test_safe_int_normal(self):
        assert _safe_int(100) == 100

    def test_safe_int_float(self):
        assert _safe_int(100.7) == 100

    def test_safe_int_none(self):
        assert _safe_int(None) is None

    def test_safe_int_nan(self):
        assert _safe_int(float("nan")) is None

    def test_safe_int_string(self):
        assert _safe_int("bad") is None


# ── IBKRConfig defaults ──────────────────────────────────────────────

class TestIBKRConfig:
    def test_defaults(self):
        cfg = IBKRConfig()
        assert cfg.host == "ib-gateway"
        assert cfg.port == 4004
        assert cfg.client_id == 1
        assert cfg.timeout == 10.0
        assert cfg.read_only is True

    def test_custom_values(self):
        cfg = IBKRConfig(host="localhost", port=4001, client_id=5, timeout=30.0, read_only=False)
        assert cfg.host == "localhost"
        assert cfg.port == 4001
        assert cfg.client_id == 5
        assert cfg.timeout == 30.0
        assert cfg.read_only is False


# ── IBKRClient connection behaviour ─────────────────────────────────

class TestIBKRClientConnection:
    def test_not_connected_by_default(self):
        client = IBKRClient()
        assert client.is_connected() is False

    def test_close_when_not_connected(self):
        client = IBKRClient()
        # Should not raise
        client.close()
        assert client.is_connected() is False

    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_connection_refused_returns_error(self, mock_ib_async):
        """When gateway is down, get_quote returns QuoteData with error."""
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = False
        mock_ib.connect.side_effect = ConnectionRefusedError("Connection refused")
        mock_ib_async.IB.return_value = mock_ib

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            quote = client.get_quote("AAPL")
            assert quote.error is not None
            assert "Cannot connect" in quote.error

    def test_import_error_returns_error(self):
        """When ib_async is not installed, get_quote returns error."""
        with patch.dict("sys.modules", {"ib_async": None}):
            client = IBKRClient()
            client._ib = None
            quote = client.get_quote("AAPL")
            assert quote.error is not None


# ── IBKRClient with fully mocked IB ─────────────────────────────────

class TestIBKRClientWithMockedIB:
    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_get_quote_success(self, mock_ib_async):
        """Full success path with mocked IB connection."""
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib_async.IB.return_value = mock_ib

        # Mock contract and ticker
        mock_contract = MagicMock()
        mock_contract.symbol = "AAPL"
        mock_ib_async.Stock.return_value = mock_contract

        mock_ticker = MagicMock()
        mock_ticker.bid = 150.10
        mock_ticker.ask = 150.20
        mock_ticker.last = 150.15
        mock_ticker.volume = 1000000
        mock_ticker.high = 151.00
        mock_ticker.low = 149.50
        mock_ticker.open = 149.80
        mock_ticker.close = 150.00
        mock_ib.reqMktData.return_value = mock_ticker

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            # Pre-set connection to skip connect()
            client._ib = mock_ib

            quote = client.get_quote("AAPL")

            assert quote.error is None
            assert quote.symbol == "AAPL"
            assert quote.bid == 150.10
            assert quote.ask == 150.20
            assert quote.last == 150.15
            assert quote.volume == 1000000
            assert quote.high == 151.00
            assert quote.low == 149.50
            assert quote.open == 149.80
            assert quote.close == 150.00
            assert quote.timestamp is not None

    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_get_quote_nan_values(self, mock_ib_async):
        """NaN values from IB are converted to None."""
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib_async.IB.return_value = mock_ib

        mock_contract = MagicMock()
        mock_contract.symbol = "AAPL"
        mock_ib_async.Stock.return_value = mock_contract

        mock_ticker = MagicMock()
        mock_ticker.bid = float("nan")
        mock_ticker.ask = float("nan")
        mock_ticker.last = 150.15
        mock_ticker.volume = float("nan")
        mock_ticker.high = float("nan")
        mock_ticker.low = float("nan")
        mock_ticker.open = float("nan")
        mock_ticker.close = float("nan")
        mock_ib.reqMktData.return_value = mock_ticker

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            client._ib = mock_ib

            quote = client.get_quote("AAPL")

            assert quote.error is None
            assert quote.bid is None
            assert quote.ask is None
            assert quote.last == 150.15
            assert quote.volume is None

    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_get_quotes_multiple(self, mock_ib_async):
        """Batch quote fetch for multiple symbols."""
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib_async.IB.return_value = mock_ib

        contracts = []
        tickers = []
        for sym, price in [("AAPL", 150.0), ("MSFT", 380.0)]:
            c = MagicMock()
            c.symbol = sym
            contracts.append(c)

            t = MagicMock()
            t.bid = price - 0.10
            t.ask = price + 0.10
            t.last = price
            t.volume = 500000
            t.high = price + 1
            t.low = price - 1
            t.open = price - 0.5
            t.close = price - 0.2
            tickers.append(t)

        mock_ib_async.Stock.side_effect = contracts
        mock_ib.reqMktData.side_effect = tickers

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            client._ib = mock_ib

            quotes = client.get_quotes(["AAPL", "MSFT"])

            assert len(quotes) == 2
            assert quotes[0].symbol == "AAPL"
            assert quotes[0].last == 150.0
            assert quotes[1].symbol == "MSFT"
            assert quotes[1].last == 380.0

    def test_get_quotes_connection_error(self):
        """When connection fails, all symbols get error."""
        with patch.dict("sys.modules", {"ib_async": None}):
            client = IBKRClient()
            client._ib = None
            quotes = client.get_quotes(["AAPL", "MSFT"])
            assert len(quotes) == 2
            assert all(q.error is not None for q in quotes)

    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_close_disconnects(self, mock_ib_async):
        """Close disconnects from IB Gateway."""
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib_async.IB.return_value = mock_ib

        client = IBKRClient()
        client._ib = mock_ib
        client.close()

        mock_ib.disconnect.assert_called_once()
        assert client._ib is None


class TestModifyOrderStop:
    """IBKRClient.modify_order_stop uses placeOrder-with-same-orderId
    semantics. The order is found across clients via reqAllOpenOrders."""

    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_modifies_and_resubmits(self, mock_ib_async):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True

        trade = MagicMock()
        trade.contract.symbol = "AAPL"
        trade.order.orderId = 42
        trade.order.orderType = "STP"
        trade.order.auxPrice = 147.0
        mock_ib.reqAllOpenOrders.return_value = [trade]
        mock_ib_async.IB.return_value = mock_ib

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            client._ib = mock_ib
            result = client.modify_order_stop(42, 150.0)

        assert result["status"] == "submitted"
        assert result["order_id"] == 42
        assert result["error"] is None
        assert trade.order.auxPrice == 150.0
        mock_ib.placeOrder.assert_called_once_with(trade.contract, trade.order)

    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_refuses_non_stp_order_type(self, mock_ib_async):
        """Defensive: if a wrong order_id ever gets routed here (e.g., a
        bug upstream that swaps STP and LMT), setting auxPrice on a LMT
        would silently corrupt it. Refuse loudly."""
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True

        trade = MagicMock()
        trade.contract.symbol = "AAPL"
        trade.order.orderId = 42
        trade.order.orderType = "LMT"
        mock_ib.reqAllOpenOrders.return_value = [trade]
        mock_ib_async.IB.return_value = mock_ib

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            client._ib = mock_ib
            result = client.modify_order_stop(42, 150.0)

        assert result["status"] == "error"
        assert "'LMT'" in result["error"]
        assert "not STP" in result["error"]
        mock_ib.placeOrder.assert_not_called()

    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_order_not_found(self, mock_ib_async):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib.reqAllOpenOrders.return_value = []
        mock_ib_async.IB.return_value = mock_ib

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            client._ib = mock_ib
            result = client.modify_order_stop(99, 100.0)

        assert result["status"] == "error"
        assert "not found" in result["error"]
        mock_ib.placeOrder.assert_not_called()

    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_broker_exception_propagates_as_error(self, mock_ib_async):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        trade = MagicMock()
        trade.order.orderId = 42
        trade.order.orderType = "STP"
        mock_ib.reqAllOpenOrders.return_value = [trade]
        mock_ib.placeOrder.side_effect = RuntimeError("rejected by IBKR")
        mock_ib_async.IB.return_value = mock_ib

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            client._ib = mock_ib
            result = client.modify_order_stop(42, 150.0)

        assert result["status"] == "error"
        assert "rejected by IBKR" in result["error"]


class TestCancelOrder:
    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_cancels(self, mock_ib_async):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        trade = MagicMock()
        trade.contract.symbol = "AAPL"
        trade.order.orderId = 42
        mock_ib.reqAllOpenOrders.return_value = [trade]
        mock_ib_async.IB.return_value = mock_ib

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            client._ib = mock_ib
            result = client.cancel_order(42)

        assert result["status"] == "cancelling"
        assert result["error"] is None
        mock_ib.cancelOrder.assert_called_once_with(trade.order)

    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_cancel_order_not_found(self, mock_ib_async):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib.reqAllOpenOrders.return_value = []
        mock_ib_async.IB.return_value = mock_ib

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            client._ib = mock_ib
            result = client.cancel_order(99)

        assert result["status"] == "error"
        assert "not found" in result["error"]
        mock_ib.cancelOrder.assert_not_called()


class TestPlaceMarketOrder:
    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_market_sell(self, mock_ib_async):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        # placeOrder returns Trade with orderId set
        new_trade = MagicMock()
        new_trade.order.orderId = 101
        mock_ib.placeOrder.return_value = new_trade
        mock_ib_async.Stock.return_value = MagicMock()
        mock_ib_async.MarketOrder.return_value = MagicMock()
        mock_ib_async.IB.return_value = mock_ib

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            client._ib = mock_ib
            result = client.place_market_order("AAPL", "SELL", 10)

        assert result["status"] == "submitted"
        assert result["order_id"] == 101
        mock_ib_async.MarketOrder.assert_called_with("SELL", 10)
        mock_ib.placeOrder.assert_called_once()


class TestGetOpenTrades:
    """Regression: monitor uses a different client_id than PaperTrader, so
    openTrades() (this-client only) misses the brackets we actually placed.
    get_open_trades must call reqAllOpenOrders() for cross-client visibility."""

    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_uses_reqAllOpenOrders_for_cross_client_visibility(self, mock_ib_async):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        other_client_trade = MagicMock()
        other_client_trade.contract.symbol = "AAPL"
        mock_ib.reqAllOpenOrders.return_value = [other_client_trade]
        # Local cache (would be empty for a fresh monitor connection)
        mock_ib.openTrades.return_value = []
        mock_ib_async.IB.return_value = mock_ib

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            client._ib = mock_ib

            result = client.get_open_trades()

        assert mock_ib.reqAllOpenOrders.called, \
            "expected reqAllOpenOrders for cross-client visibility"
        assert not mock_ib.openTrades.called, \
            "must not use openTrades() — that's client-scoped"
        assert result == [other_client_trade]

    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_returns_empty_on_exception(self, mock_ib_async):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib.reqAllOpenOrders.side_effect = RuntimeError("connection dropped")
        mock_ib_async.IB.return_value = mock_ib

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            client._ib = mock_ib

            result = client.get_open_trades()

        assert result == []


class TestPlaceBracketOrder:
    """Regression coverage: ib_async moved bracketOrder() from module-level
    to an instance method. Calling the old module-level form throws
    AttributeError silently inside PaperTrader, which presents as every
    submission returning status='error' with no orders placed."""

    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_calls_bracket_helper_on_ib_instance(self, mock_ib_async):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True

        # Three Order mocks make up the bracket; placeOrder echoes each back
        # with a unique orderId so the caller can record them.
        parent, take_profit, stop_loss = MagicMock(), MagicMock(), MagicMock()
        mock_ib.bracketOrder.return_value = [parent, take_profit, stop_loss]

        trades = []
        for oid in (101, 102, 103):
            t = MagicMock()
            t.order.orderId = oid
            trades.append(t)
        mock_ib.placeOrder.side_effect = trades

        mock_ib_async.Stock.return_value = MagicMock()
        mock_ib_async.IB.return_value = mock_ib

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            client._ib = mock_ib

            result = client.place_bracket_order(
                symbol="AAPL", quantity=10, limit_price=150.0,
                take_profit_price=155.0, stop_loss_price=147.0,
            )

        # The fix: helper is called on the IB instance, not the module.
        assert mock_ib.bracketOrder.called, "expected self._ib.bracketOrder() to be invoked"
        assert not hasattr(mock_ib_async, "bracketOrder") or \
            not mock_ib_async.bracketOrder.called, \
            "must not call the obsolete module-level ib_async.bracketOrder()"

        # Call-shape regression: kwargs must reach the helper unchanged.
        kwargs = mock_ib.bracketOrder.call_args.kwargs
        assert kwargs == {
            "action": "BUY", "quantity": 10, "limitPrice": 150.0,
            "takeProfitPrice": 155.0, "stopLossPrice": 147.0,
        }
        # All three legs were submitted and the order IDs collected.
        assert mock_ib.placeOrder.call_count == 3
        assert result["status"] == "submitted"
        assert result["order_ids"] == [101, 102, 103]
        assert result["error"] is None
        # Entry must be DAY (unfilled limits die at EOD; algorithm re-picks
        # the symbol the next day if the setup still holds). TP and SL stay
        # GTC so they ride the position once activated.
        assert parent.tif == "DAY"
        assert take_profit.tif == "GTC"
        assert stop_loss.tif == "GTC"


class TestEntryStopBracketTrailing:
    """range_support: place_entry_stop_bracket with trail_amount>0 attaches a native TRAIL
    child (trails at trail_amount, initial trigger pinned to stop via trailStopPrice)."""

    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_trail_child_built_when_trail_amount_positive(self, mock_ib_async):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        parent_t, stop_t = MagicMock(), MagicMock()
        parent_t.order.orderId = 201
        stop_t.order.orderId = 202
        mock_ib.placeOrder.side_effect = [parent_t, stop_t]
        mock_ib_async.IB.return_value = mock_ib

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            client._ib = mock_ib
            result = client.place_entry_stop_bracket(
                symbol="AAPL", quantity=10, limit_price=100.0,
                stop_loss_price=97.0, trail_amount=6.0,
            )

        # The child exit is a native TRAIL: 2xATR trailing distance, initial trigger at the 1xATR stop.
        mock_ib_async.Order.assert_called_once_with(
            action="SELL", totalQuantity=10, orderType="TRAIL",
            auxPrice=6.0, trailStopPrice=97.0,
        )
        mock_ib_async.StopOrder.assert_not_called()   # no fixed stop when trailing
        assert result["status"] == "submitted"
        assert result["order_ids"] == [201, 202]

    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_fixed_stop_when_no_trail(self, mock_ib_async):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        parent_t, stop_t = MagicMock(), MagicMock()
        parent_t.order.orderId = 301
        stop_t.order.orderId = 302
        mock_ib.placeOrder.side_effect = [parent_t, stop_t]
        mock_ib_async.IB.return_value = mock_ib

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            client._ib = mock_ib
            result = client.place_entry_stop_bracket(
                symbol="AAPL", quantity=10, limit_price=100.0, stop_loss_price=97.0,
            )

        mock_ib_async.StopOrder.assert_called_once_with("SELL", 10, 97.0)
        mock_ib_async.Order.assert_not_called()
        assert result["order_ids"] == [301, 302]


class TestOcaTrailLeg:
    """place_oca_exits builds a native TRAIL leg from order_type='TRAIL' + trail_amount."""

    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_trail_leg(self, mock_ib_async):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        placed = MagicMock()
        placed.order.orderId = 501
        mock_ib.placeOrder.return_value = placed
        mock_ib_async.IB.return_value = mock_ib

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            client._ib = mock_ib
            result = client.place_oca_exits(
                "AAPL", "grp1",
                [{"leg": "STOP_B", "order_type": "TRAIL", "quantity": 10,
                  "price": 97.0, "trail_amount": 6.0}],
            )

        mock_ib_async.Order.assert_called_once_with(
            action="SELL", totalQuantity=10, orderType="TRAIL",
            auxPrice=6.0, trailStopPrice=97.0,
        )
        assert result["status"] == "submitted"
        assert result["order_ids"] == {"STOP_B": 501}


class TestModifyRejection:
    """_modify_rejection turns an async broker refusal (e.g. Error 103 Duplicate order id) into a
    real failure, so modify_order_stop can no longer report phantom 'submitted'."""

    def test_errorcode_in_log_is_rejection(self):
        trade = SimpleNamespace(
            orderStatus=SimpleNamespace(status="Cancelled"),
            log=[SimpleNamespace(errorCode=103,
                                 message="Error 103, reqId 1057: Duplicate order id")],
        )
        msg = _modify_rejection(trade)
        assert msg is not None and "Duplicate order id" in msg

    def test_cancelled_status_is_rejection(self):
        trade = SimpleNamespace(orderStatus=SimpleNamespace(status="Cancelled"), log=[])
        assert _modify_rejection(trade) == "order Cancelled"

    def test_healthy_submit_is_not_rejection(self):
        trade = SimpleNamespace(
            orderStatus=SimpleNamespace(status="PreSubmitted"),
            log=[SimpleNamespace(errorCode=0, message="")],
        )
        assert _modify_rejection(trade) is None

    @patch("bluehorseshoe.data.ibkr_client.ib_async", create=True)
    def test_modify_order_stop_reports_rejection(self, mock_ib_async):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        target = MagicMock()
        target.order.orderId = 1057
        target.order.orderType = "STP"
        mock_ib.reqAllOpenOrders.return_value = [target]
        # placeOrder returns a trade that the broker then cancels with Error 103.
        mtrade = SimpleNamespace(
            orderStatus=SimpleNamespace(status="Cancelled"),
            log=[SimpleNamespace(errorCode=103,
                                 message="Error 103, reqId 1057: Duplicate order id")],
        )
        mock_ib.placeOrder.return_value = mtrade
        mock_ib_async.IB.return_value = mock_ib

        with patch.dict("sys.modules", {"ib_async": mock_ib_async}):
            client = IBKRClient()
            client._ib = mock_ib
            result = client.modify_order_stop(1057, 26.95)

        assert result["status"] == "error"
        assert "Duplicate order id" in result["error"]
