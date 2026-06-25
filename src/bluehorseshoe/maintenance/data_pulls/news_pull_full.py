"""Historical news-sentiment pull for the news/sentiment conditioning axis (AV NEWS_SENTIMENT).

Pulls the full 2022-02-20 -> now article history for the 899 symbols with >=1 nonbull DeepOS fire
in the archive window (news_fire_list.parquet from news_fire_census.py). One whole-range call per
symbol, paged via sort=EARLIEST + advancing time_from when a page hits the 1000-article cap.

Resumable + rate-limit-safe (pattern from earnings_pull_full.py):
  - checkpoint JSON keyed by symbol; restart skips already-fetched.
  - GATE DETECTION: AV Note/Information responses are NOT cached; >=3 consecutive gates stops the
    run gracefully for a later resume. Genuinely-empty feeds ARE cached.
Final: flatten to data/news_sentiment.parquet (long: symbol, time_published, source,
relevance_score, ticker_sentiment_score, overall_sentiment_score, title).
"""
import os, json, time, urllib.request, urllib.parse, pandas as pd

CKPT="research/indicator_screen/news_cache_full.json"
OUT_PARQUET="data/news_sentiment.parquet"
FIRES="research/indicator_screen/news_fire_list.parquet"
KEY=os.environ.get("ALPHAVANTAGE_KEY")
TIME_FROM="20220220T0000"   # 7d lookback margin before NEWS_START=2022-03-01
SLEEP=0.55; MAX_CONSEC_GATE=3; MAX_PAGES=12

syms=sorted(pd.read_parquet(FIRES).symbol.unique().tolist())
print(f"{len(syms)} symbols to pull",flush=True)

cache={}
if os.path.exists(CKPT): cache=json.load(open(CKPT))
print(f"checkpoint has {len(cache)} symbols cached",flush=True)

def fetch_page(sym,tf):
    url=("https://www.alphavantage.co/query?function=NEWS_SENTIMENT"
         f"&tickers={urllib.parse.quote(sym)}&time_from={tf}&sort=EARLIEST&limit=1000&apikey={KEY}")
    raw=urllib.request.urlopen(url,timeout=60).read().decode()
    j=json.loads(raw)
    if "Note" in j or "Information" in j:
        return None,"gate:"+str(j.get("Note") or j.get("Information"))[:80]
    if "Error Message" in j:
        return [],None   # invalid/delisted symbol -> cache as empty
    return j.get("feed",[]),None

def slim(sym,a):
    ts=next((t for t in a.get("ticker_sentiment",[]) if t.get("ticker")==sym),{})
    return {"time_published":a.get("time_published"),
            "source":a.get("source"),
            "relevance_score":ts.get("relevance_score"),
            "ticker_sentiment_score":ts.get("ticker_sentiment_score"),
            "overall_sentiment_score":a.get("overall_sentiment_score"),
            "title":(a.get("title") or "")[:120]}

consec_gate=0; done=0
for sym in syms:
    if sym in cache: continue
    arts=[]; tf=TIME_FROM; pages=0; gated=False
    while pages<MAX_PAGES:
        feed,gate=fetch_page(sym,tf); time.sleep(SLEEP)
        if gate is not None:
            consec_gate+=1; gated=True
            print(f"  GATE on {sym} ({consec_gate} consecutive): {gate}",flush=True)
            break
        consec_gate=0
        arts.extend(slim(sym,a) for a in feed)
        pages+=1
        if len(feed)<1000: break
        last=feed[-1].get("time_published","")[:13]  # AV accepts YYYYMMDDTHHMM only (no seconds)
        if not last or last<=tf: break
        tf=last  # AV time_from is inclusive; the duplicate boundary article is deduped at flatten
    if gated:
        if consec_gate>=MAX_CONSEC_GATE:
            print("gate storm -> stopping for later resume",flush=True); break
        continue
    cache[sym]={"articles":arts,"pages":pages}
    done+=1
    if done%25==0:
        json.dump(cache,open(CKPT,"w"))
        print(f"  {done} fetched this run / {len(cache)} total cached",flush=True)
json.dump(cache,open(CKPT,"w"))
print(f"cached: {len(cache)}/{len(syms)}",flush=True)

if len(cache)==len(syms):
    rows=[]
    for sym,v in cache.items():
        for a in v["articles"]:
            rows.append({"symbol":sym,**a})
    df=pd.DataFrame(rows)
    if len(df):
        df=df.drop_duplicates(subset=["symbol","time_published","title"])
        for c in ("relevance_score","ticker_sentiment_score","overall_sentiment_score"):
            df[c]=pd.to_numeric(df[c],errors="coerce")
    df.to_parquet(OUT_PARQUET)
    print(f"flattened {len(df)} articles -> {OUT_PARQUET}",flush=True)
    print(df.groupby(df.time_published.str[:4]).size().to_string(),flush=True)
else:
    print("incomplete -- rerun to resume",flush=True)
