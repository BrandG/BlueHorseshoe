"""Cost/liquidity stress for the deep-oversold rule — does the edge survive real execution?

Rule: RSI<30 for >=3 bars, flat, hold 10, ATR 2:1. Idealized harness entered at the SIGNAL CLOSE
and filled stops EXACTLY at -1*ATR. Neither is real. Two strategy-specific killers for dip-buying:
  (1) GAP-THROUGH STOPS: an oversold name that keeps falling gaps below the stop at the next open,
      so the loss is worse than -1R. The ideal bracket pretends every stop fills at exactly -1R.
  (2) LIQUIDITY: if the edge concentrates in thin, low-priced names it isn't tradeable.

Cumulative scenarios (each adds one friction), reported as ABSOLUTE mean R/trade (what you actually
bank), t vs 0, win-rate, n -- plus the random-entry baseline under the SAME friction so we see the
gap persists:
  S0 IDEAL     enter signal-close, stop fills at level, no cost   (reproduces +0.16R lift world)
  S1 NEXTOPEN  enter next-day OPEN (signal known only at close)
  S2 GAPSTOP   + stops fill at the open when the bar gaps through the stop  <-- the big one
  S3 COST25    + 25 bp round-trip (spread+commission+slippage), flat
  S4 REALISTIC + liquidity-tiered round-trip cost (thin names cost more)

Then: edge by LIQUIDITY TIER (20d avg $-volume) under S4, and YEAR-BY-YEAR under S4.
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
print(f"{len(syms)} syms, rule RSI<{OS:.0f} >={THR}bars hold{N} {TP_ATR:.0f}:{SL_ATR:.0f}",flush=True)

DV_TIERS=[("<1M",0,1e6),("1-5M",1e6,5e6),("5-25M",5e6,25e6),(">25M",25e6,9e18)]
def dv_cost_bp(dv):  # liquidity-tiered round-trip cost estimate
    if dv<1e6:  return 50.0
    if dv<5e6:  return 25.0
    if dv<25e6: return 12.0
    return 6.0

def run(entry,atr,o,h,l,c,gap):
    n=len(c); tp=entry+TP_ATR*atr; sl=entry-SL_ATR*atr; Rp=SL_ATR*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan); wn_arr=np.zeros(n,bool)
    valid=(np.arange(n)<(n-N-1))&(atr>0)&~np.isnan(atr)&~np.isnan(entry)
    for k in range(1,N+1):
        hk=np.full(n,np.nan); hk[:n-k]=h[k:]; lk=np.full(n,np.nan); lk[:n-k]=l[k:]
        okp=np.full(n,np.nan); okp[:n-k]=o[k:]
        tph=hk>=tp; slh=lk<=sl
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        sfill=np.where(okp<=sl,okp,sl) if gap else sl  # gap-through fills at the open
        res[loss]=((sfill[loss] if gap else sl[loss])-entry[loss])/Rp[loss]
        res[wn]=TP_ATR/SL_ATR; wn_arr[wn]=True; resolved|=(loss|wn)
    exitc=np.full(n,np.nan); exitc[:n-N]=c[N:][:n-N]
    to=valid&~resolved; res[to]=(exitc[to]-entry[to])/Rp[to]; wn_arr[to]=res[to]>0
    return res,valid,wn_arr

SC=["S0_ideal","S1_nextopen","S2_gapstop","S3_cost25","S4_realistic"]
# clustered: (scen,bucket,kind) -> [sumMeanR,sumsq,nsym,ntr]; kind in rule/rand
acc=defaultdict(lambda:[0.,0.,0,0])
def bump(k,m,nt):
    a=acc[k]; a[0]+=m; a[1]+=m*m; a[2]+=1; a[3]+=nt
wincnt=defaultdict(lambda:[0,0])  # scen -> [wins,total] over rule entries (global)

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
    dv20=pd.Series(c*v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    os=rsi<OS; age=np.full(n,-1,int); run_=0
    for i in range(n):
        if os[i]: age[i]=run_; run_+=1
        else: run_=0
    nxo=np.full(n,np.nan); nxo[:n-1]=o[1:]   # next-day open
    # base res per scenario (entry/gap differ); valid from the realistic (next-open) variant
    res_ideal,val_i,win_i = run(c,atr,o,h,l,c,gap=False)
    res_no,   val_n,win_n = run(nxo,atr,o,h,l,c,gap=False)
    res_gap,  _,    win_g = run(nxo,atr,o,h,l,c,gap=True)
    cost_flat=(25.0/1e4)/(SL_ATR*atr_pct)
    cost_tier=np.array([dv_cost_bp(x) for x in np.nan_to_num(dv20)])/1e4/(SL_ATR*atr_pct)
    RES={"S0_ideal":(res_ideal,val_i),"S1_nextopen":(res_no,val_n),"S2_gapstop":(res_gap,val_n),
         "S3_cost25":(res_gap-cost_flat,val_n),"S4_realistic":(res_gap-cost_tier,val_n)}
    WIN={"S0_ideal":win_i,"S1_nextopen":win_n,"S2_gapstop":win_g,"S3_cost25":win_g,"S4_realistic":win_g}
    years=np.array([dts[i][:4] for i in range(n)])
    for scen in SC:
        res,val=RES[scen]; ok=elig&val&~np.isnan(res)
        if ok.sum()<MIN_BASE: continue
        ent=sim(np.where(ok&(age>=THR))[0])
        if ent:
            rr=np.array([res[i] for i in ent])
            bump((scen,"FULL","rule"), rr.mean(), len(ent))
            w=WIN[scen]; wincnt[scen][0]+=int(sum(res[i]>0 for i in ent)); wincnt[scen][1]+=len(ent)
            # year buckets (S4 only, to limit volume)
            if scen=="S4_realistic":
                byy=defaultdict(list)
                for i in ent: byy[dts[i][:4]].append(res[i])
                for y,rs in byy.items(): bump((scen,y,"rule"), np.mean(rs), len(rs))
                # liquidity tiers
                for tname,lo,hi in DV_TIERS:
                    sel=[res[i] for i in ent if lo<=np.nan_to_num(dv20[i])<hi]
                    if sel: bump((scen,"LIQ_"+tname,"rule"), np.mean(sel), len(sel))
        # random baseline (absolute R under same friction)
        bump((scen,"FULL","rand"), res[ok].mean(), int(ok.sum()))

def stat(k):
    a=acc.get(k)
    if not a or a[2]<20: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt

print("\n############### CUMULATIVE FRICTION (absolute mean R / trade, clustered) ###############")
print(f"  {'scenario':>13} | {'RULE abs R':>18} {'win%':>5} | {'RANDOM abs R':>16} | {'rule-rand':>9}")
for scen in SC:
    r=stat((scen,"FULL","rule")); b=stat((scen,"FULL","rand"))
    w=wincnt[scen]; wr=100.0*w[0]/w[1] if w[1] else 0
    def F(x): return f"{x[0]:+.4f}R t{x[1]:+.1f} n{x[3]}" if x else "--"
    edge=f"{r[0]-b[0]:+.4f}R" if (r and b) else "--"
    print(f"  {scen:>13} | {F(r):>18} {wr:>4.0f}% | {(F(b)):>16} | {edge:>9}")

print("\n############### S4 REALISTIC — by LIQUIDITY tier (20d avg $-vol) ###############")
print(f"  {'tier':>8} | {'abs mean R':>18} | n_trades")
for tname,_,_ in DV_TIERS:
    s=stat(("S4_realistic","LIQ_"+tname,"rule"))
    print(f"  {tname:>8} | {(f'{s[0]:+.4f}R t{s[1]:+.1f}' if s else '(thin)'):>18} | {s[3] if s else 0}")

print("\n############### S4 REALISTIC — year by year (absolute R) ###############")
print(f"  {'year':>6} | {'abs mean R':>18} | n")
for y in [str(x) for x in range(2016,2027)]:
    s=stat(("S4_realistic",y,"rule"))
    print(f"  {y:>6} | {(f'{s[0]:+.4f}R t{s[1]:+.1f}' if s else '(thin)'):>18} | {s[3] if s else 0}")
