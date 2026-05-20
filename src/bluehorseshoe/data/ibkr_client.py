"""
IBKR Gateway client for real-time market data queries.

Uses ib_async (community fork of ib_insync) to connect to IB Gateway
and fetch bid/ask/last/volume snapshots. Data-only — no order placement.
"""
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class IBKRConfig:
    """Connection configuration for IB Gateway."""
    host: str = "ib-gateway"
    port: int = 4004
    client_id: int = 1
    timeout: float = 10.0
    read_only: bool = True


@dataclass
class QuoteData:
    """Snapshot quote data for a single symbol."""
    symbol: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    volume: Optional[int] = None
    high: Optional[float] = None
    low: Optional[float] = None
    open: Optional[float] = None
    close: Optional[float] = None
    timestamp: Optional[datetime] = None
    error: Optional[str] = None


def _safe_float(value) -> Optional[float]:
    """Convert IB value to float, returning None for NaN/None."""
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _safe_int(value) -> Optional[int]:
    """Convert IB value to int, returning None for NaN/None."""
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f):
            return None
        return int(f)
    except (ValueError, TypeError):
        return None


class IBKRClient:
    """
    Client for querying real-time market data from IB Gateway.

    Uses snapshot mode (no streaming subscription required) to fetch
    bid/ask/last/volume for individual symbols or batches.
    """

    def __init__(self, config: Optional[IBKRConfig] = None):
        self._config = config or IBKRConfig()
        self._ib = None  # Lazy-loaded ib_async.IB instance

    def _ensure_connected(self):
        """Connect to IB Gateway if not already connected."""
        if self._ib is not None and self._ib.isConnected():
            return

        try:
            import ib_async  # pylint: disable=import-outside-toplevel
        except ImportError as e:
            raise ImportError(
                "ib_async is not installed. Install it with: pip install ib_async"
            ) from e

        self._ib = ib_async.IB()
        try:
            self._ib.connect(
                host=self._config.host,
                port=self._config.port,
                clientId=self._config.client_id,
                timeout=self._config.timeout,
                readonly=self._config.read_only,
            )
            logger.info(
                "Connected to IB Gateway at %s:%s (client_id=%s)",
                self._config.host, self._config.port, self._config.client_id,
            )
        except ConnectionRefusedError as exc:
            self._ib = None
            raise ConnectionRefusedError(
                f"Cannot connect to IB Gateway at {self._config.host}:{self._config.port}. "
                "Is the ib-gateway container running? Start it with: "
                "cd docker && docker compose up -d ib-gateway"
            ) from exc
        except Exception:
            self._ib = None
            raise

    def is_connected(self) -> bool:
        """Check if currently connected to IB Gateway."""
        return self._ib is not None and self._ib.isConnected()

    def get_quote(self, symbol: str) -> QuoteData:
        """
        Get a snapshot quote for a single symbol.

        Args:
            symbol: Stock ticker symbol (e.g., "AAPL")

        Returns:
            QuoteData with bid/ask/last/volume or error message
        """
        try:
            self._ensure_connected()
        except (ConnectionRefusedError, ImportError) as e:
            return QuoteData(symbol=symbol, error=str(e))
        except Exception as e:
            return QuoteData(symbol=symbol, error=f"Connection failed: {e}")

        try:
            import ib_async  # pylint: disable=import-outside-toplevel
            contract = ib_async.Stock(symbol, "SMART", "USD")
            self._ib.qualifyContracts(contract)

            ticker = self._ib.reqMktData(contract, snapshot=True)
            # Wait for snapshot data to arrive
            self._ib.sleep(2)

            quote = QuoteData(
                symbol=symbol,
                bid=_safe_float(ticker.bid),
                ask=_safe_float(ticker.ask),
                last=_safe_float(ticker.last),
                volume=_safe_int(ticker.volume),
                high=_safe_float(ticker.high),
                low=_safe_float(ticker.low),
                open=_safe_float(ticker.open),
                close=_safe_float(ticker.close),
                timestamp=datetime.now(),
            )

            self._ib.cancelMktData(contract)
            return quote

        except Exception as e:
            logger.error("Error fetching quote for %s: %s", symbol, e)
            return QuoteData(symbol=symbol, error=str(e))

    def get_quotes(self, symbols: List[str]) -> List[QuoteData]:
        """
        Get snapshot quotes for multiple symbols.

        Args:
            symbols: List of stock ticker symbols

        Returns:
            List of QuoteData, one per symbol
        """
        try:
            self._ensure_connected()
        except (ConnectionRefusedError, ImportError) as e:
            return [QuoteData(symbol=s, error=str(e)) for s in symbols]
        except Exception as e:
            return [QuoteData(symbol=s, error=f"Connection failed: {e}") for s in symbols]

        try:
            import ib_async  # pylint: disable=import-outside-toplevel

            contracts = [ib_async.Stock(s, "SMART", "USD") for s in symbols]
            self._ib.qualifyContracts(*contracts)

            tickers = []
            for contract in contracts:
                ticker = self._ib.reqMktData(contract, snapshot=True)
                tickers.append((contract, ticker))

            # Wait for all snapshot data
            self._ib.sleep(2)

            results = []
            for contract, ticker in tickers:
                results.append(QuoteData(
                    symbol=contract.symbol,
                    bid=_safe_float(ticker.bid),
                    ask=_safe_float(ticker.ask),
                    last=_safe_float(ticker.last),
                    volume=_safe_int(ticker.volume),
                    high=_safe_float(ticker.high),
                    low=_safe_float(ticker.low),
                    open=_safe_float(ticker.open),
                    close=_safe_float(ticker.close),
                    timestamp=datetime.now(),
                ))
                self._ib.cancelMktData(contract)

            return results

        except Exception as e:
            logger.error("Error fetching quotes: %s", e)
            return [QuoteData(symbol=s, error=str(e)) for s in symbols]

    def place_bracket_order(
        self,
        symbol: str,
        quantity: int,
        limit_price: float,
        take_profit_price: float,
        stop_loss_price: float,
    ) -> dict:
        """
        Place a bracket order: limit entry + take-profit + stop-loss.

        All three legs use GTC (Good-Til-Cancelled) time-in-force.

        Args:
            symbol: Stock ticker symbol (e.g., "AAPL")
            quantity: Number of shares to buy
            limit_price: Limit price for the entry order
            take_profit_price: Limit price for the take-profit (sell) order
            stop_loss_price: Stop price for the stop-loss (sell) order

        Returns:
            dict with keys: order_ids (list of 3 ints), status, error
        """
        try:
            self._ensure_connected()
        except Exception as e:
            return {"order_ids": [], "status": "error", "error": str(e)}

        try:
            import ib_async  # pylint: disable=import-outside-toplevel

            contract = ib_async.Stock(symbol, "SMART", "USD")
            self._ib.qualifyContracts(contract)

            # ib_async moved the bracket-order helper from module-level to an
            # instance method (kept the same kwargs).
            bracket = self._ib.bracketOrder(
                action="BUY",
                quantity=quantity,
                limitPrice=round(limit_price, 2),
                takeProfitPrice=round(take_profit_price, 2),
                stopLossPrice=round(stop_loss_price, 2),
            )

            # Set all legs to GTC
            for order in bracket:
                order.tif = "GTC"

            order_ids = []
            for order in bracket:
                trade = self._ib.placeOrder(contract, order)
                order_ids.append(trade.order.orderId)

            logger.info(
                "Bracket order placed for %s: qty=%d entry=%.2f tp=%.2f sl=%.2f ids=%s",
                symbol, quantity, limit_price, take_profit_price, stop_loss_price, order_ids,
            )
            return {"order_ids": order_ids, "status": "submitted", "error": None}

        except Exception as e:
            logger.error("Error placing bracket order for %s: %s", symbol, e)
            return {"order_ids": [], "status": "error", "error": str(e)}

    def get_executions(self, since: Optional[datetime] = None) -> List[dict]:
        """
        Get execution reports from IB Gateway.

        Args:
            since: Only return executions after this time.
                   Defaults to last 24 hours.

        Returns:
            List of dicts with: exec_id, symbol, side, quantity, price,
            commission, exec_time, order_id
        """
        try:
            self._ensure_connected()
        except Exception as e:
            logger.error("Cannot connect to fetch executions: %s", e)
            return []

        try:
            import ib_async  # pylint: disable=import-outside-toplevel
            from datetime import timedelta  # pylint: disable=import-outside-toplevel

            # Build execution filter
            exec_filter = ib_async.ExecutionFilter()
            if since:
                exec_filter.time = since.strftime("%Y%m%d-%H:%M:%S")
            else:
                # Default: last 24 hours
                yesterday = datetime.now() - timedelta(days=1)
                exec_filter.time = yesterday.strftime("%Y%m%d-%H:%M:%S")

            fills = self._ib.reqExecutions(exec_filter)

            results = []
            for fill in fills:
                execution = fill.execution
                commission_report = fill.commissionReport
                commission = 0.0
                if commission_report and _safe_float(commission_report.commission) is not None:
                    commission = commission_report.commission

                results.append({
                    "exec_id": execution.execId,
                    "symbol": fill.contract.symbol,
                    "side": execution.side.lower(),  # "BOT" → "bot", "SLD" → "sld"
                    "quantity": int(execution.shares),
                    "price": float(execution.price),
                    "commission": commission,
                    "exec_time": execution.time,
                    "order_id": execution.orderId,
                })

            logger.info("Retrieved %d executions from IBKR", len(results))
            return results

        except Exception as e:
            logger.error("Error fetching executions: %s", e)
            return []

    def get_commissions(self, exec_ids: Optional[List[str]] = None) -> dict:
        """
        Get commission reports, optionally filtered by execution IDs.

        Args:
            exec_ids: If provided, only return commissions for these exec IDs.

        Returns:
            Dict mapping exec_id -> commission amount.
        """
        try:
            self._ensure_connected()
        except Exception as e:
            logger.error("Cannot connect to fetch commissions: %s", e)
            return {}

        try:
            import ib_async  # pylint: disable=import-outside-toplevel

            fills = self._ib.fills()
            result = {}
            for fill in fills:
                eid = fill.execution.execId
                if exec_ids and eid not in exec_ids:
                    continue
                cr = fill.commissionReport
                if cr and _safe_float(cr.commission) is not None:
                    result[eid] = cr.commission

            return result

        except Exception as e:
            logger.error("Error fetching commissions: %s", e)
            return {}

    def get_open_orders(self) -> list:
        """
        Get all open orders from IB Gateway.

        Returns:
            List of open Trade objects, or empty list on error.
        """
        try:
            self._ensure_connected()
            return self._ib.openOrders()
        except Exception as e:
            logger.error("Error fetching open orders: %s", e)
            return []

    def get_open_trades(self) -> list:
        """
        Get all open Trade objects (order + contract + fills + status)
        across **all** clients on this account.

        IBKR's API scopes order visibility to the client_id that placed
        them — `openTrades()` alone would only return orders this client
        submitted. `reqAllOpenOrders()` snapshots open orders from every
        client (PaperTrader on client_id=1, monitor on client_id=7, etc.),
        which is what the read-only monitor needs.

        Each Trade exposes .contract, .order, .orderStatus, .fills.
        Preferred over get_open_orders() when downstream needs symbol context.
        """
        try:
            self._ensure_connected()
            return self._ib.reqAllOpenOrders()
        except Exception as e:
            logger.error("Error fetching open trades: %s", e)
            return []

    def modify_order_stop(self, order_id: int, new_stop_price: float) -> dict:
        """
        Modify the stop (auxPrice) of a working STP order.

        IBKR's modify semantics: call placeOrder again with the same orderId
        and changed fields. The order keeps its orderId; only the modified
        attributes propagate. We use reqAllOpenOrders() so this works across
        clients (e.g., monitor modifies a PaperTrader-placed stop).

        Returns dict with keys: order_id, status, error.
        """
        try:
            self._ensure_connected()
        except Exception as e:
            return {"order_id": order_id, "status": "error", "error": str(e)}

        try:
            trades = self._ib.reqAllOpenOrders()
            target = next(
                (t for t in trades if getattr(t.order, "orderId", None) == order_id),
                None,
            )
            if target is None:
                return {"order_id": order_id, "status": "error",
                        "error": f"order {order_id} not found in open trades"}

            # Defensive: this function is "modify the stop of a STP order."
            # If we ever get called with a LMT id (say, a bug in upstream
            # leg classification routed us to a take-profit), setting
            # auxPrice would silently corrupt the LMT order without actually
            # modifying any meaningful field. Refuse loudly instead.
            order_type = getattr(target.order, "orderType", "")
            if order_type != "STP":
                return {"order_id": order_id, "status": "error",
                        "error": f"order {order_id} is {order_type!r}, not STP"}

            target.order.auxPrice = round(float(new_stop_price), 2)
            self._ib.placeOrder(target.contract, target.order)
            logger.info(
                "modify_order_stop: order_id=%s new_stop=%.2f symbol=%s",
                order_id, new_stop_price,
                getattr(target.contract, "symbol", "?"),
            )
            return {"order_id": order_id, "status": "submitted", "error": None}
        except Exception as e:
            logger.error("Error modifying stop on order %s: %s", order_id, e)
            return {"order_id": order_id, "status": "error", "error": str(e)}

    def cancel_order(self, order_id: int) -> dict:
        """
        Cancel a working order.

        Looks up the order across all clients via reqAllOpenOrders() and
        calls IB.cancelOrder. Returns dict with keys: order_id, status, error.
        """
        try:
            self._ensure_connected()
        except Exception as e:
            return {"order_id": order_id, "status": "error", "error": str(e)}

        try:
            trades = self._ib.reqAllOpenOrders()
            target = next(
                (t for t in trades if getattr(t.order, "orderId", None) == order_id),
                None,
            )
            if target is None:
                return {"order_id": order_id, "status": "error",
                        "error": f"order {order_id} not found in open trades"}

            self._ib.cancelOrder(target.order)
            logger.info("cancel_order: order_id=%s symbol=%s",
                        order_id, getattr(target.contract, "symbol", "?"))
            return {"order_id": order_id, "status": "cancelling", "error": None}
        except Exception as e:
            logger.error("Error cancelling order %s: %s", order_id, e)
            return {"order_id": order_id, "status": "error", "error": str(e)}

    def place_market_order(
        self, symbol: str, action: str, quantity: int,
    ) -> dict:
        """
        Place a market order. Used by the flatten operator tool to exit
        positions immediately.

        Args:
            symbol: stock ticker
            action: "BUY" | "SELL"
            quantity: positive integer

        Returns dict with keys: order_id, status, error.
        """
        try:
            self._ensure_connected()
        except Exception as e:
            return {"order_id": 0, "status": "error", "error": str(e)}

        try:
            import ib_async  # pylint: disable=import-outside-toplevel
            contract = ib_async.Stock(symbol, "SMART", "USD")
            self._ib.qualifyContracts(contract)
            order = ib_async.MarketOrder(action, quantity)
            order.tif = "DAY"
            trade = self._ib.placeOrder(contract, order)
            order_id = getattr(trade.order, "orderId", 0)
            logger.info(
                "place_market_order: symbol=%s %s qty=%d order_id=%s",
                symbol, action, quantity, order_id,
            )
            return {"order_id": order_id, "status": "submitted", "error": None}
        except Exception as e:
            logger.error("Error placing market order for %s: %s", symbol, e)
            return {"order_id": 0, "status": "error", "error": str(e)}

    def get_positions(self) -> List[dict]:
        """
        Get all current positions from IB Gateway.

        Returns:
            List of dicts with: account, symbol, position (signed qty),
            avg_cost, contract_type. Empty list on error or no positions.
        """
        try:
            self._ensure_connected()
        except Exception as e:
            logger.error("Cannot connect to fetch positions: %s", e)
            return []

        try:
            raw = self._ib.positions()
            results = []
            for p in raw:
                contract = p.contract
                results.append({
                    "account": getattr(p, "account", ""),
                    "symbol": getattr(contract, "symbol", ""),
                    "position": float(getattr(p, "position", 0) or 0),
                    "avg_cost": _safe_float(getattr(p, "avgCost", None)) or 0.0,
                    "contract_type": getattr(contract, "secType", ""),
                    "currency": getattr(contract, "currency", ""),
                })
            return results
        except Exception as e:
            logger.error("Error fetching positions: %s", e)
            return []

    def get_account_summary(self, account: str = "") -> dict:
        """
        Get account summary values needed for sizing and safety gates.

        Returns dict with keys (all floats, 0.0 if unavailable):
          - net_liquidation, settled_cash, available_funds, buying_power,
            total_cash_value, gross_position_value, account_id.

        Args:
            account: Optional account ID filter. Empty = first account found.
        """
        empty = {
            "account_id": account,
            "net_liquidation": 0.0,
            "settled_cash": 0.0,
            "available_funds": 0.0,
            "buying_power": 0.0,
            "total_cash_value": 0.0,
            "gross_position_value": 0.0,
        }
        try:
            self._ensure_connected()
        except Exception as e:
            logger.error("Cannot connect to fetch account summary: %s", e)
            return empty

        # Map IBKR tag -> our key. Tag names from IB API documentation.
        tag_map = {
            "NetLiquidation": "net_liquidation",
            "SettledCash": "settled_cash",
            "AvailableFunds": "available_funds",
            "BuyingPower": "buying_power",
            "TotalCashValue": "total_cash_value",
            "GrossPositionValue": "gross_position_value",
        }

        try:
            rows = self._ib.accountSummary(account) if account else self._ib.accountSummary()
            summary = dict(empty)
            for row in rows:
                tag = getattr(row, "tag", "")
                value = getattr(row, "value", "")
                row_account = getattr(row, "account", "")
                if tag in tag_map and value:
                    parsed = _safe_float(value)
                    if parsed is not None:
                        summary[tag_map[tag]] = parsed
                if row_account and not summary["account_id"]:
                    summary["account_id"] = row_account
            return summary
        except Exception as e:
            logger.error("Error fetching account summary: %s", e)
            return empty

    def close(self):
        """Disconnect from IB Gateway."""
        if self._ib is not None:
            try:
                if self._ib.isConnected():
                    self._ib.disconnect()
                    logger.info("Disconnected from IB Gateway")
            except Exception as e:
                logger.error("Error disconnecting from IB Gateway: %s", e)
            finally:
                self._ib = None
