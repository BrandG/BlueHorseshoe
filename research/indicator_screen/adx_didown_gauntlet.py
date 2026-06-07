"""Gauntlet for adx_diDown (strong-downtrend contrarian long), the one PSAR/ADX edge that passed
the incremental test (adx_didown_incremental.out: residual +0.148R t6.2 vs known dislocation).

adx_diDown is a PERSISTING STATE, not an event — so realistic de-overlapped execution (enter once,
hold 10, no re-entry for 10 bars) won't capture the deep-in-run bars where the edge concentrated
(re-audit: de-overlapped onset +0.014R vs full-pop NW +0.094R nonbull; age6+ +0.104R). So this tests
several deployable entry variants to find which banks AFTER real frictions:
  adx        = ADX>25 & -DI>+DI                         (fires throughout the downtrend; onset-dominated)
  adx_aged6  = adx AND state-age>=6                      (enter DEEP, where the age gradient peaked)
  adx_x_known= adx AND known dislocation                 (confluence amplifier; highest conviction)
  known      = known dislocation alone                   (benchmark: rsi<30|below-cloud|below-SMA200|far-SMA50)
  rand       = all eligible                               (absolute floor)

Cumulative frictions (each adds one), de-overlapped (one entry / N bars), symbol-clustered:
  S0 IDEAL  enter signal close, stop at level, no cost
  S1 NEXTOPEN enter next-day OPEN
  S2 GAPSTOP  + stops fill at the open when the bar gaps through
  S3 COST25   + 25bp round-trip flat
  S4 REALISTIC+ liquidity-tiered round-trip cost
Per regime (all / nonbull), incremental R vs known, year-by-year + liquidity tiers for the adx arms.
Machinery identical to ha_confluence_gauntlet.py.
"""
import numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005; DISP=26
N=10; TP_ATR,SL_ATR=2.0,1.0; MIN_BASE=15; AGE_DEEP=6
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg_map.get(str(d)[:10],False)

syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
syms=[s for s in syms if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"{len(syms)} syms, adx_diDown gauntlet hold{N} {TP_ATR:.0f}:{SL_ATR:.0f}, deep-age>={AGE_DEEP}",flush=True)

rmx=lambda x,w: pd.Series(x).rolling(w).max().to_numpy(); rmn=lambda x,w: pd.Series(x).rolling(w).min().to_numpy()
DV_TIERS=[("<1M",0,1e6),("1-5M",1e6,5e6),("5-25M",5e6,25e6),(">25M",25e6,9e18)]
def dv_cost_bp(dv):
    if dv<1e6:  return 50.0
    if dv<5e6:  return 25.0
    if dv<25e6: return 12.0
    return 6.0
def age_of(state):
    a=np.full(len(state),-1,int); r=0
    for i in range(len(state)):
        if state[i]: a[i]=r; r+=1
        else: r=0
    return a
def run(entry,atr,o,h,l,c,gap):
    n=len(c); tp=entry+TP_ATR*atr; sl=entry-SL_ATR*atr; Rp=SL_ATR*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan)
    valid=(np.arange(n)<(n-N-1))&(atr>0)&~np.isnan(atr)&~np.isnan(entry)
    for k in range(1,N+1):
        hk=np.full(n,np.nan); hk[:n-k]=h[k:]; lk=np.full(n,np.nan); lk[:n-k]=l[k:]
        okp=np.full(n,np.nan); okp[:n-k]=o[k:]
        tph=hk>=tp; slh=lk<=sl
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        sfill=np.where(okp<=sl,okp,sl) if gap else sl
        res[loss]=((sfill[loss] if gap else sl[loss])-entry[loss])/Rp[loss]
        res[wn]=TP_ATR/SL_ATR; resolved|=(loss|wn)
    exitc=np.full(n,np.nan); exitc[:n-N]=c[N:][:n-N]
    to=valid&~resolved; res[to]=(exitc[to]-entry[to])/Rp[to]
    return res,valid

SC=["S0_ideal","S1_nextopen","S2_gapstop","S3_cost25","S4_realistic"]
REGIMES=["all","nonbull"]; ARM_NAMES=["adx","adx_aged6","adx_x_known","known"]
acc=defaultdict(lambda:[0.,0.,0,0])
def bump(k,m,nt):
    a=acc[k]; a[0]+=m; a[1]+=m*m; a[2]+=1; a[3]+=nt
wincnt=defaultdict(lambda:[0,0])
def sim(idx):
    out=[]; iu=-1
    for i in idx:
        if i<=iu: continue
        out.append(i); iu=i+N
    return out

for ii,sym in enumerate(syms):
    if ii%300==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    dv20=pd.Series(c*v).rolling(20).mean().to_numpy(); atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    nonbull=~np.array([isbull(x) for x in dts])
    adx14=talib.ADX(h,l,c,14); pdi=talib.PLUS_DI(h,l,c,14); mdi=talib.MINUS_DI(h,l,c,14)
    sma50=talib.SMA(c,50); sma200=talib.SMA(c,200)
    sA=np.full(n,np.nan); sB=np.full(n,np.nan)
    tk=(rmx(h,9)+rmn(l,9))/2; kj=(rmx(h,26)+rmn(l,26))/2
    sA[DISP:]=((tk+kj)/2)[:n-DISP]; sB[DISP:]=((rmx(h,52)+rmn(l,52))/2)[:n-DISP]
    bot=np.fmin(sA,sB)
    known=(rsi<30)|(c<bot)|(c<sma200)|((sma50-c)/np.where(atr>0,atr,np.nan)>2.0)
    adx_dd=(adx14>25)&(mdi>pdi)
    age=age_of(np.asarray(adx_dd,bool))
    ARMS={"adx":adx_dd,"adx_aged6":adx_dd&(age>=AGE_DEEP),"adx_x_known":adx_dd&np.asarray(known,bool),"known":np.asarray(known,bool)}
    nxo=np.full(n,np.nan); nxo[:n-1]=o[1:]
    res_ideal,val_i=run(c,atr,o,h,l,c,gap=False)
    res_no,   val_n=run(nxo,atr,o,h,l,c,gap=False)
    res_gap,  _    =run(nxo,atr,o,h,l,c,gap=True)
    with np.errstate(divide='ignore',invalid='ignore'):
        cost_flat=(25.0/1e4)/(SL_ATR*atr_pct)
        cost_tier=np.array([dv_cost_bp(x) for x in np.nan_to_num(dv20)])/1e4/(SL_ATR*atr_pct)
    RES={"S0_ideal":(res_ideal,val_i),"S1_nextopen":(res_no,val_n),"S2_gapstop":(res_gap,val_n),
         "S3_cost25":(res_gap-cost_flat,val_n),"S4_realistic":(res_gap-cost_tier,val_n)}
    for reg in REGIMES:
        rmask=nonbull if reg=="nonbull" else np.ones(n,bool)
        for scen in SC:
            res,val=RES[scen]; ok=elig&val&~np.isnan(res)&rmask
            if ok.sum()<MIN_BASE: continue
            for arm in ARM_NAMES:
                ent=sim(np.where(ok&np.asarray(ARMS[arm],bool))[0])
                if not ent: continue
                rr=np.array([res[i] for i in ent])
                bump((reg,scen,"FULL",arm), rr.mean(), len(ent))
                wincnt[(reg,scen,arm)][0]+=int((rr>0).sum()); wincnt[(reg,scen,arm)][1]+=len(ent)
                if scen=="S4_realistic" and arm in ("adx","adx_aged6"):
                    byy=defaultdict(list)
                    for i in ent: byy[dts[i][:4]].append(res[i])
                    for y,rs in byy.items(): bump((reg,scen,y,arm), np.mean(rs), len(rs))
                    if reg=="nonbull":
                        for tname,lo,hi in DV_TIERS:
                            sel=[res[i] for i in ent if lo<=np.nan_to_num(dv20[i])<hi]
                            if sel: bump((reg,scen,"LIQ_"+tname,arm), np.mean(sel), len(sel))
            bump((reg,scen,"FULL","rand"), res[ok].mean(), int(ok.sum()))

def stat(k,minsym=20):
    a=acc.get(k)
    if not a or a[2]<minsym: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt
def F(x): return f"{x[0]:+.4f}R t{x[1]:+.1f} n{x[3]}" if x else "--"

for reg in REGIMES:
    print(f"\n################ CUMULATIVE FRICTION — regime={reg} (de-overlapped, clustered) ################")
    print(f"  {'scenario':>13} | {'adx':>19} {'win%':>5} | {'adx_aged6':>19} {'win%':>5} | {'adx_x_known':>19} | {'known':>17} | {'rand':>15}")
    for scen in SC:
        a=stat((reg,scen,"FULL","adx")); ag=stat((reg,scen,"FULL","adx_aged6")); ax=stat((reg,scen,"FULL","adx_x_known"))
        kn=stat((reg,scen,"FULL","known")); rd=stat((reg,scen,"FULL","rand"))
        wa=wincnt[(reg,scen,"adx")]; wra=100.0*wa[0]/wa[1] if wa[1] else 0
        wg=wincnt[(reg,scen,"adx_aged6")]; wrg=100.0*wg[0]/wg[1] if wg[1] else 0
        print(f"  {scen:>13} | {F(a):>19} {wra:>4.0f}% | {F(ag):>19} {wrg:>4.0f}% | {F(ax):>19} | {F(kn):>17} | {F(rd):>15}")

print("\n################ S4 REALISTIC — year by year (absolute R) ################")
print(f"  {'year':>6} | {'adx (all)':>20} | {'adx (nonbull)':>22} | {'adx_aged6 (nonbull)':>22}")
for y in [str(x) for x in range(2016,2027)]:
    sa=stat(("all","S4_realistic",y,"adx")); sn=stat(("nonbull","S4_realistic",y,"adx")); sg=stat(("nonbull","S4_realistic",y,"adx_aged6"))
    g=lambda s: (f"{s[0]:+.3f}R t{s[1]:+.1f} n{s[3]}" if s else "(thin)")
    print(f"  {y:>6} | {g(sa):>20} | {g(sn):>22} | {g(sg):>22}")

print("\n################ S4 REALISTIC — by liquidity tier (nonbull) ################")
for arm in ("adx","adx_aged6"):
    print(f"  -- {arm} --")
    for tname,_,_ in DV_TIERS:
        s=stat(("nonbull","S4_realistic","LIQ_"+tname,arm))
        print(f"     {tname:>8} | {(f'{s[0]:+.4f}R t{s[1]:+.1f}' if s else '(thin)'):>20} | n {s[3] if s else 0}")
print("\ndone.")
