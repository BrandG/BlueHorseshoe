"""Stack the Heiken-Ashi reversal confirmation on the VALIDATED deep-oversold rule.

[[project_rsi_oversold_bracket_edge]] blessed: rsi<30 for >=3 bars, hold 10, ATR 2:1 — cost-survived,
year-stable, positive every year in ALL regimes (not just nonbull). [[project_heiken_ashi_deepdive]]
showed a fresh HA green flip amplifies the contrarian sleeve. This stacks them: does a Heiken-Ashi
confirmation, applied ON TOP of deep-oversold, raise per-trade R further after real frictions?

Arms (under identical cumulative friction, de-overlapped one entry/N bars, clustered):
  deep       = rsi<30 AND age>=3                 (the validated benchmark)
  deep_flip  = deep AND ha_flip_up               (green HA bar today, red yesterday — strict turn)
  deep_green = deep AND HA-bar-currently-green    (looser: momentum already turning up)
  rand       = all eligible bars                  (absolute floor)
age: consecutive count of rsi<30 bars, 0-indexed (age>=3 => 4th+ oversold bar), per coststress.

Scenarios S0 ideal -> S1 next-open -> S2 gap-stop -> S3 +25bp -> S4 liquidity-tiered cost.
Reported per regime (all / nonbull) with incremental R vs deep, plus year-by-year + liquidity tiers.
Machinery identical to ha_confluence_gauntlet.py / rsi_oversold_coststress.py.
"""
import numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; THR=3; N=10; TP_ATR,SL_ATR=2.0,1.0; MIN_BASE=15
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
print(f"{len(syms)} syms, deep = rsi<{OS:.0f} age>={THR}, hold{N} {TP_ATR:.0f}:{SL_ATR:.0f}",flush=True)

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
ARM_NAMES=["deep","deep_flip","deep_green"]
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
    os=rsi<OS; age=np.full(n,-1,int); run_=0
    for i in range(n):
        if os[i]: age[i]=run_; run_+=1
        else: run_=0
    deep=os&(age>=THR)
    # HA
    ha_close=(o+h+l+c)/4.0; ha_open=np.empty(n); ha_open[0]=(o[0]+c[0])/2.0
    for t in range(1,n): ha_open[t]=(ha_open[t-1]+ha_close[t-1])/2.0
    green=ha_close>ha_open; red=ha_close<ha_open
    rprev=np.zeros(n,bool); rprev[1:]=red[:-1]; flip=green&rprev
    ARMS={"deep":deep,"deep_flip":deep&flip,"deep_green":deep&green}
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
                ent=sim(np.where(ok&ARMS[arm])[0])
                if not ent: continue
                rr=np.array([res[i] for i in ent])
                bump((reg,scen,"FULL",arm), rr.mean(), len(ent))
                wincnt[(reg,scen,arm)][0]+=int((rr>0).sum()); wincnt[(reg,scen,arm)][1]+=len(ent)
                if scen=="S4_realistic" and arm=="deep_flip":
                    byy=defaultdict(list)
                    for i in ent: byy[dts[i][:4]].append(res[i])
                    for y,rs in byy.items(): bump((reg,scen,y,"deep_flip"), np.mean(rs), len(rs))
                    if reg=="all":
                        for tname,lo,hi in DV_TIERS:
                            sel=[res[i] for i in ent if lo<=np.nan_to_num(dv20[i])<hi]
                            if sel: bump((reg,scen,"LIQ_"+tname,"deep_flip"), np.mean(sel), len(sel))
            bump((reg,scen,"FULL","rand"), res[ok].mean(), int(ok.sum()))

def stat(k,minsym=20):
    a=acc.get(k)
    if not a or a[2]<minsym: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt
def F(x): return f"{x[0]:+.4f}R t{x[1]:+.1f} n{x[3]}" if x else "--"

for reg in REGIMES:
    print(f"\n################ CUMULATIVE FRICTION — regime={reg} (de-overlapped, clustered) ################")
    print(f"  {'scenario':>13} | {'DEEP (bench)':>20} | {'DEEP_FLIP':>20} {'win%':>5} | {'DEEP_GREEN':>20} | {'flip-deep':>10}")
    for scen in SC:
        dp=stat((reg,scen,"FULL","deep")); df=stat((reg,scen,"FULL","deep_flip")); dg=stat((reg,scen,"FULL","deep_green"))
        w=wincnt[(reg,scen,"deep_flip")]; wr=100.0*w[0]/w[1] if w[1] else 0
        inc=f"{df[0]-dp[0]:+.4f}R" if (df and dp) else "--"
        print(f"  {scen:>13} | {F(dp):>20} | {F(df):>20} {wr:>4.0f}% | {F(dg):>20} | {inc:>10}")

print("\n################ S4 REALISTIC — DEEP_FLIP year by year (absolute R) ################")
print(f"  {'year':>6} | {'all regime':>24} | {'nonbull':>24}")
for y in [str(x) for x in range(2016,2027)]:
    sa=stat(("all","S4_realistic",y,"deep_flip")); sn=stat(("nonbull","S4_realistic",y,"deep_flip"))
    g=lambda s: (f"{s[0]:+.4f}R t{s[1]:+.1f} n{s[3]}" if s else "(thin)")
    print(f"  {y:>6} | {g(sa):>24} | {g(sn):>24}")

print("\n################ S4 REALISTIC — DEEP_FLIP by liquidity tier (all regime, 20d avg $-vol) ################")
for tname,_,_ in DV_TIERS:
    s=stat(("all","S4_realistic","LIQ_"+tname,"deep_flip"))
    print(f"  {tname:>8} | {(f'{s[0]:+.4f}R t{s[1]:+.1f}' if s else '(thin)'):>20} | n {s[3] if s else 0}")
print("\ndone.")
