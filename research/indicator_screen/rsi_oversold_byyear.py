"""Deep-oversold edge, year by year — stop guessing where the era boundary goes.

Brand's point: SPLIT=2021 buries COVID (Mar 2020, the biggest deep-oversold snapback ever) inside
H1, and the calendar halves don't hold equal trade counts. So don't pick a boundary — show the
whole trajectory. Per calendar year, the deployable rule "RSI<30 for >=THR bars, flat, hold N":
mean lift vs that year's random-day baseline, clustered by symbol, with n. Plus a clean 3-era
view: PRE-COVID (2016-2020-02) / COVID-2020 (2020-03..2020-12) / POST (2021+).

Reveals: when did daily mean-reversion turn on? is 2020 an outlier? still on in 2025-26?
"""
import numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; N=10; TP_ATR,SL_ATR=2.0,1.0; MIN_BASE=15; THR=3   # the sweet-spot rule

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg.get(str(d)[:10],False)
print(f"{len(syms)} syms, rule: RSI<{OS:.0f} for >={THR} bars, hold {N}, {TP_ATR:.0f}:{SL_ATR:.0f}",flush=True)

def bracket(h,l,c,atr,N,tp_atr,sl_atr):
    n=len(c); tp=c+tp_atr*atr; sl=c-sl_atr*atr; Rp=sl_atr*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan)
    valid=(np.arange(n)<(n-N))&(atr>0)&~np.isnan(atr)
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp[:n-k]; slh[:n-k]=l[k:]<=sl[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=tp_atr/sl_atr; resolved|=(loss|wn)
    ex=np.full(n,np.nan); ex[:n-N]=c[N:][:n-N] if n-N>0 else ex[:n-N]
    to=valid&~resolved; res[to]=(ex[to]-c[to])/Rp[to]
    return res,valid

def sim(idx_sorted):
    out=[]; in_until=-1
    for i in idx_sorted:
        if i<=in_until: continue
        out.append(i); in_until=i+N
    return out

def era_of(ym):  # ym = 'YYYY-MM'
    if ym<"2020-03": return "1_pre-COVID(16-20Feb)"
    if ym<"2021-01": return "2_COVID-2020(Mar-Dec)"
    return "3_post(2021+)"

# clustered: key -> [sumLift,sumsqLift,nsym,ntr]
yr=defaultdict(lambda:[0.,0.,0,0]); er=defaultdict(lambda:[0.,0.,0,0])
def bump(store,key,lift,nt):
    a=store[key]; a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt

for ii,sym in enumerate(syms):
    if ii%300==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    res,valid=bracket(h,l,c,atr,N,TP_ATR,SL_ATR); ok=elig&valid&~np.isnan(res)
    os=rsi<OS
    age=np.full(n,-1,int); run=0
    for i in range(n):
        if os[i]: age[i]=run; run+=1
        else: run=0
    cand=np.where(ok&(age>=THR))[0]
    ent=sim(cand)
    years=np.array([dts[i][:4] for i in range(n)])
    yms=np.array([dts[i][:7] for i in range(n)])
    # per-year: lift vs that year's eligible-bar baseline (same symbol)
    for label,grpfn in (("year",lambda i:dts[i][:4]),("era",lambda i:era_of(yms[i]))):
        store=yr if label=="year" else er
        byg=defaultdict(list)
        for i in ent: byg[grpfn(i)].append(res[i])
        for g,rs in byg.items():
            # baseline = mean over eligible-valid bars in same group for this symbol
            if label=="year": gmask=ok&(years==g)
            else: gmask=ok&np.array([era_of(x)==g for x in yms])
            if gmask.sum()<MIN_BASE or len(rs)<1: continue
            bump(store,g, np.mean(rs)-res[gmask].mean(), len(rs))

def show(store,title):
    print(f"\n############### {title} ###############")
    print(f"  {'bucket':>24} | {'deep-oversold lift':>20} | n_sym  n_trades")
    for g in sorted(store):
        s,ss,ns,nt=store[g]
        if ns<20: print(f"  {g:>24} | (thin: {ns} syms)"); continue
        m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5; t=m/se if se>0 else 0
        bar="#"*max(0,int(round(m*40))) if m>0 else ""
        print(f"  {g:>24} | {m:+.4f}R t={t:+5.1f} | {ns:>4}  {nt:>6}  {bar}")

show(er,"3-ERA (COVID isolated)")
show(yr,"YEAR-BY-YEAR trajectory")
