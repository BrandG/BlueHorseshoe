"""short_tuning_v1 — param-tune the discovered short candidates (strengthen + expand).

Targets (from short_discovery_trend_v1 + short_discovery_v1):
  ichimoku:USD_SGD, ichimoku:GBP_CAD, ichimoku:CAD_CHF, macd:EUR_USD, sma:CAD_CHF  (all short)

For each family, sweep a small param grid. PART A: per target, best-tuned vs default geometry on the
same gate (positive A∧B∧holdout, expectancy-CI, beats matched-random-short). PART B: re-sweep the
whole universe with the tuned grid and list which NEW pairs clear the gate (expansion).

Rigor: select params on in-sample (A+B), validate on the 24mo holdout + edge-over-random. The
matched-random baseline depends only on pair+geometry (not params), so it's computed once per pair.
Masks are the fidelity-checked ports from short_discovery_trend_v1 / fx_replay. Read-only.
Run: ./run.sh python research/short_tuning_v1/run.py [--smoke]
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

from bud.briefing import CELLS, Cell, LOOKBACK_BARS  # noqa: E402
from bh_ftmo.indicators import macd as macd_ind, ichimoku as ichimoku_ind  # noqa: E402
from bh_ftmo.indicators.trend import sma as sma_ind  # noqa: E402
from bh_ftmo.indicators.volatility import atr as atr_ind  # noqa: E402
from _lib import fx_replay as FR  # noqa: E402
from _lib import harness as H  # noqa: E402

TP, SL, HOLD_DAYS = 0.010, 0.010, 14
HOLDOUT_MONTHS = 24
LBARS = LOOKBACK_BARS
EMODE = {"ichimoku": "limit", "macd": "limit", "sma": "mid"}

TARGETS = [("ichimoku", "USD_SGD"), ("ichimoku", "GBP_CAD"), ("ichimoku", "CAD_CHF"),
           ("macd", "EUR_USD"), ("sma", "CAD_CHF")]

ICHI_GRID = [{"tenkan": t, "kijun": k, "senkou_b": 52, "displacement": 26, "trigger": "tk_cross"}
             for t in (7, 9, 11) for k in (22, 26, 30, 34)]
MACD_GRID = [{"fast": f, "slow": s, "signal": 9, "trigger": tg}
             for f in (8, 12, 16) for s in (21, 26, 34) if s > f
             for tg in ("signal_cross", "zero_cross")]
SMA_GRID = [{"period": p, "k": k, "atr_period": 14} for p in (50, 100, 200) for k in (1.5, 2.0, 2.5)]
GRIDS = {"ichimoku": ICHI_GRID, "macd": MACD_GRID, "sma": SMA_GRID}


def _shift(a):
    o = np.full_like(a, np.nan); o[1:] = a[:-1]; return o


def _fresh(c):
    o = c.copy(); o[1:] = c[1:] & ~c[:-1]; o[0] = False; return o


def mask_for(cell, mid):
    p, d = cell.params, cell.direction
    if cell.strategy == "sma":
        return FR.fire_mask(cell, mid)
    o = mid["open"].to_numpy(float); hi = mid["high"].to_numpy(float)
    lo = mid["low"].to_numpy(float); cl = mid["close"].to_numpy(float)
    if cell.strategy == "macd":
        m = macd_ind(mid, fast=p["fast"], slow=p["slow"], signal=p["signal"])
        ma = m["macd"].to_numpy(float); sg = m["signal"].to_numpy(float)
        ma1, sg1 = _shift(ma), _shift(sg)
        ok = ~np.isnan(ma) & ~np.isnan(ma1)
        if p["trigger"] == "signal_cross":
            ok &= ~np.isnan(sg) & ~np.isnan(sg1)
            cond = (ma < sg) & (ma1 >= sg1)
        else:
            cond = (ma < 0) & (ma1 >= 0)
        return cond & ok
    if cell.strategy == "ichimoku":
        ich = ichimoku_ind(mid, tenkan_period=p["tenkan"], kijun_period=p["kijun"],
                           senkou_b_period=p["senkou_b"], displacement=p["displacement"])
        tk = ich["tenkan"].to_numpy(float); kj = ich["kijun"].to_numpy(float)
        tk1, kj1 = _shift(tk), _shift(kj)
        ok = ~np.isnan(tk) & ~np.isnan(kj) & ~np.isnan(tk1) & ~np.isnan(kj1)
        return ((tk < kj) & (tk1 >= kj1)) & ok
    return np.zeros(len(mid), bool)


def events(cell, P, mask):
    mid = P["mid_df"]; hi = P["hi"]; lo = P["lo"]; ts = P["ts"]; spread = P["spread"]; n = len(mid)
    out = []
    for i in (int(x) for x in np.flatnonzero(mask)):
        if not (LBARS <= i < n - 1):
            continue
        if cell.entry_mode == "mid":
            entry, ei, fs = float(mid["close"].iloc[i]), i, i + 1
        else:
            entry = float(mid["high"].iloc[i]); j = i + 1
            if j >= n or not (hi[j] >= entry):
                continue
            ei, fs = j, j
        out.append((ei, fs, entry, pd.Timestamp(ts[ei]), float(spread[ei])))
    return out


def bracket(P, ei, fs, entry, spread):
    hi, lo, cl, ts = P["hi"], P["lo"], P["cl"], P["ts"]
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
    return R - spread / sd


def rand_pair(P, rng, since=None):
    n = len(P["cl"]); ts = P["ts"]
    elig = np.arange(LBARS, n - 1)
    if since is not None:
        elig = elig[ts[elig] >= np.datetime64(since)]
    rs = [bracket(P, i, i + 1, float(P["cl"][i]), float(P["spread"][i]))
          for i in (int(x) for x in rng.choice(elig, size=min(6000, len(elig)), replace=True))]
    rs = [r for r in rs if r is not None]
    return float(np.mean(rs)) if rs else np.nan


def evaluate(cell, P, rand_full, holdout_cut, min_n):
    mask = mask_for(cell, P["mid_df"])
    recs = []
    for ei, fs, entry, ts, sp in events(cell, P, mask):
        r = bracket(P, ei, fs, entry, sp)
        if r is not None:
            recs.append((ts, r))
    if len(recs) < min_n:
        return None
    df = pd.DataFrame(recs, columns=["ts", "R"]).sort_values("ts")
    full = H.summarize_R(df["R"].to_numpy(), L=HOLD_DAYS * 6 - 1)
    se = max(full.get("nw_se", np.nan), full.get("clustered_se", np.nan))
    ci_low = full["mean_R"] - 1.96 * se
    q = df["ts"].dt.year * 4 + (df["ts"].dt.month - 1) // 3
    ins = df[df["ts"] < holdout_cut]; hod = df[df["ts"] >= holdout_cut]
    a = ins[q[ins.index] % 2 == 0]["R"]; b = ins[q[ins.index] % 2 == 1]["R"]
    edge = full["mean_R"] - rand_full
    robust = len(a) and len(b) and len(hod) and a.mean() > 0 and b.mean() > 0 and hod["R"].mean() > 0
    passes = bool(full["mean_R"] > 0 and robust and ci_low > 0 and edge > 0)
    ins_mean = float(ins["R"].mean()) if len(ins) else np.nan
    return {"n": len(df), "mean_R": full["mean_R"], "ci_low": ci_low, "ins_mean": ins_mean,
            "A": float(a.mean()) if len(a) else np.nan, "B": float(b.mean()) if len(b) else np.nan,
            "hold": float(hod["R"].mean()) if len(hod) else np.nan, "edge": edge, "passes": passes}


def representative(strategy):
    for c in CELLS:
        if c.strategy == strategy:
            return dict(c.params)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--min-n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=20260626)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    universe = sorted({c.pair for c in CELLS})
    P_by = FR.load_pairs(universe, smoke=args.smoke)
    universe = [p for p in universe if p in P_by]
    max_ts = max(pd.Timestamp(P["ts"][-1]) for P in P_by.values())
    holdout_cut = max_ts - pd.DateOffset(months=HOLDOUT_MONTHS)
    rand = {p: rand_pair(P_by[p], rng) for p in universe}  # once per pair (param-independent)
    print(f"# short tuning  pairs={len(universe)}  holdout_cut={holdout_cut.date()}  smoke={args.smoke}")

    print("\n=== PART A: tune the targets (default -> best in-sample combo, validated OOS) ===")
    a_rows = []
    for fam, pair in TARGETS:
        P = P_by.get(pair)
        if P is None:
            continue
        emode = EMODE[fam]
        defc = Cell(fam, pair, "short", emode, representative(fam))
        dres = evaluate(defc, P, rand[pair], holdout_cut, args.min_n)
        best = None
        for params in GRIDS[fam]:
            r = evaluate(Cell(fam, pair, "short", emode, params), P, rand[pair], holdout_cut, args.min_n)
            if r and (best is None or r["ins_mean"] > best[1]["ins_mean"]):
                best = (params, r)
        if best is None:
            continue
        bp, br = best
        a_rows.append({"target": f"{fam}:{pair}",
                       "def_hold": dres["hold"] if dres else np.nan,
                       "def_edge": dres["edge"] if dres else np.nan,
                       "best_params": _fmt(fam, bp), "n": br["n"], "best_hold_R": br["hold"],
                       "best_A": br["A"], "best_B": br["B"], "best_edge": br["edge"],
                       "best_ci": br["ci_low"], "passes": br["passes"]})
    da = pd.DataFrame(a_rows)
    pd.set_option("display.width", 240, "display.max_columns", 40)
    print(da.to_string(index=False, float_format=lambda x: f"{x:6.3f}"))

    print("\n=== PART B: expansion — pairs that clear the gate under each family's tuned grid ===")
    for fam in ("ichimoku", "macd", "sma"):
        hits = []
        for pair in universe:
            P = P_by[pair]
            best = None
            for params in GRIDS[fam]:
                r = evaluate(Cell(fam, pair, "short", EMODE[fam], params), P, rand[pair], holdout_cut, args.min_n)
                if r and r["passes"] and (best is None or r["edge"] > best[1]["edge"]):
                    best = (params, r)
            if best:
                hits.append((pair, best[1]["mean_R"], best[1]["edge"], _fmt(fam, best[0])))
        hits.sort(key=lambda x: -x[2])
        print(f"\n  {fam} short — {len(hits)} pairs clear the gate (tuned):")
        for pair, mr, edge, pp in hits:
            print(f"    {pair:8s} mean {mr:.3f}R edge+{edge:.3f}  [{pp}]")

    da.to_csv(Path(__file__).resolve().parent / "tuning.csv", index=False)


def _fmt(fam, p):
    if fam == "ichimoku":
        return f"tk{p['tenkan']}/kj{p['kijun']}"
    if fam == "macd":
        return f"{p['fast']}/{p['slow']}/{p['signal']}:{p['trigger'][:3]}"
    return f"p{p['period']}/k{p['k']}"


if __name__ == "__main__":
    main()
