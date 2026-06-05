"""Are the redundant indicators the SAME transform, or just co-moving with the market?

Discriminator = cross-sectional correlation. Two indicators that are the same formula
agree stock-by-stock on the SAME day. Two that merely both track the market agree over
time but scatter cross-sectionally. So compare:
  (A) within-symbol correlation  (time-series; market-common factor still present)
  (B) double-demeaned correlation (within-symbol AND within-date; market factor removed)
If the big cluster + high pairs SURVIVE in (B) -> structural sameness (real redundancy).
If they DISSOLVE -> it was beta co-movement (more independent than it looked).

Two passes: pass1 builds per-date cross-sectional means; pass2 demeans + z-scores +
accumulates both correlation matrices.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))

def rsum(a,w): return pd.Series(a).rolling(w).sum().to_numpy()
def rmean(a,w): return pd.Series(a).rolling(w).mean().to_numpy()
def rstd(a,w): return pd.Series(a).rolling(w).std().to_numpy()
def rmax(a,w): return pd.Series(a).rolling(w).max().to_numpy()
def rmin(a,w): return pd.Series(a).rolling(w).min().to_numpy()
def shift(a,k):
    out=np.full(len(a),np.nan)
    if k<len(a): out[k:]=a[:-k]
    return out

def signals(o,h,l,c,v):
    S={}
    S["rsi"]=talib.RSI(c,14); S["willr"]=talib.WILLR(h,l,c,14)
    S["stochk"],_=talib.STOCH(h,l,c,14,3,0,3,0); S["cci"]=talib.CCI(h,l,c,20)
    S["mfi"]=talib.MFI(h,l,c,v,14); S["roc10"]=talib.ROC(c,10); S["roc3"]=talib.ROC(c,3)
    macd,sig,hist=talib.MACD(c,12,26,9); S["macd_hist"]=hist
    up,mid,lo=talib.BBANDS(c,20,2,2); S["bb_pctb"]=(c-lo)/(up-lo); S["bb_width"]=(up-lo)/mid
    sma20=talib.SMA(c,20); S["zscore"]=(c-sma20)/rstd(c,20)
    S["adx"]=talib.ADX(h,l,c,14); S["di_spread"]=talib.PLUS_DI(h,l,c,14)-talib.MINUS_DI(h,l,c,14)
    S["aroonosc"]=talib.AROONOSC(h,l,25); S["psar_dist"]=(c-talib.SAR(h,l,0.02,0.2))/c
    kij=(rmax(h,26)+rmin(l,26))/2; S["ich_kijun"]=(c-kij)/c
    sma50=talib.SMA(c,50); sma200=talib.SMA(c,200)
    S["dist_sma50"]=c/sma50-1; S["dist_sma200"]=c/sma200-1; S["sma_cross"]=sma50/sma200-1
    lo20=rmin(l,20); hi20=rmax(h,20); S["donch_pos"]=(c-lo20)/(hi20-lo20)
    ema20=talib.EMA(c,20); S["ema_slope"]=ema20/shift(ema20,5)-1
    atr=talib.ATR(h,l,c,14); S["atr_pct"]=atr/c; S["keltner_pos"]=(c-ema20)/atr
    S["rvol"]=v/rmean(v,20)
    obv=talib.OBV(c,v); S["obv_slope"]=obv-shift(obv,10)
    fi=(c-shift(c,1))*v; S["force_idx"]=talib.EMA(np.nan_to_num(fi),13)
    ad=talib.AD(h,l,c,v); S["ad_slope"]=ad-shift(ad,10)
    tp=(h+l+c)/3; S["vwap_dist"]=c/(rsum(tp*v,20)/rsum(v,20))-1
    S["gap"]=o/shift(c,1)-1
    S["engulf"]=talib.CDLENGULFING(o,h,l,c).astype(float)
    S["hammer"]=talib.CDLHAMMER(o,h,l,c).astype(float)
    return S

# cache eligible rows per symbol: (dates, X[good])
NAMES=None; cache={}
date_sum={}; date_cnt={}
for i,sym in enumerate(syms):
    if i%300==0: print(f"  pass1 {i}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy()
    atr=talib.ATR(h,l,c,14); vol20=rmean(v,20)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&((atr/np.where(c>0,c,np.nan))>=VOL_FLOOR)
    S=signals(o,h,l,c,v)
    if NAMES is None: NAMES=list(S.keys())
    X=np.column_stack([S[k] for k in NAMES])
    good=elig&np.all(np.isfinite(X),axis=1)
    if good.sum()<30: continue
    Xg=X[good]; dg=dts[good]; cache[sym]=(dg,Xg)
    for j,dd in enumerate(dg):
        if dd in date_sum: date_sum[dd]+=Xg[j]; date_cnt[dd]+=1
        else: date_sum[dd]=Xg[j].copy(); date_cnt[dd]=1

K=len(NAMES); date_mean={dd:date_sum[dd]/date_cnt[dd] for dd in date_sum}
Mts=np.zeros((K,K)); nts=0; Mxs=np.zeros((K,K)); nxs=0
for i,(sym,(dg,Xg)) in enumerate(cache.items()):
    if i%300==0: print(f"  pass2 {i}/{len(cache)}",flush=True)
    # (A) within-symbol z-score
    mu=Xg.mean(0); sd=Xg.std(0); sd[sd==0]=1
    Za=(Xg-mu)/sd; Mts+=Za.T@Za; nts+=Za.shape[0]
    # (B) subtract per-date cross-sectional mean, THEN within-symbol z-score
    DM=np.column_stack([date_mean[dd] for dd in dg]).T
    Xd=Xg-DM; mu2=Xd.mean(0); sd2=Xd.std(0); sd2[sd2==0]=1
    Zb=(Xd-mu2)/sd2; Mxs+=Zb.T@Zb; nxs+=Zb.shape[0]

def corr_of(M,n):
    c=M/n; dd=np.sqrt(np.clip(np.diag(c),1e-9,None)); c=c/np.outer(dd,dd); np.fill_diagonal(c,1.0); return c
def PR(c):
    w=np.clip(np.linalg.eigvalsh(c),0,None); return (w.sum()**2)/np.sum(w**2)

Cts=corr_of(Mts,nts); Cxs=corr_of(Mxs,nxs)
idx={n:i for i,n in enumerate(NAMES)}
PAIRS=[("bb_pctb","zscore"),("cci","zscore"),("rsi","keltner_pos"),("rsi","di_spread"),
       ("rsi","willr"),("willr","donch_pos"),("dist_sma50","ema_slope"),("macd_hist","roc10"),
       ("adx","rsi"),("gap","rsi"),("rvol","rsi"),("ad_slope","obv_slope")]
print(f"\n==== same transform vs market co-movement  (K={K}, n={nts:,}) ====")
print(f"  Participation ratio  within-symbol (A): {PR(Cts):.1f}")
print(f"  Participation ratio  cross-sectional (B, market removed): {PR(Cxs):.1f}")
print(f"\n  pair                         |r| within-sym (A)   |r| cross-sec (B)   verdict")
for a,b in PAIRS:
    ra=abs(Cts[idx[a],idx[b]]); rb=abs(Cxs[idx[a],idx[b]])
    if rb>=0.6: vd="SAME TRANSFORM (survives)"
    elif ra>=0.6 and rb<0.4: vd="was MARKET co-move (dissolves)"
    else: vd="independent"
    print(f"    {a:12} ~ {b:12}      {ra:.2f}              {rb:.2f}          {vd}")
# cluster count cross-sectionally
TH=0.6; parent=list(range(K))
def find(x):
    while parent[x]!=x: parent[x]=parent[parent[x]]; x=parent[x]
    return x
for a in range(K):
    for b in range(a+1,K):
        if abs(Cxs[a,b])>=TH:
            ra,rb=find(a),find(b)
            if ra!=rb: parent[ra]=rb
cl={}
for ii,nm in enumerate(NAMES): cl.setdefault(find(ii),[]).append(nm)
print(f"\n  cross-sectional clusters (|r|>={TH}):")
for m in sorted(cl.values(),key=len,reverse=True):
    print(f"    {{{', '.join(m)}}}"+("  <-- still redundant" if len(m)>1 else ""))
print(f"  => {len(cl)} clusters after removing the market factor (was 8 within-symbol)")
