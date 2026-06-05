"""Deep-oversold persistence: is the depth edge era-stable and broad, or 3 crash V-bottoms?

VIEW 2 of rsi_oversold_production.py showed forward return rises monotonically with how long RSI
has been below 30 (onset~0 -> 6+ bars = +0.44R nonbull t13). This decides whether that's real:

  RULE: "enter when RSI has been <30 for >= THR bars, AND flat; hold N." Production-spaced.
  For THR in {1,3,6}, regimes all/bull/nonbull:
    - clustered lift vs random-day baseline
    - TIME-SPLIT H1 2016-20 / H2 2021-26 (does DEPTH flip sign like onset did?)
    - CONCENTRATION: distinct symbols; share of entries in the top-3 calendar months;
      mean lift with the single biggest month removed (kills the COVID/2022-bottom artifact worry)
"""
import numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"; SPLIT="2021-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; N=10; TP_ATR,SL_ATR=2.0,1.0; MIN_BASE=15; THRS=[1,3,6]

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg.get(str(d)[:10],False)
print(f"{len(syms)} symbols, hold N={N}, bracket {TP_ATR:.0f}:{SL_ATR:.0f}, thresholds={THRS}",flush=True)

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

def sim(cand,n):
    out=[]; in_until=-1
    for i in np.where(cand)[0]:
        if i<=in_until: continue
        out.append(i); in_until=i+N
    return out

acc=defaultdict(lambda:[0.,0.,0,0])   # (thr,rk[,half]) -> sumLift,sumsqLift,nsym,ntr
months=defaultdict(lambda:defaultdict(float)) # (thr,rk) -> ym -> count
month_sumR=defaultdict(lambda:defaultdict(float))
symset=defaultdict(set)
glob=defaultdict(lambda:[0.,0])  # (thr,rk)-> [sumR,n] global for biggest-month-removed calc

for ii,sym in enumerate(syms):
    if ii%300==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    bull=np.array([isbull(x) for x in dts]); h1=dts<SPLIT
    res,valid=bracket(h,l,c,atr,N,TP_ATR,SL_ATR); ok=elig&valid&~np.isnan(res)
    os=rsi<OS
    age=np.full(n,-1,int); run=0
    for i in range(n):
        if os[i]: age[i]=run; run+=1
        else: run=0
    for rk,rmask in (("all",np.ones(n,bool)),("bull",bull),("nonbull",~bull)):
        base=ok&rmask
        if base.sum()<MIN_BASE: continue
        bmean=res[base].mean()
        for thr in THRS:
            cand=ok&rmask&(age>=thr)
            ent=sim(cand,n)
            if not ent: continue
            rs=np.array([res[i] for i in ent])
            a=acc[(thr,rk)]; lift=rs.mean()-bmean
            a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=len(ent)
            symset[(thr,rk)].add(sym)
            g=glob[(thr,rk)]; g[0]+=rs.sum(); g[1]+=len(ent)
            for i,r in zip(ent,rs):
                ym=dts[i][:7]; months[(thr,rk)][ym]+=1; month_sumR[(thr,rk)][ym]+=r
            # time-split
            for half,hm in (("H1",h1),("H2",~h1)):
                eh=[i for i in ent if hm[i]]
                bh=ok&rmask&hm
                if eh and bh.sum()>=MIN_BASE:
                    rsh=np.array([res[i] for i in eh]); lh=rsh.mean()-res[bh].mean()
                    k=(thr,rk,half); aa=acc[k]; aa[0]+=lh; aa[1]+=lh*lh; aa[2]+=1; aa[3]+=len(eh)

def stat(key):
    a=acc.get(key)
    if not a or a[2]<30: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt

print("\n############### DEPTH RULE: lift vs random + era-split (clustered) ###############")
print(f"  {'thr':>3} {'regime':>8} | {'full':>20} | {'H1 16-20':>18} | {'H2 21-26':>18}  era")
for thr in THRS:
    for rk in ("all","bull","nonbull"):
        f=stat((thr,rk)); h1=stat((thr,rk,"H1")); h2=stat((thr,rk,"H2"))
        def F(x): return f"{x[0]:+.4f}R t={x[1]:+.1f}" if x else "(n<30)"
        era="" if not(h1 and h2) else ("ROBUST same-sign" if np.sign(h1[0])==np.sign(h2[0]) else "flips")
        ntr=f[3] if f else 0
        print(f"  {thr:>3} {rk:>8} | {F(f):>20} | {F(h1):>18} | {F(h2):>18}  {era}")

print("\n############### CONCENTRATION (is deep-oversold just COVID/2022 bottoms?) ###############")
print(f"  {'thr':>3} {'regime':>8} | {'nsym':>5} {'ntr':>6} | {'top3-mo share':>13} | {'mean R':>9} {'minus top mo':>12}")
for thr in THRS:
    for rk in ("all","bull","nonbull"):
        mo=months.get((thr,rk));
        if not mo: continue
        ntr=sum(mo.values());
        if ntr<100: continue
        top3=sorted(mo.values(),reverse=True)[:3]; share=sum(top3)/ntr
        nsym=len(symset[(thr,rk)])
        g=glob[(thr,rk)]; meanR=g[0]/g[1]
        # remove single biggest-count month
        bigmo=max(mo,key=mo.get)
        rem_n=g[1]-mo[bigmo]; rem_sum=g[0]-month_sumR[(thr,rk)][bigmo]
        remR=rem_sum/rem_n if rem_n>0 else float('nan')
        print(f"  {thr:>3} {rk:>8} | {nsym:>5} {ntr:>6} | {share*100:>11.1f}% | {meanR:>+8.4f}R {remR:>+11.4f}R")
print("  [top3-mo share low + meanR ~ minus-top-mo => broad, not a few crash months]")
