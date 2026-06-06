"""PSAR & ADX re-audit under the NEWEY-WEST standard + age-gating (the 'same second look').

Why this exists: PSAR was declared 'fully closed' and ADX 'weak, fails time-split' — but BOTH
verdicts rested on episode-start DE-OVERLAP, which we proved (2026-06-05) is BIASED for persisting
states: it keeps only the ONSET bar and discards the deeper-in-run bars where mean-reversion edge
actually lives. That same bias read rsi_oversold as ~zero (deov) when keeping all firings + NW
flipped it firmly positive, and resurrected below_cloud (deov t1.1 -> NW t2.4). PSAR ('above SAR')
and ADX ('strong uptrend') are persisting states de-overlapped to their onset — so they deserve the
identical treatment before the dead verdict stands.

Method = clean_harness.py PASS 2, byte-identical machinery (bracket TP2:SL1 hold10, vol floor,
$-vol floor, gap-skip, symbol-cluster, test-ticker exclusion, SEED/N_SYMBOLS), three columns:
  DE-OVERLAP (production-faithful, onset-only) | FULL-POP cluster (every firing) | FULL-POP Newey-West
plus the AGE GRADIENT (onset / 1-2 / 3-5 / 6+ bars-in-state), each with its own NW-honest t — this is
the litmus: a FLAT/DOWN gradient confirms 'dead for the right reason' (trend-following long, daily
returns mean-revert); a RISING+positive gradient means de-overlap buried an edge (the rsi_oversold
pattern). RANDOM row is the sanity floor (~0R, t~0).

Signals (long, persisting states):
  PSAR        : close > SAR(0.02, 0.2)
  ADX25_diUp  : ADX(14) > 25  AND  +DI(14) > -DI(14)          [textbook strong-uptrend long]
  ADX25_p21   : ADX(21) > 25                                   [the cleaned-sweep 'only survivor', DI-off]
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; DOLLAR_VOL=1_000_000; GAP=0.50
BR_N=10; TP_ATR,SL_ATR=2.0,1.0
YEARS=[str(y) for y in range(2016,2027)]
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")
AGE_BUCKETS=[("onset0",0,0),("age1-2",1,2),("age3-5",3,5),("age6+",6,99999)]

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg_map.get(str(d)[:10],False)

syms=con.execute("""SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300""",[START]).df().symbol.tolist()
syms=[s for s in syms if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"{len(syms)} symbols (test tickers pre-excluded)",flush=True)

# ---- accumulators (identical structure to clean_harness) ----
B={}                              # de-overlap: (name,regime) -> [sum,sumsq,nsym,ntr]
def bumpB(k,lift,nt):
    a=B.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
BF={}                            # full-pop cluster: (name,regime[,bucket/year]) -> [sum,sumsq,nsym,ntr]
def bumpF(k,lift,nt):
    a=BF.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
L_NW=BR_N-1
NW_W=np.array([1.0-j/(L_NW+1) for j in range(L_NW+1)])   # Bartlett weight = true overlap fraction
NW={}                            # full-pop NW: key -> [S, M, G0..G_L]
def bumpNW(k,u,m):
    a=NW.setdefault(k,np.zeros(3+L_NW)); a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    for j in range(1,L_NW+1): a[2+j]+=float(u[:-j]@u[j:])

def bracket(h,l,c,atr,N,tp_atr,sl_atr,badpath):
    n=len(c); tp=c+tp_atr*atr; sl=c-sl_atr*atr; Rp=sl_atr*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan)
    valid=(np.arange(n)<(n-N))&(atr>0)&~np.isnan(atr)&~badpath
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp[:n-k]; slh[:n-k]=l[k:]<=sl[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=tp_atr/sl_atr; resolved|=(loss|wn)
    ex=np.full(n,np.nan)
    if n-N>0: ex[:n-N]=c[N:][:n-N]
    to=valid&~resolved; res[to]=(ex[to]-c[to])/Rp[to]
    return res,valid

def noov(mask,res,N):            # episode-start de-overlap (production-faithful)
    out=[];u=-1
    for i in np.where(mask&~np.isnan(res))[0]:
        if i<=u: continue
        out.append(i); u=i+N
    return out

def age_of(state):               # consecutive bars the state has held (0 = onset, -1 = off)
    a=np.full(len(state),-1,int); r=0
    for i in range(len(state)):
        if state[i]: a[i]=r; r+=1
        else: r=0
    return a

for ii,sym in enumerate(syms):
    if ii%400==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    if n<300: continue
    atr=talib.ATR(h,l,c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan); dollar=c*vol20
    dmove=np.zeros(n); dmove[1:]=np.abs(c[1:]/np.where(c[:-1]>0,c[:-1],np.nan)-1.0)
    badday=dmove>GAP
    yr=np.array([x[:4] for x in dts]); nonbull=~np.array([isbull(x) for x in dts])

    sar=talib.SAR(h,l,0.02,0.2)
    adx14=talib.ADX(h,l,c,14); pdi=talib.PLUS_DI(h,l,c,14); mdi=talib.MINUS_DI(h,l,c,14)
    adx21=talib.ADX(h,l,c,21)
    STATES={"PSAR":c>sar, "ADX25_diUp":(adx14>25)&(pdi>mdi), "ADX25_p21":adx21>25}

    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL); pos=(c>0)&(o>0)&(h>0)&(l>0)
    clean_elig=base_price&pos&(atr_pct>=VOL_FLOOR)&(dollar>=DOLLAR_VOL)
    badpathB=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
    for t in range(n-BR_N):
        if cs[t+BR_N+1]-cs[t+1]>0: badpathB[t]=True
    res,valid=bracket(h,l,c,atr,BR_N,TP_ATR,SL_ATR,badpathB)
    ok=clean_elig&valid&~np.isnan(res)

    for rk,rmask in (("all",np.ones(n,bool)),("bull",~nonbull),("nonbull",nonbull)):
        base=ok&rmask
        if base.sum()<20: continue
        bmean=res[base].mean()
        for sname,smask in list(STATES.items())+[("RANDOM",np.ones(n,bool))]:
            ent=noov(smask&base,res,BR_N)
            if ent: bumpB((sname,rk), float(np.mean([res[i] for i in ent])-bmean), len(ent))
            fidx=np.where(smask&base)[0]
            if len(fidx)>=5:
                bumpF((sname,rk), float(res[fidx].mean()-bmean), len(fidx))
                u=np.zeros(n); u[fidx]=res[fidx]-bmean
                bumpNW((sname,rk), u, len(fidx))
        # AGE GRADIENT (full-pop + NW per bucket) — the litmus for a buried edge
        for sname,smask in STATES.items():
            age=age_of(np.asarray(smask,bool))
            for bname,lo,hi in AGE_BUCKETS:
                fidx=np.where(base&smask&(age>=lo)&(age<=hi))[0]
                if len(fidx)>=5:
                    bumpF((sname,rk,bname), float(res[fidx].mean()-bmean), len(fidx))
                    u=np.zeros(n); u[fidx]=res[fidx]-bmean
                    bumpNW((sname,rk,bname), u, len(fidx))
        # PER-YEAR NW (year-demeaned, COVID isolated to 2020)
        for sname,smask in STATES.items():
            for Y in YEARS:
                yb=base&(yr==Y)
                if yb.sum()<20: continue
                ybmean=res[yb].mean(); fidx=np.where(smask&yb)[0]
                if len(fidx)>=5:
                    u=np.zeros(n); u[fidx]=res[fidx]-ybmean
                    bumpNW((sname,rk,"Y"+Y), u, len(fidx))

def st(store,k,minsym=30):
    a=store.get(k)
    if not a or a[2]<minsym: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt
def stNW(k,minfire=50):
    a=NW.get(k)
    if a is None or a[1]<minfire: return None
    S,M=a[0],a[1]; G=a[2:]
    varS=G[0]+2.0*float(np.dot(NW_W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)

print("\n############### PSAR/ADX clean re-audit — DE-OVERLAP vs FULL-POP vs NEWEY-WEST ###############")
print(f"  bracket TP{TP_ATR:.0f}:SL{SL_ATR:.0f} hold{BR_N}, vol_floor {VOL_FLOOR}, $vol>={DOLLAR_VOL:,}, gap-skip")
print("  if FULL-POP/NW flips positive vs de-overlap => onset-bias buried an edge (rsi_oversold pattern).")
for rk in ("all","nonbull","bull"):
    print(f"\n  --- regime={rk} ---   (lift vs matched random-entry)")
    print(f"    {'signal':12} {'DE-OVERLAP':>22} {'FULL-POP(cluster)':>22} {'FULL-POP(Newey-West)':>26}")
    for sname in ("PSAR","ADX25_diUp","ADX25_p21","RANDOM"):
        b=st(B,(sname,rk)); ff=st(BF,(sname,rk)); nw=stNW((sname,rk))
        c1=f"{b[0]:+.3f}R t={b[1]:+.1f} n={b[3]}" if b else "(thin)"
        c2=f"{ff[0]:+.3f}R t={ff[1]:+.1f}" if ff else "(thin)"
        c3=f"{nw[0]:+.3f}R t={nw[1]:+.1f} n={nw[2]}" if nw else "(thin)"
        print(f"    {sname:12} {c1:>22} {c2:>22} {c3:>26}")

print("\n############### AGE GRADIENT (full-pop Newey-West t per bars-in-state) ###############")
print("  litmus: RISING+positive => edge lives deeper in the run (de-overlap buried it). FLAT/DOWN => dead, correctly.")
for sname in ("PSAR","ADX25_diUp","ADX25_p21"):
    print(f"\n  {sname}:")
    print(f"    {'regime':9} | " + " | ".join(f"{b[0]:>16}" for b in AGE_BUCKETS))
    for rk in ("all","nonbull","bull"):
        cells=[]
        for bname,_,_ in AGE_BUCKETS:
            x=stNW((sname,rk,bname),minfire=30)
            cells.append(f"{x[0]:+.3f}R t{x[1]:+.1f}" if x else "(thin)")
        print(f"    {rk:9} | " + " | ".join(f"{c:>16}" for c in cells))

print("\n############### PER-YEAR NW (year-demeaned; 2020 = COVID, isolated) ###############")
for sname in ("PSAR","ADX25_diUp","ADX25_p21"):
    for rk in ("nonbull","all"):
        cells=[]; npos=nneg=0
        for Y in YEARS:
            x=stNW((sname,rk,"Y"+Y),minfire=30)
            if not x: cells.append(f"{Y[2:]}:  .   "); continue
            if x[0]>0: npos+=1
            else: nneg+=1
            cells.append(f"{Y[2:]}:{x[0]:+.2f}({x[1]:+.0f})")
        print(f"  {sname:12} {rk:8} [+{npos}/-{nneg}yr]")
        print("     "+" ".join(cells))
print("\ndone.")
