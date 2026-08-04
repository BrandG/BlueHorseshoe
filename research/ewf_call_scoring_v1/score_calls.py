"""Phase 4: join extracted calls to prices and score per the frozen SPEC.md.

Every post gets exactly one row in data/scored.parquet — the funnel (SPEC §5.1)
is the first table of the report and unscoreable reasons are never collapsed.

Usage:
  ./run_research.sh python research/ewf_call_scoring_v1/score_calls.py --fetch   # pull OANDA H1 cache
  ./run_research.sh python research/ewf_call_scoring_v1/score_calls.py           # score + report
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "research"))
sys.path.insert(0, str(HERE))

from _lib import clustered_se, newey_west_se  # noqa: E402
from instrument_map import OANDA_ALIASES, map_instrument  # noqa: E402
from price_sources import PriceLib, fetch_oanda_cache  # noqa: E402
import scoring  # noqa: E402

CALLS = HERE / "data" / "calls.jsonl"
POSTS = HERE / "data" / "ewf_posts.parquet"
OUT = HERE / "data" / "scored.parquet"

NO_TEXT_LEN = 200  # empty video/webinar posts: extractor errors reclassified as no-text


def load_calls() -> pd.DataFrame:
    recs = [json.loads(l) for l in CALLS.open() if l.strip()]
    meta = pd.read_parquet(POSTS, columns=["id", "text_len", "edit_lag_days"]).set_index("id")
    df = pd.DataFrame(recs).drop_duplicates("post_id", keep="last").set_index("post_id")
    df = df.join(meta, how="left")
    df["date_gmt"] = pd.to_datetime(df["date_gmt"])
    return df


def classify_and_score(df: pd.DataFrame, lib: PriceLib) -> pd.DataFrame:
    rows = []
    for pid, r in df.iterrows():
        row = {"post_id": pid, "date_gmt": r.date_gmt, "title": r.title,
               "edited_late": bool(r.edit_lag_days > 7) if pd.notna(r.edit_lag_days) else False,
               "instrument_raw": r.get("instrument"), "call_type": r.get("call_type"),
               "direction": r.get("direction"), "stage": None}
        rows.append(row)

        if isinstance(r.get("error"), str) and r.get("error"):
            row["stage"] = "not-a-forecast" if (r.text_len or 0) < NO_TEXT_LEN else "extract-error"
            continue
        if not r.get("is_forecast"):
            row["stage"] = "not-a-forecast"
            continue
        if r.get("multi_scenario"):
            row["stage"] = "multi-scenario-hedge"
            continue
        mapped = map_instrument(r.get("instrument"), lib.equity_symbols)
        if mapped is None:
            row["stage"] = "no-instrument-data"
            continue
        source, symbol = mapped
        row["source"], row["symbol"] = source, symbol
        if r.get("direction") not in ("long", "short"):
            row["stage"] = "no-direction"
            continue

        bars = lib.equity_bars(symbol) if source == "duckdb" else lib.oanda_bars(symbol)
        if bars is None:
            row["stage"] = "no-price-data"
            continue
        i0 = (scoring.ref_bar_equity if source == "duckdb" else scoring.ref_bar_h1)(bars, r.date_gmt)
        if i0 is None or i0 == 0:
            row["stage"] = "no-price-data"
            continue
        # The primary window must actually FIT in the data. Without this, a call near the
        # end of a series (discontinued instrument, a 40-bar stub like SEK_JPY, or a post
        # from the last few weeks) silently gets a truncated window and its timeout R is
        # measured over days that do not exist. Reported as its own funnel stage so the
        # exclusion is visible rather than mistaken for a real timeout.
        if scoring.forward_trading_days(bars, i0) < max(scoring.WINDOWS_TD):
            if scoring.forward_trading_days(bars, i0) < 30:
                row["stage"] = "insufficient-forward-data"
                continue
            row["short_window_60"] = True  # 30td fits, 60td sensitivity does not
        ref = float(bars["open"][i0])
        inv = scoring.resolve_invalidation(r.get("invalidation"), bars)

        ctype = r.get("call_type")
        targets = r.get("targets") or []
        zone = r.get("zone")
        if ctype == "zone_reaction":
            if not (isinstance(zone, (list, np.ndarray)) and len(zone) >= 1):
                row["stage"] = "no-zone"
                continue
            if inv is None:
                row["stage"] = "no-invalidation"
                continue
            res = scoring.score_type_b(bars, i0, ref, r.direction, list(zone), inv, list(targets))
        else:
            if not targets:
                row["stage"] = "no-target"
                continue
            if inv is None:
                row["stage"] = "no-invalidation"
                continue
            res = scoring.score_type_a(bars, i0, ref, r.direction, list(targets), inv)

        if "unscoreable" in res:
            row["stage"] = res["unscoreable"]
            continue
        row["stage"] = "scored"
        row.update(res)
        row["ref_ts"] = pd.Timestamp(bars["ts"][i0])

        # nulls (SPEC §4), 30td primary window
        trend = scoring.trend_direction(bars, i0)
        rand = scoring.random_direction(int(pid))
        if ctype == "zone_reaction":
            edge, risk = res["entry_edge"], res["risk"]
            row["R_null_trend"] = scoring.null_type_b(bars, i0, edge, risk, trend) if trend else np.nan
            row["R_null_random"] = scoring.null_type_b(bars, i0, edge, risk, rand)
        else:
            tdist = min(abs(float(t) - ref) for t in targets)
            idist = abs(inv - ref)
            row["R_null_trend"] = scoring.null_type_a(bars, i0, ref, trend, tdist, idist) if trend else np.nan
            row["R_null_random"] = scoring.null_type_a(bars, i0, ref, rand, tdist, idist)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def _block(name: str, sub: pd.DataFrame) -> None:
    """Headline stats for one scored population (R_30 primary read)."""
    r = sub["R_30"].to_numpy(float)
    ok = ~np.isnan(r)
    r, sub = r[ok], sub[ok]
    if len(r) == 0:
        print(f"\n[{name}] n=0")
        return
    order = np.argsort(sub["ref_ts"].to_numpy())
    nw = newey_west_se(r[order], L=29)
    cse = clustered_se(r, sub["symbol"].to_numpy())
    amb = (sub["outcome_30"] == "ambiguous").sum()
    drop = sub["R_30_drop_ambig"].to_numpy(float)
    print(f"\n[{name}] n={len(r)}  mean R={r.mean():+.4f}  total R={r.sum():+.1f}  "
          f"NW-SE={nw:.4f}  clust-SE={cse:.4f}")
    print(f"  CI95(NW) = [{r.mean()-1.96*nw:+.4f}, {r.mean()+1.96*nw:+.4f}]  "
          f"hit rate={(sub['outcome_30']=='win').mean():.1%}  ambiguous={amb} "
          f"(drop-ambig mean R={np.nanmean(drop):+.4f})")
    for null in ("R_null_trend", "R_null_random"):
        n = sub[null].to_numpy(float)
        pair = ~np.isnan(n)
        if pair.sum() > 3:
            d = r[pair] - n[pair]
            se = d.std(ddof=1) / np.sqrt(len(d))
            print(f"  paired dR vs {null[7:]:6s}: {d.mean():+.4f} (SE {se:.4f}, n={len(d)})"
                  f"   [null own mean R={n[pair].mean():+.4f}]")
    # CANARY (research/README §5): a coin-flip direction on a driftless walk is a
    # martingale — mean R must sit at ~0.000. A drift away from 0 means the bracket
    # machinery is non-neutral and NO cell in this block can be trusted.
    rnd = sub["R_null_random"].to_numpy(float)
    rnd = rnd[~np.isnan(rnd)]
    if len(rnd) > 30:
        se = rnd.std(ddof=1) / np.sqrt(len(rnd))
        flag = "OK" if abs(rnd.mean()) < 2 * se else "*** NON-NEUTRAL ***"
        print(f"  canary: random-null mean R={rnd.mean():+.4f} (SE {se:.4f}) -> {flag}")
    for w in (10, 60):
        rw = sub[f"R_{w}"].to_numpy(float)
        print(f"  window {w}td: mean R={np.nanmean(rw):+.4f}")
    yr = sub.groupby(sub["date_gmt"].dt.year)["R_30"].agg(["count", "mean"])
    print("  per-year mean R: " + "  ".join(f"{y}:{m:+.2f}({c})" for y, (c, m) in yr.iterrows()))


def report(scored: pd.DataFrame) -> None:
    print("=" * 76)
    print("FUNNEL (every post, SPEC §5.1)")
    print(scored["stage"].value_counts().to_string())
    unmapped = scored.loc[scored.stage == "no-instrument-data", "instrument_raw"]
    print("\ntop unmapped instrument strings:")
    print(pd.Series(Counter(unmapped.dropna()).most_common(20)).to_string())

    sc = scored[scored.stage == "scored"]
    a = sc[sc.call_type != "zone_reaction"]
    b = sc[sc.call_type == "zone_reaction"]
    for late in (False, True):
        tag = "EDITED-LATE" if late else "clean (edit lag <= 7d)"
        _block(f"Type A directional — {tag}", a[a.edited_late == late])
    nofill = (b["outcome_30"] == "no_fill").sum()
    print(f"\nType B zone_reaction: {len(b)} scored, {nofill} no-fill in 30td "
          f"({nofill/max(len(b),1):.0%})")
    for late in (False, True):
        tag = "EDITED-LATE" if late else "clean (edit lag <= 7d)"
        filled = b[(b.edited_late == late) & (b["outcome_30"] != "no_fill")]
        _block(f"Type B +1R checkpoint — {tag}", filled)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="pull OANDA H1 cache for needed instruments")
    ap.add_argument("--fetch-all", action="store_true",
                    help="pull every instrument in the alias map (cache stays complete "
                         "even while extraction is still running)")
    args = ap.parse_args()

    df = load_calls()
    lib = PriceLib()
    try:
        if args.fetch or args.fetch_all:
            if args.fetch_all:
                need = Counter(OANDA_ALIASES.values())
            else:
                need = Counter()
                for _, r in df.iterrows():
                    m = map_instrument(r.get("instrument"), lib.equity_symbols)
                    if m and m[0] == "oanda":
                        need[m[1]] += 1
            # span from the POSTS archive (not calls-so-far): one fetch covers the
            # whole study even while extraction is still appending
            span = pd.read_parquet(POSTS, columns=["date_gmt"])["date_gmt"]
            start = (span.min() - pd.Timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
            end = (span.max() + pd.Timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"fetching {len(need)} OANDA instruments, {start} .. {end}")
            fetch_oanda_cache(sorted(need), start, end)
            return
        scored = classify_and_score(df, lib)
        scored.to_parquet(OUT, index=False)
        print(f"wrote {OUT} ({len(scored)} rows)")
        report(scored)
    finally:
        lib.close()


if __name__ == "__main__":
    main()
