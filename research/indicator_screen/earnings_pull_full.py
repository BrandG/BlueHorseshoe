"""Full earnings pull for the pinned 2000-symbol harness universe (AV EARNINGS endpoint).

Resumable + rate-limit-safe:
  - checkpoint JSON keyed by symbol; restart skips already-fetched.
  - GATE DETECTION: an AV rate-limit/Note response is NOT cached (would falsely look like 'no earnings');
    on a gate-storm (>=3 consecutive) the run STOPS gracefully so we resume later. Genuinely-empty (delisted)
    results ARE cached (gate is None).
  - rate ~1.8/s (under CPS=2). ~2000 calls ~= 20min if the plan allows; else stops + resumes across days.
Final: flatten to data/earnings.parquet (long: symbol, fiscalDateEnding, reportedDate, reportedEPS,
estimatedEPS, surprise, surprisePercentage, reportTime). Universe pinned identically to the fixed harness
(ORDER BY symbol, SEED=7, N=2000) so the earnings table aligns with Angles 1&2.
"""
import os, json, time, urllib.request, numpy as np, pandas as pd, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")
CKPT="research/indicator_screen/earnings_cache_full.json"
OUT_PARQUET="data/earnings.parquet"
KEY=os.environ.get("ALPHAVANTAGE_KEY")
SLEEP=0.55; MAX_CONSEC_GATE=3

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300 ORDER BY symbol",[START]).df().symbol.tolist()
syms=[s for s in syms if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=sorted(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"universe: {len(syms)} pinned symbols",flush=True)

# seed checkpoint from the prototype cache if present (reuse those 25 calls)
cache={}
if os.path.exists(CKPT): cache=json.load(open(CKPT))
proto="research/indicator_screen/earnings_cache_proto.json"
if os.path.exists(proto):
    for s,v in json.load(open(proto)).items():
        if s not in cache and v.get("gate") is None: cache[s]=v
print(f"checkpoint has {len(cache)} symbols cached",flush=True)

def fetch(sym):
    url=f"https://www.alphavantage.co/query?function=EARNINGS&symbol={sym}&apikey={KEY}"
    raw=urllib.request.urlopen(url,timeout=30).read().decode()
    d=json.loads(raw)
    gate=[d[k] for k in ("Note","Information","Error Message") if k in d]
    return d.get("quarterlyEarnings",[]), (gate[0][:140] if gate else None)

todo=[s for s in syms if s not in cache]
print(f"to fetch: {len(todo)}",flush=True)
consec_gate=0; fetched=0; t0=time.time()
stopped=False
for i,s in enumerate(todo):
    try:
        qe,gate=fetch(s)
    except Exception as e:
        print(f"  net-err {s}: {e} (will retry on resume)",flush=True); time.sleep(SLEEP); continue
    if gate is not None:
        is_rate=any(t in gate.lower() for t in ("call frequency","premium","thank you for using","rate limit","higher api"))
        if is_rate:
            consec_gate+=1
            print(f"  RATE-GATE on {s}: {gate}  (consec {consec_gate})",flush=True)
            if consec_gate>=MAX_CONSEC_GATE:
                print(f"  >>> rate-storm — stopping to resume later. {len(cache)}/{len(syms)} cached.",flush=True)
                stopped=True; break
            time.sleep(SLEEP); continue
        # terminal per-symbol failure (Invalid API call / bad ticker) -> cache empty so we stop retrying
        consec_gate=0; cache[s]={"qe":[],"gate":None}; fetched+=1
        print(f"  terminal-empty {s}: {gate}",flush=True)
        time.sleep(SLEEP); continue
    consec_gate=0
    cache[s]={"qe":qe,"gate":None}; fetched+=1
    if fetched%50==0:
        json.dump(cache,open(CKPT,"w"))
        el=time.time()-t0; rate=fetched/el if el>0 else 0
        print(f"  {len(cache)}/{len(syms)} cached ({fetched} this run, {rate:.1f}/s)",flush=True)
    time.sleep(SLEEP)
json.dump(cache,open(CKPT,"w"))

covered=[s for s in syms if s in cache and cache[s]["qe"]]
empty=[s for s in syms if s in cache and not cache[s]["qe"]]
missing=[s for s in syms if s not in cache]
print(f"\nCOVERAGE: covered={len(covered)} empty/delisted={len(empty)} not-yet-fetched={len(missing)}",flush=True)

if not missing:   # complete -> flatten to parquet
    rows=[]
    for s in covered:
        for r in cache[s]["qe"]:
            rows.append({"symbol":s,"fiscalDateEnding":r.get("fiscalDateEnding"),
                         "reportedDate":r.get("reportedDate"),"reportedEPS":r.get("reportedEPS"),
                         "estimatedEPS":r.get("estimatedEPS"),"surprise":r.get("surprise"),
                         "surprisePercentage":r.get("surprisePercentage"),"reportTime":r.get("reportTime")})
    df=pd.DataFrame(rows)
    df.to_parquet(OUT_PARQUET,index=False)
    print(f"WROTE {OUT_PARQUET}: {len(df)} earnings rows over {df.symbol.nunique()} symbols",flush=True)
    print(f"  coverage rate: {100*len(covered)/len(syms):.1f}% of universe has earnings data")
    print("COMPLETE.")
else:
    print(f"INCOMPLETE — {len(missing)} symbols remain (gate/cap or net errors). Re-run to resume.")
print("\ndone.")
