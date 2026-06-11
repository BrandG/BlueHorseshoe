"""Depth-controlled test of the 48h news inverse gradient: does most-negative-news (sq_low)
beat the rest of the covered book WITHIN a fixed dislocation-depth bucket?

deepos_news_gauntlet (48h/Bearish variant) found the inverse of the 'justified collapse'
hypothesis: covered-fire sentiment terciles are monotonic toward negative news
(sq_low +0.345R t+3.6 > sq_mid +0.200 > sq_high +0.158 nonbull; +0.203/+0.100/+0.039 all).
Two explanations:
  (A) fresh negative news is a real CONDITIONER (capitulation/overreaction marker), OR
  (B) bad news just SELECTS deeper dislocations — and the edge is already monotonic in
      depth, so sentiment would add nothing new.
Test (pattern from adx_depth_control.py): stratify covered fires by DEPTH on each axis,
within each bucket compare sq_low vs rest (mean_s > q33). GAP = sq_low − rest.
  consistent +GAP across buckets -> real conditioner (A)
  gap vanishes once depth fixed  -> depth proxy (B)
Depth axes per fire:
  RSI   : rsi(14) level at fire (lower = deeper), tercile cuts from covered-fire dist
  AGE   : consecutive oversold bars (3-4 / 5-6 / 7+)
  DD10  : (max(close,10) − close)/ATR  drawdown depth in ATRs, tercile cuts
Window: fires >= 2022-03-01; news 48h lookback, REL_MIN 0.2; harness locked
(SEED=7 N=2000, S4 frictions, NW Bartlett L=9, lift vs same-symbol random baseline).
"""
import os, numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"; NEWS_START="2022-03-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; AGE=3; N=10; TP_ATR,SL_ATR=2.0,1.0
LOOKBACK_D=2; REL_MIN=0.2

news=pd.read_parquet("data/news_sentiment.parquet")
news=news.dropna(subset=["time_published","ticker_sentiment_score"])
news["rel"]=pd.to_numeric(news.relevance_score,errors="coerce").fillna(0.0)
news=news[news.rel>=REL_MIN]
news["day"]=news.time_published.str[:8]
NEWS={}
for sym,g in news.groupby("symbol"):
    g=g.sort_values("day")
    NEWS[sym]=(g.day.to_numpy(),g.ticker_sentiment_score.to_numpy(float),g.rel.to_numpy(float))
print(f"news table: {len(news)} relevant articles, {len(NEWS)} symbols",flush=True)

def news_feat(sym,d):
    t=NEWS.get(sym)
    if t is None: return 0,np.nan
    days,sc,rel=t
    hi=(d[:4]+d[5:7]+d[8:10])
    lo=(pd.Timestamp(d)-pd.Timedelta(days=LOOKBACK_D)).strftime("%Y%m%d")
    i0,i1=np.searchsorted(days,lo),np.searchsorted(days,hi,side="right")
    if i1<=i0: return 0,np.nan
    s,w=sc[i0:i1],rel[i0:i1]
    return int(i1-i0),float(np.average(s,weights=w))

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

# ---- pass 1: per-symbol cache + distributions over covered nonbull fires ----
FIRES={}; dist={"ms":[],"rsi":[],"age":[],"dd10":[]}
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
    dd10=(pd.Series(c).rolling(10).max().to_numpy()-c)/np.where(atr>0,atr,np.nan)
    inwin=dts>=NEWS_START
    fidx=np.where(deepos&elig&inwin)[0]
    feats={i:news_feat(sym,dts[i]) for i in fidx}
    FIRES[sym]=(o,h,l,c,v,dts,n,atr,atr_pct,vol20,elig,deepos,inwin,feats,rsi,age,dd10)
    for i in fidx:
        nr,ms=feats[i]
        if nr>0 and not isbull(dts[i]):
            dist["ms"].append(ms); dist["rsi"].append(rsi[i]); dist["age"].append(age[i]); dist["dd10"].append(dd10[i])
ms=np.array(dist["ms"])
q33=np.quantile(ms,1/3)
r33,r67=np.quantile(np.array(dist["rsi"]),[1/3,2/3])
d33,d67=np.quantile(np.array(dist["dd10"])[~np.isnan(dist["dd10"])],[1/3,2/3]) if np.isfinite(dist["dd10"]).any() else (1.5,3.0)
print(f"covered nonbull fires: {len(ms)} | sq_low cut mean_s<={q33:+.3f} | RSI cuts {r33:.1f}/{r67:.1f} | DD10 cuts {d33:.2f}/{d67:.2f}",flush=True)
print(f"  depth sanity — corr(mean_s, rsi)={np.corrcoef(ms,dist['rsi'])[0,1]:+.3f}  corr(mean_s, dd10)={np.corrcoef(ms[~np.isnan(dist['dd10'])],np.array(dist['dd10'])[~np.isnan(dist['dd10'])])[0,1]:+.3f}",flush=True)

AXES=[
    ("RSI",  lambda rsiv,agev,ddv: [("deep(<=%.1f)"%r33, rsiv<=r33),("mid",(rsiv>r33)&(rsiv<=r67)),("shallow",rsiv>r67)]),
    ("AGE",  lambda rsiv,agev,ddv: [("3-4",(agev>=3)&(agev<=4)),("5-6",(agev>=5)&(agev<=6)),("7+",agev>=7)]),
    ("DD10", lambda rsiv,agev,ddv: [("shallow(<=%.1f)"%d33, ddv<=d33),("mid",(ddv>d33)&(ddv<=d67)),("deep",ddv>d67)]),
]

# ---- pass 2: outcomes per (axis, bucket, sentiment-arm) ----
for ii,(sym,r) in enumerate(FIRES.items()):
    if ii%200==0: print(f"  P2 {ii}/{len(FIRES)}",flush=True)
    o,h,l,c,v,dts,n,atr,atr_pct,vol20,elig,deepos,inwin,feats,rsi,agev,dd10=r
    dv20=pd.Series(c*v).rolling(20).mean().to_numpy()
    nxo=np.full(n,np.nan); nxo[:n-1]=o[1:]
    nonbull=~np.array([isbull(x) for x in dts])
    nrel=np.zeros(n); means=np.full(n,np.nan)
    for i,(nr,msv) in feats.items(): nrel[i]=nr; means[i]=msv
    cov=deepos&inwin&(nrel>0)
    sqlow=cov&(means<=q33); rest=cov&(means>q33)
    rg,_=run(nxo,atr,o,h,l,c,True); ctier=np.array([dv_cost_bp(x) for x in np.nan_to_num(dv20)])/1e4/(SL_ATR*atr_pct)
    res=rg-ctier
    for reg in ("nonbull","all"):
        rmask=nonbull if reg=="nonbull" else np.ones(n,bool)
        ok=elig&~np.isnan(res)&rmask
        if ok.sum()<20: continue
        bmean=res[ok].mean()
        def bump(name,cm):
            fi=np.where(cm&ok)[0]
            if len(fi)>=1:
                u=np.zeros(n); u[fi]=res[fi]-bmean; bumpNW((name,reg),u,len(fi))
        bump("cov_all_sqlow",sqlow); bump("cov_all_rest",rest)
        for arm,cm in (("cov_all_sqlow",sqlow),("cov_all_rest",rest)):
            fi=np.where(cm&ok)[0]
            for Y in np.unique(np.array([dts[j][:4] for j in fi])) if len(fi) else []:
                yi=fi[np.array([dts[j][:4]==Y for j in fi])]
                if len(yi)>=3:
                    uy=np.zeros(n); uy[yi]=res[yi]-bmean; bumpNW((arm,reg,Y),uy,len(yi))
        for axis,mk in AXES:
            for lbl,bmask in mk(rsi,agev,dd10):
                bump(f"{axis}|{lbl}|sqlow",sqlow&bmask)
                bump(f"{axis}|{lbl}|rest", rest&bmask)

def stNW(k,minf=20):
    a=NWd.get(k)
    if a is None or a[1]<minf: return None
    L=N-1; W=make_w(L); S,M=a[0],a[1]; G=a[2:2+1+L]; varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def fR(x): return f"{x[0]:+.3f}R t{x[1]:+.1f} n{x[2]}" if x else "(thin)"

for reg in ("nonbull","all"):
    sl_=stNW((f"cov_all_sqlow",reg)); rs_=stNW((f"cov_all_rest",reg))
    gap=f"{sl_[0]-rs_[0]:+.3f}" if (sl_ and rs_) else "--"
    print(f"\n######## DEPTH CONTROL (48h, fires {NEWS_START}+, S4) — regime={reg} ########")
    print(f"   overall covered: sq_low {fR(sl_)} | rest {fR(rs_)} | GAP {gap}")
    for axis,_ in AXES:
        row=[]
        for lbl,_p in AXES[[a[0] for a in AXES].index(axis)][1](np.zeros(1),np.zeros(1),np.zeros(1)):
            s=stNW((f"{axis}|{lbl}|sqlow",reg)); rr=stNW((f"{axis}|{lbl}|rest",reg))
            g=f"{s[0]-rr[0]:+.3f}" if (s and rr) else "  -- "
            row.append(f"{lbl}: sq_low {fR(s)} vs rest {fR(rr)} GAP {g}")
        print(f"   {axis}:")
        for x in row: print(f"      {x}")
print(f"\n######## YEAR-BY-YEAR (gap audit — is the gap all one era?) ########")
for reg in ("nonbull","all"):
    print(f"  regime={reg}")
    print(f"  {'year':>6} | {'sq_low':>20} | {'rest':>20} | {'GAP':>7}")
    for y in ("2022","2023","2024","2025","2026"):
        s=stNW(("cov_all_sqlow",reg,y),minf=8); rr=stNW(("cov_all_rest",reg,y),minf=8)
        g=f"{s[0]-rr[0]:+.3f}" if (s and rr) else "   --"
        print(f"  {y:>6} | {fR(s):>20} | {fR(rr):>20} | {g:>7}")

print("\nread: consistent +GAP across depth buckets => sentiment is a real conditioner;")
print("      GAP ~0/erratic once depth fixed => bad news was a depth proxy.")
print("done.")
