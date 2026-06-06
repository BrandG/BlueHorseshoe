"""Broad NW re-sweep: which 'dead' indicators were de-overlap FALSE NEGATIVES?

The mandate from [[project_deoverlap_signflip_newey_west]]: de-overlap (onset-only) is a BIASED estimator
for persisting dislocation signals — it keeps the falling-knife onset bar and discards the deeper-in-run
bars where reversion edge lives. It buried below_cloud (deov t1.1 -> NW t2.4) and rsi_oversold. PSAR/ADX
are now re-audited (both stay dead). This sweeps the REMAINING ~30 indicators across all factor families
through the identical blessed 3-column machinery to find any OTHER buried edge.

Read: scan the NW column. The buried-edge signature is DE-OVERLAP <=0/ns  ->  FULL-POP & NW positive & t>=~3.
Contrarian/oversold/below signals are the prime suspects (persisting dislocations). Trend/breakout controls
should STAY negative under all three SEs (NW made PSAR/ADX-trend MORE negative) — a positive there is a flag.
Anchors (rsi_oversold, below_cloud, below_not_os) calibrate the scale. NOT a deploy test — flips get the
full year-stability + cost + overlap follow-up before anyone believes them.

Machinery byte-identical to clean_harness.py PASS 2: bracket TP2:SL1 hold10, vol floor, $-vol floor,
gap-skip path, symbol-cluster, NW Bartlett L=BR_N-1, demean vs same-regime random.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; DOLLAR_VOL=1_000_000; GAP=0.50; DISP=26
BR_N=10; TP_ATR,SL_ATR=2.0,1.0
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
print(f"{len(syms)} symbols",flush=True)

rmx=lambda x,w: pd.Series(x).rolling(w).max().to_numpy(); rmn=lambda x,w: pd.Series(x).rolling(w).min().to_numpy()
def shift(a,k):
    out=np.full(len(a),np.nan);
    if k<len(a): out[k:]=a[:-k]
    return out

B={};
def bumpB(k,lift,nt):
    a=B.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
BF={}
def bumpF(k,lift,nt):
    a=BF.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
L_NW=BR_N-1; NW_W=np.array([1.0-j/(L_NW+1) for j in range(L_NW+1)])
NW={}
def bumpNW(k,u,m):
    a=NW.setdefault(k,np.zeros(3+L_NW)); a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    for j in range(1,L_NW+1): a[2+j]+=float(u[:-j]@u[j:])
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

# signal groups (label -> builder takes the per-bar arrays dict, returns bool mask)
GROUPS=[
 ("ANCHORS (known +)",      ["rsi_oversold","below_cloud","below_not_os"]),
 ("OSCILLATORS oversold",   ["stoch_os","willr_os","cci_os","cci_deep","mfi_os","ultosc_os","rsi_deep"]),
 ("MA dislocation",         ["below_sma200","far_below_sma200","below_sma50","far_below_sma50"]),
 ("BANDS / CHANNEL",        ["bb_below","bb_far","donchian_low"]),
 ("GAP / VOL / VOLAT",      ["gap_down","gap_up","rvol_high","atr_rising"]),
 ("CANDLES",                ["hammer","engulf_bull"]),
 ("TREND controls (exp -)", ["rsi_strong","above_sma200","golden_cross","macd_bull","donchian_high","stoch_ob"]),
 ("RANDOM",                 ["RANDOM"]),
]
ALL_SIGS=[s for _,ss in GROUPS for s in ss]

for ii,sym in enumerate(syms):
    if ii%400==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    if n<300: continue
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan); dollar=c*vol20
    dmove=np.zeros(n); dmove[1:]=np.abs(c[1:]/np.where(c[:-1]>0,c[:-1],np.nan)-1.0); badday=dmove>GAP
    nonbull=~np.array([isbull(x) for x in dts])

    slowk,slowd=talib.STOCH(h,l,c)
    willr=talib.WILLR(h,l,c,14); cci=talib.CCI(h,l,c,14); mfi=talib.MFI(h,l,c,v,14); ult=talib.ULTOSC(h,l,c)
    bbu,bbm,bbl=talib.BBANDS(c,20,2,2)
    sma50=talib.SMA(c,50); sma200=talib.SMA(c,200)
    macd,macdsig,_=talib.MACD(c,12,26,9)
    ham=talib.CDLHAMMER(o,h,l,c); eng=talib.CDLENGULFING(o,h,l,c)
    donlo=rmn(l,20); donhi=rmx(h,20)
    prevc=shift(c,1)
    # Ichimoku cloud bottom
    sA=np.full(n,np.nan); sB=np.full(n,np.nan)
    tk=(rmx(h,9)+rmn(l,9))/2; kj=(rmx(h,26)+rmn(l,26))/2
    sA[DISP:]=((tk+kj)/2)[:n-DISP]; sB[DISP:]=((rmx(h,52)+rmn(l,52))/2)[:n-DISP]
    bot=np.fmin(sA,sB); below=c<bot; os=rsi<30

    SIG={
      "rsi_oversold":os, "below_cloud":below, "below_not_os":below&~os,
      "stoch_os":slowk<20, "willr_os":willr<-80, "cci_os":cci<-100, "cci_deep":cci<-200,
      "mfi_os":mfi<20, "ultosc_os":ult<30, "rsi_deep":rsi<20,
      "below_sma200":c<sma200, "far_below_sma200":(c<sma200)&((sma200-c)/np.where(sma200>0,sma200,np.nan)>0.10),
      "below_sma50":c<sma50, "far_below_sma50":(c<sma50)&((sma50-c)/np.where(atr>0,atr,np.nan)>2.0),
      "bb_below":c<bbl, "bb_far":(c<bbl)&((bbl-c)/np.where(atr>0,atr,np.nan)>0.5), "donchian_low":c<=donlo,
      "gap_down":o<prevc*0.97, "gap_up":o>prevc*1.03, "rvol_high":v>2*vol20, "atr_rising":atr>shift(atr,5),
      "hammer":ham!=0, "engulf_bull":eng>0,
      "rsi_strong":rsi>50, "above_sma200":c>sma200, "golden_cross":sma50>sma200,
      "macd_bull":macd>macdsig, "donchian_high":c>=donhi, "stoch_ob":slowk>80,
      "RANDOM":np.ones(n,bool),
    }

    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL); pos=(c>0)&(o>0)&(h>0)&(l>0)
    clean_elig=base_price&pos&(atr_pct>=VOL_FLOOR)&(dollar>=DOLLAR_VOL)
    badpathB=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
    for t in range(n-BR_N):
        if cs[t+BR_N+1]-cs[t+1]>0: badpathB[t]=True
    res,valid=bracket(h,l,c,atr,BR_N,TP_ATR,SL_ATR,badpathB)
    ok=clean_elig&valid&~np.isnan(res)

    for rk,rmask in (("nonbull",nonbull),("all",np.ones(n,bool))):
        base=ok&rmask
        if base.sum()<20: continue
        bmean=res[base].mean()
        for sname in ALL_SIGS:
            smask=np.asarray(SIG[sname],bool)&base
            ent=noov(smask,res,BR_N)
            if ent: bumpB((sname,rk), float(np.mean([res[i] for i in ent])-bmean), len(ent))
            fidx=np.where(smask)[0]
            if len(fidx)>=5:
                bumpF((sname,rk), float(res[fidx].mean()-bmean), len(fidx))
                u=np.zeros(n); u[fidx]=res[fidx]-bmean
                bumpNW((sname,rk), u, len(fidx))

def stC(store,k,minsym=30):
    a=store.get(k)
    if not a or a[2]<minsym: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt
def stNW(k,minfire=50):
    a=NW.get(k)
    if a is None or a[1]<minfire: return None
    S,M=a[0],a[1]; G=a[2:]; varS=G[0]+2.0*float(np.dot(NW_W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)

print("\n################ BROAD NW RE-SWEEP — DE-OVERLAP vs FULL-POP vs NEWEY-WEST ################")
print(f"  bracket TP{TP_ATR:.0f}:SL{SL_ATR:.0f} hold{BR_N}, vol_floor {VOL_FLOOR}, $vol>={DOLLAR_VOL:,}")
print("  FLAG ▲ = buried-edge signature (de-overlap<=0 AND NW>0 t>=3).  FLAG ! = trend control came POSITIVE.")
for rk in ("nonbull","all"):
    print(f"\n  ===================== regime={rk} =====================")
    print(f"    {'signal':17} {'DE-OVERLAP':>20} {'FULL-POP(clus)':>18} {'NEWEY-WEST':>22}  flag")
    for gname,sigs in GROUPS:
        print(f"   -- {gname} --")
        for sname in sigs:
            b=stC(B,(sname,rk)); ff=stC(BF,(sname,rk)); nw=stNW((sname,rk))
            c1=f"{b[0]:+.3f}R t{b[1]:+.1f}" if b else "(thin)"
            c2=f"{ff[0]:+.3f}R t{ff[1]:+.1f}" if ff else "(thin)"
            c3=f"{nw[0]:+.3f}R t{nw[1]:+.1f} n{nw[2]}" if nw else "(thin)"
            flag=""
            if nw and b and b[0]<=0.0 and nw[0]>0 and nw[1]>=3.0: flag="▲ buried?"
            if gname.startswith("TREND") and nw and nw[0]>0 and nw[1]>=3.0: flag="! trend+"
            print(f"    {sname:17} {c1:>20} {c2:>18} {c3:>22}  {flag}")
print("\ndone.")
