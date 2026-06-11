"""SuperTrend deep-dive under the blessed Newey-West harness.

SuperTrend = ATR-band trailing flip (period 10, mult 3.0, production calculate_supertrend).
Sibling of PSAR (ATR-trailing flip, CLOSED redundant) and the cloud (binary trend state).
Three questions, mapped to prior findings:
  1. CONTINUATION (st_bull state, fresh bull-flip) -> expect anti-predictive (trend family).
  2. CONTRARIAN STATE (st_bear, aged/deep) -> is "price persistently below the band" the
     slow-dislocation factor, and does it add anything ORTHOGONAL to rsi<30|below_cloud|below_sma200?
     (PSAR/ADX both proved purely redundant.)
  3. SALVAGE SHOT: fresh bull-flip WHILE dislocated = analog of ha_flip_up x dislocation, the only
     trend-family overlay that ever passed the gauntlet (+0.264R nonbull). Head-to-head vs the HA flip.

Machinery byte-identical to nw_broad_sweep.py: bracket TP2:SL1 holds {10,20}, vol+$vol floors,
gap-skip path, NW Bartlett L=hold-1, demean vs same-regime random, 2000 syms 2016+.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; DOLLAR_VOL=1_000_000; GAP=0.50; DISP=26
TP_ATR,SL_ATR=2.0,1.0; HOLDS=(10,20)
ST_P,ST_M=10,3.0
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
print(f"{len(syms)} symbols; SuperTrend({ST_P},{ST_M}) deep-dive",flush=True)

rmx=lambda x,w: pd.Series(x).rolling(w).max().to_numpy(); rmn=lambda x,w: pd.Series(x).rolling(w).min().to_numpy()
def shift(a,k):
    out=np.full(len(a),np.nan)
    if k<len(a): out[k:]=a[:-k]
    return out

def supertrend(h,l,c,P,M):
    """Production-faithful SuperTrend. Returns (trend[+1/-1], st_line, final_upper, final_lower)."""
    n=len(c); atr=talib.ATR(h,l,c,P); hl2=(h+l)*0.5
    bu=hl2+M*atr; bl=hl2-M*atr
    fu=np.zeros(n); fl=np.zeros(n); tr=np.zeros(n,np.int8)
    s=int(np.argmax(~np.isnan(atr)))           # first valid ATR
    fu[s]=bu[s]; fl[s]=bl[s]; tr[s]=1
    for i in range(s+1,n):
        fu[i]=bu[i] if (bu[i]<fu[i-1] or c[i-1]>fu[i-1]) else fu[i-1]
        fl[i]=bl[i] if (bl[i]>fl[i-1] or c[i-1]<fl[i-1]) else fl[i-1]
        t=tr[i-1] or 1
        if t==1 and c[i]<fl[i]: t=-1
        elif t==-1 and c[i]>fu[i]: t=1
        tr[i]=t
    st=np.where(tr==1,fl,fu).astype(float)
    return tr,st,fu,fl

# ---- accumulators (clustered de-overlap + full-pop, and NW) ----
B={};   bumpB=lambda k,lift,nt:(B.setdefault(k,[0.,0.,0,0]),)[0]
def bumpB(k,lift,nt):
    a=B.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
BF={}
def bumpF(k,lift,nt):
    a=BF.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
NW={}
def make_w(L): return np.array([1.0-j/(L+1) for j in range(L+1)])
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
    dts=d.date.astype(str).str[:10].to_numpy(); yr=d.date.astype(str).str[:4].to_numpy(); n=len(c)
    if n<300: continue
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan); dollar=c*vol20
    dmove=np.zeros(n); dmove[1:]=np.abs(c[1:]/np.where(c[:-1]>0,c[:-1],np.nan)-1.0); badday=dmove>GAP
    nonbull=~np.array([isbull(x) for x in dts])
    sma200=talib.SMA(c,200)
    sA=np.full(n,np.nan); sB=np.full(n,np.nan)
    tk=(rmx(h,9)+rmn(l,9))/2; kj=(rmx(h,26)+rmn(l,26))/2
    sA[DISP:]=((tk+kj)/2)[:n-DISP]; sB[DISP:]=((rmx(h,52)+rmn(l,52))/2)[:n-DISP]
    bot=np.fmin(sA,sB)
    disloc=(rsi<30)|(c<bot)|(c<sma200)

    tr,st,fu,fl=supertrend(h,l,c,ST_P,ST_M)
    up=(tr==1); bear=(tr==-1)
    prevup=shift(up.astype(float),1)==1
    flip_up=up&~prevup; flip_dn=bear& prevup
    distbelow=np.where(bear,(fu-c)/np.where(atr>0,atr,np.nan),np.nan)
    # bear-state age (consecutive bars in downtrend)
    bage=np.zeros(n,int)
    for i in range(1,n): bage[i]=bage[i-1]+1 if bear[i] else 0
    # true-recursive Heiken-Ashi green flip (validated comparator)
    hac=(o+h+l+c)/4.0; hao=np.empty(n); hao[0]=(o[0]+c[0])/2
    for i in range(1,n): hao[i]=(hao[i-1]+hac[i-1])/2
    hagreen=hac>hao; haprev=shift(hagreen.astype(float),1)==1; ha_flip=hagreen&~haprev

    SIG={
      "st_bull":up, "st_flip_up":flip_up, "st_flip_up_disl":flip_up&disloc,
      "st_bear":bear, "st_bear_deep":bear&(distbelow>2.0),
      "st_bear_age10":bear&(bage>=10), "st_bear_age26":bear&(bage>=26),
      "st_bear_age26_indisl":bear&(bage>=26)&disloc, "st_bear_age26_resid":bear&(bage>=26)&~disloc,
      "st_flip_down":flip_dn,
      "disloc(benchmark)":disloc, "ha_flip_up_disl":ha_flip&disloc, "RANDOM":np.ones(n,bool),
    }
    base_price=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(o>0)&(h>0)&(l>0)
    clean_elig=base_price&(atr_pct>=VOL_FLOOR)&(dollar>=DOLLAR_VOL)

    for BR_N in HOLDS:
        L=BR_N-1
        badpathB=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
        for t in range(n-BR_N):
            if cs[t+BR_N+1]-cs[t+1]>0: badpathB[t]=True
        res,valid=bracket(h,l,c,atr,BR_N,TP_ATR,SL_ATR,badpathB)
        ok=clean_elig&valid&~np.isnan(res)
        for rk,rmask in (("nonbull",nonbull),("all",np.ones(n,bool))):
            bse=ok&rmask
            if bse.sum()<20: continue
            bmean=res[bse].mean()
            for sname,sraw in SIG.items():
                smask=np.asarray(sraw,bool)&bse
                ent=noov(smask,res,BR_N)
                if ent: bumpB((sname,rk,BR_N), float(np.mean([res[i] for i in ent])-bmean), len(ent))
                fidx=np.where(smask)[0]
                if len(fidx)>=5:
                    bumpF((sname,rk,BR_N), float(res[fidx].mean()-bmean), len(fidx))
                    u=np.zeros(n); u[fidx]=res[fidx]-bmean
                    bumpNW((sname,rk,BR_N), u, len(fidx), L)
                    if BR_N==10 and sname in ("st_bear_age26","st_flip_up_disl","ha_flip_up_disl","disloc(benchmark)"):
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
    L=k[2]-1 if isinstance(k[2],int) else 9; W=make_w(L)
    S,M=a[0],a[1]; G=a[2:2+1+L]; varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def line(sname,rk,BR_N):
    b=stC(B,(sname,rk,BR_N)); ff=stC(BF,(sname,rk,BR_N)); nw=stNW((sname,rk,BR_N))
    c1=f"{b[0]:+.3f}R t{b[1]:+.1f}" if b else "(thin)"
    c2=f"{ff[0]:+.3f}R t{ff[1]:+.1f}" if ff else "(thin)"
    c3=f"{nw[0]:+.3f}R t{nw[1]:+.1f} n{nw[2]}" if nw else "(thin)"
    return f"    {sname:22} {c1:>20} {c2:>18} {c3:>22}"

ORDER=["st_bull","st_flip_up","st_flip_up_disl","st_bear","st_bear_deep","st_bear_age10",
       "st_bear_age26","st_bear_age26_indisl","st_bear_age26_resid","st_flip_down",
       "disloc(benchmark)","ha_flip_up_disl","RANDOM"]
print("\n################ SUPERTREND DEEP-DIVE — DE-OVERLAP | FULL-POP(clus) | NEWEY-WEST ################")
print(f"  ST({ST_P},{ST_M}); bracket TP{TP_ATR:.0f}:SL{SL_ATR:.0f}; vol_floor {VOL_FLOOR}; $vol>={DOLLAR_VOL:,}")
print("  Salvage = st_flip_up_disl beats disloc(benchmark) like ha_flip; orthogonality = st_bear_age26_resid NW>0 t>=3.")
for BR_N in HOLDS:
    for rk in ("nonbull","all"):
        print(f"\n  ===================== hold{BR_N}  regime={rk} =====================")
        print(f"    {'signal':22} {'DE-OVERLAP':>20} {'FULL-POP':>18} {'NEWEY-WEST':>22}")
        for s in ORDER: print(line(s,rk,BR_N))

print("\n############### PER-YEAR NW (hold10, lift vs same-regime random; 2020=COVID) ###############")
for rk in ("nonbull","all"):
    print(f"\n  regime={rk}")
    for tag in ("st_flip_up_disl","ha_flip_up_disl","disloc(benchmark)","st_bear_age26"):
        cells=[]
        for Y in [str(y) for y in range(2016,2027)]:
            nw=stNW((tag,rk,10,Y),minfire=20)
            cells.append(f"{Y[2:]}:{nw[0]:+.2f}(t{nw[1]:+.0f})" if nw else f"{Y[2:]}: .  ")
        print(f"    {tag:20} "+"  ".join(cells))
print("\ndone.")
