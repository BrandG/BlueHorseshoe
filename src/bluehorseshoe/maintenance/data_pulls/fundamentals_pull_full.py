"""Full fundamentals pull for the 1,142 earnings-covered names (AV 3-statement feed).

Universe = the symbols that came back COVERED in earnings_cache_full.json (i.e. we already hold their
reportedDate calendar in data/earnings.parquet). 3 statements each (INCOME_STATEMENT, BALANCE_SHEET,
CASH_FLOW) = ~3,426 AV calls. We do NOT re-pull EARNINGS — reportedDate (the PIT as-of date) comes from
earnings.parquet, "already in hand".

Resumable + rate-limit-safe (mirrors earnings_pull_full.py):
  - checkpoint JSON keyed by symbol; restart skips already-fetched symbols.
  - a symbol is cached ONLY when all 3 statements returned without a RATE gate (no partial caching).
  - RATE gate (call-frequency/premium) -> not cached; >=3 consecutive -> STOP gracefully, resume later.
  - terminal per-statement failure (Invalid API call / bad ticker) -> that statement cached empty so we
    stop retrying; symbol still cached (its F-score will just have fewer components).
  - seeds inc/bal/cf from the prototype cache for any overlapping symbol (free reuse).

Final (only when no symbol is missing): compute Piotroski F-score per quarter, align each quarter to its
earnings reportedDate (PIT, no lookahead), and flatten to data/fundamentals.parquet. Stores the F-score AND
the raw TTM building blocks + level inputs (ni/ocf/rev/assets/debt/shares/retained/ebit/liabilities) so the
downstream conditioning script can build profitable/Altman-Z LEVEL flags without re-pulling.

F-score (9, binary), TTM flows + YoY-quarter (quarter i vs i-4) to dodge seasonality:
 1 NI_ttm>0  2 OCF_ttm>0  3 dROA>0  4 OCF_ttm>NI_ttm (accrual)
 5 dLeverage<0 (debt/assets)  6 dCurrentRatio>0  7 no dilution (shares not up)
 8 dGrossMargin>0  9 dAssetTurnover>0
"""
import os, json, time, urllib.request, numpy as np, pandas as pd

EARN_CKPT="research/indicator_screen/earnings_cache_full.json"
PROTO="research/indicator_screen/fund_cache_proto.json"
CKPT="research/indicator_screen/fund_cache_full.json"
EARN_PARQUET="data/earnings.parquet"
OUT_PARQUET="data/fundamentals.parquet"
KEY=os.environ.get("ALPHAVANTAGE_KEY")
SLEEP=0.55; MAX_CONSEC_GATE=3

# --- universe: the earnings-covered names (we hold their reportedDate calendar) ---
ec=json.load(open(EARN_CKPT))
syms=sorted(s for s,v in ec.items() if v.get("qe"))
print(f"universe: {len(syms)} earnings-covered symbols (3 statements each = {3*len(syms)} calls)",flush=True)

# --- checkpoint, seeded from prototype cache for overlapping symbols ---
cache=json.load(open(CKPT)) if os.path.exists(CKPT) else {}
if os.path.exists(PROTO):
    proto=json.load(open(PROTO)); reused=0
    for s in syms:
        if s not in cache and s in proto and proto[s].get("inc"):
            cache[s]={"inc":proto[s]["inc"],"bal":proto[s]["bal"],"cf":proto[s]["cf"],"gate":None}; reused+=1
    if reused: print(f"  seeded {reused} symbols from prototype cache",flush=True)
print(f"checkpoint has {len(cache)} symbols cached",flush=True)

def fetch(fn,sym):
    url=f"https://www.alphavantage.co/query?function={fn}&symbol={sym}&apikey={KEY}"
    d=json.loads(urllib.request.urlopen(url,timeout=30).read().decode())
    gate=[d[k] for k in ("Note","Information","Error Message") if k in d]
    return d.get("quarterlyReports",[]), (gate[0][:140] if gate else None)

def is_rate(g): return any(t in g.lower() for t in ("call frequency","premium","thank you for using","rate limit","higher api"))

todo=[s for s in syms if s not in cache]
print(f"to fetch: {len(todo)} symbols ({3*len(todo)} calls)",flush=True)
consec_gate=0; fetched=0; t0=time.time(); stopped=False
STMTS=[("INCOME_STATEMENT","inc"),("BALANCE_SHEET","bal"),("CASH_FLOW","cf")]
for s in todo:
    rec={}; rate_hit=False
    for fn,key in STMTS:
        try:
            rep,gate=fetch(fn,s)
        except Exception as e:
            print(f"  net-err {s}/{fn}: {e} (will retry on resume)",flush=True); rate_hit=True; time.sleep(SLEEP); break
        if gate is not None:
            if is_rate(gate):
                consec_gate+=1; rate_hit=True
                print(f"  RATE-GATE {s}/{fn}: {gate} (consec {consec_gate})",flush=True)
                time.sleep(SLEEP); break
            # terminal per-statement failure -> empty that statement, keep going
            rec[key]=[]; print(f"  terminal-empty {s}/{fn}: {gate}",flush=True); time.sleep(SLEEP); continue
        consec_gate=0; rec[key]=rep; time.sleep(SLEEP)
    if rate_hit:
        if consec_gate>=MAX_CONSEC_GATE:
            print(f"  >>> rate-storm — stopping to resume later. {len(cache)}/{len(syms)} cached.",flush=True)
            stopped=True; break
        continue
    cache[s]={"inc":rec.get("inc",[]),"bal":rec.get("bal",[]),"cf":rec.get("cf",[]),"gate":None}; fetched+=1
    if fetched%25==0:
        json.dump(cache,open(CKPT,"w"))
        el=time.time()-t0; rate=(3*fetched)/el if el>0 else 0
        print(f"  {len(cache)}/{len(syms)} cached ({fetched} syms this run, {rate:.1f} calls/s)",flush=True)
json.dump(cache,open(CKPT,"w"))

covered=[s for s in syms if s in cache]
missing=[s for s in syms if s not in cache]
print(f"\nCOVERAGE: cached={len(covered)} not-yet-fetched={len(missing)}",flush=True)

if missing:
    print(f"INCOMPLETE — {len(missing)} symbols remain (gate/cap or net errors). Re-run to resume.")
    print("\ndone."); raise SystemExit

# ---------- complete: build PIT-aligned F-score table ----------
print("building reportedDate map from earnings.parquet ...",flush=True)
ep=pd.read_parquet(EARN_PARQUET)
repmap={}  # symbol -> {fiscalDateEnding: reportedDate}
for sym,g in ep.groupby("symbol"):
    repmap[sym]={fd:rd for fd,rd in zip(g.fiscalDateEnding, g.reportedDate) if rd}

def Fv(x):
    try: return float(x)
    except: return np.nan

def rows_for(sym):
    rec=cache[sym]
    if not rec["inc"] or not rec["bal"] or not rec["cf"]: return []
    inc={r["fiscalDateEnding"]:r for r in rec["inc"]}
    bal={r["fiscalDateEnding"]:r for r in rec["bal"]}
    cf ={r["fiscalDateEnding"]:r for r in rec["cf"]}
    rep=repmap.get(sym,{})
    qs=sorted(set(inc)&set(bal)&set(cf))
    NI=[Fv(inc[q].get("netIncome")) for q in qs]
    OCF=[Fv(cf[q].get("operatingCashflow")) for q in qs]
    REV=[Fv(inc[q].get("totalRevenue")) for q in qs]
    GP =[Fv(inc[q].get("grossProfit")) for q in qs]
    EBIT=[Fv(inc[q].get("ebit")) for q in qs]
    TA=[Fv(bal[q].get("totalAssets")) for q in qs]
    TL=[Fv(bal[q].get("totalLiabilities")) for q in qs]
    CA=[Fv(bal[q].get("totalCurrentAssets")) for q in qs]
    CL=[Fv(bal[q].get("totalCurrentLiabilities")) for q in qs]
    DEBT=[Fv(bal[q].get("shortLongTermDebtTotal")) for q in qs]
    RET=[Fv(bal[q].get("retainedEarnings")) for q in qs]
    SH=[Fv(bal[q].get("commonStockSharesOutstanding")) for q in qs]
    def ttm(arr,i):
        v=arr[i-3:i+1]
        return np.nan if any(np.isnan(v)) else sum(v)
    out=[]
    for i in range(len(qs)):
        if i<7: continue
        ni,ocf,rev,gp,ebit=ttm(NI,i),ttm(OCF,i),ttm(REV,i),ttm(GP,i),ttm(EBIT,i)
        ni0,ocf0,rev0,gp0=ttm(NI,i-4),ttm(OCF,i-4),ttm(REV,i-4),ttm(GP,i-4)
        ta,ta0=TA[i],TA[i-4]
        comp=[]
        comp.append(ni>0); comp.append(ocf>0)
        comp.append((ni/ta)>(ni0/ta0) if ta and ta0 else np.nan)
        comp.append(ocf>ni)
        lev=DEBT[i]/ta if ta else np.nan; lev0=DEBT[i-4]/ta0 if ta0 else np.nan
        comp.append(lev<lev0)
        cr=CA[i]/CL[i] if CL[i] else np.nan; cr0=CA[i-4]/CL[i-4] if CL[i-4] else np.nan
        comp.append(cr>cr0)
        comp.append(SH[i]<=SH[i-4] if (not np.isnan(SH[i]) and not np.isnan(SH[i-4])) else np.nan)
        gm=gp/rev if rev else np.nan; gm0=gp0/rev0 if rev0 else np.nan
        comp.append(gm>gm0)
        at=rev/ta if ta else np.nan; at0=rev0/ta0 if ta0 else np.nan
        comp.append(at>at0)
        avail=[c for c in comp if not (isinstance(c,float) and np.isnan(c))]
        fs=sum(1 for c in avail if c is True)
        q=qs[i]
        out.append({"symbol":sym,"fiscalDateEnding":q,"reportedDate":rep.get(q),
                    "fscore":fs,"n_avail":len(avail),
                    "ni_ttm":ni,"ocf_ttm":ocf,"rev_ttm":rev,"ebit_ttm":ebit,
                    "total_assets":ta,"total_liabilities":TL[i],"total_debt":DEBT[i],
                    "current_assets":CA[i],"current_liabilities":CL[i],
                    "retained_earnings":RET[i],"shares_out":SH[i]})
    return out

rows=[]; no_inc=0; no_rd=0
for s in covered:
    rs=rows_for(s)
    if not rs and (not cache[s]["inc"]): no_inc+=1
    for r in rs:
        if not r["reportedDate"]: no_rd+=1
    rows.extend(rs)
df=pd.DataFrame(rows)
# fallback as-of for the rare quarter with no exact reportedDate match: fiscalEnd + 45d
miss=df["reportedDate"].isna()
if miss.any():
    df.loc[miss,"reportedDate"]=(pd.to_datetime(df.loc[miss,"fiscalDateEnding"])+pd.Timedelta(days=45)).dt.strftime("%Y-%m-%d")
df=df.sort_values(["symbol","fiscalDateEnding"]).reset_index(drop=True)
df.to_parquet(OUT_PARQUET,index=False)
print(f"WROTE {OUT_PARQUET}: {len(df)} quarter-rows over {df.symbol.nunique()} symbols",flush=True)
print(f"  symbols with no income data: {no_inc} | quarter-rows needing reportedDate fallback: {int(miss.sum())}")
print(f"  F-score dist: mean {df.fscore.mean():.2f}  low(<=3) {100*(df.fscore<=3).mean():.0f}%  high(>=7) {100*(df.fscore>=7).mean():.0f}%")
print("COMPLETE.")
print("\ndone.")
