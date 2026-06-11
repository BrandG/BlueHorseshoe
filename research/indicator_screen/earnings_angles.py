"""ANGLES 1 & 2: condition the DeepOS sleeve on earnings (orthogonal, non-price axis).

ANGLE 2 (lead) — "why is it down?": within DeepOS (rsi<30 age>=3), split by the MOST RECENT earnings:
  post_missK = recent earnings <=K trading days ago & surprise<0  (PEAD-down knife candidate)
  post_beatK = recent earnings <=K days ago & surprise>0
  clean      = no earnings within +/-10d (pure technical dislocation)
ANGLE 1 — proximity filter: split by NEXT earnings:
  preK       = earnings within next K days (binary-event risk; deploy=defer)
  no_preK    = filtered book
Benchmark = bare deepos. Lift read as cell_NW - deepos_NW.

FAITHFUL execution (earnings reactions ARE gaps -> close-entry would charge them, see the killed gap filter):
enter next-day OPEN, stop fills at open on gap-through, tiered round-trip cost. Two scenarios reported:
  S2 = next-open + gap-stop (gross) ; S4 = + liquidity-tiered cost.
NW (Bartlett L=hold-1) demean vs same-regime/same-scenario random. Universe = earnings-COVERED subset of the
pinned-2000 (currently-listed = live-tradeable). reaction-day map validated in earnings_proto.py. hold10.
"""
import numpy as np, pandas as pd, talib, duckdb
from collections import defaultdict

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; AGE=3; N=10; TP_ATR,SL_ATR=2.0,1.0
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

# earnings -> dict[symbol] = list[(reportedDate, reportTime, surprise_float)]
edf=duckdb.connect().execute(
    "SELECT symbol,reportedDate,reportTime,surprise FROM read_parquet('data/earnings.parquet') WHERE reportedDate>='2015-06-01'").df()
ED=defaultdict(list)
for r in edf.itertuples(index=False):
    try: sp=float(r.surprise)
    except: sp=np.nan
    ED[r.symbol].append((r.reportedDate, r.reportTime, sp))
covered=[s for s in syms if s in ED]
print(f"universe pinned {len(syms)}; earnings-covered {len(covered)}",flush=True)

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
def dv_cost_bp(dv):
    if dv<1e6: return 50.0
    if dv<5e6: return 25.0
    if dv<25e6: return 12.0
    return 6.0
NWd={}
def make_w(L): return np.array([1.0-j/(L+1) for j in range(L+1)])
def bumpNW(k,u,m):
    a=NWd.setdefault(k,np.zeros(3+N)); a[0]+=u.sum(); a[1]+=m; a[2]+=float(u@u)
    for j in range(1,N): a[2+j]+=float(u[:-j]@u[j:])

SCN=["S2","S4"]
for ii,sym in enumerate(covered):
    if ii%200==0: print(f"  {ii}/{len(covered)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    dv20=pd.Series(c*v).rolling(20).mean().to_numpy(); atr_pct=atr/np.where(c>0,c,np.nan)
    elig=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(atr_pct>=VOL_FLOOR)
    nonbull=~np.array([isbull(x) for x in dts])
    osr=rsi<OS; age=np.zeros(n,int)
    for i in range(1,n): age[i]=age[i-1]+1 if osr[i] else 0
    deepos=osr&(age>=AGE)
    nxo=np.full(n,np.nan); nxo[:n-1]=o[1:]
    # reaction-day map (validated): pre-market react day>=D ; post/unknown react day>D
    react={}
    for (D,rt,sp) in ED[sym]:
        if D<dts[0] or D>dts[-1]: continue
        idx=int(np.searchsorted(dts,D,side=("left" if rt=="pre-market" else "right")))
        if 0<=idx<n: react[idx]=np.sign(sp) if not np.isnan(sp) else np.nan
    rset=set(react)
    since=np.full(n,10**9); lastsign=np.full(n,np.nan); last=-10**9; ls=np.nan
    for i in range(n):
        if i in rset: last=i; ls=react[i]
        since[i]=i-last; lastsign[i]=ls
    nxt=np.full(n,10**9); cur=10**9
    for i in range(n-1,-1,-1):
        cur=0 if i in rset else (cur+1 if cur<10**9 else 10**9)
        nxt[i]=cur
    CELLS={
      "deepos(base)":deepos,
      "post_miss5":deepos&(since<=5)&(lastsign<0), "post_beat5":deepos&(since<=5)&(lastsign>0),
      "post_miss10":deepos&(since<=10)&(lastsign<0),"post_beat10":deepos&(since<=10)&(lastsign>0),
      "post_miss20":deepos&(since<=20)&(lastsign<0),"post_beat20":deepos&(since<=20)&(lastsign>0),
      "clean_pm10":deepos&(since>10)&(nxt>10),
      "pre5":deepos&(nxt<=5), "no_pre5":deepos&(nxt>5),
      "pre10":deepos&(nxt<=10),"no_pre10":deepos&(nxt>10),
      "RANDOM":np.ones(n,bool),
    }
    rg,_=run(nxo,atr,o,h,l,c,True)
    ctier=np.array([dv_cost_bp(x) for x in np.nan_to_num(dv20)])/1e4/(SL_ATR*atr_pct)
    RES={"S2":rg,"S4":rg-ctier}
    for reg in ("nonbull","all"):
        rmask=nonbull if reg=="nonbull" else np.ones(n,bool)
        for scn in SCN:
            res=RES[scn]; ok=elig&~np.isnan(res)&rmask
            if ok.sum()<20: continue
            bmean=res[ok].mean()
            for cn,cm in CELLS.items():
                fidx=np.where(cm&ok)[0]
                if len(fidx)>=5:
                    u=np.zeros(n); u[fidx]=res[fidx]-bmean; bumpNW((cn,reg,scn),u,len(fidx))
                    if scn=="S4" and reg=="nonbull" and cn in ("deepos(base)","post_miss10","post_beat10","clean_pm10","pre5","no_pre5"):
                        for Y in np.unique(np.array([x[:4] for x in dts[fidx]])):
                            yi=fidx[np.array([dts[j][:4]==Y for j in fidx])]
                            if len(yi)>=8:
                                uy=np.zeros(n); uy[yi]=res[yi]-bmean; bumpNW((cn,reg,scn,Y),uy,len(yi))

def stNW(k,minf=30):
    a=NWd.get(k)
    if a is None or a[1]<minf: return None
    L=N-1; W=make_w(L); S,M=a[0],a[1]; G=a[2:2+1+L]; varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def line(cn,reg,base):
    s2=stNW((cn,reg,"S2")); s4=stNW((cn,reg,"S4"))
    f=lambda x:(f"{x[0]:+.3f}R t{x[1]:+.1f} n{x[2]}" if x else "(thin)")
    lift=f"{s4[0]-base:+.3f}" if (s4 and base is not None and cn!='deepos(base)') else ("base" if cn=='deepos(base)' else "--")
    return f"    {cn:16} S2 {f(s2):>22}   S4 {f(s4):>22}   liftS4 {lift}"

for reg in ("nonbull","all"):
    b=stNW(("deepos(base)",reg,"S4")); base=b[0] if b else None
    print(f"\n################ regime={reg}  (faithful next-open+gapstop; S4=+cost; lift vs deepos S4) ################")
    print("  ===== ANGLE 2 — why is it down? (most-recent earnings) =====")
    for cn in ["deepos(base)","post_miss5","post_beat5","post_miss10","post_beat10","post_miss20","post_beat20","clean_pm10"]:
        print(line(cn,reg,base))
    print("  ===== ANGLE 1 — proximity filter (next earnings) =====")
    for cn in ["pre5","no_pre5","pre10","no_pre10"]:
        print(line(cn,reg,base))
    print("  ===== control =====")
    print(line("RANDOM",reg,base))

print("\n################ PER-YEAR NW (nonbull S4; 2020=COVID) ################")
for cn in ["deepos(base)","post_miss10","post_beat10","clean_pm10","pre5","no_pre5"]:
    cells=[]
    for Y in [str(y) for y in range(2016,2027)]:
        s=stNW((cn,"nonbull","S4",Y),minf=8)
        cells.append(f"{Y[2:]}:{s[0]:+.2f}(n{s[2]})" if s else f"{Y[2:]}: .")
    print(f"  {cn:14} "+"  ".join(cells))
print("\ndone.")
