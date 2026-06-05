"""Crash gate for the deep-oversold rule — re-checked year by year.

Rule: RSI<30 for >=3 bars, flat, hold 10, ATR 2:1. It earns in 9/11 years; the ONE failure is
2020 (the COVID freefall), mechanically where dip-buying should fail. Goal: an INDEX-freefall gate
that removes the 2020 loss WITHOUT killing 2022 (an orderly bear where the rule earned +0.41R) or
the nonbull regime generally. So the gate must read 'freefall' (velocity/vol/new-lows), NOT just
'bear' (below 200-EMA — too blunt, would kill the best regime).

Gates (skip entries when SPY is in freefall):
  G0 none
  G1 spy 10d return <= -8%        G2 spy 10d return <= -12%
  G3 spy 5d return  <= -7%        G4 spy ATR%(14) >= 3.5%
  G5 SPY making a fresh 20d low   G6 combo: (10d<=-10%) OR (ATR%>=4%)

Output: (1) decision table per gate — full-sample lift/t, trades, %removed, 2020, COVID-March,
worst year, #positive years; (2) year-by-year for G0 and the chosen gate.
"""
import numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; N=10; TP_ATR,SL_ATR=2.0,1.0; MIN_BASE=15; THR=3

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))

# --- SPY-derived crash signals (computed once) ---
spy=con.execute("SELECT date,open,high,low,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
sc=spy.close.to_numpy(float); sh=spy.high.to_numpy(float); sl=spy.low.to_numpy(float)
sd=spy.date.astype(str).str[:10].to_numpy()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
isbull_arr=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg=dict(zip(sd,isbull_arr.to_numpy()))
def isbull(d): return reg.get(str(d)[:10],False)
ret5=np.full(len(sc),np.nan); ret5[5:]=sc[5:]/sc[:-5]-1
ret10=np.full(len(sc),np.nan); ret10[10:]=sc[10:]/sc[:-10]-1
spy_atrp=talib.ATR(sh,sl,sc,14)/sc
roll20min=pd.Series(sc).rolling(20).min().shift(1).to_numpy()
newlow20=sc<=roll20min
GATES={
 "G0_none":      np.ones(len(sc),bool),
 "G1_ret10>-8":  ~(ret10<=-0.08),
 "G2_ret10>-12": ~(ret10<=-0.12),
 "G3_ret5>-7":   ~(ret5<=-0.07),
 "G4_atr<3.5":   ~(spy_atrp>=0.035),
 "G5_no_newlow": ~newlow20,
 "G6_combo":     ~((ret10<=-0.10)|(spy_atrp>=0.04)),
}
allow=  {g:dict(zip(sd,m)) for g,m in GATES.items()}   # date -> allowed?
def gate_ok(g,d): return allow[g].get(str(d)[:10],True)
print(f"{len(syms)} syms, rule RSI<{OS:.0f} >={THR}bars hold{N} {TP_ATR:.0f}:{SL_ATR:.0f}; gates={list(GATES)}",flush=True)

def bracket(h,l,c,atr,N,tp_atr,sl_atr):
    n=len(c); tp=c+tp_atr*atr; slv=c-sl_atr*atr; Rp=sl_atr*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan)
    valid=(np.arange(n)<(n-N))&(atr>0)&~np.isnan(atr)
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp[:n-k]; slh[:n-k]=l[k:]<=slv[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=tp_atr/sl_atr; resolved|=(loss|wn)
    ex=np.full(n,np.nan); ex[:n-N]=c[N:][:n-N] if n-N>0 else ex[:n-N]
    to=valid&~resolved; res[to]=(ex[to]-c[to])/Rp[to]
    return res,valid
def sim(idx):
    out=[]; iu=-1
    for i in idx:
        if i<=iu: continue
        out.append(i); iu=i+N
    return out
def bucket_of(ym):
    if ym=="2020-03": return None  # handled separately
    return None

# clustered acc: (gate,bucket) -> [sumLift,sumsq,nsym,ntr]
acc=defaultdict(lambda:[0.,0.,0,0])
def bump(k,lift,nt):
    a=acc[k]; a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt

for ii,sym in enumerate(syms):
    if ii%300==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan)
    ok=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)&(np.arange(n)<(n-N))&(atr>0)&~np.isnan(atr)
    res,valid=bracket(h,l,c,atr,N,TP_ATR,SL_ATR); ok=ok&~np.isnan(res)
    os=rsi<OS
    age=np.full(n,-1,int); run=0
    for i in range(n):
        if os[i]: age[i]=run; run+=1
        else: run=0
    ent=sim(np.where(ok&(age>=THR))[0])
    if not ent: continue
    years=np.array([dts[i][:4] for i in range(n)])
    # per-(symbol,bucket) baseline means (ungated random eligible bars)
    def base_for(mask): return res[mask].mean() if mask.sum()>=MIN_BASE else None
    ybase={y:base_for(ok&(years==y)) for y in np.unique(years)}
    fullbase=base_for(ok)
    # special covid buckets
    mar20=np.array([dt[:7]=="2020-03" for dt in dts]); covid=np.array([("2020-03"<=dt[:7]<="2020-12") for dt in dts])
    marbase=base_for(ok&mar20); covidrestbase=base_for(ok&covid&~mar20)
    for g in GATES:
        ge=[i for i in ent if gate_ok(g,dts[i])]
        if not ge: continue
        rs_all=np.array([res[i] for i in ge])
        if fullbase is not None: bump((g,"FULL"), rs_all.mean()-fullbase, len(ge))
        # years
        byy=defaultdict(list)
        for i in ge: byy[dts[i][:4]].append(res[i])
        for y,rs in byy.items():
            if ybase.get(y) is not None: bump((g,y), np.mean(rs)-ybase[y], len(rs))
        # covid march / rest
        m=[res[i] for i in ge if dts[i][:7]=="2020-03"]
        if m and marbase is not None: bump((g,"2020-Mar"), np.mean(m)-marbase, len(m))
        r=[res[i] for i in ge if ("2020-04"<=dts[i][:7]<="2020-12")]
        if r and covidrestbase is not None: bump((g,"2020-Apr-Dec"), np.mean(r)-covidrestbase, len(r))

def stat(k):
    a=acc.get(k)
    if not a or a[2]<20: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt
YEARS=[str(y) for y in range(2016,2027)]

print("\n############### DECISION TABLE (one row per gate) ###############")
g0full=stat(("G0_none","FULL")); g0n=g0full[3] if g0full else 1
hdr=f"  {'gate':>14} | {'FULL lift':>17} | {'trades':>6} {'%kept':>6} | {'2020':>14} | {'Mar20':>14} | {'+yrs':>4} {'worst yr':>16}"
print(hdr)
for g in GATES:
    f=stat((g,"FULL"))
    if not f: print(f"  {g:>14} | (thin)"); continue
    pos=0; worst=(None,99)
    for y in YEARS:
        s=stat((g,y))
        if not s: continue
        if s[0]>0: pos+=1
        if s[0]<worst[1]: worst=(y,s[0])
    y20=stat((g,"2020")); mar=stat((g,"2020-Mar"))
    def F(x): return f"{x[0]:+.3f}R t{x[1]:+.1f}" if x else "   --   "
    kept=100.0*f[3]/g0n
    wy=f"{worst[0]} {worst[1]:+.2f}" if worst[0] else "--"
    print(f"  {g:>14} | {F(f):>17} | {f[3]:>6} {kept:>5.0f}% | {F(y20):>14} | {F(mar):>14} | {pos:>4} {wy:>16}")

print("\n############### YEAR-BY-YEAR: G0 vs G6_combo vs G4_atr<3.5 ###############")
print(f"  {'year':>12} | " + " | ".join(f"{g:>16}" for g in ("G0_none","G6_combo","G4_atr<3.5")))
for y in YEARS+["2020-Mar","2020-Apr-Dec"]:
    cells=[]
    for g in ("G0_none","G6_combo","G4_atr<3.5"):
        s=stat((g,y)); cells.append(f"{s[0]:+.3f}R t{s[1]:+.1f}" if s else "(thin)")
    print(f"  {y:>12} | " + " | ".join(f"{c:>16}" for c in cells))
