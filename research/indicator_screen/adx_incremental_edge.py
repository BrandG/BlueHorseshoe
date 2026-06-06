"""Incremental-edge test: is aged-nonbull-ADX(21) a NEW factor, or re-found dislocation?

psar_adx_nw.py surfaced one ember: ADX(21)>25 in nonbull, with the edge living entirely in AGED bars
(age6+ = +0.036R t+4.0) and flipped positive only after dropping de-overlap. The open question (per the
'prune on EDGE not correlation' rule): does that +R survive CONDITIONAL on the bar NOT already being a
dislocation bar (below the Ichimoku cloud OR RSI<30)? If it vanishes off the dislocation bars it's the
same mean-reversion factor seen through ADX; if it survives it's an orthogonal contributor.

Decompose ADX_aged firings (nonbull) by dislocation membership and measure each cell's full-pop cluster
+ Newey-West R-lift vs the same regime random baseline:
   ADX_aged              = ADX21>25 & age>=GATE
   ADX_aged & disloc     = ... & (below_cloud | rsi<30)        [overlap with known factor]
   ADX_aged & clean      = ... & ~below_cloud & ~rsi<30        [KEY: incremental edge]
Symmetric control (which signal is the parent?):
   disloc                = below_cloud | rsi<30
   disloc & ~ADX_aged    = dislocation WITHOUT the ADX-persistence condition
Machinery byte-identical to clean_harness.py PASS 2 (bracket TP2:SL1 hold10, vol/$vol floor, gap-skip,
symbol-cluster, NW Bartlett L=BR_N-1). GATE swept at 6 (headline) and 3 (robustness).
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; DOLLAR_VOL=1_000_000; GAP=0.50
BR_N=10; TP_ATR,SL_ATR=2.0,1.0; DISP=26
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")
GATES=[6,3]

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

CELLN=[]  # collected once
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

    # Ichimoku cloud bottom -> below_cloud; rsi oversold
    sA=np.full(n,np.nan); sB=np.full(n,np.nan)
    tk=(rmx(h,9)+rmn(l,9))/2; kj=(rmx(h,26)+rmn(l,26))/2
    sA[DISP:]=((tk+kj)/2)[:n-DISP]; sB[DISP:]=((rmx(h,52)+rmn(l,52))/2)[:n-DISP]
    bot=np.fmin(sA,sB); below=c<bot; os=rsi<30
    disloc=below|os; clean=(~below)&(~os)

    adx21=talib.ADX(h,l,c,21); adx_state=adx21>25; age=age_of(adx_state)

    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL); pos=(c>0)&(o>0)&(h>0)&(l>0)
    clean_elig=base_price&pos&(atr_pct>=VOL_FLOOR)&(dollar>=DOLLAR_VOL)
    badpathB=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
    for t in range(n-BR_N):
        if cs[t+BR_N+1]-cs[t+1]>0: badpathB[t]=True
    res,valid=bracket(h,l,c,atr,BR_N,TP_ATR,SL_ATR,badpathB)
    ok=clean_elig&valid&~np.isnan(res)

    for rk,rmask in (("nonbull",nonbull),("all",np.ones(n,bool))):
        base=ok&rmask
        if base.sum()<20: continue
        bmean=res[base].mean()
        for GATE in GATES:
            aged=adx_state&(age>=GATE)
            cells={
                f"ADX_aged{GATE}":              aged,
                f"ADX_aged{GATE}&disloc":       aged&disloc,
                f"ADX_aged{GATE}&clean":        aged&clean,
                f"disloc(ref{GATE})":           disloc,
                f"disloc&~ADXaged{GATE}":       disloc&~aged,
            }
            for cname,cmask in cells.items():
                fidx=np.where(cmask&base)[0]
                if len(fidx)>=5:
                    bumpF((cname,rk), float(res[fidx].mean()-bmean), len(fidx))
                    u=np.zeros(n); u[fidx]=res[fidx]-bmean
                    bumpNW((cname,rk), u, len(fidx))

def stF(k,minsym=30):
    a=BF.get(k)
    if not a or a[2]<minsym: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt
def stNW(k,minfire=50):
    a=NW.get(k)
    if a is None or a[1]<minfire: return None
    S,M=a[0],a[1]; G=a[2:]; varS=G[0]+2.0*float(np.dot(NW_W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)

print("\n############### ADX(21) incremental-edge decomposition vs dislocation (below_cloud | rsi<30) ###############")
print("  KEY ROW = 'ADX_aged&clean': aged-ADX edge on bars that are NEITHER below-cloud NOR oversold.")
print("  if it collapses to ~0/neg => the ember IS the dislocation factor (redundant). if it holds => orthogonal.\n")
for rk in ("nonbull","all"):
    print(f"  === regime={rk} ===   (full-pop cluster | Newey-West, R-lift vs random)")
    for GATE in GATES:
        print(f"   -- age>= {GATE} --")
        order=[f"ADX_aged{GATE}",f"ADX_aged{GATE}&disloc",f"ADX_aged{GATE}&clean",
               f"disloc(ref{GATE})",f"disloc&~ADXaged{GATE}"]
        # firing-share context
        tot=stNW((f"ADX_aged{GATE}",rk)); ov=stNW((f"ADX_aged{GATE}&disloc",rk)); cl=stNW((f"ADX_aged{GATE}&clean",rk))
        if tot and ov: frac=100.0*ov[2]/tot[2]
        else: frac=float('nan')
        for cname in order:
            ff=stF((cname,rk)); nw=stNW((cname,rk))
            c2=f"{ff[0]:+.3f}R t{ff[1]:+.1f} ns={ff[2]}" if ff else "(thin)"
            c3=f"{nw[0]:+.3f}R t{nw[1]:+.1f} nfire={nw[2]}" if nw else "(thin)"
            print(f"     {cname:26} {c2:>26} | {c3:>30}")
        print(f"     -> of ADX_aged{GATE} firings, {frac:.0f}% are dislocation bars\n")
print("done.")
