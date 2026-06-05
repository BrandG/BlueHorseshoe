import pandas as pd, numpy as np
from scipy import stats

df = pd.read_csv("research/scoring_efficacy/dataset.csv")
COL = "c_curve_total_range_20"
print("total rows", len(df))

# Restrict to ENTERED trades with non-null component and pnl
d = df[(df["entered"]==True) & df[COL].notna() & df["pnl_pct"].notna()].copy()
print("entered+nonnull component+pnl:", len(d))
print("component non-null fraction among entered:",
      df[df["entered"]==True][COL].notna().mean())
print("component describe:\n", d[COL].describe())
print("unique vals (top):", d[COL].value_counts().head(10).to_dict())

def spear(x, y):
    if len(x) < 8 or x.std()==0:
        return (np.nan, np.nan, len(x))
    r, p = stats.spearmanr(x, y)
    return (r, p, len(x))

print("\n=== OVERALL ===")
r,p,n = spear(d[COL], d["pnl_pct"])
print(f"Spearman r={r:.4f} p={p:.4g} n={n}")

print("\n=== (a) BY REGIME x STRATEGY (sign stability) ===")
signs = []
for (strat, reg), g in d.groupby(["strategy","market_regime"]):
    r,p,n = spear(g[COL], g["pnl_pct"])
    if not np.isnan(r):
        signs.append((strat,reg,r,p,n))
        print(f"{strat:14s} {reg:9s} r={r:+.4f} p={p:.3g} n={n}")

print("\n=== BY REGIME ONLY (pooled strategies) ===")
reg_signs=[]
for reg, g in d.groupby("market_regime"):
    r,p,n = spear(g[COL], g["pnl_pct"])
    reg_signs.append((reg,r,n))
    print(f"{reg:9s} r={r:+.4f} n={n}")
pos = [s for s in reg_signs if s[1]>0]
neg = [s for s in reg_signs if s[1]<0]
print(f"regimes positive: {[s[0] for s in pos]}  negative: {[s[0] for s in neg]}")

print("\n=== (c) ONE-REGIME DRIVE CHECK (leave-one-regime-out overall sign) ===")
for reg in d["market_regime"].unique():
    sub = d[d["market_regime"]!=reg]
    r,p,n = spear(sub[COL], sub["pnl_pct"])
    print(f"drop {reg:9s}: r={r:+.4f} p={p:.3g} n={n}")

print("\n=== (b) CONFOUND CONTROL: partial Spearman controlling composite_score & signal_strength ===")
# encode signal_strength
d["ss_code"] = d["signal_strength"].astype("category").cat.codes
def partial_spearman(d, target, ctrls):
    # rank transform then regress out controls via OLS residuals
    from numpy.linalg import lstsq
    sub = d[[COL, target]+ctrls].dropna()
    if len(sub) < 20: return (np.nan, np.nan, len(sub))
    def rank(s): return stats.rankdata(s)
    X = np.column_stack([np.ones(len(sub))]+[rank(sub[c]) for c in ctrls])
    def resid(y):
        yr = rank(y)
        beta,_,_,_ = lstsq(X, yr, rcond=None)
        return yr - X@beta
    rx = resid(sub[COL]); ry = resid(sub[target])
    if rx.std()==0 or ry.std()==0: return (np.nan,np.nan,len(sub))
    r,p = stats.pearsonr(rx, ry)
    return (r,p,len(sub))

for ctrls in [["composite_score"],["ss_code"],["composite_score","ss_code"]]:
    r,p,n = partial_spearman(d, "pnl_pct", ctrls)
    print(f"partial r (ctrl={ctrls}) = {r:+.4f} p={p:.3g} n={n}")

print("\n=== within composite_score buckets (quintile) ===")
d["cs_q"] = pd.qcut(d["composite_score"], 5, duplicates="drop")
within=[]
for q,g in d.groupby("cs_q", observed=True):
    r,p,n = spear(g[COL], g["pnl_pct"])
    within.append(r)
    print(f"{str(q):28s} r={r:+.4f} n={n}")
within=[w for w in within if not np.isnan(w)]
print("within-bucket signs:", [f"{w:+.3f}" for w in within],
      " all same sign:", all(w>0 for w in within) or all(w<0 for w in within))

print("\n=== correlation of component with composite_score (proxy check) ===")
print("Spearman(component, composite_score) =",
      round(stats.spearmanr(d[COL], d["composite_score"])[0],4))

print("\n=== Mean pnl_pct by component tercile ===")
try:
    d["c_t"] = pd.qcut(d[COL], 3, duplicates="drop")
    print(d.groupby("c_t", observed=True)["pnl_pct"].agg(["mean","count"]))
except Exception as e:
    print("tercile failed:", e)
