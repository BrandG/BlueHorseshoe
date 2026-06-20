"""Phase 1 — solo-edge test for swing-pivot/volume support proximity.

Question: does entering "near a strong support" beat just being long, on the SAME
bracketed harness that surfaced the deep-oversold edge? And does the level's
STRENGTH add anything beyond raw proximity, and beyond the engine's existing
implicit-S/R proxies (Donchian-low, Bollinger %B)?

Harness is lifted verbatim from research/indicator_screen/clean_harness.py so the
numbers are directly comparable:
  * bracket TP2:SL1, hold 10, vol-floor + $vol-floor + gap-skip badpath
  * eligibility/price floors identical
  * regimes all / bull / nonbull (SPY EMA200 + 50>200)
  * three reads per signal: DE-OVERLAP, FULL-POP(cluster), FULL-POP(Newey-West)
  * every lift is vs the same-regime eligible-population mean (RANDOM ~ 0)

S/R features come from detector.py (point-in-time verified). The headline signal:
  near_strong = (dist_to_support_atr <= D) AND (support_strength above the symbol's
  own causal expanding median).  Strong/weak split isolates whether STRENGTH matters.

Plus a distance-bucket monotonicity table in nonbull — the direct test of "the
closer to support, the better", the way depth-monotonicity was the tell for
deep-oversold.
"""
import sys, os
import numpy as np, pandas as pd, talib, duckdb

sys.path.insert(0, os.path.dirname(__file__))
from detector import compute_sr_arrays, SRParams  # noqa: E402

# ---- harness constants (match clean_harness.py) ----
SEED = 7; N_SYMBOLS = 1000; START = "2016-01-01"
PRICE_MIN, PRICE_MAX, MIN_VOL = 5.0, 500.0, 100_000
VOL_FLOOR = 0.005; DOLLAR_VOL = 1_000_000; GAP = 0.50
BR_N = 10; TP_ATR, SL_ATR = 2.0, 1.0
YEARS = [str(y) for y in range(2016, 2027)]
TEST_PAT = ("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")
DISTS = [0.25, 0.50, 1.00]            # ATR proximity thresholds
DBUCKETS = [(0,0.25),(0.25,0.5),(0.5,1.0),(1.0,2.0),(2.0,99)]  # monotonicity grid

con = duckdb.connect("data/ohlcv.duckdb", read_only=True)
spy = con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"] = talib.EMA(spy.close,50); spy["e200"] = talib.EMA(spy.close,200)
spy["bull"] = (spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map = dict(zip(spy.date.astype(str).str[:10], spy.bull))
def isbull(d): return reg_map.get(str(d)[:10], False)

syms = con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
syms = [s for s in syms if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng = np.random.default_rng(SEED)
if len(syms) > N_SYMBOLS: syms = list(rng.choice(syms, N_SYMBOLS, replace=False))
print(f"{len(syms)} symbols", flush=True)

# ---- bracket + de-overlap + Newey-West (verbatim from clean_harness) ----
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
    out=[]; u=-1
    for i in np.where(mask&~np.isnan(res))[0]:
        if i<=u: continue
        out.append(i); u=i+N
    return out

L_NW=BR_N-1
NW_W=np.array([1.0-j/(L_NW+1) for j in range(L_NW+1)])
B={}; BF={}; NW={}; DB={}
def bumpB(k,lift,nt): a=B.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
def bumpF(k,lift,nt): a=BF.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
def bumpNW(k,u,m):
    a=NW.setdefault(k,np.zeros(3+L_NW)); a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    for j in range(1,L_NW+1): a[2+j]+=float(u[:-j]@u[j:])
def bumpDB(k,vals):  # distance-bucket: accumulate raw R (not lift) + count
    a=DB.setdefault(k,[0.,0]); a[0]+=float(np.sum(vals)); a[1]+=len(vals)

for ii,sym in enumerate(syms):
    if ii%200==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    if n<300: continue
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan); dollar=c*vol20
    dmove=np.zeros(n); dmove[1:]=np.abs(c[1:]/np.where(c[:-1]>0,c[:-1],np.nan)-1.0)
    badday=dmove>GAP

    # --- S/R features (point-in-time) ---
    sr=compute_sr_arrays(h,l,c,v,SRParams())
    dsup=sr["dist_to_support_atr"]; sstr=sr["support_strength"]
    # causal "strong": support_strength above its own expanding median (shift 1 = no peek)
    smed=pd.Series(sstr).expanding(min_periods=50).median().shift(1).to_numpy()
    strong=sstr>=smed

    # --- existing implicit-S/R controls ---
    donlo=pd.Series(l).rolling(20).min().to_numpy()
    near_don=((c-donlo)/np.where(atr>0,atr,np.nan)<=0.5)&(c>donlo)
    bbu,bbm,bbl=talib.BBANDS(c,20,2.0,2.0)
    bbpct=(c-bbl)/np.where((bbu-bbl)>0,(bbu-bbl),np.nan)
    bb_low=bbpct<=0.2
    os=rsi<30

    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)
    pos=(c>0)&(o>0)&(h>0)&(l>0)
    nonbull=~np.array([isbull(x) for x in dts]); yr=np.array([x[:4] for x in dts])

    clean_elig=base_price&pos&(atr_pct>=VOL_FLOOR)&(dollar>=DOLLAR_VOL)
    badpathB=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
    for t in range(n-BR_N):
        if cs[t+BR_N+1]-cs[t+1]>0: badpathB[t]=True
    res,valid=bracket(h,l,c,atr,BR_N,TP_ATR,SL_ATR,badpathB)
    ok=clean_elig&valid&~np.isnan(res)&~np.isnan(dsup)

    # signal set
    SIG={}
    for D in DISTS:
        SIG[f"near_{D:.2f}"]=dsup<=D
    SIG["near_strong_0.50"]=(dsup<=0.5)&strong
    SIG["near_weak_0.50"]=(dsup<=0.5)&~strong
    SIG["near_strong_0.25"]=(dsup<=0.25)&strong
    SIG["ctrl_donchlow"]=near_don
    SIG["ctrl_bb_low"]=bb_low
    SIG["os"]=os
    SIG["near_strong&os"]=(dsup<=0.5)&strong&os
    SIG["os&~nearstrong"]=os&~((dsup<=0.5)&strong)
    SIG["nearstrong&~os"]=(dsup<=0.5)&strong&~os
    SIG["RANDOM"]=np.ones(n,bool)

    for rk,rmask in (("all",np.ones(n,bool)),("bull",~nonbull),("nonbull",nonbull)):
        base=ok&rmask
        if base.sum()<20: continue
        bmean=res[base].mean()
        for sname,smask in SIG.items():
            sm=smask&base
            ent=noov(sm,res,BR_N)
            if ent: bumpB((sname,rk), float(np.mean([res[i] for i in ent])-bmean), len(ent))
            fidx=np.where(sm)[0]
            if len(fidx)>=5:
                bumpF((sname,rk), float(res[fidx].mean()-bmean), len(fidx))
                u=np.zeros(n); u[fidx]=res[fidx]-bmean
                bumpNW((sname,rk), u, len(fidx))
        # distance-bucket monotonicity (raw R, full pop) within regime
        for lo,hi in DBUCKETS:
            m=base&(dsup>=lo)&(dsup<hi)
            idx=np.where(m)[0]
            if len(idx): bumpDB((rk,lo,hi), res[idx])

con.close()

# ---- stats ----
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
    m=S/M; se=(varS**0.5)/M
    return m,(m/se if se>0 else 0),int(M)

ORDER=[f"near_{D:.2f}" for D in DISTS]+["near_strong_0.50","near_weak_0.50","near_strong_0.25",
       "ctrl_donchlow","ctrl_bb_low","os","near_strong&os","os&~nearstrong","nearstrong&~os","RANDOM"]

print("\n############### SOLO-EDGE: bracketed R lift vs same-regime population (RANDOM~0) ###############")
print(f"  TP{TP_ATR:.0f}:SL{SL_ATR:.0f} hold{BR_N}, vol_floor {VOL_FLOOR}, $vol>={DOLLAR_VOL:,}, gap-skip, {len(syms)} symbols, {START}+")
for rk in ("all","nonbull","bull"):
    print(f"\n  --- regime={rk} ---")
    print(f"    {'signal':18} {'DE-OVERLAP':>22} {'FULL-POP(cluster)':>22} {'FULL-POP(Newey-West)':>26}")
    for sname in ORDER:
        b=st(B,(sname,rk)); ff=st(BF,(sname,rk)); nw=stNW((sname,rk))
        c1=f"{b[0]:+.3f}R t={b[1]:+.1f} n={b[3]}" if b else "(thin)"
        c2=f"{ff[0]:+.3f}R t={ff[1]:+.1f}" if ff else "(thin)"
        c3=f"{nw[0]:+.3f}R t={nw[1]:+.1f} n={nw[2]}" if nw else "(thin)"
        print(f"    {sname:18} {c1:>22} {c2:>22} {c3:>26}")

print("\n############### DISTANCE-TO-SUPPORT MONOTONICITY (raw mean R, full pop) ###############")
print("  hypothesis: closer to support -> higher R.  read the gradient down each column.")
print(f"    {'regime':10} "+" ".join(f"{f'[{lo:.2f}-{hi:.2f})':>14}" for lo,hi in DBUCKETS))
for rk in ("all","nonbull","bull"):
    cells=[]
    for lo,hi in DBUCKETS:
        a=DB.get((rk,lo,hi))
        cells.append(f"{a[0]/a[1]:+.3f}(n{a[1]//1000}k)" if a and a[1] else "   .")
    print(f"    {rk:10} "+" ".join(f"{c:>14}" for c in cells))
print("\ndone.")
