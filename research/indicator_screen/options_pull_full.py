"""Historical options pull for the options-IV conditioning axis (AV HISTORICAL_OPTIONS).

One EOD chain per DeepOS fire from options_fire_list.parquet. Checkpoint values are slimmed
before caching so the JSON remains resumable at full-fire scale. Final flatten writes both the
slim chain safety net and one row per fire of analysis-ready ATM IV / 25-delta skew features.
"""
import argparse, json, os, time, urllib.parse, urllib.request
from datetime import datetime

import numpy as np, pandas as pd

FIRES="research/indicator_screen/options_fire_list.parquet"
CKPT="research/indicator_screen/options_cache_full.json"
CHAINS_OUT="data/options_chains_fires.parquet"
FEATURES_OUT="data/options_iv_features.parquet"
KEY=os.environ.get("ALPHAVANTAGE_KEY")
SLEEP=0.55; MAX_CONSEC_GATE=3; FLUSH_EVERY=250
KEEP_FIELDS=("expiration","strike","type","mark","bid","ask","volume","open_interest","implied_volatility","delta")
CHAIN_COLS=["symbol","fire_date","expiration","dte","strike","type","mark","bid","ask","volume","open_interest","iv","delta"]
FEATURE_COLS=["symbol","date","nonbull","close","has_chain","dte_used","atm_iv","put25_iv","call25_iv",
              "skew_25d","skew_norm","pcr_oi","n_contracts","atm_spread_pct",
              "put25_delta","call25_delta","atm_moneyness","iv_pctile"]

def num(x):
    try:
        if x in (None,"","None"): return np.nan
        return float(x)
    except Exception:
        return np.nan

def key_for(sym,dt): return f"{sym}|{dt}"

def write_cache(cache):
    tmp=CKPT+".tmp"
    with open(tmp,"w") as f:
        json.dump(cache,f)
    os.replace(tmp,CKPT)

def fetch(sym,dt):
    url=("https://www.alphavantage.co/query?function=HISTORICAL_OPTIONS"
         f"&symbol={urllib.parse.quote(sym)}&date={dt}&apikey={KEY}")
    raw=urllib.request.urlopen(url,timeout=60).read().decode()
    j=json.loads(raw)
    if "Note" in j or "Information" in j:
        return None,"gate:"+str(j.get("Note") or j.get("Information"))[:140]
    if "Error Message" in j:
        return [],None
    return j.get("data",[]) or [],None

def slim_chain(chain,fire_date):
    fdt=datetime.strptime(fire_date,"%Y-%m-%d").date()
    rows=[]
    for r in chain:
        exp=r.get("expiration")
        try:
            dte=(datetime.strptime(exp,"%Y-%m-%d").date()-fdt).days
        except Exception:
            continue
        delta=num(r.get("delta"))
        if dte<7 or dte>90 or not (0.05<=abs(delta)<=0.95): continue
        out={k:r.get(k) for k in KEEP_FIELDS}
        for k in ("strike","mark","bid","ask","volume","open_interest","implied_volatility","delta"):
            out[k]=num(out.get(k))
        out["dte"]=int(dte)
        rows.append(out)
    return rows

def target_expiration(df):
    dtes=np.array(sorted(df.dte.dropna().astype(int).unique()))
    band=dtes[(dtes>=20)&(dtes<=60)]
    choices=band if len(band) else dtes[dtes>=7]
    if not len(choices): return None,np.nan
    dte=int(sorted(choices,key=lambda x:(abs(x-30),x))[0])
    exp=df.loc[df.dte==dte,"expiration"].sort_values().iloc[0]
    return exp,dte

def valid_iv(s):
    return s.notna() & (s>0.01) & (s<5.0)

def delta_iv(df,typ,target,lo,hi):
    legs=df[df.type.str.lower().eq(typ) & valid_iv(df.iv) & df.delta.between(lo,hi)].copy()
    if not len(legs): return np.nan
    legs["dist"]=(legs.delta-target).abs()
    leg=legs.sort_values(["dist","strike"]).iloc[0]
    return float(leg.iv),float(leg.delta)

def flatten(fires,cache):
    fires=fires.copy()
    if fires.duplicated(["symbol","date"]).any():
        dup=fires[fires.duplicated(["symbol","date"],keep=False)].head()
        raise AssertionError(f"duplicate fire keys:\n{dup}")
    rows=[]
    feature_rows=[]
    for r in fires.itertuples(index=False):
        sym=r.symbol; dt=str(r.date); k=key_for(sym,dt)
        contracts=cache.get(k,{}).get("contracts",[])
        for c in contracts:
            rows.append({"symbol":sym,"fire_date":dt,"expiration":c.get("expiration"),"dte":c.get("dte"),
                         "strike":c.get("strike"),"type":c.get("type"),"mark":c.get("mark"),
                         "bid":c.get("bid"),"ask":c.get("ask"),"volume":c.get("volume"),
                         "open_interest":c.get("open_interest"),"iv":c.get("implied_volatility"),
                         "delta":c.get("delta")})
        feat={"symbol":sym,"date":dt,"nonbull":bool(r.nonbull),"close":float(r.close),
              "has_chain":bool(contracts),"dte_used":np.nan,"atm_iv":np.nan,"put25_iv":np.nan,
              "call25_iv":np.nan,"skew_25d":np.nan,"skew_norm":np.nan,"pcr_oi":np.nan,
              "n_contracts":len(contracts),"atm_spread_pct":np.nan,"put25_delta":np.nan,
              "call25_delta":np.nan,"atm_moneyness":np.nan,"iv_pctile":np.nan}
        if contracts:
            cdf=pd.DataFrame(contracts)
            exp,dte=target_expiration(cdf)
            feat["dte_used"]=dte
            tdf=cdf[cdf.expiration.eq(exp)].copy() if exp is not None else cdf.iloc[0:0].copy()
            if len(tdf):
                tdf["type"]=tdf.type.astype(str)
                tdf["iv"]=tdf.implied_volatility
                atm_strike=float(tdf.iloc[(tdf.strike-float(r.close)).abs().argsort()[:1]].strike.iloc[0])
                feat["atm_moneyness"]=atm_strike/float(r.close) if float(r.close) else np.nan
                atm=tdf[tdf.strike.eq(atm_strike)].copy()
                atm_iv=atm.loc[valid_iv(atm.implied_volatility),"implied_volatility"]
                feat["atm_iv"]=float(atm_iv.mean()) if len(atm_iv) else np.nan
                put=delta_iv(tdf,"put",-0.25,-0.45,-0.10)
                call=delta_iv(tdf,"call",0.25,0.10,0.45)
                if isinstance(put,tuple): feat["put25_iv"],feat["put25_delta"]=put
                if isinstance(call,tuple): feat["call25_iv"],feat["call25_delta"]=call
                if pd.notna(feat["put25_iv"]) and pd.notna(feat["call25_iv"]):
                    feat["skew_25d"]=feat["put25_iv"]-feat["call25_iv"]
                if pd.notna(feat["skew_25d"]) and pd.notna(feat["atm_iv"]) and feat["atm_iv"]!=0:
                    feat["skew_norm"]=feat["skew_25d"]/feat["atm_iv"]
                put_oi=tdf.loc[tdf.type.str.lower().eq("put"),"open_interest"].sum(skipna=True)
                call_oi=tdf.loc[tdf.type.str.lower().eq("call"),"open_interest"].sum(skipna=True)
                feat["pcr_oi"]=float(put_oi/call_oi) if call_oi else np.nan
                spr=atm.assign(spread_pct=(atm.ask-atm.bid)/atm.mark.replace(0,np.nan)).spread_pct
                feat["atm_spread_pct"]=float(spr.median()) if spr.notna().any() else np.nan
        feature_rows.append(feat)
    chains=pd.DataFrame(rows,columns=CHAIN_COLS)
    feats=pd.DataFrame(feature_rows,columns=FEATURE_COLS)
    if len(feats):
        mask=feats.has_chain & feats.atm_iv.notna()
        # Partial smoke flattens often have one fire per date, so pctile=1.0 there; full pulls are cross-sectional.
        feats.loc[mask,"iv_pctile"]=feats.loc[mask].groupby("date").atm_iv.rank(pct=True)
    chains.to_parquet(CHAINS_OUT,index=False)
    feats.to_parquet(FEATURES_OUT,index=False)
    print(f"flattened {len(chains)} contracts -> {CHAINS_OUT}",flush=True)
    print(f"flattened {len(feats)} fire features -> {FEATURES_OUT}",flush=True)
    if len(feats):
        print(f"coverage overall: {100*feats.has_chain.mean():.1f}% ({int(feats.has_chain.sum())}/{len(feats)})",flush=True)
        by_year=feats.groupby(feats.date.str[:4]).has_chain.mean().mul(100)
        print("coverage by year (%):"); print(by_year.round(1).to_string(),flush=True)
        nb=feats[feats.nonbull]
        print(f"coverage nonbull-only: {100*nb.has_chain.mean():.1f}% ({int(nb.has_chain.sum())}/{len(nb)})" if len(nb) else "coverage nonbull-only: n/a",flush=True)
    return chains,feats

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--limit",type=int,default=None,help="process only the first N uncached fires")
    ap.add_argument("--flatten-partial",action="store_true",help="flatten cached subset even if pull is incomplete")
    args=ap.parse_args()
    fires=pd.read_parquet(FIRES)
    fires["date"]=fires.date.astype(str).str[:10]
    fire_keys=set(fires.apply(lambda r: key_for(r.symbol,r.date),axis=1))
    print(f"{len(fires)} fires to pull",flush=True)
    cache=json.load(open(CKPT)) if os.path.exists(CKPT) else {}
    print(f"checkpoint has {len(cache)} fires cached",flush=True)
    todo=fires[~fires.apply(lambda r: key_for(r.symbol,r.date) in cache,axis=1)]
    if args.limit is not None: todo=todo.head(args.limit)
    print(f"to fetch this run: {len(todo)}",flush=True)

    consec_gate=0; fetched=0
    for r in todo.itertuples(index=False):
        sym=r.symbol; dt=str(r.date); k=key_for(sym,dt)
        try:
            chain,gate=fetch(sym,dt)
        except Exception as e:
            print(f"  net-err {k}: {e} (will retry on resume)",flush=True); time.sleep(SLEEP); continue
        time.sleep(SLEEP)
        if gate is not None:
            consec_gate+=1
            print(f"  GATE on {k} ({consec_gate} consecutive): {gate}",flush=True)
            if consec_gate>=MAX_CONSEC_GATE:
                print("gate storm -> stopping for later resume",flush=True); break
            continue
        consec_gate=0
        cache[k]={"contracts":slim_chain(chain,dt)}
        fetched+=1
        if fetched%FLUSH_EVERY==0:
            write_cache(cache)
            print(f"  {fetched} fetched this run / {len(cache)} total cached",flush=True)
    write_cache(cache)
    print(f"cached: {len(cache)}/{len(fires)}",flush=True)

    complete=fire_keys.issubset(cache)
    if complete or args.flatten_partial:
        use=fires if complete else fires[fires.apply(lambda r: key_for(r.symbol,r.date) in cache,axis=1)]
        flatten(use,cache)
        if args.flatten_partial and not complete: print("partial flatten complete -- rerun without --limit for full pull",flush=True)
    else:
        print("incomplete -- rerun to resume",flush=True)

if __name__=="__main__":
    main()
