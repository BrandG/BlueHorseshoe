"""Hypothetical trade engine — evaluates matured journal signals against actual OHLCV."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from pymongo.database import Database
from pymongo.errors import BulkWriteError

from bluehorseshoe.analysis.constants import REGIME_PROFILES
from bluehorseshoe.analysis.strategy_registry import get_all_strategies, get_strategy
from bluehorseshoe.analysis.trade_evaluator import TradeEvalConfig, evaluate_bars
from bluehorseshoe.core.market_calendar import trading_days_after
from bluehorseshoe.data.duckdb_store import DuckDBStore

logger = logging.getLogger(__name__)

EVALUATOR_VERSION = "1.0"


class HypothesisEngine:
    """
    Evaluates matured journal signals against actual OHLCV data.
    Writes results to journal_hypothetical_trades.
    """

    MATURITY_BUFFER_TRADING_DAYS = 5
    PIN_GRACE_TRADING_DAYS = 10   # extra slack before a stuck (unevaluable) batch is dropped
    ENTRY_BUFFER_PCT = 0.001   # 0.1% below entry
    SCORE_THRESHOLD = 0        # Evaluate all signals with score > 0

    def __init__(self, database: Database, store: DuckDBStore):
        self._db = database
        self._store = store
        self._batches = database["journal_batches"]
        self._signals = database["journal_signals"]
        self._results = database["journal_hypothetical_trades"]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Create indexes for idempotency and query performance."""
        self._results.create_index(
            [("batch_date", 1), ("symbol", 1), ("strategy", 1)],
            unique=True, name="ux_hypo_key",
        )
        self._results.create_index([("batch_date", 1)], name="ix_batch_date")
        self._results.create_index(
            [("outcome", 1), ("strategy", 1)], name="ix_outcome",
        )

    def _is_mature(self, batch_date: str, hold_days: int, as_of_date: str) -> bool:
        """Check if enough trading days have elapsed since the batch date.

        Uses the NYSE calendar rather than counting SPY bars in the store. The
        old SPY-bar approach silently wedged the whole feed whenever index-ETF
        OHLCV went stale: SPY/QQQ aren't in the daily ``-u`` universe, so once
        their data froze, no batch after that date could ever accumulate the
        required post-batch bars and matured signals stopped flowing. The
        calendar is the source of truth for "has time passed"; price freshness
        is the evaluator's concern, not the gate's.
        """
        needed = hold_days + self.MATURITY_BUFFER_TRADING_DAYS
        return trading_days_after(batch_date, as_of_date) >= needed

    def _get_hold_days(self, batch_doc: dict) -> int:
        """Resolve hold_days from the batch market regime."""
        regime = batch_doc.get("market_regime", {}).get("status", "Neutral")
        profile = REGIME_PROFILES.get(regime, REGIME_PROFILES.get("Neutral", {}))
        return profile.get("hold_days", 5)

    def _strategy_hold_days(self, strategy_name: str, regime_status: str) -> int:
        """Per-strategy hold horizon; falls back to the regime default for
        unknown/legacy strategy names."""
        try:
            return get_strategy(strategy_name).get_hold_days(regime_status)
        except Exception:
            profile = REGIME_PROFILES.get(
                regime_status or "Neutral", REGIME_PROFILES.get("Neutral", {})
            )
            return profile.get("hold_days", 5)

    def _strategy_entry_style(self, strategy_name: str) -> str:
        """Per-strategy entry-fill model; falls back to 'limit_below'."""
        try:
            return get_strategy(strategy_name).entry_style
        except Exception:
            return "limit_below"

    def find_mature_batches(self, as_of_date: Optional[str] = None) -> List[dict]:
        """Find mature batches that still have unevaluated signals."""
        if as_of_date is None:
            as_of_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        mature_batches: List[dict] = []
        for batch_doc in self._batches.find().sort("batch_date", 1):
            batch_date = batch_doc.get("batch_date")
            if not batch_date:
                continue

            hold_days = self._get_hold_days(batch_doc)
            if not self._is_mature(batch_date, hold_days, as_of_date):
                continue

            signal_count = self._signals.count_documents({
                "batch_date": batch_date,
                "composite_score": {"$gt": self.SCORE_THRESHOLD},
            })
            result_count = self._results.count_documents({"batch_date": batch_date})
            if result_count >= signal_count:
                continue

            # Batch-pin age-out: stop re-scanning a batch whose strategies are all long
            # past maturity but which still has unevaluable signals (e.g. missing price
            # data) — accept the partial evaluation rather than re-scanning forever.
            regime = batch_doc.get("market_regime", {}).get("status", "Neutral")
            max_hold = max((s.get_hold_days(regime) for s in get_all_strategies()),
                           default=hold_days)
            aged_threshold = (
                max_hold + self.MATURITY_BUFFER_TRADING_DAYS + self.PIN_GRACE_TRADING_DAYS
            )
            if trading_days_after(batch_date, as_of_date) >= aged_threshold:
                continue

            mature_batches.append(batch_doc)

        return mature_batches

    def _compute_spy_return(self, spy_df: pd.DataFrame, entry_date: str, exit_date: str) -> float:
        """Compute SPY return over the same period as the evaluated trade."""
        if spy_df is None or spy_df.empty:
            return 0.0

        date_strs = spy_df["date"].astype(str).str[:10]
        mask = (date_strs >= entry_date) & (date_strs <= exit_date)
        period = spy_df[mask]
        if period.empty:
            return 0.0

        spy_entry = float(period.iloc[0]["open"])
        spy_exit = float(period.iloc[-1]["close"])
        if spy_entry == 0:
            return 0.0
        return (spy_exit - spy_entry) / spy_entry

    def evaluate_batch(self, batch_doc: dict, as_of_date: Optional[str] = None) -> dict:
        """Evaluate all positive-score signals in a matured batch."""
        batch_date = batch_doc["batch_date"]
        regime = batch_doc.get("market_regime", {}).get("status", "Unknown")
        if as_of_date is None:
            as_of_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        regime_hold = self._get_hold_days(batch_doc)   # batch baseline, for the summary line

        signals = list(self._signals.find({
            "batch_date": batch_date,
            "composite_score": {"$gt": self.SCORE_THRESHOLD},
        }))

        symbols = list({s["symbol"] for s in signals} | {"SPY"})
        price_data = self._store.load_symbols_bulk(symbols, start_date=batch_date)
        spy_df = price_data.get("SPY")

        result_docs: List[Dict[str, Any]] = []
        errors = 0

        for signal in signals:
            try:
                strat_name = signal.get("strategy", "")
                strat_hold = self._strategy_hold_days(strat_name, regime)
                if not self._is_mature(batch_date, strat_hold, as_of_date):
                    continue   # this strategy hasn't matured yet for this batch — pick up on a later run
                entry_style = self._strategy_entry_style(strat_name)
                config = TradeEvalConfig(
                    hold_days=strat_hold,
                    entry_buffer_pct=self.ENTRY_BUFFER_PCT,
                    entry_style=entry_style,
                )
                symbol = signal["symbol"]
                symbol_df = price_data.get(symbol)
                if symbol_df is None or symbol_df.empty:
                    logger.debug("No price data for %s after %s", symbol, batch_date)
                    errors += 1
                    continue

                entry_price = signal["entry_price"]
                stop_loss = signal["stop_loss"]
                take_profit = signal.get("take_profit_t2", 0)
                if not entry_price or not stop_loss or not take_profit:
                    errors += 1
                    continue

                eval_result = evaluate_bars(
                    bars_df=symbol_df,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    config=config,
                )

                spy_return = 0.0
                if eval_result["entry_date"] and eval_result["exit_date"]:
                    spy_return = self._compute_spy_return(
                        spy_df, eval_result["entry_date"], eval_result["exit_date"]
                    )
                elif spy_df is not None and not spy_df.empty:
                    spy_slice = spy_df.head(strat_hold)
                    if not spy_slice.empty:
                        spy_open = float(spy_slice.iloc[0]["open"])
                        if spy_open != 0:
                            spy_return = (
                                float(spy_slice.iloc[-1]["close"]) - spy_open
                            ) / spy_open

                result_docs.append({
                    "batch_date": batch_date,
                    "symbol": symbol,
                    "strategy": signal["strategy"],
                    "composite_score": signal.get("composite_score", 0),
                    "signal_strength": signal.get("signal_strength", ""),
                    "rank": signal.get("rank", 0),
                    "ml_win_probability": signal.get("ml_win_probability", 0.0),
                    # 48h news annotation arms (DeepOS-family; None = not annotated)
                    # carried through so matured trades split by arm without a join
                    "news_48h_mean": signal.get("news_48h_mean"),
                    "news_48h_count": signal.get("news_48h_count"),
                    "news_48h_arm": signal.get("news_48h_arm"),
                    # Options-fear annotation arms (DeepOS-family; None = not annotated)
                    "options_skew": signal.get("options_skew"),
                    "options_atm_iv": signal.get("options_atm_iv"),
                    "options_dte": signal.get("options_dte"),
                    "options_dd10": signal.get("options_dd10"),
                    "options_arm": signal.get("options_arm"),
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "market_regime": regime,
                    "hold_days": strat_hold,
                    "outcome": eval_result["outcome"],
                    "adjusted_entry": entry_price * (1 - self.ENTRY_BUFFER_PCT),
                    "actual_entry": eval_result["actual_entry"],
                    "entry_date": eval_result["entry_date"],
                    "exit_price": eval_result["exit_price"],
                    "exit_date": eval_result["exit_date"],
                    "exit_reason": eval_result["exit_reason"],
                    "days_held": eval_result["days_held"],
                    "pnl_pct": eval_result["pnl_pct"],
                    "mae_pct": eval_result["mae_pct"],
                    "mfe_pct": eval_result["mfe_pct"],
                    "spy_return_pct": spy_return,
                    "alpha_pct": eval_result["pnl_pct"] - spy_return,
                    "evaluated_at": datetime.now(timezone.utc),
                    "evaluator_version": EVALUATOR_VERSION,
                })
            except Exception as exc:
                logger.warning(
                    "Failed to evaluate %s/%s: %s",
                    signal.get("symbol"),
                    signal.get("strategy"),
                    exc,
                )
                errors += 1

        inserted = 0
        if result_docs:
            try:
                res = self._results.insert_many(result_docs, ordered=False)
                inserted = len(res.inserted_ids)
            except BulkWriteError as bwe:
                inserted = bwe.details.get("nInserted", 0)
                logger.info(
                    "Batch %s: %d new, %d duplicates skipped.",
                    batch_date,
                    inserted,
                    len(result_docs) - inserted,
                )

        outcomes: Dict[str, int] = {}
        for doc in result_docs:
            outcomes[doc["outcome"]] = outcomes.get(doc["outcome"], 0) + 1

        return {
            "batch_date": batch_date,
            "regime": regime,
            "hold_days": regime_hold,
            "evaluated": inserted,
            "skipped_duplicates": len(result_docs) - inserted,
            "errors": errors,
            "outcomes": outcomes,
        }

    def run(self, as_of_date: Optional[str] = None) -> List[dict]:
        """Find mature batches and evaluate them. Returns per-batch summaries."""
        if as_of_date is None:
            as_of_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        mature = self.find_mature_batches(as_of_date=as_of_date)
        if not mature:
            logger.info("HypothesisEngine: No mature batches to evaluate.")
            return []

        logger.info("HypothesisEngine: Found %d mature batch(es) to evaluate.", len(mature))
        summaries = []
        for batch_doc in mature:
            try:
                summary = self.evaluate_batch(batch_doc, as_of_date=as_of_date)
                summaries.append(summary)
                logger.info(
                    "HypothesisEngine: Batch %s — %d evaluated, outcomes: %s",
                    summary["batch_date"], summary["evaluated"], summary["outcomes"],
                )
            except Exception as exc:
                logger.error(
                    "HypothesisEngine: Failed to evaluate batch %s: %s",
                    batch_doc.get("batch_date"), exc,
                )
        return summaries
