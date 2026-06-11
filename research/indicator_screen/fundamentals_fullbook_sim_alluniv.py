"""FULL-BOOK PORTFOLIO SIM: solvency policy (none / hard-filter / graded-tilt) on the LIVE allocator.

Faithful to production (src/bluehorseshoe): two paper sleeves competing for max_positions=10 slots, ranked
GLOBALLY by score*edge_weight (slots_deep_oversold=0 -> reservation off), conviction-weighted sizing (pot =
n_selected*base split by sleeve edge_weight, capped 2.5*base), base=$1000. Live constants:
  bare deep_oversold : rsi<30 age>=3, 20d $-vol >= $25M, entry = prevclose*1.01 DAY LIMIT, stop=entry-1*ATR,
                       tgt=entry+2*ATR*0.98, hold10, NO regime gate, edge_weight 0.142, score 14.5+(age-3)*1.5
  deep_oversold_ha   : same + SPY-nonbull + recursive-HA-green, edge_weight 0.404 (~2.8x -> wins slots first)
Entry fill model: next day, fill if low<=limit (marketable: open if open<=limit else limit), else NO FILL (miss).
Bracket from fill day, intraday TP/SL w/ gap-stop, timeout at close(hold). $P&L_i = dollars_i * R_i * atr_pct_i.

SOLVENCY POLICIES (applied to BARE fires only — HA already subsumes solvency per Door #1):
  SQ   status-quo (no solvency)
  HARD drop bare fires with KNOWN Altman-Z''<1.1 (unknown-Z kept)
  TILT multiply bare fire's ranking score AND conviction weight by solv in [0.2,1.0] (rank-normalized Z''; 1.0 if unknown)

Books: PROD (bare all-regime, as coded) and BARE-NONBULL (also nonbull-gate bare). 3 policies each.
Metrics: total $P&L / return% on $10k, dollar-wt mean R, n trades, avg concurrent positions, $/day; year-block
bootstrap 90%CI on (policy - SQ) dollar-wt mean R. Universe = pinned-2000 ∩ fund-covered (where Z'' is defined).
"""
import os, numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX=5.0,500.0
DVOL_FLOOR=25_000_000.0; MAX_RISK=0.05
OS=30.0; AGE=3; HOLD=10; STOP_MULT,TGT_MULT=1.0,2.0; PREMIUM=0.01
EW_BARE,EW_HA=0.142,0.404
TOTAL_INV=10000.0; MAXPOS=10; BASE=TOTAL_INV/MAXPOS; CAPMULT=2.5
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
covered=[s for s in syms if s in FQ]
print(f"FULL UNIVERSE {len(syms)} syms ({len(covered)} fund-covered; non-covered = tilt-neutral solv=1.0, never hard-dropped) | full-book sim, {NCAL} trading days",flush=True)

def dv_cost_bp(dv): return 50.0 if dv<1e6 else 25.0 if dv<5e6 else 12.0 if dv<25e6 else 6.0

# ---- precompute all fire events across ALL pinned symbols (covered + non-covered) ----
FIRES=[]   # dict per filled fire
for ii,sym in enumerate(syms):
    if ii%300==0: print(f"  scan {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<60: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14)
    dv20=pd.Series(c*v).rolling(20).mean().to_numpy(); atr_pct=atr/np.where(c>0,c,np.nan)
    osr=rsi<OS; age=np.zeros(n,int)
    for i in range(1,n): age[i]=age[i-1]+1 if osr[i] else 0
    # recursive HA green
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
        # fill next day (i+1): marketable BUY LIMIT -> fills at open if open<=limit, else at limit intraday.
        f=i+1
        if l[f]>entry: continue   # limit never reached -> no fill (missed)
        fill = o[f] if o[f]<=entry else entry   # P&L measured from the ACTUAL fill (often < limit)
        # stop/target anchored to the limit (entry) per production; R numerator uses fill.
        tp=entry+TGT_MULT*atr[i]*0.98; sl=entry-STOP_MULT*atr[i]; Rp=STOP_MULT*atr[i]
        # scan days AFTER the fill day (k=1..HOLD), matching the validated next-open harness which
        # does NOT stop on the entry bar's own intraday range; timeout at close(f+HOLD).
        R=None; hk=None
        kmax=min(HOLD,n-1-f)
        for k in range(1,kmax+1):
            jj=f+k; hit_sl=l[jj]<=sl; hit_tp=h[jj]>=tp
            if hit_sl and hit_tp: R=((min(o[jj],sl) if o[jj]<=sl else sl)-fill)/Rp; hk=k; break
            if hit_sl: R=((o[jj] if o[jj]<=sl else sl)-fill)/Rp; hk=k; break
            if hit_tp: R=(tp-fill)/Rp; hk=k; break
        if R is None:
            jexit=f+kmax; R=(c[jexit]-fill)/Rp; hk=kmax
        R-=dv_cost_bp(dv20[i])/1e4/(STOP_MULT*atr_pct[i])   # tiered cost in R
        sig=dts[i]; sidx=CIDX.get(sig)
        if sidx is None: continue
        exit_idx=min(sidx+1+hk-1, NCAL-1)   # occupies (sidx+1 .. exit_idx)
        nb=not isbull(sig)
        bare_ok=True
        ha_ok=nb and bool(hg[i])
        FIRES.append({"sym":sym,"sidx":sidx,"exit":exit_idx,"score":14.5+(age[i]-AGE)*1.5,
                      "z":zarr[i],"zc":bool(~np.isnan(zarr[i])),"atrp":float(atr_pct[i]),
                      "R":float(R),"nb":nb,"ha_ok":ha_ok,"yr":int(sig[:4])})
print(f"  total filled fire-events: {len(FIRES)}",flush=True)
# DIAGNOSTIC: raw per-fire mean R (no portfolio) vs the validated +0.139R ($25M tier) sanity anchor
_allR=np.array([f["R"] for f in FIRES])
_nbbare=np.array([f["R"] for f in FIRES if f["nb"]])
_ha=np.array([f["R"] for f in FIRES if f["ha_ok"]])
print(f"  RAW fire R (sanity): all {_allR.mean():+.3f} (n{len(_allR)}) | nonbull {_nbbare.mean():+.3f} (n{len(_nbbare)}) | HA-elig {_ha.mean():+.3f} (n{len(_ha)})",flush=True)

# rank-normalized solvency factor for bare fires (percentile of Z'' among known-z bare fires)
zk=np.array([f["z"] for f in FIRES if f["zc"]])
zk_sorted=np.sort(zk)
def solv_factor(f):
    if not f["zc"]: return 1.0
    pct=np.searchsorted(zk_sorted,f["z"],side="right")/len(zk_sorted)
    return 0.2+0.8*pct
for f in FIRES: f["solv"]=solv_factor(f)
fires_by_sidx=defaultdict(list)
for f in FIRES: fires_by_sidx[f["sidx"]].append(f)

def simulate(book, policy):
    """book in {'prod','barenb'}; policy in {'SQ','HARD','TILT'}. Returns per-trade records."""
    open_pos=[]   # list of (exit_idx, sym)
    recs=[]       # (yr, dollars, R, atrp)
    for t in range(NCAL):
        open_pos=[p for p in open_pos if p[0]>=t]          # free exited
        occ={p[1] for p in open_pos}; slots=MAXPOS-len(open_pos)
        if slots<=0: continue
        # candidate fires signalled today (each symbol -> its best eligible sleeve view)
        cands=[]
        for f in fires_by_sidx.get(t,[]):
            if f["sym"] in occ: continue
            # bare eligibility (book gate) + HA eligibility
            bare_live = (f["nb"] if book=="barenb" else True)
            views=[]
            if f["ha_ok"]: views.append(("ha",EW_HA,1.0))         # HA: solvency untouched
            if bare_live:
                if policy=="HARD" and f["zc"] and f["z"]<Z_DISTRESS: pass  # dropped
                else:
                    sv = f["solv"] if policy=="TILT" else 1.0
                    views.append(("bare",EW_BARE,sv))
            if not views: continue
            # pick the sleeve that ranks highest for this symbol (score*ew*solv)
            best=max(views, key=lambda vw: f["score"]*vw[1]*vw[2])
            sleeve,ew,sv=best
            cands.append((f, ew, sv, f["score"]*ew*sv))
        if not cands: continue
        cands.sort(key=lambda x:x[3], reverse=True)
        sel=cands[:slots]
        # conviction sizing: pot = n_sel*base, split by ew*sv, cap 2.5*base
        ws=[ew*sv for (_,ew,sv,_) in sel]; tw=sum(ws); pot=len(sel)*BASE
        for (f,ew,sv,_),w in zip(sel,ws):
            dollars = min(pot*w/tw, CAPMULT*BASE) if tw>0 else BASE
            recs.append((f["yr"], dollars, f["R"], f["atrp"]))
            open_pos.append((f["exit"], f["sym"]))
    return recs

def summarize(recs):
    yr=np.array([r[0] for r in recs]); D=np.array([r[1] for r in recs])
    R=np.array([r[2] for r in recs]); ap=np.array([r[3] for r in recs])
    pnl=D*R*ap; tot=pnl.sum(); wR=float((D*R).sum()/D.sum())
    years=(NCAL/252.0)
    cagr=( (TOTAL_INV+tot)/TOTAL_INV )**(1/years)-1
    return {"n":len(recs),"tot":tot,"ret":tot/TOTAL_INV,"cagr":cagr,"wR":wR,"yr":yr,"D":D,"R":R,"ap":ap}

def boot_wR_diff(a,b,B):
    """year-block bootstrap 90%CI of dollar-wt mean R difference a-b (paired by resampled years)."""
    yrs=np.unique(np.concatenate([a["yr"],b["yr"]])); K=len(yrs)
    ai={y:np.where(a["yr"]==y)[0] for y in yrs}; bi={y:np.where(b["yr"]==y)[0] for y in yrs}
    bs=np.random.default_rng(SEED); out=np.empty(B)
    for it in range(B):
        dr=bs.choice(yrs,K,replace=True)
        axa=np.concatenate([ai[y] for y in dr]); bxb=np.concatenate([bi[y] for y in dr])
        wa=(a["D"][axa]*a["R"][axa]).sum()/a["D"][axa].sum() if len(axa) else np.nan
        wb=(b["D"][bxb]*b["R"][bxb]).sum()/b["D"][bxb].sum() if len(bxb) else np.nan
        out[it]=wa-wb
    out=out[~np.isnan(out)]; return np.median(out),np.percentile(out,5),np.percentile(out,95),float((out>0).mean())

for book,blabel in (("prod","PROD book (bare all-regime + HA nonbull)"),("barenb","BARE-NONBULL book (both sleeves nonbull)")):
    print(f"\n################ {blabel} ################")
    S={}
    for pol in ("SQ","HARD","TILT"): S[pol]=summarize(simulate(book,pol))
    print(f"  {'policy':5} {'nTrades':>8} {'total$':>10} {'return%':>8} {'CAGR%':>7} {'$wtR':>7} {'$/day':>7}")
    for pol in ("SQ","HARD","TILT"):
        s=S[pol]; print(f"  {pol:5} {s['n']:>8} {s['tot']:>10.0f} {100*s['ret']:>7.1f}% {100*s['cagr']:>6.2f}% {s['wR']:>+7.3f} {s['tot']/NCAL:>7.2f}")
    for pol in ("HARD","TILT"):
        md,lo,hi,p=boot_wR_diff(S[pol],S["SQ"],B)
        print(f"  Δ$wtR {pol}-SQ: {md:+.3f} 90%CI[{lo:+.3f},{hi:+.3f}] P(>0)={p:.2f}")
print("\ndone.")
