"""CONDITION DeepOS on fundamentals/quality — does company quality split the oversold bounce?

Two orthogonal quality axes (memory: Piotroski F = IMPROVEMENT, not LEVEL — so test both):
  IMPROVEMENT  Piotroski F-score tiers  lowF(<=3) / midF(4-6) / highF(>=7)
  LEVEL        profitable_ttm (NI_ttm>0)  AND  Altman Z'' (book, no market term) distress/safe
               Z'' = 6.56*WC/TA + 3.26*RE/TA + 6.72*EBIT_ttm/TA + 1.05*BookEq/TL
               distress Z''<1.1, grey 1.1-2.6, safe >2.6  (book-only => fully PIT from statements)

Lead hypothesis (the quality-RECOVERY side): oversold in an IMPROVING / solvent name bounces; oversold in
a DETERIORATING / distressed name is a value-trap knife. So the deployable move is a FILTER that excludes
the low-quality tail and keeps a cleaner book.

Methodology = the locked harness (knife_reaudit / earnings_filter_confirm):
  pinned SEED=7 N=2000, fundamentals-covered subset; DeepOS = rsi<30 & age>=3; faithful NEXT-OPEN entry +
  gap-stop; S2 gross / S4 tiered-cost; nonbull regime gate; NW (Bartlett L=hold-1) vs same-regime random.
  Fundamentals aligned PIT by reportedDate (forward-filled as-of step series — no lookahead).

DECISIVE TESTS (quality has subsumed nothing yet; HA-green has subsumed everything):
  (A) do the tiers actually split DeepOS R?   (B) does any FILTER lift the filtered book + stay year-stable?
  (C) HA-OVERLAP — does DeepOS+HA already avoid the low-quality knife (like it did gaps & earnings)?
      If HA already dodges it, fundamentals is redundant on the live sleeve = closed for deployment.
"""
import os, numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; AGE=3; N=10; TP_ATR,SL_ATR=2.0,1.0
FUND="data/fundamentals.parquet"
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")

if not os.path.exists(FUND):
    raise SystemExit(f"{FUND} not present yet — run fundamentals_pull_full.py to completion first.")

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

# ---- fundamentals: per-symbol as-of quarter list (reportedDate, fscore, profitable, altman_z'') ----
fdf=pd.read_parquet(FUND)
def num(s): return pd.to_numeric(s,errors="coerce")
ta=num(fdf.total_assets); tl=num(fdf.total_liabilities)
wc=num(fdf.current_assets)-num(fdf.current_liabilities); re=num(fdf.retained_earnings)
ebit=num(fdf.ebit_ttm); bookeq=ta-tl
with np.errstate(divide="ignore",invalid="ignore"):
    z=6.56*(wc/ta)+3.26*(re/ta)+6.72*(ebit/ta)+1.05*(bookeq/tl)
fdf=fdf.assign(profitable=(num(fdf.ni_ttm)>0), altman_z=z)
FQ=defaultdict(list)   # symbol -> sorted [(reportedDate, fscore, profitable, z)]
for r in fdf.sort_values(["symbol","reportedDate"]).itertuples(index=False):
    if isinstance(r.reportedDate,str) and r.reportedDate:
        FQ[r.symbol].append((r.reportedDate,float(r.fscore),bool(r.profitable),float(r.altman_z) if np.isfinite(r.altman_z) else np.nan))
covered=[s for s in syms if s in FQ]
print(f"fundamentals-covered {len(covered)}/{len(syms)}  (quarter-rows {len(fdf)})",flush=True)

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

for ii,sym in enumerate(covered):
    if ii%200==0: print(f"  {ii}/{len(covered)}",flush=True)
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
    # PIT forward-fill: as-of each bar use the most recent quarter whose reportedDate <= bar date
    qf=FQ[sym]; farr=np.full(n,np.nan); parr=np.full(n,np.nan); zarr=np.full(n,np.nan); j=0; cf=cp=cz=np.nan
    for i in range(n):
        while j<len(qf) and qf[j][0]<=dts[i]: cf=qf[j][1]; cp=1.0 if qf[j][2] else 0.0; cz=qf[j][3]; j+=1
        farr[i]=cf; parr[i]=cp; zarr[i]=cz
    fcov=~np.isnan(farr)
    lowF=fcov&(farr<=3); midF=fcov&(farr>=4)&(farr<=6); highF=fcov&(farr>=7)
    prof=fcov&(parr==1.0); unprof=fcov&(parr==0.0)
    zc=~np.isnan(zarr); distress=zc&(zarr<1.1); zsafe=zc&(zarr>2.6); zmid=zc&(zarr>=1.1)&(zarr<=2.6)
    badq=lowF|distress   # low-quality knife (deteriorating OR distressed)
    CELLS={
        "deepos":deepos, "RANDOM":np.ones(n,bool), "deepos_fc":deepos&fcov,
        # axis A: improvement tiers
        "lowF":deepos&lowF, "midF":deepos&midF, "highF":deepos&highF,
        # axis B: level
        "prof":deepos&prof, "unprof":deepos&unprof,
        "zsafe":deepos&zsafe, "zmid":deepos&zmid, "zdistress":deepos&distress,
        # deployable filters (exclude the knife, keep cleaner book)
        "Qf_F":deepos&fcov&~lowF, "Qf_P":deepos&prof, "Qf_Z":deepos&zc&~distress,
        "Qf_FZ":deepos&fcov&zc&~badq,
        # HA overlap — does DeepOS+HA already dodge the low-quality knife?
        "HA":deepos&hg, "HA_badq":deepos&hg&badq, "HA_cleanq":deepos&hg&fcov&zc&~badq,
        "HA_lowF":deepos&hg&lowF, "HA_highF":deepos&hg&highF,
        "HA_distress":deepos&hg&distress, "HA_zsafe":deepos&hg&zsafe,
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
                    if scn=="S4" and reg=="nonbull" and cn in ("deepos_fc","Qf_F","Qf_FZ","highF","lowF"):
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
    print(f"\n################ A. QUALITY TIERS within DeepOS — regime={reg} (NW lift vs random) ################")
    for scn in ("S2","S4"):
        b=stNW(("deepos",reg,scn)); bfc=stNW(("deepos_fc",reg,scn))
        print(f"  [{scn}] deepos {fR(b)} | deepos_fcov {fR(bfc)}")
        print(f"        improvement: lowF {fR(stNW(('lowF',reg,scn)))} | midF {fR(stNW(('midF',reg,scn)))} | highF {fR(stNW(('highF',reg,scn)))}")
        print(f"        profitable : prof {fR(stNW(('prof',reg,scn)))} | unprof {fR(stNW(('unprof',reg,scn)))}")
        print(f"        Altman Z'' : safe {fR(stNW(('zsafe',reg,scn)))} | grey {fR(stNW(('zmid',reg,scn)))} | distress {fR(stNW(('zdistress',reg,scn)))}")

print(f"\n################ B. DEPLOYABLE FILTERS (S4, exclude low-quality tail) ################")
for reg in ("nonbull","all"):
    base=stNW(("deepos_fc",reg,"S4")); bn=base[2] if base else 1; bv=base[0] if base else None
    print(f"  regime={reg}  [deepos_fcov base {fR(base)}]")
    print(f"    {'filter':8} {'FILTERED-BOOK S4':>24} {'lift':>8} {'%vol kept':>9}   [definition]")
    for k,defn in [("Qf_F","drop lowF (F<=3)"),("Qf_P","keep profitable"),("Qf_Z","drop Z''-distress"),("Qf_FZ","drop lowF OR distress")]:
        ft=stNW((k,reg,"S4")); lift=f"{ft[0]-bv:+.3f}" if (ft and bv is not None) else "--"; keep=f"{100*ft[2]/bn:.0f}%" if ft else "--"
        print(f"    {k:8} {fR(ft):>24} {lift:>8} {keep:>9}   [{defn}]")

print(f"\n################ C. HA-OVERLAP — does DeepOS+HA already dodge the low-quality knife? ################")
for reg in ("nonbull","all"):
    ha=stNW(("HA",reg,"S4")); hac=stNW(("HA_cleanq",reg,"S4")); hab=stNW(("HA_badq",reg,"S4"))
    print(f"  {reg:8} HA-sleeve {fR(ha):>22} | HA & clean-quality {fR(hac):>22} | HA & BAD-quality {fR(hab):>20}")
    print(f"           HA&lowF {fR(stNW(('HA_lowF',reg,'S4')))} HA&highF {fR(stNW(('HA_highF',reg,'S4')))} | HA&distress {fR(stNW(('HA_distress',reg,'S4')))} HA&zsafe {fR(stNW(('HA_zsafe',reg,'S4')))}")

print(f"\n################ D. YEAR-BY-YEAR (nonbull S4): base vs filters vs tier extremes ################")
print(f"  {'year':>6} | {'deepos_fcov':>18} | {'Qf_FZ':>18} | {'highF':>18} | {'lowF':>18}")
for y in [str(x) for x in range(2016,2027)]:
    g=lambda k:(lambda s:f"{s[0]:+.3f} n{s[2]}" if s else "(thin)")(stNW((k,"nonbull","S4",y),minf=8))
    print(f"  {y:>6} | {g('deepos_fc'):>18} | {g('Qf_FZ'):>18} | {g('highF'):>18} | {g('lowF'):>18}")
print("\ndone.")
