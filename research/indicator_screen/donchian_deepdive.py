"""Donchian deep-dive under the blessed Newey-West harness.

Mandate (Brand): apply the same rigor as the ADX/PSAR/Ichimoku/HA dives to see if
Donchian is salvageable. Priors from the broad sweep & trend_short_test:
  - donchian_high (breakout) LONG = -0.130R all / ~flat-absolute nonbull  -> no continuation edge.
  - donchian_high SHORT = worst of trend family, net -0.436R nonbull       -> short door closed by costs.
  - donchian_low (20d low) LONG = -0.132R t-1.7 nonbull (n417, thin)       -> looks like a KNIFE, but 1 point.

This dive tests the one open door — the BREAKDOWN (new N-day low) as a contrarian long —
across the dimensions that decided every prior indicator:
  1) TIMESCALE sweep N in {10,20,55}: is a slow 55d low a persistent dislocation (alpha, like
     below_sma200) while a fast 10/20d low is a knife (like gap_down)?
  2) HOLD sweep {10,20}: slow dislocation pays more at longer holds.
  3) CHANNEL POSITION deciles (continuous (c-lo)/(hi-lo)): monotonic oversold gradient?
  4) SLOW-CONTEXT split: don_low & below_sma200 (slow) vs & above_sma200 (knife-in-uptrend).
  5) PER-YEAR NW stability (COVID-2020 robustness) for the low cells.
  6) INCREMENTAL EDGE vs the dislocation factor (rsi<30 | below_cloud | below_sma200) — orthogonal or
     redundant? (the test that closed HA/ADX/PSAR).

Machinery byte-identical to nw_broad_sweep.py: bracket TP2:SL1, vol+$vol floors, gap-skip path,
NW Bartlett L=hold-1, demean vs same-regime random. Channel uses PREVIOUS-window bands (shift 1),
matching production calculate_donchian()'s .shift(1).
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; DOLLAR_VOL=1_000_000; GAP=0.50; DISP=26
TP_ATR,SL_ATR=2.0,1.0
HOLDS=(10,20)
DON_NS=(10,20,55)
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
print(f"{len(syms)} symbols; prev-window Donchian bands; bracket TP{TP_ATR:.0f}:SL{SL_ATR:.0f}",flush=True)

rmx=lambda x,w: pd.Series(x).rolling(w).max().to_numpy(); rmn=lambda x,w: pd.Series(x).rolling(w).min().to_numpy()
def shift(a,k):
    out=np.full(len(a),np.nan)
    if k<len(a): out[k:]=a[:-k]
    return out

# ---- accumulators: clustered (de-overlap & full-pop) + Newey-West, keyed by arbitrary tuple ----
B={}      # de-overlap clustered
def bumpB(k,lift,nt):
    a=B.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
BF={}     # full-pop clustered
def bumpF(k,lift,nt):
    a=BF.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
NW={}     # Newey-West (trade-weighted); L set per hold
def make_nw_w(L): return np.array([1.0-j/(L+1) for j in range(L+1)])
def bumpNW(k,u,m,L):
    a=NW.setdefault(k,np.zeros(3+30)); a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    for j in range(1,L+1): a[2+j]+=float(u[:-j]@u[j:])

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
    yr=d.date.astype(str).str[:4].to_numpy()
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan); dollar=c*vol20
    dmove=np.zeros(n); dmove[1:]=np.abs(c[1:]/np.where(c[:-1]>0,c[:-1],np.nan)-1.0); badday=dmove>GAP
    nonbull=~np.array([isbull(x) for x in dts])
    sma200=talib.SMA(c,200)
    # Ichimoku cloud bottom (for dislocation factor / incremental test)
    sA=np.full(n,np.nan); sB=np.full(n,np.nan)
    tk=(rmx(h,9)+rmn(l,9))/2; kj=(rmx(h,26)+rmn(l,26))/2
    sA[DISP:]=((tk+kj)/2)[:n-DISP]; sB[DISP:]=((rmx(h,52)+rmn(l,52))/2)[:n-DISP]
    bot=np.fmin(sA,sB)
    disloc=(rsi<30)|(c<bot)|(c<sma200)   # the existing slow/known dislocation factor

    # prev-window Donchian bands at each N (shift 1 = production-faithful)
    lo={N:shift(rmn(l,N),1) for N in DON_NS}
    hi={N:shift(rmx(h,N),1) for N in DON_NS}
    low_sig={N:(c<lo[N]) for N in DON_NS}          # downside breakout = new N-day low
    high_sig={N:(c>hi[N]) for N in DON_NS}         # upside breakout = new N-day high
    # channel position at N=20 (continuous), deciles q0(near low)..q9(near high)
    width=hi[20]-lo[20]; cpos=np.where(width>1e-9,(c-lo[20])/width,np.nan)

    SIG={}
    for N in DON_NS:
        SIG[f"don_low_{N}"]=low_sig[N]
        SIG[f"don_high_{N}"]=high_sig[N]
    for q in range(10):
        SIG[f"cpos_q{q}"]=(cpos>=q/10.0)&(cpos<(q+1)/10.0)
    # slow-context split on the 55d and 20d low
    for N in (20,55):
        SIG[f"don_low_{N}_below200"]=low_sig[N]&(c<sma200)
        SIG[f"don_low_{N}_above200"]=low_sig[N]&(c>=sma200)
    # incremental: 55d low orthogonal to the dislocation factor (and the 20d)
    SIG["don_low_55_resid"]=low_sig[55]&~disloc
    SIG["don_low_55_indisloc"]=low_sig[55]&disloc
    SIG["don_low_20_resid"]=low_sig[20]&~disloc
    SIG["RANDOM"]=np.ones(n,bool)

    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL); pos=(c>0)&(o>0)&(h>0)&(l>0)
    clean_elig=base_price&pos&(atr_pct>=VOL_FLOOR)&(dollar>=DOLLAR_VOL)

    for BR_N in HOLDS:
        L=BR_N-1
        badpathB=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
        for t in range(n-BR_N):
            if cs[t+BR_N+1]-cs[t+1]>0: badpathB[t]=True
        res,valid=bracket(h,l,c,atr,BR_N,TP_ATR,SL_ATR,badpathB)
        ok=clean_elig&valid&~np.isnan(res)
        for rk,rmask in (("nonbull",nonbull),("all",np.ones(n,bool))):
            base=ok&rmask
            if base.sum()<20: continue
            bmean=res[base].mean()
            for sname,sraw in SIG.items():
                smask=np.asarray(sraw,bool)&base
                ent=noov(smask,res,BR_N)
                if ent: bumpB((sname,rk,BR_N), float(np.mean([res[i] for i in ent])-bmean), len(ent))
                fidx=np.where(smask)[0]
                if len(fidx)>=5:
                    bumpF((sname,rk,BR_N), float(res[fidx].mean()-bmean), len(fidx))
                    u=np.zeros(n); u[fidx]=res[fidx]-bmean
                    bumpNW((sname,rk,BR_N), u, len(fidx), L)
                    # per-year NW only at hold10 for the low/high cells
                    if BR_N==10 and (sname.startswith("don_low_") or sname.startswith("don_high_")) and "_" not in sname[8:]:
                        for Y in np.unique(yr[fidx]):
                            ym=smask&(yr==Y); yi=np.where(ym)[0]
                            if len(yi)>=5:
                                uy=np.zeros(n); uy[yi]=res[yi]-bmean
                                bumpNW((sname,rk,BR_N,Y), uy, len(yi), L)

def stC(store,k,minsym=30):
    a=store.get(k)
    if not a or a[2]<minsym: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt
def stNW(k,minfire=50):
    a=NW.get(k)
    if a is None or a[1]<minfire: return None
    L=k[2]-1 if isinstance(k[2],int) else 9
    W=make_nw_w(L)
    S,M=a[0],a[1]; G=a[2:2+1+L]; varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)

def line(sname,rk,BR_N):
    b=stC(B,(sname,rk,BR_N)); ff=stC(BF,(sname,rk,BR_N)); nw=stNW((sname,rk,BR_N))
    c1=f"{b[0]:+.3f}R t{b[1]:+.1f}" if b else "(thin)"
    c2=f"{ff[0]:+.3f}R t{ff[1]:+.1f}" if ff else "(thin)"
    c3=f"{nw[0]:+.3f}R t{nw[1]:+.1f} n{nw[2]}" if nw else "(thin)"
    return f"    {sname:20} {c1:>20} {c2:>18} {c3:>22}"

print("\n################ DONCHIAN DEEP-DIVE — DE-OVERLAP | FULL-POP(clus) | NEWEY-WEST ################")
print(f"  prev-window bands; bracket TP{TP_ATR:.0f}:SL{SL_ATR:.0f}; vol_floor {VOL_FLOOR}; $vol>={DOLLAR_VOL:,}")
print("  Read: a salvageable contrarian LOW shows NW positive & t>=~3, growing with N (slow) and hold.")
for BR_N in HOLDS:
    for rk in ("nonbull","all"):
        print(f"\n  ===================== hold{BR_N}  regime={rk} =====================")
        print(f"    {'signal':20} {'DE-OVERLAP':>20} {'FULL-POP':>18} {'NEWEY-WEST':>22}")
        print("   -- BREAKDOWN longs (new N-day low) --")
        for N in DON_NS: print(line(f"don_low_{N}",rk,BR_N))
        print("   -- BREAKOUT longs (new N-day high) [control] --")
        for N in DON_NS: print(line(f"don_high_{N}",rk,BR_N))
        print("   -- CHANNEL POSITION deciles N=20 (q0=near low) --")
        for q in range(10): print(line(f"cpos_q{q}",rk,BR_N))
        print("   -- SLOW-CONTEXT split (low & below/above SMA200) --")
        for N in (20,55):
            print(line(f"don_low_{N}_below200",rk,BR_N)); print(line(f"don_low_{N}_above200",rk,BR_N))
        print("   -- INCREMENTAL vs dislocation factor (rsi<30|below_cloud|below_sma200) --")
        print(line("don_low_55_indisloc",rk,BR_N)); print(line("don_low_55_resid",rk,BR_N))
        print(line("don_low_20_resid",rk,BR_N))
        print("   -- RANDOM (machinery check) --")
        print(line("RANDOM",rk,BR_N))

print("\n############### PER-YEAR NW (hold10, lift vs same-regime random; 2020=COVID) ###############")
for rk in ("nonbull","all"):
    print(f"\n  regime={rk}")
    for N in DON_NS:
        for tag in (f"don_low_{N}",f"don_high_{N}"):
            cells=[]
            for Y in [str(y) for y in range(2016,2027)]:
                nw=stNW((tag,rk,10,Y),minfire=20)
                cells.append(f"{Y[2:]}:{nw[0]:+.2f}(t{nw[1]:+.0f})" if nw else f"{Y[2:]}: .  ")
            print(f"    {tag:16} "+"  ".join(cells))
print("\ndone.")
