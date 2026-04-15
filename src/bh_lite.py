"""BH Lite: daily-bar FTMO signal generator using BlueHorseshoe scoring."""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
import yfinance as yf
from ta.volatility import AverageTrueRange

from bluehorseshoe.analysis.constants import (
    ATR_WINDOW,
    ENTRY_DISCOUNT_BY_SIGNAL,
    ENABLE_DYNAMIC_ENTRY,
    MAX_RISK_PERCENT,
    MIN_RR_RATIO_BASELINE,
    SIGNAL_STRENGTH_THRESHOLDS,
)
from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer
from bluehorseshoe.data.historical_data import get_technical_indicators

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "bh_lite_config.json")


def load_config(path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Load BH Lite JSON config."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_ohlcv(symbol: str, period: str = "6mo") -> Optional[pd.DataFrame]:
    """Fetch daily OHLCV data from yfinance and normalize columns."""
    try:
        raw = yf.download(symbol, period=period, progress=False, auto_adjust=False)
    except Exception as exc:  # pragma: no cover - network failure path
        logger.warning("Failed to fetch %s: %s", symbol, exc)
        return None

    if raw is None or raw.empty:
        logger.warning("No data returned for %s", symbol)
        return None

    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    df = df.reset_index()
    df.columns = [str(col).lower().replace(" ", "_") for col in df.columns]
    if "adj_close" in df.columns and "close" not in df.columns:
        df["close"] = df["adj_close"]
    if "date" not in df.columns:
        first_col = df.columns[0]
        df = df.rename(columns={first_col: "date"})

    required = ["date", "open", "high", "low", "close"]
    if any(col not in df.columns for col in required):
        logger.warning("Missing OHLC columns for %s", symbol)
        return None

    if "volume" not in df.columns:
        df["volume"] = 0
    df = df[["date", "open", "high", "low", "close", "volume"]].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = df["volume"].fillna(0)
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df.reset_index(drop=True)


def enrich_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Add BlueHorseshoe technical indicators to a DataFrame."""
    enriched = df.copy()
    get_technical_indicators(enriched)
    return enriched


class LiteTrader:
    """Lightweight setup calculator - no DB, no ML dependencies."""

    def _calculate_atr(self, df: pd.DataFrame) -> float:
        """Helper to calculate or retrieve ATR."""
        if 'ATR' not in df.columns:
            df['ATR'] = AverageTrueRange(
                high=df['high'],
                low=df['low'],
                close=df['close'],
                window=ATR_WINDOW
            ).average_true_range()
        atr = df['ATR'].values[-1]
        if pd.isna(atr):
            return df['close'].values[-1] * 0.02
        return atr

    @staticmethod
    def _classify_signal_strength(score: float) -> str:
        """
        Classify technical score into strength tier.

        Args:
            score: Technical score (typically 0-100+)

        Returns:
            Signal strength classification: EXTREME, HIGH, MEDIUM, LOW, or WEAK
        """
        thresholds = SIGNAL_STRENGTH_THRESHOLDS
        if score >= thresholds['EXTREME']:
            return 'EXTREME'
        elif score >= thresholds['HIGH']:
            return 'HIGH'
        elif score >= thresholds['MEDIUM']:
            return 'MEDIUM'
        elif score >= thresholds['LOW']:
            return 'LOW'
        else:
            return 'WEAK'

    @staticmethod
    def _get_dynamic_atr_discount(technical_score: float) -> float:
        """
        Calculate dynamic ATR discount based on signal strength.

        Args:
            technical_score: Technical score (0-100+)

        Returns:
            ATR multiplier (0.05 - 0.50) for entry calculation
        """
        if not ENABLE_DYNAMIC_ENTRY:
            return 0.20

        signal_class = LiteTrader._classify_signal_strength(technical_score)
        return ENTRY_DISCOUNT_BY_SIGNAL.get(signal_class, 0.20)

    def _determine_baseline_entry(
        self,
        last_row: pd.Series,
        ema9: float,
        atr: float,
        technical_score: float = 0.0
    ) -> tuple[float, float, str]:
        """
        Determine entry price using dynamic ATR discount based on signal strength.

        Args:
            last_row: Latest price data
            ema9: 9-period EMA (kept for compatibility, not currently used)
            atr: Average True Range
            technical_score: Technical score for signal quality (default 0.0 for backward compat)

        Returns:
            Tuple of (entry_price, atr_discount_used, signal_strength)
        """
        last_close = last_row['close']

        atr_discount = self._get_dynamic_atr_discount(technical_score)
        signal_strength = self._classify_signal_strength(technical_score)

        entry_price = last_close - (atr_discount * atr)

        return entry_price, atr_discount, signal_strength

    def calculate_baseline_setup(self, df: pd.DataFrame, ml_stop_multiplier: float = 2.0, ml_target_multiplier: float = 3.0, technical_score: float = 0.0) -> Dict[str, float]:
        """
        Calculate structural prices for Baseline (Trend) strategy:
        Entry = Pullback to EMA + Bullish candle close
        Stop = Below recent swing low or ml_stop_multiplier * ATR
        Target = Prior high or ml_target_multiplier * ATR
        """
        last_row = df.iloc[-1]
        last_close = last_row['close']

        ema9 = df['close'].ewm(span=9).mean().iloc[-1]
        atr = self._calculate_atr(df)

        swing_low_5 = df['low'].rolling(window=5).min().iloc[-1]

        entry_price, atr_discount_used, signal_strength = self._determine_baseline_entry(last_row, ema9, atr, technical_score=technical_score)

        atr_stop = entry_price - (ml_stop_multiplier * atr)
        swing_stop = swing_low_5 * 0.985

        stop_loss = min(swing_stop, atr_stop)

        atr_target = entry_price + (ml_target_multiplier * atr)
        take_profit = entry_price + (atr_target - entry_price) * 0.98

        risk = entry_price - stop_loss
        reward = take_profit - entry_price
        rr_ratio = reward / risk if risk > 0 else 0

        if rr_ratio < MIN_RR_RATIO_BASELINE and stop_loss == swing_stop:
            risk_atr = entry_price - atr_stop
            rr_atr = reward / risk_atr if risk_atr > 0 else 0

            if rr_atr >= MIN_RR_RATIO_BASELINE:
                stop_loss = atr_stop
                rr_ratio = rr_atr

        avg_volume = last_row.get('avg_volume_20', 1)
        risk_pct = (entry_price - stop_loss) / entry_price if entry_price > 0 else 0

        return {
            'entry_price': float(entry_price),
            'stop_loss': float(stop_loss),
            'take_profit': float(take_profit),
            'rr_ratio': float(rr_ratio),
            'vol_ratio': float(last_row['volume'] / avg_volume if avg_volume > 0 else 0),
            'is_realistic': (abs((last_close / entry_price) - 1) <= 0.15) and (risk_pct <= MAX_RISK_PERCENT),
            'atr_discount_used': float(atr_discount_used),
            'signal_strength': signal_strength
        }

    def calculate_mean_reversion_setup(self, df: pd.DataFrame, ml_stop_multiplier: float = 1.5, ml_target_multiplier: float = 2.0) -> Dict[str, float]:
        """
        Calculate structural prices for Mean Reversion (Dip) strategy:
        Entry = Current Close (Buying extreme weakness)
        Stop = ml_stop_multiplier * ATR (Tighter stop for fast reversals)
        Target = ml_target_multiplier * ATR with 2% delta haircut
        """
        last_row = df.iloc[-1]
        last_close = last_row['close']

        atr = self._calculate_atr(df)

        entry_price = last_close

        stop_loss = entry_price - (ml_stop_multiplier * atr)

        atr_target = entry_price + (ml_target_multiplier * atr)
        take_profit = entry_price + (atr_target - entry_price) * 0.98

        reward = take_profit - entry_price
        risk = entry_price - stop_loss
        rr_ratio = reward / risk if risk > 0 else 0
        risk_pct = risk / entry_price if entry_price > 0 else 0

        return {
            'entry_price': float(entry_price),
            'stop_loss': float(stop_loss),
            'take_profit': float(take_profit),
            'rr_ratio': float(rr_ratio),
            'vol_ratio': last_row['volume'] / last_row.get('avg_volume_20', 1) if last_row.get('avg_volume_20', 0) > 0 else 0,
            'is_realistic': risk_pct <= MAX_RISK_PERCENT
        }


def score_instrument(df: pd.DataFrame) -> dict:
    """Score an enriched instrument for baseline and mean reversion setups."""
    baseline_components = TechnicalAnalyzer.calculate_baseline_score(df)
    mean_reversion_components = TechnicalAnalyzer.calculate_technical_score(df, strategy="mean_reversion")
    return {
        "baseline_score": float(baseline_components.get("total", 0.0)),
        "baseline_components": baseline_components,
        "mean_reversion_score": float(mean_reversion_components.get("total", 0.0)),
        "mean_reversion_components": mean_reversion_components,
    }


def calculate_t1_t2(entry: float, stop: float, take_profit: float) -> dict:
    """Calculate split targets."""
    risk = entry - stop
    return {"t1": entry + risk, "t2": take_profit}


def _round_down_to_lot(lots: float, min_lot: float) -> float:
    rounded = int((lots + 1e-9) / min_lot) * min_lot
    return round(max(0.0, rounded), 4)


def calculate_position_size(
    entry: float,
    stop: float,
    instrument: dict,
    risk_config: dict,
    account_config: dict,
    daily_risk_used: float,
) -> dict:
    """Calculate FTMO-aware position size."""
    risk_per_unit = abs(entry - stop)
    max_risk_usd = account_config["size"] * risk_config["max_risk_per_trade_pct"]
    remaining_daily = account_config["size"] * risk_config["max_daily_risk_pct"] - daily_risk_used
    risk_usd = min(max_risk_usd, remaining_daily)

    if risk_usd <= 0 or risk_per_unit <= 0:
        return {"lots": 0, "risk_usd": 0, "skipped": True}

    if instrument["type"] == "forex":
        risk_in_pips = risk_per_unit / instrument["pip_size"]
        lots = risk_usd / (risk_in_pips * instrument["dollar_per_pip_per_lot"])
        actual_risk = lots * risk_in_pips * instrument["dollar_per_pip_per_lot"]
    else:
        lots = risk_usd / (risk_per_unit * instrument["contract_size"])
        actual_risk = lots * risk_per_unit * instrument["contract_size"]

    lots = _round_down_to_lot(lots, instrument["min_lot"])
    if instrument["type"] == "forex":
        actual_risk = lots * (risk_per_unit / instrument["pip_size"]) * instrument["dollar_per_pip_per_lot"]
    else:
        actual_risk = lots * risk_per_unit * instrument["contract_size"]

    return {"lots": lots, "risk_usd": round(actual_risk, 2), "skipped": lots == 0}


def _candidate_for_strategy(signal: dict, strategy_key: str) -> Optional[dict]:
    score_key = f"{strategy_key}_score"
    setup_key = f"{strategy_key}_setup"
    setup = signal.get(setup_key, {})
    if not setup.get("is_realistic") or setup.get("rr_ratio", 0) < 0.5:
        return None
    return {
        **signal,
        "strategy": "Baseline" if strategy_key == "baseline" else "MeanRev",
        "score": signal.get(score_key, 0.0),
        "setup": setup,
    }


def rank_signals(signals: Sequence[dict], top_n: Optional[int] = None) -> List[dict]:
    """Pick each instrument's best valid strategy and rank by score."""
    ranked = []
    for signal in signals:
        candidates = [
            candidate
            for candidate in (
                _candidate_for_strategy(signal, "baseline"),
                _candidate_for_strategy(signal, "mean_reversion"),
            )
            if candidate is not None
        ]
        if candidates:
            ranked.append(max(candidates, key=lambda item: item["score"]))
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:top_n] if top_n is not None else ranked


def format_output(signals: Sequence[dict], account_config: dict, risk_config: dict, daily_risk_used: float) -> str:
    """Format ranked signal table for the console."""
    daily_budget = account_config["size"] * risk_config["max_daily_risk_pct"]
    lines = [
        f"BH Lite FTMO Signals - {date.today().isoformat()}",
        f"Account: ${account_config['size']:,.0f} {account_config.get('currency', 'USD')} | Daily risk budget: ${daily_budget:,.2f}",
        "",
        "Rank  Instrument  Strategy  Score   Entry      Stop       T1         T2         Lots    Risk$",
        "----  ----------  --------  ------  ---------  ---------  ---------  ---------  ------  --------",
    ]
    used = daily_risk_used
    for idx, signal in enumerate(signals, start=1):
        setup = signal["setup"]
        size = signal["position_size"]
        targets = signal["targets"]
        used += size["risk_usd"]
        lines.append(
            f"{idx:>4}  {signal['instrument']['name']:<10}  {signal['strategy']:<8}  "
            f"{signal['score']:>6.2f}  {setup['entry_price']:>9.5f}  {setup['stop_loss']:>9.5f}  "
            f"{targets['t1']:>9.5f}  {targets['t2']:>9.5f}  {size['lots']:>6.2f}  ${size['risk_usd']:>7.2f}"
        )
    lines.extend(["", f"Daily risk used: ${used:,.2f} / ${daily_budget:,.2f}"])
    return "\n".join(lines)


def _write_csv(signals: Sequence[dict], output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["rank", "instrument", "symbol", "strategy", "score", "entry", "stop", "t1", "t2", "lots", "risk_usd"],
        )
        writer.writeheader()
        for idx, signal in enumerate(signals, start=1):
            setup = signal["setup"]
            targets = signal["targets"]
            size = signal["position_size"]
            writer.writerow(
                {
                    "rank": idx,
                    "instrument": signal["instrument"]["name"],
                    "symbol": signal["instrument"]["symbol"],
                    "strategy": signal["strategy"],
                    "score": signal["score"],
                    "entry": setup["entry_price"],
                    "stop": setup["stop_loss"],
                    "t1": targets["t1"],
                    "t2": targets["t2"],
                    "lots": size["lots"],
                    "risk_usd": size["risk_usd"],
                }
            )


def _build_signal(instrument: dict, df: pd.DataFrame, config: dict, daily_risk_used: float) -> dict:
    trader = LiteTrader()
    scores = score_instrument(df)
    baseline_setup = trader.calculate_baseline_setup(df, technical_score=scores["baseline_score"])
    mean_reversion_setup = trader.calculate_mean_reversion_setup(df)
    signal = {
        "instrument": instrument,
        "baseline_score": scores["baseline_score"],
        "baseline_components": scores["baseline_components"],
        "baseline_setup": baseline_setup,
        "mean_reversion_score": scores["mean_reversion_score"],
        "mean_reversion_components": scores["mean_reversion_components"],
        "mean_reversion_setup": mean_reversion_setup,
    }
    ranked = rank_signals([signal], top_n=1)
    if not ranked:
        return signal
    best = ranked[0]
    setup = best["setup"]
    best["targets"] = calculate_t1_t2(setup["entry_price"], setup["stop_loss"], setup["take_profit"])
    best["position_size"] = calculate_position_size(
        setup["entry_price"],
        setup["stop_loss"],
        instrument,
        config["risk"],
        config["account"],
        daily_risk_used,
    )
    return best


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run BH Lite signal generation."""
    parser = argparse.ArgumentParser(description="Generate BH Lite FTMO daily-bar signals.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to BH Lite config JSON.")
    parser.add_argument("--top", type=int, default=3, help="Number of ranked signals to print.")
    parser.add_argument("--csv", action="store_true", help="Write ranked signals to src/logs/bh_lite_YYYY-MM-DD.csv.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    config = load_config(args.config)
    signals = []
    failed = []
    daily_risk_used = 0.0

    for instrument in config["instruments"]:
        df = fetch_ohlcv(instrument["symbol"])
        if df is None or len(df) < 60:
            failed.append(instrument["name"])
            continue
        enriched = enrich_dataframe(df)
        signal = _build_signal(instrument, enriched, config, daily_risk_used)
        if "position_size" in signal and not signal["position_size"]["skipped"]:
            signals.append(signal)

    ranked = rank_signals(signals, top_n=args.top)
    daily_risk_used = 0.0
    for signal in ranked:
        signal["position_size"] = calculate_position_size(
            signal["setup"]["entry_price"],
            signal["setup"]["stop_loss"],
            signal["instrument"],
            config["risk"],
            config["account"],
            daily_risk_used,
        )
        daily_risk_used += signal["position_size"]["risk_usd"]

    output = format_output(ranked, config["account"], config["risk"], 0.0)
    if failed:
        output += "\nFailed fetches: " + ", ".join(failed)
    print(output)

    if args.csv:
        path = os.path.join("src", "logs", f"bh_lite_{date.today().isoformat()}.csv")
        _write_csv(ranked, path)
        print(f"CSV written: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
