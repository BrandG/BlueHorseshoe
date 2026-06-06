"""Heiken-Ashi deep dive under the blessed Newey-West harness.

HA is deployed in production (config HEIKEN_ASHI_MULTIPLIER=1.0 in trend, 0.0 in MR) as a
TREND-CONTINUATION signal: calculate_heiken_ashi() scores +3 when the last 3 HA candles are
bullish (HA_close>HA_open). In this universe every trend-continuation control anti-selects for
long entries (rsi_strong/above_sma200/golden_cross/donchian_high/stoch_ob all NW-negative — see
nw_broad_sweep.out), while persisting dislocations (oversold, below-MA, below-cloud) carry the
edge. So the deployed HA shape is a prime "trend control -> expect negative" candidate, and the
HA reversal/dislocation variants (consecutive red runs, flip-up after reds) are the buried-edge
suspects. This screen tests BOTH families through identical machinery.

Two implementation subtlety being audited:
  TRUE HA open is recursive:  HA_open[t] = (HA_open[t-1]+HA_close[t-1])/2  (the smoother).
  PRODUCTION open is one-step: HA_open[t] = (open[t-1]+close[t-1])/2       (NOT smoothed).
We test the true recursive HA, plus a *_PROD variant of the deployed 3-green signal so we can see
whether the deployed approximation even matches the genuine indicator.

Machinery byte-identical to clean_harness.py PASS 2 / nw_broad_sweep.py: bracket TP2:SL1 hold10,
vol floor, $-vol floor, gap-skip path, symbol-cluster, NW Bartlett L=BR_N-1, demean vs same-regime
random. NOT a deploy test — anything positive gets the full year-stability + cost + overlap follow-up.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; DOLLAR_VOL=1_000_000; GAP=0.50
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

def shift(a,k):
    out=np.full(len(a),np.nan)
    if k<len(a): out[k:]=a[:-k]
    return out

B={}
def bumpB(k,lift,nt):
    a=B.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
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
def noov(mask,res,N):
    out=[];u=-1
    for i in np.where(mask&~np.isnan(res))[0]:
        if i<=u: continue
        out.append(i); u=i+N
    return out

GROUPS=[
 ("ANCHOR (known +)",          ["rsi_oversold"]),
 ("HA trend-continuation",     ["ha_green","ha_2green","ha_3green","ha_3green_PROD","ha_strong_green"]),
 ("HA reversal (suspect +)",   ["ha_flip_up","ha_flip_after_3red","ha_flip_after_5red"]),
 ("HA dislocation (suspect +)",["ha_red","ha_3red","ha_redrun5","ha_redrun8","ha_strong_red"]),
 ("RANDOM",                    ["RANDOM"]),
]
ALL_SIGS=[s for _,ss in GROUPS for s in ss]

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

    # --- True recursive Heiken-Ashi ---
    ha_close=(o+h+l+c)/4.0
    ha_open=np.empty(n); ha_open[0]=(o[0]+c[0])/2.0
    redrun=np.zeros(n,int)
    for t in range(1,n):
        ha_open[t]=(ha_open[t-1]+ha_close[t-1])/2.0
    ha_high=np.maximum.reduce([h,ha_open,ha_close]); ha_low=np.minimum.reduce([l,ha_open,ha_close])
    green=ha_close>ha_open; red=ha_close<ha_open
    for t in range(1,n):
        redrun[t]=redrun[t-1]+1 if red[t] else 0
    # no lower wick (strong bull) / no upper wick (strong bear)
    nolow=np.abs(ha_low-ha_open)<1e-9
    noup =np.abs(ha_high-ha_open)<1e-9
    gp=shift(green.astype(float),1); gp2=shift(green.astype(float),2)
    rp=shift(red.astype(float),1); rp2=shift(red.astype(float),2); rp3=shift(red.astype(float),3)
    rp4=shift(red.astype(float),4)
    # production (non-recursive) HA open for deployed-signal audit
    ha_open_prod=(shift(o,1)+shift(c,1))/2.0
    green_prod=ha_close>ha_open_prod
    gpp=shift(green_prod.astype(float),1); gpp2=shift(green_prod.astype(float),2)

    SIG={
      "rsi_oversold": rsi<30,
      "ha_green": green,
      "ha_2green": green&(gp==1),
      "ha_3green": green&(gp==1)&(gp2==1),
      "ha_3green_PROD": green_prod&(gpp==1)&(gpp2==1),
      "ha_strong_green": green&nolow,
      "ha_flip_up": green&(rp==1),
      "ha_flip_after_3red": green&(rp==1)&(rp2==1)&(rp3==1),
      "ha_flip_after_5red": green&(rp==1)&(rp2==1)&(rp3==1)&(rp4==1)&(shift(red.astype(float),5)==1),
      "ha_red": red,
      "ha_3red": red&(rp==1)&(rp2==1),
      "ha_redrun5": redrun>=5,
      "ha_redrun8": redrun>=8,
      "ha_strong_red": red&noup,
      "RANDOM": np.ones(n,bool),
    }

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
        for sname in ALL_SIGS:
            smask=np.asarray(SIG[sname],bool)&base
            ent=noov(smask,res,BR_N)
            if ent: bumpB((sname,rk), float(np.mean([res[i] for i in ent])-bmean), len(ent))
            fidx=np.where(smask)[0]
            if len(fidx)>=5:
                bumpF((sname,rk), float(res[fidx].mean()-bmean), len(fidx))
                u=np.zeros(n); u[fidx]=res[fidx]-bmean
                bumpNW((sname,rk), u, len(fidx))

def stC(store,k,minsym=30):
    a=store.get(k)
    if not a or a[2]<minsym: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt
def stNW(k,minfire=50):
    a=NW.get(k)
    if a is None or a[1]<minfire: return None
    S,M=a[0],a[1]; G=a[2:]; varS=G[0]+2.0*float(np.dot(NW_W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)

print("\n################ HEIKEN-ASHI DEEP DIVE — DE-OVERLAP vs FULL-POP vs NEWEY-WEST ################")
print(f"  bracket TP{TP_ATR:.0f}:SL{SL_ATR:.0f} hold{BR_N}, vol_floor {VOL_FLOOR}, $vol>={DOLLAR_VOL:,}")
print("  Deployed shape = ha_3green (trend-continuation). ha_3green_PROD = production non-recursive open.")
print("  FLAG ▲ = buried-edge signature (de-overlap<=0 AND NW>0 t>=3).")
for rk in ("nonbull","all"):
    print(f"\n  ===================== regime={rk} =====================")
    print(f"    {'signal':20} {'DE-OVERLAP':>20} {'FULL-POP(clus)':>18} {'NEWEY-WEST':>22}  flag")
    for gname,sigs in GROUPS:
        print(f"   -- {gname} --")
        for sname in sigs:
            b=stC(B,(sname,rk)); ff=stC(BF,(sname,rk)); nw=stNW((sname,rk))
            c1=f"{b[0]:+.3f}R t{b[1]:+.1f}" if b else "(thin)"
            c2=f"{ff[0]:+.3f}R t{ff[1]:+.1f}" if ff else "(thin)"
            c3=f"{nw[0]:+.3f}R t{nw[1]:+.1f} n{nw[2]}" if nw else "(thin)"
            flag=""
            if nw and b and b[0]<=0.0 and nw[0]>0 and nw[1]>=3.0: flag="▲ buried?"
            print(f"    {sname:20} {c1:>20} {c2:>18} {c3:>22}  {flag}")
print("\ndone.")
