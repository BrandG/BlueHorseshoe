"""FIX #2: clean re-validation of the DEPLOYABLE PACKAGE {nonbull-gate bare + HARD solvency} vs production.

The full-universe sim's whole-book $wtR was dominated by the thin/oversized HA sleeve (2.85x dollars, n~150),
drowning the bare-sleeve signal. FIX = decompose realized book P&L by SLEEVE. The package only touches BARE,
HA is a ~constant backdrop, so the BARE-ONLY contribution (and the cross-config difference, where HA cancels)
is the clean signal. Three configs through the SAME live allocator (full pinned-2000, HA always nonbull as prod):
  A  PROD      bare all-regime,  no solvency        (current production)
  M  NB-ONLY   bare nonbull,     no solvency        (isolates the regime-gate)
  B  PACKAGE   bare nonbull,     HARD drop-distress  (the proposal)
Report per config: whole-book / BARE-only / HA-only {n, total$, $wtR, $/day}. Year-block bootstrap the
cross-config difference (M-A isolates gating; B-A = full package; B-M = solvency-on-top) on bare-only total$ and
whole-book total$. Production-faithful bracket (incl. the known +1% entry stop-compression — constant across arms).
"""
import os, numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX=5.0,500.0; DVOL_FLOOR=25_000_000.0; MAX_RISK=0.05
OS=30.0; AGE=3; HOLD=10; STOP_MULT,TGT_MULT=1.0,2.0; PREMIUM=0.01
EW_BARE,EW_HA=0.142,0.404; TOTAL_INV=10000.0; MAXPOS=10; BASE=TOTAL_INV/MAXPOS; CAPMULT=2.5
Z_DISTRESS=1.1; B=3000
FUND="data/fundamentals.parquet"
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg_map.get(d,False)
CAL=sorted(spy.date.astype(str).str[:10].tolist()); CIDX={d:i for i,d in enumerate(CAL)}; NCAL=len(CAL)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300 ORDER BY symbol",[START]).df().symbol.tolist()
syms=[s for s in syms if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=sorted(rng.choice(syms,N_SYMBOLS,replace=False))

fdf=pd.read_parquet(FUND)
def num(s): return pd.to_numeric(s,errors="coerce")
ta=num(fdf.total_assets); tl=num(fdf.total_liabilities)
wc=num(fdf.current_assets)-num(fdf.current_liabilities); re=num(fdf.retained_earnings); ebit=num(fdf.ebit_ttm)
with np.errstate(divide="ignore",invalid="ignore"):
    z=6.56*(wc/ta)+3.26*(re/ta)+6.72*(ebit/ta)+1.05*((ta-tl)/tl)
fdf=fdf.assign(altman_z=z)
FQ=defaultdict(list)
for r in fdf.sort_values(["symbol","reportedDate"]).itertuples(index=False):
    if isinstance(r.reportedDate,str) and r.reportedDate:
        FQ[r.symbol].append((r.reportedDate,float(r.altman_z) if np.isfinite(r.altman_z) else np.nan))
print(f"FULL UNIVERSE {len(syms)} syms ({sum(1 for s in syms if s in FQ)} fund-covered)",flush=True)
def dv_cost_bp(dv): return 50.0 if dv<1e6 else 25.0 if dv<5e6 else 12.0 if dv<25e6 else 6.0

FIRES=[]
for ii,sym in enumerate(syms):
    if ii%400==0: print(f"  scan {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<60: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14)
    dv20=pd.Series(c*v).rolling(20).mean().to_numpy(); atr_pct=atr/np.where(c>0,c,np.nan)
    osr=rsi<OS; age=np.zeros(n,int)
    for i in range(1,n): age[i]=age[i-1]+1 if osr[i] else 0
    hac=(o+h+l+c)/4.0; hao=np.empty(n); hao[0]=(o[0]+c[0])/2
    for i in range(1,n): hao[i]=(hao[i-1]+hac[i-1])/2
    hg=hac>hao
    qf=FQ.get(sym,[]); zarr=np.full(n,np.nan); j=0; cz=np.nan
    for i in range(n):
        while j<len(qf) and qf[j][0]<=dts[i]: cz=qf[j][1]; j+=1
        zarr[i]=cz
    for i in range(40,n-1):
        if age[i]<AGE or not (dv20[i]>=DVOL_FLOOR) or not (atr[i]>0): continue
        entry=c[i]*(1+PREMIUM)
        if not (PRICE_MIN<entry<PRICE_MAX): continue
        if (STOP_MULT*atr[i])/entry > MAX_RISK: continue
        f=i+1
        if l[f]>entry: continue
        fill=o[f] if o[f]<=entry else entry
        tp=entry+TGT_MULT*atr[i]*0.98; sl=entry-STOP_MULT*atr[i]; Rp=STOP_MULT*atr[i]
        R=None; hk=None; kmax=min(HOLD,n-1-f)
        for k in range(1,kmax+1):
            jj=f+k; hsl=l[jj]<=sl; htp=h[jj]>=tp
            if hsl and htp: R=((min(o[jj],sl) if o[jj]<=sl else sl)-fill)/Rp; hk=k; break
            if hsl: R=((o[jj] if o[jj]<=sl else sl)-fill)/Rp; hk=k; break
            if htp: R=(tp-fill)/Rp; hk=k; break
        if R is None: R=(c[f+kmax]-fill)/Rp; hk=kmax
        R-=dv_cost_bp(dv20[i])/1e4/(STOP_MULT*atr_pct[i])
        sig=dts[i]; sidx=CIDX.get(sig)
        if sidx is None: continue
        # slot occupied from fill (sidx+1) through actual bracket resolution day (variable hold)
        FIRES.append({"sym":sym,"sidx":sidx,"exit":min(sidx+hk,NCAL-1),"score":14.5+(age[i]-AGE)*1.5,
                      "z":zarr[i],"zc":bool(~np.isnan(zarr[i])),"atrp":float(atr_pct[i]),"R":float(R),
                      "nb":(not isbull(sig)),"ha_ok":((not isbull(sig)) and bool(hg[i])),"yr":int(sig[:4])})
print(f"  total filled fire-events: {len(FIRES)}",flush=True)
zk=np.sort(np.array([f["z"] for f in FIRES if f["zc"]]))
def solv_factor(f):
    if not f["zc"]: return 1.0
    return 0.2+0.8*(np.searchsorted(zk,f["z"],side="right")/len(zk))
for f in FIRES: f["solv"]=solv_factor(f)
fires_by_sidx=defaultdict(list)
for f in FIRES: fires_by_sidx[f["sidx"]].append(f)

def simulate(bare_regime, solvency):
    """bare_regime in {'all','nonbull'}; solvency in {'none','hard'}. Returns recs (yr,$,R,atrp,sleeve)."""
    open_pos=[]; recs=[]
    for t in range(NCAL):
        open_pos=[p for p in open_pos if p[0]>=t]
        occ={p[1] for p in open_pos}; slots=MAXPOS-len(open_pos)
        if slots<=0: continue
        cands=[]
        for f in fires_by_sidx.get(t,[]):
            if f["sym"] in occ: continue
            views=[]
            if f["ha_ok"]: views.append(("ha",EW_HA))
            bare_live = f["nb"] if bare_regime=="nonbull" else True
            if bare_live and not (solvency=="hard" and f["zc"] and f["z"]<Z_DISTRESS):
                views.append(("bare",EW_BARE))
            if not views: continue
            sleeve,ew=max(views,key=lambda vw: f["score"]*vw[1])
            cands.append((f,sleeve,ew,f["score"]*ew))
        if not cands: continue
        cands.sort(key=lambda x:x[3],reverse=True)
        sel=cands[:slots]
        ws=[ew for (_,_,ew,_) in sel]; tw=sum(ws); pot=len(sel)*BASE
        for (f,sleeve,ew,_),w in zip(sel,ws):
            dollars=min(pot*w/tw,CAPMULT*BASE) if tw>0 else BASE
            recs.append((f["yr"],dollars,f["R"],f["atrp"],sleeve))
            open_pos.append((f["exit"],f["sym"]))
    return recs

def metrics(recs, sleeve=None):
    rr=[r for r in recs if sleeve is None or r[4]==sleeve]
    if not rr: return {"n":0,"tot":0.0,"wR":0.0}
    D=np.array([r[1] for r in rr]); R=np.array([r[2] for r in rr]); ap=np.array([r[3] for r in rr])
    tot=float((D*R*ap).sum()); wR=float((D*R).sum()/D.sum())
    return {"n":len(rr),"tot":tot,"wR":wR}

def boot_tot_diff(recsX, recsA, sleeve, B):
    """year-block bootstrap of (total$ X - total$ A), sleeve-filtered, normalized per year-draw."""
    fX=[r for r in recsX if sleeve is None or r[4]==sleeve]; fA=[r for r in recsA if sleeve is None or r[4]==sleeve]
    yX=np.array([r[0] for r in fX]); yA=np.array([r[0] for r in fA])
    pX=np.array([r[1]*r[2]*r[3] for r in fX]); pA=np.array([r[1]*r[2]*r[3] for r in fA])
    yrs=np.array(sorted(set(yX.tolist())|set(yA.tolist()))); K=len(yrs)
    iX={y:np.where(yX==y)[0] for y in yrs}; iA={y:np.where(yA==y)[0] for y in yrs}
    bs=np.random.default_rng(SEED); out=np.empty(B)
    for it in range(B):
        dr=bs.choice(yrs,K,replace=True)
        sx=sum(pX[iX[y]].sum() for y in dr); sa=sum(pA[iA[y]].sum() for y in dr)
        out[it]=sx-sa
    return np.median(out),np.percentile(out,5),np.percentile(out,95),float((out>0).mean())

CFG={"A_prod":("all","none"),"M_nbonly":("nonbull","none"),"B_package":("nonbull","hard")}
REC={k:simulate(*v) for k,v in CFG.items()}
print(f"\n{'config':11} {'scope':6} {'n':>6} {'total$':>9} {'$wtR':>8} {'$/day':>7}")
for k in ("A_prod","M_nbonly","B_package"):
    for scope,sl in (("whole",None),("bare","bare"),("ha","ha")):
        m=metrics(REC[k],sl); print(f"  {k:11} {scope:6} {m['n']:>6} {m['tot']:>9.0f} {m['wR']:>+8.3f} {m['tot']/NCAL:>7.2f}")
print(f"\n################ CROSS-CONFIG BOOTSTRAP (year-block, total$ difference) ################")
for label,(X,A) in (("M-A (regime-gate only)",("M_nbonly","A_prod")),
                     ("B-A (FULL PACKAGE)",("B_package","A_prod")),
                     ("B-M (solvency on nonbull)",("B_package","M_nbonly"))):
    for scope,sl in (("whole",None),("bare","bare")):
        md,lo,hi,p=boot_tot_diff(REC[X],REC[A],sl,B)
        print(f"  {label:26} [{scope:5}]  Δtotal$ {md:+8.0f} 90%CI[{lo:+8.0f},{hi:+8.0f}] P(>0)={p:.2f}")
print("\ndone.")
