"""ADX rising-band test — does 'buy when 25 < ADX[-1] < ADX[0] < 40' raise the
probability that the NEXT bar makes a higher high, vs a random date?

Signal fires at the close of bar t (we observe today's ADX and yesterday's).
Outcome = high[t+1] > high[t]  (a binary 'next bar makes a higher high').

The unconditional rate over all eligible bars IS the 'random date' benchmark.
We compare the signal-date rate to it (and to the non-signal eligible bars via a
two-proportion z-test). Two signal arms:
  exact : 25 < ADX[-1] < ADX[0] < 40                  (Brand's gate, directionless)
  +dir  : same AND +DI > -DI                          (require bullish direction)

Secondary outcomes for context (not Brand's headline):
  HH_within3 : max(high[t+1..t+3]) > high[t]
  up_close   : close[t+1] > close[t]
Streaming per-symbol aggregation; memory-safe on the 4-vCPU box.
"""
import numpy as np
import pandas as pd
import talib
import duckdb

SEED = 7
N_SYMBOLS = 2000
START = "2016-01-01"
PRICE_MIN, PRICE_MAX, MIN_VOL = 5.0, 500.0, 100_000

con = duckdb.connect("data/ohlcv.duckdb", read_only=True)

spy = con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date", [START]).df()
spy["ema50"] = talib.EMA(spy.close, 50); spy["ema200"] = talib.EMA(spy.close, 200)
spy["bull"] = (spy.close > spy.ema200) & (spy.ema50 > spy.ema200)
spy_regime = dict(zip(spy.date.astype(str).str[:10], spy.bull))
def reg(d): return "bull" if spy_regime.get(str(d)[:10], False) else "nonbull"

syms = con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300", [START]).df().symbol.tolist()
rng = np.random.default_rng(SEED)
if len(syms) > N_SYMBOLS:
    syms = list(rng.choice(syms, N_SYMBOLS, replace=False))
print(f"{len(syms)} symbols", flush=True)

# accumulators: key (arm, outcome, regime) -> [n, k]  (k = count of True outcomes)
acc = {}
def bump(arm, out, rk, n, k):
    key = (arm, out, rk)
    a = acc.get(key)
    if a is None: acc[key] = a = [0, 0]
    a[0] += int(n); a[1] += int(k)

for i, sym in enumerate(syms):
    if i % 400 == 0: print(f"  {i}/{len(syms)}", flush=True)
    d = con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date", [sym, START]).df()
    if len(d) < 250: continue
    o,h,l,c,v = (d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dates = d.date.astype(str).str[:10].to_numpy()
    n = len(c)

    adx = talib.ADX(h,l,c,14); pdi = talib.PLUS_DI(h,l,c,14); mdi = talib.MINUS_DI(h,l,c,14)
    vol20 = pd.Series(v).rolling(20).mean().to_numpy()
    adx_p = np.concatenate([[np.nan], adx[:-1]])           # ADX[-1] (yesterday)

    # signals (index t)
    sig_exact = (adx_p > 25) & (adx > adx_p) & (adx < 40)   # 25 < ADX[-1] < ADX[0] < 40
    sig_dir   = sig_exact & (pdi > mdi)

    # outcomes (index t), need future bars -> last bar(s) invalid
    hi_next = np.concatenate([h[1:], [np.nan]])
    hh_next = hi_next > h
    hi_max3 = np.concatenate([pd.Series(h).rolling(3).max().to_numpy()[3:], [np.nan,np.nan,np.nan]])  # max(high[t+1..t+3])
    hh_w3   = hi_max3 > h
    cl_next = np.concatenate([c[1:], [np.nan]])
    up_cl   = cl_next > c

    have_next  = np.arange(n) < (n-1)
    have_next3 = np.arange(n) < (n-3)
    eligible = (c >= PRICE_MIN) & (c <= PRICE_MAX) & (vol20 > MIN_VOL)
    regimes = np.array([reg(x) for x in dates])

    outcomes = {
        "HH_next":    (hh_next, eligible & have_next),
        "HH_within3": (hh_w3,   eligible & have_next3),
        "up_close":   (up_cl,   eligible & have_next),
    }
    arms = {"__baseline__": np.ones(n, bool), "exact": sig_exact, "+dir": sig_dir}

    for oname, (out, valid) in outcomes.items():
        out = np.asarray(out, bool)
        for aname, amask in arms.items():
            for rk in ("all","bull","nonbull"):
                m = valid & np.asarray(amask, bool)
                if rk != "all": m = m & (regimes == rk)
                nn = int(m.sum())
                if nn: bump(aname, oname, rk, nn, int(out[m].sum()))

def two_prop_z(k1,n1,k0,n0):
    if n1==0 or n0==0: return None
    p1,p0 = k1/n1, k0/n0
    pp = (k1+k0)/(n1+n0)
    se = (pp*(1-pp)*(1/n1+1/n0))**0.5
    return (p1-p0)/se if se>0 else 0.0

print("\n==== ADX rising-band test: P(next bar makes a higher high) ====")
print("baseline = unconditional rate over all eligible bars = the 'random date' benchmark.")
print("z = two-proportion z, signal bars vs all OTHER eligible (non-signal) bars.\n")
for oname in ("HH_next","HH_within3","up_close"):
    print(f"--- outcome: {oname} ---")
    for rk in ("all","bull","nonbull"):
        bn,bk = acc.get(("__baseline__",oname,rk),[0,0])
        pbase = bk/bn if bn else float("nan")
        print(f"  regime={rk:7}  baseline(random date) p={pbase:.4f}  n={bn:,}")
        for arm in ("exact","+dir"):
            sn,sk = acc.get((arm,oname,rk),[0,0])
            if not sn:
                print(f"      {arm:6}: no fires"); continue
            psig = sk/sn
            # non-signal eligible = baseline minus signal
            n0,k0 = bn-sn, bk-sk
            z = two_prop_z(sk,sn,k0,n0)
            lift = psig - pbase
            print(f"      {arm:6}: p={psig:.4f}  lift={lift:+.4f}  z={z:+.1f}  n={sn:,}")
    print()
