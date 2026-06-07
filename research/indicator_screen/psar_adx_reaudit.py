"""PSAR & ADX comprehensive re-audit on the clean+Newey-West harness.

The prior re-audit (psar_adx_nw.py, committed 3cfde3c) tested only the LONG trend-continuation
*states* — psar_above, adx_diUp, adx_p21 — and found them dead/anti-predictive, correctly (flat/down
age gradients; ADX_diUp NW MORE negative; only a faint non-year-stable ADX_p21 nonbull-deep whisper).

But every lesson in this book — and the Heiken-Ashi result especially ([[project_heiken_ashi_deepdive]])
— says a "trend" indicator's buried edge, if any, lives in the REVERSAL / DISLOCATION / CONDITIONING
direction, not continuation. The de-overlap bias that buried rsi_oversold/below_cloud only flips
PERSISTING-state signals; it can't manufacture edge from a continuation control. So this re-audit
reproduces the state verdict AND extends to the directions the prior audit never probed:

  PSAR  — above (state, control) | flip_up (bull-flip event) | below (bearish state, contrarian) |
          far_below (deep dislocation in ATR) | flip_dn (sell event, short-side check)
  ADX   — diUp (textbook long, control) | p21 (DI-off survivor) | high (strength, DI-agnostic) |
          diDown (STRONG DOWNTREND — a dislocation filter for longs, the prime suspect) |
          low (no-trend/range — does range favour the mean-reversion bracket?) | rising (strengthening)

Machinery byte-identical to clean_harness.py PASS 2 / nw_broad_sweep.py / psar_adx_nw.py:
bracket TP2:SL1 hold10, vol floor, $-vol floor, gap-skip path, symbol-cluster, test-ticker exclusion,
NW Bartlett L=BR_N-1 (trade-weighted, true-overlap kernel), demean vs same-regime random. 3 columns
(DE-OVERLAP | FULL-POP cluster | NEWEY-WEST) + age-gradient litmus for the persisting states.
Buried-edge flag ▲ = de-overlap<=0 AND NW>0 t>=3 (the rsi_oversold signature). NOT a deploy test.
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

def shift(a,k):
    out=np.full(len(a),np.nan)
    if k<len(a): out[k:]=a[:-k]
    return out
B={}
def bumpB(k,lift,nt):
    a=B.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
BF={}
def bumpF(k,lift,nt):
    a=BF.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
L_NW=BR_N-1; NW_W=np.array([1.0-j/(L_NW+1) for j in range(L_NW+1)])
NW={}
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
def noov(mask,res,N):
    out=[];u=-1
    for i in np.where(mask&~np.isnan(res))[0]:
        if i<=u: continue
        out.append(i); u=i+N
    return out
def age_of(state):
    a=np.full(len(state),-1,int); r=0
    for i in range(len(state)):
        if state[i]: a[i]=r; r+=1
        else: r=0
    return a

GROUPS=[
 ("PSAR continuation (control -)", ["psar_above"]),
 ("PSAR reversal / contrarian",    ["psar_flip_up","psar_below","psar_far_below","psar_flip_dn"]),
 ("ADX trend (control -)",         ["adx_diUp","adx_p21","adx_high"]),
 ("ADX contrarian / regime",       ["adx_diDown","adx_low","adx_rising"]),
 ("RANDOM",                        ["RANDOM"]),
]
ALL_SIGS=[s for _,ss in GROUPS for s in ss]
AGE_SIGS=["psar_above","psar_below","adx_diUp","adx_diDown","adx_low","adx_high"]  # persisting states

for ii,sym in enumerate(syms):
    if ii%400==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    if n<300: continue
    atr=talib.ATR(h,l,c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan); dollar=c*vol20
    dmove=np.zeros(n); dmove[1:]=np.abs(c[1:]/np.where(c[:-1]>0,c[:-1],np.nan)-1.0); badday=dmove>GAP
    nonbull=~np.array([isbull(x) for x in dts])

    sar=talib.SAR(h,l,0.02,0.2); sarprev=shift(sar,1); prevc=shift(c,1)
    adx14=talib.ADX(h,l,c,14); pdi=talib.PLUS_DI(h,l,c,14); mdi=talib.MINUS_DI(h,l,c,14); adx21=talib.ADX(h,l,c,21)
    psar_above=c>sar; psar_below=c<sar
    sar_dist=(sar-c)/np.where(atr>0,atr,np.nan)
    SIG={
      "psar_above":psar_above,
      "psar_flip_up":psar_above&(prevc<=sarprev),
      "psar_below":psar_below,
      "psar_far_below":psar_below&(sar_dist>1.0),
      "psar_flip_dn":psar_below&(prevc>=sarprev),
      "adx_diUp":(adx14>25)&(pdi>mdi),
      "adx_p21":adx21>25,
      "adx_high":adx14>25,
      "adx_diDown":(adx14>25)&(mdi>pdi),
      "adx_low":adx14<20,
      "adx_rising":adx14>shift(adx14,5),
      "RANDOM":np.ones(n,bool),
    }

    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL); pos=(c>0)&(o>0)&(h>0)&(l>0)
    clean_elig=base_price&pos&(atr_pct>=VOL_FLOOR)&(dollar>=DOLLAR_VOL)
    badpathB=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
    for t in range(n-BR_N):
        if cs[t+BR_N+1]-cs[t+1]>0: badpathB[t]=True
    res,valid=bracket(h,l,c,atr,BR_N,TP_ATR,SL_ATR,badpathB)
    ok=clean_elig&valid&~np.isnan(res)

    for rk,rmask in (("all",np.ones(n,bool)),("nonbull",nonbull),("bull",~nonbull)):
        base=ok&rmask
        if base.sum()<20: continue
        bmean=res[base].mean()
        for sname in ALL_SIGS:
            smask=np.asarray(SIG[sname],bool)&base
            ent=noov(smask,res,BR_N)
            if ent: bumpB((sname,rk), float(np.mean([res[i] for i in ent])-bmean), len(ent))
            fidx=np.where(smask)[0]
            if len(fidx)>=5:
                bumpF((sname,rk), float(res[fidx].mean()-bmean), len(fidx))
                u=np.zeros(n); u[fidx]=res[fidx]-bmean
                bumpNW((sname,rk), u, len(fidx))
        for sname in AGE_SIGS:
            age=age_of(np.asarray(SIG[sname],bool))
            for bname,lo,hi in AGE_BUCKETS:
                fidx=np.where(base&np.asarray(SIG[sname],bool)&(age>=lo)&(age<=hi))[0]
                if len(fidx)>=5:
                    u=np.zeros(n); u[fidx]=res[fidx]-bmean
                    bumpNW((sname,rk,bname), u, len(fidx))

def st(store,k,minsym=30):
    a=store.get(k)
    if not a or a[2]<minsym: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt
def stNW(k,minfire=50):
    a=NW.get(k)
    if a is None or a[1]<minfire: return None
    S,M=a[0],a[1]; G=a[2:]; varS=G[0]+2.0*float(np.dot(NW_W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)

print("\n############### PSAR/ADX RE-AUDIT — DE-OVERLAP vs FULL-POP vs NEWEY-WEST ###############")
print(f"  bracket TP{TP_ATR:.0f}:SL{SL_ATR:.0f} hold{BR_N}, vol_floor {VOL_FLOOR}, $vol>={DOLLAR_VOL:,}, gap-skip")
print("  ▲ buried-edge signature: de-overlap<=0 AND NW>0 t>=3 (rsi_oversold pattern).")
for rk in ("all","nonbull","bull"):
    print(f"\n  ===================== regime={rk} =====================")
    print(f"    {'signal':16} {'DE-OVERLAP':>22} {'FULL-POP(clus)':>18} {'NEWEY-WEST':>24}  flag")
    for gname,sigs in GROUPS:
        print(f"   -- {gname} --")
        for sname in sigs:
            b=st(B,(sname,rk)); ff=st(BF,(sname,rk)); nw=stNW((sname,rk))
            c1=f"{b[0]:+.3f}R t{b[1]:+.1f} n{b[3]}" if b else "(thin)"
            c2=f"{ff[0]:+.3f}R t{ff[1]:+.1f}" if ff else "(thin)"
            c3=f"{nw[0]:+.3f}R t{nw[1]:+.1f} n{nw[2]}" if nw else "(thin)"
            flag=""
            if nw and b and b[0]<=0.0 and nw[0]>0 and nw[1]>=3.0: flag="▲ buried?"
            print(f"    {sname:16} {c1:>22} {c2:>18} {c3:>24}  {flag}")

print("\n############### AGE GRADIENT (full-pop Newey-West t per bars-in-state) ###############")
print("  RISING+positive => edge lives deeper in the run (de-overlap buried it). FLAT/DOWN => dead, correctly.")
for sname in AGE_SIGS:
    print(f"\n  {sname}:")
    print(f"    {'regime':9} | " + " | ".join(f"{b[0]:>15}" for b in AGE_BUCKETS))
    for rk in ("all","nonbull","bull"):
        cells=[]
        for bname,_,_ in AGE_BUCKETS:
            x=stNW((sname,rk,bname),minfire=30)
            cells.append(f"{x[0]:+.3f}R t{x[1]:+.1f}" if x else "(thin)")
        print(f"    {rk:9} | " + " | ".join(f"{c:>15}" for c in cells))
print("\ndone.")
