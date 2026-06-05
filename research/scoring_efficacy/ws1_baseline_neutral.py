import json
import numpy as np
import pandas as pd

STRATEGY = "baseline"
REGIME = "Neutral"

df = pd.read_csv("/root/BlueHorseshoe/research/scoring_efficacy/dataset.csv")

# Filter to slice
mask = (df["entered"] == True) & (df["strategy"] == STRATEGY)
if REGIME != "ALL":
    mask &= (df["market_regime"] == REGIME)
d = df[mask].copy()

n = int(len(d))
base_win_rate = float(d["win"].mean())
base_mean_pnl_pct = float(d["pnl_pct"].mean())

ccols = [c for c in d.columns if c.startswith("c_")]

components = []
for c in ccols:
    s = d[c]
    if s.isna().all():
        continue
    if s.nunique(dropna=True) < 2 or s.var(skipna=True) == 0 or np.isnan(s.var(skipna=True)):
        continue
    sub = d[[c, "pnl_pct"]].dropna()
    if len(sub) < 10:
        continue
    x = sub[c].values
    y = sub["pnl_pct"].values
    if np.std(x) == 0:
        continue
    ic = float(np.corrcoef(x, y)[0, 1])
    nn = len(sub)
    if abs(ic) >= 1.0:
        t = float("inf")
    else:
        t = float(ic * np.sqrt(nn - 2) / np.sqrt(1 - ic**2))

    # Quintiles
    quintile_monotonic = False
    try:
        q = pd.qcut(sub[c], 5, labels=False, duplicates="drop")
        qmeans = sub.groupby(q)["pnl_pct"].mean().values
        if len(qmeans) >= 3:
            inc = all(qmeans[i] < qmeans[i+1] for i in range(len(qmeans)-1))
            dec = all(qmeans[i] > qmeans[i+1] for i in range(len(qmeans)-1))
            quintile_monotonic = bool(inc or dec)
    except Exception:
        quintile_monotonic = False

    # Ablation: top tercile minus bottom tercile
    try:
        terc = pd.qcut(sub[c], 3, labels=False, duplicates="drop")
        tvals = sorted(terc.dropna().unique())
        if len(tvals) >= 2:
            top = sub.loc[terc == tvals[-1], "pnl_pct"].mean()
            bot = sub.loc[terc == tvals[0], "pnl_pct"].mean()
            ablation = float(top - bot)
        else:
            ablation = float("nan")
    except Exception:
        ablation = float("nan")

    # Classify
    sign_agree = (not np.isnan(ablation)) and (np.sign(ablation) == np.sign(ic)) and ic != 0
    if abs(t) > 3 and quintile_monotonic and sign_agree:
        verdict = "predictive"  # ic positive => higher comp better
    elif abs(t) > 3 and quintile_monotonic and (not np.isnan(ablation)) and ic != 0 and np.sign(ablation) == np.sign(ic) and ic < 0:
        verdict = "anti"
    else:
        verdict = "noise"

    # Refine: predictive requires positive relationship (higher comp -> better pnl); anti = wrong sign
    if abs(t) > 3 and quintile_monotonic and sign_agree:
        verdict = "predictive" if ic > 0 else "anti"
    else:
        verdict = "noise"

    components.append({
        "name": c,
        "ic": round(ic, 6),
        "t_stat": round(t, 4) if np.isfinite(t) else 9999.0,
        "ablation_pnl_pct": round(ablation, 6) if not np.isnan(ablation) else 0.0,
        "quintile_monotonic": quintile_monotonic,
        "verdict": verdict,
    })

# Sort by abs t
components.sort(key=lambda r: abs(r["t_stat"]), reverse=True)

pred = [c["name"] for c in components if c["verdict"] == "predictive"]
anti = [c["name"] for c in components if c["verdict"] == "anti"]
headline = (f"baseline/Neutral n={n}: win_rate={base_win_rate:.1%}, mean_pnl={base_mean_pnl_pct:.3%}. "
            f"predictive={pred or 'none'}; anti={anti or 'none'}.")

out = {
    "slice": "baseline/Neutral",
    "n": n,
    "base_win_rate": round(base_win_rate, 6),
    "base_mean_pnl_pct": round(base_mean_pnl_pct, 6),
    "components": components,
    "headline": headline,
}
print(json.dumps(out, indent=2))
