"""Decisive: does DEEP below-cloud (>=1.5 ATR under the cloud, nonbull) survive
symbol-clustered + de-overlapped error bars, AND is its edge orthogonal to rsi<30?
If the deep-cell-AND-NOT-rsi<30 residual is flat -> cloud is fully redundant with the
oversold sleeve; the depth signal is just re-measuring the same dislocation axis.
"""
import numpy as np, pandas as pd, talib, duckdb
SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005; DISP=26; DEEP=1.5
con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg_map.get(str(d)[:10],False)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"{len(syms)} symbols, DEEP=>={DEEP} ATR below cloud",flush=True)
rmx=lambda x,w: pd.Series(x).rolling(w).max().to_numpy(); rmn=lambda x,w: pd.Series(x).rolling(w).min().to_numpy()
acc={}
def bump(k,lift,nt):
    a=acc.setdefault(k,[0.,0.,0,0]); a[0]+=lift;a[1]+=lift*lift;a[2]+=1;a[3]+=nt
def fwd(c,hh):
    fr=np.full(len(c),np.nan); fr[:len(c)-hh]=c[hh:]/c[:len(c)-hh]-1.0; return fr*100.0
def noov(mask,res,N):
    out=[];u=-1
    for i in np.where(mask&~np.isnan(res))[0]:
        if i<=u: continue
        out.append(i); u=i+N
    return out
for ii,sym in enumerate(syms):
    if ii%400==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan)
    tk=(rmx(h,9)+rmn(l,9))/2; kj=(rmx(h,26)+rmn(l,26))/2
    sA=np.full(n,np.nan); sB=np.full(n,np.nan)
    sA[DISP:]=((tk+kj)/2)[:n-DISP]; sB[DISP:]=((rmx(h,52)+rmn(l,52))/2)[:n-DISP]
    bot=np.fmin(sA,sB); depth=np.where((atr>0),(bot-c)/atr,np.nan)
    deep=depth>=DEEP; os=rsi<30
    nonbull=~np.array([isbull(x) for x in dts])
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)&nonbull
    for hh,N in ((10,10),(20,20)):
        res=fwd(c,hh); ok=elig&~np.isnan(res)
        if ok.sum()<30: continue
        b=res[ok].mean()
        for name,m in (("deep",deep&ok),("deep_not_os",deep&~os&ok),
                       ("deep_and_os",deep&os&ok),("rand",ok)):
            e=noov(m,res,N)
            if e: bump((name,hh), np.mean([res[i] for i in e])-b, len(e))
        nd=int((deep&ok).sum())
        if nd: bump(("ovfrac",hh), float((deep&os&ok).sum())/nd, nd)
def st(k):
    a=acc.get(k)
    if not a or a[2]<30: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt
def f(x): return f"{x[0]:+.3f}% t={x[1]:+.1f} nsym={x[2]} nt={x[3]}" if x else "(n<30)"
print("\n### DEEP below-cloud (nonbull), clustered + de-overlapped ###")
for hh in (10,20):
    ov=st(("ovfrac",hh))
    print(f"  h{hh}:  deep              {f(st(('deep',hh)))}")
    print(f"         deep & NOT rsi<30 {f(st(('deep_not_os',hh)))}   <- cloud-depth ORTHOGONAL part")
    print(f"         deep & rsi<30     {f(st(('deep_and_os',hh)))}")
    print(f"         random            {f(st(('rand',hh)))}")
    if ov: print(f"         overlap: {ov[0]*100:.0f}% of deep bars are also rsi<30")
