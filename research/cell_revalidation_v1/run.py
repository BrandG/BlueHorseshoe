"""Per-cell re-adjudication of the mid-entry quarantine (cell_revalidation_v1).

Replays each quarantined-strategy cell over the full H4 history, mirroring the live
trader's signal + geometry exactly, brackets the outcome in R, costs the spread from the
data, and runs the R series through the project's clean stats harness. Emits a per-cell
RESTORE / HOLD / INSUFFICIENT verdict at the BUD bar (profitable after costs in
full ∧ A ∧ B ∧ holdout, plus an expectancy-CI gate).

Read-only. Writes only this study's scorecard.csv. Touches nothing in the live path.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# --- import wiring -------------------------------------------------------------
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "research"))  # _lib is a package here

from bud.briefing import (  # noqa: E402
    CELLS,
    LOOKBACK_BARS,
    cell_uses_long_mr_exit,
    compute_entry_stop_target,
    evaluate_cell,
)
from bh_ftmo.data.fx_store import FxStore  # noqa: E402
from bh_ftmo.indicators.volatility import bollinger_bands, atr  # noqa: E402
from bh_ftmo.indicators.momentum import rsi, cci, stochastic  # noqa: E402
from bh_ftmo.indicators.trend import sma, ema  # noqa: E402
from _lib import harness as H  # noqa: E402

# Strategies paused as a class by the live QUARANTINED_STRATEGIES set (auto_trader.py:81).
QUARANTINED = frozenset({"stoch", "bb", "sma", "ema", "rsi", "cci"})
# Currently-trading strategies — run as a control so a null is distinguishable from a bug.
ACTIVE = frozenset({"atr", "macd", "ichimoku"})

# Hold caps (calendar days) — long-MR mid-longs are 10d, the global v2 default is 14d.
# Mirrors briefing.LONG_MR_MAX_HOLD_DAYS and the "14d v2 default" note at briefing.py:522.
LONG_MR_HOLD_DAYS = 10
V2_DEFAULT_HOLD_DAYS = 14
BARS_PER_DAY = 6  # H4 → 6 bars / 24h; used only for the Newey-West bandwidth L=hold-1
HOLDOUT_MONTHS = 24
GRAN = "H4"


def _mid_frame(raw: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    """Build the live-style mid OHLC frame + spread arrays from bid/ask bars."""
    raw = raw[raw["is_complete"]].reset_index(drop=True)
    o = (raw["open_bid"] + raw["open_ask"]) / 2.0
    h = (raw["high_bid"] + raw["high_ask"]) / 2.0
    low = (raw["low_bid"] + raw["low_ask"]) / 2.0
    c = (raw["close_bid"] + raw["close_ask"]) / 2.0
    mid = pd.DataFrame({"open": o, "high": h, "low": low, "close": c})
    ts = raw["timestamp"].values.astype("datetime64[ns]")
    spread = (raw["close_ask"] - raw["close_bid"]).abs().values
    return mid, ts, spread, c.values


def _hold_days(cell) -> int:
    return LONG_MR_HOLD_DAYS if cell_uses_long_mr_exit(cell) else V2_DEFAULT_HOLD_DAYS


# --- vectorized fire detection (1× indicator compute, not per-bar) -------------
# Mirrors briefing.py's _*_fired exactly, reusing the SAME indicator functions over the
# full series. Causal indicators give bar-i values identical to the live 300-bar window,
# so the only reimplemented part is the (vectorized) fresh-trigger comparison. A fidelity
# assertion against live evaluate_cell guards any divergence. Strategies without a
# vectorized path (atr/macd/ichimoku/candle) fall back to the per-bar loop.
def _fresh(cond: np.ndarray) -> np.ndarray:
    """cond[i] true AND cond[i-1] false (fresh edge); index 0 is False."""
    out = cond.copy()
    out[1:] = cond[1:] & ~cond[:-1]
    out[0] = False
    return out


def _rolling_all(b: np.ndarray, w: int) -> np.ndarray:
    """acc[i] = b[i] & b[i-1] & ... & b[i-w+1] (w small)."""
    acc = b.copy()
    for j in range(1, w):
        acc[j:] = acc[j:] & b[:-j]
        acc[:j] = False
    return acc


def _osc_mask(arr: np.ndarray, threshold: float, recovery: int, direction: str,
              signed: bool) -> np.ndarray:
    n = len(arr)
    long_base = -threshold if signed else threshold
    short_base = threshold if signed else 100.0 - threshold
    rising = np.zeros(n, bool)
    rising[1:] = arr[1:] > arr[:-1]
    falling = np.zeros(n, bool)
    falling[1:] = arr[1:] < arr[:-1]
    base = np.full(n, np.nan)
    if recovery < n:
        base[recovery:] = arr[:-recovery]
    ok = ~np.isnan(base) & ~np.isnan(arr)
    if direction == "long":
        cond = _rolling_all(rising, recovery) & (base < long_base) & ok
    else:
        cond = _rolling_all(falling, recovery) & (base > short_base) & ok
    return _fresh(cond)


def fire_mask(cell, mid: pd.DataFrame) -> np.ndarray | None:
    """Boolean fire array over all bars, or None if strategy isn't vectorized."""
    p, d = cell.params, cell.direction
    close = mid["close"].to_numpy(float)
    if cell.strategy == "bb":
        bb = bollinger_bands(mid, period=p["period"], n_std=p["n_std"])
        lower = bb["lower"].to_numpy(float)
        upper = bb["upper"].to_numpy(float)
        bw = upper - lower
        if d == "long":
            t = lower - float(p["depth"]) * bw
            cond = (close < t) & ~np.isnan(t)
        else:
            t = upper + float(p["depth"]) * bw
            cond = (close > t) & ~np.isnan(t)
        return _fresh(cond)
    if cell.strategy == "stoch":
        arr = stochastic(mid, k_period=p["k_period"], d_period=p["d_period"])["k"].to_numpy(float)
        return _osc_mask(arr, float(p["threshold"]), int(p["recovery"]), d, signed=False)
    if cell.strategy == "rsi":
        arr = rsi(mid, period=p["period"]).to_numpy(float)
        return _osc_mask(arr, float(p["threshold"]), int(p["recovery"]), d, signed=False)
    if cell.strategy == "cci":
        arr = cci(mid, period=p["period"]).to_numpy(float)
        return _osc_mask(arr, float(p["threshold"]), int(p["recovery"]), d, signed=True)
    if cell.strategy in ("sma", "ema"):
        ma_fn = sma if cell.strategy == "sma" else ema
        ma = ma_fn(mid, period=p["period"]).to_numpy(float)
        a = atr(mid, period=p["atr_period"]).to_numpy(float)
        k = float(p["k"])
        ok = ~np.isnan(close) & ~np.isnan(ma) & ~np.isnan(a)
        if d == "long":
            cond = (close < ma - k * a) & ok
        else:
            cond = (close > ma + k * a) & ok
        return _fresh(cond)
    return None


def fidelity_mismatches(cell, mid: pd.DataFrame, mask: np.ndarray, rng,
                        sample: int = 150) -> tuple[int, int, list]:
    """Compare the vectorized mask to live evaluate_cell on sampled bars.

    Returns (n_seed, n_logic, details). A mismatch is classified 'seed' when the mask
    agrees with evaluate_cell run on the FULL-series window (so the only disagreement is
    the recursive-indicator seed: live uses a 300-bar window, vectorized uses full history)
    — immaterial. 'logic' means it disagrees with full-series too — a real bug to fix.
    """
    n = len(mid)
    idxs = rng.choice(np.arange(LOOKBACK_BARS, n), size=min(sample, n - LOOKBACK_BARS), replace=False)
    n_seed = n_logic = 0
    details = []
    for i in idxs:
        i = int(i)
        live_win = bool(evaluate_cell(cell, mid.iloc[i - LOOKBACK_BARS + 1 : i + 1]))
        if bool(mask[i]) == live_win:
            continue
        live_full = bool(evaluate_cell(cell, mid.iloc[: i + 1]))
        if bool(mask[i]) == live_full:
            n_seed += 1
        else:
            n_logic += 1
            details.append((cell.strategy, cell.pair, i, bool(mask[i]), live_win, live_full))
    return n_seed, n_logic, details


def replay_cell(cell, mid: pd.DataFrame, ts: np.ndarray, spread: np.ndarray) -> list[dict]:
    """Walk bars forward, fire the cell, bracket each fire in R (raw + spread-net)."""
    n = len(mid)
    hold_days = _hold_days(cell)
    side = 1 if cell.direction == "long" else -1
    horizon = np.timedelta64(hold_days, "D")
    hi = mid["high"].values
    lo = mid["low"].values
    cl = mid["close"].values
    mask = fire_mask(cell, mid)
    if mask is not None:
        fire_idx = [i for i in np.flatnonzero(mask) if LOOKBACK_BARS <= i < n - 1]
    else:  # fallback: per-bar live evaluation (atr/macd/ichimoku/candle)
        fire_idx = [i for i in range(LOOKBACK_BARS, n - 1)
                    if evaluate_cell(cell, mid.iloc[i - LOOKBACK_BARS + 1 : i + 1])]

    rows: list[dict] = []
    for i in fire_idx:
        window = mid.iloc[i - LOOKBACK_BARS + 1 : i + 1]
        entry, stop, target = compute_entry_stop_target(cell, window)
        stop_dist = abs(entry - stop)
        if stop_dist <= 0:
            continue
        target_R = abs(target - entry) / stop_dist

        if cell.entry_mode == "mid":
            entry_idx, fwd_start = i, i + 1
        else:  # limit order resting for the next bar only (GTD)
            j = i + 1
            touched = (lo[j] <= entry) if side == 1 else (hi[j] >= entry)
            if not touched:
                continue
            entry_idx, fwd_start = j, j  # fill bar's own path is fair game (stop-first)

        if fwd_start >= n:
            continue
        within = (ts[fwd_start:] - ts[entry_idx]) <= horizon
        k = fwd_start + int(within.sum())
        if k <= fwd_start:
            continue
        r_raw = H.bracket_trade(
            hi[fwd_start:k], lo[fwd_start:k], cl[fwd_start:k],
            entry, stop_dist, target_R=target_R, max_hold=k - fwd_start, side=side,
        )
        if np.isnan(r_raw):
            continue
        cost_R = spread[entry_idx] / stop_dist
        rows.append({
            "entry_ts": pd.Timestamp(ts[entry_idx]),
            "symbol": cell.pair,
            "R_raw": float(r_raw),
            "R_net": float(r_raw - cost_R),
        })
    return rows


def _cell_geometry(cell) -> tuple[float, float]:
    """(stop_pct, target_R) matching compute_entry_stop_target's pct geometry."""
    if cell_uses_long_mr_exit(cell):
        return 0.010, 0.015 / 0.010  # long-MR: SL 1.0%, TP 1.5%
    return 0.010, 1.0               # global v2: 1%/1%


def matched_canary(cell, mid: pd.DataFrame, ts: np.ndarray, rng, n_signal: int) -> float:
    """Random-entry pooled mean R with the cell's *matched* geometry/side/hold.

    Reads ~0 on a driftless series; a positive value means the pair drifted in the
    cell's direction over the sample (beta the cell can't claim as timing edge).
    """
    if n_signal == 0:
        return np.nan
    n = len(mid)
    hold_days = _hold_days(cell)
    side = 1 if cell.direction == "long" else -1
    horizon = np.timedelta64(hold_days, "D")
    hi, lo, cl = mid["high"].values, mid["low"].values, mid["close"].values
    stop_pct, target_R = _cell_geometry(cell)
    eligible = np.arange(LOOKBACK_BARS, n - 1)

    def trade_fn(idx: int) -> float:
        entry = cl[idx]
        stop_dist = stop_pct * entry
        within = (ts[idx + 1:] - ts[idx]) <= horizon
        k = idx + 1 + int(within.sum())
        if k <= idx + 1:
            return np.nan
        return H.bracket_trade(
            hi[idx + 1:k], lo[idx + 1:k], cl[idx + 1:k],
            entry, stop_dist, target_R=target_R, max_hold=k - (idx + 1), side=side,
        )

    draws = rng.choice(eligible, size=min(n_signal * 20, len(eligible)), replace=True)
    rs = np.array([trade_fn(int(j)) for j in draws], float)
    rs = rs[~np.isnan(rs)]
    return float(rs.mean()) if len(rs) else np.nan


def adjudicate(rows: list[dict], hold_days: int, holdout_cut: pd.Timestamp, min_n: int) -> dict:
    df = pd.DataFrame(rows).sort_values("entry_ts").reset_index(drop=True)
    n = len(df)
    out = {"n": n, "fires": n}
    if n == 0:
        out["verdict"] = "NO_FIRES"
        return out
    L = max(1, hold_days * BARS_PER_DAY - 1)
    net = df["R_net"].values
    sym = df["symbol"].values
    full = H.summarize_R(net, symbols=sym, L=L)
    se = max(full.get("nw_se", np.nan), full.get("clustered_se", np.nan))
    ci_low = full["mean_R"] - 1.96 * se

    q = df["entry_ts"].dt.year * 4 + (df["entry_ts"].dt.month - 1) // 3
    in_s = df[df["entry_ts"] < holdout_cut]
    hold = df[df["entry_ts"] >= holdout_cut]
    a = in_s[q[in_s.index] % 2 == 0]["R_net"]
    b = in_s[q[in_s.index] % 2 == 1]["R_net"]

    out.update({
        "sum_R_raw": float(df["R_raw"].sum()),
        "sum_R_net": float(df["R_net"].sum()),
        "mean_R_raw": float(df["R_raw"].mean()),
        "mean_R_net": float(full["mean_R"]),
        "spread_delta": float(df["R_raw"].mean() - full["mean_R"]),
        "nw_t": float(full.get("nw_t", np.nan)),
        "clustered_t": float(full.get("clustered_t", np.nan)),
        "ci_low": float(ci_low),
        "n_A": int(len(a)), "mean_A": float(a.mean()) if len(a) else np.nan,
        "n_B": int(len(b)), "mean_B": float(b.mean()) if len(b) else np.nan,
        "n_hold": int(len(hold)), "mean_hold": float(hold["R_net"].mean()) if len(hold) else np.nan,
    })
    if n < min_n or len(a) == 0 or len(b) == 0 or len(hold) == 0:
        out["verdict"] = "INSUFFICIENT"
    else:
        profitable = (full["mean_R"] > 0 and a.mean() > 0 and b.mean() > 0 and hold["R_net"].mean() > 0)
        out["verdict"] = "RESTORE" if (profitable and ci_low > 0) else "HOLD"
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="last 2500 bars only (wiring check)")
    ap.add_argument("--include-active", action="store_true", help="also run atr/macd/ichimoku control")
    ap.add_argument("--min-n", type=int, default=20, help="min fires to adjudicate (else INSUFFICIENT)")
    ap.add_argument("--seed", type=int, default=20260625)
    args = ap.parse_args()

    strategies = QUARANTINED | (ACTIVE if args.include_active else frozenset())
    cells = [c for c in CELLS if c.strategy in strategies]
    pairs = sorted({c.pair for c in cells})
    rng = np.random.default_rng(args.seed)

    store = FxStore(read_only=True)
    cov = store.coverage(granularity=GRAN)
    max_ts = max(c.max_timestamp for c in cov.values() if c.symbol in pairs)
    holdout_cut = pd.Timestamp(max_ts) - pd.DateOffset(months=HOLDOUT_MONTHS)
    print(f"# cells={len(cells)}  pairs={len(pairs)}  holdout_cut={holdout_cut.date()}  "
          f"max_ts={pd.Timestamp(max_ts).date()}  smoke={args.smoke}")

    results = []
    by_pair: dict[str, tuple] = {}
    for pair in pairs:
        raw = store.load(pair, granularity=GRAN)
        if args.smoke:
            raw = raw.tail(2500)
        if len(raw) <= LOOKBACK_BARS + 2:
            print(f"  ! {pair}: only {len(raw)} bars — skipping")
            continue
        by_pair[pair] = _mid_frame(raw)
    store.close()

    seed_total = logic_total = 0
    logic_details = []
    for cell in cells:
        if cell.pair not in by_pair:
            continue
        mid, ts, spread, _ = by_pair[cell.pair]
        vmask = fire_mask(cell, mid)
        if vmask is not None:
            n_seed, n_logic, det = fidelity_mismatches(cell, mid, vmask, rng)
            seed_total += n_seed
            logic_total += n_logic
            logic_details += det
        rows = replay_cell(cell, mid, ts, spread)
        res = adjudicate(rows, _hold_days(cell), holdout_cut, args.min_n)
        res["canary_R"] = matched_canary(cell, mid, ts, rng, res.get("fires", 0))
        mean_net = res.get("mean_R_net", np.nan)
        res["edge_vs_canary"] = float(mean_net - res["canary_R"]) if pd.notna(mean_net) else np.nan
        # worse-than-random is the one random concern (research/README.md): a cell that
        # otherwise passes but sits below its own matched-random baseline is drift, not edge.
        if res.get("verdict") == "RESTORE" and pd.notna(res["edge_vs_canary"]) \
                and res["edge_vs_canary"] <= 0:
            res["verdict"] = "DRIFT"
        res.update({"strategy": cell.strategy, "pair": cell.pair,
                    "direction": cell.direction, "entry_mode": cell.entry_mode,
                    "quarantined": cell.strategy in QUARANTINED})
        results.append(res)

    df = pd.DataFrame(results)
    if df.empty:
        print("no results")
        return
    cols = ["strategy", "pair", "direction", "entry_mode", "quarantined", "n",
            "mean_R_net", "spread_delta", "ci_low", "nw_t", "mean_A", "mean_B",
            "mean_hold", "canary_R", "edge_vs_canary", "verdict"]
    df = df.sort_values(["quarantined", "strategy", "verdict"], ascending=[False, True, True])
    pd.set_option("display.width", 200, "display.max_columns", 40)
    print(df[cols].to_string(index=False, float_format=lambda x: f"{x:6.3f}"))

    out = Path(__file__).resolve().parent / "scorecard.csv"
    df.to_csv(out, index=False)
    print(f"\nwrote {out}")
    print(f"fidelity: seed-noise mismatches={seed_total} (benign, recursive-indicator seed), "
          f"logic mismatches={logic_total} ({'CLEAN' if logic_total == 0 else 'BUG — FIX'})")
    for s, p, i, m, lw, lf in logic_details[:10]:
        print(f"    LOGIC {s} {p} bar={i} mask={m} live_win={lw} live_full={lf}")
    print("\nRESTORE candidates (quarantined, passed the BUD bar after costs):")
    keep = df[(df["quarantined"]) & (df["verdict"] == "RESTORE")]
    print("  " + (", ".join(f"{r.strategy}:{r.pair}:{r.direction}" for r in keep.itertuples())
                  or "(none)"))


if __name__ == "__main__":
    main()
