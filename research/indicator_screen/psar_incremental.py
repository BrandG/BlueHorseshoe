"""Decisive PSAR removability test: is the PSAR-flip edge UNIQUE, or just the
oversold/mean-reversion factor it correlates 0.76 with?

Focus: nonbull (where PSAR-flip showed +0.083R t=4.5), slow AF (0.01,0.2).
Decompose the flip-up entry against oversold (rsi<30 = the factor we'd KEEP):
  A psar_up               : the raw signal edge
  B psar_up &  oversold   : the overlap
  C psar_up & ~oversold   : <-- THE TEST. PSAR firing when NOT oversold.
  D oversold (rsi<30)     : the factor's own edge (what we keep anyway)
  E oversold & ~psar_up   : factor edge on the non-PSAR bars
If C ~ 0  -> PSAR's edge is entirely the oversold overlap -> REMOVABLE.
If C >> 0 -> PSAR carries unique edge -> keep / investigate.
Clean harness: ATR 2:1 runner, vol floor, episode-start, symbol-clustered lift vs random.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
N=10; TP_ATR,SL_ATR=2.0,1.0; MIN_BASE=15; AFS,AFM=0.01,0.2; OS=30

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg.get(str(d)[:10],False)
print(f"{len(syms)} symbols, PSAR af=({AFS},{AFM}), oversold=rsi<{OS}, nonbull, N={N}",flush=True)

acc={}
def bump(tag,lift,ne):
    a=acc.get(tag)
    if a is None: acc[tag]=a=[0.,0.,0,0]
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
def estart(m): return m&~np.concatenate([[False],m[:-1]])

for i,sym in enumerate(syms):
    if i%300==0: print(f"  {i}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy(); rsi=talib.RSI(c,14)
    sar=talib.SAR(h,l,AFS,AFM); above=c>sar
    nonbull=~np.array([isbull(x) for x in dts])
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&((atr/np.where(c>0,c,np.nan))>=VOL_FLOOR)
    res,valid=bracket(h,l,c,atr); base=elig&valid&~np.isnan(res)&nonbull
    if base.sum()<MIN_BASE: continue
    bmean=res[base].mean()
    flip=above&~np.concatenate([[False],above[:-1]]); os=rsi<OS
    sigs={"A_psar_up":flip,"B_psar&os":flip&os,"C_psar&~os":flip&~os,
          "D_oversold":estart(os),"E_os&~psar_recent":estart(os)& ~above}
    for tag,m in sigs.items():
        s=estart(m)&base; ne=int(s.sum())
        if ne>=1: bump(tag,res[s].mean()-bmean,ne)

def rep(tag):
    a=acc.get(tag)
    if not a or a[2]<30: return None
    sL,ss,ns,ne=a; m=sL/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5; t=m/se if se>0 else 0
    return m,t,ns,ne

print("\n==== PSAR incremental decomposition (nonbull, lift vs random) ====")
labels={"A_psar_up":"psar flip-up (raw)","B_psar&os":"psar-flip AND oversold",
        "C_psar&~os":"psar-flip AND NOT oversold  <-- THE TEST","D_oversold":"oversold rsi<30 (the kept factor)",
        "E_os&~psar_recent":"oversold AND not-above-SAR"}
for tag in ["A_psar_up","B_psar&os","C_psar&~os","D_oversold","E_os&~psar_recent"]:
    r=rep(tag)
    if r: m,t,ns,ne=r; print(f"  {labels[tag]:42} lift={m:+.4f}R  t={t:+.1f}  n_sym={ns:<4} n_ep={ne}")
    else: print(f"  {labels[tag]:42} (n<30)")
print("\n  Verdict: if C (psar & NOT oversold) ~ 0 -> PSAR edge = oversold overlap -> REMOVABLE.")
