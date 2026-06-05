"""Lock the p21 ADX filter: time-split + cost check.

Config: bull regime, ADX(period=21) > 25, no upper cap, direction OFF, rising OFF.
Measurement: ATR 2:1 runner (TP=2*ATR14, SL=1*ATR14), windows 10 & 15, vol floor
0.5%, episode-start de-overlap, SYMBOL-CLUSTERED stats.

Costs: round-trip cost in bps of entry price -> per-trade cost_R = cost_frac/(ATR/close),
subtracted from BOTH signal and baseline trades. Reports, per half x cost:
  signal NET absolute expectancy (mean across symbols, t vs 0)  -> is it profitable?
  NET lift vs random-entry baseline (symbol-clustered, t)        -> does the filter add value?
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"; SPLIT="2021-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; MIN_BASE_BARS=15; TP_ATR,SL_ATR=2.0,1.0
PERIOD,ADX_MIN,ADX_MAX=21,25,999
WINDOWS=[10,15]; COSTS_BPS=[0,5,10,20]

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["ema50"]=talib.EMA(spy.close,50); spy["ema200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.ema200)&(spy.ema50>spy.ema200)
spy_regime=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return spy_regime.get(str(d)[:10],False)

syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"{len(syms)} symbols, split {SPLIT}, config p{PERIOD} adx>{ADX_MIN} bull di=off",flush=True)

# (N, half, cost) -> dict with signal: [sumExp,sumsqExp,nsym, nep]  and lift: [sumL,sumsqL,nsym]
accS={}; accL={}
def bumpS(N,half,cost,exp,ne):
    k=(N,half,cost); a=accS.get(k)
    if a is None: accS[k]=a=[0.0,0.0,0,0]
    a[0]+=exp; a[1]+=exp*exp; a[2]+=1; a[3]+=ne
def bumpL(N,half,cost,lift):
    k=(N,half,cost); a=accL.get(k)
    if a is None: accL[k]=a=[0.0,0.0,0]
    a[0]+=lift; a[1]+=lift*lift; a[2]+=1

def bracket(h,l,c,atr,N):
    n=len(c); tp=c+TP_ATR*atr; sl=c-SL_ATR*atr; Rp=SL_ATR*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan); valid=(np.arange(n)<(n-N))&(atr>0)&~np.isnan(atr)
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp[:n-k]; slh[:n-k]=l[k:]<=sl[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=TP_ATR/SL_ATR; resolved|=(loss|wn)
    ex=np.full(n,np.nan); ex[:n-N]=c[N:][:n-N] if n-N>0 else ex[:n-N]
    to=valid&~resolved; res[to]=(ex[to]-c[to])/Rp[to]
    return res,valid

for i,sym in enumerate(syms):
    if i%300==0: print(f"  {i}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dates=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan)
    eligible=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    bull=np.array([isbull(x) for x in dates])
    adx=talib.ADX(h,l,c,PERIOD); m=(adx>ADX_MIN)&(adx<ADX_MAX)
    m_start=m&~np.concatenate([[False],m[:-1]])
    h1=dates<SPLIT
    for N in WINDOWS:
        res,valid=bracket(h,l,c,atr,N)
        base0=eligible&valid&~np.isnan(res)&bull
        sig0=m_start&base0
        for half,hm in (("H1_16-20",h1),("H2_21-26",~h1)):
            bmask=base0&hm; smask=sig0&hm
            if smask.sum()<1 or bmask.sum()<MIN_BASE_BARS: continue
            ne=int(smask.sum())
            for cb in COSTS_BPS:
                cf=cb/10000.0; cost_R=cf/atr_pct          # per-bar cost in R
                bnet=res[bmask]-cost_R[bmask]; snet=res[smask]-cost_R[smask]
                sexp=snet.mean()
                bumpS(N,half,cb,sexp,ne)
                bumpL(N,half,cb,sexp-bnet.mean())

def rep(acc,k):
    a=acc.get(k)
    if not a: return None
    if len(a)==4: s,ss,ns,ne=a
    else: s,ss,ns=a; ne=None
    mean=s/ns; var=max(ss/ns-mean*mean,0); se=(var/ns)**0.5; t=mean/se if se>0 else 0.0
    return mean,t,ns,ne

for N in WINDOWS:
    print(f"\n================  N={N} days  ================")
    for half in ("H1_16-20","H2_21-26"):
        print(f"\n  --- {half} ---")
        print(f"      {'cost':>6} | {'signal NET exp':>16} | {'NET lift vs random':>20} | n_sym  n_ep")
        for cb in COSTS_BPS:
            S=rep(accS,(N,half,cb)); L=rep(accL,(N,half,cb))
            if not S: print(f"      {cb:>4}bp | (no data)"); continue
            sm,st,ns,ne=S; lm,lt,_,_=L
            print(f"      {cb:>4}bp | {sm:+.4f}R (t={st:+.1f}) | {lm:+.4f}R (t={lt:+.1f}) | {ns:<5} {ne}")
