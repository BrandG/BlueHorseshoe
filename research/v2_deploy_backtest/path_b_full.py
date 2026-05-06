"""Path B full: regenerate all 9 deployed-strategy ledgers with MAX_HOLD = 30 (5d).

Reuses the trick from path_b_fast.py — monkeypatch MAX_HOLD on each run_*_v2
module and call its collect_trades on the already-selected production cells.
This skips the parameter sweep (the long part of each script).

For bb, we use a different path because bb v2 lives in research/bb_execution_v1/
and uses its own MAX_HOLD constant; the bb script's collect_trades takes a
local-style helper, so we replicate the trade collection inline to avoid a
larger refactor of portfolio_bb_v2.py.

Output: research/v2_deploy_backtest/5day_ledgers/<strategy>_5d_<entry>.csv (one
per deployed strategy/entry-mode combination).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "_v2_rerun"))
sys.path.insert(0, str(REPO / "research" / "bb_execution_v1"))
sys.path.insert(0, str(REPO / "src"))

import run_atr_v2  # noqa: E402
import run_cci_v2  # noqa: E402
import run_ema_v2  # noqa: E402
import run_ichimoku_v2  # noqa: E402
import run_macd_v2  # noqa: E402
import run_rsi_v2  # noqa: E402
import run_sma_v2  # noqa: E402
import run_stoch_v2  # noqa: E402
from _lib import survivor_gate_walkforward, select_production_cells  # noqa: E402

OUT_DIR = REPO / "research" / "v2_deploy_backtest" / "5day_ledgers"
NEW_MAX_HOLD = 30
OLD_MAX_HOLD = 14 * 6
V2 = REPO / "research" / "_v2_rerun"

# Each strategy: (module, walkforward_spread.csv, cell_columns, entry_mode,
#                 args_from_row, orig_portfolio_csv)
STRATEGIES = [
    (run_macd_v2,
     V2 / "macd" / "walkforward_spread_limit.csv",
     ["pair", "fast", "slow", "signal", "trigger", "direction"],
     "limit",
     lambda s: (s["pair"], int(s["fast"]), int(s["slow"]),
                int(s["signal"]), s["trigger"], s["direction"]),
     V2 / "macd" / "portfolio_trades_limit.csv"),
    (run_atr_v2,
     V2 / "atr" / "walkforward_spread_limit.csv",
     ["pair", "atr_period", "k", "trigger", "direction"],
     "limit",
     lambda s: (s["pair"], int(s["atr_period"]), float(s["k"]),
                s["trigger"], s["direction"]),
     V2 / "atr" / "portfolio_trades_limit.csv"),
    (run_ichimoku_v2,
     V2 / "ichimoku" / "walkforward_spread_limit.csv",
     ["pair", "tenkan", "kijun", "senkou_b", "displacement", "trigger", "direction"],
     "limit",
     lambda s: (s["pair"], int(s["tenkan"]), int(s["kijun"]),
                int(s["senkou_b"]), int(s["displacement"]),
                s["trigger"], s["direction"]),
     V2 / "ichimoku" / "portfolio_trades_limit.csv"),
    (run_stoch_v2,
     V2 / "stoch" / "walkforward_spread.csv",
     ["pair", "k_period", "d_period", "threshold", "recovery", "direction"],
     "mid",
     lambda s: (s["pair"], int(s["k_period"]), int(s["d_period"]),
                int(s["threshold"]), int(s["recovery"]), s["direction"]),
     V2 / "stoch" / "portfolio_trades.csv"),
    (run_cci_v2,
     V2 / "cci" / "walkforward_spread.csv",
     ["pair", "period", "threshold", "recovery", "direction"],
     "mid",
     lambda s: (s["pair"], int(s["period"]), int(s["threshold"]),
                int(s["recovery"]), s["direction"]),
     V2 / "cci" / "portfolio_trades.csv"),
    (run_ema_v2,
     V2 / "ema" / "walkforward_spread.csv",
     ["pair", "period", "k", "direction"],
     "mid",
     lambda s: (s["pair"], int(s["period"]), float(s["k"]), s["direction"]),
     V2 / "ema" / "portfolio_trades.csv"),
    (run_sma_v2,
     V2 / "sma" / "walkforward_spread.csv",
     ["pair", "period", "k", "direction"],
     "mid",
     lambda s: (s["pair"], int(s["period"]), float(s["k"]), s["direction"]),
     V2 / "sma" / "portfolio_trades.csv"),
    (run_rsi_v2,
     V2 / "rsi" / "walkforward_spread.csv",
     ["pair", "period", "threshold", "recovery", "direction"],
     "mid",
     lambda s: (s["pair"], int(s["period"]), int(s["threshold"]),
                int(s["recovery"]), s["direction"]),
     V2 / "rsi" / "portfolio_trades.csv"),
]


def regen_v2(module, spread_csv, cell_columns, entry_mode, args_from_row):
    spread_df = pd.read_csv(spread_csv)
    robust = survivor_gate_walkforward(spread_df)
    if robust.empty:
        return pd.DataFrame()
    selected = select_production_cells(robust, cell_columns)

    module.MAX_HOLD = NEW_MAX_HOLD
    trades = []
    for s in selected:
        tr = module.collect_trades(*args_from_row(s), entry_mode=entry_mode)
        trades.extend(tr)
    module.MAX_HOLD = OLD_MAX_HOLD

    if not trades:
        return pd.DataFrame()
    return pd.DataFrame(trades).sort_values("entry_ts").reset_index(drop=True)


def regen_bb():
    """Replicate portfolio_bb_v2.collect_trades with MAX_HOLD=30."""
    from bh_ftmo.data.fx_store import FxStore
    from bh_ftmo.indicators import bollinger_bands, ohlc_mid
    import portfolio_bb_v2 as bb

    df = pd.read_csv(bb.SPREAD_CSV)
    robust = df[(df["variant"] == "A")
                & (df["tr_ci_low_r"] > 0.0) & (df["te_ci_low_r"] > 0.0)
                & (df["tr_n"] >= 50) & (df["te_n"] >= 30)].copy()
    selected = []
    for pair in sorted(robust["pair"].unique()):
        pair_cells = robust[robust["pair"] == pair].sort_values(
            ["te_n", "te_mean_r"], ascending=[False, False])
        selected.append(pair_cells.iloc[0])

    trades = []
    for s in selected:
        pair = s["pair"]
        period, std_, depth, direction = (int(s["period"]), float(s["std"]),
                                          float(s["depth"]), s["direction"])
        store = FxStore()
        raw = store.load(pair, granularity=bb.GRANULARITY, include_incomplete=False)
        if raw is None or raw.empty:
            continue
        mid = ohlc_mid(raw)
        m_close = mid["close"].to_numpy(dtype=float)
        bb_ = bollinger_bands(mid, period=period, n_std=std_)
        lower = bb_["lower"].to_numpy(dtype=float)
        upper = bb_["upper"].to_numpy(dtype=float)
        bw = upper - lower
        ts = raw["timestamp"].to_numpy()
        ca = raw["close_ask"].to_numpy(dtype=float)
        ha = raw["high_ask"].to_numpy(dtype=float)
        la = raw["low_ask"].to_numpy(dtype=float)
        cb = raw["close_bid"].to_numpy(dtype=float)
        hb = raw["high_bid"].to_numpy(dtype=float)
        lb = raw["low_bid"].to_numpy(dtype=float)
        if direction == "long":
            triggers = bb.find_fresh_long(m_close, lower, bw, depth)
        else:
            triggers = bb.find_fresh_short(m_close, upper, bw, depth)
        for i in triggers:
            i = int(i)
            if direction == "long":
                r, exit_idx = bb.sim_long_spread(ca, hb, lb, cb, i, NEW_MAX_HOLD)
            else:
                r, exit_idx = bb.sim_short_spread(cb, ha, la, ca, i, NEW_MAX_HOLD)
            if r is None:
                continue
            trades.append({"pair": pair,
                           "entry_ts": pd.Timestamp(ts[i]),
                           "exit_ts": pd.Timestamp(ts[exit_idx]),
                           "r": r})
    if not trades:
        return pd.DataFrame()
    return pd.DataFrame(trades).sort_values("entry_ts").reset_index(drop=True)


def stats(df):
    if df.empty:
        return None
    rs = df["r"].to_numpy()
    return {
        "n": len(rs),
        "mean_r": float(rs.mean()),
        "cum_r": float(rs.sum()),
        "wr": float((rs >= 1.0 - 1e-9).sum() / max(((rs >= 1.0) | (rs <= -1.0)).sum(), 1)),
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Path B FULL: regenerating 9 ledgers with MAX_HOLD = {NEW_MAX_HOLD} bars (5d)")
    print()
    summary = []

    # 8 v2 strategies
    for module, spread_csv, cell_cols, entry_mode, args_fn, orig_csv in STRATEGIES:
        strat = module.__name__.replace("run_", "").replace("_v2", "")
        print(f"[{strat}/{entry_mode}] regen ...", flush=True)
        new = regen_v2(module, spread_csv, cell_cols, entry_mode, args_fn)
        if new.empty:
            print(f"  empty result")
            continue
        out_path = OUT_DIR / f"{strat}_5d_{entry_mode}.csv"
        new[["pair", "entry_ts", "exit_ts", "r"]].to_csv(out_path, index=False)
        orig = pd.read_csv(orig_csv)
        s_new, s_old = stats(new), stats(orig)
        d_count = (s_new["n"] - s_old["n"]) / s_old["n"] * 100
        d_r = (s_new["mean_r"] - s_old["mean_r"]) / abs(s_old["mean_r"]) * 100
        d_cum = (s_new["cum_r"] - s_old["cum_r"]) / abs(s_old["cum_r"]) * 100
        print(f"  ORIG  n={s_old['n']:>5d}  mean_R={s_old['mean_r']:+.4f}  cum_R={s_old['cum_r']:+8.1f}")
        print(f"  NEW   n={s_new['n']:>5d}  mean_R={s_new['mean_r']:+.4f}  cum_R={s_new['cum_r']:+8.1f}")
        print(f"  Δ     count={d_count:+.1f}%  mean_R={d_r:+.1f}%  cum_R={d_cum:+.1f}%")
        summary.append((strat, entry_mode, s_old, s_new, d_count, d_r, d_cum))

    # bb
    print(f"[bb/mid] regen ...", flush=True)
    new = regen_bb()
    if not new.empty:
        out_path = OUT_DIR / "bb_5d_mid.csv"
        new[["pair", "entry_ts", "exit_ts", "r"]].to_csv(out_path, index=False)
        orig = pd.read_csv(REPO / "research" / "bb_execution_v1" / "portfolio_trades.csv")
        s_new, s_old = stats(new), stats(orig)
        d_count = (s_new["n"] - s_old["n"]) / s_old["n"] * 100
        d_r = (s_new["mean_r"] - s_old["mean_r"]) / abs(s_old["mean_r"]) * 100
        d_cum = (s_new["cum_r"] - s_old["cum_r"]) / abs(s_old["cum_r"]) * 100
        print(f"  ORIG  n={s_old['n']:>5d}  mean_R={s_old['mean_r']:+.4f}  cum_R={s_old['cum_r']:+8.1f}")
        print(f"  NEW   n={s_new['n']:>5d}  mean_R={s_new['mean_r']:+.4f}  cum_R={s_new['cum_r']:+8.1f}")
        print(f"  Δ     count={d_count:+.1f}%  mean_R={d_r:+.1f}%  cum_R={d_cum:+.1f}%")
        summary.append(("bb", "mid", s_old, s_new, d_count, d_r, d_cum))

    print()
    print("=== Summary ===")
    print(f"{'strategy':12s} {'entry':5s}  {'orig n':>7s}→{'new n':>7s}  Δct%  "
          f"{'orig R':>8s}→{'new R':>8s}  ΔR%   {'orig cum':>9s}→{'new cum':>9s}  Δcum%")
    print("-" * 100)
    for strat, em, so, sn, dc, dr, dcum in summary:
        print(f"{strat:12s} {em:5s}  {so['n']:>7d}→{sn['n']:>7d}  {dc:+5.1f}  "
              f"{so['mean_r']:>+8.4f}→{sn['mean_r']:>+8.4f}  {dr:+5.1f}  "
              f"{so['cum_r']:>+9.1f}→{sn['cum_r']:>+9.1f}  {dcum:+5.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
