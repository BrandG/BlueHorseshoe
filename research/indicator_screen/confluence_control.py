"""Depth-matched control: is BOTH (cloud-age>=26 & rsi<30) super-additive because RSI adds an
INDEPENDENT axis, or because it just selects the deepest/oldest tail of cloud dislocation?

Collect every cloud_all (below & age>=26, liquid>$25M, hold20 next-open net) trade with its
(net, depth=ATR below cloud, age, is_both). Then:
  - BOTH mean net (reference)
  - DEPTH-matched control: top-N cloud_all by depth (N = #BOTH), mean net
  - AGE-matched control:   top-N cloud_all by age,   mean net
  - does BOTH select deeper/older? (mean depth/age of BOTH vs all cloud_all)
Read: if a single-axis-matched control REACHES BOTH's net -> RSI is a proxy for that axis (gate directly).
      if BOTH still beats both matched controls -> RSI is a genuine 2nd axis (true confluence).
"""
import numpy as np, pandas as pd, talib, duckdb
SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; GAP=0.50; DISP=26; TP_ATR,SL_ATR=2.0,1.0; N_HOLD=20; LIQ=25e6
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
# collectors per regime: lists of (net, depth, age, isboth)
COL={"all":[[],[],[],[]],"nonbull":[[],[],[],[]]}
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
    depth=np.where(atr>0,(bot-c)/atr,np.nan)
    age=np.zeros(n,int); run=0
    for i in range(n):
        if below[i]: run+=1; age[i]=run
        else: run=0
    cage=below&(age>=26)
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
        m=cage&clean&valO&~np.isnan(net)&~np.isnan(depth)&rmask
        idx=np.where(m)[0]
        if len(idx):
            COL[rk][0].extend(net[idx].tolist()); COL[rk][1].extend(depth[idx].tolist())
            COL[rk][2].extend(age[idx].tolist()); COL[rk][3].extend(os[idx].tolist())
def boot_t(x):
    x=np.asarray(x); m=x.mean(); se=x.std(ddof=1)/np.sqrt(len(x)); return m,(m/se if se>0 else 0),len(x)
print("\n############### DEPTH/AGE-MATCHED CONTROL — is BOTH true confluence or just deeper? ###############")
for rk in ("all","nonbull"):
    net=np.array(COL[rk][0]); dep=np.array(COL[rk][1]); ag=np.array(COL[rk][2]); both=np.array(COL[rk][3],bool)
    if len(net)<100: print(f"  {rk}: thin"); continue
    nB=int(both.sum())
    mB,tB,_=boot_t(net[both])
    # depth-matched: top-nB cloud_all by depth
    di=np.argsort(-dep)[:nB]; mD,tD,_=boot_t(net[di])
    ai=np.argsort(-ag)[:nB]; mA,tA,_=boot_t(net[ai])
    mAll,_,_=boot_t(net)
    print(f"\n  --- {rk} ---   cloud_all n={len(net)}, BOTH n={nB}")
    print(f"    BOTH (cloud & rsi<30)         {mB:+.3f}R (t{tB:+.1f})")
    print(f"    depth-matched top-{nB} cloud   {mD:+.3f}R (t{tD:+.1f})   [select deepest by ATR-below-cloud]")
    print(f"    age-matched   top-{nB} cloud   {mA:+.3f}R (t{tA:+.1f})   [select oldest age-below-cloud]")
    print(f"    cloud_all (all of it)         {mAll:+.3f}R")
    print(f"    mean depth: BOTH={dep[both].mean():.2f}ATR vs cloud_all={dep.mean():.2f}ATR ;"
          f"  mean age: BOTH={ag[both].mean():.0f} vs cloud_all={ag.mean():.0f}")
    win=mB-max(mD,mA)
    verdict="TRUE 2-AXIS CONFLUENCE (BOTH beats both matched controls)" if win>0.02 else \
            ("RSI ~ depth/age proxy (a matched control reaches it)" if win<=0 else "marginal")
    print(f"    => BOTH - best matched control = {win:+.3f}R  -> {verdict}")
print("\ndone.")
