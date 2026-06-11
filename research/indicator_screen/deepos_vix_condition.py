"""CONDITION DeepOS on VIX — does market fear carry edge ORTHOGONAL to the spy_is_nonbull gate?

The live DeepOS sleeve is gated only by spy_is_nonbull = NOT(SPY>EMA200 AND EMA50>EMA200) — a
SLOW price-trend proxy. The edge is documented strongest-in-fear. VIX is a FAST, forward-looking
implied-vol read that can capture acute panic the EMA gate misses (EMA200 stays intact through a
sharp spike). So the question is NOT "does VIX predict bounces" but:

  Within the nonbull-gated book, does conditioning on VIX still SPLIT the oversold bounce?
  If yes  -> VIX carries incremental fear info the EMA gate lacks (orthogonal, possibly deployable).
  If no   -> the EMA gate already encodes the fear dimension (VIX redundant) -> clean negative,
             redirect to VIX-as-sizing rather than VIX-as-gate.

Three VIX representations (lead with spike/percentile — most orthogonal to a slow EMA gate):
  LEVEL    absolute VIX close            vlow<16 / vmid 16-24 / vhigh>=24
  PCTILE   90d rank of VIX close         plow<40 / pmid / phigh>70   (relative fear, regime-agnostic)
  SPIKE    VIX / its 20d SMA             calm<1.00 / flat / spike>1.12 (acute dislocation)

Methodology = the locked harness (fundamentals_condition / knife_reaudit):
  pinned SEED=7 N=2000; DeepOS = rsi<30 & age>=3; faithful NEXT-OPEN entry + gap-stop;
  S2 gross / S4 tiered-cost; nonbull vs all regime; NW (Bartlett L=hold-1) lift vs same-regime random.
  VIX aligned PIT by asof (most-recent close on or before the bar date) — market-wide, no lookahead.

DECISIVE TESTS:
  (A) do VIX buckets actually split DeepOS R, and does the split survive WITHIN nonbull (orthogonality)?
  (B) does a fear/spike FILTER lift the filtered book + stay year-stable?
  (C) HA-OVERLAP — does DeepOS+HA already capture the fear dimension (like it did gaps/earnings/quality)?
      If HA already dodges the calm-VIX tail, VIX is redundant on the live sleeve.
"""
import os, numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; AGE=3; N=10; TP_ATR,SL_ATR=2.0,1.0
VIXP="data/vix_history.parquet"
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")

if not os.path.exists(VIXP):
    raise SystemExit(f"{VIXP} not present — run pull_vix_history.py first.")

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

# ---- VIX series -> derived metrics computed ONCE, asof-joined by date ----
vdf=pd.read_parquet(VIXP).sort_values("date").reset_index(drop=True)
vc=pd.to_numeric(vdf.close,errors="coerce")
vsma20=vc.rolling(20).mean()
vspike=vc/vsma20
vpct90=vc.rolling(90).apply(lambda w:(w<=w[-1]).mean()*100.0,raw=True)
vdates=vdf.date.astype(str).str[:10].to_numpy()
V_close=vc.to_numpy(); V_spike=vspike.to_numpy(); V_pct=vpct90.to_numpy()
def vix_asof(dts):
    """Most-recent VIX metrics on or before each bar date (YYYY-MM-DD lexicographic)."""
    idx=np.searchsorted(vdates,dts,side="right")-1
    ok=idx>=0
    out_c=np.where(ok,V_close[np.clip(idx,0,None)],np.nan)
    out_s=np.where(ok,V_spike[np.clip(idx,0,None)],np.nan)
    out_p=np.where(ok,V_pct[np.clip(idx,0,None)],np.nan)
    return out_c,out_s,out_p
print(f"VIX rows {len(vdf)}  range {vdates[0]} -> {vdates[-1]}",flush=True)

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

for ii,sym in enumerate(syms):
    if ii%200==0: print(f"  {ii}/{len(syms)}",flush=True)
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
    # VIX asof each bar (most recent close on or before bar date)
    vcl,vsp,vpc=vix_asof(dts)
    vcov=~np.isnan(vcl); spcov=~np.isnan(vsp); pccov=~np.isnan(vpc)
    vlow=vcov&(vcl<16); vmid=vcov&(vcl>=16)&(vcl<24); vhigh=vcov&(vcl>=24)
    plow=pccov&(vpc<40); pmid=pccov&(vpc>=40)&(vpc<=70); phigh=pccov&(vpc>70)
    vcalm=spcov&(vsp<1.00); vflat=spcov&(vsp>=1.00)&(vsp<=1.12); vspk=spcov&(vsp>1.12)
    CELLS={
        "deepos":deepos, "RANDOM":np.ones(n,bool), "deepos_vc":deepos&vcov,
        # A: level / percentile / spike splits
        "vlow":deepos&vlow, "vmid":deepos&vmid, "vhigh":deepos&vhigh,
        "plow":deepos&plow, "pmid":deepos&pmid, "phigh":deepos&phigh,
        "vcalm":deepos&vcalm, "vflat":deepos&vflat, "vspk":deepos&vspk,
        # B: deployable filters (keep the fear/spike tail, drop the calm tail)
        "Vf_fear":deepos&vcov&~vlow, "Vf_pct":deepos&pccov&~plow, "Vf_spike":deepos&spcov&~vcalm,
        # C: HA overlap — does DeepOS+HA already capture the fear dimension?
        "HA":deepos&hg, "HA_vlow":deepos&hg&vlow, "HA_vhigh":deepos&hg&vhigh,
        "HA_vcalm":deepos&hg&vcalm, "HA_vspk":deepos&hg&vspk,
    }
    rg,_=run(nxo,atr,o,h,l,c,True); ctier=np.array([dv_cost_bp(x) for x in np.nan_to_num(dv20)])/1e4/(SL_ATR*atr_pct)
    RES={"S2":rg,"S4":rg-ctier}
    for reg in ("nonbull","all"):
        rmask=nonbull if reg=="nonbull" else np.ones(n,bool)
        for scn in ("S2","S4"):
            res=RES[scn]; ok=elig&~np.isnan(res)&rmask
            if ok.sum()<20: continue
            bmean=res[ok].mean()
            for cn,cm in CELLS.items():
                fidx=np.where(cm&ok)[0]
                if len(fidx)>=5:
                    u=np.zeros(n); u[fidx]=res[fidx]-bmean; bumpNW((cn,reg,scn),u,len(fidx))
                    if scn=="S4" and reg=="nonbull" and cn in ("deepos_vc","Vf_fear","Vf_spike","vhigh","vlow","vspk","vcalm"):
                        for Y in np.unique(np.array([dts[j2][:4] for j2 in fidx])):
                            yi=fidx[np.array([dts[j2][:4]==Y for j2 in fidx])]
                            if len(yi)>=8:
                                uy=np.zeros(n); uy[yi]=res[yi]-bmean; bumpNW((cn,reg,scn,Y),uy,len(yi))

def stNW(k,minf=30):
    a=NWd.get(k)
    if a is None or a[1]<minf: return None
    L=N-1; W=make_w(L); S,M=a[0],a[1]; G=a[2:2+1+L]; varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def fR(x): return f"{x[0]:+.3f}R t{x[1]:+.1f} n{x[2]}" if x else "(thin)"

for reg in ("nonbull","all"):
    print(f"\n################ A. VIX SPLITS within DeepOS — regime={reg} (NW lift vs random) ################")
    for scn in ("S2","S4"):
        b=stNW(("deepos",reg,scn)); bvc=stNW(("deepos_vc",reg,scn))
        print(f"  [{scn}] deepos {fR(b)} | deepos_vixcov {fR(bvc)}")
        print(f"        LEVEL  : vlow<16 {fR(stNW(('vlow',reg,scn)))} | vmid {fR(stNW(('vmid',reg,scn)))} | vhigh>=24 {fR(stNW(('vhigh',reg,scn)))}")
        print(f"        PCTILE : plow<40 {fR(stNW(('plow',reg,scn)))} | pmid {fR(stNW(('pmid',reg,scn)))} | phigh>70 {fR(stNW(('phigh',reg,scn)))}")
        print(f"        SPIKE  : calm<1.0 {fR(stNW(('vcalm',reg,scn)))} | flat {fR(stNW(('vflat',reg,scn)))} | spike>1.12 {fR(stNW(('vspk',reg,scn)))}")

print(f"\n################ B. DEPLOYABLE FILTERS (S4, drop the calm tail) ################")
for reg in ("nonbull","all"):
    base=stNW(("deepos_vc",reg,"S4")); bn=base[2] if base else 1; bv=base[0] if base else None
    print(f"  regime={reg}  [deepos_vixcov base {fR(base)}]")
    print(f"    {'filter':9} {'FILTERED-BOOK S4':>24} {'lift':>8} {'%vol kept':>9}   [definition]")
    for k,defn in [("Vf_fear","drop vlow (VIX<16)"),("Vf_pct","drop plow (pct<40)"),("Vf_spike","drop calm (vix<sma20)")]:
        ft=stNW((k,reg,"S4")); lift=f"{ft[0]-bv:+.3f}" if (ft and bv is not None) else "--"; keep=f"{100*ft[2]/bn:.0f}%" if ft else "--"
        print(f"    {k:9} {fR(ft):>24} {lift:>8} {keep:>9}   [{defn}]")

print(f"\n################ C. HA-OVERLAP — does DeepOS+HA already capture the fear dimension? ################")
for reg in ("nonbull","all"):
    ha=stNW(("HA",reg,"S4"))
    print(f"  {reg:8} HA-sleeve {fR(ha):>22}")
    print(f"           HA&vlow {fR(stNW(('HA_vlow',reg,'S4')))} HA&vhigh {fR(stNW(('HA_vhigh',reg,'S4')))} | HA&calm {fR(stNW(('HA_vcalm',reg,'S4')))} HA&spike {fR(stNW(('HA_vspk',reg,'S4')))}")

print(f"\n################ D. YEAR-BY-YEAR (nonbull S4): base vs fear/spike filters vs tier extremes ################")
print(f"  {'year':>6} | {'deepos_vc':>16} | {'Vf_fear':>16} | {'vhigh':>16} | {'vlow':>16} | {'vspk':>16}")
for y in [str(x) for x in range(2016,2027)]:
    g=lambda k:(lambda s:f"{s[0]:+.3f} n{s[2]}" if s else "(thin)")(stNW((k,"nonbull","S4",y),minf=8))
    print(f"  {y:>6} | {g('deepos_vc'):>16} | {g('Vf_fear'):>16} | {g('vhigh'):>16} | {g('vlow'):>16} | {g('vspk'):>16}")
print("\ndone.")
