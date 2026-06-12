"""Robustness pass on the deep-tail priced-fear cell (deepos_options_deeptail):

The cell (fear = ivp>q67 OR sk>q67, deep = DD10>q67) was chosen IN-SAMPLE after the depth
control pointed at it — sequential-conditioning risk. Three legs before any wiring:
  1. CUT SENSITIVITY: 3x3 grid fear_q x deep_q in {0.60, 2/3, 0.75}. A real effect degrades
     gracefully across the grid; a curve-fit artifact lives at one corner.
  2. COMPONENT SPLIT (at q67/q67): fear_ivp-only vs fear_sk-only vs both — which feature
     carries? Pure cells: both / ivp_only / sk_only vs neither.
  3. NEWS CONTROL (fires >= 2022-03-01, the AV news window): the 48h news arm
     ([[project_deepos_news_condition]], live annotation cut mean_s<=+0.030, 2d lookback,
     REL_MIN 0.2) is the other "priced fear" axis. Composition P(news arm | fear) and the
     fear GAP WITHIN news arms (nocov / sq_low / rest). If the GAP only exists inside one
     news arm, options fear is news re-measured; if it holds across arms, it's additive.
     (Signs differ a priori: negative NEWS = best bounce, option FEAR = worst bounce.)
Harness locked: next-open + gap-stop, S4 cost, NW Bartlett L=hold-1, same-symbol baseline;
fires/features = data/options_iv_features.parquet; nonbull focus (the live book).
"""
import numpy as np, pandas as pd, talib, duckdb

START="2016-01-01"; OPT_END="2026-06-11"; NEWS_START="2022-03-01"
N=10; TP_ATR,SL_ATR=2.0,1.0
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
QS=(0.60,2/3,0.75); QLBL={0.60:"q60",2/3:"q67",0.75:"q75"}
NEWS_LOOKBACK_D=2; REL_MIN=0.2; SQLOW_CUT=0.030

feat=pd.read_parquet("data/options_iv_features.parquet")
feat["date"]=feat.date.astype(str).str[:10]
feat=feat[feat.date<=OPT_END].copy()
nb=feat[feat.nonbull]
IVP_C={q:float(np.quantile(nb.iv_pctile.dropna(),q)) for q in QS}
SK_C={q:float(np.quantile(nb.skew_25d.dropna(),q)) for q in QS}
print("fear cuts:",{QLBL[q]:(round(IVP_C[q],3),round(SK_C[q],3)) for q in QS},flush=True)

# ---- 48h news features (live-annotation-faithful) ----
news=pd.read_parquet("data/news_sentiment.parquet")
news=news.dropna(subset=["time_published","ticker_sentiment_score"])
news["rel"]=pd.to_numeric(news.relevance_score,errors="coerce").fillna(0.0)
news=news[news.rel>=REL_MIN]
news["day"]=news.time_published.str[:8]
NEWS={}
for sym,g in news.groupby("symbol"):
    g=g.sort_values("day")
    NEWS[sym]=(g.day.to_numpy(),g.ticker_sentiment_score.to_numpy(float),g.rel.to_numpy(float))
def news_arm(sym,d):
    """'nocov' | 'sqlow' | 'rest' for fires >= NEWS_START; None outside window."""
    if d<NEWS_START: return None
    t=NEWS.get(sym)
    if t is None: return "nocov"
    days,sc,rel=t
    hi=d[:4]+d[5:7]+d[8:10]
    lo=(pd.Timestamp(d)-pd.Timedelta(days=NEWS_LOOKBACK_D)).strftime("%Y%m%d")
    i0,i1=np.searchsorted(days,lo),np.searchsorted(days,hi,side="right")
    if i1<=i0: return "nocov"
    ms=float(np.average(sc[i0:i1],weights=rel[i0:i1]))
    return "sqlow" if ms<=SQLOW_CUT else "rest"

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
    atr=talib.ATR(h,l,c,14)
    dd10=(pd.Series(c).rolling(10).max().to_numpy()-c)/np.where(atr>0,atr,np.nan)
    vol20=pd.Series(v).rolling(20).mean().to_numpy(); atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    return o,h,l,c,v,dts,n,atr,atr_pct,elig,dd10,{dt:i for i,dt in enumerate(dts)}

# ---- pass 1: dd10 at fires -> deep cuts; news composition ----
FD={}; dist_d=[]
for ii,(sym,g) in enumerate(sorted(bysym.items())):
    if ii%200==0: print(f"  P1 {ii}/{len(bysym)}",flush=True)
    a=sym_arrays(sym)
    if a is None: continue
    dd10,idx=a[10],a[11]
    for r in g.itertuples(index=False):
        i=idx.get(r.date)
        if i is None: continue
        FD[(r.symbol if hasattr(r,'symbol') else sym, r.date)]=float(dd10[i])
        if r.nonbull and not np.isnan(r.atm_iv): dist_d.append(dd10[i])
dd=np.array(dist_d); dd=dd[~np.isnan(dd)]
DD_C={q:float(np.quantile(dd,q)) for q in QS}
print("deep cuts (DD10):",{QLBL[q]:round(DD_C[q],2) for q in QS},flush=True)

# composition + corr in the news window (deep=q67, fear=q67, covered nonbull)
comp={("fear",a):0 for a in ("nocov","sqlow","rest")}|{("nofear",a):0 for a in ("nocov","sqlow","rest")}
msf=[]; flf=[]
for r in nb.itertuples(index=False):
    d10=FD.get((r.symbol,r.date),np.nan)
    if np.isnan(r.atm_iv) or not (d10>DD_C[2/3]) or r.date<NEWS_START: continue
    fear=(not np.isnan(r.iv_pctile) and r.iv_pctile>IVP_C[2/3]) or (not np.isnan(r.skew_25d) and r.skew_25d>SK_C[2/3])
    arm=news_arm(r.symbol,r.date)
    comp[("fear" if fear else "nofear",arm)]+=1
nf=sum(v for (f,_),v in comp.items() if f=="fear"); nn=sum(v for (f,_),v in comp.items() if f=="nofear")
if nf and nn:
    print("news-window deep cell composition: "
          +" | ".join(f"P({a}|fear)={100*comp[('fear',a)]/nf:.0f}% vs P({a}|nofear)={100*comp[('nofear',a)]/nn:.0f}%"
                      for a in ("nocov","sqlow","rest"))+f"  (n fear {nf} / nofear {nn})",flush=True)

# ---- pass 2: outcomes ----
for ii,(sym,g) in enumerate(sorted(bysym.items())):
    if ii%200==0: print(f"  P2 {ii}/{len(bysym)}",flush=True)
    a=sym_arrays(sym)
    if a is None: continue
    o,h,l,c,v,dts,n,atr,atr_pct,elig,dd10,idx=a
    dv20=pd.Series(c*v).rolling(20).mean().to_numpy()
    nxo=np.full(n,np.nan); nxo[:n-1]=o[1:]
    nonbull=~np.array([isbull(x) for x in dts])
    fi=[]; rows=[]
    for r in g.itertuples(index=False):
        i=idx.get(r.date)
        if i is not None: fi.append(i); rows.append(r)
    if not fi: continue
    fi=np.array(fi)
    ivp=np.array([r.iv_pctile for r in rows]); sk=np.array([r.skew_25d for r in rows])
    covered=np.array([not np.isnan(r.atm_iv) for r in rows])
    d10=np.array([FD.get((sym,r.date),np.nan) for r in rows])
    arms=np.array([news_arm(sym,r.date) or "pre" for r in rows])
    def mk(sel):
        m=np.zeros(n,bool); m[fi[sel]]=True; return m
    ivp_f={q:(~np.isnan(ivp))&(ivp>IVP_C[q]) for q in QS}
    sk_f={q:(~np.isnan(sk))&(sk>SK_C[q]) for q in QS}
    CELLS={"deepos":mk(np.ones(len(fi),bool))}
    for fq in QS:
        fear=ivp_f[fq]|sk_f[fq]
        for dq in QS:
            deep=covered&(d10>DD_C[dq])
            CELLS[f"g_{QLBL[fq]}_{QLBL[dq]}_fear"]=mk(deep&fear)
            CELLS[f"g_{QLBL[fq]}_{QLBL[dq]}_nofear"]=mk(deep&~fear)
    deep67=covered&(d10>DD_C[2/3]); f_ivp=ivp_f[2/3]; f_sk=sk_f[2/3]
    CELLS|={"c_ivp_fear":mk(deep67&f_ivp),"c_ivp_nofear":mk(deep67&~f_ivp),
            "c_sk_fear":mk(deep67&f_sk),"c_sk_nofear":mk(deep67&(~np.isnan(sk))&~f_sk),
            "c_both":mk(deep67&f_ivp&f_sk),"c_ivponly":mk(deep67&f_ivp&~f_sk),
            "c_skonly":mk(deep67&f_sk&~f_ivp),"c_neither":mk(deep67&~f_ivp&~f_sk)}
    fear67=f_ivp|f_sk; inwin=arms!="pre"
    CELLS|={f"nw_{a}_{f}":mk(deep67&inwin&(arms==a)&(fear67 if f=="fear" else ~fear67))
            for a in ("nocov","sqlow","rest") for f in ("fear","nofear")}
    CELLS|={"nw_all_fear":mk(deep67&inwin&fear67),"nw_all_nofear":mk(deep67&inwin&~fear67)}
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

def stNW(k,minf=12):
    a=NWd.get(k)
    if a is None or a[1]<minf: return None
    L=N-1; W=make_w(L); S,M=a[0],a[1]; G=a[2:2+1+L]; varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def fR(x): return f"{x[0]:+.3f}R t{x[1]:+.1f} n{x[2]}" if x else "(thin)"
def gap(a,b):
    return f"{a[0]-b[0]:+.3f}" if (a and b) else "  -- "

for reg in ("nonbull","all"):
    print(f"\n######## ROBUSTNESS (S4, fires {START}+) — regime={reg}  [base {fR(stNW(('deepos',reg)))}] ########")
    print("   1) CUT-SENSITIVITY GRID — GAP fear−nofear (n_fear):")
    print(f"      {'':>10} | "+" | ".join(f"deep {QLBL[dq]:>14}" for dq in QS))
    for fq in QS:
        row=[]
        for dq in QS:
            f_=stNW((f"g_{QLBL[fq]}_{QLBL[dq]}_fear",reg)); n_=stNW((f"g_{QLBL[fq]}_{QLBL[dq]}_nofear",reg))
            row.append(f"{gap(f_,n_):>7} (n{f_[2] if f_ else 0:>5})")
        print(f"      fear {QLBL[fq]:>4} | "+" | ".join(row))
    print("   2) COMPONENT SPLIT (deep q67):")
    print(f"      ivp-arm:  fear {fR(stNW((f'c_ivp_fear',reg)))} | nofear {fR(stNW((f'c_ivp_nofear',reg)))} | GAP {gap(stNW((f'c_ivp_fear',reg)),stNW((f'c_ivp_nofear',reg)))}")
    print(f"      sk-arm:   fear {fR(stNW((f'c_sk_fear',reg)))} | nofear {fR(stNW((f'c_sk_nofear',reg)))} | GAP {gap(stNW((f'c_sk_fear',reg)),stNW((f'c_sk_nofear',reg)))}")
    print(f"      pure:     both {fR(stNW((f'c_both',reg)))} | ivp_only {fR(stNW((f'c_ivponly',reg)))} | sk_only {fR(stNW((f'c_skonly',reg)))} | neither {fR(stNW((f'c_neither',reg)))}")
    print(f"   3) NEWS CONTROL (fires {NEWS_START}+, deep q67, fear q67):")
    aw=stNW((f"nw_all_fear",reg)); nw=stNW((f"nw_all_nofear",reg))
    print(f"      window overall: fear {fR(aw)} | nofear {fR(nw)} | GAP {gap(aw,nw)}")
    for a in ("nocov","sqlow","rest"):
        f_=stNW((f"nw_{a}_fear",reg)); n_=stNW((f"nw_{a}_nofear",reg))
        print(f"      within {a:6s}: fear {fR(f_)} | nofear {fR(n_)} | GAP {gap(f_,n_)}")

print("\nread: 1) GAP negative across the grid (graceful decay) => not a cut artifact;")
print("      2) both components carry (esp. pure cells ordered both<ivp_only/sk_only<neither) => composite justified;")
print("      3) GAP holds within news arms => additive to news; confined to one arm => redundant.")
print("done.")
