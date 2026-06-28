"""Data access: AlphaVantage pull + cache, intraday loaders, and daily ATR_14.

ATR source: DuckDB OHLCV store first (covers the equity universe); falls back to a
cached AlphaVantage daily file ({SYM}_DAILY.json) for ETFs not in DuckDB.
"""
import os, glob, json, time, urllib.request
from collections import defaultdict
import config as C


# ---------------- ATR (Wilder, ATR_14, known at the open = through the prior close) ----------------
def _wilder_atr_by_date(rows):
    """rows: sorted list of (date, high, low, close). Returns {date: ATR_through_that_date}."""
    atr = None; prev = None; trs = []; out = {}
    for d, h, l, c in rows:
        tr = (h - l) if prev is None else max(h - l, abs(h - prev), abs(l - prev))
        if atr is None:
            trs.append(tr)
            if len(trs) == 14:
                atr = sum(trs) / 14.0
        else:
            atr = (atr * 13 + tr) / 14.0
        if atr is not None:
            out[d] = atr
        prev = c
    return out


def _atr_from_duckdb(sym):
    import duckdb
    con = duckdb.connect(C.DUCKDB_PATH, read_only=True)
    rows = con.execute("select date, high, low, close from ohlcv where symbol=? order by date",
                       [sym]).fetchall()
    con.close()
    return rows


def _atr_from_daily_json(sym):
    for d in C.CACHE_DIRS:
        p = os.path.join(d, f"{sym}_DAILY.json")
        if os.path.exists(p):
            ts = json.load(open(p)).get("Time Series (Daily)", {})
            return sorted((dt, float(v["2. high"]), float(v["3. low"]), float(v["4. close"]))
                          for dt, v in ts.items())
    return []


def get_atr(sym):
    """{trade_date: ATR_14 known at that day's open}. ATR through the prior available daily bar."""
    rows = _atr_from_duckdb(sym)
    if len(rows) < 20:
        rows = _atr_from_daily_json(sym)
    through = _wilder_atr_by_date(rows)
    dates = [r[0] for r in rows]
    return {dates[i]: through[dates[i-1]] for i in range(1, len(dates)) if dates[i-1] in through}


# ---------------- intraday bars ----------------
def load_intraday(sym):
    """Merge all cached month files for sym across CACHE_DIRS. {day: sorted [(hm,o,h,l,c)]}, hm<=11:00."""
    by_day = defaultdict(list)
    seen = set()
    for d in C.CACHE_DIRS:
        for p in glob.glob(os.path.join(d, f"{sym}_2*.json")):   # month files (skip _DAILY)
            ts = json.load(open(p)).get("Time Series (1min)", {})
            for stamp, b in ts.items():
                if stamp in seen:
                    continue
                seen.add(stamp)
                day, hm = stamp.split(" ")
                if hm > C.SIM_END:
                    continue
                by_day[day].append((hm, float(b["1. open"]), float(b["2. high"]),
                                    float(b["3. low"]), float(b["4. close"])))
    for day in by_day:
        by_day[day].sort()
    return by_day


def build_setups(symbols, day_min=None, day_max=None):
    """Yield validated setups (ATR filter applied), tagged with _sym/_day/_q (quarter)."""
    from strategy import build_setup
    out = []
    for sym in symbols:
        atr = get_atr(sym)
        for day, bars in load_intraday(sym).items():
            if (day_min and day < day_min) or (day_max and day >= day_max):
                continue
            a = atr.get(day)
            if a is None:
                continue
            s = build_setup(bars)
            if not s or s["R"] < C.ATR_MULT * a:
                continue
            s["_sym"] = sym; s["_day"] = day
            s["_q"] = f"{day[:4]}Q{(int(day[5:7]) - 1)//3 + 1}"
            out.append(s)
    return out


# ---------------- AlphaVantage pull ----------------
def _api_key():
    for line in open(os.path.join(C.REPO_ROOT, ".env")):
        if line.startswith("ALPHAVANTAGE_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("ALPHAVANTAGE_KEY not found in .env")


def _fetch(url, path, want):
    if os.path.exists(path) and os.path.getsize(path) > 2000:
        return "cached"
    for _ in range(3):
        try:
            raw = urllib.request.urlopen(url, timeout=60).read()
            d = json.loads(raw)
            if want in d:
                open(path, "wb").write(raw)
                return "ok"
            msg = str(d.get("Note") or d.get("Information") or d.get("Error Message") or "?")
            time.sleep(15 if any(w in msg.lower() for w in ("rate", "frequency")) else 2)
        except Exception:
            time.sleep(3)
    return "FAIL"


def pull(symbols, months, intraday=True, daily=True, cache_dir=None):
    """Download (and cache) intraday month files and/or daily files for symbols."""
    cache_dir = cache_dir or C.PRIMARY_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)
    k = _api_key(); fails = []
    if daily:
        for t in symbols:
            u = (f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={t}"
                 f"&outputsize=full&apikey={k}")
            if _fetch(u, os.path.join(cache_dir, f"{t}_DAILY.json"), "Time Series (Daily)") == "FAIL":
                fails.append((t, "daily"))
            time.sleep(0.7)
    if intraday:
        for t in symbols:
            for m in months:
                u = (f"https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol={t}"
                     f"&interval=1min&month={m}&outputsize=full&extended_hours=false&apikey={k}")
                r = _fetch(u, os.path.join(cache_dir, f"{t}_{m}.json"), "Time Series (1min)")
                if r == "FAIL":
                    fails.append((t, m))
                if r != "cached":
                    time.sleep(0.7)
            print(f"  pulled {t}", flush=True)
    return fails
