"""Gauntlet for the ha_flip_up x dislocation CONFLUENCE (the only HA edge that survived the screen).

Deep dive [[project_heiken_ashi_deepdive]] found: HA adds no NEW factor, but a fresh Heiken-Ashi
green flip (green bar after a red) while price is already in a dislocation state amplifies the known
contrarian edge: ha_flip_up & known = +0.176R t19 (NW, nonbull) vs +0.067R for bare dislocation.
That +0.176R is an IDEALIZED full-pop number. This runs it through the same gauntlet the rsi_oversold
rule cleared (rsi_oversold_coststress.py): cumulative real-execution frictions, year-by-year
stability, liquidity tiers. Three arms under IDENTICAL friction so we see the INCREMENTAL bankable R:
  conf  = ha_flip_up AND dislocation   (the overlay rule)
  disl  = dislocation alone            (the benchmark it claims to amplify)
  rand  = all eligible bars            (absolute floor)
dislocation = (rsi<30 OR close<ichimoku-cloud-bottom), instant — matches the deep-dive 'known' def.

Cumulative scenarios (each adds one friction), de-overlapped (one entry / N bars, realistic hold):
  S0 IDEAL     enter signal close, stop fills at level, no cost
  S1 NEXTOPEN  enter next-day OPEN (signal known only at close)
  S2 GAPSTOP   + stops fill at the open when the bar gaps through  <-- the dip-buyer killer
  S3 COST25    + 25bp round-trip flat
  S4 REALISTIC + liquidity-tiered round-trip cost
Run per regime (all / nonbull). The question: does conf beat disl AFTER costs, every year?
"""
import numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005; DISP=26
OS=30.0; N=10; TP_ATR,SL_ATR=2.0,1.0; MIN_BASE=15
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
print(f"{len(syms)} syms, conf = ha_flip_up & (rsi<{OS:.0f} or below-cloud), hold{N} {TP_ATR:.0f}:{SL_ATR:.0f}",flush=True)

rmx=lambda x,w: pd.Series(x).rolling(w).max().to_numpy(); rmn=lambda x,w: pd.Series(x).rolling(w).min().to_numpy()
DV_TIERS=[("<1M",0,1e6),("1-5M",1e6,5e6),("5-25M",5e6,25e6),(">25M",25e6,9e18)]
def dv_cost_bp(dv):
    if dv<1e6:  return 50.0
    if dv<5e6:  return 25.0
    if dv<25e6: return 12.0
    return 6.0

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
REGIMES=["all","nonbull"]
acc=defaultdict(lambda:[0.,0.,0,0])      # (regime,scen,bucket,arm) -> clustered meanR
def bump(k,m,nt):
    a=acc[k]; a[0]+=m; a[1]+=m*m; a[2]+=1; a[3]+=nt
wincnt=defaultdict(lambda:[0,0])         # (regime,scen,arm) -> [wins,total]

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
    # cloud bottom
    sA=np.full(n,np.nan); sB=np.full(n,np.nan)
    tk=(rmx(h,9)+rmn(l,9))/2; kj=(rmx(h,26)+rmn(l,26))/2
    sA[DISP:]=((tk+kj)/2)[:n-DISP]; sB[DISP:]=((rmx(h,52)+rmn(l,52))/2)[:n-DISP]
    bot=np.fmin(sA,sB); disl=(rsi<OS)|(c<bot)
    # HA flip
    ha_close=(o+h+l+c)/4.0; ha_open=np.empty(n); ha_open[0]=(o[0]+c[0])/2.0
    for t in range(1,n): ha_open[t]=(ha_open[t-1]+ha_close[t-1])/2.0
    green=ha_close>ha_open; red=ha_close<ha_open
    rprev=np.zeros(n,bool); rprev[1:]=red[:-1]
    flip=green&rprev
    conf=flip&disl
    nxo=np.full(n,np.nan); nxo[:n-1]=o[1:]

    res_ideal,val_i=run(c,atr,o,h,l,c,gap=False)
    res_no,   val_n=run(nxo,atr,o,h,l,c,gap=False)
    res_gap,  _    =run(nxo,atr,o,h,l,c,gap=True)
    cost_flat=(25.0/1e4)/(SL_ATR*atr_pct)
    cost_tier=np.array([dv_cost_bp(x) for x in np.nan_to_num(dv20)])/1e4/(SL_ATR*atr_pct)
    RES={"S0_ideal":(res_ideal,val_i),"S1_nextopen":(res_no,val_n),"S2_gapstop":(res_gap,val_n),
         "S3_cost25":(res_gap-cost_flat,val_n),"S4_realistic":(res_gap-cost_tier,val_n)}
    ARMS={"conf":conf,"disl":disl}

    for reg in REGIMES:
        rmask=nonbull if reg=="nonbull" else np.ones(n,bool)
        for scen in SC:
            res,val=RES[scen]; ok=elig&val&~np.isnan(res)&rmask
            if ok.sum()<MIN_BASE: continue
            for arm,amask in ARMS.items():
                ent=sim(np.where(ok&amask)[0])
                if not ent: continue
                rr=np.array([res[i] for i in ent])
                bump((reg,scen,"FULL",arm), rr.mean(), len(ent))
                wincnt[(reg,scen,arm)][0]+=int((rr>0).sum()); wincnt[(reg,scen,arm)][1]+=len(ent)
                if scen=="S4_realistic" and arm=="conf":
                    byy=defaultdict(list)
                    for i in ent: byy[dts[i][:4]].append(res[i])
                    for y,rs in byy.items(): bump((reg,scen,y,"conf"), np.mean(rs), len(rs))
                    if reg=="nonbull":
                        for tname,lo,hi in DV_TIERS:
                            sel=[res[i] for i in ent if lo<=np.nan_to_num(dv20[i])<hi]
                            if sel: bump((reg,scen,"LIQ_"+tname,"conf"), np.mean(sel), len(sel))
            bump((reg,scen,"FULL","rand"), res[ok].mean(), int(ok.sum()))

def stat(k,minsym=20):
    a=acc.get(k)
    if not a or a[2]<minsym: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt
def F(x): return f"{x[0]:+.4f}R t{x[1]:+.1f} n{x[3]}" if x else "--"

for reg in REGIMES:
    print(f"\n################ CUMULATIVE FRICTION — regime={reg} (de-overlapped, clustered) ################")
    print(f"  {'scenario':>13} | {'CONF abs R':>20} {'win%':>5} | {'DISL abs R':>20} | {'RAND abs R':>18} | {'conf-disl':>10}")
    for scen in SC:
        cf=stat((reg,scen,"FULL","conf")); ds=stat((reg,scen,"FULL","disl")); rd=stat((reg,scen,"FULL","rand"))
        w=wincnt[(reg,scen,"conf")]; wr=100.0*w[0]/w[1] if w[1] else 0
        inc=f"{cf[0]-ds[0]:+.4f}R" if (cf and ds) else "--"
        print(f"  {scen:>13} | {F(cf):>20} {wr:>4.0f}% | {F(ds):>20} | {F(rd):>18} | {inc:>10}")

print("\n################ S4 REALISTIC — CONF year by year (absolute R) ################")
print(f"  {'year':>6} | {'all regime':>22} | {'nonbull':>22}")
for y in [str(x) for x in range(2016,2027)]:
    sa=stat((("all"),"S4_realistic",y,"conf")); sn=stat(("nonbull","S4_realistic",y,"conf"))
    g=lambda s: (f"{s[0]:+.4f}R t{s[1]:+.1f} n{s[3]}" if s else "(thin)")
    print(f"  {y:>6} | {g(sa):>22} | {g(sn):>22}")

print("\n################ S4 REALISTIC — CONF by liquidity tier (nonbull, 20d avg $-vol) ################")
for tname,_,_ in DV_TIERS:
    s=stat(("nonbull","S4_realistic","LIQ_"+tname,"conf"))
    print(f"  {tname:>8} | {(f'{s[0]:+.4f}R t{s[1]:+.1f}' if s else '(thin)'):>20} | n {s[3] if s else 0}")
print("\ndone.")
