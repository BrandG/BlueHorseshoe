"""OPTIONS-IV/SKEW conditioning on DeepOS — does option-implied fear (per-name, cross-sectional)
select among deep-oversold fires?

Axis from the conditioning campaign (project_deepos_conditioning_rollup): market-level fear
(VIX level/direction, fire-density) is exhausted — redundant with the nonbull gate and
2018/2020-inseparable. This tests the PER-NAME, cross-sectional variant: IV level/rank and
25-delta put/call skew measured PIT on the fire date (EOD chain, knowable before next-open
entry). Hypothesis split:
  - IV level (atm_iv / iv_pctile): prior REDUNDANT — a name that just cratered has mechanically
    elevated IV (realized vol re-measured); expect the depth control to kill any gradient.
  - skew_25d (put25_iv - call25_iv): the live candidate — crash-insurance demand / informed
    positioning, plausibly orthogonal to depth. Competes with news for the "priced fear" slot.

Features from data/options_iv_features.parquet (AV HISTORICAL_OPTIONS backfill, one EOD chain
per fire; quality gates: valid-IV 0.01-5, 25D delta bands [0.10,0.45]). Fire list = the parquet
itself (same locked census, SEED=7 N=2000) — guarantees fire<->feature consistency; duckdb
supplies prices for outcomes only. COVERAGE CONFOUND: ~24% of fires have no usable chain and
optionability correlates with size; nochain cell reported with median $vol, and covered-only
tercile splits are the cleaner read (same caveat structure as the news gauntlet).

Cells (tercile cuts data-driven from covered NONBULL fires):
  nochain                 no usable chain / no valid atm_iv
  aiv_low/mid/high        raw atm_iv terciles (absolute fear; time-series confounded, 2020-heavy)
  ivp_low/mid/high        iv_pctile terciles (cross-sectional within fire date - the cleaner IV read)
  sk_low/mid/high         skew_25d terciles among valid-skew fires
  skq_low/mid/high        skew terciles re-cut within quote-quality subset (atm_spread_pct<=0.5)
  pc_low/mid/high         pcr_oi terciles among valid (rank-based, robust to the OI tails)
Harness = locked: next-open + gap-stop; S4 tiered cost; keep all firings + NW (Bartlett
L=hold-1); lift vs same-symbol eligible-day baseline.
"""
import numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

START="2016-01-01"; OPT_END="2026-06-11"
N=10; TP_ATR,SL_ATR=2.0,1.0
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
SPREAD_Q=0.5

# ---- features (the fire list IS the parquet) ----
feat=pd.read_parquet("data/options_iv_features.parquet")
feat["date"]=feat.date.astype(str).str[:10]
feat=feat[feat.date<=OPT_END].copy()
print(f"fires from parquet: {len(feat)} | covered(atm_iv): {feat.atm_iv.notna().sum()} "
      f"| valid skew: {feat.skew_25d.notna().sum()}",flush=True)

nb=feat[feat.nonbull]
def cuts(s):
    s=s.dropna()
    return tuple(np.quantile(s,[1/3,2/3])) if len(s) else (np.nan,np.nan)
C_AIV=cuts(nb.atm_iv); C_IVP=cuts(nb.iv_pctile); C_SK=cuts(nb.skew_25d); C_PC=cuts(nb.pcr_oi)
C_SKQ=cuts(nb.loc[nb.atm_spread_pct<=SPREAD_Q,"skew_25d"])
print(f"nonbull cuts: atm_iv {C_AIV[0]:.3f}/{C_AIV[1]:.3f} | iv_pctile {C_IVP[0]:.3f}/{C_IVP[1]:.3f} "
      f"| skew {C_SK[0]:+.3f}/{C_SK[1]:+.3f} | skew(q) {C_SKQ[0]:+.3f}/{C_SKQ[1]:+.3f} "
      f"| pcr {C_PC[0]:.2f}/{C_PC[1]:.2f}",flush=True)

def tercile_masks(vals,c):
    lo=vals<=c[0]; mid=(vals>c[0])&(vals<=c[1]); hi=vals>c[1]
    return lo,mid,hi

# ---- harness (locked) ----
con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg_map.get(str(d)[:10],False)

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
NWd={}
def make_w(L): return np.array([1.0-j/(L+1) for j in range(L+1)])
def bumpNW(k,u,m):
    a=NWd.setdefault(k,np.zeros(3+N)); a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    for j in range(1,N): a[2+j]+=float(u[:-j]@u[j:])
DVC=defaultdict(list)

CELLNAMES=("deepos","nochain","aiv_low","aiv_mid","aiv_high","ivp_low","ivp_mid","ivp_high",
           "sk_low","sk_mid","sk_high","skq_low","skq_mid","skq_high","pc_low","pc_mid","pc_high")
YEARCELLS=("deepos","ivp_low","ivp_high","sk_low","sk_high")

bysym={s:g for s,g in feat.groupby("symbol")}
missing=0
for ii,(sym,g) in enumerate(sorted(bysym.items())):
    if ii%200==0: print(f"  {ii}/{len(bysym)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    idx={dt:i for i,dt in enumerate(dts)}
    atr=talib.ATR(h,l,c,14)
    vol20=pd.Series(v).rolling(20).mean().to_numpy(); atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    dv20=pd.Series(c*v).rolling(20).mean().to_numpy()
    nxo=np.full(n,np.nan); nxo[:n-1]=o[1:]
    nonbull=~np.array([isbull(x) for x in dts])

    fi=[]; rows=[]
    for r in g.itertuples(index=False):
        i=idx.get(r.date)
        if i is None: missing+=1; continue
        fi.append(i); rows.append(r)
    if not fi: continue
    fi=np.array(fi)
    aiv=np.array([r.atm_iv for r in rows]); ivp=np.array([r.iv_pctile for r in rows])
    sk=np.array([r.skew_25d for r in rows]); spr=np.array([r.atm_spread_pct for r in rows])
    pc=np.array([r.pcr_oi for r in rows])
    covered=~np.isnan(aiv); skv=~np.isnan(sk); skqv=skv&(spr<=SPREAD_Q); pcv=~np.isnan(pc)

    def mk(sel):
        m=np.zeros(n,bool); m[fi[sel]]=True; return m
    al,am,ah=tercile_masks(aiv,C_AIV); il,im,ih=tercile_masks(ivp,C_IVP)
    sl_,sm_,sh_=tercile_masks(sk,C_SK); ql,qm,qh=tercile_masks(sk,C_SKQ)
    pl,pm,ph=tercile_masks(pc,C_PC)
    CELLS={
        "deepos":mk(np.ones(len(fi),bool)),
        "nochain":mk(~covered),
        "aiv_low":mk(covered&al),"aiv_mid":mk(covered&am),"aiv_high":mk(covered&ah),
        "ivp_low":mk(covered&il),"ivp_mid":mk(covered&im),"ivp_high":mk(covered&ih),
        "sk_low":mk(skv&sl_),"sk_mid":mk(skv&sm_),"sk_high":mk(skv&sh_),
        "skq_low":mk(skqv&ql),"skq_mid":mk(skqv&qm),"skq_high":mk(skqv&qh),
        "pc_low":mk(pcv&pl),"pc_mid":mk(pcv&pm),"pc_high":mk(pcv&ph),
    }
    rg,_=run(nxo,atr,o,h,l,c,True); ctier=np.array([dv_cost_bp(x) for x in np.nan_to_num(dv20)])/1e4/(SL_ATR*atr_pct)
    res=rg-ctier
    for reg in ("nonbull","all"):
        rmask=nonbull if reg=="nonbull" else np.ones(n,bool)
        ok=elig&~np.isnan(res)&rmask
        if ok.sum()<20: continue
        bmean=res[ok].mean()
        for cn,cm in CELLS.items():
            ci=np.where(cm&ok)[0]
            if len(ci)>=1:
                u=np.zeros(n); u[ci]=res[ci]-bmean; bumpNW((cn,reg),u,len(ci))
                if reg=="nonbull":
                    DVC[cn].extend(dv20[ci][~np.isnan(dv20[ci])].tolist())
                    if cn in YEARCELLS:
                        for Y in np.unique(np.array([dts[j][:4] for j in ci])):
                            yi=ci[np.array([dts[j][:4]==Y for j in ci])]
                            if len(yi)>=5:
                                uy=np.zeros(n); uy[yi]=res[yi]-bmean; bumpNW((cn,reg,Y),uy,len(yi))
if missing: print(f"WARN: {missing} parquet fires not found in duckdb dates",flush=True)

def stNW(k,minf=30):
    a=NWd.get(k)
    if a is None or a[1]<minf: return None
    L=N-1; W=make_w(L); S,M=a[0],a[1]; G=a[2:2+1+L]; varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def fR(x): return f"{x[0]:+.3f}R t{x[1]:+.1f} n{x[2]}" if x else "(thin)"
def mdv(cn):
    x=DVC.get(cn)
    return f"${np.median(x)/1e6:.0f}M" if x else "--"

for reg in ("nonbull","all"):
    base=stNW(("deepos",reg))
    print(f"\n############ OPTIONS-IV SPLIT (S4, fires {START}+) — regime={reg}  [base {fR(base)}] ############")
    print(f"   coverage: nochain {fR(stNW(('nochain',reg)))}   [median $vol: nochain {mdv('nochain')} vs covered-mid {mdv('ivp_mid')}]")
    print(f"   atm_iv terciles (raw level):   aiv_low {fR(stNW(('aiv_low',reg)))} | aiv_mid {fR(stNW(('aiv_mid',reg)))} | aiv_high {fR(stNW(('aiv_high',reg)))}")
    print(f"   iv_pctile terciles (x-sec):    ivp_low {fR(stNW(('ivp_low',reg)))} | ivp_mid {fR(stNW(('ivp_mid',reg)))} | ivp_high {fR(stNW(('ivp_high',reg)))}")
    print(f"   skew_25d terciles:             sk_low  {fR(stNW(('sk_low',reg)))} | sk_mid  {fR(stNW(('sk_mid',reg)))} | sk_high  {fR(stNW(('sk_high',reg)))}")
    print(f"   skew terciles, spread<={SPREAD_Q}:    skq_low {fR(stNW(('skq_low',reg)))} | skq_mid {fR(stNW(('skq_mid',reg)))} | skq_high {fR(stNW(('skq_high',reg)))}")
    print(f"   pcr_oi terciles:               pc_low  {fR(stNW(('pc_low',reg)))} | pc_mid  {fR(stNW(('pc_mid',reg)))} | pc_high  {fR(stNW(('pc_high',reg)))}")

print(f"\n############ YEAR-BY-YEAR (nonbull S4) ############")
print(f"  {'year':>6} | {'deepos':>14} | {'ivp_low':>13} | {'ivp_high':>13} | {'sk_low':>13} | {'sk_high':>13}")
for y in [str(x) for x in range(2016,2027)]:
    g=lambda k:(lambda s:f"{s[0]:+.3f} n{s[2]}" if s else "(thin)")(stNW((k,"nonbull",y),minf=8))
    print(f"  {y:>6} | {g('deepos'):>14} | {g('ivp_low'):>13} | {g('ivp_high'):>13} | {g('sk_low'):>13} | {g('sk_high'):>13}")
print("\ndone.")
