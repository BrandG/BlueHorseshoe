"""Pure scoring engine for EWF calls — implements SPEC.md §2, §3, §4, §7 exactly.

No I/O here: everything operates on bar arrays. Bars are dicts of aligned numpy
arrays {ts, open, high, low, close, date} sorted by ts (date = per-bar trading
date, used for trading-day window arithmetic on both daily and H1 series).

Outcome vocabulary: win / loss / ambiguous / timeout / no_fill (Type B only).
AMBIGUOUS (target and stop inside the same bar) is its own bucket per SPEC §3:
the primary read scores it -1R, the sensitivity read drops it — both are emitted
so the report never has to re-walk bars.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WINDOWS_TD = (10, 30, 60)  # SPEC §3: 30 primary, 10/60 sensitivities
MIN_RISK_FRAC = 0.001      # SPEC §2: degenerate-bracket gate


# ---------------------------------------------------------------------------
# reference bar location (SPEC §2)
# ---------------------------------------------------------------------------

def ref_bar_equity(bars: dict, pub_ts: pd.Timestamp) -> int | None:
    """First daily-bar open at or after publication.

    A post published before 09:30 America/New_York on a trading day references
    that same day's open; otherwise the next trading day's.
    """
    pub_ny = pub_ts.tz_localize("UTC").tz_convert("America/New_York")
    cand = pub_ny.date() if pub_ny.time() < pd.Timestamp("09:30").time() else pub_ny.date() + pd.Timedelta(days=1)
    idx = np.searchsorted(bars["date"], np.datetime64(pd.Timestamp(cand), "D"))
    return int(idx) if idx < len(bars["date"]) else None


def ref_bar_h1(bars: dict, pub_ts: pd.Timestamp) -> int | None:
    """First H1 bar whose open time is strictly after publication."""
    idx = np.searchsorted(bars["ts"], np.datetime64(pub_ts), side="right")
    return int(idx) if idx < len(bars["ts"]) else None


def forward_trading_days(bars: dict, i0: int) -> int:
    """Distinct trading dates available from i0 onward (including i0's own date)."""
    return int(len(np.unique(bars["date"][i0:])))


def window_end(bars: dict, i0: int, n_td: int) -> int:
    """Index of the last bar inside the n_td-trading-day window starting at i0."""
    dates = bars["date"][i0:]
    uniq = np.unique(dates)
    if len(uniq) <= n_td:
        return len(bars["date"]) - 1
    cutoff = uniq[n_td]  # first date OUTSIDE the window
    return i0 + int(np.searchsorted(dates, cutoff)) - 1


# ---------------------------------------------------------------------------
# invalidation resolution
# ---------------------------------------------------------------------------

def resolve_invalidation(inv, bars: dict) -> float | None:
    """Numeric invalidation, resolving {"type": "date_extreme"} to that date's H/L."""
    if inv is None:
        return None
    if isinstance(inv, (int, float)):
        return float(inv)
    if isinstance(inv, dict) and inv.get("type") == "date_extreme":
        try:
            d = np.datetime64(pd.Timestamp(inv["date"]), "D")
        except (ValueError, KeyError):
            return None
        mask = bars["date"] == d
        if not mask.any():
            return None
        return float(bars["high"][mask].max()) if inv.get("side") == "high" else float(bars["low"][mask].min())
    return None


# ---------------------------------------------------------------------------
# bracket walker (SPEC §3) — ambiguous is a distinct outcome, timeout is clamped
# ---------------------------------------------------------------------------

def walk_bracket(bars: dict, i_start: int, i_end: int, ref: float,
                 target: float, stop: float, side: int) -> dict:
    """Walk bars[i_start..i_end] for a long (side=+1) or short (side=-1) bracket.

    Returns {outcome, R, R_drop_ambiguous, exit_idx}. R uses the SPEC formulas:
    win = |target-ref|/risk, loss = -1, ambiguous = -1 primary (R_drop = nan),
    timeout = side*(close_end - ref)/risk clamped to [-1, win_R].
    """
    risk = abs(stop - ref)
    win_r = abs(target - ref) / risk
    hi, lo, cl = bars["high"], bars["low"], bars["close"]
    for i in range(i_start, i_end + 1):
        hit_t = hi[i] >= target if side == 1 else lo[i] <= target
        hit_s = lo[i] <= stop if side == 1 else hi[i] >= stop
        if hit_t and hit_s:
            return {"outcome": "ambiguous", "R": -1.0, "R_drop_ambiguous": np.nan, "exit_idx": i}
        if hit_s:
            return {"outcome": "loss", "R": -1.0, "R_drop_ambiguous": -1.0, "exit_idx": i}
        if hit_t:
            return {"outcome": "win", "R": win_r, "R_drop_ambiguous": win_r, "exit_idx": i}
    r = float(np.clip(side * (cl[i_end] - ref) / risk, -1.0, win_r))
    return {"outcome": "timeout", "R": r, "R_drop_ambiguous": r, "exit_idx": i_end}


# ---------------------------------------------------------------------------
# Type A — directional (SPEC §1-§3)
# ---------------------------------------------------------------------------

def score_type_a(bars: dict, i0: int, ref: float, direction: str,
                 targets: list[float], inv: float) -> dict:
    """Score a directional call at every window; primary target = nearest to ref."""
    side = 1 if direction == "long" else -1
    tgts = sorted((float(t) for t in targets), key=lambda t: abs(t - ref))
    primary, farthest = tgts[0], tgts[-1]

    # SPEC §2 sanity gates
    if side * (primary - ref) <= 0 or side * (ref - inv) <= 0:
        return {"unscoreable": "levels-inconsistent"}
    if abs(inv - ref) < MIN_RISK_FRAC * ref:
        return {"unscoreable": "levels-inconsistent"}

    out = {"ref": ref, "risk": abs(inv - ref)}
    for w in WINDOWS_TD:
        iw = window_end(bars, i0, w)
        res = walk_bracket(bars, i0, iw, ref, primary, inv, side)
        out[f"outcome_{w}"] = res["outcome"]
        out[f"R_{w}"] = res["R"]
        out[f"R_{w}_drop_ambig"] = res["R_drop_ambiguous"]
        if farthest != primary:  # SPEC §1 sensitivity: farthest target
            out[f"R_{w}_far"] = walk_bracket(bars, i0, iw, ref, farthest, inv, side)["R"]
    return out


# ---------------------------------------------------------------------------
# Type B — zone_reaction (SPEC §7 addendum)
# ---------------------------------------------------------------------------

def score_type_b(bars: dict, i0: int, ref: float, direction: str,
                 zone: list[float], pivot: float, targets: list[float]) -> dict:
    """Two-leg Blue Box call: touched-limit fill at nearest zone edge, stop=pivot,
    checkpoints +1R / +2R. The outcome walk runs to the SAME window end as the
    fill window (fixed total horizon per call; late fills have less room —
    reported via fill_idx so the tail is auditable)."""
    side = 1 if direction == "long" else -1
    lo_e, hi_e = (min(zone), max(zone)) if len(zone) >= 2 else (float(zone[0]), float(zone[0]))
    edge = hi_e if abs(hi_e - ref) <= abs(lo_e - ref) else lo_e

    # pivot must sit beyond the entry edge on the anti-direction side
    if side * (edge - pivot) <= 0:
        return {"unscoreable": "levels-inconsistent"}
    risk = abs(edge - pivot)
    if risk < MIN_RISK_FRAC * edge:
        return {"unscoreable": "levels-inconsistent"}

    out = {"ref": ref, "entry_edge": edge, "risk": risk}
    hi, lo = bars["high"], bars["low"]
    for w in WINDOWS_TD:
        iw = window_end(bars, i0, w)
        fill = None
        for i in range(i0, iw + 1):
            if lo[i] <= edge <= hi[i]:
                fill = i
                break
        if fill is None:
            out[f"outcome_{w}"] = "no_fill"
            out[f"R_{w}"] = np.nan
            out[f"R_{w}_drop_ambig"] = np.nan
            continue
        out[f"fill_idx_{w}"] = fill
        for k in (1, 2):  # +1R primary, +2R secondary checkpoints
            res = walk_bracket(bars, fill, iw, edge, edge + side * k * risk, pivot, side)
            suf = "" if k == 1 else "_2r"
            out[f"outcome_{w}{suf}"] = res["outcome"]
            out[f"R_{w}{suf}"] = res["R"]
            out[f"R_{w}{suf}_drop_ambig"] = res["R_drop_ambiguous"]
        if targets:  # stated reaction target: also score as §3 with ref = edge
            t = sorted((float(t) for t in targets), key=lambda t: abs(t - edge))[0]
            if side * (t - edge) > 0:
                out[f"R_{w}_stated"] = walk_bracket(bars, fill, iw, edge, t, pivot, side)["R"]
    return out


# ---------------------------------------------------------------------------
# nulls (SPEC §4) — same geometry, direction replaced
# ---------------------------------------------------------------------------

def trend_direction(bars: dict, i0: int, n_td: int = 20) -> str | None:
    """Sign of the trailing n_td-trading-day close return at reference."""
    if i0 == 0:
        return None
    dates = bars["date"][:i0]
    uniq = np.unique(dates)
    if len(uniq) < n_td + 1:
        return None
    start_date = uniq[-(n_td + 1)]
    j = int(np.searchsorted(dates, start_date))
    ret = bars["close"][i0 - 1] / bars["close"][j] - 1.0
    if ret == 0:
        return None
    return "long" if ret > 0 else "short"


def random_direction(post_id: int) -> str:
    """Deterministic coin flip seeded by post id (SPEC §4b)."""
    return "long" if (post_id * 2654435761) % (2**32) & 1 else "short"


def null_type_a(bars: dict, i0: int, ref: float, direction: str,
                target_dist: float, inv_dist: float) -> float:
    """Type A null: same |target-ref| and |inv-ref|, direction replaced. 30td R."""
    side = 1 if direction == "long" else -1
    iw = window_end(bars, i0, 30)
    return walk_bracket(bars, i0, iw, ref, ref + side * target_dist, ref - side * inv_dist, side)["R"]


def null_type_b(bars: dict, i0: int, edge: float, risk: float, direction: str) -> float:
    """Type B null: same entry edge and risk distance, reaction direction replaced
    (stop mirrored to the anti-direction side of the edge). +1R checkpoint, 30td.
    Returns nan on no-fill (matches the real call's no-fill treatment)."""
    side = 1 if direction == "long" else -1
    iw = window_end(bars, i0, 30)
    hi, lo = bars["high"], bars["low"]
    fill = next((i for i in range(i0, iw + 1) if lo[i] <= edge <= hi[i]), None)
    if fill is None:
        return np.nan
    return walk_bracket(bars, fill, iw, edge, edge + side * risk, edge - side * risk, side)["R"]
