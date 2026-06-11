"""Donchian breakout under a LET-IT-RUN exit — does the breakout carry positive skew /
a fat right tail that our 2:1/hold-10 bracket amputates?

Answers Brand's "what do the millions see that we don't": trend-followers don't cap at +2R
and leave in 10 days — they trail a stop and let winners run for months (low win-rate, fat
right tail). Our fixed bracket is a mean-reversion-shaped instrument; it clips exactly that tail.

Two exit models, contrasted vs a mean-reversion entry (don_low_20) and RANDOM:
  MODEL A  uncapped fixed-horizon forward return in ATR units: R_H=(c[t+H]-c[t])/atr[t].
           No TP/SL. Pure shape of the move. Sweep H -> where does mean R peak = "optimal hold".
  MODEL B  Chandelier trailing stop, non-overlapping trades, let-it-run with downside cut.
           initial stop = entry - M*atr; trail = max(stop, runmax_high - M*atr); risk unit = M*atr.
           Sweep trail multiple M and max-hold cap. Reports realized R + trade duration.

Distribution metrics per cell: n, win%, mean, median, std, SKEW, P90/95/99, max, %>3R/5R/10R,
mean_win, mean_loss. Universe/floors/gap-skip identical to donchian_deepdive.py. Regimes by ENTRY bar.
Gross (close-based); cost would shave a few bps/trade — first-pass shape test.
"""
import numpy as np, pandas as pd, talib, duckdb

SEED=7; N_SYMBOLS=2000; START="2016-01-01"
PRICE_MIN,PRICE_MAX,MIN_VOL=5.0,500.0,100_000
VOL_FLOOR=0.005; DOLLAR_VOL=1_000_000; GAP=0.50
HORIZONS=(5,10,20,40,60,120,250)
TRAIL_MS=(2.0,3.0,4.0); MAXHOLD=250; MAXHOLD_SWEEP=(20,60,120,250)
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
print(f"{len(syms)} symbols; trailing/let-it-run exit study",flush=True)

rmx=lambda x,w: pd.Series(x).rolling(w).max().to_numpy(); rmn=lambda x,w: pd.Series(x).rolling(w).min().to_numpy()
def shift(a,k):
    out=np.full(len(a),np.nan)
    if k<len(a): out[k:]=a[:-k]
    return out

# collectors: key -> list of R  (Model A keyed by (sig,reg,H); Model B by (sig,reg,'Mx'/'capN'))
A={}; Adur={}
def addA(k,r): A.setdefault(k,[]).append(r)
Bn={}; Bdur={}
def addB(k,r,dur): Bn.setdefault(k,[]).append(r); Bdur.setdefault(k,[]).append(dur)

def trail_trade(t,o,h,l,c,atr,badday,n,M,maxhold):
    """simulate one chandelier trade entered at close[t]; return (R,dur) or None if contaminated/invalid."""
    entry=c[t]; risk=M*atr[t]
    if risk<=0 or not np.isfinite(risk): return None
    stop=entry-risk; runmax=h[t]
    end=min(t+maxhold,n-1)
    for k in range(1,end-t+1):
        day=t+k
        if badday[day]: return None         # split/contamination in the path -> drop
        # gap-through or intrabar hit of trailing stop
        if o[day]<=stop:  exit_p=o[day];  return (exit_p-entry)/risk, k
        if l[day]<=stop:  return (stop-entry)/risk, k
        if h[day]>runmax: runmax=h[day]
        stop=max(stop, runmax-risk)
    return (c[end]-entry)/risk, end-t                  # hit max-hold cap

for ii,sym in enumerate(syms):
    if ii%400==0: print(f"  {ii}/{len(syms)}",flush=True)
    d=con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",[sym,START]).df()
    if len(d)<300: continue
    o,h,l,c,v=(d[x].to_numpy(float) for x in ("open","high","low","close","volume"))
    dts=d.date.astype(str).str[:10].to_numpy(); n=len(c)
    if n<300: continue
    atr=talib.ATR(h,l,c,14); vol20=pd.Series(v).rolling(20).mean().to_numpy()
    atr_pct=atr/np.where(c>0,c,np.nan); dollar=c*vol20
    dmove=np.zeros(n); dmove[1:]=np.abs(c[1:]/np.where(c[:-1]>0,c[:-1],np.nan)-1.0); badday=dmove>GAP
    bull=np.array([isbull(x) for x in dts]); nonbull=~bull
    hi20=shift(rmx(h,20),1); hi55=shift(rmx(h,55),1); lo20=shift(rmn(l,20),1)
    base=(c>=PRICE_MIN)&(c<=PRICE_MAX)&(vol20>MIN_VOL)&(o>0)&(h>0)&(l>0)&(atr_pct>=VOL_FLOOR)&(dollar>=DOLLAR_VOL)&(atr>0)
    SIG={"don_high_20":(c>hi20),"don_high_55":(c>hi55),"don_low_20":(c<lo20),"RANDOM":np.ones(n,bool)}

    def regmask(rk): return {"all":np.ones(n,bool),"nonbull":nonbull,"bull":bull}[rk]

    # ---- MODEL A: uncapped fixed-horizon R, de-overlapped by H ----
    for sname,sraw in SIG.items():
        sig=np.asarray(sraw,bool)&base
        for H in HORIZONS:
            # gap-skip forward window via cumulative badday
            fires=np.where(sig)[0]; nxt=-1
            for t in fires:
                if t<=nxt or t+H>=n: continue
                if badday[t+1:t+H+1].any(): continue
                r=(c[t+H]-c[t])/atr[t]
                for rk in ("all","nonbull","bull"):
                    if regmask(rk)[t]: addA((sname,rk,H), r)
                nxt=t+H

    # ---- MODEL B: chandelier trailing, non-overlapping ----
    for sname,sraw in SIG.items():
        sig=np.asarray(sraw,bool)&base
        # (i) sweep trail multiple at MAXHOLD
        for M in TRAIL_MS:
            nxt=-1
            for t in np.where(sig)[0]:
                if t<=nxt: continue
                out=trail_trade(t,o,h,l,c,atr,badday,n,M,MAXHOLD)
                if out is None: continue
                r,dur=out
                for rk in ("all","nonbull","bull"):
                    if regmask(rk)[t]: addB((sname,rk,f"M{M:.0f}"), r, dur)
                nxt=t+dur
        # (ii) sweep max-hold cap at M=3 (only the two breakouts + random, to bound output)
        if sname in ("don_high_20","don_high_55","RANDOM"):
            for cap in MAXHOLD_SWEEP:
                nxt=-1
                for t in np.where(sig)[0]:
                    if t<=nxt: continue
                    out=trail_trade(t,o,h,l,c,atr,badday,n,3.0,cap)
                    if out is None: continue
                    r,dur=out
                    for rk in ("all","nonbull"):
                        if regmask(rk)[t]: addB((sname,rk,f"cap{cap}"), r, dur)
                    nxt=t+dur

def skew(x):
    x=np.asarray(x); m=x.mean(); s=x.std()
    return float(((x-m)**3).mean()/s**3) if s>0 else 0.0
def stats(vals,dur=None):
    x=np.asarray(vals,float)
    if len(x)<50: return None
    w=x>0
    s=dict(n=len(x),win=w.mean(),mean=x.mean(),med=np.median(x),std=x.std(),skew=skew(x),
            p90=np.percentile(x,90),p95=np.percentile(x,95),p99=np.percentile(x,99),mx=x.max(),
            g3=(x>3).mean(),g5=(x>5).mean(),g10=(x>10).mean(),
            mw=x[w].mean() if w.any() else 0.0, ml=x[~w].mean() if (~w).any() else 0.0)
    if dur is not None:
        dd=np.asarray(dur,float); s["dur"]=dd.mean(); s["durw"]=dd[w].mean() if w.any() else 0.0
    return s
def fmtA(s):
    if not s: return "(thin)"
    return (f"mean{s['mean']:+.2f}R med{s['med']:+.2f} skew{s['skew']:+.1f} win{s['win']*100:.0f}% "
            f"p95{s['p95']:+.1f} max{s['mx']:+.0f} >5R{s['g5']*100:.1f}% n{s['n']}")

print("\n################ MODEL A — uncapped fixed-horizon R (ATR units); OPTIMAL-HOLD sweep ################")
print("  Trend thesis: breakout mean R RISES with H (tail compounds). MR thesis: don_low peaks early then fades.")
for rk in ("all","nonbull","bull"):
    print(f"\n  ===== regime={rk} =====")
    for sname in ("don_high_20","don_high_55","don_low_20","RANDOM"):
        print(f"   -- {sname} --")
        best=None
        for H in HORIZONS:
            s=stats(A.get((sname,rk,H)))
            if s and (best is None or s['mean']>best[1]): best=(H,s['mean'])
            print(f"     H{H:<4} {fmtA(s)}")
        if best: print(f"     -> optimal fixed hold = H{best[0]} (mean {best[1]:+.2f}R)")

print("\n################ MODEL B — chandelier trailing, let-it-run (non-overlapping trades) ################")
print("  R normalized to initial risk (M*ATR). dur=avg trade days, durW=avg WINNER days (=how long runners run).")
for rk in ("all","nonbull","bull"):
    print(f"\n  ===== regime={rk}  (trail-multiple sweep, max-hold {MAXHOLD}) =====")
    for sname in ("don_high_20","don_high_55","don_low_20","RANDOM"):
        for M in TRAIL_MS:
            s=stats(Bn.get((sname,rk,f"M{M:.0f}")),Bdur.get((sname,rk,f"M{M:.0f}")))
            if not s: print(f"     {sname:12} M{M:.0f}  (thin)"); continue
            print(f"     {sname:12} M{M:.0f}  mean{s['mean']:+.2f}R med{s['med']:+.2f} skew{s['skew']:+.1f} "
                  f"win{s['win']*100:.0f}% mw{s['mw']:+.1f} ml{s['ml']:+.1f} max{s['mx']:+.0f} "
                  f">5R{s['g5']*100:.1f}% >10R{s['g10']*100:.1f}% dur{s['dur']:.0f}/{s['durw']:.0f} n{s['n']}")

print("\n  ----- max-hold cap sweep (M=3) : does capping the hold help or hurt the breakout? -----")
for rk in ("all","nonbull"):
    print(f"   regime={rk}")
    for sname in ("don_high_20","don_high_55","RANDOM"):
        row=[]
        for cap in MAXHOLD_SWEEP:
            s=stats(Bn.get((sname,rk,f"cap{cap}")),Bdur.get((sname,rk,f"cap{cap}")))
            row.append(f"cap{cap}:{s['mean']:+.2f}R(sk{s['skew']:+.1f},dur{s['dur']:.0f})" if s else f"cap{cap}:(thin)")
        print(f"     {sname:12} "+"  ".join(row))
print("\ndone.")
