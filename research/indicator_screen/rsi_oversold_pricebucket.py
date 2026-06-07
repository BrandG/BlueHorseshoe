"""Price-ceiling sensitivity for the DEPLOYED deep-oversold sleeve.

Question: the +0.142R edge was validated on a $5-$500 price band (see
rsi_oversold_production.py:22). If we raise MAX_STOCK_PRICE to $1000 (now that
fractional shares let us position in pricey names), do the *new* $500-$1000 names
the sleeve would take carry the same edge — or do they dilute it?

Method mirrors rsi_oversold_production.py (symbol-clustered, buy-if-flat / hold N,
2:1 ATR bracket) but uses the DEPLOYED sleeve's real gates instead of the looser
research ones, so the answer applies to what we'd actually trade:
  * liquidity = 20d avg DOLLAR-volume >= $25M  (DEEP_OVERSOLD_MIN_DOLLAR_VOLUME)
  * depth     = oversold age >= 3 consecutive bars (DEEP_OVERSOLD_MIN_AGE)
  * bracket   = 2:1 ATR, hold 10, close-entry (selection-alpha proxy; no frictions,
                so absolute R here is the IDEAL number, not the cost-stressed +0.142 —
                what matters is the bucket-vs-bucket COMPARISON, held to one method)
Partitions oversold-if-flat entries by price bucket; reports, per bucket x regime:
  abs R (clustered) | random-in-bucket R | selection alpha (os - rnd) | #trades | #syms
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; START="2016-01-01"
DVOL_MIN=25_000_000.0; VOL_FLOOR=0.005          # deployed liquidity + degenerate-ATR guard
OS=30.0; MIN_AGE=3; N=10; TP_ATR,SL_ATR=2.0,1.0 # deployed depth + bracket
MIN_SYM=20                                       # clustered: need >= this many symbols in a cell
BUCKETS=[("$5-500 (validated)",5.0,500.0),
         ("$500-750 (new)",500.0,750.0),
         ("$750-1000 (new)",750.0,1000.0),
         ("$500-1000 (new, all)",500.0,1000.0)]

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
print(f"{len(syms)} symbols (full universe), oversold=rsi<{OS:.0f} age>={MIN_AGE}, $vol>=${DVOL_MIN/1e6:.0f}M, hold {N}, {TP_ATR:.0f}:{SL_ATR:.0f}",flush=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg.get(str(d)[:10],False)

def bracket(h,l,c,atr,N,tp_atr,sl_atr):
    n=len(c); tp=c+tp_atr*atr; sl=c-sl_atr*atr; Rp=sl_atr*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan)
    valid=(np.arange(n)<(n-N))&(atr>0)&~np.isnan(atr)
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp[:n-k]; slh[:n-k]=l[k:]<=sl[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=tp_atr/sl_atr; resolved|=(loss|wn)
    ex=np.full(n,np.nan); ex[:n-N]=c[N:][:n-N] if n-N>0 else ex[:n-N]
    to=valid&~resolved; res[to]=(ex[to]-c[to])/Rp[to]
    return res,valid

def sim_entries(cand,elig,res,n):
    out=[]; in_until=-1
    idx=np.where(cand&elig&~np.isnan(res))[0]
    for i in idx:
        if i<=in_until: continue
        out.append(i); in_until=i+N
    return out

# clustered: key (bucket,regime,'os'/'rnd') -> per-symbol mean R: [sum, sumsq, nsym, ntrades]
acc={}
def bump(key,val,nt):
    a=acc.setdefault(key,[0.,0.,0,0]); a[0]+=val; a[1]+=val*val; a[2]+=1; a[3]+=nt

for ii,sym in enumerate(syms):
    if ii%500==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14)
    dvol20=pd.Series(c*v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan)
    liq=(dvol20>=DVOL_MIN)&(atr_pct>=VOL_FLOOR)
    bull=np.array([isbull(x) for x in dts])
    res,valid=bracket(h,l,c,atr,N,TP_ATR,SL_ATR)
    os=rsi<OS
    age=np.full(n,-1,int); run=0
    for i in range(n):
        if os[i]: age[i]=run; run+=1
        else: run=0
    os_deep=os&(age>=MIN_AGE)
    allbar=np.ones(n,bool)
    for rk,rmask in (("all",np.ones(n,bool)),("bull",bull),("nonbull",~bull)):
        for bname,lo,hi in BUCKETS:
            elig=liq&valid&~np.isnan(res)&(c>=lo)&(c<hi)&rmask
            if elig.sum()<1: continue
            ose=sim_entries(os_deep&rmask,elig,res,n)
            rne=sim_entries(allbar&rmask,elig,res,n)
            if ose: bump((bname,rk,"os"),  float(np.mean([res[i] for i in ose])), len(ose))
            if rne: bump((bname,rk,"rnd"), float(np.mean([res[i] for i in rne])), len(rne))

def stat(key):
    a=acc.get(key)
    if not a or a[2]<MIN_SYM: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt

print("\n#################### DEEP-OVERSOLD R BY PRICE BUCKET (clustered, ideal-bracket) ####################")
for rk in ("all","bull","nonbull"):
    print(f"\n=== regime: {rk} ===")
    print(f"  {'bucket':>22} | {'oversold absR':>20} | {'random-in-bucket':>18} | {'selection alpha':>16} | {'#syms':>6}")
    for bname,_,_ in BUCKETS:
        o=stat((bname,rk,"os")); r=stat((bname,rk,"rnd"))
        if not o:
            print(f"  {bname:>22} | {'(n<'+str(MIN_SYM)+' syms)':>20} |")
            continue
        alpha=f"{o[0]-r[0]:+.3f}R" if r else "(no rnd)"
        rnd=f"{r[0]:+.3f}R" if r else "  —"
        print(f"  {bname:>22} | {o[0]:+.3f}R t={o[1]:+.1f} nt={o[3]:>5} | {rnd:>18} | {alpha:>16} | {o[2]:>6}")
print("\n  READ: if $500-1000 'oversold absR' and 'selection alpha' match $5-500 (and #syms is non-trivial),")
print("        raising MAX_STOCK_PRICE adds real candidates that carry the edge. If absR collapses or alpha")
print("        goes <=0 (just beta), keep the $500 ceiling. nt=#trades across all symbols in the cell.")
