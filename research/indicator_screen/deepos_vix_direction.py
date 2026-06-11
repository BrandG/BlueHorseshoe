"""DEFENSIVE VIX on DeepOS — does VIX DIRECTION separate the V-bottom bounce from the crash knife?

Prior result (deepos_vix_condition): VIX LEVEL splits the bounce (high-VIX fires carry the edge) but
is (a) redundant with spy_is_nonbull and (b) NOT year-robust — high-VIX concentrates the book into
2020-COVID where the bounce INVERTS (-0.34R). The mean hid a crash-shaped left tail. VIX level can't
tell "panic peaking" (V-bottom, safe) from "panic still building" (knife).

Defensive hypothesis: VIX DIRECTION into the signal does. r5 = VIX(i)/VIX(i-5)-1 (no lookahead — VIX of
the signal day is known before the next-open entry).
  rising  r5 > +0.10  : panic accelerating  -> suspected knife (esp. when already extreme)
  falling r5 < -0.10  : panic subsiding      -> suspected bounce
The deployable move is a CRASH CIRCUIT-BREAKER: drop the (extreme & rising) cell. SUCCESS is judged on
TWO things, not one:
  (1) does dropping it LIFT the filtered book? and crucially
  (2) does it RESCUE year-stability — specifically, does 2020 stop being a -0.34R disaster?
A filter that lifts the mean but leaves 2020 broken is not a crash lever. Connects to the 10-slot
crash-capacity tension in project_live_sleeve_gate.

Harness = locked (deepos_vix_condition): SEED=7 N=2000; DeepOS rsi<30 & age>=3; next-open + gap-stop;
S2/S4; nonbull vs all; NW (Bartlett L=hold-1) lift vs same-regime random; VIX asof PIT.
"""
import os, numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; AGE=3; N=10; TP_ATR,SL_ATR=2.0,1.0
RISE,FALL=0.10,-0.10          # VIX 5d % change thresholds
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

# ---- VIX series -> level + 5d direction, asof-joined by date ----
vdf=pd.read_parquet(VIXP).sort_values("date").reset_index(drop=True)
vc=pd.to_numeric(vdf.close,errors="coerce")
vr5=(vc/vc.shift(5)-1.0)
vdates=vdf.date.astype(str).str[:10].to_numpy()
V_close=vc.to_numpy(); V_r5=vr5.to_numpy()
def vix_asof(dts):
    idx=np.searchsorted(vdates,dts,side="right")-1; ok=idx>=0; ci=np.clip(idx,0,None)
    return (np.where(ok,V_close[ci],np.nan), np.where(ok,V_r5[ci],np.nan))
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
YEARCELLS=("deepos_vc","Df_norise","Df_noHIrise","hi_rise","hi_fall","hi_steady","rise","fall")

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
    vcl,vr=vix_asof(dts); vcov=~np.isnan(vcl); rcov=~np.isnan(vr)
    vhigh=vcov&(vcl>=24)
    rise=rcov&(vr>RISE); fall=rcov&(vr<FALL); steady=rcov&(vr>=FALL)&(vr<=RISE)
    hi_rise=vhigh&rise; hi_fall=vhigh&fall; hi_steady=vhigh&steady
    CELLS={
        "deepos":deepos, "deepos_vc":deepos&vcov&rcov,
        # direction alone (within deepos)
        "rise":deepos&rise, "steady":deepos&steady, "fall":deepos&fall,
        # level x direction — isolate the suspected knife (extreme & rising) vs the bounce (extreme & falling)
        "hi_rise":deepos&hi_rise, "hi_fall":deepos&hi_fall, "hi_steady":deepos&hi_steady,
        # defensive circuit-breakers
        "Df_norise":deepos&rcov&~rise,            # drop ALL rising-VIX fires
        "Df_noHIrise":deepos&rcov&~hi_rise,       # drop only the (extreme & rising) knife cell
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
                    if scn=="S4" and reg=="nonbull" and cn in YEARCELLS:
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
    print(f"\n################ A. VIX DIRECTION splits within DeepOS — regime={reg} ################")
    for scn in ("S2","S4"):
        b=stNW(("deepos_vc",reg,scn))
        print(f"  [{scn}] deepos_vixcov {fR(b)}")
        print(f"        DIRECTION : rising(r5>+10%) {fR(stNW(('rise',reg,scn)))} | steady {fR(stNW(('steady',reg,scn)))} | falling(r5<-10%) {fR(stNW(('fall',reg,scn)))}")
        print(f"        VIX>=24 x : hi&rising {fR(stNW(('hi_rise',reg,scn)))} | hi&steady {fR(stNW(('hi_steady',reg,scn)))} | hi&falling {fR(stNW(('hi_fall',reg,scn)))}")

print(f"\n################ B. DEFENSIVE CIRCUIT-BREAKERS (S4) — lift + volume ################")
for reg in ("nonbull","all"):
    base=stNW(("deepos_vc",reg,"S4")); bn=base[2] if base else 1; bv=base[0] if base else None
    print(f"  regime={reg}  [deepos_vixcov base {fR(base)}]")
    for k,defn in [("Df_norise","drop ALL rising VIX (r5>+10%)"),("Df_noHIrise","drop (VIX>=24 & rising) knife only")]:
        ft=stNW((k,reg,"S4")); lift=f"{ft[0]-bv:+.3f}" if (ft and bv is not None) else "--"; keep=f"{100*ft[2]/bn:.0f}%" if ft else "--"
        print(f"    {k:12} {fR(ft):>24} lift {lift:>7}  vol {keep:>5}   [{defn}]")

print(f"\n################ C. YEAR-BY-YEAR (nonbull S4) — does dropping the knife RESCUE 2020? ################")
print(f"  {'year':>6} | {'deepos_vc':>15} | {'Df_noHIrise':>15} | {'Df_norise':>15} || {'hi_rise(knife)':>16} | {'hi_fall':>13} | {'hi_steady':>13}")
for y in [str(x) for x in range(2016,2027)]:
    g=lambda k:(lambda s:f"{s[0]:+.3f} n{s[2]}" if s else "(thin)")(stNW((k,"nonbull","S4",y),minf=8))
    print(f"  {y:>6} | {g('deepos_vc'):>15} | {g('Df_noHIrise'):>15} | {g('Df_norise'):>15} || {g('hi_rise'):>16} | {g('hi_fall'):>13} | {g('hi_steady'):>13}")
print("\ndone.")
