"""Does the VOLUME SIGNATURE at entry separate bounces from knives WITHIN the deep-oversold sleeve?

Base = the validated rule: RSI(14)<30 for >=3 consecutive closes (DeepOS). Orthogonal axis = volume,
which is NOT in the RSI/MA-distance price signal. Two competing textbook theses, let the data pick:
  CLIMAX  : oversold low on a volume SPIKE (forced selling exhausting itself) -> bounces harder.
  DRY-UP  : oversold low on CONTRACTING volume (sellers gone, quiet base)     -> bounces harder.
  (null)  : volume carries nothing -> all buckets ~= bare DeepOS.

Cells (all = DeepOS & condition), demeaned vs same-regime random (so lift over DeepOS is readable as
cell_NW - deepos_NW). RVOL = vol / SMA(vol,50) (self-normalized -> liquidity-neutral). Run at $1M and the
deployable >$25M tiers. Machinery byte-identical to nw_broad_sweep.py: bracket TP2:SL1 holds{10,20},
vol+$vol floors, gap-skip, NW Bartlett L=hold-1, 2000 syms 2016+. RANDOM must read ~0.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; GAP=0.50; TP_ATR,SL_ATR=2.0,1.0; HOLDS=(10,20)
TIERS={"$1M":1_000_000,"$25M":25_000_000}
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
print(f"{len(syms)} symbols; DeepOS x volume-signature",flush=True)

def shift(a,k):
    out=np.full(len(a),np.nan)
    if k<len(a): out[k:]=a[:-k]
    return out
BF={}
def bumpF(k,lift,nt):
    a=BF.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
B={}
def bumpB(k,lift,nt):
    a=B.setdefault(k,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=nt
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
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14)
    vol20=pd.Series(v).rolling(20).mean().to_numpy(); vol50=pd.Series(v).rolling(50).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan); dollar=c*vol20
    dmove=np.zeros(n); dmove[1:]=np.abs(c[1:]/np.where(c[:-1]>0,c[:-1],np.nan)-1.0); badday=dmove>GAP
    nonbull=~np.array([isbull(x) for x in dts])
    # DeepOS base: rsi<30 for >=3 consecutive closes
    os=rsi<30; age=np.zeros(n,int)
    for i in range(1,n): age[i]=age[i-1]+1 if os[i] else 0
    deepos=os&(age>=3)
    # volume signature
    rvol=v/np.where(vol50>0,vol50,np.nan)
    m5prior=shift(pd.Series(v).rolling(5).mean().to_numpy(),1)
    vexp=v>1.3*m5prior; vcon=v<0.7*m5prior
    rng_=h-l; closepos=np.where(rng_>1e-9,(c-l)/rng_,0.5)
    climax_bar=(rvol>2.0)&(c<shift(c,1))&(closepos>0.5)   # spike + down + closed upper half (washout snapback)

    COND={
      "deepos(base)":np.ones(n,bool),
      "rvol<0.7":rvol<0.7, "rvol0.7-1":(rvol>=0.7)&(rvol<1.0), "rvol1-1.5":(rvol>=1.0)&(rvol<1.5),
      "rvol1.5-2":(rvol>=1.5)&(rvol<2.0), "rvol2-3":(rvol>=2.0)&(rvol<3.0), "rvol>3":rvol>=3.0,
      "vol_expanding":vexp, "vol_contracting":vcon, "climax_bar":climax_bar,
    }
    base_ok=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(o>0)&(h>0)&(l>0)&(atr_pct>=VOL_FLOOR)
    for tname,tfloor in TIERS.items():
        elig=base_ok&(dollar>=tfloor)
        for BR_N in HOLDS:
            L=BR_N-1
            badpathB=np.zeros(n,bool); bd=badday.astype(int); cs=np.concatenate([[0],np.cumsum(bd)])
            for t in range(n-BR_N):
                if cs[t+BR_N+1]-cs[t+1]>0: badpathB[t]=True
            res,valid=bracket(h,l,c,atr,BR_N,TP_ATR,SL_ATR,badpathB)
            ok=elig&valid&~np.isnan(res)
            for rk,rmask in (("nonbull",nonbull),("all",np.ones(n,bool))):
                bse=ok&rmask
                if bse.sum()<20: continue
                bmean=res[bse].mean()
                # RANDOM control on this base
                rfi=np.where(bse)[0]
                if len(rfi)>=50:
                    u=np.zeros(n); u[rfi]=res[rfi]-bmean; bumpNW(("RANDOM",tname,rk,BR_N),u,len(rfi),L)
                dp=deepos&bse
                for cname,craw in COND.items():
                    smask=dp&np.asarray(craw,bool)
                    ent=noov(smask,res,BR_N)
                    if ent: bumpB((cname,tname,rk,BR_N),float(np.mean([res[i] for i in ent])-bmean),len(ent))
                    fidx=np.where(smask)[0]
                    if len(fidx)>=5:
                        bumpF((cname,tname,rk,BR_N),float(res[fidx].mean()-bmean),len(fidx))
                        u=np.zeros(n); u[fidx]=res[fidx]-bmean; bumpNW((cname,tname,rk,BR_N),u,len(fidx),L)
                        if BR_N==10 and tname=="$25M" and cname in ("deepos(base)","rvol>3","rvol<0.7","climax_bar","vol_expanding"):
                            for Y in np.unique(yr[fidx]):
                                ym=smask&(yr==Y); yi=np.where(ym)[0]
                                if len(yi)>=5:
                                    uy=np.zeros(n); uy[yi]=res[yi]-bmean; bumpNW((cname,tname,rk,BR_N,Y),uy,len(yi),L)

def stC(store,k,minsym=30):
    a=store.get(k)
    if not a or a[2]<minsym: return None
    s,ss,ns,nt=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,nt
def stNW(k,minfire=40):
    a=NW.get(k)
    if a is None or a[1]<minfire: return None
    L=k[3]-1 if isinstance(k[3],int) else 9; W=make_w(L)
    S,M=a[0],a[1]; G=a[2:2+1+L]; varS=G[0]+2.0*float(np.dot(W[1:],G[1:]))
    if varS<=0: return None
    return S/M,((S/M)/((varS**0.5)/M)),int(M)
def line(cname,tn,rk,BR_N,base_nw):
    b=stC(B,(cname,tn,rk,BR_N)); ff=stC(BF,(cname,tn,rk,BR_N)); nw=stNW((cname,tn,rk,BR_N))
    c1=f"{b[0]:+.3f} t{b[1]:+.1f}" if b else "(thin)"
    c2=f"{ff[0]:+.3f} t{ff[1]:+.1f}" if ff else "(thin)"
    c3=f"{nw[0]:+.3f}R t{nw[1]:+.1f} n{nw[2]}" if nw else "(thin)"
    lift=f"{nw[0]-base_nw:+.3f}" if (nw and base_nw is not None and cname!='deepos(base)') else ("base" if cname=='deepos(base)' else "—")
    return f"    {cname:16} {c1:>16} {c2:>16} {c3:>22}  lift {lift}"
ORDER=list(["deepos(base)","rvol<0.7","rvol0.7-1","rvol1-1.5","rvol1.5-2","rvol2-3","rvol>3",
            "vol_expanding","vol_contracting","climax_bar","RANDOM"])

print("\n################ DEEPOS x VOLUME-SIGNATURE — DE-OVERLAP | FULL-POP | NEWEY-WEST ################")
print("  lift = NW(cell) - NW(deepos base). CLIMAX thesis: rvol>3/climax_bar lift>0. DRY-UP thesis: rvol<0.7 lift>0.")
for tn in TIERS:
    for BR_N in HOLDS:
        for rk in ("nonbull","all"):
            bnw=stNW(("deepos(base)",tn,rk,BR_N)); base_nw=bnw[0] if bnw else None
            print(f"\n  ===== tier={tn}  hold{BR_N}  regime={rk}   [deepos base NW={base_nw:+.3f}R]"
                  if base_nw is not None else f"\n  ===== tier={tn} hold{BR_N} {rk} (base thin) =====")
            print(f"    {'cell':16} {'DE-OVERLAP':>16} {'FULL-POP':>16} {'NEWEY-WEST':>22}")
            for cn in ORDER: print(line(cn,tn,rk,BR_N,base_nw))

print("\n############### PER-YEAR NW ($25M, hold10, nonbull, demean vs random; 2020=COVID) ###############")
for tag in ("deepos(base)","rvol>3","climax_bar","rvol<0.7","vol_expanding"):
    cells=[]
    for Y in [str(y) for y in range(2016,2027)]:
        nw=stNW(("$25M",) and (tag,"$25M","nonbull",10,Y),minfire=15)
        cells.append(f"{Y[2:]}:{nw[0]:+.2f}(t{nw[1]:+.0f})" if nw else f"{Y[2:]}: .  ")
    print(f"    {tag:16} "+"  ".join(cells))
print("\ndone.")
