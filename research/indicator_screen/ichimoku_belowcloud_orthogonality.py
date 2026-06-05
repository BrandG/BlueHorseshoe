"""Is 'price below the Ichimoku cloud, nonbull regime' a REAL, NON-REDUNDANT sleeve,
or is it just rsi<30 in disguise? And what's the honest (symbol-clustered, de-overlapped)
error bar — not the overlapping-window t=18.6 from the screen?

Three things:
  (A) Symbol-CLUSTERED mean lift of below_cloud vs same-regime baseline, h10 & h20,
      using ONE non-overlapping entry per symbol every N bars (de-overlap), nonbull only.
  (B) Overlap with rsi<30: of below_cloud-nonbull bars, what % are also rsi<30?
      Edge of below_cloud AND NOT rsi<30 (the part RSI can't see) vs baseline.
      Edge of rsi<30 AND NOT below_cloud (what the cloud can't see).
  (C) Dislocation DEPTH: cloud distance (how far below the cloud, in ATR) — does the
      edge live deeper, like rsi_oversold's depth result?
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
DISP=26
con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg_map.get(str(d)[:10],False)

syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"{len(syms)} symbols",flush=True)

def roll_max(x,w): return pd.Series(x).rolling(w).max().to_numpy()
def roll_min(x,w): return pd.Series(x).rolling(w).min().to_numpy()

# clustered accumulators: key -> [sum_of_persymbol_lift, sumsq, n_sym, n_trades]
acc={}
def bump(key,lift,nt):
    a=acc.setdefault(key,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt

def fwd(c,hh):
    fr=np.full(len(c),np.nan); fr[:len(c)-hh]=c[hh:]/c[:len(c)-hh]-1.0; return fr*100.0

def sim_nonoverlap(mask,res,N):
    out=[]; until=-1
    for i in np.where(mask&~np.isnan(res))[0]:
        if i<=until: continue
        out.append(i); until=i+N
    return out

DEPTH_BUCKETS=[("0-0.5atr",0,0.5),("0.5-1.5",0.5,1.5),("1.5-3",1.5,3.0),("3+",3.0,1e9)]

for ii,sym in enumerate(syms):
    if ii%400==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan)
    tenkan=(roll_max(h,9)+roll_min(l,9))/2; kijun=(roll_max(h,26)+roll_min(l,26))/2
    spanA=np.full(n,np.nan); spanB=np.full(n,np.nan)
    spanA[DISP:]=((tenkan+kijun)/2)[:n-DISP]; spanB[DISP:]=((roll_max(h,52)+roll_min(l,52))/2)[:n-DISP]
    bot=np.fmin(spanA,spanB)
    below=c<bot
    depth=np.where(below&(atr>0),(bot-c)/atr,np.nan)  # how far below cloud, in ATR
    os=rsi<30
    nonbull=~np.array([isbull(x) for x in dts])
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)&nonbull

    for hh,N in ((10,10),(20,20)):
        res=fwd(c,hh); ok=elig&~np.isnan(res)
        if ok.sum()<30: continue
        bmean=res[ok].mean()
        # (A) de-overlapped below_cloud lift, clustered
        ent=sim_nonoverlap(below&ok,res,N)
        if ent: bump(("below",hh), np.mean([res[i] for i in ent])-bmean, len(ent))
        rnd=sim_nonoverlap(ok,res,N)
        if rnd: bump(("rand",hh), np.mean([res[i] for i in rnd])-bmean, len(rnd))
        # (B) orthogonality vs rsi<30 (de-overlapped within each subset)
        e_bc_not_os=sim_nonoverlap(below&~os&ok,res,N)
        if e_bc_not_os: bump(("below_not_os",hh), np.mean([res[i] for i in e_bc_not_os])-bmean, len(e_bc_not_os))
        e_os_not_bc=sim_nonoverlap(os&~below&ok,res,N)
        if e_os_not_bc: bump(("os_not_below",hh), np.mean([res[i] for i in e_os_not_bc])-bmean, len(e_os_not_bc))
        e_both=sim_nonoverlap(os&below&ok,res,N)
        if e_both: bump(("both",hh), np.mean([res[i] for i in e_both])-bmean, len(e_both))
        # overlap fraction (population, not de-overlapped)
        nb=int((below&ok).sum())
        if nb: bump(("overlapfrac",hh), float((below&os&ok).sum())/nb, nb)
        # (C) depth buckets (all below-cloud bars, not de-overlapped; lift vs baseline)
        for bn,lo,hi in DEPTH_BUCKETS:
            m=below&ok&(depth>=lo)&(depth<hi)
            if m.any(): bump(("depth",bn,hh), res[m].mean()-bmean, int(m.sum()))

def stat(key):
    a=acc.get(key)
    if not a or a[2]<30: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt

def f(x): return f"{x[0]:+.3f}% t={x[1]:+.1f} nsym={x[2]} nt={x[3]}" if x else "(n<30)"

print("\n### (A) below-cloud nonbull, SYMBOL-CLUSTERED + DE-OVERLAPPED (honest error bars) ###")
for hh in (10,20):
    print(f"  h{hh}: below_cloud {f(stat(('below',hh)))}")
    print(f"        random     {f(stat(('rand',hh)))}")

print("\n### (B) orthogonality vs rsi<30 (de-overlapped) ###")
for hh in (10,20):
    ov=stat(("overlapfrac",hh))
    print(f"  h{hh}: overlap (frac of below-cloud bars that are also rsi<30): {ov[0]*100:.1f}%" if ov else f"  h{hh}: (thin)")
    print(f"        below & NOT rsi<30 (cloud-only):  {f(stat(('below_not_os',hh)))}")
    print(f"        rsi<30 & NOT below (rsi-only):    {f(stat(('os_not_below',hh)))}")
    print(f"        both:                              {f(stat(('both',hh)))}")

print("\n### (C) edge by cloud DEPTH (ATR below cloud), nonbull ###")
for hh in (10,20):
    print(f"  h{hh}: "+" | ".join(f"{bn}:{(lambda x: f'{x[0]:+.3f}%(t{x[1]:+.0f})' if x else '(n<30)')(stat(('depth',bn,hh)))}" for bn,_,_ in DEPTH_BUCKETS))
