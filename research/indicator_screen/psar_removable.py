"""Can PSAR be removed entirely — even after tweaking its acceleration params?

Two removability criteria, swept over the PSAR knobs (af_start x af_max):
  (1) REDUNDANCY: corr(psar_dist, RSI). If it stays high for every setting, PSAR is
      just another member of the price-position cluster -> nothing unique to lose.
  (2) NO UNIQUE EDGE: clean standalone edge of the PSAR long-flip entry (close crosses
      above SAR), measured on the honest harness (ATR 2:1 runner, vol floor,
      episode-start de-overlap, symbol-clustered lift vs random). If no setting beats
      random, tuning can't rescue it.
If redundant AND edge-less across the whole grid -> safe to delete.
"""
import numpy as np, pandas as pd, talib, duckdb
from itertools import product

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
N=10; TP_ATR,SL_ATR=2.0,1.0; MIN_BASE=15
AF_START=[0.01,0.02,0.04]; AF_MAX=[0.10,0.20,0.40]

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg.get(str(d)[:10],False)
CFG=list(product(AF_START,AF_MAX))
print(f"{len(syms)} symbols, {len(CFG)} PSAR configs",flush=True)

# correlation accumulators per cfg: n,Sx,Sy,Sxx,Syy,Sxy   (x=psar_dist, y=rsi)
corr={c:[0,0.,0.,0.,0.,0.] for c in CFG}
# edge accumulators per (cfg,regime): [sumLift,sumsq,nsym,nep]
edge={}
def bumpE(c,rk,lift,ne):
    k=(c,rk); a=edge.get(k)
    if a is None: edge[k]=a=[0.,0.,0,0]
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
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy(); rsi=talib.RSI(c,14)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&((atr/np.where(c>0,c,np.nan))>=VOL_FLOOR)
    bull=np.array([isbull(x) for x in dts])
    res,valid=bracket(h,l,c,atr); base0=elig&valid&~np.isnan(res)
    for cfg in CFG:
        afs,afm=cfg
        sar=talib.SAR(h,l,afs,afm)
        pdist=(c-sar)/c
        above=c>sar; flip_up=above&~np.concatenate([[False],above[:-1]])  # cross above SAR
        # redundancy: corr(pdist, rsi) over eligible finite rows
        gg=elig&np.isfinite(pdist)&np.isfinite(rsi)
        if gg.any():
            x=pdist[gg]; y=rsi[gg]; a=corr[cfg]
            a[0]+=len(x); a[1]+=x.sum(); a[2]+=y.sum(); a[3]+=(x*x).sum(); a[4]+=(y*y).sum(); a[5]+=(x*y).sum()
        # edge of flip_up entry, symbol-clustered paired lift
        for rk,rm in (("all",np.ones(n,bool)),("bull",bull),("nonbull",~bull)):
            b=base0&rm; s=flip_up&b; ne=int(s.sum())
            if ne>=1 and int(b.sum())>=MIN_BASE:
                bumpE(cfg,rk,res[s].mean()-res[b].mean(),ne)

def pear(a):
    n,Sx,Sy,Sxx,Syy,Sxy=a
    if n<2: return float('nan')
    num=n*Sxy-Sx*Sy; den=((n*Sxx-Sx*Sx)*(n*Syy-Sy*Sy))**0.5
    return num/den if den>0 else float('nan')

print("\n==== PSAR removability sweep (|corr| w/ RSI = redundancy; lift = unique edge) ====")
print(f"  {'af_start':>8} {'af_max':>7} | {'|corr(dist,RSI)|':>16} | {'edge ALL':>16} {'edge BULL':>16} {'edge NONBULL':>16}")
for cfg in CFG:
    afs,afm=cfg; r=abs(pear(corr[cfg]))
    def cell(rk):
        a=edge.get((cfg,rk))
        if not a or a[2]<30: return "  n<30"
        sL,ss,ns,ne=a; m=sL/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5; t=m/se if se>0 else 0
        return f"{m:+.4f}R(t={t:+.1f})"
    print(f"  {afs:>8} {afm:>7} | {r:>16.2f} | {cell('all'):>16} {cell('bull'):>16} {cell('nonbull'):>16}")
print("\n  (high |corr| every row => redundant with RSI regardless of tuning;")
print("   no positive significant edge => tuning cannot rescue a unique signal)")
