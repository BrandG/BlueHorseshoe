"""RSI-oversold, measured the way we'd actually TRADE it — Brand's correction.

The prior gauntlet conflated two things: (a) overlapping forward windows inflate the t-stat
[real], and (b) restricting to the FIRST bar of each oversold run changes the point estimate
[a population choice, NOT a stats fix]. Episode-start keeps only the onset bar — the worst entry
of the run (farthest from the bounce). That's biased against this signal.

This script measures the PRODUCTION population instead: walk each symbol forward, and "buy when
oversold AND flat, hold N days" — exactly how the live system would use it (every day, one
position per symbol, no stacking). Error bars are symbol-CLUSTERED (honest about overlap) but we
DON'T throw away the good bars. Three views:

  VIEW 1 - Production simulation: oversold-if-flat vs random-if-flat, same spacing. Clustered t.
  VIEW 2 - Edge by oversold AGE (onset / 1-2 / 3-5 / 6+ bars below 30): does the edge live deeper
           in the run? If yes, onset-only de-overlap was throwing away the edge.
  VIEW 3 - Time-split, reported as REGIME-DEPENDENCE (not pass/fail). Same-sign => robust;
           sign-flip => regime-conditional (deployable behind a regime filter, per project norms).
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"; SPLIT="2021-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; N=10; TP_ATR,SL_ATR=2.0,1.0; MIN_BASE=15

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg.get(str(d)[:10],False)
print(f"{len(syms)} symbols, oversold=rsi<{OS:.0f}, hold N={N}, bracket {TP_ATR:.0f}:{SL_ATR:.0f}",flush=True)

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
    """Walk forward: take a candidate bar if eligible & flat; then block re-entry for N bars."""
    out=[]; in_until=-1
    idx=np.where(cand&elig&~np.isnan(res))[0]
    for i in idx:
        if i<=in_until: continue
        out.append(i); in_until=i+N
    return out

# clustered accumulators: key -> [sumLift, sumsqLift, n_sym, n_trades]
acc={}
def bump(key,lift,nt):
    a=acc.setdefault(key,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
# age-bucket accumulator: key -> [sumR, n] per symbol then cluster -> store per-symbol mean lift
age_acc={}
def bump_age(bucket,reg,lift,nt):
    a=age_acc.setdefault((bucket,reg),[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt

AGE_BUCKETS=[("onset(0)",0,0),("1-2",1,2),("3-5",3,5),("6+",6,9999)]

for ii,sym in enumerate(syms):
    if ii%300==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    bull=np.array([isbull(x) for x in dts]); h1=dts<SPLIT
    res,valid=bracket(h,l,c,atr,N,TP_ATR,SL_ATR); ok=elig&valid&~np.isnan(res)
    os=rsi<OS

    # oversold run age (bars since RSI crossed below OS)
    age=np.full(n,-1,int); run=0
    for i in range(n):
        if os[i]: age[i]=run; run+=1
        else: run=0

    # random candidate mask (matched count handled by sim spacing): every bar is a candidate
    allbar=np.ones(n,bool)

    for rk,rmask in (("all",np.ones(n,bool)),("bull",bull),("nonbull",~bull)):
        base=ok&rmask
        if base.sum()<MIN_BASE: continue
        bmean=res[base].mean()
        # VIEW 1: production sim. oversold-if-flat vs random-if-flat (regime-restricted candidates)
        os_entries=sim_entries(os&rmask,elig,res,n)
        rnd_entries=sim_entries(allbar&rmask,elig,res,n)
        if os_entries:
            bump(("prod_os",rk), np.mean([res[i] for i in os_entries])-bmean, len(os_entries))
        if rnd_entries:
            bump(("prod_rnd",rk), np.mean([res[i] for i in rnd_entries])-bmean, len(rnd_entries))
        # VIEW 2: edge by oversold age (ALL oversold bars, bucketed; lift vs same-regime baseline)
        for bname,lo,hi in AGE_BUCKETS:
            m=base&os&(age>=lo)&(age<=hi)
            if m.any(): bump_age(bname,rk, res[m].mean()-bmean, int(m.sum()))
        # VIEW 3: time-split on production-os entries
        for half,hm in (("H1",h1),("H2",~h1)):
            bh=ok&rmask&hm
            if bh.sum()<MIN_BASE: continue
            ent=[i for i in os_entries if hm[i]]
            if ent: bump(("split",rk,half), np.mean([res[i] for i in ent])-res[bh].mean(), len(ent))

def stat(key,store=acc):
    a=store.get(key)
    if not a or a[2]<30: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt

print("\n############### VIEW 1: production sim (buy-if-flat, hold N), symbol-clustered ###############")
print("  How the live system would actually trade it: every day, oversold & not already holding -> buy.")
print(f"  {'regime':>8} | {'oversold lift vs random':>26} | {'(sanity) random-vs-uncond':>26}")
for rk in ("all","bull","nonbull"):
    o=stat(("prod_os",rk)); r=stat(("prod_rnd",rk))
    def f(x): return f"{x[0]:+.4f}R t={x[1]:+.1f} nt={x[3]}" if x else "(n<30)"
    print(f"  {rk:>8} | {f(o):>26} | {f(r):>26}")

print("\n############### VIEW 2: edge by oversold AGE (does edge live deeper in the run?) ###############")
print(f"  {'age (bars<30)':>13} | " + " | ".join(f"{rk:>20}" for rk in ("all","bull","nonbull")))
for bname,_,_ in AGE_BUCKETS:
    cells=[]
    for rk in ("all","bull","nonbull"):
        x=stat((bname,rk),store=age_acc)
        cells.append(f"{x[0]:+.4f}R t={x[1]:+.1f}" if x else "(n<30)")
    print(f"  {bname:>13} | " + " | ".join(f"{c:>20}" for c in cells))
print("  [rising left->right within a regime => edge builds with oversold depth; onset is the worst entry]")

print("\n############### VIEW 3: time-split (regime-dependence, NOT pass/fail) ###############")
print(f"  {'regime':>8} | {'H1 (2016-20)':>22} | {'H2 (2021-26)':>22}  read")
for rk in ("all","bull","nonbull"):
    h1r=stat(("split",rk,"H1")); h2r=stat(("split",rk,"H2"))
    def f(x): return f"{x[0]:+.4f}R t={x[1]:+.1f}" if x else "(n<30)"
    if h1r and h2r:
        same=np.sign(h1r[0])==np.sign(h2r[0])
        read="robust (same sign)" if same else "regime-conditional (flips)"
    else: read="(thin)"
    print(f"  {rk:>8} | {f(h1r):>22} | {f(h2r):>22}  {read}")
