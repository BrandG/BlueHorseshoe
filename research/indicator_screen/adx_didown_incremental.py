"""Is adx_diDown's edge NEW, or just the known dislocation factor in disguise?

The PSAR/ADX re-audit (psar_adx_reaudit.out) found the ONLY live ADX edge is contrarian:
adx_diDown (ADX>25 & -DI>+DI = strong established DOWNtrend), long bracket, nonbull NW +0.094R t12.2,
monotone-rising to age6+ +0.104R t11.1. But "strong downtrend" ≈ "price falling hard" ≈ the SAME
dislocation factor already carried by rsi<30 / below-cloud / below-SMA ([[project_signal_independence]],
[[project_heiken_ashi_deepdive]] where the analogous HA reversal edge collapsed to 0 once conditioned).
So before any "ADX has edge" claim, the [[project_pruning_edge_not_correlation]] standard applies:
test INCREMENTAL edge, not correlation.

For each known-dislocation set, in nonbull (where the edge lives):
  (A) overlap: % of adx_diDown fires that are also in the known set
  (B) adx_diDown AND NOT known   -> the part the anchors can't see (residual; the decisive number)
  (C) adx_diDown AND known       -> confluence subset
  (D) reference: known alone, and known AND NOT adx_diDown
Three known sets to localize redundancy:
  known_osc = rsi<30 OR below-cloud           (the oscillator/cloud dislocation; same as the HA test)
  known_ma  = below_sma200 OR (sma50-c)/atr>2 (the MA trend-dislocation adx_diDown is closest to)
  known_all = known_osc OR known_ma

Machinery identical to ha_incremental.py / psar_adx_reaudit.py: bracket TP2:SL1 hold10, vol+$vol floors,
gap-skip, NW Bartlett L=BR_N-1 (trade-weighted), demean vs same-regime random.
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

KNOWN_SETS=["known_osc","known_ma","known_all"]
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
    adx14=talib.ADX(h,l,c,14); pdi=talib.PLUS_DI(h,l,c,14); mdi=talib.MINUS_DI(h,l,c,14)
    sma50=talib.SMA(c,50); sma200=talib.SMA(c,200)
    sA=np.full(n,np.nan); sB=np.full(n,np.nan)
    tk=(rmx(h,9)+rmn(l,9))/2; kj=(rmx(h,26)+rmn(l,26))/2
    sA[DISP:]=((tk+kj)/2)[:n-DISP]; sB[DISP:]=((rmx(h,52)+rmn(l,52))/2)[:n-DISP]
    bot=np.fmin(sA,sB)
    os=rsi<30; below=c<bot
    known_osc=os|below
    known_ma=(c<sma200)|((sma50-c)/np.where(atr>0,atr,np.nan)>2.0)
    known_all=known_osc|known_ma
    KNOWN={"known_osc":known_osc,"known_ma":known_ma,"known_all":known_all}
    adx_diDown=(adx14>25)&(mdi>pdi)

    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL); pos=(c>0)&(o>0)&(h>0)&(l>0)
    clean_elig=base_price&pos&(atr_pct>=VOL_FLOOR)&(dollar>=DOLLAR_VOL)
    badpathB=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
    for t in range(n-BR_N):
        if cs[t+BR_N+1]-cs[t+1]>0: badpathB[t]=True
    res,valid=bracket(h,l,c,atr,BR_N,TP_ATR,SL_ATR,badpathB)
    ok=clean_elig&valid&~np.isnan(res)&nonbull
    if ok.sum()<20: continue
    bmean=res[ok].mean()
    def acc(tag,mask):
        m=np.asarray(mask,bool)&ok; fidx=np.where(m)[0]
        if len(fidx)>=5:
            u=np.zeros(n); u[fidx]=res[fidx]-bmean
            bumpNW(tag,u,len(fidx))
    a=np.asarray(adx_diDown,bool)
    acc(("adx_diDown","all"),a)
    for ks in KNOWN_SETS:
        kn=np.asarray(KNOWN[ks],bool)
        s=a&ok
        if s.sum(): bumpOV((ks),int((s&kn).sum()),int(s.sum()))
        acc(("adx_diDown","not_"+ks),a&~kn)
        acc(("adx_diDown","and_"+ks),a&kn)
        acc((ks,"all"),kn)
        acc((ks,"not_adx"),kn&~a)

def stNW(k,minfire=50):
    a=NW.get(k)
    if a is None or a[1]<minfire: return None
    S,M=a[0],a[1]; G=a[2:]; varS=G[0]+2.0*float(np.dot(NW_W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def f(x): return f"{x[0]:+.3f}R t{x[1]:+.1f} n{x[2]}" if x else "(thin)"

print("\n################ adx_diDown INCREMENTAL EDGE (nonbull) ################")
print("  Q: is the adx_diDown edge NEW, or the known dislocation factor in disguise?")
print(f"  adx_diDown (all):  {f(stNW(('adx_diDown','all')))}")
for ks in KNOWN_SETS:
    ov=OV.get(ks); frac=100.0*ov[0]/ov[1] if ov and ov[1] else 0.0
    print(f"\n  --- vs {ks} ---  overlap: {frac:.1f}% of adx_diDown fires are also in {ks}")
    print(f"    adx_diDown AND NOT {ks} (residual): {f(stNW(('adx_diDown','not_'+ks)))}   <-- decisive")
    print(f"    adx_diDown AND {ks}:                {f(stNW(('adx_diDown','and_'+ks)))}")
    print(f"    {ks} alone:                         {f(stNW((ks,'all')))}")
    print(f"    {ks} AND NOT adx_diDown:            {f(stNW((ks,'not_adx')))}")
print("\ndone.")
