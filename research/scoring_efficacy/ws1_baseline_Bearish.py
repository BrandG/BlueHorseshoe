import json
import numpy as np
import pandas as pd

STRATEGY = "baseline"
REGIME = "Bearish"

df = pd.read_csv("/root/BlueHorseshoe/research/scoring_efficacy/dataset.csv")

# Slice filter
sl = df[(df["entered"] == True) & (df["strategy"] == STRATEGY)].copy()
if REGIME != "ALL":
    sl = sl[sl["market_regime"] == REGIME].copy()

n = len(sl)
base_win_rate = float(sl["win"].mean()) if n else float("nan")
base_mean_pnl = float(sl["pnl_pct"].mean()) if n else float("nan")

c_cols = [c for c in sl.columns if c.startswith("c_")]
y = sl["pnl_pct"].astype(float)

components = []
for col in c_cols:
    x = sl[col].astype(float)
    if x.notna().sum() < 5 or x.std(ddof=0) == 0 or np.isclose(x.var(), 0.0):
        continue
    mask = x.notna() & y.notna()
    xv, yv = x[mask], y[mask]
    nn = len(xv)
    if nn < 5 or xv.std(ddof=0) == 0:
        continue
    ic = float(np.corrcoef(xv, yv)[0, 1])
    if np.isnan(ic):
        continue
    denom = max(1e-12, 1 - ic * ic)
    t = ic * np.sqrt(max(nn - 2, 0)) / np.sqrt(denom)

    # Quintiles
    monotonic = False
    try:
        q = pd.qcut(xv, 5, labels=False, duplicates="drop")
        qm = yv.groupby(q).mean()
        if len(qm) >= 3:
            vals = qm.values
            inc = all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))
            dec = all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))
            monotonic = bool(inc or dec)
    except Exception:
        monotonic = False

    # Ablation: top tercile - bottom tercile
    try:
        tert = pd.qcut(xv, 3, labels=False, duplicates="drop")
        top = yv[tert == tert.max()].mean()
        bot = yv[tert == tert.min()].mean()
        ablation = float(top - bot)
    except Exception:
        ablation = float("nan")

    ablation_pct = ablation * 100.0 if not np.isnan(ablation) else float("nan")

    sign_agree = (np.sign(ic) == np.sign(ablation)) and not np.isnan(ablation)
    if abs(t) > 3 and monotonic and sign_agree:
        verdict = "predictive" if ic > 0 else "anti"
    else:
        verdict = "noise"

    components.append({
        "name": col,
        "ic": round(ic, 4),
        "t_stat": round(float(t), 3),
        "ablation_pnl_pct": round(ablation_pct, 4) if not np.isnan(ablation_pct) else None,
        "quintile_monotonic": monotonic,
        "verdict": verdict,
    })

components.sort(key=lambda c: abs(c["t_stat"]), reverse=True)

pred = [c["name"] for c in components if c["verdict"] == "predictive"]
anti = [c["name"] for c in components if c["verdict"] == "anti"]
headline = (f"baseline/Bearish n={n}: win_rate={base_win_rate:.3f}, "
            f"mean_pnl={base_mean_pnl*100:.3f}%. "
            f"predictive={pred or 'none'}; anti={anti or 'none'}.")

out = {
    "slice": "baseline/Bearish",
    "n": n,
    "base_win_rate": round(base_win_rate, 4),
    "base_mean_pnl_pct": round(base_mean_pnl * 100, 4),
    "components": components,
    "headline": headline,
}
print(json.dumps(out, indent=2))
