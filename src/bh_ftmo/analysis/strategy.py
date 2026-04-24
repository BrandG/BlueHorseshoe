"""BH FTMO strategy scoring — `BaselineStrategy` and shared types.

A strategy takes:
  - ``pair_df``: bid/ask OHLC DataFrame from :class:`FxStore.load` (with a
    ``timestamp`` column)
  - ``weights``: per-component weight dict (from ``bh_ftmo_weights.json``)
  - Optional multi-pair context: synthesized ``dxy`` series and a currency
    ``strengths`` DataFrame

...and produces one :class:`Signal` per bar. Each signal records which rules
fired (``components``), the total weighted score, and whether the score
crosses the configured threshold (``above_threshold``).

This module deliberately keeps the scoring logic **rule-based and
discrete**. Each component is a boolean condition; when true it contributes
its weight to the score. This trades a bit of expressiveness for legibility
— the components dict makes every signal fully explainable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from bh_ftmo.indicators import (
    Session,
    adx,
    ema,
    ichimoku,
    is_bullish_engulfing,
    is_hammer,
    macd as macd_fn,
    ohlc_mid,
    rsi,
    session_label,
    supertrend,
)
from bh_ftmo.indicators.strength import _split_pair

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WEIGHTS_PATH = REPO_ROOT / "src" / "bh_ftmo_weights.json"


@dataclass(frozen=True)
class Signal:
    """One bar's strategy output.

    ``components`` shows every rule that fired with its contribution value
    (= weight if boolean-rule design is kept). ``score`` is the sum.
    """

    symbol: str
    strategy: str
    timestamp: datetime
    direction: int  # +1 long, -1 short, 0 = no valid signal
    score: float
    components: dict[str, float] = field(default_factory=dict)
    above_threshold: bool = False


def load_weights(path: Optional[Path] = None) -> dict:
    """Load ``bh_ftmo_weights.json``. Returns the full config dict."""
    path = path or DEFAULT_WEIGHTS_PATH
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


class BaselineStrategy:
    """Long-only trend-following baseline.

    Scoring rules (each fires a boolean → adds its weight):

      Trend:
        - ``trend_above_ema_50``:          close > EMA(50)
        - ``trend_adx_strong_bullish``:    ADX >= 20 AND +DI > -DI
        - ``trend_supertrend_up``:         supertrend direction == +1
        - ``trend_ichimoku_above_cloud``:  close > max(senkou_a, senkou_b)
        - ``trend_macd_bullish``:          MACD histogram > 0

      Momentum:
        - ``momentum_rsi_healthy``:        40 <= RSI <= 70
        - ``momentum_rsi_not_overbought``: RSI < 70

      Candlestick:
        - ``candlestick_bullish_reversal``: hammer OR bullish_engulfing fires
          on the current bar

      Context (optional — contribute only if the relevant context is provided):
        - ``strength_base_strong``:        base currency is in the top 3 of
          the 8-major strength rank
        - ``strength_quote_weak``:         quote currency is in the bottom 3
        - ``dxy_alignment``:               DXY direction supports the setup.
          For USD-quote pairs (*/USD): DXY has been falling over the past
          20 bars. For USD-base pairs: DXY has been rising.
        - ``session_overlap_bonus``:       current bar is in the London/NY
          OVERLAP session

    All rules are configured via the "baseline.components" dict in
    ``bh_ftmo_weights.json``. Setting a weight to 0 disables a rule.
    """

    name = "baseline"

    def __init__(
        self,
        weights: Optional[dict] = None,
        *,
        ema_period: int = 50,
        adx_period: int = 14,
        rsi_period: int = 14,
        adx_threshold: float = 20.0,
        dxy_lookback: int = 20,
        strength_top_k: int = 3,
    ) -> None:
        if weights is None:
            weights = load_weights()
        strat_cfg = weights.get(self.name)
        if strat_cfg is None:
            raise ValueError(f"weights file has no '{self.name}' strategy block")
        self._component_weights: dict[str, float] = dict(strat_cfg.get("components", {}))
        self.direction: int = int(strat_cfg.get("direction", 1))
        self.min_score_threshold: float = float(strat_cfg.get("min_score_threshold", 0.0))
        self.ema_period = ema_period
        self.adx_period = adx_period
        self.rsi_period = rsi_period
        self.adx_threshold = adx_threshold
        self.dxy_lookback = dxy_lookback
        self.strength_top_k = strength_top_k

    @property
    def component_weights(self) -> dict[str, float]:
        return dict(self._component_weights)

    def score_pair(
        self,
        pair_df: pd.DataFrame,
        *,
        symbol: str,
        dxy: Optional[pd.Series] = None,
        strengths: Optional[pd.DataFrame] = None,
    ) -> list[Signal]:
        """Score every bar in ``pair_df``. Returns one :class:`Signal` per bar."""
        if "timestamp" not in pair_df.columns:
            raise ValueError("pair_df must have a 'timestamp' column")
        if len(pair_df) == 0:
            return []

        ohlc = ohlc_mid(pair_df)
        timestamps = pair_df["timestamp"].to_list()
        split = _split_pair(symbol)
        base_ccy, quote_ccy = split if split else (None, None)

        # Pre-compute indicator series once (all pandas Series/DataFrames
        # aligned to ohlc's row index).
        ema_fast = ema(ohlc, period=self.ema_period)
        adx_df = adx(ohlc, period=self.adx_period)
        rsi_series = rsi(ohlc, period=self.rsi_period)
        st_df = supertrend(ohlc)
        ich_df = ichimoku(ohlc)
        macd_df = macd_fn(ohlc)
        hammer_flags = is_hammer(ohlc)
        engulf_flags = is_bullish_engulfing(ohlc)

        labels = session_label(pair_df["timestamp"])

        # DXY alignment: positive-slope DXY over lookback is USD strengthening
        dxy_slope: Optional[pd.Series] = None
        if dxy is not None:
            dxy_aligned = dxy.reindex(pair_df["timestamp"].to_list()) if len(dxy) else None
            # fallback: use index-based reindex against ohlc.index (if both share a grid)
            if dxy_aligned is None or dxy_aligned.isna().all():
                dxy_aligned = None
            if dxy_aligned is None:
                # try matching by ohlc.index
                try:
                    dxy_aligned = dxy.reindex(ohlc.index)
                except Exception:  # noqa: BLE001
                    dxy_aligned = None
            if dxy_aligned is not None:
                dxy_slope = dxy_aligned - dxy_aligned.shift(self.dxy_lookback)

        # Currency strength ranks: highest = strongest
        strength_rank: Optional[pd.DataFrame] = None
        if strengths is not None:
            strength_rank = strengths.rank(axis=1, ascending=True, method="average")

        signals: list[Signal] = []
        w = self._component_weights
        n = len(ohlc)
        for i in range(n):
            ts = timestamps[i]
            components: dict[str, float] = {}

            close_i = ohlc["close"].iloc[i]
            ema_i = ema_fast.iloc[i]
            if pd.notna(ema_i) and close_i > ema_i:
                components["trend_above_ema_50"] = w.get("trend_above_ema_50", 0.0)

            adx_i = adx_df["adx"].iloc[i]
            pdi = adx_df["plus_di"].iloc[i]
            mdi = adx_df["minus_di"].iloc[i]
            if pd.notna(adx_i) and adx_i >= self.adx_threshold and pdi > mdi:
                components["trend_adx_strong_bullish"] = w.get("trend_adx_strong_bullish", 0.0)

            if int(st_df["direction"].iloc[i]) == 1:
                components["trend_supertrend_up"] = w.get("trend_supertrend_up", 0.0)

            senk_a = ich_df["senkou_a"].iloc[i]
            senk_b = ich_df["senkou_b"].iloc[i]
            if pd.notna(senk_a) and pd.notna(senk_b) and close_i > max(senk_a, senk_b):
                components["trend_ichimoku_above_cloud"] = w.get("trend_ichimoku_above_cloud", 0.0)

            hist_i = macd_df["histogram"].iloc[i]
            if pd.notna(hist_i) and hist_i > 0:
                components["trend_macd_bullish"] = w.get("trend_macd_bullish", 0.0)

            rsi_i = rsi_series.iloc[i]
            if pd.notna(rsi_i):
                if 40 <= rsi_i <= 70:
                    components["momentum_rsi_healthy"] = w.get("momentum_rsi_healthy", 0.0)
                if rsi_i < 70:
                    components["momentum_rsi_not_overbought"] = w.get(
                        "momentum_rsi_not_overbought", 0.0
                    )

            if bool(hammer_flags.iloc[i]) or bool(engulf_flags.iloc[i]):
                components["candlestick_bullish_reversal"] = w.get(
                    "candlestick_bullish_reversal", 0.0
                )

            if strength_rank is not None and base_ccy is not None:
                if base_ccy in strength_rank.columns:
                    try:
                        base_rank = strength_rank[base_ccy].loc[ts]
                        n_ccy = len(strength_rank.columns)
                        if pd.notna(base_rank) and base_rank >= n_ccy - self.strength_top_k + 1:
                            components["strength_base_strong"] = w.get("strength_base_strong", 0.0)
                    except KeyError:
                        pass
                if quote_ccy in strength_rank.columns:
                    try:
                        quote_rank = strength_rank[quote_ccy].loc[ts]
                        if pd.notna(quote_rank) and quote_rank <= self.strength_top_k:
                            components["strength_quote_weak"] = w.get("strength_quote_weak", 0.0)
                    except KeyError:
                        pass

            if dxy_slope is not None:
                slope_i = dxy_slope.iloc[i] if i < len(dxy_slope) else None
                if pd.notna(slope_i):
                    # USD-quote pair (*/USD): we want DXY falling for a long trade (USD weakening)
                    # USD-base pair (USD/*): we want DXY rising
                    # Non-USD cross: skip
                    if quote_ccy == "USD" and slope_i < 0:
                        components["dxy_alignment"] = w.get("dxy_alignment", 0.0)
                    elif base_ccy == "USD" and slope_i > 0:
                        components["dxy_alignment"] = w.get("dxy_alignment", 0.0)

            if labels.iloc[i] == Session.OVERLAP:
                components["session_overlap_bonus"] = w.get("session_overlap_bonus", 0.0)

            # Remove zero-weight (disabled) contributions from the report
            components = {k: v for k, v in components.items() if v != 0.0}
            score = sum(components.values())
            signals.append(
                Signal(
                    symbol=symbol,
                    strategy=self.name,
                    timestamp=ts,
                    direction=self.direction,
                    score=score,
                    components=components,
                    above_threshold=score >= self.min_score_threshold,
                )
            )

        return signals
