"""Reference clean-harness primitives — Layer 1 (hygiene) + Layer 2 (statistics).

This module encodes the standard from research/README.md so studies don't re-derive
(and re-taint) it. It is intentionally small and dependency-light (numpy + pandas).
Layer 3 (faithful next-open fills + tiered cost stress) is study-specific and lives
in each study's runner — see README §1.

Honesty notes:
- These are reference implementations, not a tested library. Sanity-check on your data.
- bracket_trade resolves same-bar stop+target collisions CONSERVATIVELY (stop first).
  If you have intraday/sub-bar data, model the path instead of assuming the worst.
"""
from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# Layer 1 — hygiene
# ---------------------------------------------------------------------------

# Floors (see README §1). Screen tier vs liquid/tradeable tier.
VOL_FLOOR_ATR_PCT = 0.005          # drop dead stocks
DOLLAR_VOL_FLOOR_SCREEN = 1_000_000      # $1M  — first-pass screen
DOLLAR_VOL_FLOOR_LIQUID = 25_000_000     # $25M — "tradeable on liquid names" claims


def atr_pct(high, low, close, window: int = 14) -> np.ndarray:
    """ATR as a fraction of close (Wilder). Returns an array aligned to `close`."""
    high = np.asarray(high, float)
    low = np.asarray(low, float)
    close = np.asarray(close, float)
    prev_close = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum.reduce([
        high - low,
        np.abs(high - prev_close),
        np.abs(low - prev_close),
    ])
    atr = np.full_like(tr, np.nan)
    if len(tr) >= window:
        atr[window - 1] = tr[:window].mean()
        for i in range(window, len(tr)):
            atr[i] = (atr[i - 1] * (window - 1) + tr[i]) / window
    return atr / close


def passes_liquidity(close: float, vol20: float, tier: str = "screen") -> bool:
    """Dollar-volume floor. tier in {'screen' ($1M), 'liquid' ($25M)}."""
    floor = DOLLAR_VOL_FLOOR_LIQUID if tier == "liquid" else DOLLAR_VOL_FLOOR_SCREEN
    return (close * vol20) >= floor


def bracket_trade(
    fwd_high,
    fwd_low,
    fwd_close,
    entry: float,
    stop_dist: float,
    target_R: float = 2.0,
    max_hold: int = 10,
    side: int = 1,
) -> float:
    """Bracketed outcome in R for one trade. Worst case = -1.0R.

    Walks forward bars (1..max_hold). Win = +target_R, loss = -1.0,
    timeout = fractional (close_at_exit - entry)/risk in R. Conservative on
    same-bar stop+target collisions (assumes stop first).

    side: +1 long, -1 short. stop_dist is a positive price distance (e.g. 1*ATR).
    fwd_* are the forward OHLC path AFTER entry (length >= 1).
    """
    if stop_dist <= 0:
        return np.nan
    fwd_high = np.asarray(fwd_high, float)
    fwd_low = np.asarray(fwd_low, float)
    fwd_close = np.asarray(fwd_close, float)
    n = min(max_hold, len(fwd_close))

    if side == 1:
        target = entry + target_R * stop_dist
        stop = entry - stop_dist
        for i in range(n):
            if fwd_low[i] <= stop:          # conservative: stop checked first
                return -1.0
            if fwd_high[i] >= target:
                return target_R
        return (fwd_close[n - 1] - entry) / stop_dist
    else:
        target = entry - target_R * stop_dist
        stop = entry + stop_dist
        for i in range(n):
            if fwd_high[i] >= stop:
                return -1.0
            if fwd_low[i] <= target:
                return target_R
        return (entry - fwd_close[n - 1]) / stop_dist


# ---------------------------------------------------------------------------
# Layer 2 — statistics
# ---------------------------------------------------------------------------

def clustered_se(r, symbols) -> float:
    """Symbol-clustered (cluster-robust) SE of the mean of R.

    var(mean) = (1/N^2) * sum_g (sum_{i in g} (r_i - mean))^2
    Complements Newey-West: cluster = symbol-weighted, NW = trade-weighted.
    """
    r = np.asarray(r, float)
    symbols = np.asarray(symbols)
    n = len(r)
    if n == 0:
        return np.nan
    e = r - r.mean()
    var = 0.0
    for g in np.unique(symbols):
        var += e[symbols == g].sum() ** 2
    return np.sqrt(var) / n


def newey_west_se(r_time_ordered, L: int) -> float:
    """Newey-West (Bartlett kernel, bandwidth L) HAC SE of the mean.

    Pass the per-trade R series ORDERED BY ENTRY TIME; use L = hold - 1 (the
    forward-window overlap). The Bartlett weight (1 - j/(L+1)) downweights lag j.
    Captures own-series overlap; pair with clustered_se for cross-symbol structure.
    """
    r = np.asarray(r_time_ordered, float)
    n = len(r)
    if n < 2:
        return np.nan
    e = r - r.mean()
    gamma0 = (e @ e) / n
    lrv = gamma0
    for j in range(1, min(L, n - 1) + 1):
        w = 1.0 - j / (L + 1)
        gamma_j = (e[j:] @ e[:-j]) / n
        lrv += 2.0 * w * gamma_j
    lrv = max(lrv, 0.0)              # guard tiny negative from sampling
    return np.sqrt(lrv / n)


def summarize_R(r, symbols=None, entry_order=None, L: int = 9) -> dict:
    """Headline stats for a cell: mean_R, n, clustered + Newey-West SE and t.

    symbols: array for clustered SE (optional). entry_order: index/array to sort
    R by entry time for NW (optional; if None, assumes r is already time-ordered).
    """
    r = np.asarray(r, float)
    out = {"n": int(len(r)), "mean_R": float(np.mean(r)) if len(r) else np.nan}
    if symbols is not None:
        cse = clustered_se(r, symbols)
        out["clustered_se"] = float(cse)
        out["clustered_t"] = float(out["mean_R"] / cse) if cse else np.nan
    r_ord = r[np.argsort(entry_order)] if entry_order is not None else r
    nw = newey_west_se(r_ord, L)
    out["nw_se"] = float(nw)
    out["nw_t"] = float(out["mean_R"] / nw) if nw else np.nan
    return out


def matched_random_benchmark(
    eligible_mask,
    n_signal: int,
    trade_fn,
    rng: np.random.Generator,
    n_draws: int = 1,
):
    """Matched random-entry canary: draw n_signal entries from the SAME eligible
    universe the signal could fire on, run them through `trade_fn(idx) -> R`, and
    return the pooled R array. Expectation ~0.000R; if not, the machinery is
    non-neutral — fix before trusting any cell (README §1).

    eligible_mask: boolean array over candidate entry indices (same filters/spacing
    as the real signal). rng: a seeded numpy Generator (vary the seed by study/index;
    Math.random/Date.now are unavailable in some contexts — seed explicitly).
    """
    eligible_idx = np.flatnonzero(np.asarray(eligible_mask))
    if len(eligible_idx) == 0:
        return np.array([])
    out = []
    for _ in range(n_draws):
        pick = rng.choice(eligible_idx, size=min(n_signal, len(eligible_idx)), replace=False)
        out.extend(trade_fn(i) for i in pick)
    return np.asarray(out, float)
