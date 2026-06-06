"""Is Heiken-Ashi's reversal/dislocation edge NEW, or just rsi<30 / below-cloud in disguise?

The HA sweep (ha_nw_sweep.out) found the edge lives entirely in the REVERSAL direction:
  ha_flip_up  (first green HA bar after a red): nonbull NW +0.078R t12.4
  ha_redrun8  (8+ consecutive red HA bars):     nonbull NW +0.100R t8.2
while the deployed trend-continuation shape (ha_3green) is anti-predictive (-0.065R t-10).

But [[project_signal_independence]] says these are ~3.7 independent factors and the reversion/
dislocation factor is ALREADY carried by rsi_oversold + below_cloud + below_sma. So before anyone
believes HA adds anything, the [[project_pruning_edge_not_correlation]] standard applies: test
INCREMENTAL edge, not correlation. For each HA winner:
  (A) overlap: what fraction of HA-signal bars are ALSO rsi<30 or below-cloud?
  (B) HA-signal AND NOT(rsi<30 OR below_cloud)  -> the part the known anchors can't see (residual)
  (C) known AND NOT HA                           -> what HA can't see
  (D) both
If the residual (B) keeps a clean NW t, HA is a genuinely new lens. If it collapses, HA is redundant.

Machinery identical to ha_nw_sweep.py: bracket TP2:SL1 hold10, vol+$vol floors, gap-skip, NW
Bartlett L=BR_N-1, trade-weighted, demean vs same-regime random. nonbull regime (where edge is largest).
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; DOLLAR_VOL=1_000_000; GAP=0.50; DISP=26
BR_N=10; TP_ATR,SL_ATR=2.0,1.0
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg_map.get(str(d)[:10],False)

syms=con.execute("""SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300""",[START]).df().symbol.tolist()
syms=[s for s in syms if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"{len(syms)} symbols",flush=True)

rmx=lambda x,w: pd.Series(x).rolling(w).max().to_numpy(); rmn=lambda x,w: pd.Series(x).rolling(w).min().to_numpy()
def shift(a,k):
    out=np.full(len(a),np.nan)
    if k<len(a): out[k:]=a[:-k]
    return out
L_NW=BR_N-1; NW_W=np.array([1.0-j/(L_NW+1) for j in range(L_NW+1)])
NW={}; OV={}
def bumpNW(k,u,m):
    a=NW.setdefault(k,np.zeros(3+L_NW)); a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    for j in range(1,L_NW+1): a[2+j]+=float(u[:-j]@u[j:])
def bumpOV(k,num,den):
    a=OV.setdefault(k,[0,0]); a[0]+=num; a[1]+=den
def bracket(h,l,c,atr,N,tp_atr,sl_atr,badpath):
    n=len(c); tp=c+tp_atr*atr; sl=c-sl_atr*atr; Rp=sl_atr*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan)
    valid=(np.arange(n)<(n-N))&(atr>0)&~np.isnan(atr)&~badpath
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp[:n-k]; slh[:n-k]=l[k:]<=sl[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=tp_atr/sl_atr; resolved|=(loss|wn)
    ex=np.full(n,np.nan)
    if n-N>0: ex[:n-N]=c[N:][:n-N]
    to=valid&~resolved; res[to]=(ex[to]-c[to])/Rp[to]
    return res,valid

for ii,sym in enumerate(syms):
    if ii%400==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    if n<300: continue
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan); dollar=c*vol20
    dmove=np.zeros(n); dmove[1:]=np.abs(c[1:]/np.where(c[:-1]>0,c[:-1],np.nan)-1.0); badday=dmove>GAP
    nonbull=~np.array([isbull(x) for x in dts])
    # cloud
    sA=np.full(n,np.nan); sB=np.full(n,np.nan)
    tk=(rmx(h,9)+rmn(l,9))/2; kj=(rmx(h,26)+rmn(l,26))/2
    sA[DISP:]=((tk+kj)/2)[:n-DISP]; sB[DISP:]=((rmx(h,52)+rmn(l,52))/2)[:n-DISP]
    bot=np.fmin(sA,sB); below=c<bot; os=rsi<30
    known=os|below            # the established dislocation edge factor
    # HA
    ha_close=(o+h+l+c)/4.0
    ha_open=np.empty(n); ha_open[0]=(o[0]+c[0])/2.0
    redrun=np.zeros(n,int)
    for t in range(1,n): ha_open[t]=(ha_open[t-1]+ha_close[t-1])/2.0
    green=ha_close>ha_open; red=ha_close<ha_open
    for t in range(1,n): redrun[t]=redrun[t-1]+1 if red[t] else 0
    rp=shift(red.astype(float),1)
    ha_flip_up=green&(rp==1); ha_redrun8=redrun>=8

    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL); pos=(c>0)&(o>0)&(h>0)&(l>0)
    clean_elig=base_price&pos&(atr_pct>=VOL_FLOOR)&(dollar>=DOLLAR_VOL)
    badpathB=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
    for t in range(n-BR_N):
        if cs[t+BR_N+1]-cs[t+1]>0: badpathB[t]=True
    res,valid=bracket(h,l,c,atr,BR_N,TP_ATR,SL_ATR,badpathB)
    ok=clean_elig&valid&~np.isnan(res)&nonbull   # nonbull only
    if ok.sum()<20: continue
    bmean=res[ok].mean()
    def acc(tag,mask):
        m=np.asarray(mask,bool)&ok; fidx=np.where(m)[0]
        if len(fidx)>=5:
            u=np.zeros(n); u[fidx]=res[fidx]-bmean
            bumpNW(tag,u,len(fidx))
    for nm,sig in (("flip_up",ha_flip_up),("redrun8",ha_redrun8)):
        s=np.asarray(sig,bool)&ok
        if s.sum(): bumpOV(nm,int((s&known).sum()),int(s.sum()))
        acc((nm,"all"),sig)
        acc((nm,"not_known"),sig&~known)   # residual: HA sees, anchors don't
        acc((nm,"and_known"),sig&known)
    acc(("known","all"),known)
    acc(("known","not_ha_flip"),known&~ha_flip_up)
    acc(("known","not_ha_redrun8"),known&~ha_redrun8)

def stNW(k,minfire=50):
    a=NW.get(k)
    if a is None or a[1]<minfire: return None
    S,M=a[0],a[1]; G=a[2:]; varS=G[0]+2.0*float(np.dot(NW_W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def f(x): return f"{x[0]:+.3f}R t{x[1]:+.1f} n{x[2]}" if x else "(thin)"

print("\n################ HEIKEN-ASHI INCREMENTAL EDGE (nonbull) ################")
print("  Q: is HA reversal edge NEW, or rsi<30 / below-cloud in disguise?  known = (rsi<30 OR below_cloud)")
for nm in ("flip_up","redrun8"):
    ov=OV.get(nm); frac=100.0*ov[0]/ov[1] if ov and ov[1] else 0.0
    print(f"\n  --- ha_{nm} ---")
    print(f"    overlap with known dislocation: {frac:.1f}% of fires are also rsi<30 or below-cloud")
    print(f"    ha_{nm} (all):                 {f(stNW((nm,'all')))}")
    print(f"    ha_{nm} AND NOT known (resid): {f(stNW((nm,'not_known')))}   <-- the part anchors can't see")
    print(f"    ha_{nm} AND known:             {f(stNW((nm,'and_known')))}")
print("\n  --- reference: known dislocation factor itself ---")
print(f"    known (rsi<30 OR below_cloud):   {f(stNW(('known','all')))}")
print(f"    known AND NOT ha_flip_up:        {f(stNW(('known','not_ha_flip')))}")
print(f"    known AND NOT ha_redrun8:        {f(stNW(('known','not_ha_redrun8')))}")
print("\ndone.")
