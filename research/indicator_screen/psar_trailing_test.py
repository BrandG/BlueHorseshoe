"""PSAR on its home turf: as a TRAILING STOP / exit, not an entry.

Same random entries (every eligible bar), measured in common R = 1*ATR14. Compare
exit rules, PAIRED (each entry scored under every rule, so the difference is purely
the exit mechanism):
  A  fixed 2:1      : TP=+2ATR, fixed SL=-1ATR, timeout N           (current bracket)
  B1 PSAR pure-trail: no TP, exit when close < PSAR dot, timeout N  (faithful Wilder use)
  B2 PSAR + 2ATR TP : TP=+2ATR, stop = PSAR dot (trailing), timeout (isolates the STOP)
PSAR stop tested at af=0.02 (default) and af=0.01 (looser trail = lets winners run).
Clean: vol floor, symbol-clustered, time-split. Reports each rule's expectancy and the
PAIRED lift (PSAR-rule minus fixed) with stability across halves.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"; SPLIT="2021-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
N=10; TP_ATR,SL_ATR=2.0,1.0; MIN_ENTRIES=20

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

def fixed_bracket(h,l,c,atr):
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

def psar_trail(h,l,c,atr,psar,use_tp):
    n=len(c); entry=c; tp=c+TP_ATR*atr; Rp=atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan); valid=(np.arange(n)<(n-N))&(atr>0)&~np.isnan(atr)
    for k in range(1,N+1):
        cf=np.full(n,np.nan); cf[:n-k]=c[k:]
        hf=np.full(n,np.nan); hf[:n-k]=h[k:]
        pf=np.full(n,np.nan); pf[:n-k]=psar[k:]
        if use_tp:
            tphit=valid&~resolved&(hf>=tp); res[tphit]=TP_ATR/SL_ATR; resolved|=tphit  # intrabar TP first
        stophit=valid&~resolved&np.isfinite(pf)&(cf<pf)   # close below the dot
        res[stophit]=(cf[stophit]-entry[stophit])/Rp[stophit]; resolved|=stophit
    ex=np.full(n,np.nan); ex[:n-N]=c[N:][:n-N] if n-N>0 else ex[:n-N]
    to=valid&~resolved; res[to]=(ex[to]-entry[to])/Rp[to]
    return res

acc={}      # (rule,regime,half) -> [sum,sumsq,nsym]  (per-symbol mean expectancy)
accL={}     # (rule,regime,half) -> [sum,sumsq,nsym]  (per-symbol mean PAIRED lift vs fixed)
def bump(D,key,val):
    a=D.get(key)
    if a is None: D[key]=a=[0.,0.,0]
    a[0]+=val;a[1]+=val*val;a[2]+=1

RULES=["A_fixed","B1_trail_af02","B1_trail_af01","B2_tp+stop_af02","B2_tp+stop_af01"]
for i,sym in enumerate(syms):
    if i%300==0: print(f"  {i}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy(); atr_pct=atr/np.where(c>0,c,np.nan)
    psar02=talib.SAR(h,l,0.02,0.2); psar01=talib.SAR(h,l,0.01,0.2)
    bull=np.array([isbull(x) for x in dts]); h1=dts<SPLIT
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    R={}
    R["A_fixed"],valid=fixed_bracket(h,l,c,atr)
    R["B1_trail_af02"]=psar_trail(h,l,c,atr,psar02,False)
    R["B1_trail_af01"]=psar_trail(h,l,c,atr,psar01,False)
    R["B2_tp+stop_af02"]=psar_trail(h,l,c,atr,psar02,True)
    R["B2_tp+stop_af01"]=psar_trail(h,l,c,atr,psar01,True)
    ent=elig&valid
    for r in RULES: ent=ent&np.isfinite(R[r])
    if ent.sum()<MIN_ENTRIES: continue
    for rk,rm in (("all",np.ones(n,bool)),("bull",bull),("nonbull",~bull)):
        for half,hm in (("ALL",np.ones(n,bool)),("H1",h1),("H2",~h1)):
            m=ent&rm&hm
            if m.sum()<MIN_ENTRIES: continue
            af=R["A_fixed"][m]
            for r in RULES: bump(acc,(r,rk,half),R[r][m].mean())
            for r in RULES[1:]: bump(accL,(r,rk,half),(R[r][m]-af).mean())

def stat(D,key):
    a=D.get(key)
    if not a or a[2]<40: return None
    s,ss,ns=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns
def f(x): return f"{x[0]:+.3f}R(t{x[1]:+.1f})" if x else "    --"

for rk in ("all","bull","nonbull"):
    print(f"\n############ regime={rk} : expectancy per exit rule (random entries) ############")
    print(f"  {'rule':18} | {'ALL':>15} | {'H1 16-20':>15} | {'H2 21-26':>15}")
    for r in RULES:
        print(f"  {r:18} | {f(stat(acc,(r,rk,'ALL'))):>15} | {f(stat(acc,(r,rk,'H1'))):>15} | {f(stat(acc,(r,rk,'H2'))):>15}")
    print(f"  -- PAIRED lift vs A_fixed (does the PSAR stop BEAT the fixed stop?) --")
    for r in RULES[1:]:
        A=stat(accL,(r,rk,'ALL')); H1=stat(accL,(r,rk,'H1')); H2=stat(accL,(r,rk,'H2'))
        stable=H1 and H2 and H1[0]>0 and H2[0]>0 and H1[1]>1.5 and H2[1]>1.5 and A and A[1]>2
        print(f"    {r:16} | {f(A):>15} | {f(H1):>15} | {f(H2):>15} {'<== BEATS fixed (stable)' if stable else ''}")
