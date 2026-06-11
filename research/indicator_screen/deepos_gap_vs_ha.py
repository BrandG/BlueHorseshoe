"""Does DeepOS+HA already avoid the gap-down knives, or does the gap filter still help it?

From [[project_deepos_volume_conditioner]] overlap test: gap_down is the dominant knife in BARE DeepOS
(-0.39R nonbull), and excluding it lifts the bare sleeve +0.049R. But the live sleeve is DeepOS+HA
(deepos & true-recursive HA-green). Hypothesis: a 3% down-gap that CLOSES STRONG (washout+recover) is
HA-GREEN, while one that gaps down and stays weak is HA-RED — so HA-green already keeps the recovered
gap-downs and drops the knives, making a blanket gap filter redundant/harmful for the HA sleeve.

Cells on DeepOS base (rsi<30 age>=3), demean vs same-regime random; n shows coverage/overlap. Decisive:
  hg_&_gapdown   vs  hared_&_gapdown  -> does HA-green RESCUE gap-downs? (green not-very-neg, red very-neg)
  hg_&_nogap     vs  ha_green(sleeve) -> does the gap filter still LIFT the HA sleeve? (compare to bare lift)
NW harness; sample PINNED (ORDER BY symbol) so absolute R is stable. $1M+$25M, holds{10,20}.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; GAP=0.50; TP_ATR,SL_ATR=2.0,1.0; HOLDS=(10,20)
TIERS={"$1M":1_000_000,"$25M":25_000_000}
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg_map.get(str(d)[:10],False)
# PINNED sample: ORDER BY symbol before choice (fixes cross-script wobble)
syms=con.execute("""SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300 ORDER BY symbol""",[START]).df().symbol.tolist()
syms=[s for s in syms if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=sorted(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"{len(syms)} symbols (PINNED); DeepOS gap_down vs HA-green",flush=True)

def shift(a,k):
    out=np.full(len(a),np.nan)
    if k<len(a): out[k:]=a[:-k]
    return out
BF={}; NW={}
def bumpF(k,lift,nt):
    a=BF.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
def make_w(L): return np.array([1.0-j/(L+1) for j in range(L+1)])
def bumpNW(k,u,m,L):
    a=NW.setdefault(k,np.zeros(3+30)); a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    for j in range(1,L+1): a[2+j]+=float(u[:-j]@u[j:])
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
    os=rsi<30; age=np.zeros(n,int)
    for i in range(1,n): age[i]=age[i-1]+1 if os[i] else 0
    deepos=os&(age>=3)
    prevc=shift(c,1); gapdown=o<prevc*0.97
    hac=(o+h+l+c)/4.0; hao=np.empty(n); hao[0]=(o[0]+c[0])/2
    for i in range(1,n): hao[i]=(hao[i-1]+hac[i-1])/2
    hg=hac>hao   # HA-green (recursive) = the deployed DeepOS+HA condition
    COND={
      "deepos(base)":np.ones(n,bool),
      "gapdown":gapdown, "no_gapdown":~gapdown,
      "ha_green(sleeve)":hg, "ha_red":~hg,
      "hg_&_gapdown":hg&gapdown, "hg_&_nogap":hg&~gapdown,
      "hared_&_gapdown":(~hg)&gapdown,
    }
    base_ok=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(o>0)&(h>0)&(l>0)&(atr_pct>=VOL_FLOOR)
    for tname,tfloor in TIERS.items():
        elig=base_ok&(dollar>=tfloor)
        for BR_N in HOLDS:
            L=BR_N-1
            badpathB=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
            for t in range(n-BR_N):
                if cs[t+BR_N+1]-cs[t+1]>0: badpathB[t]=True
            res,valid=bracket(h,l,c,atr,BR_N,TP_ATR,SL_ATR,badpathB)
            ok=elig&valid&~np.isnan(res)
            for rk,rmask in (("nonbull",nonbull),("all",np.ones(n,bool))):
                bse=ok&rmask
                if bse.sum()<20: continue
                bmean=res[bse].mean()
                rfi=np.where(bse)[0]
                if len(rfi)>=50:
                    u=np.zeros(n); u[rfi]=res[rfi]-bmean; bumpNW(("RANDOM",tname,rk,BR_N),u,len(rfi),L)
                dp=deepos&bse
                for cname,craw in COND.items():
                    smask=dp&np.asarray(craw,bool)
                    fidx=np.where(smask)[0]
                    if len(fidx)>=5:
                        bumpF((cname,tname,rk,BR_N),float(res[fidx].mean()-bmean),len(fidx))
                        u=np.zeros(n); u[fidx]=res[fidx]-bmean; bumpNW((cname,tname,rk,BR_N),u,len(fidx),L)

def stNW(k,minfire=30):
    a=NW.get(k)
    if a is None or a[1]<minfire: return None
    L=k[3]-1 if isinstance(k[3],int) else 9; W=make_w(L)
    S,M=a[0],a[1]; G=a[2:2+1+L]; varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def fmt(cname,tn,rk,BR_N,base_nw,sleeve_nw):
    nw=stNW((cname,tn,rk,BR_N))
    c3=f"{nw[0]:+.3f}R t{nw[1]:+.1f} n{nw[2]}" if nw else "(thin)"
    ex=""
    if nw and cname=="no_gapdown" and base_nw is not None: ex=f"   bare gap-filter lift {nw[0]-base_nw:+.3f}"
    if nw and cname=="hg_&_nogap" and sleeve_nw is not None: ex=f"   HA gap-filter lift {nw[0]-sleeve_nw:+.3f}"
    if nw and cname=="ha_green(sleeve)" and base_nw is not None: ex=f"   HA lift over base {nw[0]-base_nw:+.3f}"
    return f"    {cname:18} {c3:>24}{ex}"
ORDER=["deepos(base)","gapdown","no_gapdown","ha_green(sleeve)","ha_red","hared_&_gapdown",
       "hg_&_gapdown","hg_&_nogap","RANDOM"]

print("\n################ DeepOS: gap_down vs HA-green (does the HA sleeve already dodge the gaps?) ################")
print("  RESCUE if hg_&_gapdown >> hared_&_gapdown. REDUNDANT-for-HA if HA gap-filter lift ~0 while bare lift >0.")
for tn in TIERS:
    for BR_N in HOLDS:
        for rk in ("nonbull","all"):
            bnw=stNW(("deepos(base)",tn,rk,BR_N)); base_nw=bnw[0] if bnw else None
            snw=stNW(("ha_green(sleeve)",tn,rk,BR_N)); sleeve_nw=snw[0] if snw else None
            print(f"\n  ===== tier={tn} hold{BR_N} regime={rk} =====")
            for cn in ORDER: print(fmt(cn,tn,rk,BR_N,base_nw,sleeve_nw))
print("\ndone.")
