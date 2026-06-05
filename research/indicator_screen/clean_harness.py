"""Clean harness — raw vs clean, per-guard deltas. Built to the spec agreed 2026-06-05.

Audit verdict: data is split-ADJUSTED for major names but adjustment FAILS on small-cap
reverse-splitters (SBFM $104->$21000 etc.), plus Nasdaq test tickers and nonpositive prices.
So: keep adjusted prices (a), bolt on the (b) forward-window gap-skip as a targeted safety net,
plus hard exclusions + vol floor + $-vol floor.

Two metrics, one symbol loop:
  PASS 1 (close-to-close fwd return %, symbol-CLUSTERED lift vs same-symbol baseline):
     report each Ichimoku signal under 4 cleaning levels so each guard's delta is visible:
       L0 raw | L1 +excl(test-tickers,close>0) | L2 +gapskip(>50% daily move in window) | L3 +winsor(±50%)
  PASS 2 (bracketed R, TP2:SL1 hold10, DE-OVERLAPPED, clustered): the production-faithful number,
     fully clean, with matched random-entry benchmark. Includes rsi_oversold re-check.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"; SPLIT="2021-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; DOLLAR_VOL=1_000_000; GAP=0.50; WINSOR=0.50
DISP=26; HSET=[5,10,20]; BR_N=10; TP_ATR,SL_ATR=2.0,1.0
YEARS=[str(y) for y in range(2016,2027)]
TEST_PAT=("ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST")

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
print(f"{len(syms)} symbols (test tickers pre-excluded)",flush=True)

rmx=lambda x,w: pd.Series(x).rolling(w).max().to_numpy(); rmn=lambda x,w: pd.Series(x).rolling(w).min().to_numpy()

# PASS1 clustered accumulators: key (signal,h,regime,level) -> per-symbol lift list aggregated as [sum,sumsq,nsym,ntr]
A={}
def bump(k,lift,nt):
    a=A.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
# PASS2 bracket accumulators: key (name,regime,half) -> [sum,sumsq,nsym,ntr]
B={}
def bumpB(k,lift,nt):
    a=B.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
# PASS2 FULL-POPULATION (every firing, no de-overlap) clustered accumulator — de-overlap sanity check
BF={}
def bumpF(k,lift,nt):
    a=BF.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt

# PASS2b Newey-West accumulator: keep ALL firings, correct the t for overlapping forward windows.
# Two entries j bars apart share (BR_N-j)/BR_N of their forward path, so bracket-outcome autocorrelation
# is triangular and dies at lag BR_N. Bartlett weight w_j = 1 - j/(L+1) with L=BR_N-1 gives
# w_j = (BR_N-j)/BR_N == the true overlap fraction. (Brackets can resolve early, so real overlap <= that
# -> the correction is mildly conservative.) Per-symbol series are concatenated with the kernel reset at
# symbol boundaries: non-firing bars hold 0, so lagged cross-products only land on real firing pairs.
L_NW=BR_N-1
NW_W=np.array([1.0-j/(L_NW+1) for j in range(L_NW+1)])  # NW_W[0]=1 ... NW_W[L]=1/BR_N
NW={}  # key (name,regime) -> [S, M, G0, G1, ..., G_L]: S=sum demeaned outcome, M=#firings, Gj=autocov@lag j
def bumpNW(k,u,m):
    a=NW.setdefault(k,np.zeros(3+L_NW)); a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    for j in range(1,L_NW+1): a[2+j]+=float(u[:-j]@u[j:])

LEVELS=["raw","excl","gapskip","winsor"]

def bracket(h,l,c,atr,N,tp_atr,sl_atr,badpath):
    n=len(c); tp=c+tp_atr*atr; sl=c-sl_atr*atr; Rp=sl_atr*atr
    resolved=np.zeros(n,bool); res=np.full(n,np.nan)
    valid=(np.arange(n)<(n-N))&(atr>0)&~np.isnan(atr)&~badpath
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp[:n-k]; slh[:n-k]=l[k:]<=sl[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=tp_atr/sl_atr; resolved|=(loss|wn)
    ex=np.full(n,np.nan)
    if n-N>0: ex[:n-N]=c[N:][:n-N]
    to=valid&~resolved; res[to]=(ex[to]-c[to])/Rp[to]
    return res,valid

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
    if n<300: continue
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan); dollar=c*vol20
    # daily move magnitude for gap fingerprint
    dmove=np.zeros(n); dmove[1:]=np.abs(c[1:]/np.where(c[:-1]>0,c[:-1],np.nan)-1.0)
    badday=dmove>GAP  # split-fingerprint day

    tk=(rmx(h,9)+rmn(l,9))/2; kj=(rmx(h,26)+rmn(l,26))/2
    sA=np.full(n,np.nan); sB=np.full(n,np.nan)
    sA[DISP:]=((tk+kj)/2)[:n-DISP]; sB[DISP:]=((rmx(h,52)+rmn(l,52))/2)[:n-DISP]
    top=np.fmax(sA,sB); bot=np.fmin(sA,sB)
    chikou_above=np.zeros(n,bool); chikou_above[DISP:]=c[DISP:]>c[:n-DISP]
    above=c>top; below=c<bot; green=sA>sB; tkst=tk>kj
    def cross_up(a,b):
        out=np.zeros(len(a),bool); out[1:]=(a[1:]>b[1:])&(a[:-1]<=b[:-1]); return out
    SIG={"above_cloud":above,"below_cloud":below,"in_cloud":(~above)&(~below)&~np.isnan(top),
         "tk_above_kijun":tkst,"green_cloud":green,"chikou_above":chikou_above,
         "perfect_bull":above&tkst&green&chikou_above,"cloud_breakout":cross_up(c,top),
         "tk_bull_cross":cross_up(tk,kj)}
    os=rsi<30

    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)
    pos=(c>0)&(o>0)&(h>0)&(l>0)
    nonbull=~np.array([isbull(x) for x in dts]); yr=np.array([x[:4] for x in dts])

    # ---- PASS 1: close-to-close fwd return %, 4 cleaning levels ----
    for hh in HSET:
        fr=np.full(n,np.nan)
        if n-hh>0: fr[:n-hh]=c[hh:]/np.where(c[:n-hh]>0,c[:n-hh],np.nan)-1.0
        fr=fr*100.0
        # forward-window bad-path mask: any badday in (t+1..t+hh]
        badpath=np.zeros(n,bool)
        bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
        for t in range(n-hh):
            if cs[t+hh+1]-cs[t+1] > 0: badpath[t]=True
        fr_w=np.clip(fr,-WINSOR*100,WINSOR*100)
        elig={
            "raw":   base_price & ~np.isnan(fr),
            "excl":  base_price & pos & ~np.isnan(fr),
            "gapskip":base_price & pos & ~badpath & ~np.isnan(fr),
            "winsor":base_price & pos & ~np.isnan(fr),
        }
        metric={"raw":fr,"excl":fr,"gapskip":fr,"winsor":fr_w}
        for rk,rmask in (("all",np.ones(n,bool)),("bull",~nonbull),("nonbull",nonbull)):
            for lv in LEVELS:
                e=elig[lv]&rmask; m=metric[lv]
                if e.sum()<20: continue
                bmean=np.nanmean(m[e])
                for sname,smask in SIG.items():
                    sm=e&smask
                    if sm.sum()>=5:
                        bump((sname,hh,rk,lv), float(np.nanmean(m[sm])-bmean), int(sm.sum()))

    # ---- PASS 2: bracketed R, de-overlapped, fully clean ----
    clean_elig = base_price & pos & (atr_pct>=VOL_FLOOR) & (dollar>=DOLLAR_VOL)
    # bad-path for bracket hold window
    badpathB=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
    for t in range(n-BR_N):
        if cs[t+BR_N+1]-cs[t+1]>0: badpathB[t]=True
    res,valid=bracket(h,l,c,atr,BR_N,TP_ATR,SL_ATR,badpathB)
    ok=clean_elig&valid&~np.isnan(res)
    for rk,rmask in (("all",np.ones(n,bool)),("bull",~nonbull),("nonbull",nonbull)):
        base=ok&rmask
        if base.sum()<20: continue
        bmean=res[base].mean()
        for sname,smask in (("above_cloud",above),("below_cloud",below),("perfect_bull",SIG["perfect_bull"]),
                            ("tk_above_kijun",tkst),("green_cloud",green),("rsi_oversold",os),
                            ("below&os",below&os),("below_not_os",below&~os),("rsi_not_below",os&~below),
                            ("RANDOM",np.ones(n,bool))):
            ent=noov(smask&base,res,BR_N)
            if ent: bumpB((sname,rk,"all"), float(np.mean([res[i] for i in ent])-bmean), len(ent))
            # full-population (every firing, no de-overlap): clustered point estimate + Newey-West t
            fidx=np.where(smask&base)[0]
            if len(fidx)>=5:
                bumpF((sname,rk,"all"), float(res[fidx].mean()-bmean), len(fidx))
                u=np.zeros(n); u[fidx]=res[fidx]-bmean
                bumpNW((sname,rk,"all"), u, len(fidx))
        # PER-CALENDAR-YEAR NW (replaces the discredited 2-bin era split: unequal sizes + COVID-in-H1).
        # Each year demeaned vs THAT year's same-regime baseline so the year's beta is removed; COVID
        # isolated to 2020 where it's visible rather than poisoning a 5-year bin.
        for sname,smask in (("below_cloud",below),("below_not_os",below&~os),("rsi_oversold",os)):
            for Y in YEARS:
                yb=ok&rmask&(yr==Y)
                if yb.sum()<20: continue
                ybmean=res[yb].mean()
                fidx=np.where(smask&yb)[0]
                if len(fidx)>=5:
                    bumpF((sname,rk,Y), float(res[fidx].mean()-ybmean), len(fidx))
                    u=np.zeros(n); u[fidx]=res[fidx]-ybmean
                    bumpNW((sname,rk,Y), u, len(fidx))

def st(store,k,minsym=30):
    a=store.get(k)
    if not a or a[2]<minsym: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt

def stNW(k,minfire=50):
    a=NW.get(k)
    if a is None or a[1]<minfire: return None
    S,M=a[0],a[1]; G=a[2:]  # G[0]=Gamma_0, G[j]=Gamma_j
    varS=G[0]+2.0*float(np.dot(NW_W[1:],G[1:]))  # Newey-West: Gamma_0 + 2 sum_j w_j Gamma_j
    if varS<=0: return None
    m=S/M; se=(varS**0.5)/M
    return m,(m/se if se>0 else 0),int(M)

print("\n################ PASS 1: close-to-close edge (clustered lift), per-guard deltas ################")
print("each cell = mean per-symbol lift vs same-symbol baseline (t).  watch if cleaning FLIPS a sign.")
for rk in ("all","nonbull","bull"):
    print(f"\n--- regime={rk}, horizon h10 ---")
    print(f"  {'signal':16} {'L0 raw':>16} {'L1 +excl':>16} {'L2 +gapskip':>16} {'L3 +winsor':>16}")
    for sname in SIG:
        cells=[]
        for lv in LEVELS:
            x=st(A,(sname,10,rk,lv))
            cells.append(f"{x[0]:+.3f}%(t{x[1]:+.0f})" if x else "(thin)")
        print(f"  {sname:16} "+" ".join(f"{c:>16}" for c in cells))

print("\n################ PASS 2: bracketed R, fully clean — DE-OVERLAP vs FULL-POP vs NEWEY-WEST ################")
print(f"  bracket TP{TP_ATR:.0f}:SL{SL_ATR:.0f} hold{BR_N}, vol_floor {VOL_FLOOR}, $vol>={DOLLAR_VOL:,}, gap-skip on path")
print("  point estimates should AGREE (de-overlap unbiased); deov t throws data away, cluster/NW keep all firings (honest t).")
for rk in ("all","nonbull","bull"):
    print(f"\n  --- regime={rk} ---   (lift vs matched random-entry)")
    print(f"    {'signal':15} {'DE-OVERLAP':>22} {'FULL-POP(cluster)':>22} {'FULL-POP(Newey-West)':>26}")
    for sname in ("above_cloud","green_cloud","tk_above_kijun","perfect_bull","below_cloud",
                  "rsi_oversold","below&os","below_not_os","rsi_not_below","RANDOM"):
        b=st(B,(sname,rk,"all")); ff=st(BF,(sname,rk,"all")); nw=stNW((sname,rk,"all"))
        c1=f"{b[0]:+.3f}R t={b[1]:+.1f} n={b[3]}" if b else "(thin)"
        c2=f"{ff[0]:+.3f}R t={ff[1]:+.1f}" if ff else "(thin)"
        c3=f"{nw[0]:+.3f}R t={nw[1]:+.1f} n={nw[2]}" if nw else "(thin)"
        print(f"    {sname:15} {c1:>22} {c2:>22} {c3:>26}")

print("\n################ PER-YEAR NW (bracketed R lift vs that-year same-regime random) ################")
print("  replaces the discarded 2-bin era split (unequal + COVID-in-H1). 2020 isolated so you can SEE COVID.")
print("  read: count the +/- years and whether any single year (esp 2020) carries the sign.  '.'=thin year.")
for sname in ("below_not_os","below_cloud","rsi_oversold"):
    for rk in ("nonbull","all"):
        cells=[]; npos=nneg=0
        for Y in YEARS:
            x=stNW((sname,rk,Y),minfire=30)
            if not x: cells.append(f"{Y[2:]}:  .   "); continue
            if x[0]>0: npos+=1
            else: nneg+=1
            cells.append(f"{Y[2:]}:{x[0]:+.2f}({x[1]:+.0f})")
        print(f"  {sname:13} {rk:8} [+{npos}/-{nneg}yr]")
        print("     "+" ".join(cells))
print("\ndone.")
