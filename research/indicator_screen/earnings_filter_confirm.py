"""CONFIRMATION: combined earnings knife-filter on DeepOS — aggregate lift, year-stability, HA-overlap.

From earnings_angles: post-MISS (≤20d after, −0.129R t−2.6) and PRE-earnings (≤5-10d before, −0.14R) are
real faithful knives inside DeepOS. Here we test combined FILTERS as one deployable mask and measure the
FILTERED-BOOK aggregate lift (the deploy-relevant number my too-narrow ±10d 'clean' cell missed):
  F1 = (next earn ≤10d) OR (miss ≤20d)        [proposed]
  F2 = (next ≤10d) OR (ANY earnings ≤20d)     [broader: both miss & beat were neg at 10-20d]
  F3 = (miss ≤20d) only                        [post-miss only]
  F4 = (next ≤5d) OR (miss ≤20d)               [tighter proximity]
For each: knife (excluded) R, filtered-book R, lift vs base, % volume retained. Then year-by-year (does it
dodge 2020/2022?) and HA-sleeve overlap (does DeepOS+HA already avoid earnings knives, like it did gaps?).
Faithful next-open+gapstop+tiered-cost (S4) + S2 gross. NW vs random. earnings-covered pinned-2000, hold10.
"""
import numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; AGE=3; N=10; TP_ATR,SL_ATR=2.0,1.0
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg_map.get(str(d)[:10],False)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300 ORDER BY symbol",[START]).df().symbol.tolist()
syms=[s for s in syms if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=sorted(rng.choice(syms,N_SYMBOLS,replace=False))
edf=duckdb.connect().execute("SELECT symbol,reportedDate,reportTime,surprise FROM read_parquet('data/earnings.parquet') WHERE reportedDate>='2015-06-01'").df()
ED=defaultdict(list)
for r in edf.itertuples(index=False):
    try: sp=float(r.surprise)
    except: sp=np.nan
    ED[r.symbol].append((r.reportedDate,r.reportTime,sp))
covered=[s for s in syms if s in ED]
print(f"covered {len(covered)}",flush=True)

def run(entry,atr,o,h,l,c,gap):
    n=len(c); tp=entry+TP_ATR*atr; sl=entry-SL_ATR*atr; Rp=SL_ATR*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan)
    valid=(np.arange(n)<(n-N-1))&(atr>0)&~np.isnan(atr)&~np.isnan(entry)
    for k in range(1,N+1):
        hk=np.full(n,np.nan); hk[:n-k]=h[k:]; lk=np.full(n,np.nan); lk[:n-k]=l[k:]; okp=np.full(n,np.nan); okp[:n-k]=o[k:]
        tph=hk>=tp; slh=lk<=sl; live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        sfill=np.where(okp<=sl,okp,sl) if gap else sl
        res[loss]=((sfill[loss] if gap else sl[loss])-entry[loss])/Rp[loss]; res[wn]=TP_ATR/SL_ATR; resolved|=(loss|wn)
    exitc=np.full(n,np.nan); exitc[:n-N]=c[N:][:n-N]
    to=valid&~resolved; res[to]=(exitc[to]-entry[to])/Rp[to]
    return res,valid
def dv_cost_bp(dv): return 50.0 if dv<1e6 else 25.0 if dv<5e6 else 12.0 if dv<25e6 else 6.0
NWd={}
def make_w(L): return np.array([1.0-j/(L+1) for j in range(L+1)])
def bumpNW(k,u,m):
    a=NWd.setdefault(k,np.zeros(3+N)); a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    for j in range(1,N): a[2+j]+=float(u[:-j]@u[j:])

for ii,sym in enumerate(covered):
    if ii%200==0: print(f"  {ii}/{len(covered)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    dv20=pd.Series(c*v).rolling(20).mean().to_numpy(); atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    nonbull=~np.array([isbull(x) for x in dts])
    osr=rsi<OS; age=np.zeros(n,int)
    for i in range(1,n): age[i]=age[i-1]+1 if osr[i] else 0
    deepos=osr&(age>=AGE)
    nxo=np.full(n,np.nan); nxo[:n-1]=o[1:]
    hac=(o+h+l+c)/4.0; hao=np.empty(n); hao[0]=(o[0]+c[0])/2
    for i in range(1,n): hao[i]=(hao[i-1]+hac[i-1])/2
    hg=hac>hao
    react={}
    for (D,rt,sp) in ED[sym]:
        if D<dts[0] or D>dts[-1]: continue
        idx=int(np.searchsorted(dts,D,side=("left" if rt=="pre-market" else "right")))
        if 0<=idx<n: react[idx]=np.sign(sp) if not np.isnan(sp) else np.nan
    rset=set(react); since=np.full(n,10**9); lastsign=np.full(n,np.nan); last=-10**9; ls=np.nan
    for i in range(n):
        if i in rset: last=i; ls=react[i]
        since[i]=i-last; lastsign[i]=ls
    nxt=np.full(n,10**9); cur=10**9
    for i in range(n-1,-1,-1):
        cur=0 if i in rset else (cur+1 if cur<10**9 else 10**9); nxt[i]=cur
    miss20=(since<=20)&(lastsign<0); any20=(since<=20); nx10=(nxt<=10); nx5=(nxt<=5)
    F={"F1":nx10|miss20,"F2":nx10|any20,"F3":miss20,"F4":nx5|miss20}
    CELLS={"deepos":deepos,"RANDOM":np.ones(n,bool),"HA":deepos&hg}
    for k,m in F.items():
        CELLS[f"{k}_knife"]=deepos&m; CELLS[f"{k}_filt"]=deepos&~m
    CELLS["HA_F1filt"]=deepos&hg&~F["F1"]; CELLS["HA_F1knife"]=deepos&hg&F["F1"]
    rg,_=run(nxo,atr,o,h,l,c,True); ctier=np.array([dv_cost_bp(x) for x in np.nan_to_num(dv20)])/1e4/(SL_ATR*atr_pct)
    RES={"S2":rg,"S4":rg-ctier}
    for reg in ("nonbull","all"):
        rmask=nonbull if reg=="nonbull" else np.ones(n,bool)
        for scn in ("S2","S4"):
            res=RES[scn]; ok=elig&~np.isnan(res)&rmask
            if ok.sum()<20: continue
            bmean=res[ok].mean()
            for cn,cm in CELLS.items():
                fidx=np.where(cm&ok)[0]
                if len(fidx)>=5:
                    u=np.zeros(n); u[fidx]=res[fidx]-bmean; bumpNW((cn,reg,scn),u,len(fidx))
                    if scn=="S4" and reg=="nonbull" and cn in ("deepos","F1_filt","F2_filt"):
                        for Y in np.unique(np.array([dts[j][:4] for j in fidx])):
                            yi=fidx[np.array([dts[j][:4]==Y for j in fidx])]
                            if len(yi)>=8:
                                uy=np.zeros(n); uy[yi]=res[yi]-bmean; bumpNW((cn,reg,scn,Y),uy,len(yi))

def stNW(k,minf=30):
    a=NWd.get(k)
    if a is None or a[1]<minf: return None
    L=N-1; W=make_w(L); S,M=a[0],a[1]; G=a[2:2+1+L]; varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def fR(x): return f"{x[0]:+.3f}R t{x[1]:+.1f} n{x[2]}" if x else "(thin)"

for reg in ("nonbull","all"):
    b=stNW(("deepos",reg,"S4")); base=b[0] if b else None; bn=b[2] if b else 1
    print(f"\n################ COMBINED FILTER — regime={reg}  [deepos base S4 {fR(b)}] ################")
    print(f"  {'filter':6} {'KNIFE(excluded) S4':>24} {'FILTERED-BOOK S4':>24} {'liftS4':>8} {'%vol kept':>9}")
    for k in ("F1","F2","F3","F4"):
        kn=stNW((f"{k}_knife",reg,"S4")); ft=stNW((f"{k}_filt",reg,"S4"))
        lift=f"{ft[0]-base:+.3f}" if (ft and base is not None) else "--"
        keep=f"{100*ft[2]/bn:.0f}%" if ft else "--"
        defn={"F1":"next≤10|miss≤20","F2":"next≤10|any≤20","F3":"miss≤20","F4":"next≤5|miss≤20"}[k]
        print(f"  {k:6} {fR(kn):>24} {fR(ft):>24} {lift:>8} {keep:>9}   [{defn}]")

print("\n################ HA-SLEEVE OVERLAP (does DeepOS+HA already avoid earnings knives?) ################")
for reg in ("nonbull","all"):
    ha=stNW(("HA",reg,"S4")); haf=stNW(("HA_F1filt",reg,"S4")); hak=stNW(("HA_F1knife",reg,"S4"))
    print(f"  {reg:8} HA-sleeve {fR(ha):>22} | HA & F1-filtered {fR(haf):>22} | HA & F1-KNIFE {fR(hak):>20}")

print("\n################ YEAR-BY-YEAR (nonbull S4): base vs F1-filtered vs F2-filtered ################")
print(f"  {'year':>6} | {'deepos base':>20} | {'F1-filtered':>20} | {'F2-filtered':>20}")
for y in [str(x) for x in range(2016,2027)]:
    b=stNW(("deepos","nonbull","S4",y),minf=8); f1=stNW(("F1_filt","nonbull","S4",y),minf=8); f2=stNW(("F2_filt","nonbull","S4",y),minf=8)
    g=lambda s:(f"{s[0]:+.3f} n{s[2]}" if s else "(thin)")
    print(f"  {y:>6} | {g(b):>20} | {g(f1):>20} | {g(f2):>20}")
print("\ndone.")
