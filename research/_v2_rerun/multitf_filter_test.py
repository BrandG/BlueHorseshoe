"""Phase 2: Cell-level v2 walk-forward with D1-trend alignment filter.

Drop trades where the H4 trigger direction disagrees with the daily-bar direction
at entry (D1 close > D1 open → bullish day; only longs allowed; mirror for short).

Mechanism: monkey-patch FxStore.load to precompute a per-H4-bar D1 direction
array, and patch the sim functions in _lib to return (None, None) if the trigger
bar's D1 direction doesn't match the trade direction. Patching happens BEFORE
runner imports so `from _lib import sim_*` binds to the patched versions.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/research/_v2_rerun")
sys.path.insert(0, "/root/BlueHorseshoe/src")

import _lib  # noqa: E402
from bh_ftmo.data.fx_store import FxStore  # noqa: E402
from bh_ftmo.indicators import ohlc_mid  # noqa: E402
from bh_ftmo.indicators.pivots import daily_ohlc  # noqa: E402

# Module state: set by patched FxStore.load, read by patched sim functions.
_STATE = {"d1_dir_per_bar": None}


def _compute_d1_dir(raw: pd.DataFrame):
    """Per-H4-bar D1 direction: 'long' if D1 close > D1 open that NY day,
    'short' if <, 'flat' if equal or daily missing."""
    mid = ohlc_mid(raw)
    daily = daily_ohlc(mid, timestamps=raw["timestamp"])
    ts = pd.to_datetime(raw["timestamp"])
    if ts.dt.tz is None:
        ts_ny = ts.dt.tz_localize("UTC").dt.tz_convert("America/New_York")
    else:
        ts_ny = ts.dt.tz_convert("America/New_York")
    ny_dates = ts_ny.dt.date.values
    out = []
    for d in ny_dates:
        if d in daily.index:
            o = daily.at[d, "open"]
            c = daily.at[d, "close"]
            out.append("long" if c > o else ("short" if c < o else "flat"))
        else:
            out.append("flat")
    return out


_orig_fxstore_load = FxStore.load


def _patched_fxstore_load(self, pair, **kwargs):
    raw = _orig_fxstore_load(self, pair, **kwargs)
    if raw is not None and not raw.empty:
        _STATE["d1_dir_per_bar"] = _compute_d1_dir(raw)
    else:
        _STATE["d1_dir_per_bar"] = None
    return raw


FxStore.load = _patched_fxstore_load


def _make_filter(orig, expected_dir, i_pos):
    """Wrap a sim function to drop trades whose D1 direction doesn't match."""
    def patched(*args, **kwargs):
        d1 = _STATE["d1_dir_per_bar"]
        if d1 is not None:
            i = args[i_pos]
            if 0 <= i < len(d1) and d1[i] != expected_dir:
                return None, None
        return orig(*args, **kwargs)
    return patched


# Mid sims: (close, high, low, i, max_hold) — i at index 3
_lib.sim_long_mid = _make_filter(_lib.sim_long_mid, "long", 3)
_lib.sim_short_mid = _make_filter(_lib.sim_short_mid, "short", 3)
# Limit sims: (close, high, low, i, max_hold, fill_window=) — i at 3
_lib.sim_long_limit = _make_filter(_lib.sim_long_limit, "long", 3)
_lib.sim_short_limit = _make_filter(_lib.sim_short_limit, "short", 3)
# Stop sims: (close, high, low, i, max_hold, fill_window=) — i at 3
_lib.sim_long_stop = _make_filter(_lib.sim_long_stop, "long", 3)
_lib.sim_short_stop = _make_filter(_lib.sim_short_stop, "short", 3)
# Spread sims: (ca, hb, lb, cb, i, max_hold) — i at 4
_lib.sim_long_spread = _make_filter(_lib.sim_long_spread, "long", 4)
_lib.sim_short_spread = _make_filter(_lib.sim_short_spread, "short", 4)
# Limit-spread: (ca, hb, lb, cb, lb_signal, i, max_hold, fill_window=) — i at 5
_lib.sim_long_limit_spread = _make_filter(_lib.sim_long_limit_spread, "long", 5)
_lib.sim_short_limit_spread = _make_filter(_lib.sim_short_limit_spread, "short", 5)
# Stop-spread: (ca, hb, lb, cb, ha, ha_signal, i, max_hold, fill_window=) — i at 6
_lib.sim_long_stop_spread = _make_filter(_lib.sim_long_stop_spread, "long", 6)
_lib.sim_short_stop_spread = _make_filter(_lib.sim_short_stop_spread, "short", 6)

# Now import runners — they pick up the patched sim functions.
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
    ("macd",      run_macd_v2,      ["limit"]),
    ("atr",       run_atr_v2,       ["mid", "limit"]),
    ("ichimoku",  run_ichimoku_v2,  ["limit"]),
]

# Baselines (unfiltered): (n_cells, wf_survivors, prod_pairs)
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


def call_spread_test(module, r, entry_mode):
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


def run_filter_test(module, entry_mode):
    all_rows = []
    for pair in _lib.PAIRS_FULL:
        rows = module.walkforward_pair(pair, entry_mode=entry_mode)
        all_rows.extend(rows)
    wf_df = pd.DataFrame(all_rows)
    wf_survivors = _lib.survivor_gate_walkforward(wf_df)

    spread_rows = []
    for _, r in wf_survivors.iterrows():
        out = call_spread_test(module, r, entry_mode)
        if out is not None:
            spread_rows.append(out)
    sp_df = pd.DataFrame(spread_rows)
    sp_survivors = _lib.survivor_gate_walkforward(sp_df) if not sp_df.empty else sp_df
    n_unique_pairs = sp_survivors["pair"].nunique() if (not sp_survivors.empty and "pair" in sp_survivors) else 0
    test_mean_r = sp_survivors["te_mean_r"].mean() if not sp_survivors.empty else float("nan")
    return len(wf_df), len(wf_survivors), len(sp_survivors), n_unique_pairs, test_mean_r


def main():
    print("=" * 100)
    print("PHASE 2 — D1 ALIGNMENT FILTER TEST (cell-level v2 walk-forward)")
    print("=" * 100)
    print(f"{'INDICATOR':<12} {'ENTRY':<8} {'WF_BASE→FILT':<16} "
          f"{'PROD_CELLS':<22} {'UNIQ_PAIRS':<14} {'TEST_MEAN_R':<12}")
    print("-" * 100)
    rows = []
    for name, module, entry_modes in INDICATORS:
        for entry in entry_modes:
            n_cells, n_wf, n_prod, n_pairs, te_mean = run_filter_test(module, entry)
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
                  f"{pair_str:<14} {te_str:<12}", flush=True)
    out_path = Path("/root/BlueHorseshoe/research/_v2_rerun/multitf_filter_results.csv")
    pd.DataFrame(rows).to_csv(out_path, index=False)
    print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    main()
