"""ADX direction/band, measured like a TRADE: a 1:1 bracket (+1% before -1%).

Entry at close[t]. Win = high touches +1% BEFORE low touches -1%, within N bars.
Same-bar both-touch resolves STOP-FIRST (conservative). No barrier hit by bar N ->
timeout, marked to market at close[t+N] (return expressed in R = pct/1.0%).

Three arms vs the random-date baseline, at N = 5, 10, 15:
  dir  = +DI > -DI
  band = 25 < ADX[-1] < ADX[0] < 40
  both = dir AND band

Two money metrics per arm:
  win_rate     = P(+1% before -1% within N)         -> two-proportion z vs random date
  expectancy_R = mean realized R (win=+1, loss=-1, timeout=mtm)  -> t vs random date
"""
import numpy as np
import pandas as pd
import talib
import duckdb

SEED = 7
N_SYMBOLS = 2000
START = "2016-01-01"
PRICE_MIN, PRICE_MAX, MIN_VOL = 5.0, 500.0, 100_000
WINDOWS = [5, 10, 15]
TP, SL = 0.01, 0.01   # +1% / -1%

con = duckdb.connect("data/ohlcv.duckdb", read_only=True)
spy = con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date", [START]).df()
spy["ema50"] = talib.EMA(spy.close, 50); spy["ema200"] = talib.EMA(spy.close, 200)
spy["bull"] = (spy.close > spy.ema200) & (spy.ema50 > spy.ema200)
spy_regime = dict(zip(spy.date.astype(str).str[:10], spy.bull))
def reg(d): return "bull" if spy_regime.get(str(d)[:10], False) else "nonbull"

syms = con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300", [START]).df().symbol.tolist()
rng = np.random.default_rng(SEED)
if len(syms) > N_SYMBOLS: syms = list(rng.choice(syms, N_SYMBOLS, replace=False))
print(f"{len(syms)} symbols", flush=True)

# acc: (group, N, regime) -> [n, k_win, sum_R, sumsq_R]
acc = {}
def bump(g, N, rk, n, kw, sR, ssR):
    key = (g, N, rk); a = acc.get(key)
    if a is None: acc[key] = a = [0, 0, 0.0, 0.0]
    a[0]+=int(n); a[1]+=int(kw); a[2]+=float(sR); a[3]+=float(ssR)

def bracket(o,h,l,c,N):
    """Return (result_R[float], win[bool], valid[bool]) for a +TP/-SL bracket over N bars."""
    n = len(c)
    tp = c*(1+TP); sl = c*(1-SL)
    resolved = np.zeros(n, bool); win = np.zeros(n, bool); res = np.full(n, np.nan)
    valid = np.arange(n) < (n-N)                      # full window available
    for k in range(1, N+1):
        tph = np.zeros(n, bool); slh = np.zeros(n, bool)
        tph[:n-k] = h[k:] >= tp[:n-k]
        slh[:n-k] = l[k:] <= sl[:n-k]
        live = valid & ~resolved & (tph | slh)
        loss = live & slh                              # stop-first on same-bar tie
        wn   = live & tph & ~slh
        res[loss] = -1.0; res[wn] = +1.0
        win[wn] = True; resolved |= (loss | wn)
    # timeouts -> mark to market at close[t+N]
    ex = np.full(n, np.nan); ex[:n-N] = c[N:][:n-N] if n-N>0 else ex[:n-N]
    to = valid & ~resolved
    res[to] = (ex[to]/c[to]-1.0)/TP                    # in R units
    return res, win, valid

for i, sym in enumerate(syms):
    if i % 400 == 0: print(f"  {i}/{len(syms)}", flush=True)
    d = con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date", [sym, START]).df()
    if len(d) < 300: continue
    o,h,l,c,v = (d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dates = d.date.astype(str).str[:10].to_numpy(); n = len(c)
    adx = talib.ADX(h,l,c,14); pdi = talib.PLUS_DI(h,l,c,14); mdi = talib.MINUS_DI(h,l,c,14)
    vol20 = pd.Series(v).rolling(20).mean().to_numpy()
    adx_p = np.concatenate([[np.nan], adx[:-1]])
    dirb = pdi > mdi
    band = (adx_p > 25) & (adx > adx_p) & (adx < 40)
    groups = {"dir": dirb, "band": band, "both": dirb & band, "__baseline__": np.ones(n, bool)}
    eligible = (c >= PRICE_MIN) & (c <= PRICE_MAX) & (vol20 > MIN_VOL)
    regimes = np.array([reg(x) for x in dates])
    for N in WINDOWS:
        res, win, valid = bracket(o,h,l,c,N)
        base_ok = eligible & valid & ~np.isnan(res)
        for gname, gmask in groups.items():
            gm = base_ok & np.asarray(gmask, bool)
            for rk in ("all","bull","nonbull"):
                m = gm if rk=="all" else gm & (regimes==rk)
                nn = int(m.sum())
                if nn:
                    r = res[m]
                    bump(gname, N, rk, nn, int(win[m].sum()), r.sum(), (r*r).sum())

def two_prop_z(k1,n1,k0,n0):
    if n1==0 or n0==0: return None
    p1,p0=k1/n1,k0/n0; pp=(k1+k0)/(n1+n0); se=(pp*(1-pp)*(1/n1+1/n0))**0.5
    return (p1-p0)/se if se>0 else 0.0
def get(g,N,rk): return acc.get((g,N,rk),[0,0,0.0,0.0])

for N in WINDOWS:
    print(f"\n================  bracket +1%/-1%  within {N} days  ================")
    for rk in ("all","bull","nonbull"):
        bn,bkw,bsR,bssR = get("__baseline__",N,rk)
        if not bn: continue
        bwr = bkw/bn; bexp = bsR/bn
        print(f"\n  regime={rk}   RANDOM DATE: win_rate={bwr:.4f}  expectancy={bexp:+.4f}R  n={bn:,}")
        for g in ("dir","band","both"):
            gn,gkw,gsR,gssR = get(g,N,rk)
            if not gn: print(f"    {g:5}: no fires"); continue
            wr=gkw/gn; exp=gsR/gn
            z=two_prop_z(gkw,gn,bkw-gkw,bn-gn)                      # win-rate vs non-signal
            var=max(gssR/gn-exp*exp,0); se=(var/gn)**0.5; tR=(exp-bexp)/se if se>0 else 0.0
            print(f"    {g:5}: win_rate={wr:.4f} (lift={wr-bwr:+.4f}, z={z:+.1f})   "
                  f"expectancy={exp:+.4f}R (lift={exp-bexp:+.4f}R, t={tR:+.1f})   n={gn:,}")
