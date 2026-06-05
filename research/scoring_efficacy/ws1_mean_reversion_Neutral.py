import json
import numpy as np
import pandas as pd

STRATEGY = "mean_reversion"
REGIME = "Neutral"

df = pd.read_csv("/root/BlueHorseshoe/research/scoring_efficacy/dataset.csv")

mask = (df["entered"] == True) & (df["strategy"] == STRATEGY)
if REGIME != "ALL":
    mask &= (df["market_regime"] == REGIME)
sl = df[mask].copy()

n = len(sl)
win_rate = float(sl["win"].mean())
mean_pnl = float(sl["pnl_pct"].mean())

c_cols = [c for c in sl.columns if c.startswith("c_")]
y = sl["pnl_pct"].astype(float)

components = []
for c in c_cols:
    x = sl[c].astype(float)
    if x.var() == 0 or x.isna().all():
        continue
    valid = x.notna() & y.notna()
    xv, yv = x[valid], y[valid]
    if xv.var() == 0 or len(xv) < 5:
        continue
    ic = float(np.corrcoef(xv, yv)[0, 1])
    if np.isnan(ic):
        continue
    nn = len(xv)
    denom = np.sqrt(max(1e-12, 1 - ic**2))
    t = float(ic * np.sqrt(nn - 2) / denom)

    # quintiles
    monotonic = False
    try:
        q = pd.qcut(xv, 5, labels=False, duplicates="drop")
        qmeans = yv.groupby(q).mean().sort_index()
        if len(qmeans) >= 3:
            vals = qmeans.values
            inc = all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))
            dec = all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))
            monotonic = bool(inc or dec)
    except Exception:
        pass

    # ablation: top tercile - bottom tercile
    try:
        tq = pd.qcut(xv, 3, labels=False, duplicates="drop")
        top = yv[tq == tq.max()].mean()
        bot = yv[tq == tq.min()].mean()
        ablation = float(top - bot)
    except Exception:
        ablation = float("nan")

    ablation_pct = ablation * 100 if not np.isnan(ablation) else float("nan")

    sign_agree = (np.sign(ic) == np.sign(ablation)) if not np.isnan(ablation) else False

    if abs(t) > 3 and monotonic and sign_agree:
        verdict = "predictive" if ic > 0 else "anti"
    else:
        verdict = "noise"

    components.append({
        "name": c,
        "ic": round(ic, 4),
        "t_stat": round(t, 3),
        "ablation_pnl_pct": round(ablation_pct, 4) if not np.isnan(ablation_pct) else 0.0,
        "quintile_monotonic": monotonic,
        "verdict": verdict,
    })

components.sort(key=lambda d: -abs(d["t_stat"]))

out = {
    "slice": f"{STRATEGY}/{REGIME}",
    "n": n,
    "base_win_rate": round(win_rate, 4),
    "base_mean_pnl_pct": round(mean_pnl * 100, 4),
    "components": components,
}
print(json.dumps(out, indent=2))
