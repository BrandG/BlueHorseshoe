"""Deep-tail probe of the options-fear interaction found by deepos_options_depth_control:

Both options features are depth-orthogonal by correlation (ivp/sk vs rsi/dd10 all |corr|<=0.11)
yet their gaps CONCENTRATE in the deepest-dislocation buckets and vanish elsewhere:
  ivlow GAP:  DD10-deep +0.165 (ivrest -0.067R t-1.7), RSI-deep +0.146 (ivrest -0.010) — ~0 in 6/9
  skhigh GAP: DD10-deep -0.200 (skhigh -0.110R t-2.0), RSI-deep -0.212 (skhigh -0.112) — flips shallow
Same shape, two features, two depth axes => hypothesis: option-priced fear discriminates ONLY
among the deepest knives — "the deep dislocations the options market is paying to insure are the
ones that fail; the quiet ones bounce."

This probe makes that one deployable cell and stress-tests it:
  1. FEAR flag (covered fires): ivp > q67  OR  skew_25d > q67  (cuts from covered nonbull)
  2. Deep cell: DD10-deep (primary) and RSI-deep (variant) — fear vs nofear, overall + YEAR table
     (era gate: sign-consistent in the wide years or it joins the VIX corpse)
  3. Altman-Z'' control: is priced fear just re-measuring solvency distress (the campaign's one
     wired-adjacent orthogonal axis)? Within deep cell: fear-vs-nofear gap inside z_low / z_high /
     z_na; plus P(fear | z bucket) composition check.
  4. Deployable Df_dropfear = take every fire EXCEPT (deep & covered & fear): lift vs base, %vol.
Harness locked: next-open + gap-stop, S4 cost, NW Bartlett L=hold-1, same-symbol baseline;
fires/features = data/options_iv_features.parquet.
"""
import numpy as np, pandas as pd, talib, duckdb

START="2016-01-01"; OPT_END="2026-06-11"
N=10; TP_ATR,SL_ATR=2.0,1.0
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
Z_STALE_D=400

feat=pd.read_parquet("data/options_iv_features.parquet")
feat["date"]=feat.date.astype(str).str[:10]
feat=feat[feat.date<=OPT_END].copy()
nb=feat[feat.nonbull]
IVP_Q67=float(np.quantile(nb.iv_pctile.dropna(),2/3))
SK_Q67=float(np.quantile(nb.skew_25d.dropna(),2/3))
print(f"fear cuts (nonbull): ivp>{IVP_Q67:.3f} OR sk>{SK_Q67:+.3f}",flush=True)

# ---- Altman-Z'' (PIT: latest report strictly before fire date, <=400d stale) ----
fund=pd.read_parquet("data/fundamentals.parquet")
ta=fund.total_assets.where(fund.total_assets>0); tl=fund.total_liabilities.where(fund.total_liabilities>0)
fund["z2"]=(3.25+6.56*(fund.current_assets-fund.current_liabilities)/ta
            +3.26*fund.retained_earnings/ta+6.72*fund.ebit_ttm/ta+1.05*(ta-tl)/tl)
fund["rd"]=fund.reportedDate.astype(str).str[:10]
fund=fund.dropna(subset=["rd"]).sort_values(["symbol","rd"])
FUND={s:(g.rd.to_numpy(),g.z2.to_numpy(float)) for s,g in fund.groupby("symbol")}
def z_at(sym,d):
    t=FUND.get(sym)
    if t is None: return np.nan
    i=int(np.searchsorted(t[0],d,side="left"))-1
    if i<0: return np.nan
    if (pd.Timestamp(d)-pd.Timestamp(t[0][i])).days>Z_STALE_D: return np.nan
    return t[1][i]

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

bysym={s:g for s,g in feat.groupby("symbol")}
def sym_arrays(sym):
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: return None
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14)
    dd10=(pd.Series(c).rolling(10).max().to_numpy()-c)/np.where(atr>0,atr,np.nan)
    vol20=pd.Series(v).rolling(20).mean().to_numpy(); atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    return o,h,l,c,v,dts,n,atr,atr_pct,elig,rsi,dd10,{dt:i for i,dt in enumerate(dts)}

# ---- pass 1: depth at fires; cuts; Z distribution in the deep cell ----
FD={}; dist_r=[]; dist_d=[]
for ii,(sym,g) in enumerate(sorted(bysym.items())):
    if ii%200==0: print(f"  P1 {ii}/{len(bysym)}",flush=True)
    a=sym_arrays(sym)
    if a is None: continue
    rsi,dd10,idx=a[10],a[11],a[12]
    for r in g.itertuples(index=False):
        i=idx.get(r.date)
        if i is None: continue
        FD[(sym,r.date)]=(float(rsi[i]),float(dd10[i]))
        if r.nonbull and not np.isnan(r.atm_iv):
            dist_r.append(rsi[i]); dist_d.append(dd10[i])
r33=float(np.quantile(np.array(dist_r),1/3))
dd=np.array(dist_d); d67=float(np.quantile(dd[~np.isnan(dd)],2/3))
print(f"deep cuts (covered nonbull): RSI<= {r33:.1f} | DD10> {d67:.2f}",flush=True)

zvals=[]
for r in nb.itertuples(index=False):
    fd=FD.get((r.symbol,r.date))
    if fd is None or np.isnan(r.atm_iv): continue
    if fd[1]>d67:
        z=z_at(r.symbol,r.date)
        if not np.isnan(z): zvals.append(z)
ZMED=float(np.median(zvals)) if zvals else np.nan
print(f"Z'' known for {len(zvals)} deep covered nonbull fires | median {ZMED:.2f} (z_low = below median)",flush=True)
fear_n=z_n=0; comp={"z_low":[0,0],"z_high":[0,0],"z_na":[0,0]}
for r in nb.itertuples(index=False):
    fd=FD.get((r.symbol,r.date))
    if fd is None or np.isnan(r.atm_iv) or fd[1]<=d67: continue
    fear=(not np.isnan(r.iv_pctile) and r.iv_pctile>IVP_Q67) or (not np.isnan(r.skew_25d) and r.skew_25d>SK_Q67)
    z=z_at(r.symbol,r.date)
    kb="z_na" if np.isnan(z) else ("z_low" if z<ZMED else "z_high")
    comp[kb][1]+=1; comp[kb][0]+=int(fear)
print("composition P(fear | z bucket), deep covered nonbull: "
      +" | ".join(f"{k} {100*v[0]/v[1]:.0f}% (n{v[1]})" for k,v in comp.items() if v[1]),flush=True)

# ---- pass 2: outcomes ----
for ii,(sym,g) in enumerate(sorted(bysym.items())):
    if ii%200==0: print(f"  P2 {ii}/{len(bysym)}",flush=True)
    a=sym_arrays(sym)
    if a is None: continue
    o,h,l,c,v,dts,n,atr,atr_pct,elig,rsi,dd10,idx=a
    dv20=pd.Series(c*v).rolling(20).mean().to_numpy()
    nxo=np.full(n,np.nan); nxo[:n-1]=o[1:]
    nonbull=~np.array([isbull(x) for x in dts])
    fi=[]; rows=[]
    for r in g.itertuples(index=False):
        i=idx.get(r.date)
        if i is not None: fi.append(i); rows.append(r)
    if not fi: continue
    fi=np.array(fi)
    covered=np.array([not np.isnan(r.atm_iv) for r in rows])
    fear=np.array([((not np.isnan(r.iv_pctile) and r.iv_pctile>IVP_Q67) or
                    (not np.isnan(r.skew_25d) and r.skew_25d>SK_Q67)) for r in rows])
    deep_d=np.array([FD.get((sym,r.date),(np.nan,np.nan))[1]>d67 for r in rows])
    deep_r=np.array([FD.get((sym,r.date),(np.nan,np.nan))[0]<=r33 for r in rows])
    zb=np.array([("z_na" if np.isnan(z) else ("z_low" if z<ZMED else "z_high"))
                 for z in (z_at(sym,r.date) for r in rows)])
    def mk(sel):
        m=np.zeros(n,bool); m[fi[sel]]=True; return m
    CELLS={
        "deepos":mk(np.ones(len(fi),bool)),
        "deepd_fear":mk(deep_d&covered&fear),"deepd_nofear":mk(deep_d&covered&~fear),
        "deepd_nocov":mk(deep_d&~covered),
        "deepr_fear":mk(deep_r&covered&fear),"deepr_nofear":mk(deep_r&covered&~fear),
        "Df_dropfear":mk(~(deep_d&covered&fear)),
    }
    for zk in ("z_low","z_high","z_na"):
        CELLS[f"deepd_fear_{zk}"]=mk(deep_d&covered&fear&(zb==zk))
        CELLS[f"deepd_nofear_{zk}"]=mk(deep_d&covered&~fear&(zb==zk))
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
                if reg=="nonbull" and cn in ("deepos","deepd_fear","deepd_nofear","Df_dropfear"):
                    for Y in np.unique(np.array([dts[j][:4] for j in ci])):
                        yi=ci[np.array([dts[j][:4]==Y for j in ci])]
                        if len(yi)>=3:
                            uy=np.zeros(n); uy[yi]=res[yi]-bmean; bumpNW((cn,reg,Y),uy,len(yi))

def stNW(k,minf=20):
    a=NWd.get(k)
    if a is None or a[1]<minf: return None
    L=N-1; W=make_w(L); S,M=a[0],a[1]; G=a[2:2+1+L]; varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def fR(x): return f"{x[0]:+.3f}R t{x[1]:+.1f} n{x[2]}" if x else "(thin)"

for reg in ("nonbull","all"):
    base=stNW(("deepos",reg)); bv=base[0] if base else None; bn=base[2] if base else 1
    print(f"\n######## DEEP-TAIL FEAR CELL (S4, fires {START}+) — regime={reg}  [base {fR(base)}] ########")
    f_=stNW((f"deepd_fear",reg)); nf=stNW((f"deepd_nofear",reg))
    gap=f"{f_[0]-nf[0]:+.3f}" if (f_ and nf) else "--"
    print(f"   DD10-deep:  fear {fR(f_)} | nofear {fR(nf)} | GAP {gap} | nocov {fR(stNW(('deepd_nocov',reg)))}")
    f2=stNW((f"deepr_fear",reg)); nf2=stNW((f"deepr_nofear",reg))
    gap2=f"{f2[0]-nf2[0]:+.3f}" if (f2 and nf2) else "--"
    print(f"   RSI-deep:   fear {fR(f2)} | nofear {fR(nf2)} | GAP {gap2}")
    print(f"   Z'' control (DD10-deep):")
    for zk in ("z_low","z_high","z_na"):
        zf=stNW((f"deepd_fear_{zk}",reg),minf=12); zn=stNW((f"deepd_nofear_{zk}",reg),minf=12)
        zg=f"{zf[0]-zn[0]:+.3f}" if (zf and zn) else "  -- "
        print(f"      {zk:7s}: fear {fR(zf)} | nofear {fR(zn)} | GAP {zg}")
    ft=stNW(("Df_dropfear",reg)); lift=f"{ft[0]-bv:+.3f}" if (ft and bv is not None) else "--"
    keep=f"{100*ft[2]/bn:.0f}%" if ft else "--"
    print(f"   deployable Df_dropfear (skip deep&fear): {fR(ft)}  lift {lift}  vol {keep}")

print(f"\n######## YEAR-BY-YEAR (nonbull) ########")
print(f"  {'year':>6} | {'deepos':>18} | {'deepd_fear':>18} | {'deepd_nofear':>18} | {'GAP':>7} | {'Df_dropfear':>18}")
for y in [str(x) for x in range(2016,2027)]:
    f_=stNW(("deepd_fear","nonbull",y),minf=8); nf=stNW(("deepd_nofear","nonbull",y),minf=8)
    g=f"{f_[0]-nf[0]:+.3f}" if (f_ and nf) else "   --"
    print(f"  {y:>6} | {fR(stNW(('deepos','nonbull',y),minf=8)):>18} | {fR(f_):>18} | {fR(nf):>18} | {g:>7} | {fR(stNW(('Df_dropfear','nonbull',y),minf=8)):>18}")

print("\nread: deep-cell GAP consistently negative across years AND inside both Z buckets")
print("      => priced fear is a real, solvency-independent deep-knife discriminator;")
print("      GAP confined to z_low => it was re-measuring the Altman axis; year flips => VIX corpse.")
print("done.")
