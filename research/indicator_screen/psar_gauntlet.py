"""PSAR full gauntlet — time-split + cost + incremental-over-trend-events.

Signal = PSAR flip-up (close crosses above SAR). Clean harness throughout:
ATR 2:1 runner, vol floor 0.5%, episode-start de-overlap, symbol-clustered stats.

SECTION A (time-split + cost): the two configs that showed life --
  flip(0.01,0.2) in NONBULL ; flip(0.04,0.4) in ALL regime.
  Per half (2016-20 / 2021-26) x cost (0/5/10/20 bps): NET abs expectancy + NET lift vs random.
  Survives only if positive & significant in BOTH halves after realistic cost.

SECTION B (incremental over trend-event cluster-mates, nonbull, af 0.01):
  trend_event = sma50_reclaim OR donchian20_break OR macd_bull_cross.
  raw flip / flip&TE / flip&~TE / TE-alone. If flip&~TE ~ raw -> PSAR is incremental
  (adds beyond the trend events); if it collapses -> redundant with them.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"; SPLIT="2021-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
N=10; TP_ATR,SL_ATR=2.0,1.0; MIN_BASE=15; COSTS=[0,5,10,20]

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg.get(str(d)[:10],False)
print(f"{len(syms)} symbols",flush=True)

def cross_up(a,b):
    out=np.zeros(len(a),bool); out[1:]=(a[1:]>b[1:])&(a[:-1]<=b[:-1]); return out
def estart(m): return m&~np.concatenate([[False],m[:-1]])
def shift1(a,k=1):
    out=np.full(len(a),np.nan); out[k:]=a[:-k]; return out
def bracket(h,l,c,atr):
    n=len(c); tp=c+TP_ATR*atr; sl=c-SL_ATR*atr; Rp=SL_ATR*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan); valid=(np.arange(n)<(n-N))&(atr>0)&~np.isnan(atr)
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp[:n-k]; slh[:n-k]=l[k:]<=sl[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=TP_ATR/SL_ATR; resolved|=(loss|wn)
    ex=np.full(n,np.nan); ex[:n-N]=c[N:][:n-N] if n-N>0 else ex[:n-N]
    to=valid&~resolved; res[to]=(ex[to]-c[to])/Rp[to]
    return res,valid

# accumulators
accA={}  # (cfg,half,cost) -> sums for abs + lift
def bumpA(cfg,half,cost,aexp,lift,ne):
    k=(cfg,half,cost); a=accA.get(k)
    if a is None: accA[k]=a=[0.,0.,0.,0.,0,0]  # sumAbs,sumsqAbs,sumLift,sumsqLift,nsym,nep
    a[0]+=aexp;a[1]+=aexp*aexp;a[2]+=lift;a[3]+=lift*lift;a[4]+=1;a[5]+=ne
accB={}
def bumpB(tag,lift,ne):
    a=accB.get(tag)
    if a is None: accB[tag]=a=[0.,0.,0,0]
    a[0]+=lift;a[1]+=lift*lift;a[2]+=1;a[3]+=ne

for i,sym in enumerate(syms):
    if i%300==0: print(f"  {i}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    bull=np.array([isbull(x) for x in dts]); h1=dts<SPLIT
    res,valid=bracket(h,l,c,atr); base0=elig&valid&~np.isnan(res)
    flip01=estart(c>talib.SAR(h,l,0.01,0.2)); flip04=estart(c>talib.SAR(h,l,0.04,0.4))

    # SECTION A
    A=[("flip01_nonbull",flip01,~bull),("flip04_all",flip04,np.ones(n,bool))]
    for cfg,flip,rmask in A:
        for half,hm in (("H1",h1),("H2",~h1)):
            b=base0&rmask&hm; s=flip&b; ne=int(s.sum())
            if ne<1 or int(b.sum())<MIN_BASE: continue
            for cb in COSTS:
                cR=(cb/10000.0)/atr_pct
                bexp=(res[b]-cR[b]).mean(); sexp=(res[s]-cR[s]).mean()
                bumpA(cfg,half,cb,sexp,sexp-bexp,ne)

    # SECTION B (nonbull, af01, gross)
    sma50=talib.SMA(c,50); macd,sig,_=talib.MACD(c,12,26,9)
    prior20hi=shift1(pd.Series(h).rolling(20).max().to_numpy())
    TE=cross_up(c,sma50)|cross_up(c,prior20hi)|cross_up(macd,sig)
    bnb=base0&~bull
    if bnb.sum()>=MIN_BASE:
        bmean=res[bnb].mean()
        for tag,m in (("raw_flip",flip01),("flip&TE",flip01&TE),
                      ("flip&~TE",flip01&~TE),("TE_alone",estart(TE))):
            s=estart(m)&bnb; ne=int(s.sum())
            if ne>=1: bumpB(tag,res[s].mean()-bmean,ne)

def stat(arr,absidx=False):
    if absidx:
        s,ss,_,_,ns,ne=arr; m=s/ns; var=max(ss/ns-m*m,0)
    else:
        if len(arr)==6: _,_,s,ss,ns,ne=arr
        else: s,ss,ns,ne=arr
        m=s/ns; var=max(ss/ns-m*m,0)
    se=(var/ns)**0.5; return m,(m/se if se>0 else 0),ns,ne

print("\n################ SECTION A: time-split + cost ################")
for cfg in ("flip01_nonbull","flip04_all"):
    print(f"\n  === {cfg} ===")
    print(f"      {'half':>4} {'cost':>5} | {'NET abs exp':>15} | {'NET lift vs random':>20} | n_sym n_ep")
    for half in ("H1","H2"):
        for cb in COSTS:
            a=accA.get((cfg,half,cb))
            if not a or a[4]<30: print(f"      {half:>4} {cb:>3}bp | (n<30)"); continue
            am,at,ns,ne=stat(a,absidx=True); lm,lt,_,_=stat(a,absidx=False)
            print(f"      {half:>4} {cb:>3}bp | {am:+.4f}R(t={at:+.1f}) | {lm:+.4f}R(t={lt:+.1f}) | {ns} {ne}")

print("\n################ SECTION B: incremental over trend-events (nonbull, af01, gross) ################")
for tag in ("raw_flip","flip&TE","flip&~TE","TE_alone"):
    a=accB.get(tag)
    if not a or a[2]<30: print(f"  {tag:12} (n<30)"); continue
    m,t,ns,ne=stat(a); print(f"  {tag:12} lift={m:+.4f}R  t={t:+.1f}  n_sym={ns:<5} n_ep={ne}")
print("\n  (flip&~TE ~ raw_flip => PSAR edge is incremental to trend-events;")
print("   flip&~TE collapses => PSAR redundant with sma-reclaim/donchian/macd events)")
