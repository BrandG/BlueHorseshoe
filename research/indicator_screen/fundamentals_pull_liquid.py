"""One-time fundamentals coverage extension to the FULL liquid universe (deployment data prep).

The research pull covered a random pinned-2000 sample; only ~424 of those overlap the ~1,946 names that are
actually liquid enough ($25M/day) to be DeepOS candidates. This pulls earnings + 3 statements for the liquid
names not already cached, computes book Altman-Z'' per quarter aligned to the earnings reportedDate (PIT),
and (re)writes data/fundamentals.parquet covering research ∪ liquid. Seeding into prod is a SEPARATE brief
write step (does NOT hold the prod DB lock during this multi-thousand-call network pull).

Resumable: extends earnings_cache_full.json + fund_cache_full.json; restart skips cached names; stops on a
rate-storm. ~4 AV calls per new name (1 EARNINGS + 3 statements).
"""
import os, json, time, urllib.request, numpy as np, pandas as pd, duckdb

KEY=os.environ.get("ALPHAVANTAGE_KEY")
EARN_CACHE="research/indicator_screen/earnings_cache_full.json"
FUND_CACHE="research/indicator_screen/fund_cache_full.json"
OUT_PARQUET="data/fundamentals.parquet"
SLEEP=0.55; MAX_CONSEC_GATE=3
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
liquid=con.execute("""
    WITH recent AS (SELECT symbol, close*volume dv,
        ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) rn
        FROM ohlcv WHERE date >= '2026-04-01')
    SELECT symbol FROM (SELECT symbol, AVG(dv) adv FROM recent WHERE rn<=20 GROUP BY symbol HAVING adv>=25000000)
    ORDER BY symbol
""").df().symbol.tolist()
liquid=[s for s in liquid if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
print(f"liquid universe: {len(liquid)} names",flush=True)

ecache=json.load(open(EARN_CACHE)) if os.path.exists(EARN_CACHE) else {}
fcache=json.load(open(FUND_CACHE)) if os.path.exists(FUND_CACHE) else {}
print(f"caches: earnings {len(ecache)}, fundamentals {len(fcache)}",flush=True)

def get(url):
    raw=urllib.request.urlopen(url,timeout=30).read().decode()
    d=json.loads(raw)
    gate=[d[k] for k in ("Note","Information","Error Message") if k in d]
    return d, (gate[0][:160] if gate else None)
def is_rate(g): return g is not None and any(t in g.lower() for t in ("call frequency","premium","thank you for using","rate limit","higher api"))

todo=[s for s in liquid if s not in ecache or s not in fcache]
print(f"to fetch: {len(todo)} names (~{4*len(todo)} calls upper bound)",flush=True)
consec=0; n_e=0; n_f=0; t0=time.time(); stopped=False
for i,s in enumerate(todo):
    # EARNINGS
    if s not in ecache:
        try: d,g=get(f"https://www.alphavantage.co/query?function=EARNINGS&symbol={s}&apikey={KEY}")
        except Exception as ex: print(f"  net-err EARN {s}: {ex}",flush=True); time.sleep(SLEEP); continue
        if is_rate(g):
            consec+=1; print(f"  RATE-GATE EARN {s} (consec {consec})",flush=True)
            if consec>=MAX_CONSEC_GATE: stopped=True; break
            time.sleep(SLEEP); continue
        consec=0; ecache[s]={"qe":d.get("quarterlyEarnings",[]),"gate":None}; n_e+=1; time.sleep(SLEEP)
    # STATEMENTS
    if s not in fcache:
        rec={}; rate_hit=False
        for fn,key in [("INCOME_STATEMENT","inc"),("BALANCE_SHEET","bal"),("CASH_FLOW","cf")]:
            try: d,g=get(f"https://www.alphavantage.co/query?function={fn}&symbol={s}&apikey={KEY}")
            except Exception as ex: print(f"  net-err {fn} {s}: {ex}",flush=True); rate_hit=True; time.sleep(SLEEP); break
            if g is not None:
                if is_rate(g):
                    consec+=1; rate_hit=True; print(f"  RATE-GATE {fn} {s} (consec {consec})",flush=True); time.sleep(SLEEP); break
                rec[key]=[]; time.sleep(SLEEP); continue
            consec=0; rec[key]=d.get("quarterlyReports",[]); time.sleep(SLEEP)
        if rate_hit:
            if consec>=MAX_CONSEC_GATE: stopped=True; break
            continue
        fcache[s]={"inc":rec.get("inc",[]),"bal":rec.get("bal",[]),"cf":rec.get("cf",[]),"gate":None}; n_f+=1
    if (n_e+n_f)%50==0 and (n_e+n_f)>0:
        json.dump(ecache,open(EARN_CACHE,"w")); json.dump(fcache,open(FUND_CACHE,"w"))
        el=time.time()-t0; print(f"  {i+1}/{len(todo)} done ({n_e} earn, {n_f} fund this run, {(n_e+3*n_f)/el:.1f} calls/s)",flush=True)
json.dump(ecache,open(EARN_CACHE,"w")); json.dump(fcache,open(FUND_CACHE,"w"))

missing=[s for s in liquid if s not in fcache]
print(f"\nfundamentals cached for {len(liquid)-len(missing)}/{len(liquid)} liquid names; {len(missing)} remain",flush=True)
if missing:
    print(f"INCOMPLETE — re-run to resume ({len(missing)} liquid names left).")
    raise SystemExit

# ---- build expanded parquet (research ∪ liquid, every name we have statements for) ----
print("computing Z'' rows + writing parquet ...",flush=True)
repmap={}  # symbol -> {fiscalDateEnding: reportedDate}
for s,rec in ecache.items():
    repmap[s]={r.get("fiscalDateEnding"):r.get("reportedDate") for r in rec.get("qe",[]) if r.get("reportedDate")}
def F(x):
    try: return float(x)
    except: return np.nan
def ttm(a,i):
    v=a[i-3:i+1]; return np.nan if any(np.isnan(v)) else sum(v)
rows=[]
allsyms=sorted(set(fcache)| set(s for s in liquid if s in fcache))
for sym in allsyms:
    rec=fcache[sym]
    if not rec["inc"] or not rec["bal"] or not rec["cf"]: continue
    inc={r["fiscalDateEnding"]:r for r in rec["inc"]}; bal={r["fiscalDateEnding"]:r for r in rec["bal"]}; cf={r["fiscalDateEnding"]:r for r in rec["cf"]}
    rep=repmap.get(sym,{}); qs=sorted(set(inc)&set(bal)&set(cf))
    NI=[F(inc[q].get("netIncome")) for q in qs]; OCF=[F(cf[q].get("operatingCashflow")) for q in qs]
    REV=[F(inc[q].get("totalRevenue")) for q in qs]; EBIT=[F(inc[q].get("ebit")) for q in qs]
    TA=[F(bal[q].get("totalAssets")) for q in qs]; TL=[F(bal[q].get("totalLiabilities")) for q in qs]
    CA=[F(bal[q].get("totalCurrentAssets")) for q in qs]; CL=[F(bal[q].get("totalCurrentLiabilities")) for q in qs]
    DEBT=[F(bal[q].get("shortLongTermDebtTotal")) for q in qs]; RET=[F(bal[q].get("retainedEarnings")) for q in qs]
    SH=[F(bal[q].get("commonStockSharesOutstanding")) for q in qs]; GP=[F(inc[q].get("grossProfit")) for q in qs]
    for i in range(len(qs)):
        if i<7: continue
        q=qs[i]
        rows.append({"symbol":sym,"fiscalDateEnding":q,"reportedDate":rep.get(q),
                     "fscore":np.nan,"n_avail":np.nan,
                     "ni_ttm":ttm(NI,i),"ocf_ttm":ttm(OCF,i),"rev_ttm":ttm(REV,i),"ebit_ttm":ttm(EBIT,i),
                     "total_assets":TA[i],"total_liabilities":TL[i],"total_debt":DEBT[i],
                     "current_assets":CA[i],"current_liabilities":CL[i],
                     "retained_earnings":RET[i],"shares_out":SH[i]})
df=pd.DataFrame(rows)
miss=df["reportedDate"].isna()
if miss.any():
    df.loc[miss,"reportedDate"]=(pd.to_datetime(df.loc[miss,"fiscalDateEnding"])+pd.Timedelta(days=45)).dt.strftime("%Y-%m-%d")
df=df.sort_values(["symbol","fiscalDateEnding"]).reset_index(drop=True)
df.to_parquet(OUT_PARQUET,index=False)
liquid_covered=df[df.symbol.isin(set(liquid))].symbol.nunique()
print(f"WROTE {OUT_PARQUET}: {len(df)} rows over {df.symbol.nunique()} symbols ({liquid_covered}/{len(liquid)} liquid covered)")
print("COMPLETE.")
