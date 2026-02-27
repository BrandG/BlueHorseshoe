"""
analyze_indicator_impact.py

Leave-One-In Indicator Restoration Analysis.

V3 data-driven weights zeroed out 11 indicators and underperformed V2 significantly.
This script identifies which zeroed-out indicators, when restored individually to
their V2 weight, improve candidate selection quality.

Two-pass approach to stay within 4GB container memory:
  Pass 1: Score all symbols with V3 base weights, keep top ~200 per date
  Pass 2: Re-score only those ~200 with all 14 weight variants

Usage:
    docker exec bluehorseshoe python src/analyze_indicator_impact.py
"""

import copy
import gc
import json
import logging
import time

import numpy as np
import pandas as pd
from ta.volatility import AverageTrueRange

from bluehorseshoe.analysis.constants import ATR_WINDOW, MIN_STOCK_PRICE, MAX_STOCK_PRICE
from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer
from bluehorseshoe.core.config import weights_config
from bluehorseshoe.core.container import create_app_container
from bluehorseshoe.data.historical_data import get_technical_indicators

logging.basicConfig(level=logging.WARNING)

# ── Configuration ──────────────────────────────────────────────────────────

ANALYSIS_DATES = ["2025-11-12", "2025-11-19", "2025-12-10"]

ZEROED_INDICATORS = [
    ("trend",       "ADX_MULTIPLIER",                    1.0),
    ("trend",       "DONCHIAN_MULTIPLIER",               1.5),
    ("trend",       "SUPERTREND_MULTIPLIER",             1.5),
    ("trend",       "KELTNER_MULTIPLIER",                1.5),
    ("trend",       "PSAR_MULTIPLIER",                   0.5),
    ("trend",       "TTM_SQUEEZE_MULTIPLIER",            2.0),
    ("trend",       "AROON_MULTIPLIER",                  1.0),
    ("volume",      "AD_LINE_MULTIPLIER",                1.0),
    ("volume",      "VWAP_MULTIPLIER",                   2.0),
    ("candlestick", "MARUBOZU_MULTIPLIER",               1.0),
    ("candlestick", "RISE_FALL_3_METHODS_MULTIPLIER",    1.5),
    ("candlestick", "THREE_WHITE_SOLDIERS_MULTIPLIER",   0.5),
]

TOP_N = 10
TOP_N_WIDE = 20
TOP_SPREAD = 50
# How many symbols to keep after pass 1 for detailed variant scoring
PASS1_KEEP = 200


# ── Helpers ────────────────────────────────────────────────────────────────

def load_weights_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def patch_weights(new_weights: dict) -> None:
    weights_config._weights = new_weights


def compute_atr_price_ratio(df: pd.DataFrame) -> float:
    if "ATR" not in df.columns:
        df["ATR"] = AverageTrueRange(
            high=df["high"], low=df["low"], close=df["close"], window=ATR_WINDOW
        ).average_true_range()
    atr = df["ATR"].values[-1]
    close = df["close"].values[-1]
    if pd.isna(atr) or close <= 0:
        return 0.02
    return atr / close


def analyze_variant(scored: list[dict], v2_top10_syms: set[str]) -> dict:
    if not scored:
        return {
            "n_candidates": 0,
            "score_mean": 0, "score_std": 0, "score_min": 0, "score_max": 0,
            "avg_atr_ratio_top10": 0, "v2_overlap_top10": 0, "v2_in_top20": 0,
            "top10_syms": [],
        }

    top_n = scored[:TOP_N]
    top_spread = scored[:TOP_SPREAD]
    top_wide = scored[:TOP_N_WIDE]

    scores_spread = [r["score"] for r in top_spread]
    top10_syms = {r["symbol"] for r in top_n}
    top20_syms = {r["symbol"] for r in top_wide}

    return {
        "n_candidates": len(scored),
        "score_mean": float(np.mean(scores_spread)),
        "score_std": float(np.std(scores_spread)),
        "score_min": float(np.min(scores_spread)),
        "score_max": float(np.max(scores_spread)),
        "avg_atr_ratio_top10": float(np.mean([r["atr_ratio"] for r in top_n])),
        "v2_overlap_top10": len(top10_syms & v2_top10_syms),
        "v2_in_top20": len(top20_syms & v2_top10_syms),
        "top10_syms": [r["symbol"] for r in top_n],
    }


def load_and_prepare(database, symbol: str, target_ts: pd.Timestamp) -> pd.DataFrame | None:
    """Load one symbol from historical_prices_recent, filter & enrich."""
    doc = database["historical_prices_recent"].find_one(
        {"symbol": symbol}, {"days": 1, "_id": 0}
    )
    if not doc or not doc.get("days"):
        return None

    df = pd.DataFrame(doc["days"])
    if "date" not in df.columns or len(df) < 30:
        return None

    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] <= target_ts]
    if len(df) < 30:
        return None

    last_date = df.iloc[-1]["date"]
    if (target_ts - last_date).days > 7:
        return None

    for c in ["open", "high", "low", "close"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

    get_technical_indicators(df)

    close = df.iloc[-1]["close"]
    if close < MIN_STOCK_PRICE or close > MAX_STOCK_PRICE:
        return None

    return df


# ── Main ──────────────────────────────────────────────────────────────────

def run_analysis():
    t_start = time.time()
    print("=" * 90)
    print("LEAVE-ONE-IN INDICATOR RESTORATION ANALYSIS")
    print("=" * 90)

    v3_weights = load_weights_file("/workspaces/BlueHorseshoe/src/weights.json")
    v2_weights = load_weights_file("/workspaces/BlueHorseshoe/src/weights_v2.json")

    # Build all weight variants
    all_weight_sets: dict[str, dict] = {}
    all_weight_sets["V2"] = copy.deepcopy(v2_weights)
    all_weight_sets["V3_base"] = copy.deepcopy(v3_weights)

    for category, key, v2_val in ZEROED_INDICATORS:
        label = key.replace("_MULTIPLIER", "")
        variant = copy.deepcopy(v3_weights)
        if category not in variant:
            variant[category] = {}
        variant[category][key] = v2_val
        all_weight_sets[f"+{label}"] = variant

    print(f"Weight variants: {len(all_weight_sets)} "
          f"(V2 + V3_base + {len(all_weight_sets)-2} restored)")

    container = create_app_container()
    database = container.get_database()

    # Get symbol list
    pipeline = [
        {"$project": {"symbol": 1, "last_day": {"$arrayElemAt": ["$days", -1]}}},
        {"$match": {
            "last_day.close": {"$gte": MIN_STOCK_PRICE, "$lte": MAX_STOCK_PRICE},
            "last_day.avg_volume_20": {"$gte": 100000}
        }},
        {"$project": {"symbol": 1, "_id": 0}},
    ]
    symbols = sorted([doc["symbol"] for doc in
                      database["historical_prices_recent"].aggregate(pipeline)])
    print(f"Active symbols: {len(symbols)}\n")

    # ── Per-date analysis ──────────────────────────────────────────────
    all_metrics: dict[str, list[dict]] = {}

    for date_idx, target_date in enumerate(ANALYSIS_DATES):
        print(f"{'─' * 90}")
        print(f"Date {date_idx + 1}/{len(ANALYSIS_DATES)}: {target_date}")
        print(f"{'─' * 90}")
        t_date = time.time()
        target_ts = pd.to_datetime(target_date)

        # ── PASS 1: Score all symbols with BOTH V2 and V3 base weights ──
        # We need V2's top candidates too for overlap measurement
        print("  Pass 1: Broad scoring (V2 + V3 base)...", flush=True)

        v2_scores = []  # (symbol, score, atr_ratio, close)
        v3_scores = []
        candidate_symbols = set()

        for i, sym in enumerate(symbols, 1):
            df = load_and_prepare(database, sym, target_ts)
            if df is None:
                continue

            atr_ratio = compute_atr_price_ratio(df)
            close_val = float(df.iloc[-1]["close"])

            # Score with V2
            patch_weights(all_weight_sets["V2"])
            r2 = TechnicalAnalyzer.calculate_technical_score(df, strategy="baseline")
            t2 = r2.get("total", 0.0)
            if t2 > 0:
                v2_scores.append({"symbol": sym, "score": t2,
                                  "atr_ratio": atr_ratio, "close": close_val})

            # Score with V3 base
            patch_weights(all_weight_sets["V3_base"])
            r3 = TechnicalAnalyzer.calculate_technical_score(df, strategy="baseline")
            t3 = r3.get("total", 0.0)
            if t3 > 0:
                v3_scores.append({"symbol": sym, "score": t3,
                                  "atr_ratio": atr_ratio, "close": close_val})

            if i % 500 == 0:
                print(f"    {i}/{len(symbols)} processed", flush=True)

        print(f"    {len(symbols)}/{len(symbols)} processed", flush=True)

        # Sort and get top candidates
        v2_scores.sort(key=lambda x: x["score"], reverse=True)
        v3_scores.sort(key=lambda x: x["score"], reverse=True)

        # Keep union of V2 top-200 and V3 top-200 for pass 2
        for r in v2_scores[:PASS1_KEEP]:
            candidate_symbols.add(r["symbol"])
        for r in v3_scores[:PASS1_KEEP]:
            candidate_symbols.add(r["symbol"])

        v2_top10_syms = {r["symbol"] for r in v2_scores[:TOP_N]}

        # Record V2 and V3 base metrics
        v2_metrics = analyze_variant(v2_scores, v2_top10_syms)
        if "V2" not in all_metrics:
            all_metrics["V2"] = []
        all_metrics["V2"].append(v2_metrics)

        v3_metrics = analyze_variant(v3_scores, v2_top10_syms)
        if "V3_base" not in all_metrics:
            all_metrics["V3_base"] = []
        all_metrics["V3_base"].append(v3_metrics)

        print(f"  V2:  {v2_metrics['n_candidates']} cands, "
              f"ATR/px={v2_metrics['avg_atr_ratio_top10']:.4f}, "
              f"top-10: {v2_metrics['top10_syms']}")
        print(f"  V3:  {v3_metrics['n_candidates']} cands, "
              f"overlap={v3_metrics['v2_overlap_top10']}/10, "
              f"ATR/px={v3_metrics['avg_atr_ratio_top10']:.4f}")
        print(f"  Candidate pool for pass 2: {len(candidate_symbols)} symbols")

        gc.collect()

        # ── PASS 2: Score candidates with all 12 indicator variants ──────
        print("  Pass 2: Variant scoring...", flush=True)
        variant_names = [n for n in all_weight_sets if n not in ("V2", "V3_base")]
        variant_results: dict[str, list[dict]] = {n: [] for n in variant_names}

        candidate_list = sorted(candidate_symbols)
        for i, sym in enumerate(candidate_list, 1):
            df = load_and_prepare(database, sym, target_ts)
            if df is None:
                continue

            atr_ratio = compute_atr_price_ratio(df)
            close_val = float(df.iloc[-1]["close"])

            for var_name in variant_names:
                patch_weights(all_weight_sets[var_name])
                result = TechnicalAnalyzer.calculate_technical_score(
                    df, strategy="baseline"
                )
                total = result.get("total", 0.0)
                if total > 0:
                    variant_results[var_name].append({
                        "symbol": sym,
                        "score": total,
                        "atr_ratio": atr_ratio,
                        "close": close_val,
                    })

            if i % 100 == 0:
                print(f"    {i}/{len(candidate_list)} variant-scored", flush=True)

        print(f"    {len(candidate_list)}/{len(candidate_list)} variant-scored",
              flush=True)

        # Sort and analyze each variant
        for var_name in variant_names:
            variant_results[var_name].sort(key=lambda x: x["score"], reverse=True)
            metrics = analyze_variant(variant_results[var_name], v2_top10_syms)
            if var_name not in all_metrics:
                all_metrics[var_name] = []
            all_metrics[var_name].append(metrics)

        print(f"  Date completed in {time.time() - t_date:.0f}s\n")
        gc.collect()

    # ── Restore weights ───────────────────────────────────────────────
    patch_weights(copy.deepcopy(v3_weights))

    # ── Aggregate ─────────────────────────────────────────────────────
    print()
    print("=" * 120)
    print("AGGREGATED RESULTS (averaged across 3 dates)")
    print("=" * 120)

    summary_rows = []
    for var_name, metrics_list in all_metrics.items():
        avg = {
            "variant": var_name,
            "avg_candidates": np.mean([m["n_candidates"] for m in metrics_list]),
            "avg_score_mean": np.mean([m["score_mean"] for m in metrics_list]),
            "avg_score_std": np.mean([m["score_std"] for m in metrics_list]),
            "avg_score_max": np.mean([m["score_max"] for m in metrics_list]),
            "avg_atr_ratio": np.mean([m["avg_atr_ratio_top10"] for m in metrics_list]),
            "avg_v2_overlap": np.mean([m["v2_overlap_top10"] for m in metrics_list]),
            "avg_v2_in_top20": np.mean([m["v2_in_top20"] for m in metrics_list]),
        }
        summary_rows.append(avg)

    header = (
        f"{'Variant':<25} {'Cands':>6} {'ScoreMean':>10} {'ScoreStd':>9} "
        f"{'ScoreMax':>9} {'ATR/Px':>8} {'V2@10':>6} {'V2@20':>6}"
    )
    print(header)
    print("-" * 120)

    pinned = ["V2", "V3_base"]
    pinned_rows = [r for r in summary_rows if r["variant"] in pinned]
    variant_rows = [r for r in summary_rows if r["variant"] not in pinned]
    variant_rows.sort(key=lambda x: (-x["avg_v2_overlap"], x["avg_atr_ratio"]))

    for row in pinned_rows + variant_rows:
        flag = ""
        if row["variant"] not in pinned:
            v3_base = next(r for r in summary_rows if r["variant"] == "V3_base")
            if row["avg_atr_ratio"] < v3_base["avg_atr_ratio"] * 0.95:
                flag = " << lower vol"
            if row["avg_v2_overlap"] > v3_base["avg_v2_overlap"] + 0.5:
                flag += " << more V2"
        print(
            f"{row['variant']:<25} {row['avg_candidates']:>6.0f} "
            f"{row['avg_score_mean']:>10.2f} {row['avg_score_std']:>9.2f} "
            f"{row['avg_score_max']:>9.2f} {row['avg_atr_ratio']:>8.4f} "
            f"{row['avg_v2_overlap']:>6.1f} {row['avg_v2_in_top20']:>6.1f}"
            f"{flag}"
        )

    print("-" * 120)

    # ── Delta table ───────────────────────────────────────────────────
    print()
    print("=" * 120)
    print("DELTA FROM V3 BASE (positive = improvement)")
    print("=" * 120)

    v3_base_avg = next(r for r in summary_rows if r["variant"] == "V3_base")

    delta_header = (
        f"{'Variant':<25} {'dCands':>7} {'dScoreStd':>10} "
        f"{'dATR/Px':>9} {'dV2@10':>7} {'dV2@20':>7} {'Impact':>8}"
    )
    print(delta_header)
    print("-" * 120)

    impact_scores = []
    for row in variant_rows:
        d_cands = row["avg_candidates"] - v3_base_avg["avg_candidates"]
        d_std = row["avg_score_std"] - v3_base_avg["avg_score_std"]
        d_atr = row["avg_atr_ratio"] - v3_base_avg["avg_atr_ratio"]
        d_v2_10 = row["avg_v2_overlap"] - v3_base_avg["avg_v2_overlap"]
        d_v2_20 = row["avg_v2_in_top20"] - v3_base_avg["avg_v2_in_top20"]

        impact = (d_v2_10 * 3.0) + (d_v2_20 * 1.0) + (-d_atr * 50.0) + (d_std * 0.5)
        impact_scores.append((row["variant"], impact))

        print(
            f"{row['variant']:<25} {d_cands:>+7.0f} {d_std:>+10.2f} "
            f"{d_atr:>+9.4f} {d_v2_10:>+7.1f} {d_v2_20:>+7.1f} "
            f"{impact:>+8.2f}"
        )

    print("-" * 120)

    # ── Final ranking ─────────────────────────────────────────────────
    print()
    print("=" * 90)
    print("INDICATOR RESTORATION RANKING (by composite impact score)")
    print("=" * 90)

    impact_scores.sort(key=lambda x: x[1], reverse=True)
    for rank, (name, score) in enumerate(impact_scores, 1):
        bar = "+" * max(0, int(score * 2)) if score > 0 else "-" * max(0, int(-score * 2))
        print(f"  {rank:>2}. {name:<25} impact={score:>+7.2f}  {bar}")

    print()
    print("Positive impact = indicator restoration improves candidate selection")
    print("Key factors: V2 overlap (3x), ATR/price reduction (50x), score spread (0.5x)")

    # ── Per-date detail ───────────────────────────────────────────────
    print()
    print("=" * 120)
    print("PER-DATE DETAIL: Top-10 candidates by variant")
    print("=" * 120)

    variant_names_all = [n for n in all_weight_sets if n not in pinned]
    for date_idx, target_date in enumerate(ANALYSIS_DATES):
        print(f"\n{'─' * 90}")
        print(f"Date: {target_date}")
        print(f"{'─' * 90}")

        v2_m = all_metrics["V2"][date_idx]
        v3_m = all_metrics["V3_base"][date_idx]
        print(f"  V2  top-10: {v2_m['top10_syms']}")
        print(f"  V3  top-10: {v3_m['top10_syms']}  (overlap={v3_m['v2_overlap_top10']})")

        for var_name in variant_names_all:
            m = all_metrics[var_name][date_idx]
            if m["v2_overlap_top10"] > v3_m["v2_overlap_top10"]:
                print(f"  {var_name:<23} top-10: {m['top10_syms']}  "
                      f"(overlap={m['v2_overlap_top10']}, "
                      f"ATR/px={m['avg_atr_ratio_top10']:.4f})")

    elapsed = time.time() - t_start
    print(f"\nTotal elapsed: {elapsed:.0f}s ({elapsed/60:.1f}min)")


if __name__ == "__main__":
    run_analysis()
