"""CRASH-AWARE EXIT on DeepOS — cut the hold when the BROAD MARKET keeps falling after entry.

The arc's verdict: 3 entry-time crash signals (VIX level, VIX direction, oversold breadth) ALL fail the
same way — 2018 V-bottom and 2020 knife are indistinguishable at entry. The 2020 damage accrued HOLDING
10 days through a continuing crash. Unlike entry, the EXIT can use post-entry info: by hold-day 3-4 the
path reveals itself (2020 kept falling; 2018 had turned). So an exit rule can separate them where an
entry rule structurally cannot.

Rule: each hold morning, if SPY has drawn down > T from the entry-day level (measured through the prior
close), FLATTEN at that day's open. Competes with TP/SL (open-priority: you flatten at the open before
watching intraday). No same-day bail (k>=2). Faithful: signal from close[k-1], act at open[k].

SUCCESS (the test the entry probes failed): does the market-exit (1) RESCUE 2020 AND (2) leave 2018 +
normal years intact (near-zero touch there)? A surgical exit should barely fire outside crashes. Reported:
absolute book R per policy (NW t), YEAR-by-year, and TOUCH RATE (fraction of fires the exit closed).

Harness = locked (deepos_vix_*): SEED=7 N=2000; DeepOS rsi<30 & age>=3; next-open entry + gap-stop;
S4 tiered cost; nonbull vs all; NW (Bartlett L=hold-1) on ABSOLUTE book R (exit-policy compare, not vs random).
"""
import os, numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; AGE=3; N=10; TP_ATR,SL_ATR=2.0,1.0
THRESH={"mex5":0.05,"mex8":0.08,"mex3":0.03}     # SPY drawdown-from-entry exit thresholds
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
spy_map=dict(zip(spy.date.astype(str).str[:10],spy.close.astype(float)))
def isbull(d): return reg_map.get(str(d)[:10],False)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300 ORDER BY symbol",[START]).df().symbol.tolist()
syms=[s for s in syms if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=sorted(rng.choice(syms,N_SYMBOLS,replace=False))

def run(entry,atr,o,h,l,c,spy_at,T):
    """Bracket with optional crash-aware market exit. T=None => baseline (TP/SL/timeout only)."""
    n=len(c); tp=entry+TP_ATR*atr; sl=entry-SL_ATR*atr; Rp=SL_ATR*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan); mfired=np.zeros(n,bool)
    valid=(np.arange(n)<(n-N-1))&(atr>0)&~np.isnan(atr)&~np.isnan(entry)
    spy_ref=spy_at  # SPY close on the signal bar i
    for k in range(1,N+1):
        opk=np.full(n,np.nan); opk[:n-k]=o[k:]
        hk=np.full(n,np.nan); hk[:n-k]=h[k:]; lk=np.full(n,np.nan); lk[:n-k]=l[k:]
        if T is not None and k>=2:
            spc_prev=np.full(n,np.nan); spc_prev[:n-(k-1)]=spy_at[(k-1):]   # SPY close at bar i+k-1
            dd=spc_prev/spy_ref-1.0
            mex=valid&~resolved&~np.isnan(dd)&(dd<-T)
            res[mex]=(opk[mex]-entry[mex])/Rp[mex]; mfired|=mex; resolved|=mex
        tph=hk>=tp; slh=lk<=sl; live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        sfill=np.where(opk<=sl,opk,sl)
        res[loss]=(sfill[loss]-entry[loss])/Rp[loss]; res[wn]=TP_ATR/SL_ATR; resolved|=(loss|wn)
    exitc=np.full(n,np.nan); exitc[:n-N]=c[N:][:n-N]
    to=valid&~resolved; res[to]=(exitc[to]-entry[to])/Rp[to]
    return res,valid,mfired
def dv_cost_bp(dv): return 50.0 if dv<1e6 else 25.0 if dv<5e6 else 12.0 if dv<25e6 else 6.0
NWd={}; TOUCH={}
def make_w(L): return np.array([1.0-j/(L+1) for j in range(L+1)])
def bumpNW(k,u,m):   # u already absolute book R (baseline 0)
    a=NWd.setdefault(k,np.zeros(3+N)); a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    for j in range(1,N): a[2+j]+=float(u[:-j]@u[j:])
POLICIES=["base"]+list(THRESH)

for ii,sym in enumerate(syms):
    if ii%200==0: print(f"  {ii}/{len(syms)}",flush=True)
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
    spy_at=np.array([spy_map.get(x,np.nan) for x in dts])
    ctier=np.array([dv_cost_bp(x) for x in np.nan_to_num(dv20)])/1e4/(SL_ATR*atr_pct)
    for pol in POLICIES:
        T=None if pol=="base" else THRESH[pol]
        rg,_,mf=run(nxo,atr,o,h,l,c,spy_at,T)
        res=rg-ctier
        for reg in ("nonbull","all"):
            rmask=nonbull if reg=="nonbull" else np.ones(n,bool)
            ok=deepos&elig&~np.isnan(res)&rmask
            fidx=np.where(ok)[0]
            if len(fidx)>=5:
                u=np.zeros(n); u[fidx]=res[fidx]; bumpNW((pol,reg),u,len(fidx))
                t=TOUCH.setdefault((pol,reg),[0,0]); t[0]+=int(mf[fidx].sum()); t[1]+=len(fidx)
                if reg=="nonbull":
                    for Y in np.unique(np.array([dts[j2][:4] for j2 in fidx])):
                        yi=fidx[np.array([dts[j2][:4]==Y for j2 in fidx])]
                        if len(yi)>=8:
                            uy=np.zeros(n); uy[yi]=res[yi]; bumpNW((pol,reg,Y),uy,len(yi))
                            tt=TOUCH.setdefault((pol,reg,Y),[0,0]); tt[0]+=int(mf[yi].sum()); tt[1]+=len(yi)

def stNW(k,minf=30):
    a=NWd.get(k)
    if a is None or a[1]<minf: return None
    L=N-1; W=make_w(L); S,M=a[0],a[1]; G=a[2:2+1+L]; varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def fR(x): return f"{x[0]:+.3f}R t{x[1]:+.1f} n{x[2]}" if x else "(thin)"
def tch(k):
    t=TOUCH.get(k); return f"{100*t[0]/t[1]:.0f}%" if (t and t[1]) else "--"

for reg in ("nonbull","all"):
    print(f"\n################ EXIT-POLICY book R (S4) — regime={reg} ################")
    for pol in POLICIES:
        lbl=pol if pol=="base" else f"{pol} (SPY dd>{int(THRESH[pol]*100)}%)"
        print(f"   {lbl:18} {fR(stNW((pol,reg))):>22}   touch {tch((pol,reg))}")

print(f"\n################ YEAR-BY-YEAR book R (nonbull S4) — RESCUE 2020 w/o wrecking 2018? (touch% in parens) ################")
hdr="  "+f"{'year':>6} | "+" | ".join(f"{p:>16}" for p in POLICIES)
print(hdr)
for y in [str(x) for x in range(2016,2027)]:
    cells=[]
    for p in POLICIES:
        s=stNW((p,"nonbull",y),minf=8)
        cells.append(f"{s[0]:+.3f}({tch((p,'nonbull',y))})n{s[2]}" if s else "(thin)")
    print("  "+f"{y:>6} | "+" | ".join(f"{c:>16}" for c in cells))
print("\ndone.")
