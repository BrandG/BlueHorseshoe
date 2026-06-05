import pandas as pd
import numpy as np
import json

STRATEGY = "baseline"
REGIME = "ALL"

df = pd.read_csv("/root/BlueHorseshoe/research/scoring_efficacy/dataset.csv")

# Slice filter
m = (df["entered"] == True) & (df["strategy"] == STRATEGY)
if REGIME != "ALL":
    m &= (df["market_regime"] == REGIME)
d = df[m].copy()

n = len(d)
base_win_rate = float(d["win"].mean())
base_mean_pnl = float(d["pnl_pct"].mean())

y = d["pnl_pct"].astype(float)

comp_cols = [c for c in d.columns if c.startswith("c_")]

results = []
for c in comp_cols:
    x = pd.to_numeric(d[c], errors="coerce")
    valid = x.notna() & y.notna()
    xx = x[valid]
    yy = y[valid]
    if xx.nunique() < 2 or xx.std(ddof=0) == 0:
        continue  # zero variance
    nn = len(xx)
    ic = float(np.corrcoef(xx, yy)[0, 1])
    if np.isnan(ic):
        continue
    denom = max(1e-12, 1 - ic * ic)
    t = float(ic * np.sqrt(nn - 2) / np.sqrt(denom))

    # quintile means
    try:
        q = pd.qcut(xx, 5, labels=False, duplicates="drop")
    except Exception:
        q = None
    monotonic = False
    if q is not None and q.nunique() >= 3:
        qm = yy.groupby(q).mean().sort_index()
        vals = qm.values
        inc = all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))
        dec = all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))
        monotonic = bool(inc or dec)

    # tercile ablation
    try:
        ter = pd.qcut(xx, 3, labels=False, duplicates="drop")
    except Exception:
        ter = None
    ablation = float("nan")
    if ter is not None and ter.nunique() >= 2:
        top = ter.max()
        bot = ter.min()
        ablation = float(yy[ter == top].mean() - yy[ter == bot].mean())

    # classify
    verdict = "noise"
    if abs(t) > 3 and monotonic and not np.isnan(ablation):
        ic_sign = np.sign(ic)
        abl_sign = np.sign(ablation)
        if ic_sign == abl_sign and ic_sign != 0:
            # relationship direction: positive ic = higher comp -> better pnl = predictive
            if ic_sign > 0:
                verdict = "predictive"
            else:
                verdict = "anti"
    results.append({
        "name": c,
        "ic": round(ic, 5),
        "t_stat": round(t, 4),
        "ablation_pnl_pct": round(ablation * 100, 5),  # report as percent points
        "quintile_monotonic": monotonic,
        "verdict": verdict,
    })

# sort by |t|
results.sort(key=lambda r: abs(r["t_stat"]), reverse=True)

pred = [r["name"] for r in results if r["verdict"] == "predictive"]
anti = [r["name"] for r in results if r["verdict"] == "anti"]
headline = (f"baseline/ALL n={n}: win={base_win_rate:.3f} meanPnL={base_mean_pnl*100:.3f}%. "
            f"{len(pred)} predictive, {len(anti)} anti, "
            f"{len(results)-len(pred)-len(anti)} noise. "
            f"top predictive={pred[:3]} top anti={anti[:3]}")

out = {
    "slice": f"{STRATEGY}/{REGIME}",
    "n": n,
    "base_win_rate": round(base_win_rate, 5),
    "base_mean_pnl_pct": round(base_mean_pnl * 100, 5),
    "components": results,
    "headline": headline,
}
print(json.dumps(out, indent=2))
