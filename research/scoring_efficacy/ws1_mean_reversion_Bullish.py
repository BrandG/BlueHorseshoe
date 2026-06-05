import json
import numpy as np
import pandas as pd

STRATEGY = "mean_reversion"
REGIME = "Bullish"

df = pd.read_csv("/root/BlueHorseshoe/research/scoring_efficacy/dataset.csv")

m = (df["entered"] == True) & (df["strategy"] == STRATEGY)
if REGIME != "ALL":
    m &= (df["market_regime"] == REGIME)
d = df[m].copy()

n = len(d)
win_rate = float(d["win"].mean()) if n else float("nan")
mean_pnl = float(d["pnl_pct"].mean()) if n else float("nan")

ccols = [c for c in d.columns if c.startswith("c_")]
y = d["pnl_pct"].astype(float)

def monotonic(vals):
    inc = all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))
    dec = all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))
    return inc or dec

components = []
for c in ccols:
    x = d[c].astype(float)
    if x.var() == 0 or x.notna().sum() < 5:
        continue
    sub = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(sub) < 10 or sub["x"].var() == 0:
        continue
    ic = float(np.corrcoef(sub["x"], sub["y"])[0, 1])
    nn = len(sub)
    if abs(ic) >= 1.0:
        t = float("inf")
    else:
        t = float(ic * np.sqrt(nn - 2) / np.sqrt(1 - ic**2))

    # quintiles
    qmono = False
    try:
        q = pd.qcut(sub["x"], 5, labels=False, duplicates="drop")
        qmeans = sub.groupby(q)["y"].mean()
        if len(qmeans) >= 3:
            qmono = monotonic(list(qmeans.values))
    except Exception:
        qmono = False

    # ablation: top tercile - bottom tercile
    try:
        tt = pd.qcut(sub["x"], 3, labels=False, duplicates="drop")
        top = sub[tt == tt.max()]["y"].mean()
        bot = sub[tt == tt.min()]["y"].mean()
        ablation = float(top - bot)
    except Exception:
        ablation = float("nan")

    ablation_pct = ablation * 100.0 if not np.isnan(ablation) else float("nan")

    # classify
    sign_agree = (not np.isnan(ablation)) and (np.sign(ablation) == np.sign(ic)) and ic != 0
    if abs(t) > 3 and qmono and sign_agree:
        # predictive if higher comp -> better pnl (ic>0). anti if wrong sign relationship.
        # ic and ablation agree by construction here; "wrong sign" means component up -> pnl down
        if ic > 0:
            verdict = "predictive"
        else:
            verdict = "anti"
    else:
        verdict = "noise"

    components.append({
        "name": c,
        "ic": round(ic, 5),
        "t_stat": round(t, 4) if np.isfinite(t) else t,
        "ablation_pnl_pct": round(ablation_pct, 5) if np.isfinite(ablation_pct) else ablation_pct,
        "quintile_monotonic": bool(qmono),
        "verdict": verdict,
    })

components.sort(key=lambda r: -abs(r["t_stat"]) if np.isfinite(r["t_stat"]) else -1e9)

pred = [c["name"] for c in components if c["verdict"] == "predictive"]
anti = [c["name"] for c in components if c["verdict"] == "anti"]
headline = (
    f"{STRATEGY}/{REGIME}: n={n}, base WR={win_rate:.1%}, mean pnl={mean_pnl*100:.3f}%. "
    f"{len(pred)} predictive, {len(anti)} anti, {len(components)-len(pred)-len(anti)} noise. "
    f"Top predictive: {', '.join(pred[:3]) if pred else 'none'}. "
    f"Anti: {', '.join(anti[:3]) if anti else 'none'}."
)

out = {
    "slice": f"{STRATEGY}/{REGIME}",
    "n": int(n),
    "base_win_rate": round(win_rate, 5),
    "base_mean_pnl_pct": round(mean_pnl * 100, 5),
    "components": components,
    "headline": headline,
}
print(json.dumps(out, indent=2))
