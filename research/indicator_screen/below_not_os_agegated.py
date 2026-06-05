"""#3 refinement — does AGE/DEPTH gating rescue the all-regime track, and what's the
net lift over random per liquidity tier?

Cells (all are below_not_os = below cloud & NOT rsi<30):
  bnos            : plain
  bnos_age26      : + age>=26 bars below cloud (persistent drawdown)
  bnos_deep       : + depth>=1.5 ATR below cloud
  bnos_age_deep   : both
Compared to RANDOM (all clean-eligible in regime), POOLED absolute R (the tradeable metric;
symbol-demeaned lift is composition-blind and overstated for all-regime).

A. HOLD SWEEP {10,20,30,40} pooled abs R + NW t, each cell vs RANDOM, all-regime + nonbull.
C. COST at hold=20 next-open, per $-vol tier: gated-cell NET vs RANDOM NET (the honest net lift).
"""
import numpy as np, pandas as pd, talib, duckdb
SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; DOLLAR_VOL=1_000_000; GAP=0.50; DISP=26; TP_ATR,SL_ATR=2.0,1.0
HOLDS=[10,20,30,40]; MAXLAG=max(HOLDS)-1
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
NW={}
def bumpNW(k,u,m):
    a=NW.get(k)
    if a is None: a=NW[k]=np.zeros(2+MAXLAG+1)
    a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    nz=np.nonzero(u)[0]
    if len(nz)==0: return
    lo,hi=nz[0],nz[-1]
    for j in range(1,MAXLAG+1):
        if hi-lo<j: break
        a[2+j]+=float(u[lo:hi+1-j]@u[lo+j:hi+1])
def stNW(k,bw):
    a=NW.get(k)
    if a is None or a[1]<50: return None
    S,M=a[0],a[1]; G=a[2:]
    w=np.array([1.0-j/(bw+1) for j in range(1,bw+1)])
    varS=G[0]+2.0*float(np.dot(w,G[1:bw+1]))
    if varS<=0: return None
    return S/M,(S/np.sqrt(varS)),int(M)
Cc={}
def bumpC(k,v,nt):
    a=Cc.setdefault(k,[0.,0.,0,0]); a[0]+=v;a[1]+=v*v;a[2]+=1;a[3]+=nt
def stC(k,minsym=20):
    a=Cc.get(k)
    if not a or a[2]<minsym: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt
def bracket_R(h,l,c,atr,N,tp_atr,sl_atr,badpath,entry_px):
    n=len(c); tp=entry_px+tp_atr*atr; sl=entry_px-sl_atr*atr; Rp=sl_atr*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan)
    valid=(np.arange(n)<(n-N-1))&(atr>0)&~np.isnan(atr)&~badpath&~np.isnan(entry_px)
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp[:n-k]; slh[:n-k]=l[k:]<=sl[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=tp_atr/sl_atr; resolved|=(loss|wn)
    ex=np.full(n,np.nan)
    if n-N>0: ex[:n-N]=c[N:][:n-N]
    to=valid&~resolved; res[to]=(ex[to]-entry_px[to])/Rp[to]
    return res,valid
CELLS=["bnos","bnos_age26","bnos_deep","bnos_age_deep"]
TIERS=(("liq>25M",25e6,1e18),("mid5-25M",5e6,25e6),("low1-5M",1e6,5e6))
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
    bot=np.fmin(sA,sB); below=c<bot; os=rsi<30; bnos=below&~os
    depth=np.where(atr>0,(bot-c)/atr,np.nan)
    age=np.zeros(n,int); run=0
    for i in range(n):
        if below[i]: run+=1; age[i]=run
        else: run=0
    cellmask={"bnos":bnos,"bnos_age26":bnos&(age>=26),"bnos_deep":bnos&(depth>=1.5),
              "bnos_age_deep":bnos&(age>=26)&(depth>=1.5)}
    nonbull=~np.array([isbull(x) for x in dts])
    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL); pos=(c>0)&(o>0)&(h>0)&(l>0)
    clean=base_price&pos&(atr_pct>=VOL_FLOOR)&(dollar>=DOLLAR_VOL)
    open_next=np.full(n,np.nan); open_next[:n-1]=o[1:]
    # A: hold sweep pooled abs R (NW)
    for N in HOLDS:
        badpath=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
        for t in range(n-N-1):
            if cs[t+N+1]-cs[t+1]>0: badpath[t]=True
        resB,valB=bracket_R(h,l,c,atr,N,TP_ATR,SL_ATR,badpath,c)
        for rk,rmask in (("all",np.ones(n,bool)),("nonbull",nonbull)):
            ok=clean&valB&~np.isnan(resB)&rmask
            ridx=np.where(ok)[0]
            if len(ridx)>=5:
                u=np.zeros(n); u[ridx]=resB[ridx]; bumpNW(("rand",rk,N),u,len(ridx))
            for cn in CELLS:
                fidx=np.where(cellmask[cn]&ok)[0]
                if len(fidx)>=5:
                    u=np.zeros(n); u[fidx]=resB[fidx]; bumpNW((cn,rk,N),u,len(fidx))
    # C: cost at hold20 next-open, per tier, cell NET and random NET
    N=20; badpath=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
    for t in range(n-N-1):
        if cs[t+N+1]-cs[t+1]>0: badpath[t]=True
    resO,valO=bracket_R(h,l,c,atr,N,TP_ATR,SL_ATR,badpath,open_next)
    cost_bps=np.where(dollar>=25e6,5.0,np.where(dollar>=5e6,12.0,25.0))
    cost_R=(cost_bps/1e4)/np.where(atr_pct>0,atr_pct,np.nan)
    net=resO-cost_R
    for rk,rmask in (("all",np.ones(n,bool)),("nonbull",nonbull)):
        okO=clean&valO&~np.isnan(net)&rmask
        for tn,tlo,thi in TIERS:
            tm=okO&(dollar>=tlo)&(dollar<thi)
            rm=tm
            if rm.any(): bumpC(("rand_net",tn,rk),net[rm].mean(),int(rm.sum()))
            for cn in ("bnos_age26","bnos_deep","bnos_age_deep"):
                cm=tm&cellmask[cn]
                if cm.any(): bumpC((cn+"_net",tn,rk),net[cm].mean(),int(cm.sum()))
print("\n############### A. AGE/DEPTH-GATED HOLD SWEEP — pooled abs R (NW t), cell vs RANDOM ###############")
for rk in ("all","nonbull"):
    print(f"\n  --- {rk} ---")
    print(f"    {'cell':14} "+" ".join(f"{'h'+str(N):>16}" for N in HOLDS))
    rr=[stNW(("rand",rk,N),N-1) for N in HOLDS]
    print(f"    {'RANDOM':14} "+" ".join(f"{(f'{x[0]:+.3f}R(t{x[1]:+.0f})' if x else '.'):>16}" for x in rr))
    for cn in CELLS:
        cells=[stNW((cn,rk,N),N-1) for N in HOLDS]
        print(f"    {cn:14} "+" ".join(f"{(f'{x[0]:+.3f}({x[2]//1000}k)' if x else '.'):>16}" for x in cells))
    print("    (cell cells show absR(ntrades-thousands); compare to RANDOM row; beating it = monetizes)")
print("\n############### C. COST-NET vs RANDOM-NET by tier (hold20, next-open) ###############")
for rk in ("all","nonbull"):
    print(f"\n  --- {rk} ---   net R after tiered cost ; lift = cell_net - rand_net")
    for tn,_,_ in TIERS:
        rnet=stC(("rand_net",tn,rk))
        print(f"    {tn:>9}  RANDOM_net={(f'{rnet[0]:+.3f}R(t{rnet[1]:+.1f})' if rnet else '.'):>18}")
        for cn in ("bnos_age26","bnos_deep","bnos_age_deep"):
            cnet=stC((cn+"_net",tn,rk))
            lift=(cnet[0]-rnet[0]) if (cnet and rnet) else None
            s=f"{cnet[0]:+.3f}R(t{cnet[1]:+.1f}) n={cnet[3]}" if cnet else "(thin)"
            ls=f"  lift={lift:+.3f}R" if lift is not None else ""
            print(f"        {cn:14} net={s:>26}{ls}")
print("\ndone.")
