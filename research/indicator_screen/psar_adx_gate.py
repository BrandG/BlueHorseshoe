"""Wilder's canonical pairing: trust PSAR only when ADX is strong AND +DI>-DI.

Tests the FULL textbook gate (not just ADX magnitude, which I tested before and which
flipped sign across halves). Signal = PSAR flip-up AND ADX(14)>thr AND +DI>-DI.
Sweep thr in {20,25,30}. Clean harness (ATR 2:1 runner, vol floor, episode-start,
symbol-clustered), edge vs random baseline, TIME-SPLIT as the stability gate.
Compares gated vs ungated PSAR flip to see whether the ADX+DI gate rescues it.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"; SPLIT="2021-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
N=10; TP_ATR,SL_ATR=2.0,1.0; MIN_BASE=15; THRS=[20,25,30]

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg.get(str(d)[:10],False)
print(f"{len(syms)} symbols",flush=True)
def estart(m): return m&~np.concatenate([[False],m[:-1]])
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

acc={}
def bump(var,rk,half,lift,ne):
    k=(var,rk,half); a=acc.get(k)
    if a is None: acc[k]=a=[0.,0.,0,0]
    a[0]+=lift;a[1]+=lift*lift;a[2]+=1;a[3]+=ne

for i,sym in enumerate(syms):
    if i%300==0: print(f"  {i}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy(); atr_pct=atr/np.where(c>0,c,np.nan)
    adx=talib.ADX(h,l,c,14); pdi=talib.PLUS_DI(h,l,c,14); mdi=talib.MINUS_DI(h,l,c,14)
    flip=estart(c>talib.SAR(h,l,0.02,0.2)); diok=pdi>mdi
    bull=np.array([isbull(x) for x in dts]); h1=dts<SPLIT
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    res,valid=bracket(h,l,c,atr); base0=elig&valid&~np.isnan(res)
    variants={"flip(raw)":flip, "flip+DI":flip&diok}
    for thr in THRS: variants[f"flip+ADX>{thr}+DI"]=flip&(adx>thr)&diok
    for rk,rm in (("all",np.ones(n,bool)),("bull",bull),("nonbull",~bull)):
        for half,hm in (("ALL",np.ones(n,bool)),("H1",h1),("H2",~h1)):
            b=base0&rm&hm
            if b.sum()<MIN_BASE: continue
            bmean=res[b].mean()
            for var,sig in variants.items():
                s=sig&b; ne=int(s.sum())
                if ne>=1: bump(var,rk,half,res[s].mean()-bmean,ne)

def st(var,rk,half):
    a=acc.get((var,rk,half))
    if not a or a[2]<40: return None
    sL,ss,ns,ne=a; m=sL/ns; var_=max(ss/ns-m*m,0); se=(var_/ns)**0.5
    return m,(m/se if se>0 else 0),ns,ne
def fmt(x): return f"{x[0]:+.3f}R(t{x[1]:+.1f})" if x else "    --"

VARS=["flip(raw)","flip+DI"]+[f"flip+ADX>{t}+DI" for t in THRS]
for rk in ("all","bull","nonbull"):
    print(f"\n############ regime={rk}  (PSAR flip-up edge vs random; time-split) ############")
    print(f"  {'variant':18} | {'ALL':>15} | {'H1 16-20':>14} | {'H2 21-26':>14} | n_sym  stable?")
    for var in VARS:
        A=st(var,rk,"ALL"); H1=st(var,rk,"H1"); H2=st(var,rk,"H2")
        if not A: print(f"  {var:18} | (n<40)"); continue
        stable=H1 and H2 and H1[0]>0 and H2[0]>0 and H1[1]>1.5 and H2[1]>1.5 and A[1]>2
        print(f"  {var:18} | {fmt(A):>15} | {fmt(H1):>14} | {fmt(H2):>14} | {A[2]:<5} {'<== STABLE' if stable else ''}")
print("\n  (gate helps only if a +ADX+DI row is positive & significant in BOTH halves where raw flip is not)")
