"""KNIFE RE-AUDIT: do the close-to-close 'knife' signals soften under faithful NEXT-OPEN entry?

[[project_deepos_volume_conditioner]] gauntlet found the gap-down 'knife' was a CLOSE-ENTRY ARTIFACT:
close-entry charges the trade for the overnight gap (−0.66R); next-open entry buys AFTER the gap, so the
forward bounce is neutral. HYPOTHESIS: the other fast/sharp 'knives' from the broad NW sweep
([[project_deoverlap_signflip_newey_west]]) — cci_deep, rsi_deep, bb_below, stoch_os, cci_os, gap_down —
fire on sharp down-days that often gap, so their negativity is partly the same artifact and should SOFTEN
under next-open; while the SLOW-dislocation ALPHA anchors (rsi_oversold, below_cloud, below_sma200) and the
TREND controls (above_sma200, donchian_high — not gap-driven) should be ~stable.

Three entry models, each demeaned vs same-regime/same-model random (full-pop NW, Bartlett L=hold-1):
  CLOSE   enter close[t], stop fills at level      (reproduces the broad-sweep knife numbers)
  NEXTOPN enter open[t+1], stop fills at level     (isolates the ENTRY-SHIFT)
  +GAPST  enter open[t+1], stop fills at open on gap-through (full faithful)
Plus gap% = fraction of each signal's fires that gap down >=3% into the entry morning (the mechanism link).
Read: big positive Δ(NEXTOPN−CLOSE) on a knife with high gap% = artifact confirmed. Sample PINNED.
"""
import numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005; DISP=26
N=10; TP_ATR,SL_ATR=2.0,1.0
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")

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
print(f"{len(syms)} syms (PINNED); knife re-audit close vs next-open, hold{N} {TP_ATR:.0f}:{SL_ATR:.0f}",flush=True)

rmx=lambda x,w: pd.Series(x).rolling(w).max().to_numpy(); rmn=lambda x,w: pd.Series(x).rolling(w).min().to_numpy()
def shift(a,k):
    out=np.full(len(a),np.nan)
    if k<len(a): out[k:]=a[:-k]
    return out
def run(entry,atr,o,h,l,c,gap):
    n=len(c); tp=entry+TP_ATR*atr; sl=entry-SL_ATR*atr; Rp=SL_ATR*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan)
    valid=(np.arange(n)<(n-N-1))&(atr>0)&~np.isnan(atr)&~np.isnan(entry)
    for k in range(1,N+1):
        hk=np.full(n,np.nan); hk[:n-k]=h[k:]; lk=np.full(n,np.nan); lk[:n-k]=l[k:]
        okp=np.full(n,np.nan); okp[:n-k]=o[k:]
        tph=hk>=tp; slh=lk<=sl
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        sfill=np.where(okp<=sl,okp,sl) if gap else sl
        res[loss]=((sfill[loss] if gap else sl[loss])-entry[loss])/Rp[loss]
        res[wn]=TP_ATR/SL_ATR; resolved|=(loss|wn)
    exitc=np.full(n,np.nan); exitc[:n-N]=c[N:][:n-N]
    to=valid&~resolved; res[to]=(exitc[to]-entry[to])/Rp[to]
    return res,valid
NWd={}
def make_w(L): return np.array([1.0-j/(L+1) for j in range(L+1)])
def bumpNW(k,u,m,L):
    a=NWd.setdefault(k,np.zeros(3+30)); a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    for j in range(1,L+1): a[2+j]+=float(u[:-j]@u[j:])
gapc=defaultdict(lambda:[0,0])   # (signal,regime) -> [gapped_fires, total_fires]

SCN=["CLOSE","NEXTOPN","+GAPST"]
GROUPS=[
 ("ALPHA anchors (slow, expect stable)", ["rsi_oversold","below_cloud","below_sma200"]),
 ("KNIVES (gap-correlated suspects)",    ["gap_down","cci_deep","rsi_deep","bb_below","stoch_os","cci_os"]),
 ("TREND controls (not gap-driven)",     ["above_sma200","donchian_high"]),
 ("RANDOM",                              ["RANDOM"]),
]
ALL=[s for _,ss in GROUPS for s in ss]

for ii,sym in enumerate(syms):
    if ii%300==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    nonbull=~np.array([isbull(x) for x in dts])
    cci=talib.CCI(h,l,c,14); slowk,_=talib.STOCH(h,l,c); bbu,bbm,bbl=talib.BBANDS(c,20,2,2)
    sma200=talib.SMA(c,200); donhi=shift(rmx(h,20),1); prevc=shift(c,1)
    sA=np.full(n,np.nan); sB=np.full(n,np.nan)
    tk=(rmx(h,9)+rmn(l,9))/2; kj=(rmx(h,26)+rmn(l,26))/2
    sA[DISP:]=((tk+kj)/2)[:n-DISP]; sB[DISP:]=((rmx(h,52)+rmn(l,52))/2)[:n-DISP]
    bot=np.fmin(sA,sB); os=rsi<30
    SIG={"rsi_oversold":os,"below_cloud":c<bot,"below_sma200":c<sma200,
         "gap_down":o<prevc*0.97,"cci_deep":cci<-200,"rsi_deep":rsi<20,"bb_below":c<bbl,
         "stoch_os":slowk<20,"cci_os":cci<-100,
         "above_sma200":c>sma200,"donchian_high":c>=donhi,"RANDOM":np.ones(n,bool)}
    nxo=np.full(n,np.nan); nxo[:n-1]=o[1:]
    entry_gap=(nxo/np.where(c>0,c,np.nan))-1.0
    RES={"CLOSE":run(c,atr,o,h,l,c,False),"NEXTOPN":run(nxo,atr,o,h,l,c,False),"+GAPST":run(nxo,atr,o,h,l,c,True)}
    L=N-1
    for reg in ("nonbull","all"):
        rmask=nonbull if reg=="nonbull" else np.ones(n,bool)
        for scn in SCN:
            res,val=RES[scn]; ok=elig&val&~np.isnan(res)&rmask
            if ok.sum()<20: continue
            bmean=res[ok].mean()
            for s in ALL:
                fidx=np.where(np.asarray(SIG[s],bool)&ok)[0]
                if len(fidx)>=5:
                    u=np.zeros(n); u[fidx]=res[fidx]-bmean; bumpNW((s,reg,scn),u,len(fidx),L)
                    if scn=="CLOSE":   # gap-overlap once (entry-transition gap), on the close-eligible set
                        g=gapc[(s,reg)]; g[1]+=len(fidx); g[0]+=int((entry_gap[fidx]<=-0.03).sum())

def stNW(k,minfire=50):
    a=NWd.get(k)
    if a is None or a[1]<minfire: return None
    L=N-1; W=make_w(L); S,M=a[0],a[1]; G=a[2:2+1+L]; varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def f(s): return f"{s[0]:+.3f} t{s[1]:+.1f}" if s else "(thin)"

for reg in ("nonbull","all"):
    print(f"\n################ KNIFE RE-AUDIT — regime={reg}  (NW lift vs random, full-pop) ################")
    print(f"  {'signal':14} {'CLOSE':>13} {'NEXTOPN':>13} {'+GAPST':>13} | {'Δ(NO-CL)':>9} {'gap%':>5}")
    for gname,sigs in GROUPS:
        print(f"   -- {gname} --")
        for s in sigs:
            cl=stNW((s,reg,"CLOSE")); no=stNW((s,reg,"NEXTOPN")); gs=stNW((s,reg,"+GAPST"))
            dlt=f"{no[0]-cl[0]:+.3f}" if (cl and no) else "--"
            g=gapc[(s,reg)]; gp=f"{100.0*g[0]/g[1]:.0f}%" if g[1] else "--"
            print(f"  {s:14} {f(cl):>13} {f(no):>13} {f(gs):>13} | {dlt:>9} {gp:>5}")
print("\ndone.")
