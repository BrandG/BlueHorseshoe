"""Census for the options-IV conditioning axis: all eligible DeepOS fires with fire-date
close and nonbull slice flag for PIT option-chain backfills.

Harness = locked (news_fire_census.py / deepos_vix_*): SEED=7 N=2000; rsi<30 & age>=3;
eligibility = price 5-500, vol20>100k, atr_pct>=0.5%. Fires only (no bracket sim needed here).
"""
import os

import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; AGE=3; SLEEP=0.55
OUT="research/indicator_screen/options_fire_list.parquet"
DB="data/ohlcv.duckdb" if os.path.exists("data/ohlcv.duckdb") else "data/data/ohlcv.duckdb"

con=duckdb.connect(DB,read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300 ORDER BY symbol",[START]).df().symbol.tolist()
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")
syms=[s for s in syms if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=sorted(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"universe: {len(syms)} pinned symbols",flush=True)

fires=[]  # (symbol, date, nonbull, close)
for ii,sym in enumerate(syms):
    if ii%200==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    h,l,c,v=(d[x].to_numpy(float) for x in ("high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14)
    vol20=pd.Series(v).rolling(20).mean().to_numpy(); atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    osr=rsi<OS; age=np.zeros(n,int)
    for i in range(1,n): age[i]=age[i-1]+1 if osr[i] else 0
    deepos=osr&(age>=AGE)
    for i in np.where(deepos&elig)[0]:
        dt=dts[i]
        fires.append((sym,dt,not bool(reg_map.get(dt,False)),float(c[i])))

df=pd.DataFrame(fires,columns=["symbol","date","nonbull","close"])
df.to_parquet(OUT,index=False)
print(f"\nDeepOS fires {START}+: {len(df)}")
print(f"unique symbols: {df.symbol.nunique()}")
print("fires by year:"); print(df.date.str[:4].value_counts().sort_index().to_string())
nonbull=int(df.nonbull.sum()) if len(df) else 0
print(f"nonbull count: {nonbull}")
est_hours=len(df)*SLEEP/3600.0
print(f"estimated pull time at SLEEP={SLEEP}: {est_hours:.1f} hours (~{len(df)} API calls)")
print(f"wrote {OUT}")
