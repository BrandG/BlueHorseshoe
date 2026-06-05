"""WS4 #1 — Pullback-to-MA trend-continuation backtest (signal-only first pass).

Tests a genuinely with-trend bet our system does NOT run (baseline buys strength,
MR buys oversold weakness; this buys a shallow dip *inside* an uptrend), plus a
random-eligible-entry baseline that doubles as the "does selection beat random?"
denominator. Self-contained: talib for indicators, manual bracket simulation for
full control over entry semantics. Regime-split by SPY trend; V2 expectancy gate.
"""
import json
import os
import numpy as np
import pandas as pd
import talib
import duckdb

SEED = 7
N_SYMBOLS = 2500          # representative sample for a first-pass expectancy read
START = "2016-01-01"      # multi-regime span (incl. the rising_3bar caution era)
PRICE_MIN, PRICE_MAX = 5.0, 500.0
MIN_VOL = 100_000
MAX_RISK = 0.05           # constants.MAX_RISK_PERCENT
CONFIGS = [(rr, h) for rr in (1.5, 2.0) for h in (5, 10)]

con = duckdb.connect("data/ohlcv.duckdb", read_only=True)

# ── SPY regime series (bull = close>EMA200 and EMA50>EMA200) ──────────
spy = con.execute("SELECT date, close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date", [START]).df()
spy["ema50"] = talib.EMA(spy["close"], 50)
spy["ema200"] = talib.EMA(spy["close"], 200)
spy["bull"] = (spy["close"] > spy["ema200"]) & (spy["ema50"] > spy["ema200"])
spy_regime = dict(zip(spy["date"].astype(str).str[:10], spy["bull"]))

def regime_of(d):
    return "bull" if spy_regime.get(str(d)[:10], False) else "nonbull"

# ── universe sample ───────────────────────────────────────────────────
syms = con.execute(
    "SELECT symbol, count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300", [START]
).df()["symbol"].tolist()
rng = np.random.default_rng(SEED)
if len(syms) > N_SYMBOLS:
    syms = list(rng.choice(syms, N_SYMBOLS, replace=False))
print(f"universe sample: {len(syms)} symbols", flush=True)

pullback_trades = []   # (date, regime, rr, hold, R)
eligible_pool = []     # (symbol, idx) snapshots for random baseline: store per-symbol arrays

def simulate(o, h, l, c, entry_i, stop, target, hold):
    """Enter at open[entry_i]; scan forward hold bars for stop/target/time. Return R."""
    entry = o[entry_i]
    risk = entry - stop
    if risk <= 0:
        return None
    for j in range(entry_i, min(entry_i + hold, len(c))):
        if l[j] <= stop:                      # conservative: stop checked first
            return (stop - entry) / risk
        if h[j] >= target:
            return (target - entry) / risk
    j = min(entry_i + hold, len(c) - 1)
    return (c[j] - entry) / risk              # time exit

per_symbol = {}   # symbol -> dict of arrays, for the random baseline
for k, sym in enumerate(syms):
    if k % 500 == 0:
        print(f"  {k}/{len(syms)}", flush=True)
    d = con.execute(
        "SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",
        [sym, START]).df()
    if len(d) < 250:
        continue
    o, h, l, c, v = (d[x].to_numpy(float) for x in ("open", "high", "low", "close", "volume"))
    dates = d["date"].astype(str).str[:10].to_numpy()
    ema10, ema20, ema50 = talib.EMA(c, 10), talib.EMA(c, 20), talib.EMA(c, 50)
    atr = talib.ATR(h, l, c, 14)
    adx = talib.ADX(h, l, c, 14)
    volavg = pd.Series(v).rolling(20).mean().to_numpy()
    swing_low20 = pd.Series(l).rolling(20).min().to_numpy()
    per_symbol[sym] = dict(o=o, h=h, l=l, c=c, atr=atr, dates=dates, volavg=volavg,
                           price_ok=(c >= PRICE_MIN) & (c <= PRICE_MAX))

    for t in range(60, len(c) - 1):
        if not (PRICE_MIN <= c[t] <= PRICE_MAX):           continue
        if not (volavg[t] > MIN_VOL):                       continue
        if np.isnan(atr[t]) or np.isnan(adx[t]) or np.isnan(ema50[t]): continue
        # trend gate
        if not (c[t] > ema50[t] and ema50[t] > ema50[t-10] and ema10[t] > ema20[t] and adx[t] > 20):
            continue
        # pullback trigger: dip to EMA20, >=2 non-up closes, holding above 20-bar swing low
        if abs(l[t] - ema20[t]) > 0.5 * atr[t]:             continue
        if not (c[t] <= c[t-1] and c[t-1] <= c[t-2]):       continue
        if not (l[t] > swing_low20[t-1]):                   continue
        entry = o[t+1]
        stop = entry - 1.2 * atr[t]
        if entry <= 0 or (entry - stop) / entry > MAX_RISK:  continue
        reg = regime_of(dates[t+1])
        for rr, hold in CONFIGS:
            target = entry + rr * (entry - stop)
            R = simulate(o, h, l, c, t+1, stop, target, hold)
            if R is not None:
                pullback_trades.append((dates[t+1], reg, rr, hold, R))

print(f"pullback trades: {len(pullback_trades)}", flush=True)

# ── random-eligible-entry baseline (same configs, same date distribution) ──
pb = pd.DataFrame(pullback_trades, columns=["date", "regime", "rr", "hold", "R"])
rand_trades = []
sym_keys = [s for s in per_symbol if len(per_symbol[s]["c"]) > 80]
N_RAND = min(len(pb), 40000)
for _ in range(N_RAND):
    sym = sym_keys[rng.integers(len(sym_keys))]
    a = per_symbol[sym]
    n = len(a["c"])
    t = int(rng.integers(40, n - 12))
    if not a["price_ok"][t] or not (a["volavg"][t] > MIN_VOL) or np.isnan(a["atr"][t]):
        continue
    entry = a["o"][t+1] if t+1 < n else a["c"][t]
    stop = entry - 1.2 * a["atr"][t]
    if entry <= 0 or (entry - stop) / entry > MAX_RISK:
        continue
    rr, hold = CONFIGS[rng.integers(len(CONFIGS))]
    target = entry + rr * (entry - stop)
    R = simulate(a["o"], a["h"], a["l"], a["c"], t+1, stop, target, hold)
    if R is not None:
        rand_trades.append((a["dates"][t+1], regime_of(a["dates"][t+1]), rr, hold, R))
rb = pd.DataFrame(rand_trades, columns=["date", "regime", "rr", "hold", "R"])
print(f"random-baseline trades: {len(rb)}", flush=True)

# ── aggregate with V2 expectancy gate (mean_R - 1.96*SE > 0) ──────────
def summ(df):
    n = len(df)
    if n == 0:
        return dict(n=0)
    m = df["R"].mean(); se = df["R"].std(ddof=1) / np.sqrt(n)
    return dict(n=int(n), mean_R=round(float(m), 4), se=round(float(se), 4),
                lo95=round(float(m - 1.96*se), 4), win=round(float((df["R"] > 0).mean()), 3),
                gate_pass=bool(m - 1.96*se > 0))

out = {"pullback": {}, "random": {}, "by_config": {}, "by_regime": {}}
out["pullback"]["ALL"] = summ(pb)
out["random"]["ALL"] = summ(rb)
for reg in ("bull", "nonbull"):
    out["by_regime"][f"pullback/{reg}"] = summ(pb[pb.regime == reg])
    out["by_regime"][f"random/{reg}"] = summ(rb[rb.regime == reg])
for rr, hold in CONFIGS:
    out["by_config"][f"pullback rr{rr}/h{hold}"] = summ(pb[(pb.rr == rr) & (pb.hold == hold)])

os.makedirs("research/pullback_v1", exist_ok=True)
json.dump(out, open("research/pullback_v1/results.json", "w"), indent=1)
print("\n==== RESULTS ====")
print("PULLBACK  ALL :", out["pullback"]["ALL"])
print("RANDOM    ALL :", out["random"]["ALL"])
print("\nby regime:")
for k, v in out["by_regime"].items():
    print(f"  {k:18} {v}")
print("\nby config (pullback):")
for k, v in out["by_config"].items():
    print(f"  {k:22} {v}")
print("\nedge vs random (ALL): mean_R", out["pullback"]["ALL"].get("mean_R"), "-", out["random"]["ALL"].get("mean_R"))
print("saved -> research/pullback_v1/results.json")
