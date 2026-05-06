"""Build D1-filtered portfolio_trades CSVs for FTMO sizing sim input.

For each indicator/entry combo where the D1 filter expands coverage (per
MULTITF_FILTER_v1.md deployment table), run the full v2 pipeline with the D1
filter applied:
  1. Walk-forward across all pairs
  2. Spread test on walk-forward survivors
  3. Per-pair production cell selection (largest te_n)
  4. Collect trades for the production cells with filter applied
  5. Save to portfolio_trades_d1.csv

Output goes to research/_v2_rerun/<indicator>/portfolio_trades_d1{_entry}.csv
alongside the existing unfiltered portfolio_trades.csv files.
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

_STATE = {"d1_dir_per_bar": None}


def _compute_d1_dir(raw):
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


_orig_load = FxStore.load


def _patched_load(self, pair, **kwargs):
    raw = _orig_load(self, pair, **kwargs)
    if raw is not None and not raw.empty:
        _STATE["d1_dir_per_bar"] = _compute_d1_dir(raw)
    else:
        _STATE["d1_dir_per_bar"] = None
    return raw


FxStore.load = _patched_load


def _make_filter(orig, expected_dir, i_pos):
    def patched(*args, **kwargs):
        d1 = _STATE["d1_dir_per_bar"]
        if d1 is not None:
            i = args[i_pos]
            if 0 <= i < len(d1) and d1[i] != expected_dir:
                return None, None
        return orig(*args, **kwargs)
    return patched


_lib.sim_long_mid = _make_filter(_lib.sim_long_mid, "long", 3)
_lib.sim_short_mid = _make_filter(_lib.sim_short_mid, "short", 3)
_lib.sim_long_limit = _make_filter(_lib.sim_long_limit, "long", 3)
_lib.sim_short_limit = _make_filter(_lib.sim_short_limit, "short", 3)
_lib.sim_long_stop = _make_filter(_lib.sim_long_stop, "long", 3)
_lib.sim_short_stop = _make_filter(_lib.sim_short_stop, "short", 3)
_lib.sim_long_spread = _make_filter(_lib.sim_long_spread, "long", 4)
_lib.sim_short_spread = _make_filter(_lib.sim_short_spread, "short", 4)
_lib.sim_long_limit_spread = _make_filter(_lib.sim_long_limit_spread, "long", 5)
_lib.sim_short_limit_spread = _make_filter(_lib.sim_short_limit_spread, "short", 5)
_lib.sim_long_stop_spread = _make_filter(_lib.sim_long_stop_spread, "long", 6)
_lib.sim_short_stop_spread = _make_filter(_lib.sim_short_stop_spread, "short", 6)

import run_stoch_v2  # noqa: E402
import run_sma_v2  # noqa: E402
import run_ema_v2  # noqa: E402
import run_rsi_v2  # noqa: E402
import run_cci_v2  # noqa: E402
import run_macd_v2  # noqa: E402
import run_atr_v2  # noqa: E402

# Per MULTITF_FILTER_v1.md deployment table — only build filtered ledgers
# for combos where the filter expands coverage.
COMBOS = [
    ("stoch", run_stoch_v2,  "mid"),
    ("stoch", run_stoch_v2,  "limit"),
    ("sma",   run_sma_v2,    "mid"),
    ("ema",   run_ema_v2,    "mid"),
    ("rsi",   run_rsi_v2,    "mid"),
    ("cci",   run_cci_v2,    "mid"),
    ("cci",   run_cci_v2,    "limit"),
    ("macd",  run_macd_v2,   "limit"),
    ("atr",   run_atr_v2,    "mid"),
    ("atr",   run_atr_v2,    "limit"),
]


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
    raise ValueError(f"unknown module {name}")


def call_collect_trades(module, cell, entry_mode):
    name = module.__name__
    if name == "run_stoch_v2":
        return module.collect_trades(cell["pair"], int(cell["k_period"]), int(cell["d_period"]),
                                      int(cell["threshold"]), int(cell["recovery"]),
                                      cell["direction"], entry_mode=entry_mode)
    if name == "run_sma_v2":
        return module.collect_trades(cell["pair"], int(cell["period"]), float(cell["k"]),
                                      cell["direction"], entry_mode=entry_mode)
    if name == "run_ema_v2":
        return module.collect_trades(cell["pair"], int(cell["period"]), float(cell["k"]),
                                      cell["direction"], entry_mode=entry_mode)
    if name == "run_rsi_v2":
        return module.collect_trades(cell["pair"], int(cell["period"]),
                                      int(cell["threshold"]), int(cell["recovery"]),
                                      cell["direction"], entry_mode=entry_mode)
    if name == "run_cci_v2":
        return module.collect_trades(cell["pair"], int(cell["period"]),
                                      int(cell["threshold"]), int(cell["recovery"]),
                                      cell["direction"], entry_mode=entry_mode)
    if name == "run_macd_v2":
        return module.collect_trades(cell["pair"], int(cell["fast"]), int(cell["slow"]),
                                      int(cell["signal"]), cell["trigger"],
                                      cell["direction"], entry_mode=entry_mode)
    if name == "run_atr_v2":
        return module.collect_trades(cell["pair"], int(cell["atr_period"]), float(cell["k"]),
                                      cell["trigger"], cell["direction"],
                                      entry_mode=entry_mode)
    raise ValueError(f"unknown module {name}")


def build_one(indicator, module, entry_mode):
    print(f"\n=== {indicator} {entry_mode} ===", flush=True)
    out_dir = Path(f"/root/BlueHorseshoe/research/_v2_rerun/{indicator}")

    # 1. Walk-forward
    all_rows = []
    for pair in _lib.PAIRS_FULL:
        rows = module.walkforward_pair(pair, entry_mode=entry_mode)
        all_rows.extend(rows)
    wf_df = pd.DataFrame(all_rows)
    wf_survivors = _lib.survivor_gate_walkforward(wf_df)
    print(f"  walk-forward: {len(wf_survivors)}/{len(wf_df)}", flush=True)

    if wf_survivors.empty:
        print("  no survivors — skipping", flush=True)
        return

    # 2. Spread test
    spread_rows = []
    for _, r in wf_survivors.iterrows():
        out = call_spread_test(module, r, entry_mode)
        if out is not None:
            spread_rows.append(out)
    sp_df = pd.DataFrame(spread_rows)
    sp_survivors = _lib.survivor_gate_walkforward(sp_df)
    print(f"  spread-robust: {len(sp_survivors)}/{len(sp_df)}", flush=True)

    if sp_survivors.empty:
        print("  no spread-robust — skipping", flush=True)
        return

    # 3. Per-pair production cell selection (1 per pair, largest te_n)
    selected = []
    for pair, sub in sp_survivors.groupby("pair"):
        chosen = sub.sort_values(["te_n", "te_mean_r"], ascending=[False, False]).iloc[0]
        selected.append(chosen)
    print(f"  production cells (1 per pair): {len(selected)}", flush=True)

    # 4. Collect trades
    all_trades = []
    for cell in selected:
        trades = call_collect_trades(module, cell, entry_mode)
        all_trades.extend(trades)
    df_t = pd.DataFrame(all_trades)
    if df_t.empty:
        print("  no trades — skipping", flush=True)
        return
    df_t = df_t.sort_values("entry_ts").reset_index(drop=True)
    print(f"  total trades: {len(df_t)}", flush=True)

    # 5. Save
    suffix = "" if entry_mode == "mid" else f"_{entry_mode}"
    out_path = out_dir / f"portfolio_trades_d1{suffix}.csv"
    df_t.to_csv(out_path, index=False)
    print(f"  → {out_path}", flush=True)


def main():
    for indicator, module, entry_mode in COMBOS:
        build_one(indicator, module, entry_mode)


if __name__ == "__main__":
    main()
