"""short_discovery_trend_v1 — SHORT edge of the trend/breakout families (atr, macd, ichimoku).

short_discovery_v1 covered the mean-reversion families and found the short well mostly dry beyond
known cells. Trend/breakout families fire on actual DOWNTRENDS — the directional bear setups that
balance a long book. This scans their short direction across the curated universe.

Same rigor as v1: bracketed R net of spread (1%/1%/14d), A/B/holdout, expectancy-CI, matched-random
-short control. These families are limit-entry and not vectorized in fx_replay, so masks are ported
here from briefing._{atr,macd,ichimoku}_fired and FIDELITY-CHECKED against the live evaluate_cell.

Read-only. Run: ./run.sh python research/short_discovery_trend_v1/run.py [--smoke]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "research"))

from bud.briefing import CELLS, Cell, LOOKBACK_BARS, evaluate_cell  # noqa: E402
from bh_ftmo.indicators import macd as macd_ind, atr as atr_ind, ichimoku as ichimoku_ind  # noqa: E402
from _lib import fx_replay as FR  # noqa: E402
from _lib import harness as H  # noqa: E402

TP, SL, HOLD_DAYS = 0.010, 0.010, 14
HOLDOUT_MONTHS = 24
LBARS = LOOKBACK_BARS
FAMILIES = ["atr", "macd", "ichimoku"]


def _shift(a):
    out = np.full_like(a, np.nan)
    out[1:] = a[:-1]
    return out


def _fresh(cond):
    out = cond.copy()
    out[1:] = cond[1:] & ~cond[:-1]
    out[0] = False
    return out


def trend_mask(cell, mid):
    """Vectorized short/long fire mask mirroring briefing._{atr,macd,ichimoku}_fired."""
    p, d = cell.params, cell.direction
    o = mid["open"].to_numpy(float); hi = mid["high"].to_numpy(float)
    lo = mid["low"].to_numpy(float); cl = mid["close"].to_numpy(float)
    if cell.strategy == "macd":
        m = macd_ind(mid, fast=p["fast"], slow=p["slow"], signal=p["signal"])
        ma = m["macd"].to_numpy(float); sg = m["signal"].to_numpy(float)
        ma1, sg1 = _shift(ma), _shift(sg)
        ok = ~np.isnan(ma) & ~np.isnan(ma1)
        if p["trigger"] == "signal_cross":
            ok &= ~np.isnan(sg) & ~np.isnan(sg1)
            cond = (ma < sg) & (ma1 >= sg1) if d == "short" else (ma > sg) & (ma1 <= sg1)
        else:  # zero_cross
            cond = (ma < 0) & (ma1 >= 0) if d == "short" else (ma > 0) & (ma1 <= 0)
        return cond & ok  # macd fires directly on the cross (no fresh-wrap)
    if cell.strategy == "ichimoku":
        ich = ichimoku_ind(mid, tenkan_period=p["tenkan"], kijun_period=p["kijun"],
                           senkou_b_period=p["senkou_b"], displacement=p["displacement"])
        tk = ich["tenkan"].to_numpy(float); kj = ich["kijun"].to_numpy(float)
        tk1, kj1 = _shift(tk), _shift(kj)
        ok = ~np.isnan(tk) & ~np.isnan(kj) & ~np.isnan(tk1) & ~np.isnan(kj1)
        if p.get("trigger") != "tk_cross":
            return np.zeros(len(cl), bool)
        cond = (tk < kj) & (tk1 >= kj1) if d == "short" else (tk > kj) & (tk1 <= kj1)
        return cond & ok
    if cell.strategy == "atr":
        k = float(p["k"])
        if p["trigger"] == "close_breakout":
            a = atr_ind(mid, period=p["atr_period"]).to_numpy(float)
            a1, cl1 = _shift(a), _shift(cl)
            ok = ~np.isnan(cl1) & ~np.isnan(a1)
            cond = (cl < cl1 - k * a1) if d == "short" else (cl > cl1 + k * a1)
            return _fresh(cond & ok)
        # range_expansion
        lookback = int(p.get("range_lookback", 14))
        rng = hi - lo
        mean_rng = pd.Series(rng).rolling(lookback, min_periods=lookback).mean().to_numpy()
        mr1 = _shift(mean_rng)
        ok = ~np.isnan(mr1)
        big = rng > k * mr1
        directional = (cl < o) if d == "short" else (cl > o)
        return _fresh(big & directional & ok)
    return np.zeros(len(cl), bool)


def fidelity(cell, mid, mask, rng, sample=120):
    n = len(mid)
    idxs = rng.choice(np.arange(LBARS, n), size=min(sample, n - LBARS), replace=False)
    seed = logic = 0
    for i in idxs:
        i = int(i)
        win = bool(evaluate_cell(cell, mid.iloc[i - LBARS + 1:i + 1]))
        if bool(mask[i]) == win:
            continue
        full = bool(evaluate_cell(cell, mid.iloc[:i + 1]))
        if bool(mask[i]) == full:
            seed += 1
        else:
            logic += 1
    return seed, logic


def fire_events(cell, P, mask):
    mid = P["mid_df"]; hi = P["hi"]; lo = P["lo"]; ts = P["ts"]; spread = P["spread"]; n = len(mid)
    side = 1 if cell.direction == "long" else -1
    idxs = [i for i in np.flatnonzero(mask) if LBARS <= i < n - 1]
    out = []
    for i in idxs:
        if cell.entry_mode == "mid":
            entry = float(mid["close"].iloc[i]); ei, fs = i, i + 1
        else:  # limit: rest at trigger bar low (long) / high (short) for next bar
            entry = float(mid["low"].iloc[i] if side == 1 else mid["high"].iloc[i])
            j = i + 1
            if j >= n:
                continue
            if not ((lo[j] <= entry) if side == 1 else (hi[j] >= entry)):
                continue
            ei, fs = j, j
        out.append({"entry_idx": ei, "fwd_start": fs, "entry": entry,
                    "entry_ts": pd.Timestamp(ts[ei]), "spread": float(spread[ei])})
    return out


def bracket_short(P, ev):
    hi, lo, cl, ts = P["hi"], P["lo"], P["cl"], P["ts"]
    entry, fs, ei = ev["entry"], ev["fwd_start"], ev["entry_idx"]
    sd = SL * entry
    if sd <= 0:
        return None
    tR = TP / SL
    k = fs + int(((ts[fs:] - ts[ei]) <= np.timedelta64(HOLD_DAYS, "D")).sum())
    if k <= fs:
        return None
    target, stop, R = entry - tR * sd, entry + sd, None
    for j in range(fs, k):
        if hi[j] >= stop:
            R = -1.0; break
        if lo[j] <= target:
            R = tR; break
    if R is None:
        R = (entry - cl[k - 1]) / sd
    return R - ev["spread"] / sd


def random_short(P, rng, n_target, since=None):
    n = len(P["cl"]); ts = P["ts"]
    elig = np.arange(LBARS, n - 1)
    if since is not None:
        elig = elig[ts[elig] >= np.datetime64(since)]
    if len(elig) == 0:
        return np.nan
    rs = []
    for i in rng.choice(elig, size=min(max(400, n_target * 20), len(elig)), replace=True):
        i = int(i)
        out = bracket_short(P, {"entry": float(P["cl"][i]), "fwd_start": i + 1, "entry_idx": i,
                                "spread": float(P["spread"][i])})
        if out is not None:
            rs.append(out)
    return float(np.mean(rs)) if rs else np.nan


def representative(strategy):
    for c in CELLS:
        if c.strategy == strategy:
            return dict(c.params), c.entry_mode
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--min-n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=20260626)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    universe = sorted({c.pair for c in CELLS})
    P_by_pair = FR.load_pairs(universe, smoke=args.smoke)
    universe = [p for p in universe if p in P_by_pair]
    max_ts = max(pd.Timestamp(P["ts"][-1]) for P in P_by_pair.values())
    holdout_cut = max_ts - pd.DateOffset(months=HOLDOUT_MONTHS)
    print(f"# trend short discovery families={FAMILIES} pairs={len(universe)} "
          f"holdout_cut={holdout_cut.date()} smoke={args.smoke}")

    seed_tot = logic_tot = 0
    rows = []
    for fam in FAMILIES:
        tmpl = representative(fam)
        if tmpl is None:
            continue
        params, emode = tmpl
        for pair in universe:
            P = P_by_pair[pair]
            cell = Cell(fam, pair, "short", emode, params)
            mid = P["mid_df"]
            mask = trend_mask(cell, mid)
            s, l = fidelity(cell, mid, mask, rng)
            seed_tot += s; logic_tot += l
            recs = []
            for e in fire_events(cell, P, mask):
                r = bracket_short(P, e)
                if r is not None:
                    recs.append((e["entry_ts"], r))
            if len(recs) < args.min_n:
                continue
            df = pd.DataFrame(recs, columns=["ts", "R"]).sort_values("ts")
            net = df["R"].to_numpy()
            full = H.summarize_R(net, L=HOLD_DAYS * 6 - 1)
            se = max(full.get("nw_se", np.nan), full.get("clustered_se", np.nan))
            ci_low = full["mean_R"] - 1.96 * se
            q = df["ts"].dt.year * 4 + (df["ts"].dt.month - 1) // 3
            ins = df[df["ts"] < holdout_cut]; hod = df[df["ts"] >= holdout_cut]
            a = ins[q[ins.index] % 2 == 0]["R"]; b = ins[q[ins.index] % 2 == 1]["R"]
            rand = random_short(P, rng, len(df))
            edge = full["mean_R"] - rand
            robust = len(a) and len(b) and len(hod) and a.mean() > 0 and b.mean() > 0 and hod["R"].mean() > 0
            passes = bool(full["mean_R"] > 0 and robust and ci_low > 0 and edge > 0)
            verdict = "DISCOVER" if passes else ("promising" if full["mean_R"] > 0 and edge > 0 else "none")
            rows.append({"strategy": fam, "pair": pair, "n": len(df), "mean_R": full["mean_R"],
                         "ci_low": ci_low, "nw_t": full.get("nw_t", np.nan),
                         "A": a.mean() if len(a) else np.nan, "B": b.mean() if len(b) else np.nan,
                         "hold": hod["R"].mean() if len(hod) else np.nan,
                         "rand": rand, "edge": edge, "verdict": verdict})

    print(f"fidelity: seed-noise={seed_tot} logic={logic_tot} "
          f"({'CLEAN' if logic_tot == 0 else 'INVESTIGATE'})")
    df = pd.DataFrame(rows)
    if df.empty:
        print("no candidates met min-n"); return
    df = df.sort_values(["verdict", "edge"], ascending=[True, False])
    pd.set_option("display.width", 230, "display.max_columns", 40)
    cols = ["strategy", "pair", "n", "mean_R", "ci_low", "nw_t", "A", "B", "hold", "rand", "edge", "verdict"]
    print(df[cols].to_string(index=False, float_format=lambda x: f"{x:6.3f}"))
    out = Path(__file__).resolve().parent / "discovery.csv"
    df.to_csv(out, index=False)
    print(f"\nwrote {out}")
    disc = df[df["verdict"] == "DISCOVER"]
    print("\nDISCOVER — deployable short candidates (positive A∧B∧holdout, CI>0, beats random short):")
    for r in disc.itertuples():
        print(f"  {r.strategy}:{r.pair}:short  mean {r.mean_R:.3f}R  edge+{r.edge:.3f}  "
              f"(A {r.A:.3f} B {r.B:.3f} hold {r.hold:.3f}, n={r.n})")
    if disc.empty:
        print("  (none cleared the full gate)")


if __name__ == "__main__":
    main()
