"""
Curve segmentation via Ramer-Douglas-Peucker on ATR-normalized prices.

Takes OHLCV DataFrame → detects turning points → returns typed segments.
ATR normalization makes shapes comparable across different price levels.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TurningPoint:
    """A detected inflection point in the price series."""
    index: int          # bar index within window
    date: str
    norm_price: float   # ATR-normalized
    raw_price: float    # actual close


@dataclass(frozen=True)
class Segment:
    """A directional move between two consecutive turning points."""
    start: TurningPoint
    end: TurningPoint
    direction: int      # +1 up, -1 down
    magnitude: float    # ATR-normalized abs(delta)
    duration: int       # bars
    slope: float        # magnitude / duration
    curvature: float    # max perpendicular deviation / atr_mean


@dataclass
class Segmentation:
    """Complete segmentation result for a price window."""
    symbol: str
    window_size: int
    segments: List[Segment]
    turning_points: List[TurningPoint]
    atr_mean: float
    start_date: str
    end_date: str


def rdp_simplify(points: np.ndarray, epsilon: float) -> List[int]:
    """
    Ramer-Douglas-Peucker simplification.

    Args:
        points: Nx2 array of (x, y) coordinates.
        epsilon: Maximum perpendicular distance threshold.

    Returns:
        Sorted list of indices of surviving points.
    """
    if len(points) <= 2:
        return list(range(len(points)))

    # Find the point with maximum perpendicular distance from the line
    # connecting first and last points
    start = points[0]
    end = points[-1]

    # Line vector
    line_vec = end - start
    line_len = np.sqrt(line_vec[0] ** 2 + line_vec[1] ** 2)

    if line_len == 0:
        # All points at same location — keep first and last
        return [0, len(points) - 1]

    # Unit normal to the line
    line_unit = line_vec / line_len

    # Perpendicular distances for all intermediate points
    diffs = points[1:-1] - start
    # Cross product magnitude gives perpendicular distance
    cross = np.abs(diffs[:, 0] * line_unit[1] - diffs[:, 1] * line_unit[0])

    max_idx = np.argmax(cross)
    max_dist = cross[max_idx]
    max_idx += 1  # offset for skipping first point

    if max_dist > epsilon:
        # Recurse on both halves
        left = rdp_simplify(points[:max_idx + 1], epsilon)
        right = rdp_simplify(points[max_idx:], epsilon)
        # Merge, avoiding duplicate at split point
        return left + [idx + max_idx for idx in right[1:]]
    return [0, len(points) - 1]


def detect_turning_points(
    close: np.ndarray, atr: np.ndarray, epsilon: float = 1.0
) -> List[int]:
    """
    RDP on ATR-normalized prices. Returns turning point indices.

    Args:
        close: Array of closing prices.
        atr: Array of ATR values (same length as close).
        epsilon: RDP threshold in ATR units.

    Returns:
        List of indices where turning points occur.
    """
    atr_mean = np.nanmean(atr)
    if atr_mean == 0 or np.isnan(atr_mean):
        atr_mean = close[0] * 0.02  # fallback: 2% of first close

    # Normalize: (close - close[0]) / atr_mean
    norm = (close - close[0]) / atr_mean

    # Build (x, y) points where x = bar index
    x = np.arange(len(norm), dtype=float)
    points = np.column_stack([x, norm])

    return rdp_simplify(points, epsilon)


def _compute_curvature(
    close_norm: np.ndarray, start_idx: int, end_idx: int
) -> float:
    """
    Max perpendicular distance of intermediate points from the line
    connecting segment start to segment end, normalized by atr_mean.
    """
    if end_idx - start_idx <= 1:
        return 0.0

    # Points in this segment
    x = np.arange(end_idx - start_idx + 1, dtype=float)
    y = close_norm[start_idx:end_idx + 1]

    # Line from first to last
    start_pt = np.array([x[0], y[0]])
    end_pt = np.array([x[-1], y[-1]])
    line_vec = end_pt - start_pt
    line_len = np.sqrt(line_vec[0] ** 2 + line_vec[1] ** 2)

    if line_len == 0:
        return 0.0

    line_unit = line_vec / line_len

    # Perpendicular distances of intermediate points
    diffs = np.column_stack([x[1:-1], y[1:-1]]) - start_pt
    cross = np.abs(diffs[:, 0] * line_unit[1] - diffs[:, 1] * line_unit[0])

    if len(cross) == 0:
        return 0.0

    return float(np.max(cross))


def segment_price_series(
    df: pd.DataFrame, window_size: int = 40, epsilon: float = 1.0,
    symbol: str = ""
) -> Segmentation:
    """
    Segment the last `window_size` bars into directional moves.

    Args:
        df: DataFrame with columns: date, close, high, low.
        window_size: Number of trailing bars to analyze.
        epsilon: RDP simplification threshold (ATR units).
        symbol: Optional symbol name for the result.

    Returns:
        Segmentation object with turning points and segments.
    """
    if len(df) < 5:
        return Segmentation(
            symbol=symbol, window_size=window_size,
            segments=[], turning_points=[], atr_mean=0.0,
            start_date="", end_date=""
        )

    # Use last window_size bars (or all if fewer)
    n = min(window_size, len(df))
    window = df.iloc[-n:].reset_index(drop=True)

    close = window['close'].values.astype(float)
    high = window['high'].values.astype(float)
    low = window['low'].values.astype(float)

    # Compute ATR(14) or use available bars
    atr_window = min(14, n - 1)
    if atr_window < 1:
        atr_mean = close[0] * 0.02
        atr = np.full(n, atr_mean)
    else:
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:] - close[:-1])
            )
        )
        # Pad first element
        tr = np.concatenate([[tr[0]], tr])
        # Rolling mean for ATR
        atr = pd.Series(tr).rolling(window=atr_window, min_periods=1).mean().values
        atr_mean = float(np.nanmean(atr))

    if atr_mean == 0 or np.isnan(atr_mean):
        atr_mean = close[0] * 0.02

    # Detect turning points
    tp_indices = detect_turning_points(close, atr, epsilon)

    # Normalized prices
    norm = (close - close[0]) / atr_mean

    # Get date strings
    if 'date' in window.columns:
        dates = window['date'].astype(str).values
    else:
        dates = [str(i) for i in range(n)]

    # Build TurningPoint objects
    turning_points = []
    for idx in tp_indices:
        turning_points.append(TurningPoint(
            index=idx,
            date=dates[idx],
            norm_price=float(norm[idx]),
            raw_price=float(close[idx])
        ))

    # Build Segment objects
    segments = []
    for i in range(len(turning_points) - 1):
        tp_start = turning_points[i]
        tp_end = turning_points[i + 1]

        delta = tp_end.norm_price - tp_start.norm_price
        direction = 1 if delta > 0 else -1
        magnitude = abs(delta)
        duration = tp_end.index - tp_start.index
        slope = magnitude / duration if duration > 0 else 0.0
        curvature = _compute_curvature(norm, tp_start.index, tp_end.index)

        segments.append(Segment(
            start=tp_start,
            end=tp_end,
            direction=direction,
            magnitude=float(magnitude),
            duration=duration,
            slope=float(slope),
            curvature=float(curvature)
        ))

    return Segmentation(
        symbol=symbol,
        window_size=n,
        segments=segments,
        turning_points=turning_points,
        atr_mean=atr_mean,
        start_date=dates[0],
        end_date=dates[-1]
    )


def segment_multi_window(
    df: pd.DataFrame, windows: Tuple[int, ...] = (20, 40), epsilon: float = 1.0,
    symbol: str = ""
) -> Dict[int, Segmentation]:
    """Run segmentation at multiple window lengths."""
    return {
        w: segment_price_series(df, window_size=w, epsilon=epsilon, symbol=symbol)
        for w in windows
    }
