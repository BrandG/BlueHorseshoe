"""
Immutable Signal Journal for tracking prediction batches and signals.
Layer A of the track-record system.

Two collections:
  - journal_batches: One record per prediction run (keyed by batch_date)
  - journal_signals: One record per recommended signal

All writes are insert-only (never upsert). Duplicate batch_date is
detected via unique index and silently skipped with a warning.
"""
import logging
import subprocess
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from bluehorseshoe.core.config import weights_config
from bluehorseshoe.analysis.constants import (
    MIN_RR_RATIO_BASELINE,
    MIN_RR_RATIO_MEAN_REVERSION,
    MAX_RISK_PERCENT,
    MIN_STOCK_PRICE,
    MAX_STOCK_PRICE,
    SIGNAL_STRENGTH_THRESHOLDS,
    ENTRY_DISCOUNT_BY_SIGNAL,
)

logger = logging.getLogger(__name__)

ALGORITHM_VERSION = "2.0"


class SignalJournal:
    """
    Captures immutable prediction snapshots into MongoDB.

    All writes are insert-only. Duplicate batch_date is detected via
    unique index and silently skipped.
    """

    def __init__(self, database: Database):
        if database is None:
            raise ValueError("database parameter is required for SignalJournal")
        self._db = database
        self._batches = self._db["journal_batches"]
        self._signals = self._db["journal_signals"]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Create unique indexes to enforce immutability constraints."""
        try:
            self._batches.create_index(
                [("batch_date", 1)],
                unique=True,
                name="ux_batch_date",
            )
            self._signals.create_index(
                [("batch_date", 1), ("symbol", 1), ("strategy", 1)],
                unique=True,
                name="ux_signal_key",
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("SignalJournal index creation warning: %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_git_commit() -> str:
        """Return short git hash, or empty string on failure."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                cwd="/workspaces/BlueHorseshoe",
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:  # pylint: disable=broad-exception-caught
            return ""

    @staticmethod
    def _build_config_snapshot(
        paper_settings: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Snapshot current configuration state."""
        return {
            "weights": {
                cat: weights_config.get_weights(cat)
                for cat in (
                    "trend",
                    "momentum",
                    "volume",
                    "candlestick",
                    "mean_reversion",
                    "price_action",
                )
            },
            "constants": {
                "MIN_RR_RATIO_BASELINE": MIN_RR_RATIO_BASELINE,
                "MIN_RR_RATIO_MEAN_REVERSION": MIN_RR_RATIO_MEAN_REVERSION,
                "MAX_RISK_PERCENT": MAX_RISK_PERCENT,
                "MIN_STOCK_PRICE": MIN_STOCK_PRICE,
                "MAX_STOCK_PRICE": MAX_STOCK_PRICE,
                "SIGNAL_STRENGTH_THRESHOLDS": SIGNAL_STRENGTH_THRESHOLDS,
                "ENTRY_DISCOUNT_BY_SIGNAL": ENTRY_DISCOUNT_BY_SIGNAL,
            },
            "paper_settings": paper_settings,
        }

    def _build_signal_docs(
        self,
        batch_date: str,
        valid_results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Transform valid_results into journal_signals documents.
        Signals are ranked within their strategy by score descending.
        """
        baseline_items: List[Dict[str, Any]] = []
        mr_items: List[Dict[str, Any]] = []

        for r in valid_results:
            if r.get("baseline_score", 0) > 0:
                baseline_items.append(r)
            if r.get("mr_score", 0) > 0:
                mr_items.append(r)

        baseline_items.sort(key=lambda x: x["baseline_score"], reverse=True)
        mr_items.sort(key=lambda x: x["mr_score"], reverse=True)

        docs: List[Dict[str, Any]] = []

        for rank, r in enumerate(baseline_items, start=1):
            setup = r.get("baseline_setup", {})
            entry_price = setup.get("entry_price", 0)
            docs.append(
                {
                    "batch_date": batch_date,
                    "rank": rank,
                    "symbol": r["symbol"],
                    "strategy": "baseline",
                    "composite_score": r["baseline_score"],
                    "ml_win_probability": r.get("baseline_ml_prob", 0.0),
                    "signal_strength": setup.get("signal_strength", "MEDIUM"),
                    "entry_price": entry_price,
                    "stop_loss": setup.get("stop_loss", 0),
                    "take_profit_t1": (
                        round(entry_price * 1.02, 4) if entry_price > 0 else 0
                    ),
                    "take_profit_t2": setup.get("take_profit", 0),
                    "risk_reward_ratio": setup.get("rr_ratio", 0),
                    "atr_discount_used": setup.get("atr_discount_used", 0.20),
                    "stop_multiplier": r.get("stop_multiplier", 2.0),
                    "target_multiplier": r.get("target_multiplier", 3.0),
                    "sentiment": r.get("sentiment", 0.0),
                    "components": r.get("baseline_components", {}),
                }
            )

        for rank, r in enumerate(mr_items, start=1):
            setup = r.get("mr_setup", {})
            entry_price = setup.get("entry_price", 0)
            docs.append(
                {
                    "batch_date": batch_date,
                    "rank": rank,
                    "symbol": r["symbol"],
                    "strategy": "mean_reversion",
                    "composite_score": r["mr_score"],
                    "ml_win_probability": r.get("mr_ml_prob", 0.0),
                    "signal_strength": setup.get("signal_strength", "N/A"),
                    "entry_price": entry_price,
                    "stop_loss": setup.get("stop_loss", 0),
                    "take_profit_t1": (
                        round(entry_price * 1.02, 4) if entry_price > 0 else 0
                    ),
                    "take_profit_t2": setup.get("take_profit", 0),
                    "risk_reward_ratio": setup.get("rr_ratio", 0),
                    "atr_discount_used": setup.get("atr_discount_used", 0.0),
                    "stop_multiplier": r.get("stop_multiplier", 1.5),
                    "target_multiplier": r.get("target_multiplier", 2.0),
                    "sentiment": r.get("sentiment", 0.0),
                    "components": r.get("mr_components", {}),
                }
            )

        return docs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def freeze_batch(
        self,
        batch_date: str,
        valid_results: List[Dict[str, Any]],
        market_health: Dict[str, Any],
        symbol_count: int,
        paper_settings: Optional[Dict[str, Any]] = None,
        notes: str = "",
    ) -> bool:
        """
        Freeze an immutable snapshot of the prediction batch.

        Returns True if the batch was written, False if skipped (duplicate)
        or if an error occurred.  Never raises — journal failures must not
        break the prediction pipeline.
        """
        if paper_settings is None:
            paper_settings = {}

        try:
            signal_docs = self._build_signal_docs(batch_date, valid_results)

            batch_doc = {
                "batch_date": batch_date,
                "generated_at": datetime.now(timezone.utc),
                "git_commit": self._get_git_commit(),
                "algorithm_version": ALGORITHM_VERSION,
                "symbol_count": symbol_count,
                "candidate_count": len(signal_docs),
                "market_regime": market_health,
                "config_snapshot": self._build_config_snapshot(paper_settings),
                "notes": notes,
            }

            # Insert batch — DuplicateKeyError means this date is already frozen
            try:
                self._batches.insert_one(batch_doc)
            except DuplicateKeyError:
                logger.warning(
                    "SignalJournal: Batch for %s already exists, skipping.",
                    batch_date,
                )
                return False

            # Insert signals
            if signal_docs:
                try:
                    self._signals.insert_many(signal_docs, ordered=False)
                except DuplicateKeyError:
                    logger.warning(
                        "SignalJournal: Some signals for %s already existed.",
                        batch_date,
                    )

            logger.info(
                "SignalJournal: Froze batch %s — %d signals.",
                batch_date,
                len(signal_docs),
            )
            return True

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "SignalJournal: freeze_batch failed for %s: %s",
                batch_date,
                exc,
            )
            return False
