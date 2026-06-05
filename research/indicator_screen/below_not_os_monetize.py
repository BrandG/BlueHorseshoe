"""#3 — does the below_not_os cloud-dislocation cell MONETIZE?
Cell = price below Ichimoku cloud AND NOT rsi<30 (the era-robust, RSI-orthogonal selector).
Lift-vs-random is established (+11/-0 yrs all-regime). Now the tradeable questions, ABSOLUTE R:

  A. HOLD-HORIZON SWEEP — bracket TP2:SL1 with max-hold N in {5,10,15,20,30,40}, plus a pure
     time-exit (fwd return / ATR). Absolute mean R + Newey-West t (bandwidth = N-1) vs random.
     Does a longer hold turn the robust LIFT into a positive ABSOLUTE edge, and where does it peak?
  B. PERSISTENCE / DEPTH curves at hold=20 — forward R by bars-below-cloud (age) and by ATR-distance
     below cloud (depth). Rising => an empirical scale-in schedule.
  C. COST/LIQUIDITY STRESS at the best hold — next-OPEN entry + tiered round-trip cost, net R by
     dollar-volume tier. Survives as a real trade?

All-regime is the primary track; nonbull reported as the second track. Clean hygiene throughout
(test-ticker excl, close>0, vol floor, $vol floor, gap-skip on the hold path).
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; DOLLAR_VOL=1_000_000; GAP=0.50
DISP=26; TP_ATR,SL_ATR=2.0,1.0
HOLDS=[5,10,15,20,30,40]; MAXLAG=max(HOLDS)-1
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg_map.get(str(d)[:10],False)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
syms=[s for s in syms if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"{len(syms)} symbols",flush=True)
rmx=lambda x,w: pd.Series(x).rolling(w).max().to_numpy(); rmn=lambda x,w: pd.Series(x).rolling(w).min().to_numpy()

# NW accumulator with autocovariances up to MAXLAG; stNW slices to the horizon's bandwidth.
NW={}
def bumpNW(k,u,m):
    a=NW.get(k)
    if a is None: a=NW[k]=np.zeros(2+MAXLAG+1)  # [S, M, G0..G_MAXLAG]
    a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    nz=np.nonzero(u)[0]
    if len(nz)==0: return
    lo,hi=nz[0],nz[-1]
    for j in range(1,MAXLAG+1):
        if hi-lo<j: break
        a[2+j]+=float(u[lo:hi+1-j]@u[lo+j:hi+1])
def stNW(k,bw):
    a=NW.get(k)
    if a is None or a[1]<50: return None
    S,M=a[0],a[1]; G=a[2:]
    w=np.array([1.0-j/(bw+1) for j in range(1,bw+1)])
    varS=G[0]+2.0*float(np.dot(w,G[1:bw+1]))
    if varS<=0: return None
    return S/M,(S/np.sqrt(varS)),int(M)

# simple clustered (per-symbol) accumulator for B/C
C={}
def bumpC(k,v,nt):
    a=C.setdefault(k,[0.,0.,0,0]); a[0]+=v; a[1]+=v*v; a[2]+=1; a[3]+=nt
def stC(k,minsym=30):
    a=C.get(k)
    if not a or a[2]<minsym: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt

def bracket_R(h,l,c,atr,N,tp_atr,sl_atr,badpath,entry_px):
    """Bracket from entry_px (close[t] or open[t+1]); resolve over next N bars. Returns R per bar."""
    n=len(c); tp=entry_px+tp_atr*atr; sl=entry_px-sl_atr*atr; Rp=sl_atr*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan)
    valid=(np.arange(n)<(n-N-1))&(atr>0)&~np.isnan(atr)&~badpath&~np.isnan(entry_px)
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        # bars k ahead of ENTRY day t (entry executes at t, path starts t+1 already in h/l indexing via shift)
        tph[:n-k]=h[k:]>=tp[:n-k]; slh[:n-k]=l[k:]<=sl[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=tp_atr/sl_atr; resolved|=(loss|wn)
    ex=np.full(n,np.nan)
    if n-N>0: ex[:n-N]=c[N:][:n-N]
    to=valid&~resolved; res[to]=(ex[to]-entry_px[to])/Rp[to]
    return res,valid

DEPTH=[("0-.5",0,.5),(".5-1.5",.5,1.5),("1.5-3",1.5,3.),("3+",3.,1e9)]
AGE=[("1-3",1,3),("4-10",4,10),("11-25",11,25),("26+",26,99999)]

for ii,sym in enumerate(syms):
    if ii%400==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    if n<300: continue
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan); dollar=c*vol20
    dmove=np.zeros(n); dmove[1:]=np.abs(c[1:]/np.where(c[:-1]>0,c[:-1],np.nan)-1.0); badday=dmove>GAP
    tk=(rmx(h,9)+rmn(l,9))/2; kj=(rmx(h,26)+rmn(l,26))/2
    sA=np.full(n,np.nan); sB=np.full(n,np.nan)
    sA[DISP:]=((tk+kj)/2)[:n-DISP]; sB[DISP:]=((rmx(h,52)+rmn(l,52))/2)[:n-DISP]
    bot=np.fmin(sA,sB); below=c<bot; os=rsi<30
    cell=below&~os
    depth=np.where(atr>0,(bot-c)/atr,np.nan)
    age=np.zeros(n,int); run=0
    for i in range(n):
        if below[i]: run+=1; age[i]=run
        else: run=0
    nonbull=~np.array([isbull(x) for x in dts])
    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)
    pos=(c>0)&(o>0)&(h>0)&(l>0)
    clean=base_price&pos&(atr_pct>=VOL_FLOOR)&(dollar>=DOLLAR_VOL)
    open_next=np.full(n,np.nan); open_next[:n-1]=o[1:]  # next-day open for cost track

    for N in HOLDS:
        badpath=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
        for t in range(n-N-1):
            if cs[t+N+1]-cs[t+1]>0: badpath[t]=True
        resB,valB=bracket_R(h,l,c,atr,N,TP_ATR,SL_ATR,badpath,c)           # bracket from close
        # pure time-exit in ATR units (fwd return / 1 ATR), same risk normalization
        teR=np.full(n,np.nan)
        if n-N>0: teR[:n-N]=(c[N:][:n-N]-c[:n-N])/(SL_ATR*atr[:n-N])
        for rk,rmask in (("all",np.ones(n,bool)),("nonbull",nonbull)):
            okB=clean&valB&~np.isnan(resB)&rmask
            okT=clean&~np.isnan(teR)&~badpath&rmask
            for label,outc,okm in (("brk",resB,okB),("te",teR,okT)):
                fidx=np.where(cell&okm)[0]
                if len(fidx)>=5:
                    u=np.zeros(n); u[fidx]=outc[fidx]; bumpNW((label,"cell",rk,N),u,len(fidx))
                ridx=np.where(okm)[0]
                if len(ridx)>=5:
                    u=np.zeros(n); u[ridx]=outc[ridx]; bumpNW((label,"rand",rk,N),u,len(ridx))

    # B: persistence & depth at hold=20 (bracket from close)
    N=20; badpath=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
    for t in range(n-N-1):
        if cs[t+N+1]-cs[t+1]>0: badpath[t]=True
    res20,val20=bracket_R(h,l,c,atr,N,TP_ATR,SL_ATR,badpath,c)
    for rk,rmask in (("all",np.ones(n,bool)),("nonbull",nonbull)):
        ok=clean&val20&~np.isnan(res20)&rmask
        for bn,lo,hi in AGE:
            m=cell&ok&(age>=lo)&(age<=hi)
            if m.any(): bumpC(("age",bn,rk),res20[m].mean(),int(m.sum()))
        for bn,lo,hi in DEPTH:
            m=cell&ok&(depth>=lo)&(depth<hi)
            if m.any(): bumpC(("depth",bn,rk),res20[m].mean(),int(m.sum()))
        # C: cost stress at hold=20, next-OPEN entry + tiered round-trip cost
        resO,valO=bracket_R(h,l,c,atr,N,TP_ATR,SL_ATR,badpath,open_next)
        okO=clean&valO&~np.isnan(resO)&rmask
        cost_bps=np.where(dollar>=25e6,5.0,np.where(dollar>=5e6,12.0,25.0))
        cost_R=(cost_bps/1e4)/np.where(atr_pct>0,atr_pct,np.nan)  # cost in ATR(=R) units
        net=resO-cost_R
        for tier,tlo,thi in (("liq>25M",25e6,1e18),("mid5-25M",5e6,25e6),("low1-5M",1e6,5e6)):
            m=cell&okO&(dollar>=tlo)&(dollar<thi)&~np.isnan(net)
            if m.any():
                bumpC(("cost_gross",tier,rk),resO[m].mean(),int(m.sum()))
                bumpC(("cost_net",tier,rk),net[m].mean(),int(m.sum()))

print("\n############### A. HOLD-HORIZON SWEEP — absolute mean R, Newey-West t ###############")
print("   bracket = TP2:SL1 max-hold N (tradeable) ; te = pure time-exit fwd/ATR (unconstrained reversion)")
for rk in ("all","nonbull"):
    print(f"\n  --- {rk} ---   below_not_os vs random   (does abs R go positive / peak?)")
    print(f"    {'hold':>5} | {'BRK cell':>18} {'BRK rand':>14} | {'TE cell':>18} {'TE rand':>14}")
    for N in HOLDS:
        bc=stNW(("brk","cell",rk,N),N-1); br=stNW(("brk","rand",rk,N),N-1)
        tc=stNW(("te","cell",rk,N),N-1); tr=stNW(("te","rand",rk,N),N-1)
        def f(x): return f"{x[0]:+.3f}R(t{x[1]:+.0f})" if x else "(thin)"
        print(f"    {N:>5} | {f(bc):>18} {f(br):>14} | {f(tc):>18} {f(tr):>14}")

print("\n############### B. PERSISTENCE & DEPTH (hold=20 bracket, abs R) ###############")
for rk in ("all","nonbull"):
    print(f"  --- {rk} ---")
    print("    age (bars below cloud):  "+"  ".join(f"{bn}:{(lambda x: f'{x[0]:+.3f}R(t{x[1]:+.0f})' if x else '.')(stC(('age',bn,rk)))}" for bn,_,_ in AGE))
    print("    depth (ATR below cloud): "+"  ".join(f"{bn}:{(lambda x: f'{x[0]:+.3f}R(t{x[1]:+.0f})' if x else '.')(stC(('depth',bn,rk)))}" for bn,_,_ in DEPTH))

print("\n############### C. COST/LIQUIDITY STRESS (hold=20, next-open entry, tiered round-trip) ###############")
for rk in ("all","nonbull"):
    print(f"  --- {rk} ---   gross -> NET after cost")
    for tier,_,_ in (("liq>25M",0,0),("mid5-25M",0,0),("low1-5M",0,0)):
        g=stC(("cost_gross",tier,rk)); ntt=stC(("cost_net",tier,rk))
        def f(x): return f"{x[0]:+.3f}R(t{x[1]:+.1f})" if x else "(thin)"
        print(f"    {tier:>10}: gross {f(g):>16}  ->  net {f(ntt):>16}")
print("\ndone.")
