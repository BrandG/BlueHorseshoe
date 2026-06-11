"""PROTOTYPE earnings ingestion + event-alignment, small batch — de-risk before the full ~2k pull.

Checks: (1) AV EARNINGS coverage on liquid + delisted/renamed names (survivorship); (2) my reportedDate +
reportTime -> reaction-day alignment is CORRECT (earnings reaction days must show a clear |gap|/|return|
spike vs baseline — if not, the mapping is off-by-one); (3) usable sample sizes inside DeepOS (oversold bars
within K days of / after an earnings). Caches AV pulls to JSON so this is repeatable without re-hitting AV.
"""
import os, json, time, urllib.request, numpy as np, pandas as pd, talib, duckdb

LIVE=["AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","NFLX","AMD","CRM",
      "JPM","WMT","DIS","BA","INTC","MU","PYPL","ROKU","SHOP","ZM"]
DELISTED=["TWTR","ATVI","SIVB","FRC","FB"]   # taken-private / acquired / failed / renamed
BATCH=LIVE+DELISTED
CACHE="research/indicator_screen/earnings_cache_proto.json"
KEY=os.environ.get("ALPHAVANTAGE_KEY")

def fetch_earnings(sym):
    url=f"https://www.alphavantage.co/query?function=EARNINGS&symbol={sym}&apikey={KEY}"
    raw=urllib.request.urlopen(url,timeout=30).read().decode()
    d=json.loads(raw)
    gate=[d[k] for k in ("Note","Information","Error Message") if k in d]
    return d.get("quarterlyEarnings",[]), (gate[0][:120] if gate else None)

# ---- 1. fetch (cached), respect CPS=2 ----
if os.path.exists(CACHE):
    cache=json.load(open(CACHE)); print(f"loaded cache ({len(cache)} syms)")
else:
    cache={}
for s in BATCH:
    if s in cache: continue
    try:
        qe,gate=fetch_earnings(s)
        cache[s]={"qe":qe,"gate":gate}
        print(f"  fetched {s}: {len(qe)} rows{' GATE:'+gate if gate else ''}",flush=True)
    except Exception as e:
        cache[s]={"qe":[],"gate":f"ERR {e}"}; print(f"  {s} ERROR {e}")
    time.sleep(0.6)
json.dump(cache,open(CACHE,"w"))

print("\n################ 1. COVERAGE ################")
print(f"  {'sym':6} {'rows':>5} {'>=2016':>7} {'range':>25} {'noEst':>6} {'reportTime':>22}")
for s in BATCH:
    qe=cache[s]["qe"]
    if not qe:
        print(f"  {s:6} {'0':>5}  -- GATE/EMPTY: {cache[s]['gate']}"); continue
    post=[r for r in qe if r.get("reportedDate","")>="2016-01-01"]
    noest=sum(1 for r in post if r.get("estimatedEPS") in (None,"None","") )
    rng=f"{qe[-1].get('reportedDate')}..{qe[0].get('reportedDate')}"
    from collections import Counter
    rt=Counter(r.get("reportTime","?") for r in post)
    tag="DELISTED" if s in DELISTED else ""
    print(f"  {s:6} {len(qe):>5} {len(post):>7} {rng:>25} {noest:>6} {str(dict(rt)):>22} {tag}")

# ---- 2. ALIGNMENT validation: reaction day must show |gap|/|ret| spike ----
con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
def trading(sym):
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>='2016-01-01' ORDER BY date",[sym]).df()
    return d
def reaction_indices(dts, qe):
    """map each reportedDate(+reportTime) to the trading-day index of first market reaction."""
    out=[]
    for r in qe:
        D=r.get("reportedDate")
        if not D or D<dts[0] or D>dts[-1]: continue
        pre = (r.get("reportTime","")=="pre-market")
        # pre-market: react on first trading day >= D ; else (post/unknown): first trading day > D
        idx=np.searchsorted(dts, D, side=("left" if pre else "right"))
        if 0<=idx<len(dts): out.append((idx, r))
    return out

print("\n################ 2. EVENT ALIGNMENT (|overnight gap| & |day return| on reaction vs baseline) ################")
print("  Correct alignment => reaction-day medians are MULTIPLES of baseline. (post-market reacts D+1, pre-market D)")
for s in ["AAPL","NVDA","ROKU","NFLX"]:
    d=trading(s)
    if d.empty: print(f"  {s}: no OHLCV"); continue
    dts=d.date.astype(str).str[:10].to_numpy(); o=d.open.to_numpy(float); c=d.close.to_numpy(float); n=len(c)
    gap=np.full(n,np.nan); gap[1:]=np.abs(o[1:]/c[:-1]-1.0)
    ret=np.full(n,np.nan); ret[1:]=np.abs(c[1:]/c[:-1]-1.0)
    react=reaction_indices(dts, cache[s]["qe"])
    ridx=np.array([i for i,_ in react])
    mask=np.zeros(n,bool); mask[ridx]=True
    base=~mask & ~np.isnan(gap)
    mg_r=np.nanmedian(gap[ridx]); mg_b=np.nanmedian(gap[base]); mr_r=np.nanmedian(ret[ridx]); mr_b=np.nanmedian(ret[base])
    print(f"  {s:6} events={len(ridx):>3} | med|gap| react {mg_r*100:5.2f}% vs base {mg_b*100:4.2f}% ({mg_r/mg_b:4.1f}x) "
          f"| med|ret| react {mr_r*100:5.2f}% vs base {mr_b*100:4.2f}% ({mr_r/mr_b:4.1f}x)")

# ---- 3. usable n inside DeepOS for these names ----
print("\n################ 3. DeepOS x earnings sample sizes (batch, $1M+ liquid, nonbull-agnostic) ################")
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>='2016-01-01' ORDER BY date").df()
tot=dict(deepos=0, e_next5=0, e_prior5_miss=0, e_prior5_beat=0, e_none10=0)
for s in BATCH:
    d=trading(s)
    if len(d)<300: continue
    dts=d.date.astype(str).str[:10].to_numpy(); c=d.close.to_numpy(float); n=len(c)
    rsi=talib.RSI(c,14); osr=rsi<30; age=np.zeros(n,int)
    for i in range(1,n): age[i]=age[i-1]+1 if osr[i] else 0
    deepos=osr&(age>=3)
    react=reaction_indices(dts, cache[s]["qe"])
    # next/prior earnings reaction index per bar
    ridx=sorted(i for i,_ in react); surby={i:r for i,r in react}
    nextarr=np.full(n,10**9); priorarr=np.full(n,10**9); prior_surp=np.full(n,np.nan)
    j=0; last=-10**9; last_s=np.nan
    rset=set(ridx)
    # days since last
    for i in range(n):
        if i in rset: last=i; last_s=float(surby[i].get("surprise") or "nan") if surby[i].get("surprise") not in (None,"None","") else np.nan
        priorarr[i]=i-last; prior_surp[i]=last_s
    # days to next
    nxt=10**9
    for i in range(n-1,-1,-1):
        if i in rset: nxt=0
        else: nxt=nxt+1 if nxt<10**9 else 10**9
        # recompute cleanly: distance to next reaction >= i
        nextarr[i]=min((r-i for r in ridx if r>=i), default=10**9)
    dp=np.where(deepos)[0]
    tot["deepos"]+=len(dp)
    tot["e_next5"]+=int(np.sum(nextarr[dp]<=5))
    tot["e_none10"]+=int(np.sum((nextarr[dp]>10)&(priorarr[dp]>10)))
    pm=dp[(priorarr[dp]<=5)]
    tot["e_prior5_miss"]+=int(np.sum(prior_surp[pm]<0))
    tot["e_prior5_beat"]+=int(np.sum(prior_surp[pm]>=0))
print(f"  batch DeepOS bars: {tot['deepos']}")
print(f"   - earnings within NEXT 5d (proximity-filter target): {tot['e_next5']} ({100*tot['e_next5']/max(tot['deepos'],1):.1f}%)")
print(f"   - no earnings +/-10d (clean dislocation):            {tot['e_none10']} ({100*tot['e_none10']/max(tot['deepos'],1):.1f}%)")
print(f"   - earnings in PRIOR 5d & MISS (knife candidate):     {tot['e_prior5_miss']}")
print(f"   - earnings in PRIOR 5d & BEAT:                       {tot['e_prior5_beat']}")
print("\ndone.")
