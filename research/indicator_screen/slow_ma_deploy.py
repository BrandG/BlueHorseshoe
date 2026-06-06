"""Slow-MA dislocation — deployment-readiness test (year-stability + cost/liq + overlap vs cloud).

nw_broad_sweep.py found below_sma200 / far_below_sma50 / far_below_sma200 are de-overlap false-negatives,
positive ALL-REGIME under NW (t8-12) — candidate to be the all-regime contrarian sleeve the COVID-fragile
rsi_oversold and the age-gated-only cloud couldn't cleanly give. Before believing it, the faithful checks:

  PART A  COST/LIQ: liquid >$25M tier, NEXT-OPEN entry + GAP-STOPS (gap through stop fills at open, not the
          level), tiered round-trip bps. Report ABSOLUTE net R of the signal's trades vs RANDOM (universe)
          trades in the SAME liquid universe — monetizes only if signal_net beats random_net (per
          below_not_os_monetize: all-regime cloud lift was real but composition-cancelled to ~random abs R).
  PART B  YEAR-STABILITY: per-calendar-year NW lift, 2020/COVID isolated. The cloud is +11/-0 incl COVID;
          rsi is COVID-fragile. Which is the slow-MA family?
  PART C  OVERLAP vs below_cloud: split firings ∩cloud vs ∩~cloud. Survives off the cloud bars => new
          coverage; collapses => same cloud factor (don't add a duplicate sleeve).

Bracket TP2:SL1, holds 10 & 20. Machinery otherwise identical to clean_harness (vol floor, gap-skip path,
symbol-cluster, NW Bartlett L=hold-1). NOT a final deploy sign-off — faithful entry/exit + paper still after.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; DOLLAR_VOL=1_000_000; DOLLAR_VOL_LIQ=25_000_000; GAP=0.50; DISP=26
TP_ATR,SL_ATR=2.0,1.0
HOLDS=[10,20]; YEARS=[str(y) for y in range(2016,2027)]
BPS_TIERS=[0,5,10,20]   # round-trip
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")
SIGS=["far_below_sma50","below_sma200","far_below_sma200"]

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg_map=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg_map.get(str(d)[:10],False)
syms=con.execute("""SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300""",[START]).df().symbol.tolist()
syms=[s for s in syms if s not in TEST_PAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
print(f"{len(syms)} symbols; liquid tier $vol>=${DOLLAR_VOL_LIQ:,}; next-open+gap-stops",flush=True)

rmx=lambda x,w: pd.Series(x).rolling(w).max().to_numpy(); rmn=lambda x,w: pd.Series(x).rolling(w).min().to_numpy()
# absolute-net accumulators: key -> [sum_gross, sum_cunit, n]  (net@bps = mean_gross - mean_cunit*bps/1e4)
AB={}
def bumpAB(k,g,cu,ntr):
    a=AB.setdefault(k,[0.,0.,0]); a[0]+=g; a[1]+=cu; a[2]+=ntr
# NW lift accumulators (symbol-clustered demean): key -> [S,M,G0..GL] with L per hold
NW={}
def bumpNW(k,u,m,L):
    a=NW.setdefault(k,np.zeros(3+L)); a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    for j in range(1,L+1): a[2+j]+=float(u[:-j]@u[j:])

def bracket_nextopen(o,h,l,c,atr,N,badpath):
    """Enter at next open, TP/SL from entry +/- ATR*mult, gap-stops fill at the open. Returns (res,cunit,valid)."""
    n=len(c); E=np.full(n,np.nan); E[:n-1]=o[1:]
    Rp=SL_ATR*atr; tp=E+TP_ATR*atr; sl=E-SL_ATR*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan)
    valid=(np.arange(n)<(n-N-1))&(atr>0)&~np.isnan(atr)&~badpath&(E>0)
    for k in range(1,N+1):
        Ok=np.full(n,np.nan); Hk=np.full(n,np.nan); Lk=np.full(n,np.nan)
        Ok[:n-k]=o[k:]; Hk[:n-k]=h[k:]; Lk[:n-k]=l[k:]
        live=valid&~resolved
        g_sl=live&(Ok<=sl); res[g_sl]=(Ok[g_sl]-E[g_sl])/Rp[g_sl]; resolved|=g_sl   # gap-stop: fill at open (<-1R)
        live=valid&~resolved
        g_tp=live&(Ok>=tp); res[g_tp]=(Ok[g_tp]-E[g_tp])/Rp[g_tp]; resolved|=g_tp   # gap through TP: fill at open (>+2R)
        live=valid&~resolved
        both=live&(Hk>=tp)&(Lk<=sl); res[both]=-1.0; resolved|=both                  # intrabar both -> stop first
        live=valid&~resolved
        tpo=live&(Hk>=tp); res[tpo]=TP_ATR/SL_ATR; resolved|=tpo
        live=valid&~resolved
        slo=live&(Lk<=sl); res[slo]=-1.0; resolved|=slo
    CN=np.full(n,np.nan); CN[:n-N]=c[N:]; to=valid&~resolved; res[to]=(CN[to]-E[to])/Rp[to]
    cunit=np.where(Rp>0,E/Rp,np.nan)   # cost_R at b bps = cunit*b/1e4
    return res,cunit,valid

for ii,sym in enumerate(syms):
    if ii%400==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    if n<300: continue
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan); dollar=c*vol20; yr=np.array([x[:4] for x in dts])
    dmove=np.zeros(n); dmove[1:]=np.abs(c[1:]/np.where(c[:-1]>0,c[:-1],np.nan)-1.0); badday=dmove>GAP
    nonbull=~np.array([isbull(x) for x in dts])
    sma50=talib.SMA(c,50); sma200=talib.SMA(c,200)
    sA=np.full(n,np.nan); sB=np.full(n,np.nan)
    tk=(rmx(h,9)+rmn(l,9))/2; kj=(rmx(h,26)+rmn(l,26))/2
    sA[DISP:]=((tk+kj)/2)[:n-DISP]; sB[DISP:]=((rmx(h,52)+rmn(l,52))/2)[:n-DISP]
    below_cloud=c<np.fmin(sA,sB)
    SIG={
      "far_below_sma50":(c<sma50)&((sma50-c)/np.where(atr>0,atr,np.nan)>2.0),
      "below_sma200":c<sma200,
      "far_below_sma200":(c<sma200)&((sma200-c)/np.where(sma200>0,sma200,np.nan)>0.10),
    }
    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL); posb=(c>0)&(o>0)&(h>0)&(l>0)
    liq=base_price&posb&(atr_pct>=VOL_FLOOR)&(dollar>=DOLLAR_VOL_LIQ)

    for N in HOLDS:
        L=N-1
        badpathB=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
        for t in range(n-N):
            if cs[t+N+1]-cs[t+1]>0: badpathB[t]=True
        res,cunit,valid=bracket_nextopen(o,h,l,c,atr,N,badpathB)
        ok=liq&valid&~np.isnan(res)
        for rk,rmask in (("all",np.ones(n,bool)),("nonbull",nonbull)):
            base=ok&rmask
            if base.sum()<20: continue
            bmean=res[base].mean()
            # universe (RANDOM) absolute-net
            ub=np.where(base)[0]
            bumpAB(("RANDOM",rk,N), res[ub].sum(), np.nansum(cunit[ub]), len(ub))
            for sname in SIGS:
                fidx=np.where(np.asarray(SIG[sname],bool)&base)[0]
                if len(fidx)<5: continue
                bumpAB((sname,rk,N), res[fidx].sum(), np.nansum(cunit[fidx]), len(fidx))
                u=np.zeros(n); u[fidx]=res[fidx]-bmean; bumpNW((sname,rk,N,"lift"),u,len(fidx),L)
                if N==10:
                    # PART B per-year lift
                    for Y in YEARS:
                        yb=base&(yr==Y)
                        if yb.sum()<20: continue
                        ybmean=res[yb].mean(); fy=np.where(np.asarray(SIG[sname],bool)&yb)[0]
                        if len(fy)>=5:
                            uy=np.zeros(n); uy[fy]=res[fy]-ybmean; bumpNW((sname,rk,"Y"+Y),uy,len(fy),L)
                    # PART C cloud overlap
                    for tag,cm in (("incloud",below_cloud),("offcloud",~below_cloud)):
                        fc=np.where(np.asarray(SIG[sname],bool)&base&cm)[0]
                        if len(fc)>=5:
                            uc=np.zeros(n); uc[fc]=res[fc]-bmean; bumpNW((sname,rk,tag),uc,len(fc),L)

def nw(k,L,minfire=50):
    a=NW.get(k)
    if a is None or a[1]<minfire: return None
    S,M=a[0],a[1]; G=a[2:]; W=np.array([1.0-j/(L+1) for j in range(L+1)])
    varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def absnet(k,bps):
    a=AB.get(k)
    if not a or a[2]<50: return None
    sg,scu,nn=a; return sg/nn - (scu/nn)*bps/1e4, nn

print("\n################ PART A — COST / LIQ (liquid >$25M, next-open + gap-stops) ################")
print("  ABSOLUTE mean net R of the signal's trades vs RANDOM (same liquid universe). monetizes iff signal>random.")
for rk in ("all","nonbull"):
    for N in HOLDS:
        L=N-1
        rnd=absnet(("RANDOM",rk,N),10)
        print(f"\n  regime={rk} hold{N}  [RANDOM net@10bps={rnd[0]:+.3f}R n={rnd[1]}]" if rnd else f"\n  regime={rk} hold{N} [random thin]")
        print(f"    {'signal':17} {'gross NW lift':>20} {'net@10bps(abs)':>16} {'lift vs rand':>14}")
        for sname in SIGS:
            li=nw((sname,rk,N,"lift"),L); an=absnet((sname,rk,N),10)
            cl=f"{li[0]:+.3f}R t{li[1]:+.1f} n{li[2]}" if li else "(thin)"
            ca=f"{an[0]:+.3f}R" if an else "(thin)"
            lv=f"{an[0]-rnd[0]:+.3f}R" if (an and rnd) else " ."
            print(f"    {sname:17} {cl:>20} {ca:>16} {lv:>14}")
print("\n  -- bps sensitivity (abs net R), hold10 --")
for rk in ("all","nonbull"):
    rnd={b:absnet(("RANDOM",rk,10),b) for b in BPS_TIERS}
    print(f"   regime={rk}: " + "  ".join(f"RAND@{b}={rnd[b][0]:+.3f}" for b in BPS_TIERS if rnd[b]))
    for sname in SIGS:
        cells=[absnet((sname,rk,10),b) for b in BPS_TIERS]
        print(f"     {sname:17} " + "  ".join(f"@{b}={c[0]:+.3f}" if c else f"@{b}=." for b,c in zip(BPS_TIERS,cells)))

print("\n################ PART B — YEAR-STABILITY (per-year NW lift, hold10, 2020=COVID) ################")
for sname in SIGS:
    for rk in ("all","nonbull"):
        cells=[]; npos=nneg=0
        for Y in YEARS:
            x=nw((sname,rk,"Y"+Y),9,minfire=30)
            if not x: cells.append(f"{Y[2:]}:  .  "); continue
            if x[0]>0: npos+=1
            else: nneg+=1
            cells.append(f"{Y[2:]}:{x[0]:+.2f}({x[1]:+.0f})")
        print(f"  {sname:17} {rk:8} [+{npos}/-{nneg}yr]")
        print("     "+" ".join(cells))

print("\n################ PART C — OVERLAP vs below_cloud (hold10 NW lift) ################")
print("  offcloud still + => new coverage beyond the cloud; collapses => same cloud factor.")
for sname in ("far_below_sma50","below_sma200"):
    for rk in ("all","nonbull"):
        ic=nw((sname,rk,"incloud"),9,minfire=30); oc=nw((sname,rk,"offcloud"),9,minfire=30)
        cic=f"{ic[0]:+.3f}R t{ic[1]:+.1f} n{ic[2]}" if ic else "(thin)"
        coc=f"{oc[0]:+.3f}R t{oc[1]:+.1f} n{oc[2]}" if oc else "(thin)"
        print(f"    {sname:17} {rk:8}  ∩cloud {cic:>24}   |  ∩~cloud {coc:>24}")
print("\ndone.")
