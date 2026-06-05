"""How many INDEPENDENT bets are really in the indicator suite?

Compute ~32 indicators (all 6 categories) as continuous signals across 2000 symbols,
z-score each within-symbol, accumulate a pooled correlation matrix, then measure
effective dimensionality:
  - participation ratio PR = (Σλ)^2 / Σλ^2  (effective # independent factors)
  - # principal components to reach 90% variance
  - redundancy clusters (|corr|>0.6 connected components)
  - top correlated pairs (the obvious duplicates)
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))

def roll_sum(a,w): return pd.Series(a).rolling(w).sum().to_numpy()
def roll_mean(a,w): return pd.Series(a).rolling(w).mean().to_numpy()
def roll_std(a,w): return pd.Series(a).rolling(w).std().to_numpy()
def roll_max(a,w): return pd.Series(a).rolling(w).max().to_numpy()
def roll_min(a,w): return pd.Series(a).rolling(w).min().to_numpy()
def shift(a,k):
    out=np.full(len(a),np.nan); out[k:]=a[:-k] if k<len(a) else out[k:]; return out

def signals(o,h,l,c,v):
    S={}
    S["rsi"]=talib.RSI(c,14); S["willr"]=talib.WILLR(h,l,c,14)
    S["stochk"],_=talib.STOCH(h,l,c,14,3,0,3,0); S["cci"]=talib.CCI(h,l,c,20)
    S["mfi"]=talib.MFI(h,l,c,v,14); S["roc10"]=talib.ROC(c,10); S["roc3"]=talib.ROC(c,3)
    macd,sig,hist=talib.MACD(c,12,26,9); S["macd_hist"]=hist
    up,mid,lo=talib.BBANDS(c,20,2,2); S["bb_pctb"]=(c-lo)/(up-lo); S["bb_width"]=(up-lo)/mid
    sma20=talib.SMA(c,20); sd20=roll_std(c,20); S["zscore"]=(c-sma20)/sd20
    S["adx"]=talib.ADX(h,l,c,14); S["di_spread"]=talib.PLUS_DI(h,l,c,14)-talib.MINUS_DI(h,l,c,14)
    S["aroonosc"]=talib.AROONOSC(h,l,25); S["psar_dist"]=(c-talib.SAR(h,l,0.02,0.2))/c
    kij=(roll_max(h,26)+roll_min(l,26))/2; S["ich_kijun"]=(c-kij)/c
    sma50=talib.SMA(c,50); sma200=talib.SMA(c,200)
    S["dist_sma50"]=c/sma50-1; S["dist_sma200"]=c/sma200-1; S["sma_cross"]=sma50/sma200-1
    lo20=roll_min(l,20); hi20=roll_max(h,20); S["donch_pos"]=(c-lo20)/(hi20-lo20)
    ema20=talib.EMA(c,20); S["ema_slope"]=ema20/shift(ema20,5)-1
    atr=talib.ATR(h,l,c,14); S["atr_pct"]=atr/c; S["keltner_pos"]=(c-ema20)/atr
    vol20=roll_mean(v,20); S["rvol"]=v/vol20
    obv=talib.OBV(c,v); S["obv_slope"]=obv-shift(obv,10)
    fi=(c-shift(c,1))*v; S["force_idx"]=talib.EMA(np.nan_to_num(fi),13)
    ad=talib.AD(h,l,c,v); S["ad_slope"]=ad-shift(ad,10)
    tp=(h+l+c)/3; vwap20=roll_sum(tp*v,20)/roll_sum(v,20); S["vwap_dist"]=c/vwap20-1
    S["gap"]=o/shift(c,1)-1
    S["engulf"]=talib.CDLENGULFING(o,h,l,c).astype(float)
    S["hammer"]=talib.CDLHAMMER(o,h,l,c).astype(float)
    return S

NAMES=None; K=None; M=None; n_tot=0; nzfrac=None
for i,sym in enumerate(syms):
    if i%300==0: print(f"  {i}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    vol20=roll_mean(v,20); atr=talib.ATR(h,l,c,14)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&((atr/np.where(c>0,c,np.nan))>=VOL_FLOOR)
    S=signals(o,h,l,c,v)
    if NAMES is None:
        NAMES=list(S.keys()); K=len(NAMES); M=np.zeros((K,K)); nzfrac=np.zeros(K)
    X=np.column_stack([S[k] for k in NAMES])
    good=elig&np.all(np.isfinite(X),axis=1)
    if good.sum()<30: continue
    Z=X[good]
    nzfrac+=np.sum(Z!=0,axis=0)
    mu=Z.mean(0); sd=Z.std(0); sd[sd==0]=1.0
    Z=(Z-mu)/sd
    M+=Z.T@Z; n_tot+=Z.shape[0]

corr=M/n_tot
d=np.sqrt(np.clip(np.diag(corr),1e-9,None)); corr=corr/np.outer(d,d)
np.fill_diagonal(corr,1.0)
pd.DataFrame(corr,index=NAMES,columns=NAMES).round(3).to_csv("research/indicator_screen/signal_corr.csv")

w=np.linalg.eigvalsh(corr); w=np.clip(w,0,None)[::-1]
PR=(w.sum()**2)/np.sum(w**2)
cum=np.cumsum(w)/w.sum(); pc90=int(np.searchsorted(cum,0.90))+1; pc95=int(np.searchsorted(cum,0.95))+1

print(f"\n==== SIGNAL INDEPENDENCE  ({K} signals, n={n_tot:,} obs) ====")
print(f"  Participation ratio (effective # independent factors): {PR:.1f}  out of {K}")
print(f"  PCs to explain 90% variance: {pc90}   | 95%: {pc95}")
print(f"  top eigenvalues (each ~'size of one factor'): "+", ".join(f"{x:.1f}" for x in w[:8]))

# redundancy clusters: union-find on |corr|>0.6
TH=0.6; parent=list(range(K))
def find(x):
    while parent[x]!=x: parent[x]=parent[parent[x]]; x=parent[x]
    return x
def union(a,b):
    ra,rb=find(a),find(b)
    if ra!=rb: parent[ra]=rb
for a in range(K):
    for b in range(a+1,K):
        if abs(corr[a,b])>=TH: union(a,b)
clusters={}
for idx,name in enumerate(NAMES): clusters.setdefault(find(idx),[]).append(name)
print(f"\n  redundancy clusters (|corr|>={TH}; singletons = standalone factors):")
for members in sorted(clusters.values(),key=len,reverse=True):
    tag="  <-- REDUNDANT GROUP" if len(members)>1 else ""
    print(f"    {{{', '.join(members)}}}{tag}")
print(f"\n  => {len(clusters)} correlation-clusters at |r|>={TH}")

pairs=[(abs(corr[a,b]),NAMES[a],NAMES[b]) for a in range(K) for b in range(a+1,K)]
pairs.sort(reverse=True)
print("\n  top 12 most-correlated pairs (the obvious duplicates):")
for r,a,b in pairs[:12]:
    print(f"    |r|={r:.2f}  {a} ~ {b}")
print("\nsaved -> research/indicator_screen/signal_corr.csv")
