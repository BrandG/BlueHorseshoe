import json
import numpy as np
import pandas as pd

STRATEGY = "mean_reversion"
REGIME = "Bearish"
PATH = "/root/BlueHorseshoe/research/scoring_efficacy/dataset.csv"

df = pd.read_csv(PATH)

mask = (df["strategy"] == STRATEGY) & (df["entered"] == True)
if REGIME != "ALL":
    mask &= (df["market_regime"] == REGIME)
d = df[mask].copy()

n = int(len(d))
win_rate = float(d["win"].mean())
mean_pnl_pct = float(d["pnl_pct"].mean() * 100.0)

c_cols = [c for c in d.columns if c.startswith("c_")]

components = []
for col in c_cols:
    s = d[col]
    if s.notna().sum() < 10:
        continue
    if s.std(skipna=True) == 0 or pd.isna(s.std(skipna=True)):
        continue
    sub = d[[col, "pnl_pct"]].dropna()
    if len(sub) < 10 or sub[col].std() == 0:
        continue
    x = sub[col].values
    y = sub["pnl_pct"].values
    nn = len(sub)

    ic = float(np.corrcoef(x, y)[0, 1])
    if np.isnan(ic):
        continue
    denom = np.sqrt(max(1e-12, 1 - ic * ic))
    t = float(ic * np.sqrt(nn - 2) / denom)

    # quintiles
    monotonic = False
    try:
        q = pd.qcut(sub[col], 5, labels=False, duplicates="drop")
        nq = q.nunique()
        if nq >= 3:
            qmeans = sub.groupby(q)["pnl_pct"].mean().values
            inc = all(qmeans[i] < qmeans[i + 1] for i in range(len(qmeans) - 1))
            dec = all(qmeans[i] > qmeans[i + 1] for i in range(len(qmeans) - 1))
            monotonic = bool(inc or dec)
    except Exception:
        monotonic = False

    # terciles ablation
    try:
        terc = pd.qcut(sub[col], 3, labels=False, duplicates="drop")
        if terc.nunique() >= 2:
            top = terc.max()
            bot = terc.min()
            top_mean = sub.loc[terc == top, "pnl_pct"].mean()
            bot_mean = sub.loc[terc == bot, "pnl_pct"].mean()
            ablation = float((top_mean - bot_mean) * 100.0)
        else:
            ablation = 0.0
    except Exception:
        ablation = 0.0

    sign_agree = (np.sign(ic) == np.sign(ablation)) and ablation != 0.0
    if abs(t) > 3 and monotonic and sign_agree:
        verdict = "predictive" if ic > 0 else "anti"
    else:
        verdict = "noise"

    components.append({
        "name": col,
        "ic": round(ic, 4),
        "t_stat": round(t, 3),
        "ablation_pnl_pct": round(ablation, 4),
        "quintile_monotonic": bool(monotonic),
        "verdict": verdict,
    })

components.sort(key=lambda c: -abs(c["t_stat"]))

pred = [c["name"] for c in components if c["verdict"] == "predictive"]
anti = [c["name"] for c in components if c["verdict"] == "anti"]
headline = (
    f"{STRATEGY}/{REGIME}: n={n}, win_rate={win_rate:.3f}, mean_pnl={mean_pnl_pct:.3f}%. "
    f"{len(pred)} predictive, {len(anti)} anti, {len(components)-len(pred)-len(anti)} noise. "
    f"Predictive: {pred or 'none'}. Anti: {anti or 'none'}."
)

out = {
    "slice": f"{STRATEGY}/{REGIME}",
    "n": n,
    "base_win_rate": round(win_rate, 4),
    "base_mean_pnl_pct": round(mean_pnl_pct, 4),
    "components": components,
    "headline": headline,
}
print(json.dumps(out, indent=2))
