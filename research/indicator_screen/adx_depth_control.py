"""Depth-controlled amplifier test: does ADX-persistence add edge WITHIN a fixed dislocation-depth bucket?

adx_incremental_edge.py showed ADX adds nothing on clean (non-dislocated) bars, but ADX∩disloc (+0.127R)
pays MORE than disloc∖ADX (+0.046R). Two explanations:
  (A) ADX-persistence is a real CONDITIONER/amplifier on the dislocation sleeve (sizing lever), OR
  (B) ADX>25-for-6-bars in a weak tape just SELECTS deeper dislocations (depth collinearity) — and we
      already know the edge is monotonic in dislocation depth, so ADX would add nothing new.
Test: stratify dislocation bars by DEPTH on each axis, and within each bucket compare withADX vs noADX.
  If withADX beats noADX in EVERY depth bucket -> real conditioner (A).
  If the gap vanishes once depth is fixed       -> ADX was a depth proxy (B).
Depth axes (Brand: control BOTH RSI and cloud, not just cloud):
  RSI       : among rsi<30, bucket by rsi level (lower = deeper oversold)
  CLOUD_DIST: among below-cloud, bucket by (cloud_bottom - close)/ATR  (further below = deeper)
  CLOUD_AGE : among below-cloud, bucket by consecutive bars-below-cloud (older = more persistent)
ADX_aged := ADX(21)>25 sustained >=6 bars. Machinery identical to clean_harness PASS 2 (NW Bartlett L=9).
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; DOLLAR_VOL=1_000_000; GAP=0.50
BR_N=10; TP_ATR,SL_ATR=2.0,1.0; DISP=26; ADX_GATE=6
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
print(f"{len(syms)} symbols, ADX_aged := ADX21>25 & age>={ADX_GATE}",flush=True)

rmx=lambda x,w: pd.Series(x).rolling(w).max().to_numpy(); rmn=lambda x,w: pd.Series(x).rolling(w).min().to_numpy()
BF={}
def bumpF(k,lift,nt):
    a=BF.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
L_NW=BR_N-1; NW_W=np.array([1.0-j/(L_NW+1) for j in range(L_NW+1)])
NW={}
def bumpNW(k,u,m):
    a=NW.setdefault(k,np.zeros(3+L_NW)); a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    for j in range(1,L_NW+1): a[2+j]+=float(u[:-j]@u[j:])
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
def age_of(state):
    a=np.full(len(state),-1,int); r=0
    for i in range(len(state)):
        if state[i]: a[i]=r; r+=1
        else: r=0
    return a

# depth buckets per axis: (label, predicate on per-bar depth array)
RSI_BK =[("rsi27-30",lambda r:(r>=27)&(r<30)),("rsi24-27",lambda r:(r>=24)&(r<27)),
         ("rsi20-24",lambda r:(r>=20)&(r<24)),("rsi<20",lambda r:r<20)]
DIST_BK=[("0-1atr",lambda d:(d>=0)&(d<1)),("1-2atr",lambda d:(d>=1)&(d<2)),
         ("2-4atr",lambda d:(d>=2)&(d<4)),("4+atr",lambda d:d>=4)]
AGE_BK =[("age1-5",lambda a:(a>=1)&(a<=5)),("age6-25",lambda a:(a>=6)&(a<=25)),("age26+",lambda a:a>=26)]

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

    sA=np.full(n,np.nan); sB=np.full(n,np.nan)
    tk=(rmx(h,9)+rmn(l,9))/2; kj=(rmx(h,26)+rmn(l,26))/2
    sA[DISP:]=((tk+kj)/2)[:n-DISP]; sB[DISP:]=((rmx(h,52)+rmn(l,52))/2)[:n-DISP]
    bot=np.fmin(sA,sB); below=c<bot
    dist=np.where(below,(bot-c)/np.where(atr>0,atr,np.nan),np.nan)   # ATR-units below cloud
    age_below=age_of(below).astype(float)
    os=rsi<30
    adx21=talib.ADX(h,l,c,21); adx_aged=(adx21>25)&(age_of(adx21>25)>=ADX_GATE)

    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL); pos=(c>0)&(o>0)&(h>0)&(l>0)
    clean_elig=base_price&pos&(atr_pct>=VOL_FLOOR)&(dollar>=DOLLAR_VOL)
    badpathB=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
    for t in range(n-BR_N):
        if cs[t+BR_N+1]-cs[t+1]>0: badpathB[t]=True
    res,valid=bracket(h,l,c,atr,BR_N,TP_ATR,SL_ATR,badpathB)
    ok=clean_elig&valid&~np.isnan(res)

    AXES=[("RSI",os,rsi,RSI_BK),("CLOUD_DIST",below,dist,DIST_BK),("CLOUD_AGE",below,age_below,AGE_BK)]
    for rk,rmask in (("nonbull",nonbull),("all",np.ones(n,bool))):
        base=ok&rmask
        if base.sum()<20: continue
        bmean=res[base].mean()
        for axis,axmask,depthval,BKS in AXES:
            for blab,pred in BKS:
                bm=base&axmask&pred(depthval)
                for grp,gmask in (("withADX",adx_aged),("noADX",~adx_aged),("all",np.ones(n,bool))):
                    fidx=np.where(bm&gmask)[0]
                    if len(fidx)>=5:
                        bumpF((axis,blab,grp,rk), float(res[fidx].mean()-bmean), len(fidx))
                        u=np.zeros(n); u[fidx]=res[fidx]-bmean
                        bumpNW((axis,blab,grp,rk), u, len(fidx))

def stNW(k,minfire=40):
    a=NW.get(k)
    if a is None or a[1]<minfire: return None
    S,M=a[0],a[1]; G=a[2:]; varS=G[0]+2.0*float(np.dot(NW_W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)

print("\n############### DEPTH-CONTROLLED ADX AMPLIFIER TEST (NW R-lift vs regime random) ###############")
print("  within each dislocation-depth bucket: does ADX-persistence (withADX) beat its absence (noADX)?")
print("  GAP = withADX − noADX.  consistent +GAP across buckets => real conditioner; ~0/erratic => depth proxy.\n")
for axis,_,_,BKS in [("RSI",0,0,RSI_BK),("CLOUD_DIST",0,0,DIST_BK),("CLOUD_AGE",0,0,AGE_BK)]:
    for rk in ("nonbull","all"):
        print(f"  === {axis}  regime={rk} ===  (deeper bucket → down the list)")
        print(f"    {'bucket':10} {'ALL-in-bucket':>20} {'withADX':>20} {'noADX':>20} {'GAP(w−n)':>12}")
        for blab,_ in BKS:
            a=stNW((axis,blab,"all",rk)); w=stNW((axis,blab,"withADX",rk)); no=stNW((axis,blab,"noADX",rk))
            ca=f"{a[0]:+.3f}R t{a[1]:+.1f} n{a[2]}" if a else "(thin)"
            cw=f"{w[0]:+.3f}R t{w[1]:+.1f} n{w[2]}" if w else "(thin)"
            cn=f"{no[0]:+.3f}R t{no[1]:+.1f} n{no[2]}" if no else "(thin)"
            gap=f"{w[0]-no[0]:+.3f}R" if (w and no) else "  ."
            print(f"    {blab:10} {ca:>20} {cw:>20} {cn:>20} {gap:>12}")
        print()
print("done.")
