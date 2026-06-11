"""DOOR #2: solvency as a conviction-weighted SIZING TILT vs the hard drop-distress filter.

Door #1/#3 proved dropping Altman-Z''<1.1 lifts the bare deep_oversold sleeve (+0.061R nonbull, orthogonal).
But a HARD filter cuts 38% of fires. The live allocator is slot-constrained + conviction-weighted, so the
natural shape may be a TILT (size by the Z'' gradient, keep all fires). Three questions:

  (1) GRADIENT RICHNESS — quintile the book by Z''; is mean R monotone (safe>grey>distress) so a graded tilt
      adds beyond the binary distress cliff? (cond. script hinted safe +0.142 >> grey +0.041 > distress +0.018)
  (2) SLOT CONSTRAINT — per trading day, how many bare-sleeve fires vs SOLVENT fires? If most days have >=10
      solvent fires, a hard filter loses ~no throughput (just fills the 10 live slots with solvent names) and
      tilt buys little. If days are fire-poor, tilt preserves deployment.  (Caveat: live pool also has the HA
      sleeve + Connors, so bare-only counts UNDERSTATE the real candidate pool.)
  (3) POLICY HEAD-TO-HEAD — per-dollar return (Sum w*R / Sum w) + capital-deployed frac, year-block bootstrap:
      base (equal-wt) / HARD (drop distress) / TILT (quintile-graded weight, all fires kept).

Per [[throughput_over_expectancy]]: the deploy choice is whether the sleeve is slot-constrained, not raw R.
Bare deep_oversold, faithful next-open+gapstop+cost (S4), nonbull (live gate) + all. Universe pinned-2000 ∩ covered.
"""
import os, numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; AGE=3; N=10; TP_ATR,SL_ATR=2.0,1.0
Z_DISTRESS=1.1; B=3000; LIVE_SLOTS=10
FUND="data/fundamentals.parquet"
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
print(f"fundamentals-covered {len(covered)}  | sizing-tilt B={B}, live_slots={LIVE_SLOTS}",flush=True)

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

D={k:[] for k in ("yr","date","R","nb","Z")}
for ii,sym in enumerate(covered):
    if ii%300==0: print(f"  {ii}/{len(covered)}",flush=True)
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
    qf=FQ[sym]; zarr=np.full(n,np.nan); j=0; cz=np.nan
    for i in range(n):
        while j<len(qf) and qf[j][0]<=dts[i]: cz=qf[j][1]; j+=1
        zarr[i]=cz
    zc=~np.isnan(zarr)
    rg,_=run(nxo,atr,o,h,l,c,True)
    ctier=np.array([dv_cost_bp(x) for x in np.nan_to_num(dv20)])/1e4/(SL_ATR*np.where(atr_pct>0,atr_pct,np.nan))
    res=rg-ctier
    sel=deepos&elig&zc&~np.isnan(res)
    idx=np.where(sel)[0]
    if not len(idx): continue
    D["yr"].append(np.array([int(x[:4]) for x in dts[idx]])); D["date"].append(dts[idx])
    D["R"].append(res[idx]); D["nb"].append(nonbull[idx]); D["Z"].append(zarr[idx])
for k in D: D[k]=np.concatenate(D[k]) if D[k] else np.array([])

def wmean_boot(yr,R,w,B):
    uy=np.unique(yr); K=len(uy); idx_by={y:np.where(yr==y)[0] for y in uy}
    bs=np.random.default_rng(SEED); out=np.empty(B)
    for b in range(B):
        ix=np.concatenate([idx_by[y] for y in bs.choice(uy,K,replace=True)])
        ww=w[ix]; out[b]=float(np.dot(ww,R[ix])/ww.sum()) if ww.sum()>0 else np.nan
    out=out[~np.isnan(out)]; return np.median(out),np.percentile(out,5),np.percentile(out,95)

for reg in ("nonbull","all"):
    m=D["nb"] if reg=="nonbull" else np.ones(len(D["yr"]),bool)
    yr=D["yr"][m]; R=D["R"][m]; Z=D["Z"][m]; dts=D["date"][m]; nb=len(R)
    solvent=Z>=Z_DISTRESS
    print(f"\n################ DOOR #2 SIZING TILT — regime={reg}  (bare deep_oversold, n={nb}) ################")
    # (1) gradient richness: Z'' quintiles
    qe=np.quantile(Z,[0,.2,.4,.6,.8,1.0]); qbin=np.clip(np.digitize(Z,qe[1:-1]),0,4)
    print("  (1) Z'' quintile gradient (mean R, year-block CI):")
    for q in range(5):
        mm=qbin==q
        md,lo,hi=wmean_boot(yr,R,mm.astype(float),B)
        print(f"      Q{q+1} Z''[{qe[q]:+.2f},{qe[q+1]:+.2f}] n{int(mm.sum())}  R {md:+.3f} 90%CI[{lo:+.3f},{hi:+.3f}]")
    # (2) slot constraint: fires per trading day
    uday=defaultdict(lambda:[0,0])
    for i in range(nb):
        uday[dts[i]][0]+=1; uday[dts[i]][1]+=1 if solvent[i] else 0
    fires=np.array([a for a,_ in uday.values()]); solv=np.array([b for _,b in uday.values()])
    print(f"  (2) per active day: bare fires median {np.median(fires):.0f} (p25 {np.percentile(fires,25):.0f}/p75 {np.percentile(fires,75):.0f}) | "
          f"SOLVENT median {np.median(solv):.0f} (p25 {np.percentile(solv,25):.0f}/p75 {np.percentile(solv,75):.0f})")
    print(f"      days w/ <{LIVE_SLOTS} solvent fires: {100*np.mean(solv<LIVE_SLOTS):.0f}%  | <5 solvent: {100*np.mean(solv<5):.0f}%  (active days {len(fires)})")
    print(f"      => if low, a HARD filter fills the {LIVE_SLOTS} live slots with solvent names at ~no throughput cost.")
    # (3) policy head-to-head: per-dollar R + deployed-capital
    w_base=np.ones(nb); w_hard=solvent.astype(float)
    qw=np.array([0.2,0.4,0.6,0.8,1.0]); w_tilt=qw[qbin]      # graded by Z'' quintile, all fires kept
    print("  (3) policy per-dollar R (Sum w*R/Sum w), year-block CI | capital-deployed = Sum w / n:")
    for tag,w in (("base equal-wt",w_base),("HARD drop-distress",w_hard),("TILT quintile-graded",w_tilt)):
        md,lo,hi=wmean_boot(yr,R,w,B)
        print(f"      {tag:22} R {md:+.3f} 90%CI[{lo:+.3f},{hi:+.3f}]  cap-deployed {100*w.sum()/nb:.0f}%")
print("\ndone.")
