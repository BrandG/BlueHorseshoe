"""Confluence: does requiring BOTH (below-cloud-age>=26 AND rsi<30) beat either single signal,
or is it redundant (same dislocation factor)? Decision metric = net R after cost, liquid >$25M,
hold20 next-open, clustered t. all-regime + nonbull.

Cells:
  rsi_pure   = rsi<30 & NOT below-cloud        (RSI dislocation the cloud doesn't see)
  rsi_all    = rsi<30                           (RSI regardless of cloud)
  cloud_pure = below & age>=26 & NOT rsi<30     (cloud dislocation RSI doesn't see) [our cell]
  cloud_all  = below & age>=26                  (cloud regardless of RSI)
  BOTH       = below & age>=26 & rsi<30         (the confluence — recently slammed AND chronically broken)
Read: if BOTH > max(rsi_all, cloud_all) with real n => super-additive confluence is real.
      if BOTH lands between/under => redundant; gate on age/depth directly instead.
"""
import numpy as np, pandas as pd, talib, duckdb
SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; DOLLAR_VOL=1_000_000; GAP=0.50; DISP=26; TP_ATR,SL_ATR=2.0,1.0; N_HOLD=20; LIQ=25e6
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")
con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg_map.get(str(d)[:10],False)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
syms=[s for s in syms if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"{len(syms)} symbols",flush=True)
rmx=lambda x,w: pd.Series(x).rolling(w).max().to_numpy(); rmn=lambda x,w: pd.Series(x).rolling(w).min().to_numpy()
Cc={}
def bumpC(k,v,nt):
    a=Cc.setdefault(k,[0.,0.,0,0]); a[0]+=v;a[1]+=v*v;a[2]+=1;a[3]+=nt
def stC(k,minsym=20):
    a=Cc.get(k)
    if not a or a[2]<minsym: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt
def bracket_R(h,l,c,atr,N,badpath,entry_px):
    n=len(c); tp=entry_px+TP_ATR*atr; sl=entry_px-SL_ATR*atr; Rp=SL_ATR*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan)
    valid=(np.arange(n)<(n-N-1))&(atr>0)&~np.isnan(atr)&~badpath&~np.isnan(entry_px)
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp[:n-k]; slh[:n-k]=l[k:]<=sl[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=TP_ATR/SL_ATR; resolved|=(loss|wn)
    ex=np.full(n,np.nan)
    if n-N>0: ex[:n-N]=c[N:][:n-N]
    to=valid&~resolved; res[to]=(ex[to]-entry_px[to])/Rp[to]
    return res,valid
CELLS=["rsi_pure","rsi_all","cloud_pure","cloud_all","BOTH"]
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
    tk=(rmx(h,9)+rmn(l,9))/2; kj=(rmx(h,26)+rmn(l,26))/2
    sA=np.full(n,np.nan); sB=np.full(n,np.nan)
    sA[DISP:]=((tk+kj)/2)[:n-DISP]; sB[DISP:]=((rmx(h,52)+rmn(l,52))/2)[:n-DISP]
    bot=np.fmin(sA,sB); below=c<bot; os=rsi<30
    age=np.zeros(n,int); run=0
    for i in range(n):
        if below[i]: run+=1; age[i]=run
        else: run=0
    cage=below&(age>=26)
    mask={"rsi_pure":os&~below,"rsi_all":os,"cloud_pure":cage&~os,"cloud_all":cage,"BOTH":cage&os}
    nonbull=~np.array([isbull(x) for x in dts])
    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL); pos=(c>0)&(o>0)&(h>0)&(l>0)
    clean=base_price&pos&(atr_pct>=VOL_FLOOR)&(dollar>=LIQ)
    open_next=np.full(n,np.nan); open_next[:n-1]=o[1:]
    badpath=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
    for t in range(n-N_HOLD-1):
        if cs[t+N_HOLD+1]-cs[t+1]>0: badpath[t]=True
    resO,valO=bracket_R(h,l,c,atr,N_HOLD,badpath,open_next)
    cost_bps=np.where(dollar>=25e6,5.0,np.where(dollar>=5e6,12.0,25.0))
    net=resO-(cost_bps/1e4)/np.where(atr_pct>0,atr_pct,np.nan)
    for rk,rmask in (("all",np.ones(n,bool)),("nonbull",nonbull)):
        okO=clean&valO&~np.isnan(net)&rmask
        for cn in CELLS:
            m=mask[cn]&okO
            if m.sum()>=3: bumpC((cn,rk),net[m].mean(),int(m.sum()))
print("\n############### CONFLUENCE: net R after cost (liquid >$25M, hold20 next-open, clustered t) ###############")
print("   does BOTH (cloud-age>=26 AND rsi<30) beat the singles, or is it redundant?\n")
for rk in ("all","nonbull"):
    print(f"  --- {rk} ---")
    for cn in CELLS:
        x=stC((cn,rk))
        print(f"    {cn:12} {(f'{x[0]:+.3f}R(t{x[1]:+.1f}) nsym={x[2]} nt={x[3]}' if x else '(thin)'):>40}")
    ca=stC(("cloud_all",rk)); ra=stC(("rsi_all",rk)); bo=stC(("BOTH",rk))
    if ca and ra and bo:
        best=max(ca[0],ra[0]); verdict="SUPER-ADDITIVE (beats both singles)" if bo[0]>best+0.01 else ("redundant (<= best single)" if bo[0]<=best else "marginal")
        print(f"    -> BOTH {bo[0]:+.3f} vs best single {best:+.3f}  => {verdict}")
    print()
print("done.")
