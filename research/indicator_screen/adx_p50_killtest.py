"""Kill-test the p50 nonbull 'pocket' — does it survive a time split?

For each candidate p50 nonbull config, score the symbol-clustered lift SEPARATELY in
2016-2020 (H1) vs 2021-2026 (H2). Real edge -> positive & significant in BOTH halves.
Multiple-testing noise -> shows in one half, vanishes/flips in the other.
Same machinery as adx_param_sweep_clean.py (vol floor + episode-start + symbol cluster).
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"; SPLIT="2021-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; MIN_BASE_BARS=10; N=10; TP_ATR,SL_ATR=2.0,1.0
# p50 nonbull pocket candidates: (period,adx_min,adx_max,rising,di)
CONFIGS=[(50,25,999,0,"off"),(50,30,999,0,"off"),(50,30,999,0,"s0")]

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["ema50"]=talib.EMA(spy.close,50); spy["ema200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.ema200)&(spy.ema50>spy.ema200)
spy_regime=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return spy_regime.get(str(d)[:10],False)

syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"{len(syms)} symbols, split at {SPLIT}",flush=True)

acc={}  # (cfg,half) -> [sum_lift,sumsq,n_sym,n_ep]
def bump(cfg,half,lift,ne):
    k=(cfg,half); a=acc.get(k)
    if a is None: acc[k]=a=[0.0,0.0,0,0]
    a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=ne

def bracket(h,l,c,atr):
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
    if i%300==0: print(f"  {i}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dates=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    eligible=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&((atr/np.where(c>0,c,np.nan))>=VOL_FLOOR)
    nonbull=~np.array([isbull(x) for x in dates])
    h1=dates<SPLIT; h2=~h1
    res,valid=bracket(h,l,c,atr); base0=eligible&valid&~np.isnan(res)&nonbull
    for (p,amin,amax,rise,di) in CONFIGS:
        adx=talib.ADX(h,l,c,p); pdi=talib.PLUS_DI(h,l,c,p); mdi=talib.MINUS_DI(h,l,c,p)
        adxp=np.concatenate([[np.nan],adx[:-1]]); spread=pdi-mdi
        m=(adx>amin)&(adx<amax)
        if rise: m=m&(adx>adxp)
        if di=="s0": m=m&(spread>0)
        elif di=="s20": m=m&(spread>20)
        m_start=m&~np.concatenate([[False],m[:-1]])
        cfg=(p,amin,amax,rise,di)
        for half,hm in (("H1_16-20",h1),("H2_21-26",h2)):
            base=base0&hm; sig=m_start&base
            ne=int(sig.sum())
            if ne>=1 and int(base.sum())>=MIN_BASE_BARS:
                bump(cfg,half,res[sig].mean()-res[base].mean(),ne)

def show(cfg,half):
    a=acc.get((cfg,half))
    if not a: return "      (no data)"
    sL,ssL,ns,ne=a; mean=sL/ns; var=max(ssL/ns-mean*mean,0); se=(var/ns)**0.5; t=mean/se if se>0 else 0.0
    verdict="HOLDS" if (mean>0 and t>=2) else ("weak+" if mean>0 else "FAILS(neg)")
    return f"      {half}: lift={mean:+.4f}R  t={t:+.1f}  n_sym={ns:<4} n_ep={ne:<5} -> {verdict}"

print("\n==== p50 nonbull pocket — TIME-SPLIT KILL TEST (N=10, 2:1 runner) ====")
for cfg in CONFIGS:
    p,amin,amax,rise,di=cfg
    print(f"\n  config p{p} adx[{amin},{amax}] rise={rise} di={di}")
    print(show(cfg,"H1_16-20")); print(show(cfg,"H2_21-26"))
