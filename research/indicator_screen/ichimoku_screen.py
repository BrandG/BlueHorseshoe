"""Ichimoku edge screen — places Ichimoku's canonical signals in the SAME frame as
edge_table.csv (run_screen.py): forward close-to-close return when the signal fires
MINUS the unconditional 'just being long' baseline, per horizon {1,3,5,10,20} and
regime {all,bull,nonbull}. +t>2 => beats being long.

Production scorer (trend_indicators.calculate_ichimoku_score) rewards:
  price>cloud (+2), tenkan-x-up-kijun (+2), green cloud spanA>spanB (+1).
Cloud is the DISPLACED (causal) cloud: spanA[t]=mean(tenkan,kijun)[t-26],
spanB[t]=mean(52hi,52lo)[t-26]. Both known at t -> no lookahead.
Chikou bullish at t := close[t] > close[t-26] (lagging span above past price); causal.

Signals tested (long side + the dislocation mirror):
  above_cloud (state), cloud_breakout (event), tk_bull_cross (event),
  tk_above_kijun (state), green_cloud (state), chikou_above (state),
  perfect_bull (all-aligned), below_cloud (dislocation), in_cloud (transition).
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
HORIZONS=[1,3,5,10,20]
DISP=26  # cloud forward displacement / chikou lag

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def reg(d): return "bull" if reg_map.get(str(d)[:10],False) else "nonbull"

syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"{len(syms)} symbols",flush=True)

acc={}
def bump(name,h,rk,v):
    k=(name,h,rk); a=acc.get(k)
    if a is None: acc[k]=a=[0,0.0,0.0]
    a[0]+=len(v); a[1]+=float(v.sum()); a[2]+=float((v*v).sum())

def cross_up(a,b):
    out=np.zeros(len(a),bool); out[1:]=(a[1:]>b[1:])&(a[:-1]<=b[:-1]); return out

def roll_max(x,w): return pd.Series(x).rolling(w).max().to_numpy()
def roll_min(x,w): return pd.Series(x).rolling(w).min().to_numpy()

for i,sym in enumerate(syms):
    if i%400==0: print(f"  {i}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<250: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dates=d.date.astype(str).str[:10].to_numpy(); n=len(c)

    tenkan=(roll_max(h,9)+roll_min(l,9))/2
    kijun=(roll_max(h,26)+roll_min(l,26))/2
    spanA=np.full(n,np.nan); spanB=np.full(n,np.nan)
    sa=(tenkan+kijun)/2
    sb=(roll_max(h,52)+roll_min(l,52))/2
    spanA[DISP:]=sa[:n-DISP]      # displaced forward 26 (causal at t)
    spanB[DISP:]=sb[:n-DISP]
    top=np.fmax(spanA,spanB); bot=np.fmin(spanA,spanB)
    chikou_above=np.zeros(n,bool); chikou_above[DISP:]=c[DISP:]>c[:n-DISP]

    above=c>top; below=c<bot
    green=spanA>spanB
    tk_state=tenkan>kijun
    sig={
        "ichi_above_cloud":      above,
        "ichi_cloud_breakout":   cross_up(c,top),
        "ichi_tk_bull_cross":    cross_up(tenkan,kijun),
        "ichi_tk_above_kijun":   tk_state,
        "ichi_green_cloud":      green,
        "ichi_chikou_above":     chikou_above,
        "ichi_perfect_bull":     above&tk_state&green&chikou_above,
        "ichi_below_cloud":      below,
        "ichi_in_cloud":         (~above)&(~below)&~np.isnan(top),
    }

    vol20=pd.Series(v).rolling(20).mean().to_numpy()
    eligible=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)
    fret={}
    for hh in HORIZONS:
        fr=np.full(n,np.nan); fr[:n-hh]=c[hh:]/c[:n-hh]-1.0; fret[hh]=fr*100.0
    regimes=np.array([reg(x) for x in dates])
    for hh in HORIZONS:
        fr=fret[hh]; base=eligible&~np.isnan(fr)
        bump("__baseline__",hh,"all",fr[base])
        for rk in ("bull","nonbull"):
            m=base&(regimes==rk); bump("__baseline__",hh,rk,fr[m])
        for name,s in sig.items():
            s=np.asarray(s,bool); m=base&s
            if m.any():
                bump(name,hh,"all",fr[m])
                for rk in ("bull","nonbull"):
                    mm=m&(regimes==rk)
                    if mm.any(): bump(name,hh,rk,fr[mm])

def stats(k):
    a=acc.get(k)
    if not a or a[0]<30: return None
    nn,s,ss=a; mean=s/nn; var=max(ss/nn-mean*mean,0); se=(var/nn)**0.5
    return nn,mean,se

rows=[]
for (name,hh,rk) in list(acc):
    if name=="__baseline__": continue
    st=stats((name,hh,rk)); bs=stats(("__baseline__",hh,rk))
    if st is None or bs is None: continue
    nn,mean,se=st; _,bmean,_=bs; edge=mean-bmean; t=edge/se if se>0 else 0.0
    rows.append(dict(indicator=name,horizon=hh,regime=rk,n=nn,
                     mean_fwd=round(mean,4),baseline=round(bmean,4),
                     edge=round(edge,4),t=round(t,2)))
res=pd.DataFrame(rows)
res.to_csv("research/indicator_screen/ichimoku_edge.csv",index=False)

for RK in ("all","bull","nonbull"):
    print(f"\n==== ICHIMOKU EDGE vs just-being-long  [{RK}] ====")
    a=res[res.regime==RK]
    if a.empty: continue
    piv=a.pivot_table(index="indicator",columns="horizon",values="edge")
    tpv=a.pivot_table(index="indicator",columns="horizon",values="t")
    npv=a.pivot_table(index="indicator",columns="horizon",values="n")
    order=piv[10].sort_values(ascending=False).index if 10 in piv.columns else piv.index
    for ind in order:
        cells=" ".join(f"h{hh}:{piv.loc[ind,hh]:+.3f}({tpv.loc[ind,hh]:+.1f})" for hh in HORIZONS if hh in piv.columns and not pd.isna(piv.loc[ind,hh]))
        nmax=int(npv.loc[ind].max()) if ind in npv.index else 0
        print(f"  {ind:22} n~{nmax:>7} {cells}")
    b=stats(("__baseline__",10,RK))
    print(f"  baseline fwd: "+" ".join(f"h{hh}:{stats(('__baseline__',hh,RK))[1]:+.3f}%" for hh in HORIZONS))
print("\nsaved -> research/indicator_screen/ichimoku_edge.csv")
