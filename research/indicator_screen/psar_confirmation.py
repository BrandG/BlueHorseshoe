"""PSAR as a CONFIRMATION signal: in which observable states does a PSAR flip-up
carry a TIME-STABLE edge?

For each independent conditioning factor, bucket bars by the factor's state at trigger
time, and measure how much a PSAR flip-up ADDS over a random entry IN THE SAME BUCKET
(symbol-clustered lift). Report overall + both time halves. A bucket only "confirms"
if the lift is positive & significant in BOTH halves (else it's regime-luck).

PSAR fixed at default af=(0.02,0.2) to avoid config-mining. Clean harness: ATR 2:1
runner, vol floor, episode-start de-overlap, symbol-clustered.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"; SPLIT="2021-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
N=10; TP_ATR,SL_ATR=2.0,1.0; MIN_BASE=10

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg.get(str(d)[:10],False)
print(f"{len(syms)} symbols",flush=True)

def cross_up(a,b):
    out=np.zeros(len(a),bool); out[1:]=(a[1:]>b[1:])&(a[:-1]<=b[:-1]); return out
def estart(m): return m&~np.concatenate([[False],m[:-1]])
def shift1(a):
    out=np.full(len(a),np.nan); out[1:]=a[:-1]; return out
def bracket(h,l,c,atr):
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

# acc: (factor,bucket,half) -> [sumLift,sumsq,nsym,nep]
acc={}
def bump(f,b,half,lift,ne):
    k=(f,b,half); a=acc.get(k)
    if a is None: acc[k]=a=[0.,0.,0,0]
    a[0]+=lift;a[1]+=lift*lift;a[2]+=1;a[3]+=ne

for i,sym in enumerate(syms):
    if i%300==0: print(f"  {i}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy(); atr_pct=atr/np.where(c>0,c,np.nan)
    rsi=talib.RSI(c,14); adx=talib.ADX(h,l,c,14); rvol=v/vol20
    sma50=talib.SMA(c,50); macd,sg,_=talib.MACD(c,12,26,9); p20=shift1(pd.Series(h).rolling(20).max().to_numpy())
    TE=cross_up(c,sma50)|cross_up(c,p20)|cross_up(macd,sg)
    flip=estart(c>talib.SAR(h,l,0.02,0.2))
    bull=np.array([isbull(x) for x in dts]); h1=dts<SPLIT
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    res,valid=bracket(h,l,c,atr); base0=elig&valid&~np.isnan(res)

    # define buckets (string label per bar, '' = undefined)
    FB={}
    FB["regime"]=np.where(bull,"bull","nonbull")
    FB["adx"]=np.where(np.isnan(adx),"",np.where(adx<20,"adx<20",np.where(adx<30,"adx20-30","adx>=30")))
    FB["atr"]=np.where(np.isnan(atr_pct),"",np.where(atr_pct<0.02,"atr<2%",np.where(atr_pct<0.04,"atr2-4%","atr>=4%")))
    FB["rvol"]=np.where(np.isnan(rvol),"",np.where(rvol<0.8,"rvol<.8",np.where(rvol<1.2,"rvol.8-1.2","rvol>=1.2")))
    FB["rsi"]=np.where(np.isnan(rsi),"",np.where(rsi<30,"rsi<30",np.where(rsi<50,"rsi30-50",np.where(rsi<70,"rsi50-70","rsi>=70"))))
    FB["breakout"]=np.where(TE,"with_TE","no_TE")

    for fac,lab in FB.items():
        for half,hm in (("ALL",np.ones(n,bool)),("H1",h1),("H2",~h1)):
            for b in set(lab):
                if b=="": continue
                bm=base0&(lab==b)&hm
                if bm.sum()<MIN_BASE: continue
                sm=bm&flip; ne=int(sm.sum())
                if ne>=1:
                    bump(fac,b,half,res[sm].mean()-res[bm].mean(),ne)

def st(f,b,half):
    a=acc.get((f,b,half))
    if not a or a[2]<50: return None
    sL,ss,ns,ne=a; m=sL/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,ne

FACS=["regime","rsi","adx","atr","rvol","breakout"]
print("\n==== PSAR flip-up edge ADDED within each state (lift vs random-in-bucket) ====")
print(f"  {'factor/bucket':16} | {'ALL':>16} | {'H1 16-20':>14} | {'H2 21-26':>14} | stable?")
STABLE=[]
for f in FACS:
    buckets=sorted({k[1] for k in acc if k[0]==f})
    for b in buckets:
        A=st(f,b,"ALL"); H1=st(f,b,"H1"); H2=st(f,b,"H2")
        if not A: continue
        def fmt(x): return f"{x[0]:+.3f}R(t{x[1]:+.1f})" if x else "  --"
        stable = H1 and H2 and H1[0]>0 and H2[0]>0 and H1[1]>1.5 and H2[1]>1.5 and A[1]>2
        tag="  <== STABLE" if stable else ""
        if stable: STABLE.append((f,b,A))
        print(f"  {f+'/'+b:16} | {fmt(A):>16} | {fmt(H1):>14} | {fmt(H2):>14} |{tag}")
print("\n==== buckets where PSAR confirmation is TIME-STABLE (both halves, t>1.5 each, ALL t>2) ====")
if STABLE:
    for f,b,A in STABLE: print(f"  {f}/{b}:  +{A[0]:.3f}R  (t={A[1]:.1f}, n_sym={A[2]})")
else:
    print("  (none) -> no observable state makes PSAR a reliably-confirming signal")
