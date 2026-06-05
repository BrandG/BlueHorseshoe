"""Per-indicator edge screen — does each famous indicator's textbook signal beat
'just being long' over the next N days, and does it depend on horizon/regime?

For each canonical bullish signal we accumulate forward close-to-close returns at
horizons {1,3,5,10,20} and compare the conditional mean to the UNCONDITIONAL
baseline (every eligible bar = the 'random long entry' benchmark) over the same
horizon and regime. Edge = mean[signal] - baseline. Streaming aggregation
(per-symbol, no giant panel) so it's memory-safe on the 4-vCPU box.
"""
import json
import numpy as np
import pandas as pd
import talib
import duckdb

SEED = 7
N_SYMBOLS = 2000
START = "2016-01-01"
PRICE_MIN, PRICE_MAX, MIN_VOL = 5.0, 500.0, 100_000
HORIZONS = [1, 3, 5, 10, 20]

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

# accumulators: key (name,h,regime) -> [n, sum, sumsq]
acc = {}
def bump(name, h, rk, v):
    k = (name, h, rk)
    a = acc.get(k)
    if a is None: acc[k] = a = [0, 0.0, 0.0]
    a[0] += len(v); a[1] += float(v.sum()); a[2] += float((v*v).sum())

def cross_up(a, b):
    out = np.zeros(len(a), bool)
    out[1:] = (a[1:] > b[1:]) & (a[:-1] <= b[:-1])
    return out

for i, sym in enumerate(syms):
    if i % 400 == 0: print(f"  {i}/{len(syms)}", flush=True)
    d = con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date", [sym, START]).df()
    if len(d) < 250: continue
    o,h,l,c,v = (d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dates = d.date.astype(str).str[:10].to_numpy()
    n = len(c)

    rsi = talib.RSI(c,14); willr = talib.WILLR(h,l,c,14)
    slowk,_ = talib.STOCH(h,l,c,14,3,0,3,0); cci = talib.CCI(h,l,c,20)
    up,mid,lo = talib.BBANDS(c,20,2,2); macd,sig,_ = talib.MACD(c,12,26,9)
    roc = talib.ROC(c,10); adx = talib.ADX(h,l,c,14); pdi = talib.PLUS_DI(h,l,c,14); mdi = talib.MINUS_DI(h,l,c,14)
    arup = talib.AROONOSC(h,l,25); obv = talib.OBV(c,v); mfi = talib.MFI(h,l,c,v,14)
    eng = talib.CDLENGULFING(o,h,l,c); ham = talib.CDLHAMMER(o,h,l,c)
    sma50 = talib.SMA(c,50); sma200 = talib.SMA(c,200); sma20 = talib.SMA(c,20)
    vol20 = pd.Series(v).rolling(20).mean().to_numpy()
    don20 = pd.Series(h).rolling(20).max().shift(1).to_numpy()
    # CMF(20)
    rng_hl = (h-l); rng_hl[rng_hl==0] = np.nan
    mfv = ((c-l)-(h-c))/rng_hl * v
    cmf = (pd.Series(mfv).rolling(20).sum()/pd.Series(v).rolling(20).sum()).to_numpy()

    sig = {
        "rsi_oversold(<30)":        rsi < 30,
        "rsi_exit_oversold(x30up)": cross_up(rsi, np.full(n,30.0)),
        "rsi_bull(>50)":            rsi > 50,
        "williams_oversold(<-80)":  willr < -80,
        "stoch_oversold(<20)":      slowk < 20,
        "cci_oversold(<-100)":      cci < -100,
        "cci_break(x+100up)":       cross_up(cci, np.full(n,100.0)),
        "bb_lower_touch":           c <= lo,
        "bb_upper_break(x up)":     cross_up(c, up),
        "macd_bull_cross":          cross_up(macd, sig),
        "roc_pos(>0)":              roc > 0,
        "adx_uptrend(>25,+DI)":     (adx > 25) & (pdi > mdi),
        "donchian20_break":         c > don20,
        "aroonosc_up(>50)":         arup > 50,
        "obv_rising(10d)":          np.concatenate([np.full(10,False), obv[10:] > obv[:-10]]),
        "cmf_pos(>0)":              cmf > 0,
        "mfi_oversold(<20)":        mfi < 20,
        "rvol_high(>1.5x)":         v > 1.5*vol20,
        "engulfing_bull":           eng > 0,
        "hammer":                   ham > 0,
        "gap_up(>2%)":              np.concatenate([[False], o[1:] > c[:-1]*1.02]),
        "above_sma200":             c > sma200,
        "golden_cross":             cross_up(sma50, sma200),
        "sma50_reclaim(x up)":      cross_up(c, sma50),
        "sma20_pullback_uptrend":   (c > sma50) & (l <= sma20) & (c > sma20),
    }

    eligible = (c >= PRICE_MIN) & (c <= PRICE_MAX) & (vol20 > MIN_VOL)
    fret = {}
    for hh in HORIZONS:
        fr = np.full(n, np.nan)
        fr[:n-hh] = c[hh:]/c[:n-hh] - 1.0
        fret[hh] = fr*100.0  # percent

    regimes = np.array([reg(x) for x in dates])
    for hh in HORIZONS:
        fr = fret[hh]
        base_mask = eligible & ~np.isnan(fr)
        bump("__baseline__", hh, "all", fr[base_mask])
        for rk in ("bull","nonbull"):
            m = base_mask & (regimes==rk)
            bump("__baseline__", hh, rk, fr[m])
        for name, s in sig.items():
            s = np.asarray(s, bool)
            m = base_mask & s
            if m.any():
                bump(name, hh, "all", fr[m])
                for rk in ("bull","nonbull"):
                    mm = m & (regimes==rk)
                    if mm.any(): bump(name, hh, rk, fr[mm])

def stats(k):
    nn, s, ss = acc[k]
    if nn < 30: return None
    mean = s/nn; var = max(ss/nn - mean*mean, 0); se = (var/nn)**0.5
    return nn, mean, se

rows = []
for (name,hh,rk) in list(acc):
    if name == "__baseline__": continue
    st = stats((name,hh,rk)); bs = stats(("__baseline__",hh,rk))
    if st is None or bs is None: continue
    nn,mean,se = st; _,bmean,_ = bs
    edge = mean - bmean
    t = edge/se if se>0 else 0.0
    rows.append(dict(indicator=name, horizon=hh, regime=rk, n=nn,
                     mean_fwd=round(mean,4), baseline=round(bmean,4),
                     edge=round(edge,4), t=round(t,2)))
res = pd.DataFrame(rows)
res.to_csv("research/indicator_screen/edge_table.csv", index=False)

print("\n==== INDICATOR EDGE vs just-being-long (ALL regime) ====")
print("edge = mean fwd return when signal fires MINUS unconditional baseline, same horizon. +t>2 => beats long.\n")
a = res[res.regime=="all"].copy()
piv = a.pivot_table(index="indicator", columns="horizon", values="edge")
tpv = a.pivot_table(index="indicator", columns="horizon", values="t")
order = piv[5].sort_values(ascending=False).index
for ind in order:
    cells = " ".join(f"h{hh}:{piv.loc[ind,hh]:+.3f}({tpv.loc[ind,hh]:+.1f})" for hh in HORIZONS if not pd.isna(piv.loc[ind,hh]))
    print(f"  {ind:26} {cells}")
print("\nbaseline mean fwd return (all): " + " ".join(f"h{hh}:{stats(('__baseline__',hh,'all'))[1]:+.3f}%" for hh in HORIZONS))
print("\nsaved -> research/indicator_screen/edge_table.csv")
