"""DOOR #1: does dropping Altman-Z''-distressed names robustly lift the BARE deep_oversold sleeve?

The aggregate Qf_Z lift (+0.033R nonbull) is suspect because the headline DeepOS nonbull edge is carried by
sparse bull-year samples (cond. script section D: 2020 alone n1573 @ -0.377, several years thin/positive).
This tests the deploy question with a YEAR-BLOCK BOOTSTRAP so the verdict can't ride a couple of lucky years:
resample the observed calendar years WITH REPLACEMENT (K draws, each pulls that whole year's trades),
recompute mean R for base vs Z''-filtered book and the LIFT, 5000x. Report median + 90% CI.

Bare sleeve = the live `deep_oversold` cell (rsi<30 & age>=3), NO HA gate. Faithful next-open + gap-stop +
tiered cost (S4). nonbull = the live regime gate; `all` for contrast. Universe = pinned-2000 ∩ fund-covered.
Verdict: lift CI excludes 0 AND filtered-book mean CI > 0 across years => solvency SHIPS on the bare sleeve.
HA sleeve bootstrapped too, as a secondary contrast (door is bare, but it's free).
"""
import os, numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; AGE=3; N=10; TP_ATR,SL_ATR=2.0,1.0
Z_DISTRESS=1.1; B=5000
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
print(f"fundamentals-covered {len(covered)}  | year-block bootstrap B={B}, drop Z''<{Z_DISTRESS}",flush=True)

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

# collect per-trade records for the bare DeepOS (z-known) book, and the HA-gated book
REC={k:{"yr":[],"R":[],"keep":[],"nb":[]} for k in ("bare","ha")}
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
    hac=(o+h+l+c)/4.0; hao=np.empty(n); hao[0]=(o[0]+c[0])/2
    for i in range(1,n): hao[i]=(hao[i-1]+hac[i-1])/2
    hg=hac>hao
    qf=FQ[sym]; zarr=np.full(n,np.nan); j=0; cz=np.nan
    for i in range(n):
        while j<len(qf) and qf[j][0]<=dts[i]: cz=qf[j][1]; j+=1
        zarr[i]=cz
    zc=~np.isnan(zarr); keep=zarr>=Z_DISTRESS   # filtered book keeps non-distressed
    rg,_=run(nxo,atr,o,h,l,c,True)
    ctier=np.array([dv_cost_bp(x) for x in np.nan_to_num(dv20)])/1e4/(SL_ATR*np.where(atr_pct>0,atr_pct,np.nan))
    res=rg-ctier
    yrs=np.array([int(x[:4]) for x in dts])
    for tag,gate in (("bare",deepos),("ha",deepos&hg)):
        sel=gate&elig&zc&~np.isnan(res)
        idx=np.where(sel)[0]
        if len(idx):
            REC[tag]["yr"].append(yrs[idx]); REC[tag]["R"].append(res[idx])
            REC[tag]["keep"].append(keep[idx]); REC[tag]["nb"].append(nonbull[idx])
for tag in REC:
    for k in REC[tag]: REC[tag][k]=np.concatenate(REC[tag][k]) if REC[tag][k] else np.array([])

def block_boot(yr,R,keep,B):
    uy=np.unique(yr); K=len(uy)
    idx_by={y:np.where(yr==y)[0] for y in uy}
    bs=np.random.default_rng(SEED)
    base=np.empty(B); filt=np.empty(B); lift=np.empty(B)
    for b in range(B):
        draw=bs.choice(uy,K,replace=True)
        ix=np.concatenate([idx_by[y] for y in draw])
        rb=R[ix]; kb=keep[ix]
        base[b]=rb.mean(); filt[b]=rb[kb].mean() if kb.any() else np.nan; lift[b]=filt[b]-base[b]
    return base,filt,lift
def ci(a):
    a=a[~np.isnan(a)]
    return np.median(a),np.percentile(a,5),np.percentile(a,95),float((a>0).mean())

for tag,label in (("bare","BARE deep_oversold (live sleeve)"),("ha","deep_oversold + HA (secondary)")):
    print(f"\n################ {label} ################")
    for reg in ("nonbull","all"):
        m=REC[tag]["nb"] if reg=="nonbull" else np.ones(len(REC[tag]["yr"]),bool)
        yr=REC[tag]["yr"][m]; R=REC[tag]["R"][m]; keep=REC[tag]["keep"][m]
        if len(yr)<50: print(f"  [{reg}] thin (n={len(yr)})"); continue
        nbase=len(R); nfilt=int(keep.sum()); dropped=nbase-nfilt
        base_pt=R.mean(); filt_pt=R[keep].mean(); lift_pt=filt_pt-base_pt
        bb,bf,bl=block_boot(yr,R,keep,B)
        mb,lb,ub,_=ci(bb); mf,lf,uf,pf=ci(bf); ml,ll,ul,pl=ci(bl)
        print(f"  [{reg}]  base n{nbase}  filtered n{nfilt} (drop {dropped}, keep {100*nfilt/nbase:.0f}%)")
        print(f"     base mean   pt {base_pt:+.3f} | boot {mb:+.3f}  90%CI[{lb:+.3f},{ub:+.3f}]")
        print(f"     filt mean   pt {filt_pt:+.3f} | boot {mf:+.3f}  90%CI[{lf:+.3f},{uf:+.3f}]  P(>0)={pf:.2f}")
        print(f"     LIFT        pt {lift_pt:+.3f} | boot {ml:+.3f}  90%CI[{ll:+.3f},{ul:+.3f}]  P(lift>0)={pl:.2f}")
print("\ndone.")
