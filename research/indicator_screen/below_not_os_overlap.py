"""Is the gated cloud cell ADDITIVE to the existing rsi_oversold/gap_up contrarian sleeve,
or does it catch the same episodes?

Cloud cell C = below_cloud & NOT rsi<30 & age>=26 (the refined, monetizing cell).
By construction C never shares a BAR with rsi<30 — so the real question is TEMPORAL/episode overlap:
when C fires, has the oversold book already (or about to) put us in that same name nearby?

  sleeve_near[t] := any (rsi<30 OR gap_up>2%) on the SAME symbol within +/-W trading days of t.
Metrics (liquid >$25M tier, the tradeable one; hold20 next-open net R):
  1. overlap %: share of C fires that are sleeve_near (W=5 and W=10).
  2. ADDITIVITY: C's net R split sleeve_NEAR vs sleeve_FAR. If the FAR subset still pays, C is
     genuinely additive — new names/times the oversold book misses.
  3. reference: the rsi/gap sleeve's own net R (same filters).
"""
import numpy as np, pandas as pd, talib, duckdb
SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; DOLLAR_VOL=1_000_000; GAP=0.50; DISP=26; TP_ATR,SL_ATR=2.0,1.0
N_HOLD=20; LIQ=25e6
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
def bumpC(k,v,nt=1):
    a=Cc.setdefault(k,[0.,0.,0,0]); a[0]+=v;a[1]+=v*v;a[2]+=1;a[3]+=nt
def stC(k,minsym=20):
    a=Cc.get(k)
    if not a or a[2]<minsym: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt
# overlap counters: key -> [near,total]
OV={}
def bumpOV(k,near):
    a=OV.setdefault(k,[0,0]); a[0]+=int(near); a[1]+=1
def within(mask,W):
    """True at t if mask is True anywhere in [t-W, t+W]."""
    n=len(mask); cs=np.concatenate([[0],np.cumsum(mask.astype(int))])
    out=np.zeros(n,bool)
    for t in range(n):
        lo=max(0,t-W); hi=min(n-1,t+W)
        if cs[hi+1]-cs[lo]>0: out[t]=True
    return out
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
    gap_up=np.zeros(n,bool); gap_up[1:]=o[1:]>c[:-1]*1.02
    age=np.zeros(n,int); run=0
    for i in range(n):
        if below[i]: run+=1; age[i]=run
        else: run=0
    C=below&~os&(age>=26)
    sleeve=os|gap_up
    nonbull=~np.array([isbull(x) for x in dts])
    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL); pos=(c>0)&(o>0)&(h>0)&(l>0)
    clean=base_price&pos&(atr_pct>=VOL_FLOOR)&(dollar>=DOLLAR_VOL)&(dollar>=LIQ)
    open_next=np.full(n,np.nan); open_next[:n-1]=o[1:]
    near5=within(sleeve,5); near10=within(sleeve,10)
    badpath=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
    for t in range(n-N_HOLD-1):
        if cs[t+N_HOLD+1]-cs[t+1]>0: badpath[t]=True
    resO,valO=bracket_R(h,l,c,atr,N_HOLD,badpath,open_next)
    cost_bps=np.where(dollar>=25e6,5.0,np.where(dollar>=5e6,12.0,25.0))
    net=resO-(cost_bps/1e4)/np.where(atr_pct>0,atr_pct,np.nan)
    for rk,rmask in (("all",np.ones(n,bool)),("nonbull",nonbull)):
        okO=clean&valO&~np.isnan(net)&rmask
        # overlap rates among C fires (liquid)
        for i in np.where(C&okO)[0]:
            bumpOV(("w5",rk),near5[i]); bumpOV(("w10",rk),near10[i])
        # additivity: C net split near/far (W=10)
        cf=C&okO
        for i in np.where(cf&near10)[0]: bumpC(("C_near",rk),net[i])
        for i in np.where(cf&~near10)[0]: bumpC(("C_far",rk),net[i])
        # per-symbol means too (clustered) for honest t
        m_near=cf&near10; m_far=cf&~near10
        if m_near.sum()>=3: bumpC(("C_near_sym",rk),net[m_near].mean(),int(m_near.sum()))
        if m_far.sum()>=3: bumpC(("C_far_sym",rk),net[m_far].mean(),int(m_far.sum()))
        # reference: sleeve's own net (liquid)
        sm=sleeve&okO
        if sm.sum()>=3: bumpC(("sleeve_sym",rk),net[sm].mean(),int(sm.sum()))
        cm=cf
        if cm.sum()>=3: bumpC(("C_all_sym",rk),net[cm].mean(),int(cm.sum()))
print("\n############### OVERLAP of gated cloud cell (below_not_os & age>=26) with rsi<30 | gap_up sleeve ###############")
print("   liquid >$25M tier.  'near' = a sleeve signal on same symbol within +/-W trading days of the cloud entry.")
for rk in ("all","nonbull"):
    a5=OV.get(("w5",rk),[0,0]); a10=OV.get(("w10",rk),[0,0])
    p5=100*a5[0]/a5[1] if a5[1] else 0; p10=100*a10[0]/a10[1] if a10[1] else 0
    print(f"  {rk:8}: within +/-5d {p5:5.1f}%   within +/-10d {p10:5.1f}%   (of {a10[1]} cloud fires)")
print("\n############### ADDITIVITY: cloud-cell NET R, sleeve-FAR vs sleeve-NEAR (clustered t) ###############")
print("   if sleeve-FAR still pays => the cloud catches episodes the oversold book MISSES (additive).")
for rk in ("all","nonbull"):
    af=stC(("C_far_sym",rk)); an=stC(("C_near_sym",rk)); al=stC(("C_all_sym",rk)); sl=stC(("sleeve_sym",rk))
    def f(x): return f"{x[0]:+.3f}R(t{x[1]:+.1f}) nsym={x[2]} nt={x[3]}" if x else "(thin)"
    print(f"  --- {rk} ---")
    print(f"    cloud ALL      {f(al)}")
    print(f"    cloud FAR      {f(af)}   <- episodes the sleeve does NOT cover")
    print(f"    cloud NEAR     {f(an)}")
    print(f"    sleeve (ref)   {f(sl)}")
print("\ndone.")
