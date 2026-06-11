"""FIRE-DENSITY circuit-breaker on DeepOS — is universe-wide oversold BREADTH the crash signal VIX wasn't?

Prior arc (deepos_vix_*): VIX level+direction both NULL as entry gates — 2018 V-bottom and 2020 knife
are indistinguishable by any entry-time VIX feature. The 2020 damage was NOT pick-the-wrong-name; it
was everything-fired-at-once: ~2009 nonbull DeepOS fires clustered into ~3 weeks → a 10-slot book that
was 100% correlated crashing names. KEY contrast: 2022 had MORE total fires (3543) but spread over a
year and was fine (−0.003R). So the crash signal is fires-per-DAY DENSITY (breadth of capitulation),
not total count — and unlike forward path, density is KNOWABLE at entry (count today's fires).

Hypothesis: high-density fires (systemic capitulation) carry the crash tail; low-density fires
(idiosyncratic dips) carry the clean bounce. Deployable = a density circuit-breaker that suppresses/
downsizes new entries when daily oversold breadth spikes. Addresses the 10-slot crash-capacity tension
in project_live_sleeve_gate.

DECISIVE test (the one VIX-direction FAILED): does dropping high-density fires (1) lift the book AND
(2) RESCUE 2020 WITHOUT wrecking 2018? If density flags 2018's winners too, per-fire density is not the
separator either (→ escalate to a portfolio-drawdown sim, where correlated-book variance is the real harm).

Density = fraction of the eligible scannable universe that is deep-oversold, trailing 5 trading days
(frac5) — smoother than 1-day, captures the cluster. Master calendar = SPY trading days. No lookahead:
frac5 at date d uses fires on days <= d.

Harness = locked (deepos_vix_*): SEED=7 N=2000; DeepOS rsi<30 & age>=3; next-open + gap-stop; S4 tiered
cost; nonbull vs all; NW (Bartlett L=hold-1) lift vs same-regime random. TWO passes (density is x-symbol).
"""
import os, numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; AGE=3; N=10; TP_ATR,SL_ATR=2.0,1.0
DENS_WIN=5            # trailing trading-day window for the breadth signal

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg_map.get(str(d)[:10],False)
CAL=spy.date.astype(str).str[:10].to_numpy()           # master trading calendar
CALpos={d:i for i,d in enumerate(CAL)}
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300 ORDER BY symbol",[START]).df().symbol.tolist()
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")
syms=[s for s in syms if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=sorted(rng.choice(syms,N_SYMBOLS,replace=False))

def load(sym):
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: return None
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14)
    vol20=pd.Series(v).rolling(20).mean().to_numpy(); atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    osr=rsi<OS; age=np.zeros(n,int)
    for i in range(1,n): age[i]=age[i-1]+1 if osr[i] else 0
    deepos=osr&(age>=AGE)
    return d,o,h,l,c,v,dts,n,atr,atr_pct,vol20,elig,deepos

# ---- PASS A: daily breadth on the master calendar (nonbull-eligible deepos fires / eligible universe) ----
nC=len(CAL); fires_d=np.zeros(nC); univ_d=np.zeros(nC)
nonbull_cal=~np.array([isbull(x) for x in CAL])
for ii,sym in enumerate(syms):
    if ii%200==0: print(f"  A {ii}/{len(syms)}",flush=True)
    r=load(sym)
    if r is None: continue
    _,_,_,_,_,_,dts,n,_,_,_,elig,deepos=r
    pos=np.array([CALpos.get(x,-1) for x in dts])
    okp=pos>=0
    for i in np.where(okp&elig)[0]:
        p=pos[i]
        if not nonbull_cal[p]: continue
        univ_d[p]+=1
        if deepos[i]: fires_d[p]+=1
# trailing-window breadth fraction
rf=pd.Series(fires_d).rolling(DENS_WIN,min_periods=1).sum().to_numpy()
ru=pd.Series(univ_d).rolling(DENS_WIN,min_periods=1).sum().to_numpy()
frac5=np.where(ru>0,rf/ru,np.nan)
frac_map={CAL[i]:frac5[i] for i in range(nC) if np.isfinite(frac5[i])}
# tercile breakpoints over the per-fire breadth distribution (balanced buckets)
perfire=np.repeat(frac5[np.isfinite(frac5)],fires_d[np.isfinite(frac5)].astype(int))
q33,q67=np.quantile(perfire,[1/3,2/3]) if len(perfire) else (0.0,0.0)
print(f"breadth frac5: q33={q33:.3f} q67={q67:.3f}  (nonbull fire-days {int((fires_d>0).sum())})",flush=True)

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
YEARCELLS=("deepos","Df_lowdens","dlow","dmid","dhigh")

# ---- PASS B: outcomes bucketed by the breadth a fire fired into ----
for ii,sym in enumerate(syms):
    if ii%200==0: print(f"  B {ii}/{len(syms)}",flush=True)
    r=load(sym)
    if r is None: continue
    d,o,h,l,c,v,dts,n,atr,atr_pct,vol20,elig,deepos=r
    dv20=pd.Series(c*v).rolling(20).mean().to_numpy()
    nxo=np.full(n,np.nan); nxo[:n-1]=o[1:]
    nonbull=~np.array([isbull(x) for x in dts])
    fr=np.array([frac_map.get(x,np.nan) for x in dts])
    frc=~np.isnan(fr)
    dlow=frc&(fr<=q33); dmid=frc&(fr>q33)&(fr<=q67); dhigh=frc&(fr>q67)
    CELLS={
        "deepos":deepos&frc, "RANDOM":np.ones(n,bool),
        "dlow":deepos&dlow, "dmid":deepos&dmid, "dhigh":deepos&dhigh,
        "Df_lowdens":deepos&frc&~dhigh,        # circuit-breaker: drop top-tercile breadth
    }
    rg,_=run(nxo,atr,o,h,l,c,True); ctier=np.array([dv_cost_bp(x) for x in np.nan_to_num(dv20)])/1e4/(SL_ATR*atr_pct)
    res=rg-ctier
    for reg in ("nonbull","all"):
        rmask=nonbull if reg=="nonbull" else np.ones(n,bool)
        ok=elig&~np.isnan(res)&rmask
        if ok.sum()<20: continue
        bmean=res[ok].mean()
        for cn,cm in CELLS.items():
            fidx=np.where(cm&ok)[0]
            if len(fidx)>=5:
                u=np.zeros(n); u[fidx]=res[fidx]-bmean; bumpNW((cn,reg),u,len(fidx))
                if reg=="nonbull" and cn in YEARCELLS:
                    for Y in np.unique(np.array([dts[j2][:4] for j2 in fidx])):
                        yi=fidx[np.array([dts[j2][:4]==Y for j2 in fidx])]
                        if len(yi)>=8:
                            uy=np.zeros(n); uy[yi]=res[yi]-bmean; bumpNW((cn,reg,Y),uy,len(yi))

def stNW(k,minf=30):
    a=NWd.get(k)
    if a is None or a[1]<minf: return None
    L=N-1; W=make_w(L); S,M=a[0],a[1]; G=a[2:2+1+L]; varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def fR(x): return f"{x[0]:+.3f}R t{x[1]:+.1f} n{x[2]}" if x else "(thin)"

for reg in ("nonbull","all"):
    base=stNW(("deepos",reg)); bv=base[0] if base else None; bn=base[2] if base else 1
    print(f"\n################ DENSITY SPLIT (S4) — regime={reg}  [base {fR(base)}] ################")
    print(f"   breadth: dlow(<=q33) {fR(stNW(('dlow',reg)))} | dmid {fR(stNW(('dmid',reg)))} | dhigh(>q67) {fR(stNW(('dhigh',reg)))}")
    ft=stNW(("Df_lowdens",reg)); lift=f"{ft[0]-bv:+.3f}" if (ft and bv is not None) else "--"; keep=f"{100*ft[2]/bn:.0f}%" if ft else "--"
    print(f"   circuit-breaker Df_lowdens (drop top-tercile breadth): {fR(ft)}  lift {lift}  vol {keep}")

print(f"\n################ YEAR-BY-YEAR (nonbull S4) — does dropping high-breadth RESCUE 2020 w/o wrecking 2018? ################")
print(f"  {'year':>6} | {'deepos':>14} | {'Df_lowdens':>14} || {'dlow':>13} | {'dmid':>13} | {'dhigh':>13}")
for y in [str(x) for x in range(2016,2027)]:
    g=lambda k:(lambda s:f"{s[0]:+.3f} n{s[2]}" if s else "(thin)")(stNW((k,"nonbull",y),minf=8))
    print(f"  {y:>6} | {g('deepos'):>14} | {g('Df_lowdens'):>14} || {g('dlow'):>13} | {g('dmid'):>13} | {g('dhigh'):>13}")
print("\ndone.")
