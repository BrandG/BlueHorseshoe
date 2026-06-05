"""RSI-oversold(<30) clean gauntlet — re-validate the one entry edge that "beat" baseline.

Background: dislocation_bracket_test.py reported rsi_oversold(<30) nonbull / 2:1 / 10-15d at
+0.077-0.079R, t~9, n=27k. But that test counted EVERY oversold bar as an independent trade,
used NO vol-floor, and computed t per-observation. psar_incremental.py's D_oversold side-arm,
under the clean method (episode-start de-overlap), came out -0.029R t-1.3. Three knobs differ at
once. This script isolates each.

SECTION 0 - Reconciliation (nonbull, N=10, 2:1 runner). Add one clean knob at a time:
  (1) raw bars, no vol-floor, per-obs t      <- should reproduce ~+0.08R t~9
  (2) + episode-start de-overlap
  (3) + vol-floor 0.5%
  (4) + symbol-clustered t                   <- should reproduce ~-0.03R
  Pinpoints WHICH knob turns the winner negative.

SECTION A - Clean headline grid. Full clean (estart + vol-floor + symbol-clustered).
  all/bull/nonbull x N{10,15} x {1:1, 2:1}. Honest lift vs random-date baseline.

SECTION B - Time-split sign-stability gate (the PSAR lesson: nonzero weight only if same sign
  AND significant in BOTH halves). H1 2016-20 / H2 2021-26 x cost{0,5,10,20bp}, nonbull & all,
  N{10,15}, 2:1 runner.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"; SPLIT="2021-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000; VOL_FLOOR=0.005
OS=30.0; MIN_BASE=15; COSTS=[0,5,10,20]
GRID_N=[10,15]; VARIANTS={"A_1:1":(1.0,1.0),"B_2:1run":(2.0,1.0)}

con=duckdb.connect("data/ohlcv.duckdb",read_only=True)
syms=con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",[START]).df().symbol.tolist()
rng=np.random.default_rng(SEED)
if len(syms)>N_SYMBOLS: syms=list(rng.choice(syms,N_SYMBOLS,replace=False))
spy=con.execute("SELECT date,close FROM ohlcv WHERE symbol='SPY' AND date>=? ORDER BY date",[START]).df()
spy["e50"]=talib.EMA(spy.close,50); spy["e200"]=talib.EMA(spy.close,200)
spy["bull"]=(spy.close>spy.e200)&(spy.e50>spy.e200)
reg=dict(zip(spy.date.astype(str).str[:10],spy.bull))
def isbull(d): return reg.get(str(d)[:10],False)
print(f"{len(syms)} symbols, oversold=rsi<{OS:.0f}",flush=True)

def estart(m): return m&~np.concatenate([[False],m[:-1]])
def bracket(h,l,c,atr,N,tp_atr,sl_atr):
    n=len(c); tp=c+tp_atr*atr; sl=c-sl_atr*atr; Rp=sl_atr*atr
    resolved=np.zeros(n,bool); win=np.zeros(n,bool); res=np.full(n,np.nan)
    valid=(np.arange(n)<(n-N))&(atr>0)&~np.isnan(atr)
    for k in range(1,N+1):
        tph=np.zeros(n,bool); slh=np.zeros(n,bool)
        tph[:n-k]=h[k:]>=tp[:n-k]; slh[:n-k]=l[k:]<=sl[:n-k]
        live=valid&~resolved&(tph|slh); loss=live&slh; wn=live&tph&~slh
        res[loss]=-1.0; res[wn]=tp_atr/sl_atr; win[wn]=True; resolved|=(loss|wn)
    ex=np.full(n,np.nan); ex[:n-N]=c[N:][:n-N] if n-N>0 else ex[:n-N]
    to=valid&~resolved; res[to]=(ex[to]-c[to])/Rp[to]
    return res,win,valid

# --- accumulators ---
# Section 0: pooled (per-obs) need sumR,sumR2,n for signal & baseline separately per config.
pool={}  # cfg -> {"sig":[s,ss,n], "base":[s,ss,n]}
def bumpPool(cfg,which,r):
    a=pool.setdefault(cfg,{"sig":[0.,0.,0],"base":[0.,0.,0]})[which]
    a[0]+=r.sum(); a[1]+=(r*r).sum(); a[2]+=len(r)
# Section 0 cluster + Section A + Section B: per-symbol lift accumulators.
clust={}  # key -> [sumLift,sumsqLift,nsym,nep]
def bumpClust(key,lift,ne):
    a=clust.setdefault(key,[0.,0.,0,0]); a[0]+=lift; a[1]+=lift*lift; a[2]+=1; a[3]+=ne

for i,sym in enumerate(syms):
    if i%300==0: print(f"  {i}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    atr=talib.ATR(h,l,c,14); rsi=talib.RSI(c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan)
    elig_px=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)
    elig_vf=elig_px&(atr_pct>=VOL_FLOOR)
    bull=np.array([isbull(x) for x in dts]); h1=dts<SPLIT
    sig_raw=rsi<OS; sig_es=estart(rsi<OS)

    # ===== SECTION 0 (nonbull, N=10, 2:1) =====
    res,win,valid=bracket(h,l,c,atr,10,2.0,1.0); ok=valid&~np.isnan(res); nb=~bull
    # (1) raw, no vol-floor, pooled
    b1=elig_px&ok&nb;  s1=sig_raw&b1
    if b1.any(): bumpPool("1_raw_novf","base",res[b1])
    if s1.any(): bumpPool("1_raw_novf","sig", res[s1])
    # (2) episode-start, no vol-floor, pooled
    s2=sig_es&b1
    if b1.any(): bumpPool("2_es_novf","base",res[b1])
    if s2.any(): bumpPool("2_es_novf","sig", res[s2])
    # (3) episode-start, vol-floor, pooled
    b3=elig_vf&ok&nb;  s3=sig_es&b3
    if b3.any(): bumpPool("3_es_vf","base",res[b3])
    if s3.any(): bumpPool("3_es_vf","sig", res[s3])
    # (4) episode-start, vol-floor, symbol-clustered
    if b3.sum()>=MIN_BASE and s3.any():
        bumpClust(("S0","4_es_vf_clust"), res[s3].mean()-res[b3].mean(), int(s3.sum()))

    # ===== SECTION A (clean grid) + SECTION B (time-split) =====
    for N in GRID_N:
        for vname,(tpa,sla) in VARIANTS.items():
            res,win,valid=bracket(h,l,c,atr,N,tpa,sla); ok=valid&~np.isnan(res)
            base=elig_vf&ok; sig=sig_es&base
            for rk,rmask in (("all",np.ones(n,bool)),("bull",bull),("nonbull",~bull)):
                b=base&rmask; s=sig&rmask
                if b.sum()>=MIN_BASE and s.any():
                    bumpClust(("A",vname,N,rk),
                              res[s].mean()-res[b].mean(), int(s.sum()))
                    # win-rate carried alongside (reuse nep slot is taken; store separately)
            # Section B: only 2:1 runner, nonbull & all, time-split x cost
            if vname!="B_2:1run": continue
            for rk,rmask in (("all",np.ones(n,bool)),("nonbull",~bull)):
                for half,hm in (("H1",h1),("H2",~h1)):
                    b=elig_vf&ok&rmask&hm; s=sig_es&b
                    if b.sum()<MIN_BASE or not s.any(): continue
                    for cb in COSTS:
                        cR=(cb/10000.0)/atr_pct
                        bumpClust(("B",N,rk,half,cb),
                                  (res[s]-cR[s]).mean()-(res[b]-cR[b]).mean(), int(s.sum()))

# ---- stats ----
def pooled_lift(cfg):
    p=pool[cfg]; (ss,sss,ns)=p["sig"]; (bs,bss,nb)=p["base"]
    ms=ss/ns; vs=max(sss/ns-ms*ms,0); mb=bs/nb; vb=max(bss/nb-mb*mb,0)
    lift=ms-mb; se=(vs/ns+vb/nb)**0.5; t=lift/se if se>0 else 0
    return ms,mb,lift,t,ns
def clust_stat(key):
    a=clust.get(key)
    if not a or a[2]<30: return None
    s,ss,ns,ne=a; m=s/ns; var=max(ss/ns-m*m,0); se=(var/ns)**0.5
    return m,(m/se if se>0 else 0),ns,ne

print("\n################ SECTION 0: reconciliation (nonbull, N=10, 2:1) ################")
print(f"  {'config':>22} | {'sig exp':>9} {'base exp':>9} {'lift':>9} {'t':>7}  n")
for cfg in ("1_raw_novf","2_es_novf","3_es_vf"):
    ms,mb,lift,t,ns=pooled_lift(cfg)
    print(f"  {cfg:>22} | {ms:+.4f}R {mb:+.4f}R {lift:+.4f}R t={t:+.1f}  n_obs={ns:,}")
r4=clust_stat(("S0","4_es_vf_clust"))
if r4: print(f"  {'4_es_vf_clust':>22} | {'(symbol-clustered)':>29} {r4[0]:+.4f}R t={r4[1]:+.1f}  n_sym={r4[2]} n_ep={r4[3]}")
print("  [1->2 = de-overlap effect; 2->3 = vol-floor; 3->4 = clustered t (point est unchanged, honest SE)]")

print("\n################ SECTION A: clean headline grid (estart+vol-floor+clustered) ################")
for vname in VARIANTS:
    print(f"\n  === {vname} ===")
    print(f"      {'N':>3} {'regime':>8} | {'lift vs random':>16}  n_sym n_ep")
    for N in GRID_N:
        for rk in ("all","bull","nonbull"):
            r=clust_stat(("A",vname,N,rk))
            if not r: print(f"      {N:>3} {rk:>8} | (n<30)"); continue
            flag=" <==" if r[0]>0 and r[1]>2 else ("  xx" if r[0]<0 and r[1]<-2 else "")
            print(f"      {N:>3} {rk:>8} | {r[0]:+.4f}R(t={r[1]:+.1f})  {r[2]:<5} {r[3]}{flag}")

print("\n################ SECTION B: time-split sign-stability + cost (2:1 runner) ################")
print("  GATE: deployable only if lift same-sign AND |t|>2 in BOTH halves after realistic cost.")
for rk in ("nonbull","all"):
    for N in GRID_N:
        print(f"\n  === regime={rk}  N={N} ===")
        print(f"      {'cost':>5} | {'H1 (2016-20)':>20} | {'H2 (2021-26)':>20}  verdict")
        for cb in COSTS:
            h1r=clust_stat(("B",N,rk,"H1",cb)); h2r=clust_stat(("B",N,rk,"H2",cb))
            def fmt(r): return f"{r[0]:+.4f}R t={r[1]:+.1f}" if r else "(n<30)"
            ok = h1r and h2r and (np.sign(h1r[0])==np.sign(h2r[0])) and abs(h1r[1])>2 and abs(h2r[1])>2 and h1r[0]>0
            vd = "PASS" if ok else "fail"
            print(f"      {cb:>3}bp | {fmt(h1r):>20} | {fmt(h2r):>20}  {vd}")
