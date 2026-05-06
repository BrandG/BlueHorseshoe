"""Phase 2: Cell-level v2 walk-forward with OVERLAP session filter applied.

For each working v2 indicator, re-run the walk-forward + spread test with all
OVERLAP-session triggers dropped at expectancy time. Compare filtered survivor
counts against unfiltered to see if any indicator's portfolio gains cells.

Mechanism: monkey-patch `_lib.expectancy_split` BEFORE importing the runners, so
their `from _lib import expectancy_split` binds to the filtered version. Each
runner calls expectancy_split inside walkforward_pair / spread_test_pair, so
both are filtered. portfolio_trades collection is filtered post-hoc on the CSV.

No modifications to existing runners.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/research/_v2_rerun")
sys.path.insert(0, "/root/BlueHorseshoe/src")

# Patch _lib BEFORE importing runners so they pick up the filtered expectancy_split.
import _lib  # noqa: E402
from bh_ftmo.indicators.sessions import session_label  # noqa: E402

DROP_SESSION = "overlap"

_orig_expectancy_split = _lib.expectancy_split


def patched_expectancy_split(rs_with_ts, **kwargs):
    if not rs_with_ts:
        return _orig_expectancy_split(rs_with_ts, **kwargs)
    ts_series = pd.Series([ts for ts, _ in rs_with_ts])
    sessions = session_label(ts_series).values
    filtered = [
        (ts, r) for (ts, r), s in zip(rs_with_ts, sessions) if s != DROP_SESSION
    ]
    return _orig_expectancy_split(filtered, **kwargs)


_lib.expectancy_split = patched_expectancy_split

# Now import the runners — they pick up the patched expectancy_split.
import run_stoch_v2  # noqa: E402
import run_sma_v2  # noqa: E402
import run_ema_v2  # noqa: E402
import run_rsi_v2  # noqa: E402
import run_cci_v2  # noqa: E402
import run_macd_v2  # noqa: E402
import run_atr_v2  # noqa: E402
import run_ichimoku_v2  # noqa: E402


INDICATORS = [
    ("stoch",     run_stoch_v2,     ["mid", "limit"]),
    ("sma",       run_sma_v2,       ["mid", "limit"]),
    ("ema",       run_ema_v2,       ["mid", "limit"]),
    ("rsi",       run_rsi_v2,       ["mid", "limit"]),
    ("cci",       run_cci_v2,       ["mid", "limit"]),
    ("macd",      run_macd_v2,      ["limit"]),       # mid was NULL, stop near-NULL
    ("atr",       run_atr_v2,       ["mid", "limit"]),
    ("ichimoku",  run_ichimoku_v2,  ["limit"]),       # only limit produced a cell
]


def run_filter_test(module, entry_mode):
    """Walk-forward + spread test with patched expectancy. Returns counts."""
    all_rows = []
    for pair in _lib.PAIRS_FULL:
        rows = module.walkforward_pair(pair, entry_mode=entry_mode)
        all_rows.extend(rows)
    wf_df = pd.DataFrame(all_rows)
    wf_survivors = _lib.survivor_gate_walkforward(wf_df)

    spread_rows = []
    for _, r in wf_survivors.iterrows():
        # Each runner has a slightly different spread_test_pair signature — use
        # the row-record fields it produces.
        kwargs = {k: r[k] for k in r.index if k.startswith(("pair", "te_", "tr_"))}
        # We can't use a generic kwargs call; instead, dispatch per indicator's
        # known signature. But for this test, we only need the spread-survival
        # rate, not the exact cells. Run the per-indicator spread_test_pair via
        # introspection of expected fields below.
        out = call_spread_test(module, r, entry_mode)
        if out is not None:
            spread_rows.append(out)
    sp_df = pd.DataFrame(spread_rows)
    sp_survivors = _lib.survivor_gate_walkforward(sp_df) if not sp_df.empty else sp_df
    n_unique_pairs = sp_survivors["pair"].nunique() if (not sp_survivors.empty and "pair" in sp_survivors) else 0
    test_mean_r = sp_survivors["te_mean_r"].mean() if not sp_survivors.empty else float("nan")
    return len(wf_df), len(wf_survivors), len(sp_df), len(sp_survivors), n_unique_pairs, test_mean_r


def call_spread_test(module, r, entry_mode):
    """Dispatch to the runner's spread_test_pair with the right kwargs from row r."""
    name = module.__name__
    if name == "run_stoch_v2":
        return module.spread_test_pair(r["pair"], int(r["k_period"]), int(r["d_period"]),
                                        int(r["threshold"]), int(r["recovery"]),
                                        r["direction"], entry_mode=entry_mode)
    if name == "run_sma_v2":
        return module.spread_test_pair(r["pair"], int(r["period"]), float(r["k"]),
                                        r["direction"], entry_mode=entry_mode)
    if name == "run_ema_v2":
        return module.spread_test_pair(r["pair"], int(r["period"]), float(r["k"]),
                                        r["direction"], entry_mode=entry_mode)
    if name == "run_rsi_v2":
        return module.spread_test_pair(r["pair"], int(r["period"]),
                                        int(r["threshold"]), int(r["recovery"]),
                                        r["direction"], entry_mode=entry_mode)
    if name == "run_cci_v2":
        return module.spread_test_pair(r["pair"], int(r["period"]),
                                        int(r["threshold"]), int(r["recovery"]),
                                        r["direction"], entry_mode=entry_mode)
    if name == "run_macd_v2":
        return module.spread_test_pair(r["pair"], int(r["fast"]), int(r["slow"]),
                                        int(r["signal"]), r["trigger"],
                                        r["direction"], entry_mode=entry_mode)
    if name == "run_atr_v2":
        return module.spread_test_pair(r["pair"], int(r["atr_period"]), float(r["k"]),
                                        r["trigger"], r["direction"],
                                        entry_mode=entry_mode)
    if name == "run_ichimoku_v2":
        return module.spread_test_pair(r["pair"], int(r["tenkan"]), int(r["kijun"]),
                                        int(r["senkou_b"]), int(r["displacement"]),
                                        r["trigger"], r["direction"],
                                        entry_mode=entry_mode)
    raise ValueError(f"unknown module {name}")


# Baselines (unfiltered) — walk-forward survivor counts from existing CSVs.
# Format: (n_cells, wf_survivors, prod_pairs)
BASELINES = {
    ("stoch", "mid"):     (5120, 103, 4),
    ("stoch", "limit"):   (5120, 103, 4),
    ("sma", "mid"):       (1280, 19,  3),
    ("sma", "limit"):     (1280, 9,   3),
    ("ema", "mid"):       (1280, 21,  4),
    ("ema", "limit"):     (1280, 11,  4),
    ("rsi", "mid"):       (5120, 25,  3),
    ("rsi", "limit"):     (5120, 14,  3),
    ("cci", "mid"):       (5120, 40,  5),
    ("cci", "limit"):     (5120, 22,  5),
    ("macd", "limit"):    (2400, 19,  5),
    ("atr", "mid"):       (960,  27,  2),
    ("atr", "limit"):     (960,  6,   3),
    ("ichimoku", "limit"):(720,  1,   1),
}


def main():
    print("=" * 100)
    print("PHASE 2 — OVERLAP SESSION FILTER TEST (cell-level v2 walk-forward)")
    print("=" * 100)
    print(f"{'INDICATOR':<12} {'ENTRY':<8} {'WF_BASE→FILT':<16} "
          f"{'PROD_BASE→FILT_CELLS':<22} {'UNIQ_PAIRS':<12} {'TEST_MEAN_R':<12}")
    print("-" * 100)
    rows = []
    for name, module, entry_modes in INDICATORS:
        for entry in entry_modes:
            n_cells, n_wf, n_sp, n_prod, n_pairs, te_mean = run_filter_test(module, entry)
            base = BASELINES.get((name, entry), ("?", "?", "?"))
            wf_str = f"{base[1]}→{n_wf}"
            prod_str = f"{base[2]}→{n_prod}"
            pair_str = f"{base[2]}→{n_pairs}"
            te_str = f"{te_mean:+.3f}" if not pd.isna(te_mean) else "—"
            rows.append({
                "indicator": name, "entry": entry, "n_cells": n_cells,
                "wf_baseline": base[1], "wf_filtered": n_wf,
                "prod_baseline": base[2], "prod_filtered": n_prod,
                "uniq_pairs_filtered": n_pairs, "test_mean_r": te_mean,
            })
            print(f"{name:<12} {entry:<8} {wf_str:<16} {prod_str:<22} "
                  f"{pair_str:<12} {te_str:<12}", flush=True)
    out_path = Path("/root/BlueHorseshoe/research/_v2_rerun/session_filter_results.csv")
    pd.DataFrame(rows).to_csv(out_path, index=False)
    print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    main()
