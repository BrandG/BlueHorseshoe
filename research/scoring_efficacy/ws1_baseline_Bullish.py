import json
import numpy as np
import pandas as pd

STRATEGY = "baseline"
REGIME = "Bullish"

df = pd.read_csv("/root/BlueHorseshoe/research/scoring_efficacy/dataset.csv")

# Filter to slice
mask = (df["entered"] == True) & (df["strategy"] == STRATEGY)
if REGIME != "ALL":
    mask &= (df["market_regime"] == REGIME)
d = df[mask].copy()

n = len(d)
win_rate = float(d["win"].mean())
mean_pnl_pct = float(d["pnl_pct"].mean() * 100.0)  # report in percent

c_cols = [c for c in d.columns if c.startswith("c_")]

ret = d["pnl_pct"].astype(float)

components = []
for c in c_cols:
    x = d[c].astype(float)
    if x.var(ddof=0) == 0 or x.notna().sum() < 5:
        continue
    sub = pd.DataFrame({"x": x, "r": ret}).dropna()
    if len(sub) < 5 or sub["x"].var(ddof=0) == 0:
        continue
    nn = len(sub)
    ic = float(np.corrcoef(sub["x"], sub["r"])[0, 1])
    if np.isnan(ic):
        continue
    if abs(ic) >= 1.0:
        t = float("inf") * np.sign(ic)
    else:
        t = ic * np.sqrt(nn - 2) / np.sqrt(1 - ic**2)

    # quintiles
    monotonic = False
    try:
        q = pd.qcut(sub["x"], 5, labels=False, duplicates="drop")
        qm = sub.groupby(q)["r"].mean()
        if qm.shape[0] >= 3:
            vals = qm.values
            inc = all(vals[i] < vals[i+1] for i in range(len(vals)-1))
            dec = all(vals[i] > vals[i+1] for i in range(len(vals)-1))
            monotonic = bool(inc or dec)
    except Exception:
        monotonic = False

    # terciles ablation
    try:
        terc = pd.qcut(sub["x"], 3, labels=False, duplicates="drop")
        top = sub[terc == terc.max()]["r"].mean()
        bot = sub[terc == terc.min()]["r"].mean()
        ablation = float((top - bot) * 100.0)
    except Exception:
        ablation = float("nan")

    # classify
    abl_sign_agrees = (np.sign(ablation) == np.sign(ic)) if not np.isnan(ablation) else False
    if abs(t) > 3 and monotonic and abl_sign_agrees:
        verdict = "predictive" if ic > 0 else "anti"
    elif abs(t) > 3 and monotonic and (not np.isnan(ablation)) and (np.sign(ablation) != np.sign(ic)):
        verdict = "anti"
    else:
        verdict = "noise"

    components.append({
        "name": c,
        "ic": round(ic, 4),
        "t_stat": round(float(t), 3) if np.isfinite(t) else float(t),
        "ablation_pnl_pct": round(ablation, 4) if not np.isnan(ablation) else None,
        "quintile_monotonic": monotonic,
        "verdict": verdict,
    })

components.sort(key=lambda r: -abs(r["t_stat"]) if np.isfinite(r["t_stat"]) else -1e9)

out = {
    "slice": f"{STRATEGY}/{REGIME}",
    "n": int(n),
    "base_win_rate": round(win_rate, 4),
    "base_mean_pnl_pct": round(mean_pnl_pct, 4),
    "components": components,
}
print(json.dumps(out, indent=2))
