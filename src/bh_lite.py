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
import requests
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
DEFAULT_POSITIONS_PATH = os.path.join(os.path.dirname(__file__), "bh_lite_positions.json")


def load_config(path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Load BH Lite JSON config."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_positions(path: str = DEFAULT_POSITIONS_PATH) -> List[dict]:
    """Load open positions. Returns empty list if file missing or empty."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            positions = json.load(f)
        return positions if isinstance(positions, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def summarize_positions(positions: List[dict], default_risk: float = 1000.0) -> dict:
    """Summarize open positions: total risk used and position count."""
    total_risk = sum(position.get("risk_usd") or default_risk for position in positions)
    return {"total_risk_usd": total_risk, "count": len(positions)}


def _find_instrument_by_ftmo(ftmo_symbol: str, config: dict) -> Optional[dict]:
    """Find instrument config by FTMO symbol."""
    normalized = ftmo_symbol.replace(".sim", "").replace("/", "").upper()
    aliases = {
        "GSPC": "^GSPC",
        "US500": "^GSPC",
        "SPX500": "^GSPC",
        "US30": "^DJI",
        "DJI": "^DJI",
        "NAS100": "^IXIC",
        "USTEC": "^IXIC",
        "IXIC": "^IXIC",
        "DAX40": "^GDAXI",
        "GDAXI": "^GDAXI",
        "XAUUSD": "GC=F",
        "GOLD": "GC=F",
        "XAGUSD": "SI=F",
        "SILVER": "SI=F",
        "USOIL": "CL=F",
        "WTI": "CL=F",
        "BTCUSD": "BTC-USD",
        "ETHUSD": "ETH-USD",
    }
    for inst in config.get("instruments", []):
        ftmo = inst.get("ftmo", "").replace(".sim", "").replace("/", "").upper()
        yahoo = inst.get("symbol", "").replace("=X", "").replace("/", "").upper()
        if normalized in (ftmo, yahoo):
            return inst
        if len(normalized) == 6 and normalized.isalpha() and f"{normalized}=X" == inst.get("symbol"):
            return inst
        if aliases.get(normalized) == inst.get("symbol"):
            return inst
    return None


def fetch_ohlcv(symbol: str, period: str = "6mo") -> Optional[pd.DataFrame]:
    """Fetch daily OHLCV from Yahoo Finance chart API."""
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": period, "interval": "1d"}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # pragma: no cover - network failure path
        logger.warning("Failed to fetch %s: %s", symbol, exc)
        return None

    try:
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
        df = pd.DataFrame({
            "date": pd.to_datetime(timestamps, unit="s").strftime("%Y-%m-%d"),
            "open": quote["open"],
            "high": quote["high"],
            "low": quote["low"],
            "close": quote["close"],
            "volume": [v if v is not None else 0 for v in quote["volume"]],
        })
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("Failed to parse data for %s: %s", symbol, exc)
        return None

    df = df.dropna(subset=["open", "high", "low", "close"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = df["volume"].fillna(0)
    # Floor volume at 1 to prevent division-by-zero in volume indicators.
    # Yahoo returns 0 volume for forex pairs; setting to 1 makes volume
    # indicators return neutral scores instead of NaN.
    df["volume"] = df["volume"].replace(0, 1)
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


def _calculate_position_pnl(position: dict, instrument: dict, current_price: float) -> tuple:
    entry = float(position.get("entry", 0))
    lots = float(position.get("lots", 0))
    side = position.get("side", "buy").lower()
    if entry <= 0:
        return 0.0, 0.0
    price_delta = current_price - entry
    if side == "sell":
        price_delta = -price_delta
    if instrument["type"] == "forex":
        pips = price_delta / instrument["pip_size"]
        pnl = pips * instrument["dollar_per_pip_per_lot"] * lots
    else:
        pnl = price_delta * lots * instrument["contract_size"]
    pnl_pct = (price_delta / entry) * 100
    return round(pnl, 2), round(pnl_pct, 2)


def check_position_health(position: dict, config: dict) -> Optional[dict]:
    """Re-score an open position and assess health."""
    instrument = _find_instrument_by_ftmo(position.get("ftmo_symbol", ""), config)
    if instrument is None:
        logger.warning("No instrument config found for %s", position.get("ftmo_symbol", ""))
        return None

    df = fetch_ohlcv(instrument["symbol"])
    if df is None or df.empty:
        logger.warning("No data returned for open position %s", position.get("ftmo_symbol", ""))
        return None

    enriched = enrich_dataframe(df)
    scores = score_instrument(enriched)
    baseline_score = scores["baseline_score"]
    mean_reversion_score = scores["mean_reversion_score"]
    if baseline_score >= mean_reversion_score:
        current_score = baseline_score
        current_strategy = "Baseline"
    else:
        current_score = mean_reversion_score
        current_strategy = "MeanRev"

    current_price = float(enriched.iloc[-1]["close"])
    pnl_usd, pnl_pct = _calculate_position_pnl(position, instrument, current_price)
    stop = float(position.get("stop", current_price))
    distance_to_stop = abs(current_price - stop)
    distance_to_stop_pct = (distance_to_stop / current_price) * 100 if current_price else 0.0
    atr = LiteTrader()._calculate_atr(enriched)
    entry_score = float(position.get("entry_score", 10.0))

    warnings = []
    if current_score <= 0:
        warnings.append(f"Score collapsed to {current_score:.1f}")
    elif current_score < 5.0:
        warnings.append(f"Score below 5.0 threshold ({current_score:.1f})")
    if entry_score > 0 and current_score < entry_score * 0.5:
        warnings.append(f"Score dropped >50% from entry ({entry_score:.0f} -> {current_score:.1f})")
    if abs(pnl_pct) < 0.5 and current_score < entry_score * 0.6:
        warnings.append(f"Flat P&L with fading signal ({current_score:.1f} vs {entry_score:.0f} at entry)")
    if distance_to_stop <= 0.5 * atr:
        warnings.append("Price within 0.5 ATR of stop loss")
    if pnl_pct <= -3.0:
        warnings.append("Unrealized loss exceeds 3%")
    if pnl_pct < 0 and current_score < 5.0:
        warnings.append("Price below entry and score is weak")

    status = "OK"
    if current_score <= 0 or distance_to_stop <= 0.5 * atr or pnl_pct <= -3.0:
        status = "CRITICAL"
    elif warnings:
        status = "WEAKENING"

    return {
        "position": position,
        "current_price": current_price,
        "pnl_usd": pnl_usd,
        "pnl_pct": pnl_pct,
        "current_score": current_score,
        "current_strategy": current_strategy,
        "distance_to_stop_pct": round(distance_to_stop_pct, 2),
        "status": status,
        "warnings": warnings,
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
    risk_usd = max_risk_usd

    if risk_per_unit <= 0:
        return {"lots": 0, "risk_usd": 0, "skipped": True, "over_budget": False}

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

    over_budget = actual_risk > remaining_daily
    return {"lots": lots, "risk_usd": round(actual_risk, 2), "skipped": lots == 0, "over_budget": over_budget}


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


def format_output(
    signals: Sequence[dict],
    account_config: dict,
    risk_config: dict,
    daily_risk_used: float,
    positions: Optional[Sequence[dict]] = None,
    health_checks: Optional[Sequence[dict]] = None,
) -> str:
    """Format ranked signal table for the console."""
    positions = positions or []
    health_checks = health_checks or []
    daily_budget = account_config["size"] * risk_config["max_daily_risk_pct"]
    remaining_budget = max(0.0, daily_budget - daily_risk_used)
    max_positions = risk_config["max_concurrent_positions"]
    lines = [
        f"BH Lite FTMO Signals - {date.today().isoformat()}",
        f"Account: ${account_config['size']:,.0f} {account_config.get('currency', 'USD')} | Remaining daily risk: ${remaining_budget:,.2f}",
        "",
    ]
    if positions:
        lines.append("Open Positions:")
        for position in positions:
            lines.append(
                f"  {position.get('ftmo_symbol', ''):<14}  {position.get('side', ''):<4}  "
                f"{position.get('lots', 0):>6.2f} lots  entry {position.get('entry', 0):.2f}  "
                f"stop {position.get('stop', 0):.2f}  risk ${position.get('risk_usd') or 1000:,.2f}  "
                f"opened {position.get('opened', '')}"
            )
        lines.extend([
            "",
            f"Positions: {len(positions)}/{max_positions} | Daily risk committed: ${daily_risk_used:,.2f} / ${daily_budget:,.2f}",
            "",
        ])
    if health_checks:
        lines.extend(["== POSITION HEALTH CHECK ==", ""])
        for health in health_checks:
            position = health["position"]
            prefix = ""
            if health["status"] == "CRITICAL":
                prefix = "!! "
            elif health["status"] == "WEAKENING":
                prefix = "! "
            lines.append(
                f"{prefix}{position.get('ftmo_symbol', ''):<12}  {position.get('side', ''):<4} "
                f"@ {position.get('entry', 0):.2f}   now {health['current_price']:.2f}   "
                f"P&L ${health['pnl_usd']:,.0f} ({health['pnl_pct']:+.1f}%)   "
                f"Score: {health['current_score']:.1f} {health['current_strategy']}   {health['status']}"
            )
            for warning in health["warnings"]:
                lines.append(f"    -> {warning}")
        lines.append("")
    t1_split = risk_config.get("t1_split_pct", 0.5)
    lines.extend([
        "== TOP SIGNALS ==",
        "",
        "  #  FTMO Symbol     Leg  Strategy  Score   Ctx     Entry      Stop       Target     Lots    Risk$",
        "  -  --------------  ---  --------  ------  ------  ---------  ---------  ---------  ------  --------",
    ])
    used = daily_risk_used
    for idx, signal in enumerate(signals, start=1):
        setup = signal["setup"]
        size = signal["position_size"]
        targets = signal["targets"]
        ftmo = signal["instrument"].get("ftmo", signal["instrument"]["name"])
        min_lot = signal["instrument"].get("min_lot", 0.01)
        total_lots = size["lots"]
        t1_lots = _round_down_to_lot(total_lots * t1_split, min_lot)
        t2_lots = _round_down_to_lot(total_lots - t1_lots, min_lot)
        ctx_display = f"{signal.get('intraday_context', 0.0):>+5.2f}"
        fb_flag = " !FB" if signal.get("failed_breakout") else ""
        budget_note = ""
        if size.get("over_budget"):
            budget_note = "  ** OVER DAILY BUDGET **"
        used += size["risk_usd"]
        lines.append(
            f"  {idx}  {ftmo:<14}  T1   {signal['strategy']:<8}  "
            f"{signal['score']:>6.2f}  {ctx_display}{fb_flag:<4}  {setup['entry_price']:>9.5f}  {setup['stop_loss']:>9.5f}  "
            f"{targets['t1']:>9.5f}  {t1_lots:>6.2f}  ${size['risk_usd'] * t1_split:>7.2f}{budget_note}"
        )
        lines.append(
            f"     {'':<14}  T2   {'':<8}  "
            f"{'':>6}  {'':>6}  {'':>9}  {'':>9}  "
            f"{targets['t2']:>9.5f}  {t2_lots:>6.2f}  ${size['risk_usd'] * (1 - t1_split):>7.2f}"
        )
        lines.append("")
    lines.append(f"Daily risk used: ${used:,.2f} / ${daily_budget:,.2f}")
    return "\n".join(lines)


def _write_csv(signals: Sequence[dict], output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "rank", "instrument", "symbol", "strategy", "score", "context_score",
                "entry", "stop", "t1", "t2", "lots", "risk_usd",
            ],
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
                    "context_score": signal.get("intraday_context", 0.0),
                    "entry": setup["entry_price"],
                    "stop": setup["stop_loss"],
                    "t1": targets["t1"],
                    "t2": targets["t2"],
                    "lots": size["lots"],
                    "risk_usd": size["risk_usd"],
                }
            )


def _write_orders(signals: Sequence[dict], output_path: str) -> None:
    """Write ready-to-paste position entries for accepted BH Lite signals."""
    orders = []
    for signal in signals:
        setup = signal["setup"]
        size = signal["position_size"]
        instrument = signal["instrument"]
        orders.append({
            "ftmo_symbol": instrument.get("ftmo", instrument["name"]),
            "name": instrument["name"],
            "symbol": instrument["symbol"],
            "side": "buy",
            "strategy": signal["strategy"],
            "entry": round(setup["entry_price"], 5),
            "stop": round(setup["stop_loss"], 5),
            "lots": size["lots"],
            "risk_usd": size["risk_usd"],
            "entry_score": round(signal["score"], 2),
            "opened": date.today().isoformat(),
        })

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(orders, f, indent=2)


def _build_signal(instrument: dict, df: pd.DataFrame, config: dict, daily_risk_used: float) -> dict:
    trader = LiteTrader()
    scores = score_instrument(df)
    from bluehorseshoe.analysis.intraday_context import compute_daily_context
    ctx = compute_daily_context(df)
    context_bonus = ctx["context_score"] * 3.0
    scores["baseline_score"] += context_bonus
    scores["baseline_components"]["intraday_context"] = context_bonus
    scores["mean_reversion_score"] += context_bonus * 0.67
    scores["mean_reversion_components"]["intraday_context"] = context_bonus * 0.67
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
    signal["intraday_context"] = ctx["context_score"]
    signal["intraday_label"] = ctx["context_label"]
    signal["failed_breakout"] = ctx["failed_breakout"]
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
    parser.add_argument("--positions", default=DEFAULT_POSITIONS_PATH, help="Path to BH Lite open positions JSON.")
    parser.add_argument("--top", type=int, default=3, help="Number of ranked signals to print.")
    parser.add_argument("--csv", action="store_true", help="Write ranked signals to src/logs/bh_lite_YYYY-MM-DD.csv.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    config = load_config(args.config)
    positions = load_positions(args.positions)
    pos_summary = summarize_positions(positions)
    health_checks = []
    for position in positions:
        health = check_position_health(position, config)
        if health:
            health_checks.append(health)
    daily_risk_used = pos_summary["total_risk_usd"]
    signals = []
    failed = []

    for instrument in config["instruments"]:
        df = fetch_ohlcv(instrument["symbol"])
        if df is None or len(df) < 60:
            failed.append(instrument["name"])
            continue
        enriched = enrich_dataframe(df)
        signal = _build_signal(instrument, enriched, config, daily_risk_used)
        if "setup" in signal:
            signals.append(signal)

    ranked = rank_signals(signals, top_n=args.top)
    daily_risk_used = pos_summary["total_risk_usd"]
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

    output = format_output(
        ranked,
        config["account"],
        config["risk"],
        pos_summary["total_risk_usd"],
        positions,
        health_checks,
    )
    if failed:
        output += "\nFailed fetches: " + ", ".join(failed)
    print(output)

    orders_path = os.path.join(os.path.dirname(__file__), "bh_lite_orders.json")
    _write_orders(ranked, orders_path)
    print(f"Orders template: {orders_path}")

    if args.csv:
        path = os.path.join("src", "logs", f"bh_lite_{date.today().isoformat()}.csv")
        _write_csv(ranked, path)
        print(f"CSV written: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
