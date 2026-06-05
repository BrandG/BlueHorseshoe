"""ADX parameter sweep — find the config that makes ADX as strong as it can be.

Measurement held FIXED at the validated honest yardstick: ATR-scaled 2:1 runner
(TP=2*ATR14, SL=1*ATR14), entry close[t], same-bar both-touch = stop-first,
timeout = mark-to-market in R. Objective = expectancy LIFT vs the random-date
baseline (same regime, same window). Windows 10 & 15.

Swept ADX/DMI knobs:
  period   : 7, 14, 21, 28
  adx_min  : 20, 25, 30          (trend-present lower gate)
  adx_max  : 40, 50, 999(none)   (exhaustion upper cap)
  rising   : 0/1                 (require ADX[0] > ADX[-1])
  di       : off | s0(+DI>-DI) | s10((+DI--DI)>10) | s20(>20)
288 configs x 3 regimes. Reports per-knob main effects + top configs.
"""
import numpy as np, pandas as pd, talib, duckdb
from itertools import product

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
WINDOWS=[10,15]; TP_ATR,SL_ATR=2.0,1.0
PERIODS=[7,14,21,28]; ADX_MIN=[20,25,30]; ADX_MAX=[40,50,999]; RISING=[0,1]; DI=["off","s0","s10","s20"]

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["ema50"]=talib.EMA(spy.close,50); spy["ema200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.ema200)&(spy.ema50>spy.ema200)
spy_regime=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def reg(d): return "bull" if spy_regime.get(str(d)[:10],False) else "nonbull"

syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"{len(syms)} symbols, {len(PERIODS)*len(ADX_MIN)*len(ADX_MAX)*len(RISING)*len(DI)} configs",flush=True)

acc={}  # (config, window, regime) -> [n,kwin,sumR,sumsqR]
def bump(cfg,N,rk,n,kw,sR,ssR):
    key=(cfg,N,rk); a=acc.get(key)
    if a is None: acc[key]=a=[0,0,0.0,0.0]
    a[0]+=n; a[1]+=kw; a[2]+=sR; a[3]+=ssR

def bracket(h,l,c,atr,N):
    n=len(c); tp_lvl=c+TP_ATR*atr; sl_lvl=c-SL_ATR*atr; Rprice=SL_ATR*atr
    resolved=np.zeros(n,bool); win=np.zeros(n,bool); res=np.full(n,np.nan); win_pay=TP_ATR/SL_ATR
    valid=(np.arange(n)<(n-N))&(atr>0)&~np.isnan(atr)
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp_lvl[:n-k]; slh[:n-k]=l[k:]<=sl_lvl[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=win_pay; win[wn]=True; resolved|=(loss|wn)
    ex=np.full(n,np.nan); ex[:n-N]=c[N:][:n-N] if n-N>0 else ex[:n-N]
    to=valid&~resolved; res[to]=(ex[to]-c[to])/Rprice[to]
    return res,win,valid

CONFIGS=list(product(PERIODS,ADX_MIN,ADX_MAX,RISING,DI))
for i,sym in enumerate(syms):
    if i%200==0: print(f"  {i}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dates=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    eligible=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)
    reg_bull=np.array([reg(x)=="bull" for x in dates])
    # precompute ADX/DI per period
    P={}
    for p in PERIODS:
        adx=talib.ADX(h,l,c,p); pdi=talib.PLUS_DI(h,l,c,p); mdi=talib.MINUS_DI(h,l,c,p)
        P[p]=(adx,np.concatenate([[np.nan],adx[:-1]]),pdi-mdi)
    brk={N:bracket(h,l,c,atr,N) for N in WINDOWS}
    # baseline
    for N in WINDOWS:
        res,win,valid=brk[N]; base=eligible&valid&~np.isnan(res)
        for rk,rmask in (("all",base),("bull",base&reg_bull),("nonbull",base&~reg_bull)):
            if rmask.any():
                r=res[rmask]; bump(("__BASE__",),N,rk,int(rmask.sum()),int(win[rmask].sum()),float(r.sum()),float((r*r).sum()))
    for (p,amin,amax,rise,di) in CONFIGS:
        adx,adxp,spread=P[p]
        m=(adx>amin)&(adx<amax)
        if rise: m=m&(adx>adxp)
        if di=="s0": m=m&(spread>0)
        elif di=="s10": m=m&(spread>10)
        elif di=="s20": m=m&(spread>20)
        cfg=(p,amin,amax,rise,di)
        for N in WINDOWS:
            res,win,valid=brk[N]; mm=m&eligible&valid&~np.isnan(res)
            if not mm.any(): continue
            for rk,rmask in (("all",mm),("bull",mm&reg_bull),("nonbull",mm&~reg_bull)):
                nn=int(rmask.sum())
                if nn:
                    r=res[rmask]; bump(cfg,N,rk,nn,int(win[rmask].sum()),float(r.sum()),float((r*r).sum()))

def stat(cfg,N,rk):
    a=acc.get((cfg,N,rk))
    if not a or a[0]<1000: return None
    nn,kw,sR,ssR=a; mean=sR/nn; var=max(ssR/nn-mean*mean,0); se=(var/nn)**0.5
    return dict(n=nn,exp=mean,win=kw/nn,se=se)

rows=[]
for cfg in CONFIGS:
    p,amin,amax,rise,di=cfg
    for N in WINDOWS:
        for rk in ("all","bull","nonbull"):
            s=stat(cfg,N,rk); b=stat(("__BASE__",),N,rk)
            if s is None or b is None: continue
            lift=s["exp"]-b["exp"]; t=lift/s["se"] if s["se"]>0 else 0.0
            rows.append(dict(period=p,adx_min=amin,adx_max=amax,rising=rise,di=di,N=N,regime=rk,
                             n=s["n"],exp=round(s["exp"],4),lift=round(lift,4),t=round(t,1),win=round(s["win"],3)))
df=pd.DataFrame(rows)
df.to_csv("research/indicator_screen/adx_param_sweep.csv",index=False)

for rk in ("nonbull","all","bull"):
    base=stat(("__BASE__",),10,rk)
    print(f"\n############ regime={rk}  (N=10 baseline exp={base['exp']:+.4f}R, n={base['n']:,}) ############")
    sub=df[(df.regime==rk)&(df.N==10)]
    print("  -- per-knob MAIN EFFECT (mean lift over all configs holding that knob) --")
    for knob in ("period","adx_min","adx_max","rising","di"):
        eff=sub.groupby(knob)["lift"].mean().round(4).to_dict()
        print(f"    {knob:8}: "+"  ".join(f"{k}:{v:+.4f}" for k,v in eff.items()))
    print("  -- TOP 12 configs by expectancy lift (n>=2000, t>=2) --")
    top=sub[(sub.n>=2000)&(sub.t>=2)].sort_values("lift",ascending=False).head(12)
    if top.empty: print("    (none clear n>=2000 & t>=2)")
    for _,r in top.iterrows():
        print(f"    p{int(r.period):<2} adx[{int(r.adx_min)},{int(r.adx_max)}] rise={int(r.rising)} di={r.di:3} | "
              f"lift={r.lift:+.4f}R t={r.t:+.1f} exp={r.exp:+.4f}R win={r.win:.3f} n={int(r.n):,}")
print("\nsaved -> research/indicator_screen/adx_param_sweep.csv")
