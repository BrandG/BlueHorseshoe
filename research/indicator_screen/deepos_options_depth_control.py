"""Depth-controlled test of the two options-IV gauntlet survivors:

deepos_options_gauntlet found (nonbull S4, base +0.132R t7.8):
  (1) INVERSE IV gradient — aiv_low +0.183 > aiv_mid +0.105 > aiv_high +0.078; cross-sectional
      ivp_low +0.157 > ivp_mid +0.111 > ivp_high +0.098. Note the direction: this is OPPOSITE
      to the depth gradient (deeper dislocation mechanically carries HIGHER IV yet bounces
      BETTER), so IV is not trivially depth-re-measured — but only the depth control can say.
  (2) skew drop-cell — sk_high +0.061 t1.6 (vs sk_low/mid ~+0.150); heavy priced crash-insurance
      = impaired bounce. 2020-concentration risk (n699/2493 in 2020) noted; year-fragility is
      judged here and by the year table.
Test (pattern from deepos_news_depth_control.py): stratify covered fires by depth (RSI level,
oversold AGE, DD10 in ATRs), within each bucket compare arm vs rest. GAP consistent across
buckets -> real conditioner; GAP vanishes -> depth proxy. Arms:
  IV arm:   ivlow  = covered & iv_pctile <= q33   vs ivrest  (expect +GAP if real)
  SK arm:   skhigh = valid-skew & skew_25d > q67  vs skrest  (expect -GAP if real)
Fire list + features = data/options_iv_features.parquet (exact fire<->feature consistency);
duckdb supplies prices. Harness locked: next-open + gap-stop, S4 cost, NW Bartlett L=hold-1,
lift vs same-symbol eligible-day baseline. Cuts from covered NONBULL fires.
"""
import numpy as np, pandas as pd, talib, duckdb

START="2016-01-01"; OPT_END="2026-06-11"
N=10; TP_ATR,SL_ATR=2.0,1.0
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005

feat=pd.read_parquet("data/options_iv_features.parquet")
feat["date"]=feat.date.astype(str).str[:10]
feat=feat[feat.date<=OPT_END].copy()
nb=feat[feat.nonbull]
IVP_Q33=float(np.quantile(nb.iv_pctile.dropna(),1/3))
SK_Q67=float(np.quantile(nb.skew_25d.dropna(),2/3))
print(f"fires: {len(feat)} | covered: {feat.atm_iv.notna().sum()} | valid skew: {feat.skew_25d.notna().sum()}",flush=True)
print(f"cuts (nonbull): ivlow ivp<={IVP_Q33:.3f} | skhigh sk>{SK_Q67:+.3f}",flush=True)

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
    age=np.zeros(n,int); osr=rsi<30.0
    for i in range(1,n): age[i]=age[i-1]+1 if osr[i] else 0
    dd10=(pd.Series(c).rolling(10).max().to_numpy()-c)/np.where(atr>0,atr,np.nan)
    vol20=pd.Series(v).rolling(20).mean().to_numpy(); atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    return o,h,l,c,v,dts,n,atr,atr_pct,elig,rsi,age,dd10,{dt:i for i,dt in enumerate(dts)}

# ---- pass 1: depth distributions over covered nonbull fires ----
dist={"rsi":[],"age":[],"dd10":[],"ivp":[],"sk_rsi":[],"sk_dd":[],"sk":[]}
for ii,(sym,g) in enumerate(sorted(bysym.items())):
    if ii%200==0: print(f"  P1 {ii}/{len(bysym)}",flush=True)
    a=sym_arrays(sym)
    if a is None: continue
    rsi,age,dd10,idx=a[10],a[11],a[12],a[13]
    for r in g.itertuples(index=False):
        i=idx.get(r.date)
        if i is None or not r.nonbull: continue
        if not np.isnan(r.atm_iv):
            dist["rsi"].append(rsi[i]); dist["age"].append(age[i]); dist["dd10"].append(dd10[i]); dist["ivp"].append(r.iv_pctile)
        if not np.isnan(r.skew_25d):
            dist["sk_rsi"].append(rsi[i]); dist["sk_dd"].append(dd10[i]); dist["sk"].append(r.skew_25d)
rsiv=np.array(dist["rsi"]); ddv=np.array(dist["dd10"]); ivpv=np.array(dist["ivp"])
skv_=np.array(dist["sk"]); skr=np.array(dist["sk_rsi"]); skd=np.array(dist["sk_dd"])
r33,r67=np.quantile(rsiv,[1/3,2/3])
ddok=~np.isnan(ddv); d33,d67=np.quantile(ddv[ddok],[1/3,2/3])
print(f"covered nonbull fires: {len(rsiv)} | RSI cuts {r33:.1f}/{r67:.1f} | DD10 cuts {d33:.2f}/{d67:.2f}",flush=True)
ivok=~np.isnan(ivpv)
print(f"  depth sanity — corr(ivp,rsi)={np.corrcoef(ivpv[ivok&~np.isnan(rsiv)],rsiv[ivok&~np.isnan(rsiv)])[0,1]:+.3f}"
      f"  corr(ivp,dd10)={np.corrcoef(ivpv[ivok&ddok],ddv[ivok&ddok])[0,1]:+.3f}",flush=True)
skok=~np.isnan(skv_); skdok=skok&~np.isnan(skd)
print(f"  depth sanity — corr(sk,rsi)={np.corrcoef(skv_[skok&~np.isnan(skr)],skr[skok&~np.isnan(skr)])[0,1]:+.3f}"
      f"  corr(sk,dd10)={np.corrcoef(skv_[skdok],skd[skdok])[0,1]:+.3f}",flush=True)

AXES=[("RSI",[("deep",lambda R,A,D:R<=r33),("mid",lambda R,A,D:(R>r33)&(R<=r67)),("shallow",lambda R,A,D:R>r67)]),
      ("AGE",[("3-4",lambda R,A,D:(A>=3)&(A<=4)),("5-6",lambda R,A,D:(A>=5)&(A<=6)),("7+",lambda R,A,D:A>=7)]),
      ("DD10",[("shallow",lambda R,A,D:D<=d33),("mid",lambda R,A,D:(D>d33)&(D<=d67)),("deep",lambda R,A,D:D>d67)])]

# ---- pass 2: outcomes ----
for ii,(sym,g) in enumerate(sorted(bysym.items())):
    if ii%200==0: print(f"  P2 {ii}/{len(bysym)}",flush=True)
    a=sym_arrays(sym)
    if a is None: continue
    o,h,l,c,v,dts,n,atr,atr_pct,elig,rsi,age,dd10,idx=a
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
    aivok=~np.isnan(np.array([r.atm_iv for r in rows])); skok2=~np.isnan(sk)
    def mk(sel):
        m=np.zeros(n,bool); m[fi[sel]]=True; return m
    ARMS={"ivlow":mk(aivok&(ivp<=IVP_Q33)),"ivrest":mk(aivok&(ivp>IVP_Q33)),
          "skhigh":mk(skok2&(sk>SK_Q67)),"skrest":mk(skok2&(sk<=SK_Q67))}
    rg,_=run(nxo,atr,o,h,l,c,True); ctier=np.array([dv_cost_bp(x) for x in np.nan_to_num(dv20)])/1e4/(SL_ATR*atr_pct)
    res=rg-ctier
    for reg in ("nonbull","all"):
        rmask=nonbull if reg=="nonbull" else np.ones(n,bool)
        ok=elig&~np.isnan(res)&rmask
        if ok.sum()<20: continue
        bmean=res[ok].mean()
        def bump(name,cm):
            ci=np.where(cm&ok)[0]
            if len(ci)>=1:
                u=np.zeros(n); u[ci]=res[ci]-bmean; bumpNW((name,reg),u,len(ci))
            return ci
        for arm,cm in ARMS.items():
            ci=bump(arm,cm)
            for Y in (np.unique(np.array([dts[j][:4] for j in ci])) if len(ci) else []):
                yi=ci[np.array([dts[j][:4]==Y for j in ci])]
                if len(yi)>=3:
                    uy=np.zeros(n); uy[yi]=res[yi]-bmean; bumpNW((arm,reg,Y),uy,len(yi))
            for axis,buckets in AXES:
                for lbl,p in buckets:
                    bump(f"{axis}|{lbl}|{arm}",cm&mk(p(rsi[fi],age[fi],dd10[fi])))

def stNW(k,minf=20):
    a=NWd.get(k)
    if a is None or a[1]<minf: return None
    L=N-1; W=make_w(L); S,M=a[0],a[1]; G=a[2:2+1+L]; varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def fR(x): return f"{x[0]:+.3f}R t{x[1]:+.1f} n{x[2]}" if x else "(thin)"

for reg in ("nonbull","all"):
    print(f"\n######## DEPTH CONTROL (options, fires {START}+, S4) — regime={reg} ########")
    for arm,rest,sign in (("ivlow","ivrest","+"),("skhigh","skrest","-")):
        a_=stNW((arm,reg)); r_=stNW((rest,reg))
        gap=f"{a_[0]-r_[0]:+.3f}" if (a_ and r_) else "--"
        print(f"   overall: {arm} {fR(a_)} | {rest} {fR(r_)} | GAP {gap} (real if consistently {sign})")
        for axis,buckets in AXES:
            cells=[]
            for lbl,_p in buckets:
                s=stNW((f"{axis}|{lbl}|{arm}",reg)); rr=stNW((f"{axis}|{lbl}|{rest}",reg))
                g=f"{s[0]-rr[0]:+.3f}" if (s and rr) else "  -- "
                cells.append(f"{lbl} GAP {g} ({arm} {fR(s)} / {fR(rr)})")
            print(f"      {axis}: "+" | ".join(cells))

print(f"\n######## YEAR-BY-YEAR (nonbull, gap audit) ########")
print(f"  {'year':>6} | {'ivlow':>18} | {'ivrest':>18} | {'ivGAP':>7} | {'skhigh':>18} | {'skrest':>18} | {'skGAP':>7}")
for y in [str(x) for x in range(2016,2027)]:
    s1=stNW(("ivlow","nonbull",y),minf=8); r1=stNW(("ivrest","nonbull",y),minf=8)
    s2=stNW(("skhigh","nonbull",y),minf=8); r2=stNW(("skrest","nonbull",y),minf=8)
    g1=f"{s1[0]-r1[0]:+.3f}" if (s1 and r1) else "   --"
    g2=f"{s2[0]-r2[0]:+.3f}" if (s2 and r2) else "   --"
    print(f"  {y:>6} | {fR(s1):>18} | {fR(r1):>18} | {g1:>7} | {fR(s2):>18} | {fR(r2):>18} | {g2:>7}")

print("\nread: ivlow GAP consistently + across buckets => low priced fear is a real conditioner;")
print("      skhigh GAP consistently - across buckets => heavy skew is a real skip-cell;")
print("      gaps ~0/erratic once depth fixed => IV/skew were depth proxies.")
print("done.")
