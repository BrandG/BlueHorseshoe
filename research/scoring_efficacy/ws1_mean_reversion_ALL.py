import pandas as pd
import numpy as np
import json

STRATEGY = "mean_reversion"
REGIME = "ALL"

df = pd.read_csv("/root/BlueHorseshoe/research/scoring_efficacy/dataset.csv")

# Filter to slice
mask = (df["entered"] == True) & (df["strategy"] == STRATEGY)
if REGIME != "ALL":
    mask &= (df["market_regime"] == REGIME)
d = df[mask].copy()

n = len(d)
win_rate = float(d["win"].mean())
mean_pnl = float(d["pnl_pct"].mean())

c_cols = [c for c in d.columns if c.startswith("c_")]

components = []
for c in c_cols:
    s = d[c]
    if s.nunique(dropna=True) <= 1 or s.var(skipna=True) == 0 or s.isna().all():
        continue
    sub = d[[c, "pnl_pct"]].dropna()
    if len(sub) < 10:
        continue
    nn = len(sub)
    ic = float(np.corrcoef(sub[c], sub["pnl_pct"])[0, 1])
    if np.isnan(ic):
        continue
    denom = max(1e-12, 1 - ic * ic)
    t = float(ic * np.sqrt(nn - 2) / np.sqrt(denom))

    # quintiles
    monotonic = False
    try:
        q = pd.qcut(sub[c].rank(method="first"), 5, labels=False)
        qm = sub.groupby(q)["pnl_pct"].mean()
        if len(qm) == 5:
            vals = qm.values
            inc = all(vals[i] < vals[i + 1] for i in range(4))
            dec = all(vals[i] > vals[i + 1] for i in range(4))
            monotonic = bool(inc or dec)
    except Exception:
        monotonic = False

    # tercile ablation
    try:
        terc = pd.qcut(sub[c].rank(method="first"), 3, labels=False)
        top = sub.loc[terc == 2, "pnl_pct"].mean()
        bot = sub.loc[terc == 0, "pnl_pct"].mean()
        ablation = float((top - bot) * 100.0)  # in pct points
    except Exception:
        ablation = float("nan")

    # classification
    ablation_sign_agrees = (np.sign(ablation) == np.sign(ic)) and ablation != 0
    if abs(t) > 3 and monotonic and ablation_sign_agrees:
        verdict = "predictive"
    elif abs(t) > 3 and monotonic and (np.sign(ablation) == -np.sign(ic)):
        verdict = "anti"
    else:
        verdict = "noise"

    components.append({
        "name": c,
        "ic": round(ic, 5),
        "t_stat": round(t, 4),
        "ablation_pnl_pct": round(ablation, 5),
        "quintile_monotonic": monotonic,
        "verdict": verdict,
    })

components.sort(key=lambda x: -abs(x["t_stat"]))

out = {
    "slice": f"{STRATEGY}/{REGIME}",
    "n": n,
    "base_win_rate": round(win_rate, 5),
    "base_mean_pnl_pct": round(mean_pnl * 100.0, 5),
    "components": components,
}
print(json.dumps(out, indent=2))
