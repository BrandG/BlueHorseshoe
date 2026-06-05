"""Re-run PSAR & ADX under the CORRECTED lens that rescued RSI-oversold.

The bias: episode-start de-overlap keeps only the ONSET bar of a persisting state. For RSI-oversold
that was the WORST bar (onset = farthest from the bounce); the edge lived DEEPER in the run and
de-overlap buried it. PSAR ('above SAR') and ADX ('strong uptrend') are also persisting STATES that
were de-overlapped to their onset (flip / cross). Same bias COULD have buried an edge -- or, since
these are trend-following longs and daily trend signals anti-predict, the gradient may be flat/down,
confirming the dead verdict for the right reason. MEASURE it.

Signals (long, persisting states; age = consecutive bars the state has held, 0 = onset):
  PSAR : close > SAR(0.02,0.2)
  ADX  : ADX(14) > 25  AND  +DI > -DI     (textbook strong-uptrend long)

Same clean ideal harness as rsi_oversold_production.py: close-entry ATR 2:1, hold 10, vol-floor,
symbol-clustered. VIEW A = edge by state-age (the litmus). VIEW B = production-sim (buy-if-flat,
hold N) at age>=THR, year-by-year + 3-era (COVID isolated).
"""
import numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
N=10; TP_ATR,SL_ATR=2.0,1.0; MIN_BASE=15
AGE_BUCKETS=[("onset(0)",0,0),("1-2",1,2),("3-5",3,5),("6+",6,99999)]

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg.get(str(d)[:10],False)
print(f"{len(syms)} syms, PSAR & ADX, ideal bracket {TP_ATR:.0f}:{SL_ATR:.0f} hold{N}",flush=True)

def bracket(h,l,c,atr):
    n=len(c); tp=c+TP_ATR*atr; sl=c-SL_ATR*atr; Rp=SL_ATR*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan)
    valid=(np.arange(n)<(n-N))&(atr>0)&~np.isnan(atr)
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp[:n-k]; slh[:n-k]=l[k:]<=sl[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=TP_ATR/SL_ATR; resolved|=(loss|wn)
    ex=np.full(n,np.nan); ex[:n-N]=c[N:][:n-N] if n-N>0 else ex[:n-N]
    to=valid&~resolved; res[to]=(ex[to]-c[to])/Rp[to]
    return res,valid
def age_of(state):
    a=np.full(len(state),-1,int); r=0
    for i in range(len(state)):
        if state[i]: a[i]=r; r+=1
        else: r=0
    return a
def sim(idx):
    out=[]; iu=-1
    for i in idx:
        if i<=iu: continue
        out.append(i); iu=i+N
    return out
def era_of(ym):
    if ym<"2020-03": return "1_pre-COVID"
    if ym<"2021-01": return "2_COVID2020"
    return "3_post2021"

IND=["PSAR","ADX"]
A=defaultdict(lambda:[0.,0.,0,0])   # (ind,bucket,regime) -> clustered lift
B=defaultdict(lambda:[0.,0.,0,0])   # (ind,thr,bucket) -> clustered lift (all regime)
def bump(store,k,lift,nt):
    a=store[k]; a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt

for ii,sym in enumerate(syms):
    if ii%300==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    res,valid=bracket(h,l,c,atr); ok=elig&valid&~np.isnan(res)
    bull=np.array([isbull(x) for x in dts])
    sar=talib.SAR(h,l,0.02,0.2); adx=talib.ADX(h,l,c,14)
    pdi=talib.PLUS_DI(h,l,c,14); mdi=talib.MINUS_DI(h,l,c,14)
    states={"PSAR": c>sar, "ADX": (adx>25)&(pdi>mdi)}
    years=np.array([dts[i][:4] for i in range(n)])
    for ind in IND:
        st=np.asarray(states[ind],bool); age=age_of(st)
        # VIEW A: gradient by age x regime
        for rk,rmask in (("all",np.ones(n,bool)),("bull",bull),("nonbull",~bull)):
            base=ok&rmask
            if base.sum()<MIN_BASE: continue
            bmean=res[base].mean()
            for bname,lo,hi in AGE_BUCKETS:
                m=base&st&(age>=lo)&(age<=hi)
                if m.any(): bump(A,(ind,bname,rk), res[m].mean()-bmean, int(m.sum()))
        # VIEW B: production sim at age>=THR, year + era (all regime)
        ybase={y:(res[ok&(years==y)].mean() if (ok&(years==y)).sum()>=MIN_BASE else None) for y in np.unique(years)}
        ebase={}
        eras=np.array([era_of(x[:7]) for x in dts])
        for e in ("1_pre-COVID","2_COVID2020","3_post2021"):
            mm=ok&(eras==e); ebase[e]=res[mm].mean() if mm.sum()>=MIN_BASE else None
        for thr in (0,3):
            ent=sim(np.where(ok&(age>=thr))[0])
            if not ent: continue
            byy=defaultdict(list); bye=defaultdict(list)
            for i in ent: byy[dts[i][:4]].append(res[i]); bye[era_of(dts[i][:7])].append(res[i])
            for y,rs in byy.items():
                if ybase.get(y) is not None: bump(B,(ind,thr,y), np.mean(rs)-ybase[y], len(rs))
            for e,rs in bye.items():
                if ebase.get(e) is not None: bump(B,(ind,thr,"E_"+e), np.mean(rs)-ebase[e], len(rs))

def stat(store,k):
    a=store.get(k)
    if not a or a[2]<20: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt

for ind in IND:
    print(f"\n################################  {ind}  ################################")
    print("VIEW A — edge by state-age (litmus: rising+positive => de-overlap buried an edge)")
    print(f"  {'age':>10} | " + " | ".join(f"{rk:>18}" for rk in ("all","bull","nonbull")))
    for bname,_,_ in AGE_BUCKETS:
        cells=[]
        for rk in ("all","bull","nonbull"):
            x=stat(A,(ind,bname,rk)); cells.append(f"{x[0]:+.4f}R t{x[1]:+.1f}" if x else "(thin)")
        print(f"  {bname:>10} | " + " | ".join(f"{c:>18}" for c in cells))
    print("VIEW B — production-sim lift vs random (all regime), by ERA & year")
    for thr in (0,3):
        print(f"  --- age>={thr} (THR={thr}) ---")
        for e in ("E_1_pre-COVID","E_2_COVID2020","E_3_post2021"):
            x=stat(B,(ind,thr,e)); print(f"      {e:>16}: {f'{x[0]:+.4f}R t{x[1]:+.1f} n{x[3]}' if x else '(thin)'}")
        ys=[stat(B,(ind,thr,str(y))) for y in range(2016,2027)]
        pos=sum(1 for s in ys if s and s[0]>0); tot=sum(1 for s in ys if s)
        line=" ".join(f"{y}:{(s[0]>0 and '+' or '-') if s else '.'}" for y,s in zip(range(2016,2027),ys))
        print(f"      years +/-: {line}   ({pos}/{tot} positive)")
