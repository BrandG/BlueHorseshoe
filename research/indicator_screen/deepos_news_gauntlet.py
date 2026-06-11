"""NEWS/SENTIMENT conditioning on DeepOS — is "oversold + heavy negative news" a justified
collapse (skip) vs "oversold + benign/no news" a clean dislocation (take)?

Axis from the conditioning campaign (project_deepos_conditioning_rollup): every price-derived
conditioner was NULL or dislocation-redundant; news is the first genuinely exogenous axis.
Window: fires >= 2022-03-01 only (AV NEWS_SENTIMENT archive floor). The bare sleeve is ~flat
in this window (2022 -0.003R / 2023 -0.219R / 2025 -0.122R nonbull S4), so a real discriminator
shows up as SEPARATION around zero — exactly what we want from a skip-filter.

News features per fire (symbol, signal date d), point-in-time = published <= d 23:59 ET
(knowable before next-open entry), 7-day lookback, relevance >= 0.2 to drop passing mentions:
  n_rel       articles in window
  mean_s      relevance-weighted mean ticker_sentiment_score
COVERAGE CONFOUND: AV 2022 archive is thin (large-caps dominate); "no coverage" partly means
"AV didn't archive it", and coverage correlates with size. So cells are reported with median
$vol, and the covered-only tercile split is the cleaner read than covered-vs-nocov.

Cells:
  nocov                n_rel==0
  cov_benign           n_rel>=1 & mean_s > -0.15   (AV's Neutral floor)
  cov_neg              n_rel>=1 & mean_s <= -0.15  (hypothesis: justified collapse -> worse R)
  cov_heavyneg         n_rel>=3 & mean_s <= -0.15  (high-confidence toxic cell)
  sq_low/sq_mid/sq_high  terciles of mean_s among covered fires (data-driven cuts)
  Df_dropneg           deployable: deepos & ~cov_neg
Harness = locked: SEED=7 N=2000; rsi<30 & age>=3; next-open + gap-stop; S4 tiered cost;
keep all firings + NW (Bartlett L=hold-1); lift vs same-symbol random baseline.
"""
import os, numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"; NEWS_START="2022-03-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; AGE=3; N=10; TP_ATR,SL_ATR=2.0,1.0
LOOKBACK_D=int(os.environ.get("NEWS_LOOKBACK_D","7")); REL_MIN=0.2
NEG_THR=float(os.environ.get("NEWS_NEG_THR","-0.15")); HEAVY_N=3
print(f"params: lookback={LOOKBACK_D}d neg_thr={NEG_THR}",flush=True)

# ---- news features ----
news=pd.read_parquet("data/news_sentiment.parquet")
news=news.dropna(subset=["time_published","ticker_sentiment_score"])
news["rel"]=pd.to_numeric(news.relevance_score,errors="coerce").fillna(0.0)
news=news[news.rel>=REL_MIN]
news["day"]=news.time_published.str[:8]   # YYYYMMDD
NEWS={}
for sym,g in news.groupby("symbol"):
    g=g.sort_values("day")
    NEWS[sym]=(g.day.to_numpy(),g.ticker_sentiment_score.to_numpy(float),g.rel.to_numpy(float))
print(f"news table: {len(news)} relevant articles, {len(NEWS)} symbols",flush=True)

def news_feat(sym,d):
    """(n_rel, mean_s) for window [d-7d, d] inclusive; d is YYYY-MM-DD."""
    t=NEWS.get(sym)
    if t is None: return 0,np.nan
    days,sc,rel=t
    hi=(d[:4]+d[5:7]+d[8:10])
    lo=(pd.Timestamp(d)-pd.Timedelta(days=LOOKBACK_D)).strftime("%Y%m%d")
    i0,i1=np.searchsorted(days,lo),np.searchsorted(days,hi,side="right")
    if i1<=i0: return 0,np.nan
    s,w=sc[i0:i1],rel[i0:i1]
    return int(i1-i0),float(np.average(s,weights=w))

# ---- harness (locked) ----
con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg_map.get(str(d)[:10],False)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300 ORDER BY symbol",[START]).df().symbol.tolist()
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")
syms=[s for s in syms if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=sorted(rng.choice(syms,N_SYMBOLS,replace=False))

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
DVC=defaultdict(list)   # per-cell $vol20 medians for the coverage confound
MS=[]                   # per-fire mean_s for tercile cuts (pass over fires first)

# ---- pass 1: collect mean_s distribution over nonbull fires in window ----
FIRES={}  # sym -> (indices, feats) cache for pass 2
for ii,sym in enumerate(syms):
    if ii%200==0: print(f"  P1 {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14)
    vol20=pd.Series(v).rolling(20).mean().to_numpy(); atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    osr=rsi<OS; age=np.zeros(n,int)
    for i in range(1,n): age[i]=age[i-1]+1 if osr[i] else 0
    deepos=osr&(age>=AGE)
    inwin=dts>=NEWS_START
    fidx=np.where(deepos&elig&inwin)[0]
    feats={i:news_feat(sym,dts[i]) for i in fidx}
    FIRES[sym]=(d,o,h,l,c,v,dts,n,atr,atr_pct,vol20,elig,deepos,inwin,feats)
    for i in fidx:
        if not isbull(dts[i]):
            nr,ms=feats[i]
            if nr>0: MS.append(ms)
MS=np.array(MS)
q33,q67=np.quantile(MS,[1/3,2/3]) if len(MS) else (0.0,0.0)
print(f"covered nonbull fires: {len(MS)} | mean_s q33={q33:+.3f} q67={q67:+.3f} median={np.median(MS):+.3f}",flush=True)

# ---- pass 2: outcomes ----
YEARCELLS=("deepos","nocov","cov_benign","cov_neg","Df_dropneg")
for ii,(sym,r) in enumerate(FIRES.items()):
    if ii%200==0: print(f"  P2 {ii}/{len(FIRES)}",flush=True)
    d,o,h,l,c,v,dts,n,atr,atr_pct,vol20,elig,deepos,inwin,feats=r
    dv20=pd.Series(c*v).rolling(20).mean().to_numpy()
    nxo=np.full(n,np.nan); nxo[:n-1]=o[1:]
    nonbull=~np.array([isbull(x) for x in dts])
    nrel=np.zeros(n); means=np.full(n,np.nan)
    for i,(nr,ms) in feats.items(): nrel[i]=nr; means[i]=ms
    cov=nrel>0
    CELLS={
        "deepos":deepos&inwin,
        "nocov":deepos&inwin&~cov,
        "cov_benign":deepos&inwin&cov&(means>NEG_THR),
        "cov_neg":deepos&inwin&cov&(means<=NEG_THR),
        "cov_heavyneg":deepos&inwin&cov&(means<=NEG_THR)&(nrel>=HEAVY_N),
        "sq_low":deepos&inwin&cov&(means<=q33),
        "sq_mid":deepos&inwin&cov&(means>q33)&(means<=q67),
        "sq_high":deepos&inwin&cov&(means>q67),
        "Df_dropneg":deepos&inwin&~(cov&(means<=NEG_THR)),
    }
    rg,_=run(nxo,atr,o,h,l,c,True); ctier=np.array([dv_cost_bp(x) for x in np.nan_to_num(dv20)])/1e4/(SL_ATR*atr_pct)
    res=rg-ctier
    for reg in ("nonbull","all"):
        rmask=nonbull if reg=="nonbull" else np.ones(n,bool)
        ok=elig&~np.isnan(res)&rmask
        if ok.sum()<20: continue
        bmean=res[ok].mean()
        for cn,cm in CELLS.items():
            fi=np.where(cm&ok)[0]
            if len(fi)>=1:
                u=np.zeros(n); u[fi]=res[fi]-bmean; bumpNW((cn,reg),u,len(fi))
                if reg=="nonbull":
                    DVC[cn].extend(dv20[fi][~np.isnan(dv20[fi])].tolist())
                    if cn in YEARCELLS:
                        for Y in np.unique(np.array([dts[j][:4] for j in fi])):
                            yi=fi[np.array([dts[j][:4]==Y for j in fi])]
                            if len(yi)>=5:
                                uy=np.zeros(n); uy[yi]=res[yi]-bmean; bumpNW((cn,reg,Y),uy,len(yi))

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
    base=stNW(("deepos",reg)); bv=base[0] if base else None; bn=base[2] if base else 1
    print(f"\n############ NEWS SPLIT (S4, fires {NEWS_START}+) — regime={reg}  [base {fR(base)}] ############")
    print(f"   coverage: nocov {fR(stNW(('nocov',reg)))} | cov_benign {fR(stNW(('cov_benign',reg)))} | cov_neg {fR(stNW(('cov_neg',reg)))}")
    print(f"   toxic cell cov_heavyneg(n>={HEAVY_N}): {fR(stNW(('cov_heavyneg',reg),minf=15))}")
    print(f"   covered terciles: sq_low {fR(stNW(('sq_low',reg)))} | sq_mid {fR(stNW(('sq_mid',reg)))} | sq_high {fR(stNW(('sq_high',reg)))}")
    ft=stNW(("Df_dropneg",reg)); lift=f"{ft[0]-bv:+.3f}" if (ft and bv is not None) else "--"; keep=f"{100*ft[2]/bn:.0f}%" if ft else "--"
    print(f"   deployable Df_dropneg (skip covered-negative): {fR(ft)}  lift {lift}  vol {keep}")
print(f"\n   coverage-confound check (median $vol20, nonbull): nocov {mdv('nocov')} | cov_benign {mdv('cov_benign')} | cov_neg {mdv('cov_neg')}")

print(f"\n############ YEAR-BY-YEAR (nonbull S4) ############")
print(f"  {'year':>6} | {'deepos':>14} | {'nocov':>13} | {'cov_benign':>13} | {'cov_neg':>13} | {'Df_dropneg':>14}")
for y in ("2022","2023","2024","2025","2026"):
    g=lambda k:(lambda s:f"{s[0]:+.3f} n{s[2]}" if s else "(thin)")(stNW((k,"nonbull",y),minf=8))
    print(f"  {y:>6} | {g('deepos'):>14} | {g('nocov'):>13} | {g('cov_benign'):>13} | {g('cov_neg'):>13} | {g('Df_dropneg'):>14}")
print("\ndone.")
