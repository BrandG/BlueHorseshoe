"""Does ML over the full indicator set improve selection WITHIN deep-oversold fires?

Premise (Brand, 2026-06-07): the 41 indicators failed as a hand-weighted additive
SCORE (weights.json anti-selects), but that says nothing about their value as ML
FEATURES — a nonlinear model can exploit interactions an additive sum can't. The live
deep-oversold sleeve is mechanical/ML-free and ranks only on oversold DEPTH. Question:
conditional on a deep-oversold fire, can a gradient-boosted model over the indicator
set pick the winners better than (a) taking every fire, and (b) the depth rank?

Honest priors to beat (from our own research): signal-independence found ~3.7 effective
factors (mostly one redundant no-edge cluster) and entry-alpha-absent found components
had no rank edge in the general population. Conditional-on-setup + nonlinear is UNTESTED,
so this is a real open door — but it must clear the same bar: out-of-sample, with a
random-among-fires control, before any ML touches the live sleeve.

Method:
  * Population = deep-oversold fires (RSI<30 >=3 bars, 20d $-vol>=$25M, price 5-500),
    full universe, 2016-2026 — the validated live-sleeve population.
  * Label = win (realized R>0) of the validated 2:1 ATR / hold-10 bracket (close-entry
    proxy, no frictions — same harness as rsi_oversold_production.py).
  * Features = the indicator set at the FIRE bar (momentum/trend/volume/volatility/
    candlestick) + deep-specific (oversold age, $-vol, HA-green, regime). No look-ahead:
    features use data <= bar t; the label resolves over t+1..t+N.
  * TIME split (not random): train < 2021-01-01, test >= 2021-01-01.
  * Verdict = realized mean R of the model's top-quartile test fires vs (a) all test
    fires (take-every-fire) and (b) depth-rank top quartile. Plus test AUC + importances.
    Reported all-regime AND nonbull (where the edge lives).
"""
import numpy as np, pandas as pd, talib, duckdb

START="2016-01-01"; SPLIT="2021-01-01"
OS=30.0; MIN_AGE=3; N=10; TP_ATR,SL_ATR=2.0,1.0
DVOL_MIN=25_000_000.0; VOL_FLOOR=0.005; PRICE_MIN,PRICE_MAX=5.0,500.0
HA_WIN=150

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg.get(str(d)[:10],False)
print(f"{len(syms)} symbols; deep-oversold fires, bracket {TP_ATR:.0f}:{SL_ATR:.0f} hold {N}",flush=True)

def bracket(h,l,c,atr,N,tp_atr,sl_atr):
    n=len(c); tp=c+tp_atr*atr; sl=c-sl_atr*atr; Rp=sl_atr*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan)
    valid=(np.arange(n)<(n-N))&(atr>0)&~np.isnan(atr)
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp[:n-k]; slh[:n-k]=l[k:]<=sl[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=tp_atr/sl_atr; resolved|=(loss|wn)
    ex=np.full(n,np.nan); ex[:n-N]=c[N:][:n-N] if n-N>0 else ex[:n-N]
    to=valid&~resolved; res[to]=(ex[to]-c[to])/Rp[to]
    return res,valid

def ha_green(o,h,l,c):
    """Recursive Heiken-Ashi green flag per bar (windowed for convergence)."""
    n=len(c); out=np.zeros(n,bool)
    ha_close=(o+h+l+c)/4.0
    ha_open=np.empty(n);
    if n: ha_open[0]=(o[0]+c[0])/2.0
    for t in range(1,n): ha_open[t]=(ha_open[t-1]+ha_close[t-1])/2.0
    out=ha_close>ha_open
    return out

FEATS=["rsi","stochk","willr","cci","macd_hist","roc10","adx","pdi","mdi",
       "dist_sma20","dist_sma50","dist_sma200","ema9_v_21","atr_pct","bb_pos",
       "vol_ratio","log_dvol","obv_slope","dist_20d_low","dist_20d_high",
       "engulf","hammer","down_streak","oversold_age","ha_green","nonbull"]

rows=[]; labels=[]; dates=[]; Rfire=[]
for ii,sym in enumerate(syms):
    if ii%500==0: print(f"  {ii}/{len(syms)} (fires so far: {len(rows)})",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    rsi=talib.RSI(c,14); atr=talib.ATR(h,l,c,14); atr_pct=atr/np.where(c>0,c,np.nan)
    dvol20=pd.Series(c*v).rolling(20).mean().to_numpy()
    # oversold run age
    age=np.full(n,-1,int); run=0
    for i in range(n):
        if rsi[i]<OS: age[i]=run; run+=1
        else: run=0
    res,valid=bracket(h,l,c,atr,N,TP_ATR,SL_ATR)
    fire=(rsi<OS)&(age>=MIN_AGE)&(dvol20>=DVOL_MIN)&(atr_pct>=VOL_FLOOR)&(c>=PRICE_MIN)&(c<=PRICE_MAX)&valid&~np.isnan(res)
    if not fire.any(): continue
    # feature arrays (computed once per symbol, indexed at fire bars)
    stochk=talib.STOCH(h,l,c)[0]; willr=talib.WILLR(h,l,c,14); cci=talib.CCI(h,l,c,20)
    macd_hist=talib.MACD(c)[2]; roc10=talib.ROC(c,10)
    adx=talib.ADX(h,l,c,14); pdi=talib.PLUS_DI(h,l,c,14); mdi=talib.MINUS_DI(h,l,c,14)
    sma20=talib.SMA(c,20); sma50=talib.SMA(c,50); sma200=talib.SMA(c,200)
    ema9=talib.EMA(c,9); ema21=talib.EMA(c,21)
    up,mid,lo=talib.BBANDS(c,20); bb_pos=(c-lo)/np.where((up-lo)>0,(up-lo),np.nan)
    vol20=pd.Series(v).rolling(20).mean().to_numpy(); vol_ratio=v/np.where(vol20>0,vol20,np.nan)
    obv=talib.OBV(c,v); obv_slope=obv-np.concatenate([np.full(10,np.nan),obv[:-10]])
    roll_lo=pd.Series(l).rolling(20).min().to_numpy(); roll_hi=pd.Series(h).rolling(20).max().to_numpy()
    engulf=talib.CDLENGULFING(o,h,l,c)/100.0; hammer=talib.CDLHAMMER(o,h,l,c)/100.0
    hg=ha_green(o[-HA_WIN:],h[-HA_WIN:],l[-HA_WIN:],c[-HA_WIN:]) if n>HA_WIN else ha_green(o,h,l,c)
    hg_full=np.zeros(n,bool); hg_full[-len(hg):]=hg
    dstreak=np.zeros(n,int); s=0
    for i in range(1,n):
        s=s+1 if c[i]<c[i-1] else 0; dstreak[i]=s
    bull=np.array([isbull(x) for x in dts])
    feat={
        "rsi":rsi,"stochk":stochk,"willr":willr,"cci":cci,"macd_hist":macd_hist,"roc10":roc10,
        "adx":adx,"pdi":pdi,"mdi":mdi,
        "dist_sma20":(c-sma20)/sma20,"dist_sma50":(c-sma50)/sma50,"dist_sma200":(c-sma200)/sma200,
        "ema9_v_21":(ema9-ema21)/ema21,"atr_pct":atr_pct,"bb_pos":bb_pos,
        "vol_ratio":vol_ratio,"log_dvol":np.log(np.where(dvol20>0,dvol20,1.0)),
        "obv_slope":obv_slope/np.where(vol20>0,vol20,1.0),
        "dist_20d_low":(c-roll_lo)/c,"dist_20d_high":(roll_hi-c)/c,
        "engulf":engulf,"hammer":hammer,"down_streak":dstreak.astype(float),
        "oversold_age":age.astype(float),"ha_green":hg_full.astype(float),"nonbull":(~bull).astype(float),
    }
    idx=np.where(fire)[0]
    for i in idx:
        rows.append([feat[f][i] for f in FEATS]); labels.append(1.0 if res[i]>0 else 0.0)
        dates.append(dts[i]); Rfire.append(float(res[i]))

X=np.array(rows,float); y=np.array(labels); dts_arr=np.array(dates); R=np.array(Rfire)
print(f"\ntotal fires: {len(X)}  win-rate(all): {y.mean():.3f}  mean R(all): {R.mean():+.4f}",flush=True)

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score

train=dts_arr<SPLIT; test=~train
clf=HistGradientBoostingClassifier(max_iter=300,learning_rate=0.05,max_depth=4,
                                   l2_regularization=1.0,random_state=7)
clf.fit(X[train],y[train])
proba=clf.predict_proba(X[test])[:,1]
yte,Rte=y[test],R[test]
nonbull_te=X[test][:,FEATS.index("nonbull")]==1.0
auc=roc_auc_score(yte,proba) if len(set(yte))>1 else float('nan')
print(f"train fires: {train.sum()}  test fires: {test.sum()}")
print(f"\nTEST AUC (win discrimination): {auc:.4f}  [0.5 = no signal; >0.55 = meaningful]")

def verdict(mask,label):
    p=proba[mask]; rr=Rte[mask]; ages=X[test][mask][:,FEATS.index("oversold_age")]
    if len(p)<40: print(f"\n[{label}] n={len(p)} too thin"); return
    ntop=max(1,len(p)//4); o=np.argsort(-p)
    depth=np.argsort(-ages)[:ntop]
    print(f"\n[{label}] n={len(p)}  mean R / win-rate:")
    print(f"  take-every-fire (baseline): {rr.mean():+.4f}R  {(rr>0).mean():.3f}")
    print(f"  MODEL top-quartile        : {rr[o[:ntop]].mean():+.4f}R  {(rr[o[:ntop]]>0).mean():.3f}  (n={ntop})")
    print(f"  MODEL bottom-quartile     : {rr[o[-ntop:]].mean():+.4f}R  {(rr[o[-ntop:]]>0).mean():.3f}")
    print(f"  depth-rank top-quartile   : {rr[depth].mean():+.4f}R  {(rr[depth]>0).mean():.3f}")

verdict(np.ones(len(yte),bool),"ALL REGIMES")
verdict(nonbull_te,"NONBULL only")

imp=permutation_importance(clf,X[test],yte,n_repeats=5,random_state=7,scoring="roc_auc")
print("\ntop features (permutation importance, test AUC):")
for i in np.argsort(-imp.importances_mean)[:12]:
    print(f"  {FEATS[i]:16} {imp.importances_mean[i]:+.5f}")
print("\nREAD: if MODEL top-quartile mean R <= take-every-fire (and AUC ~0.5), the indicators")
print("      add NO selection edge conditional on the setup (matches signal-independence /")
print("      entry-alpha-absent priors) -> keep the sleeve mechanical. If MODEL top clearly")
print("      beats both baselines AND beats depth-rank, it earns a full cost/OOS gauntlet next.")
