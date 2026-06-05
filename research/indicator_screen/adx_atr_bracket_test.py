"""ADX direction/band measured with ATR-scaled brackets — barriers sit OUTSIDE
one bar's normal noise, so we stop measuring the intrabar both-touch artifact and
start measuring real directional follow-through.

Risk unit R = (sl_atr x ATR14) in price. Two variants:
  A  ATR 1:1   : TP=+1*ATR, SL=-1*ATR  -> win=+1R, loss=-1R   (breakeven WR 50%)
  B  ATR 2:1   : TP=+2*ATR, SL=-1*ATR  -> win=+2R, loss=-1R   (breakeven WR 33%) -- let winners run

Entry close[t]. Same-bar both-touch = STOP-FIRST (conservative). Timeout at bar N -> mark to
market in R. Three arms (dir / band / both) vs random-date baseline, at N=5,10,15.
Metrics: win_rate (P TP-first) and expectancy_R (the money number).
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
WINDOWS=[5,10,15]
VARIANTS={"A_ATR_1:1":(1.0,1.0), "B_ATR_2:1run":(2.0,1.0)}

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["ema50"]=talib.EMA(spy.close,50); spy["ema200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.ema200)&(spy.ema50>spy.ema200)
spy_regime=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def reg(d): return "bull" if spy_regime.get(str(d)[:10],False) else "nonbull"

syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"{len(syms)} symbols",flush=True)

acc={}  # (variant, group, N, regime) -> [n, k_win, sum_R, sumsq_R]
def bump(var,g,N,rk,n,kw,sR,ssR):
    key=(var,g,N,rk); a=acc.get(key)
    if a is None: acc[key]=a=[0,0,0.0,0.0]
    a[0]+=int(n); a[1]+=int(kw); a[2]+=float(sR); a[3]+=float(ssR)

def bracket(h,l,c,atr,N,tp_atr,sl_atr):
    n=len(c)
    tp_lvl=c+tp_atr*atr; sl_lvl=c-sl_atr*atr; Rprice=sl_atr*atr
    resolved=np.zeros(n,bool); win=np.zeros(n,bool); res=np.full(n,np.nan)
    win_pay=tp_atr/sl_atr
    valid=(np.arange(n)<(n-N)) & (atr>0) & ~np.isnan(atr)
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp_lvl[:n-k]; slh[:n-k]=l[k:]<=sl_lvl[:n-k]
        live=valid&~resolved&(tph|slh)
        loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=win_pay; win[wn]=True; resolved|=(loss|wn)
    ex=np.full(n,np.nan); ex[:n-N]=c[N:][:n-N] if n-N>0 else ex[:n-N]
    to=valid&~resolved
    res[to]=(ex[to]-c[to])/Rprice[to]
    return res,win,valid

for i,sym in enumerate(syms):
    if i%400==0: print(f"  {i}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dates=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    adx=talib.ADX(h,l,c,14); pdi=talib.PLUS_DI(h,l,c,14); mdi=talib.MINUS_DI(h,l,c,14)
    atr=talib.ATR(h,l,c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    adx_p=np.concatenate([[np.nan],adx[:-1]])
    dirb=pdi>mdi; band=(adx_p>25)&(adx>adx_p)&(adx<40)
    groups={"dir":dirb,"band":band,"both":dirb&band,"__baseline__":np.ones(n,bool)}
    eligible=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)
    regimes=np.array([reg(x) for x in dates])
    for var,(tpa,sla) in VARIANTS.items():
        for N in WINDOWS:
            res,win,valid=bracket(h,l,c,atr,N,tpa,sla)
            ok=eligible&valid&~np.isnan(res)
            for gname,gmask in groups.items():
                gm=ok&np.asarray(gmask,bool)
                for rk in ("all","bull","nonbull"):
                    m=gm if rk=="all" else gm&(regimes==rk)
                    nn=int(m.sum())
                    if nn:
                        r=res[m]; bump(var,gname,N,rk,nn,int(win[m].sum()),r.sum(),(r*r).sum())

def zprop(k1,n1,k0,n0):
    if n1==0 or n0==0: return 0.0
    p1,p0=k1/n1,k0/n0; pp=(k1+k0)/(n1+n0); se=(pp*(1-pp)*(1/n1+1/n0))**0.5
    return (p1-p0)/se if se>0 else 0.0
def get(var,g,N,rk): return acc.get((var,g,N,rk),[0,0,0.0,0.0])

for var in VARIANTS:
    be = 1.0/(1.0+VARIANTS[var][0]/VARIANTS[var][1])   # breakeven win rate
    print(f"\n##################  {var}   (breakeven win_rate={be:.3f})  ##################")
    for N in WINDOWS:
        print(f"\n  ====  within {N} days  ====")
        for rk in ("all","bull","nonbull"):
            bn,bkw,bsR,_=get(var,"__baseline__",N,rk)
            if not bn: continue
            print(f"    regime={rk:7} RANDOM: win={bkw/bn:.4f} exp={bsR/bn:+.4f}R n={bn:,}")
            for g in ("dir","band","both"):
                gn,gkw,gsR,gssR=get(var,g,N,rk)
                if not gn: continue
                wr=gkw/gn; exp=gsR/gn
                z=zprop(gkw,gn,bkw-gkw,bn-gn)
                var_=max(gssR/gn-exp*exp,0); se=(var_/gn)**0.5; tR=(exp-bsR/bn)/se if se>0 else 0.0
                print(f"      {g:5}: win={wr:.4f}(z={z:+.1f})  exp={exp:+.4f}R(lift={exp-bsR/bn:+.4f}, t={tR:+.1f})  n={gn:,}")
