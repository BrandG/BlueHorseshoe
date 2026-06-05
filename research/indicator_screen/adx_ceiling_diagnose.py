"""Diagnose the absurd ADX 'ceiling' — is +1.4R/t=82 a real edge or a test artifact?

Hypothesis: extreme long-period high-threshold ADX selects a few monster sustained
trends; the 'n' is overlapping consecutive bars from a handful of survivor names, so
the t-stat is wildly inflated (correlated samples counted as independent) and the
expectancy is concentration + survivorship, not a generalizable signal.

For the headline configs, report: distinct symbols, distinct EPISODES (maximal runs of
consecutive fire-bars within a symbol), share of fires from the top-5 symbols, and the
spread of per-symbol mean R. If a few names dominate -> artifact confirmed.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
TP_ATR,SL_ATR,N=2.0,1.0,10
# (label, period, adx_min, adx_max, rising, di, regime)
TARGETS=[
    ("ALL  p100 adx45 rise di=s0", 100,45,999,1,"s0","all"),
    ("BULL p75  adx45 rise di=s0",  75,45,999,1,"s0","bull"),
    ("NONB p75  adx35 di=off",      75,35,999,0,"off","nonbull"),
]

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["ema50"]=talib.EMA(spy.close,50); spy["ema200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.ema200)&(spy.ema50>spy.ema200)
spy_regime=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return spy_regime.get(str(d)[:10],False)

syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))

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

# per target: list of (symbol, fire_index_array, R_array)
hits={lbl:{} for (lbl,*_ ) in TARGETS}
for sym in syms:
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dates=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    eligible=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)
    bull=np.array([isbull(x) for x in dates]); res,valid=bracket(h,l,c,atr)
    base=eligible&valid&~np.isnan(res)
    for (lbl,p,amin,amax,rise,di,rk) in TARGETS:
        adx=talib.ADX(h,l,c,p); pdi=talib.PLUS_DI(h,l,c,p); mdi=talib.MINUS_DI(h,l,c,p)
        adxp=np.concatenate([[np.nan],adx[:-1]]); spread=pdi-mdi
        m=(adx>amin)&(adx<amax)
        if rise: m=m&(adx>adxp)
        if di=="s0": m=m&(spread>0)
        elif di=="s20": m=m&(spread>20)
        m=m&base
        if rk=="bull": m=m&bull
        elif rk=="nonbull": m=m&~bull
        idx=np.where(m)[0]
        if len(idx): hits[lbl][sym]=(idx,res[m])

for (lbl,*_),(rk) in zip(TARGETS,[t[-1] for t in TARGETS]):
    H=hits[lbl]
    allR=np.concatenate([r for (_,r) in H.values()]) if H else np.array([])
    nfires=len(allR); nsym=len(H)
    # episodes = maximal runs of consecutive bar-indices within a symbol
    episodes=0; epR=[]
    persym=[]
    for sym,(idx,r) in H.items():
        splits=np.split(np.arange(len(idx)), np.where(np.diff(idx)!=1)[0]+1)
        episodes+=len(splits)
        for s in splits: epR.append(float(r[s].mean()))
        persym.append((sym,len(idx),float(r.mean())))
    persym.sort(key=lambda x:-x[1])
    top5share=sum(x[1] for x in persym[:5])/nfires if nfires else 0
    print(f"\n===== {lbl}  (regime={rk}) =====")
    print(f"  fires(n)={nfires:,}  distinct_symbols={nsym}  distinct_episodes={episodes}")
    print(f"  fires-per-episode (overlap factor) = {nfires/max(episodes,1):.1f}x")
    print(f"  top-5 symbols = {top5share*100:.0f}% of all fires")
    print(f"  mean R (per-fire, inflated)   = {allR.mean():+.3f}  on n={nfires:,}")
    print(f"  mean R (per-EPISODE, honest)  = {np.mean(epR):+.3f}  on n_episodes={episodes:,}  (SE~{np.std(epR)/max(episodes,1)**0.5:.3f})")
    persym_R=[x[2] for x in persym]
    print(f"  per-symbol mean R spread: median={np.median(persym_R):+.3f}  "
          f"frac symbols positive={np.mean([x>0 for x in persym_R])*100:.0f}%")
    print(f"  top-8 symbols by fire-count: "+", ".join(f"{s}({k},R={mr:+.2f})" for s,k,mr in persym[:8]))
