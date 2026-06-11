"""PROTOTYPE fundamentals/quality ingestion + Piotroski F-score + PIT alignment — small batch.

De-risk before the ~3400-call full pull. Checks: (1) AV 3-statement coverage + F-score computes sensibly
(strong names high-F, distressed names low-F); (2) PIT alignment: fundamentals known as-of the earnings
reportedDate (no lookahead) — validate the fiscalDateEnding->reportedDate lag; (3) F-score VARIES across
DeepOS fires (so the conditioner has signal to split on). Caches AV pulls to JSON (repeatable).

F-score (9, binary), TTM flows + YoY-quarter (compare quarter i to i-4) to dodge seasonality:
 1 NI_ttm>0  2 OCF_ttm>0  3 dROA>0  4 OCF_ttm>NI_ttm (accrual)
 5 dLeverage<0 (debt/assets)  6 dCurrentRatio>0  7 no dilution (shares not up)
 8 dGrossMargin>0  9 dAssetTurnover>0
"""
import os, json, time, urllib.request, numpy as np, pandas as pd, talib, duckdb

BATCH=["AAPL","MSFT","JNJ","WMT",          # strong/profitable
       "BA","INTC","MU","F","GE",           # cyclical / once-troubled survivors
       "ROKU","SHOP","ZM","CVNA","PTON","RIVN",  # unprofitable growth / near-distress
       "SIVB"]                              # delisted (survivorship check)
CACHE="research/indicator_screen/fund_cache_proto.json"
KEY=os.environ.get("ALPHAVANTAGE_KEY")
def get(url):
    try: return json.loads(urllib.request.urlopen(url,timeout=30).read().decode())
    except Exception as e: return {"_err":str(e)}
def gate(d): return any(k in d for k in ("Note","Information","Error Message"))

cache=json.load(open(CACHE)) if os.path.exists(CACHE) else {}
for s in BATCH:
    if s in cache: continue
    rec={}
    for fn,key in [("INCOME_STATEMENT","inc"),("BALANCE_SHEET","bal"),("CASH_FLOW","cf"),("EARNINGS","earn")]:
        d=get(f"https://www.alphavantage.co/query?function={fn}&symbol={s}&apikey={KEY}")
        if gate(d): print(f"  GATE {s}/{fn}",flush=True)
        rec[key]=d.get("quarterlyReports", d.get("quarterlyEarnings",[]))
        time.sleep(0.55)
    cache[s]=rec; print(f"  fetched {s}: inc{len(rec['inc'])} bal{len(rec['bal'])} cf{len(rec['cf'])} earn{len(rec['earn'])}",flush=True)
json.dump(cache,open(CACHE,"w"))

def F(x):
    try: return float(x)
    except: return np.nan

def fscore_series(sym):
    """return list of (fiscalDateEnding, reportedDate, fscore, n_components_available)."""
    rec=cache[sym]
    if not rec["inc"]: return []
    inc={r["fiscalDateEnding"]:r for r in rec["inc"]}
    bal={r["fiscalDateEnding"]:r for r in rec["bal"]}
    cf ={r["fiscalDateEnding"]:r for r in rec["cf"]}
    rep={r["fiscalDateEnding"]:r.get("reportedDate") for r in rec["earn"]}
    qs=sorted(set(inc)&set(bal)&set(cf))   # quarters with all 3 statements, ascending
    NI=[F(inc[q].get("netIncome")) for q in qs]
    OCF=[F(cf[q].get("operatingCashflow")) for q in qs]
    REV=[F(inc[q].get("totalRevenue")) for q in qs]
    GP =[F(inc[q].get("grossProfit")) for q in qs]
    TA=[F(bal[q].get("totalAssets")) for q in qs]
    CA=[F(bal[q].get("totalCurrentAssets")) for q in qs]
    CL=[F(bal[q].get("totalCurrentLiabilities")) for q in qs]
    DEBT=[F(bal[q].get("shortLongTermDebtTotal")) for q in qs]
    SH=[F(bal[q].get("commonStockSharesOutstanding")) for q in qs]
    def ttm(arr,i):
        v=arr[i-3:i+1];
        return np.nan if any(np.isnan(v)) else sum(v)
    out=[]
    for i in range(len(qs)):
        if i<7: continue
        ni,ocf,rev,gp=ttm(NI,i),ttm(OCF,i),ttm(REV,i),ttm(GP,i)
        ni0,ocf0,rev0,gp0=ttm(NI,i-4),ttm(OCF,i-4),ttm(REV,i-4),ttm(GP,i-4)
        ta,ta0=TA[i],TA[i-4]
        comp=[]
        comp.append(ni>0); comp.append(ocf>0)
        comp.append((ni/ta) > (ni0/ta0) if ta and ta0 else np.nan)
        comp.append(ocf>ni)
        lev =DEBT[i]/ta if ta else np.nan; lev0=DEBT[i-4]/ta0 if ta0 else np.nan
        comp.append(lev<lev0)
        cr =CA[i]/CL[i] if CL[i] else np.nan; cr0=CA[i-4]/CL[i-4] if CL[i-4] else np.nan
        comp.append(cr>cr0)
        comp.append(SH[i]<=SH[i-4] if (not np.isnan(SH[i]) and not np.isnan(SH[i-4])) else np.nan)
        gm =gp/rev if rev else np.nan; gm0=gp0/rev0 if rev0 else np.nan
        comp.append(gm>gm0)
        at =rev/ta if ta else np.nan; at0=rev0/ta0 if ta0 else np.nan
        comp.append(at>at0)
        avail=[c for c in comp if not (isinstance(c,float) and np.isnan(c))]
        fs=sum(1 for c in avail if c is True)
        out.append((qs[i], rep.get(qs[i]), fs, len(avail)))
    return out

print("\n################ 1. COVERAGE + F-SCORE SANITY (recent quarters) ################")
print(f"  {'sym':6} {'q-all3':>6} {'scored':>6}   recent (fiscalEnd | reportedDate | F/avail)")
series={}
for s in BATCH:
    fss=fscore_series(s); series[s]=fss
    if not fss:
        print(f"  {s:6}  {'0':>6}  -- empty (delisted? {len(cache[s]['inc'])} inc rows)"); continue
    rec=cache[s]; q3=len(set(r['fiscalDateEnding'] for r in rec['inc'])&set(r['fiscalDateEnding'] for r in rec['bal'])&set(r['fiscalDateEnding'] for r in rec['cf']))
    tail=" ; ".join(f"{q[:7]}|{rd}|{fs}/{av}" for q,rd,fs,av in fss[-2:])
    print(f"  {s:6} {q3:>6} {len(fss):>6}   {tail}")

print("\n################ 2. PIT ALIGNMENT (reportedDate lag after fiscal end) ################")
lags=[]
for s in BATCH:
    for q,rd,fs,av in series.get(s,[]):
        if rd:
            try: lags.append((pd.to_datetime(rd)-pd.to_datetime(q)).days)
            except: pass
lags=np.array(lags)
if len(lags):
    print(f"  fiscalEnd->reportedDate lag: median {np.median(lags):.0f}d  p10 {np.percentile(lags,10):.0f}  p90 {np.percentile(lags,90):.0f}  (n={len(lags)})")
    print(f"  -> as-of date = reportedDate (PIT); using fundamentals only after this date avoids lookahead.")
missing_rd=sum(1 for s in BATCH for q,rd,fs,av in series.get(s,[]) if not rd)
print(f"  scored quarters with NO reportedDate match (need fallback): {missing_rd}")

print("\n################ 3. F-SCORE across DeepOS fires (does it VARY to split on?) ################")
con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
for s in ["INTC","BA","F","CVNA"]:
    fss=series.get(s,[])
    if not fss: print(f"  {s}: no fundamentals"); continue
    d=con.execute("SELECT date,close FROM ohlcv WHERE symbol=? AND date>='2016-01-01' ORDER BY date",[s]).df()
    if d.empty: print(f"  {s}: no OHLCV"); continue
    dts=d.date.astype(str).str[:10].to_numpy(); c=d.close.to_numpy(float); n=len(c)
    rsi=talib.RSI(c,14); osr=rsi<30; age=np.zeros(n,int)
    for i in range(1,n): age[i]=age[i-1]+1 if osr[i] else 0
    deepos=osr&(age>=3)
    # as-of F-score step series
    asof=sorted([(rd,fs) for q,rd,fs,av in fss if rd], key=lambda x:x[0])
    farr=np.full(n,np.nan); j=0; cur=np.nan
    for i in range(n):
        while j<len(asof) and asof[j][0]<=dts[i]: cur=asof[j][1]; j+=1
        farr[i]=cur
    dpf=farr[deepos]; dpf=dpf[~np.isnan(dpf)]
    if len(dpf):
        print(f"  {s:5} DeepOS fires={int(deepos.sum())} w/F={len(dpf)} | F mean {dpf.mean():.1f} min {dpf.min():.0f} max {dpf.max():.0f} | low(<=3) {100*np.mean(dpf<=3):.0f}% high(>=7) {100*np.mean(dpf>=7):.0f}%")
    else:
        print(f"  {s:5} DeepOS fires={int(deepos.sum())} but no F-score coverage at those bars")
print("\ndone.")
