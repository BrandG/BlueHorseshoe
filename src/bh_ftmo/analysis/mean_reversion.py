"""Mean-reversion strategy for BH FTMO.

Philosophy
----------
Forex pairs alternate between trending and range-bound regimes. Mean
reversion fades stretched moves on the assumption that extreme readings
revert to the mean. Two-sided: oversold → buy, overbought → sell.

Signal direction is **per-bar**, not per-strategy. A bar yields:

  - direction = +1 if any "long anchor" condition fires (RSI < 30, below
    BB lower band, etc.)
  - direction = -1 if any "short anchor" condition fires (RSI > 70, above
    BB upper band, etc.)
  - direction = 0 if neither (no signal — sub-threshold, components empty)

When both sides fire on the same bar (very rare, usually a data anomaly),
the side with the higher accumulated weight wins.

Rule taxonomy
-------------
Long anchors (any one needed):
  - ``mr_rsi_oversold``         RSI < 30
  - ``mr_below_bb_lower``       close < Bollinger lower band
  - ``mr_williams_oversold``    Williams %R < -80
  - ``mr_cci_extreme_low``      CCI < -100

Short anchors (any one needed):
  - ``mr_rsi_overbought``       RSI > 70
  - ``mr_above_bb_upper``       close > Bollinger upper band
  - ``mr_williams_overbought``  Williams %R > -20
  - ``mr_cci_extreme_high``     CCI > 100

Direction-specific bonuses:
  - ``mr_bullish_reversal_candle``  hammer OR bullish engulfing  (long only)
  - ``mr_bearish_reversal_candle``  shooting-star OR bearish eng (short only)

Direction-neutral bonuses (added to whichever side fired):
  - ``mr_adx_weak``             ADX < 20 (range regime, MR thesis intact)
  - ``mr_asia_session_bonus``   bar in ASIA session (range-bound by nature)
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from bh_ftmo.analysis.strategy import Signal, load_weights
from bh_ftmo.indicators import (
    Session,
    adx,
    bollinger_bands,
    cci,
    is_bearish_engulfing,
    is_bullish_engulfing,
    is_hammer,
    is_shooting_star,
    ohlc_mid,
    rsi,
    session_label,
    williams_r,
)


class MeanReversionStrategy:
    """Two-sided mean-reversion scoring."""

    name = "mean_reversion"

    def __init__(
        self,
        weights: Optional[dict] = None,
        *,
        rsi_period: int = 14,
        bb_period: int = 20,
        bb_std: float = 2.0,
        adx_period: int = 14,
        williams_period: int = 14,
        cci_period: int = 20,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        williams_oversold: float = -80.0,
        williams_overbought: float = -20.0,
        cci_low: float = -100.0,
        cci_high: float = 100.0,
        adx_range_threshold: float = 20.0,
    ) -> None:
        if weights is None:
            weights = load_weights()
        strat_cfg = weights.get(self.name)
        if strat_cfg is None:
            raise ValueError(f"weights file has no '{self.name}' strategy block")
        self._component_weights: dict[str, float] = dict(strat_cfg.get("components", {}))
        self.min_score_threshold: float = float(strat_cfg.get("min_score_threshold", 0.0))
        self.rsi_period = rsi_period
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.adx_period = adx_period
        self.williams_period = williams_period
        self.cci_period = cci_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.williams_oversold = williams_oversold
        self.williams_overbought = williams_overbought
        self.cci_low = cci_low
        self.cci_high = cci_high
        self.adx_range_threshold = adx_range_threshold

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
        """Score every bar in ``pair_df``. ``dxy`` and ``strengths`` are
        accepted for API compatibility with BaselineStrategy but currently
        unused — the MR thesis doesn't lean on them. Phase 2c tuning may
        revisit."""
        if "timestamp" not in pair_df.columns:
            raise ValueError("pair_df must have a 'timestamp' column")
        if len(pair_df) == 0:
            return []

        ohlc = ohlc_mid(pair_df)
        timestamps = pair_df["timestamp"].to_list()

        rsi_series = rsi(ohlc, period=self.rsi_period)
        bb_df = bollinger_bands(ohlc, period=self.bb_period, n_std=self.bb_std)
        adx_df = adx(ohlc, period=self.adx_period)
        wr_series = williams_r(ohlc, period=self.williams_period)
        cci_series = cci(ohlc, period=self.cci_period)
        hammer_flags = is_hammer(ohlc)
        bull_engulf = is_bullish_engulfing(ohlc)
        star_flags = is_shooting_star(ohlc)
        bear_engulf = is_bearish_engulfing(ohlc)
        labels = session_label(pair_df["timestamp"])

        w = self._component_weights
        signals: list[Signal] = []

        for i in range(len(ohlc)):
            ts = timestamps[i]
            close_i = ohlc["close"].iloc[i]

            long_components: dict[str, float] = {}
            short_components: dict[str, float] = {}

            # --- long anchors ---
            rsi_i = rsi_series.iloc[i]
            if pd.notna(rsi_i) and rsi_i < self.rsi_oversold:
                long_components["mr_rsi_oversold"] = w.get("mr_rsi_oversold", 0.0)
            if pd.notna(rsi_i) and rsi_i > self.rsi_overbought:
                short_components["mr_rsi_overbought"] = w.get("mr_rsi_overbought", 0.0)

            bb_lower = bb_df["lower"].iloc[i]
            bb_upper = bb_df["upper"].iloc[i]
            if pd.notna(bb_lower) and close_i < bb_lower:
                long_components["mr_below_bb_lower"] = w.get("mr_below_bb_lower", 0.0)
            if pd.notna(bb_upper) and close_i > bb_upper:
                short_components["mr_above_bb_upper"] = w.get("mr_above_bb_upper", 0.0)

            wr_i = wr_series.iloc[i]
            if pd.notna(wr_i) and wr_i < self.williams_oversold:
                long_components["mr_williams_oversold"] = w.get("mr_williams_oversold", 0.0)
            if pd.notna(wr_i) and wr_i > self.williams_overbought:
                short_components["mr_williams_overbought"] = w.get("mr_williams_overbought", 0.0)

            cci_i = cci_series.iloc[i]
            if pd.notna(cci_i) and cci_i < self.cci_low:
                long_components["mr_cci_extreme_low"] = w.get("mr_cci_extreme_low", 0.0)
            if pd.notna(cci_i) and cci_i > self.cci_high:
                short_components["mr_cci_extreme_high"] = w.get("mr_cci_extreme_high", 0.0)

            long_anchor_fired = bool(long_components)
            short_anchor_fired = bool(short_components)

            # --- direction-specific bonuses ---
            if long_anchor_fired and (bool(hammer_flags.iloc[i]) or bool(bull_engulf.iloc[i])):
                long_components["mr_bullish_reversal_candle"] = w.get(
                    "mr_bullish_reversal_candle", 0.0
                )
            if short_anchor_fired and (bool(star_flags.iloc[i]) or bool(bear_engulf.iloc[i])):
                short_components["mr_bearish_reversal_candle"] = w.get(
                    "mr_bearish_reversal_candle", 0.0
                )

            # --- direction-neutral bonuses (added to whichever fired) ---
            adx_i = adx_df["adx"].iloc[i]
            adx_weak = pd.notna(adx_i) and adx_i < self.adx_range_threshold
            asia = labels.iloc[i] == Session.ASIA

            if long_anchor_fired:
                if adx_weak:
                    long_components["mr_adx_weak"] = w.get("mr_adx_weak", 0.0)
                if asia:
                    long_components["mr_asia_session_bonus"] = w.get("mr_asia_session_bonus", 0.0)
            if short_anchor_fired:
                if adx_weak:
                    short_components["mr_adx_weak"] = w.get("mr_adx_weak", 0.0)
                if asia:
                    short_components["mr_asia_session_bonus"] = w.get("mr_asia_session_bonus", 0.0)

            # Strip zero-weight (disabled) contributions
            long_components = {k: v for k, v in long_components.items() if v != 0.0}
            short_components = {k: v for k, v in short_components.items() if v != 0.0}
            long_score = sum(long_components.values())
            short_score = sum(short_components.values())

            # --- resolve direction ---
            if not long_anchor_fired and not short_anchor_fired:
                direction = 0
                score = 0.0
                components: dict[str, float] = {}
            elif long_anchor_fired and not short_anchor_fired:
                direction, score, components = +1, long_score, long_components
            elif short_anchor_fired and not long_anchor_fired:
                direction, score, components = -1, short_score, short_components
            else:
                # Both sides fired (rare). Pick the higher-scoring one.
                if long_score >= short_score:
                    direction, score, components = +1, long_score, long_components
                else:
                    direction, score, components = -1, short_score, short_components

            signals.append(
                Signal(
                    symbol=symbol,
                    strategy=self.name,
                    timestamp=ts,
                    direction=direction,
                    score=score,
                    components=components,
                    above_threshold=score >= self.min_score_threshold and direction != 0,
                )
            )
        return signals
