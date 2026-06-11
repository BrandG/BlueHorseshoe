"""GAUNTLET: bare-DeepOS minus ENTRY-MORNING gap-down, faithful execution.

[[project_deepos_volume_conditioner]]: the deployable residue is a gap-down knife-filter on BARE DeepOS
(+0.035R nonbull gross; DeepOS+HA already dodges gaps since gaps are ~all HA-red). This runs it through the
same friction gauntlet the rsi_oversold/HA rules cleared, using the LIVE-FAITHFUL gap definition: the signal
fires at close[t]; next morning we observe open[t+1] BEFORE the marketable order, so "skip if it gapped down
>=X% overnight" is a clean no-lookahead entry-time decision (entry_gap = open[t+1]/close[t]-1).

Arms under identical friction:
  deepos = rsi<30 & age>=3 (bare sleeve, benchmark)
  filt3  = deepos & NOT(entry-morning gap-down >=3%)   (candidate)
  gapped3= deepos & (entry-morning gap-down >=3%)       (the excluded knives - confirm negative)
  rand   = all eligible (floor)
Cumulative scenarios (de-overlapped one entry/N bars):
  S0 ideal(close) | S1 nextopen | S2 +gapstop | S3 +25bp | S4 +liquidity-tiered cost.
Question: does filt beat deepos AFTER costs, EVERY year (not just crashes)? + threshold sweep 2/3/5%.
Sample PINNED (ORDER BY). nonbull is the deployable regime.
"""
import numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; AGE=3; N=10; TP_ATR,SL_ATR=2.0,1.0; MIN_BASE=15
GAP_THRS=[0.02,0.03,0.05]
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg_map.get(str(d)[:10],False)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300 ORDER BY symbol",[START]).df().symbol.tolist()
syms=[s for s in syms if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=sorted(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"{len(syms)} syms (PINNED); DeepOS(rsi<{OS:.0f} age>={AGE}) entry-morning-gap gauntlet, hold{N} {TP_ATR:.0f}:{SL_ATR:.0f}",flush=True)

DV_TIERS=[("<1M",0,1e6),("1-5M",1e6,5e6),("5-25M",5e6,25e6),(">25M",25e6,9e18)]
def dv_cost_bp(dv):
    if dv<1e6: return 50.0
    if dv<5e6: return 25.0
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
    osr=rsi<OS; age=np.zeros(n,int)
    for t in range(1,n): age[t]=age[t-1]+1 if osr[t] else 0
    deepos=osr&(age>=AGE)
    nxo=np.full(n,np.nan); nxo[:n-1]=o[1:]
    entry_gap=(nxo/np.where(c>0,c,np.nan))-1.0     # overnight gap into entry morning
    res_ideal,val_i=run(c,atr,o,h,l,c,gap=False)
    res_no,   val_n=run(nxo,atr,o,h,l,c,gap=False)
    res_gap,  _    =run(nxo,atr,o,h,l,c,gap=True)
    cost_flat=(25.0/1e4)/(SL_ATR*atr_pct)
    cost_tier=np.array([dv_cost_bp(x) for x in np.nan_to_num(dv20)])/1e4/(SL_ATR*atr_pct)
    RES={"S0_ideal":(res_ideal,val_i),"S1_nextopen":(res_no,val_n),"S2_gapstop":(res_gap,val_n),
         "S3_cost25":(res_gap-cost_flat,val_n),"S4_realistic":(res_gap-cost_tier,val_n)}
    gmask={x:(entry_gap<=-x) for x in GAP_THRS}      # gapped down >= x
    ARMS={"deepos":deepos}
    for x in GAP_THRS:
        tag=f"{int(x*100)}"
        ARMS[f"filt{tag}"]=deepos&~gmask[x]
    ARMS["gapped3"]=deepos&gmask[0.03]
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
                if scen=="S4_realistic" and arm in ("deepos","filt3"):
                    byy=defaultdict(list)
                    for i in ent: byy[dts[i][:4]].append(res[i])
                    for y,rs in byy.items(): bump((reg,scen,y,arm), np.mean(rs), len(rs))
                    if reg=="nonbull" and arm=="filt3":
                        for tname,lo,hi in DV_TIERS:
                            sel=[res[i] for i in ent if lo<=np.nan_to_num(dv20[i])<hi]
                            if sel: bump((reg,scen,"LIQ_"+tname,"filt3"), np.mean(sel), len(sel))
            bump((reg,scen,"FULL","rand"), res[ok].mean(), int(ok.sum()))

def stat(k,minsym=20):
    a=acc.get(k)
    if not a or a[2]<minsym: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt
def F(x): return f"{x[0]:+.4f}R t{x[1]:+.1f} n{x[3]}" if x else "--"

for reg in REGIMES:
    print(f"\n################ CUMULATIVE FRICTION — regime={reg} (de-overlapped, clustered) ################")
    print(f"  {'scenario':>13} | {'DEEPOS abs R':>21} {'win%':>4} | {'FILT3 abs R':>21} {'win%':>4} | {'GAPPED3':>20} | {'RAND':>16} | {'filt-base':>10}")
    for scen in SC:
        dp=stat((reg,scen,"FULL","deepos")); ft=stat((reg,scen,"FULL","filt3"))
        gp=stat((reg,scen,"FULL","gapped3")); rd=stat((reg,scen,"FULL","rand"))
        wd=wincnt[(reg,scen,"deepos")]; wrd=100.0*wd[0]/wd[1] if wd[1] else 0
        wf=wincnt[(reg,scen,"filt3")]; wrf=100.0*wf[0]/wf[1] if wf[1] else 0
        inc=f"{ft[0]-dp[0]:+.4f}R" if (dp and ft) else "--"
        print(f"  {scen:>13} | {F(dp):>21} {wrd:>3.0f}% | {F(ft):>21} {wrf:>3.0f}% | {F(gp):>20} | {F(rd):>16} | {inc:>10}")

print("\n################ THRESHOLD SWEEP — S4 filt lift over bare DeepOS (filt_x - deepos) ################")
for reg in REGIMES:
    dp=stat((reg,"S4_realistic","FULL","deepos"))
    row=[]
    for x in GAP_THRS:
        ft=stat((reg,"S4_realistic","FULL",f"filt{int(x*100)}"))
        row.append(f"{int(x*100)}%:{ft[0]-dp[0]:+.4f}(filt {ft[0]:+.3f},n{ft[3]})" if (ft and dp) else f"{int(x*100)}%:--")
    print(f"  {reg:>8} [deepos {dp[0]:+.4f}R]  "+"  ".join(row))

print("\n################ S4 REALISTIC — year by year: bare DeepOS vs FILT3 (lift = filt-base) ################")
print(f"  {'year':>6} | {'nonbull deepos':>22} | {'nonbull filt3':>22} | lift")
for y in [str(x) for x in range(2016,2027)]:
    dp=stat(("nonbull","S4_realistic",y,"deepos")); ft=stat(("nonbull","S4_realistic",y,"filt3"))
    g=lambda s:(f"{s[0]:+.4f}R t{s[1]:+.1f} n{s[3]}" if s else "(thin)")
    lift=f"{ft[0]-dp[0]:+.4f}" if (dp and ft) else "--"
    print(f"  {y:>6} | {g(dp):>22} | {g(ft):>22} | {lift}")

print("\n################ S4 REALISTIC — FILT3 by liquidity tier (nonbull) ################")
for tname,_,_ in DV_TIERS:
    s=stat(("nonbull","S4_realistic","LIQ_"+tname,"filt3"))
    print(f"  {tname:>8} | {(f'{s[0]:+.4f}R t{s[1]:+.1f}' if s else '(thin)'):>20} | n {s[3] if s else 0}")
print("\ndone.")
