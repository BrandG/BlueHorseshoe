"""ADX extended sweep — CLEANED, for the true ceiling.

Fixes the two artifacts that produced the bogus +1.4R/t=82:
  (1) VOL FLOOR: entry bar must have ATR(14)/close >= VOL_FLOOR (kills cash/bond
      ETFs like BIL/JPST that grind up at ~0 ATR).
  (2) DE-OVERLAP + SYMBOL CLUSTERING: collapse each consecutive signal run to its
      EPISODE START, then score per symbol as a PAIRED lift (symbol's signal mean R
      minus that symbol's own baseline mean R, same regime). Headline statistic is the
      mean of per-symbol lifts with SE across symbols -> immune to overlap and to one
      name dominating. A config is trustworthy only if n_symbols >= MIN_SYMBOLS.

Measurement unchanged: ATR 2:1 runner (TP=2*ATR14, SL=1*ATR14), windows 10 & 15.
"""
import numpy as np, pandas as pd, talib, duckdb
from itertools import product

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005           # ATR/close >= 0.5%
MIN_SYMBOLS=30; MIN_BASE_BARS=20
WINDOWS=[10,15]; TP_ATR,SL_ATR=2.0,1.0
PERIODS=[14,21,28,35,50,75]; ADX_MIN=[25,30,35,40]; ADX_MAX=[60,999]; RISING=[0,1]; DI=["off","s0","s20"]

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["ema50"]=talib.EMA(spy.close,50); spy["ema200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.ema200)&(spy.ema50>spy.ema200)
spy_regime=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return spy_regime.get(str(d)[:10],False)

syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
CONFIGS=list(product(PERIODS,ADX_MIN,ADX_MAX,RISING,DI))
print(f"{len(syms)} symbols, {len(CONFIGS)} configs, vol_floor={VOL_FLOOR}",flush=True)

# per (config,N,regime): [sum_lift, sumsq_lift, n_symbols, n_episodes]
acc={}
def bump(cfg,N,rk,lift,neps):
    key=(cfg,N,rk); a=acc.get(key)
    if a is None: acc[key]=a=[0.0,0.0,0,0]
    a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=neps

def bracket(h,l,c,atr,N):
    n=len(c); tp=c+TP_ATR*atr; sl=c-SL_ATR*atr; Rp=SL_ATR*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan); valid=(np.arange(n)<(n-N))&(atr>0)&~np.isnan(atr)
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp[:n-k]; slh[:n-k]=l[k:]<=sl[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=TP_ATR/SL_ATR; resolved|=(loss|wn)
    ex=np.full(n,np.nan); ex[:n-N]=c[N:][:n-N] if n-N>0 else ex[:n-N]
    to=valid&~resolved; res[to]=(ex[to]-c[to])/Rp[to]
    return res,valid

for i,sym in enumerate(syms):
    if i%200==0: print(f"  {i}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dates=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    eligible=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&((atr/c)>=VOL_FLOOR)   # <-- vol floor
    bull=np.array([isbull(x) for x in dates])
    regmask={"all":np.ones(n,bool),"bull":bull,"nonbull":~bull}
    P={}
    for p in PERIODS:
        adx=talib.ADX(h,l,c,p); pdi=talib.PLUS_DI(h,l,c,p); mdi=talib.MINUS_DI(h,l,c,p)
        P[p]=(adx,np.concatenate([[np.nan],adx[:-1]]),pdi-mdi)
    brk={N:bracket(h,l,c,atr,N) for N in WINDOWS}
    # per-symbol baseline mean R per (N,regime)
    basemean={}
    for N in WINDOWS:
        res,valid=brk[N]; base=eligible&valid&~np.isnan(res)
        for rk,rm in regmask.items():
            bm=base&rm
            basemean[(N,rk)]=(res[bm].mean(), int(bm.sum())) if bm.any() else (np.nan,0)
    for (p,amin,amax,rise,di) in CONFIGS:
        adx,adxp,spread=P[p]
        m=(adx>amin)&(adx<amax)
        if rise: m=m&(adx>adxp)
        if di=="s0": m=m&(spread>0)
        elif di=="s20": m=m&(spread>20)
        m_start=m&~np.concatenate([[False],m[:-1]])   # episode starts only
        cfg=(p,amin,amax,rise,di)
        for N in WINDOWS:
            res,valid=brk[N]; ok=m_start&eligible&valid&~np.isnan(res)
            if not ok.any(): continue
            for rk,rm in regmask.items():
                sel=ok&rm; ne=int(sel.sum())
                bmean,bn=basemean[(N,rk)]
                if ne>=1 and bn>=MIN_BASE_BARS and not np.isnan(bmean):
                    lift=res[sel].mean()-bmean
                    bump(cfg,N,rk,lift,ne)

rows=[]
for cfg in CONFIGS:
    p,amin,amax,rise,di=cfg
    for N in WINDOWS:
        for rk in ("all","bull","nonbull"):
            a=acc.get((cfg,N,rk))
            if not a: continue
            sL,ssL,nsym,neps=a
            if nsym<MIN_SYMBOLS: continue
            mean=sL/nsym; var=max(ssL/nsym-mean*mean,0); se=(var/nsym)**0.5
            t=mean/se if se>0 else 0.0
            rows.append(dict(period=p,adx_min=amin,adx_max=amax,rising=rise,di=di,N=N,regime=rk,
                             n_sym=nsym,n_ep=neps,lift=round(mean,4),t=round(t,1)))
df=pd.DataFrame(rows); df.to_csv("research/indicator_screen/adx_param_sweep_clean.csv",index=False)
if df.empty:
    print("\n(no config cleared MIN_SYMBOLS — edge is not diffuse)"); raise SystemExit

for rk in ("nonbull","all","bull"):
    print(f"\n############ regime={rk}  (symbol-clustered, vol-floored, episode-start) ############")
    sub=df[(df.regime==rk)&(df.N==10)]
    if sub.empty: print("  (no trustworthy config)"); continue
    print("  -- PERIOD RESPONSE: best clustered lift at each period (n_sym>=30) --")
    for p in PERIODS:
        s2=sub[sub.period==p]
        if s2.empty: print(f"    period {p:3}: (none clear)"); continue
        r=s2.loc[s2.lift.idxmax()]
        print(f"    period {p:3}: lift={r.lift:+.4f}R t={r.t:+.1f} (adx_min={int(r.adx_min)} cap={int(r.adx_max)} rise={int(r.rising)} di={r.di} | n_sym={int(r.n_sym)} n_ep={int(r.n_ep):,})")
    print("  -- TOP 10 by clustered lift (t>=2) --")
    top=sub[sub.t>=2].sort_values("lift",ascending=False).head(10)
    if top.empty: print("    (none with t>=2)")
    for _,r in top.iterrows():
        print(f"    p{int(r.period):<3} adx[{int(r.adx_min)},{int(r.adx_max)}] rise={int(r.rising)} di={r.di:3} | "
              f"lift={r.lift:+.4f}R t={r.t:+.1f} n_sym={int(r.n_sym)} n_ep={int(r.n_ep):,}")
print("\nsaved -> research/indicator_screen/adx_param_sweep_clean.csv")
