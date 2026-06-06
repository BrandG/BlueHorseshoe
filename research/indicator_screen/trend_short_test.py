"""Trend/breakout family as SHORT selectors — the constructive flip of the negative-long result.

Brand's correction ([[feedback_trend_family_not_dead]]): the trend family being negative for a LONG 2:1
bracket on a 10d mean-reverting horizon is NOT "dead" — it's a candidate SHORT selector. Test it honestly:
flip the SAME geometry to the short side and measure.

SHORT bracket: enter next open E; TP = E - 2*ATR (profit on a fall); SL = E + 1*ATR (loss on a rise);
R = (E - exit)/(1*ATR). Gap-stops (gap up through SL fills at open, <-1R; gap down through TP fills at
open, >+2R). Liquid >$25M, tiered TXN bps + BORROW cost (bps/yr * held_days/365, modeled per-trade).
Regimes split all/nonbull/bull (shorts are regime-sensitive — expect best in nonbull, worst in bull;
SEE it, don't pool it). Random-short benchmark = the same short bracket on all universe bars: on an
up-drifting universe random-short LOSES, so a signal must beat (be less negative / positive vs) random.

CAVEATS baked into the read: negative-long does NOT guarantee profitable-short (geometry inverts; the
bounce that kills the long-trend entry also squeezes the short; borrow cost is real). This MEASURES it.
Not a deploy sign-off — faithful borrow/locate + paper still after if anything clears.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; DOLLAR_VOL_LIQ=25_000_000; GAP=0.50
TP_ATR,SL_ATR=2.0,1.0; HOLDS=[10,20]; YEARS=[str(y) for y in range(2016,2027)]
BPS_TIERS=[0,5,10,20]; BORROW_TIERS=[0,50,300]   # txn round-trip bps ; borrow bps/yr
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")
SIGS=["donchian_high","above_sma200","golden_cross","rsi_strong","stoch_ob","macd_bull","adx_uptrend","psar_long"]

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
print(f"{len(syms)} symbols; SHORT bracket; liquid >$25M; next-open+gap-stops+borrow",flush=True)

rmx=lambda x,w: pd.Series(x).rolling(w).max().to_numpy(); rmn=lambda x,w: pd.Series(x).rolling(w).min().to_numpy()
AB={}  # key -> [sum_gross, sum_cunit, sum_cunit_holddays, n]
def bumpAB(k,g,cu,cuh,ntr):
    a=AB.setdefault(k,[0.,0.,0.,0]); a[0]+=g; a[1]+=cu; a[2]+=cuh; a[3]+=ntr
NW={}
def bumpNW(k,u,m,L):
    a=NW.setdefault(k,np.zeros(3+L)); a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    for j in range(1,L+1): a[2+j]+=float(u[:-j]@u[j:])

def bracket_short(o,h,l,c,atr,N,badpath):
    n=len(c); E=np.full(n,np.nan); E[:n-1]=o[1:]
    Rp=SL_ATR*atr; tp=E-TP_ATR*atr; sl=E+SL_ATR*atr      # short: TP below, SL above
    resolved=np.zeros(n,bool); res=np.full(n,np.nan); holdk=np.zeros(n)
    valid=(np.arange(n)<(n-N-1))&(atr>0)&~np.isnan(atr)&~badpath&(E>0)
    for k in range(1,N+1):
        Ok=np.full(n,np.nan); Hk=np.full(n,np.nan); Lk=np.full(n,np.nan)
        Ok[:n-k]=o[k:]; Hk[:n-k]=h[k:]; Lk[:n-k]=l[k:]
        live=valid&~resolved
        gsl=live&(Ok>=sl); res[gsl]=(E[gsl]-Ok[gsl])/Rp[gsl]; holdk[gsl]=k; resolved|=gsl   # gap up -> gap-stop (<-1R)
        live=valid&~resolved
        gtp=live&(Ok<=tp); res[gtp]=(E[gtp]-Ok[gtp])/Rp[gtp]; holdk[gtp]=k; resolved|=gtp   # gap down -> fill open (>+2R)
        live=valid&~resolved
        both=live&(Lk<=tp)&(Hk>=sl); res[both]=-1.0; holdk[both]=k; resolved|=both           # both -> stop first
        live=valid&~resolved
        tpo=live&(Lk<=tp); res[tpo]=TP_ATR/SL_ATR; holdk[tpo]=k; resolved|=tpo
        live=valid&~resolved
        slo=live&(Hk>=sl); res[slo]=-1.0; holdk[slo]=k; resolved|=slo
    CN=np.full(n,np.nan); CN[:n-N]=c[N:]; to=valid&~resolved
    res[to]=(E[to]-CN[to])/Rp[to]; holdk[to]=N
    cunit=np.where(Rp>0,E/Rp,np.nan)
    return res,cunit,holdk,valid

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
    sma50=talib.SMA(c,50); sma200=talib.SMA(c,200); slowk,_=talib.STOCH(h,l,c)
    macd,macdsig,_=talib.MACD(c,12,26,9); sar=talib.SAR(h,l,0.02,0.2)
    adx=talib.ADX(h,l,c,14); pdi=talib.PLUS_DI(h,l,c,14); mdi=talib.MINUS_DI(h,l,c,14)
    donhi=rmx(h,20)
    SIG={"donchian_high":c>=donhi,"above_sma200":c>sma200,"golden_cross":sma50>sma200,"rsi_strong":rsi>50,
         "stoch_ob":slowk>80,"macd_bull":macd>macdsig,"adx_uptrend":(adx>25)&(pdi>mdi),"psar_long":c>sar}
    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL); posb=(c>0)&(o>0)&(h>0)&(l>0)
    liq=base_price&posb&(atr_pct>=VOL_FLOOR)&(dollar>=DOLLAR_VOL_LIQ)

    for N in HOLDS:
        L=N-1
        badpathB=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
        for t in range(n-N):
            if cs[t+N+1]-cs[t+1]>0: badpathB[t]=True
        res,cunit,holdk,valid=bracket_short(o,h,l,c,atr,N,badpathB)
        ok=liq&valid&~np.isnan(res)
        for rk,rmask in (("all",np.ones(n,bool)),("nonbull",nonbull),("bull",~nonbull)):
            base=ok&rmask
            if base.sum()<20: continue
            bmean=res[base].mean()
            ub=np.where(base)[0]
            bumpAB(("RANDOM",rk,N), res[ub].sum(), np.nansum(cunit[ub]), np.nansum(cunit[ub]*holdk[ub]), len(ub))
            for sname in SIGS:
                fidx=np.where(np.asarray(SIG[sname],bool)&base)[0]
                if len(fidx)<5: continue
                bumpAB((sname,rk,N), res[fidx].sum(), np.nansum(cunit[fidx]),
                       np.nansum(cunit[fidx]*holdk[fidx]), len(fidx))
                u=np.zeros(n); u[fidx]=res[fidx]-bmean; bumpNW((sname,rk,N,"lift"),u,len(fidx),L)
                if N==10:
                    for Y in YEARS:
                        yb=base&(yr==Y)
                        if yb.sum()<20: continue
                        ybm=res[yb].mean(); fy=np.where(np.asarray(SIG[sname],bool)&yb)[0]
                        if len(fy)>=5:
                            uy=np.zeros(n); uy[fy]=res[fy]-ybm; bumpNW((sname,rk,"Y"+Y),uy,len(fy),L)

def nw(k,L,minfire=50):
    a=NW.get(k)
    if a is None or a[1]<minfire: return None
    S,M=a[0],a[1]; G=a[2:]; W=np.array([1.0-j/(L+1) for j in range(L+1)])
    varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def absnet(k,bps,borrow):
    a=AB.get(k)
    if not a or a[3]<50: return None
    sg,scu,scuh,nn=a
    return sg/nn - (scu/nn)*bps/1e4 - (scuh/nn)*(borrow/1e4)/365, nn

print("\n############### TREND-AS-SHORT — COST/LIQ (liquid >$25M, short bracket, next-open+gap-stops) ###############")
print("  abs net @ 10bps txn + 50bps/yr borrow.  vs RANDOM-short (same universe).  SHORT wins where market falls.")
for rk in ("nonbull","all","bull"):
    for N in (HOLDS if rk=="nonbull" else [10]):
        L=N-1; rnd=absnet(("RANDOM",rk,N),10,50)
        hdr=f"[RANDOM-short net={rnd[0]:+.3f}R n={rnd[1]}]" if rnd else "[random thin]"
        print(f"\n  regime={rk} hold{N}  {hdr}")
        print(f"    {'signal':14} {'gross NW lift':>20} {'net(10bps+50brw)':>18} {'lift vs rand':>14}")
        for sname in SIGS:
            li=nw((sname,rk,N,"lift"),L); an=absnet((sname,rk,N),10,50)
            cl=f"{li[0]:+.3f}R t{li[1]:+.1f}" if li else "(thin)"
            ca=f"{an[0]:+.3f}R" if an else "(thin)"
            lv=f"{an[0]-rnd[0]:+.3f}R" if (an and rnd) else " ."
            print(f"    {sname:14} {cl:>20} {ca:>18} {lv:>14}")
print("\n  -- borrow sensitivity (abs net R, nonbull hold10, txn=10bps) --")
rnd={b:absnet(("RANDOM","nonbull",10),10,b) for b in BORROW_TIERS}
print("   RANDOM-short: "+"  ".join(f"brw{b}={rnd[b][0]:+.3f}" for b in BORROW_TIERS if rnd[b]))
for sname in SIGS:
    cells=[absnet((sname,"nonbull",10),10,b) for b in BORROW_TIERS]
    print(f"     {sname:14} "+"  ".join(f"brw{b}={c[0]:+.3f}" if c else f"brw{b}=." for b,c in zip(BORROW_TIERS,cells)))

print("\n############### YEAR-STABILITY (per-year NW lift vs random-short, hold10, 2020=COVID) ###############")
for sname in SIGS:
    for rk in ("nonbull","all"):
        cells=[]; npos=nneg=0
        for Y in YEARS:
            x=nw((sname,rk,"Y"+Y),9,minfire=30)
            if not x: cells.append(f"{Y[2:]}:  .  "); continue
            if x[0]>0: npos+=1
            else: nneg+=1
            cells.append(f"{Y[2:]}:{x[0]:+.2f}({x[1]:+.0f})")
        print(f"  {sname:14} {rk:8} [+{npos}/-{nneg}yr]  "+" ".join(cells))
print("\ndone.")
