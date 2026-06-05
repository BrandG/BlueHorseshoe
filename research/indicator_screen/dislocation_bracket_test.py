"""Deep-dislocation entries vs the ATR-bracket baseline — the entry-vs-exit decider.

The honest yardstick: a random-date entry with an ATR-scaled bracket is already
positive-expectancy (esp. nonbull, longer hold, 2:1 runner). Question: does ANY of
the surviving deep-dislocation entries BEAT that baseline? If yes -> a real entry
edge measured the right way. If no -> the edge is 100% exit/structure (WS3).

Entries (the why-believed survivor family + natural capitulation variants):
  rsi_oversold(<30), rsi_deep(<20), rsi_exit_oversold(x30up),
  bb_lower_touch, stoch_oversold(<20), gap_up(>2%), gap_down(<-2%)

Brackets (ATR-scaled, R = sl_atr x ATR14):  A=1:1,  B=2:1 runner.  Windows 10 & 15.
Same-bar both-touch = stop-first (conservative). Timeout = mark-to-market in R.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
WINDOWS=[10,15]; VARIANTS={"A_1:1":(1.0,1.0),"B_2:1run":(2.0,1.0)}

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

acc={}
def bump(var,g,N,rk,n,kw,sR,ssR):
    key=(var,g,N,rk); a=acc.get(key)
    if a is None: acc[key]=a=[0,0,0.0,0.0]
    a[0]+=int(n); a[1]+=int(kw); a[2]+=float(sR); a[3]+=float(ssR)

def cross_up(a,b):
    out=np.zeros(len(a),bool); out[1:]=(a[1:]>b[1:])&(a[:-1]<=b[:-1]); return out

def bracket(h,l,c,atr,N,tp_atr,sl_atr):
    n=len(c); tp_lvl=c+tp_atr*atr; sl_lvl=c-sl_atr*atr; Rprice=sl_atr*atr
    resolved=np.zeros(n,bool); win=np.zeros(n,bool); res=np.full(n,np.nan); win_pay=tp_atr/sl_atr
    valid=(np.arange(n)<(n-N))&(atr>0)&~np.isnan(atr)
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp_lvl[:n-k]; slh[:n-k]=l[k:]<=sl_lvl[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=win_pay; win[wn]=True; resolved|=(loss|wn)
    ex=np.full(n,np.nan); ex[:n-N]=c[N:][:n-N] if n-N>0 else ex[:n-N]
    to=valid&~resolved; res[to]=(ex[to]-c[to])/Rprice[to]
    return res,win,valid

for i,sym in enumerate(syms):
    if i%400==0: print(f"  {i}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dates=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); slowk,_=talib.STOCH(h,l,c,14,3,0,3,0)
    up,mid,lo=talib.BBANDS(c,20,2,2); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    gap_up=np.concatenate([[False],o[1:]>c[:-1]*1.02])
    gap_dn=np.concatenate([[False],o[1:]<c[:-1]*0.98])
    groups={
        "rsi_os<30":      rsi<30,
        "rsi_deep<20":    rsi<20,
        "rsi_exit_x30":   cross_up(rsi,np.full(n,30.0)),
        "bb_lower_touch": c<=lo,
        "stoch_os<20":    slowk<20,
        "gap_up>2%":      gap_up,
        "gap_dn<-2%":     gap_dn,
        "__baseline__":   np.ones(n,bool),
    }
    eligible=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL); regimes=np.array([reg(x) for x in dates])
    for var,(tpa,sla) in VARIANTS.items():
        for N in WINDOWS:
            res,win,valid=bracket(h,l,c,atr,N,tpa,sla); ok=eligible&valid&~np.isnan(res)
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
ARMS=["rsi_os<30","rsi_deep<20","rsi_exit_x30","bb_lower_touch","stoch_os<20","gap_up>2%","gap_dn<-2%"]

for var in VARIANTS:
    print(f"\n##################  {var}  ##################")
    for N in WINDOWS:
        print(f"\n  ====  within {N} days  ====")
        for rk in ("all","bull","nonbull"):
            bn,bkw,bsR,_=get(var,"__baseline__",N,rk)
            if not bn: continue
            bexp=bsR/bn
            print(f"    regime={rk:7} BASELINE(random): exp={bexp:+.4f}R  win={bkw/bn:.4f}  n={bn:,}")
            for g in ARMS:
                gn,gkw,gsR,gssR=get(var,g,N,rk)
                if not gn: continue
                exp=gsR/gn; var_=max(gssR/gn-exp*exp,0); se=(var_/gn)**0.5; tR=(exp-bexp)/se if se>0 else 0.0
                flag=" <==" if (exp-bexp)>0 and tR>2 else ""
                print(f"      {g:15}: exp={exp:+.4f}R  lift={exp-bexp:+.4f}R  t={tR:+.1f}  win={gkw/gn:.4f}  n={gn:,}{flag}")
