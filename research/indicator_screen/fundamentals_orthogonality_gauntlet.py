"""DOOR #3: is the Altman-Z'' solvency lift ORTHOGONAL, or just a proxy for the cheap/volatile penny tail?

Door #1 showed dropping Z''-distress lifts the BARE deep_oversold sleeve +0.062R nonbull (year-robust).
Risk: distressed names are also cheaper / more volatile / thinner / deeper-oversold — so a plain price/ATR/
$-vol/depth filter might capture the SAME lift more cheaply (and without a fundamentals pipeline in prod).

Decisive test = NESTED RESIDUAL (year-block bootstrap, the live regime gate nonbull + all):
  base book -> apply a CHEAPNESS filter C (composite of low-price/high-ATR/low-$vol, calibrated to drop the
  same ~38% as Z'') -> then add Z'' ON TOP (residual lift_{Z|C}) and the reverse (lift_{C|Z}).
  - lift_{Z|C} CI still excludes 0  => Z'' adds orthogonal alpha beyond cheapness => solvency is real, ship it.
  - lift_{Z|C} ~ 0 while C alone ~ matches Z''  => cheapness captures it => ship the cheap filter, drop fundamentals.
Plus: covariate medians (distress vs keep) pleq depth/age control, and filter-overlap% (does distress ⊂ cheap-dropped?).
"""
import os, numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; AGE=3; N=10; TP_ATR,SL_ATR=2.0,1.0
Z_DISTRESS=1.1; B=3000
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
print(f"fundamentals-covered {len(covered)}  | orthogonality gauntlet B={B}",flush=True)

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

C={k:[] for k in ("yr","R","nb","dist","price","atrp","lvol","rsi","age")}
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
    sel=deepos&elig&zc&~np.isnan(res)&(dv20>0)
    idx=np.where(sel)[0]
    if not len(idx): continue
    C["yr"].append(np.array([int(x[:4]) for x in dts[idx]])); C["R"].append(res[idx]); C["nb"].append(nonbull[idx])
    C["dist"].append(zarr[idx]<Z_DISTRESS); C["price"].append(c[idx]); C["atrp"].append(atr_pct[idx])
    C["lvol"].append(np.log10(dv20[idx])); C["rsi"].append(rsi[idx]); C["age"].append(age[idx].astype(float))
for k in C: C[k]=np.concatenate(C[k]) if C[k] else np.array([])

def zscore(x):
    mu=np.nanmean(x); sd=np.nanstd(x); return (x-mu)/sd if sd>0 else x*0.0
def block_boot_lift(yr,R,keepmask,refmask,B):
    """median + 90%CI of mean(R[keep]) - mean(R[ref]); year-block resample."""
    uy=np.unique(yr); K=len(uy); idx_by={y:np.where(yr==y)[0] for y in uy}
    bs=np.random.default_rng(SEED); out=np.empty(B)
    for b in range(B):
        ix=np.concatenate([idx_by[y] for y in bs.choice(uy,K,replace=True)])
        rk=R[ix][keepmask[ix]]; rr=R[ix][refmask[ix]]
        out[b]=(rk.mean() if len(rk) else np.nan)-(rr.mean() if len(rr) else np.nan)
    out=out[~np.isnan(out)]; return np.median(out),np.percentile(out,5),np.percentile(out,95),float((out>0).mean())

for reg in ("nonbull","all"):
    m=C["nb"] if reg=="nonbull" else np.ones(len(C["yr"]),bool)
    yr=C["yr"][m]; R=C["R"][m]; dist=C["dist"][m]
    price=C["price"][m]; atrp=C["atrp"][m]; lvol=C["lvol"][m]; rsi=C["rsi"][m]; age=C["age"][m]
    nb=len(R); keepZ=~dist; dropfrac=1.0-keepZ.mean()
    # cheapness composite (higher = cheaper/junkier): low price, high atr, low $vol
    cheap=zscore(-price)+zscore(atrp)+zscore(-lvol)
    thr=np.quantile(cheap,keepZ.mean())        # keep the same fraction as Z'' keeps
    keepC=cheap<=thr
    # single-covariate proxies, each calibrated to keep the same fraction as Z''
    f=keepZ.mean()
    keep_pr=price>=np.quantile(price,1-f)      # drop cheapest (1-f)
    keep_at=atrp<=np.quantile(atrp,f)          # drop most volatile
    keep_vo=lvol>=np.quantile(lvol,1-f)        # drop thinnest
    keep_dp=~((rsi<=np.quantile(rsi,1-f)))     # drop deepest-rsi (depth control); keep f
    allmask=np.ones(nb,bool)
    print(f"\n################ DOOR #3  regime={reg}  (bare deep_oversold, n={nb}, Z'' keeps {100*f:.0f}%) ################")
    print(f"  covariate medians   {'distress':>12} {'keep(solvent)':>14}")
    for nm,arr in (("price",price),("atr_pct",atrp),("log10$vol",lvol),("rsi",rsi),("os_age",age)):
        print(f"    {nm:12} {np.median(arr[dist]):>12.3f} {np.median(arr[keepZ]):>14.3f}")
    print(f"  filter overlap: {100*np.mean(keepC[dist]==False):.0f}% of distress is ALSO dropped by cheapness filter (1=identical)")
    def line(tag,keepmask,ref):
        md,lo,hi,p=block_boot_lift(yr,R,keepmask,ref,B)
        return f"  {tag:26} lift {md:+.3f} 90%CI[{lo:+.3f},{hi:+.3f}] P>0={p:.2f}  keep {100*keepmask.mean():.0f}%"
    print("  -- standalone lifts vs base book --")
    print(line("Z'' (drop distress)",keepZ,allmask))
    print(line("Cheapness composite",keepC,allmask))
    print(line("price-floor only",keep_pr,allmask))
    print(line("atr-ceiling only",keep_at,allmask))
    print(line("$vol-floor only",keep_vo,allmask))
    print(line("rsi-depth control",keep_dp,allmask))
    print("  -- NESTED RESIDUAL (decisive) --")
    print(line("Z'' on top of cheapness",keepC&keepZ,keepC))    # does solvency add AFTER cheap filter?
    print(line("cheapness on top of Z''",keepZ&keepC,keepZ))    # does cheapness add AFTER solvency?
    print(line("Z'' on top of $vol-floor",keep_vo&keepZ,keep_vo))
    print(line("Z'' on top of price-floor",keep_pr&keepZ,keep_pr))
print("\ndone.")
