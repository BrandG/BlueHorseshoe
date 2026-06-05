"""ADX decomposition — isolate whether the rising-ADX band adds anything beyond
+DI>-DI alone, and vice versa.

Three building blocks (evaluated at close of bar t):
  dir   = +DI > -DI                                  (bullish direction)
  band  = 25 < ADX[-1] < ADX[0] < 40                 (rising ADX in band)
  both  = dir AND band

Headline outcome = high[t+1] > high[t] (next bar makes a higher high).
Money sanity-check outcome = close[t+1] > close[t].

Two questions:
  (Q1) Does the band add anything GIVEN direction?  -> compare  both  vs  dir-but-not-band
  (Q2) Does direction add anything GIVEN the band?  -> compare  both  vs  band-but-not-dir
Each marginal contrast is a two-proportion z between two disjoint groups.
Baseline = unconditional rate over all eligible bars = the 'random date' benchmark.
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

# accumulators: key (group, outcome, regime) -> [n, k]
acc = {}
def bump(g, out, rk, n, k):
    key = (g, out, rk); a = acc.get(key)
    if a is None: acc[key] = a = [0, 0]
    a[0] += int(n); a[1] += int(k)

for i, sym in enumerate(syms):
    if i % 400 == 0: print(f"  {i}/{len(syms)}", flush=True)
    d = con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date", [sym, START]).df()
    if len(d) < 250: continue
    o,h,l,c,v = (d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dates = d.date.astype(str).str[:10].to_numpy(); n = len(c)

    adx = talib.ADX(h,l,c,14); pdi = talib.PLUS_DI(h,l,c,14); mdi = talib.MINUS_DI(h,l,c,14)
    vol20 = pd.Series(v).rolling(20).mean().to_numpy()
    adx_p = np.concatenate([[np.nan], adx[:-1]])

    dirb = pdi > mdi
    band = (adx_p > 25) & (adx > adx_p) & (adx < 40)
    both = dirb & band

    groups = {
        "dir":          dirb,
        "band":         band,
        "both":         both,
        "dir_not_band": dirb & ~band,
        "band_not_dir": band & ~dirb,
        "__baseline__": np.ones(n, bool),
    }

    hi_next = np.concatenate([h[1:], [np.nan]]); hh_next = hi_next > h
    cl_next = np.concatenate([c[1:], [np.nan]]); up_cl = cl_next > c
    have_next = np.arange(n) < (n-1)
    eligible = (c >= PRICE_MIN) & (c <= PRICE_MAX) & (vol20 > MIN_VOL)
    valid = eligible & have_next
    regimes = np.array([reg(x) for x in dates])

    for oname, out in (("HH_next", hh_next), ("up_close", up_cl)):
        out = np.asarray(out, bool)
        for gname, gmask in groups.items():
            for rk in ("all","bull","nonbull"):
                m = valid & np.asarray(gmask, bool)
                if rk != "all": m = m & (regimes == rk)
                nn = int(m.sum())
                if nn: bump(gname, oname, rk, nn, int(out[m].sum()))

def two_prop_z(k1,n1,k0,n0):
    if n1==0 or n0==0: return None
    p1,p0 = k1/n1, k0/n0; pp = (k1+k0)/(n1+n0)
    se = (pp*(1-pp)*(1/n1+1/n0))**0.5
    return (p1-p0)/se if se>0 else 0.0

def get(g,o,rk): return acc.get((g,o,rk),[0,0])

for oname in ("HH_next","up_close"):
    print(f"\n================  outcome: {oname}  ================")
    for rk in ("all","bull","nonbull"):
        bn,bk = get("__baseline__",oname,rk); pbase = bk/bn if bn else float("nan")
        print(f"\n  regime={rk}   baseline(random date) p={pbase:.4f}  n={bn:,}")
        for g in ("dir","band","both"):
            gn,gk = get(g,oname,rk)
            if not gn: print(f"    {g:5}: no fires"); continue
            pg = gk/gn; n0,k0 = bn-gn, bk-gk; z = two_prop_z(gk,gn,k0,n0)
            print(f"    {g:5}: p={pg:.4f}  lift_vs_random={pg-pbase:+.4f}  z={z:+.1f}  n={gn:,}")
        # Q1: band's marginal effect GIVEN direction = both vs dir_not_band
        bo_n,bo_k = get("both",oname,rk); dn_n,dn_k = get("dir_not_band",oname,rk)
        if bo_n and dn_n:
            z = two_prop_z(bo_k,bo_n,dn_k,dn_n)
            print(f"    Q1 band-given-dir : p(both)={bo_k/bo_n:.4f} vs p(dir,no-band)={dn_k/dn_n:.4f}  delta={bo_k/bo_n-dn_k/dn_n:+.4f}  z={z:+.1f}")
        # Q2: direction's marginal effect GIVEN band = both vs band_not_dir
        bd_n,bd_k = get("band_not_dir",oname,rk)
        if bo_n and bd_n:
            z = two_prop_z(bo_k,bo_n,bd_k,bd_n)
            print(f"    Q2 dir-given-band : p(both)={bo_k/bo_n:.4f} vs p(band,no-dir)={bd_k/bd_n:.4f}  delta={bo_k/bo_n-bd_k/bd_n:+.4f}  z={z:+.1f}")
