"""Phase 1: Multi-timeframe (D1 trend alignment) diagnostic across v2 portfolios.

For each existing portfolio_trades CSV:
  - Load the source FX bars per pair
  - Aggregate to NY-daily OHLC
  - For each trade, look up D1 direction at entry_ts (D1 close vs D1 open OF THAT DAY)
  - Look up trade direction from spread-survivor metadata (per pair)
  - Tag each trade as "with-trend" or "counter-trend"
  - Compute per-(indicator, alignment) train/test mean_R

This is diagnostic only. Goal: see if D1 alignment correlates with per-trade R.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/src")
from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import ohlc_mid
from bh_ftmo.indicators.pivots import daily_ohlc


TRAIN_FRAC = 0.7
ROOT = Path("/root/BlueHorseshoe/research/_v2_rerun")


def load_pair_d1_direction(pair: str) -> pd.DataFrame:
    """Return DataFrame indexed by NY date with columns d1_open, d1_close."""
    store = FxStore()
    raw = store.load(pair, granularity="H4", include_incomplete=False)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["d1_open", "d1_close"])
    mid = ohlc_mid(raw)
    daily = daily_ohlc(mid, timestamps=raw["timestamp"])
    return daily[["open", "close"]].rename(columns={"open": "d1_open", "close": "d1_close"})


def get_pair_directions(spread_csv_path: Path) -> dict[str, str]:
    """From a spread test CSV, return {pair: direction} for cells passing the v2 gate.
    If a pair has multiple surviving cells with different directions, picks the
    direction with the largest aggregate te_n (matching select_production_cells's logic)."""
    if not spread_csv_path.exists():
        return {}
    df = pd.read_csv(spread_csv_path)
    if df.empty:
        return {}
    df = df[(df.tr_ci_low_r > 0) & (df.te_ci_low_r > 0)
            & (df.tr_n >= 50) & (df.te_n >= 30)]
    if df.empty:
        return {}
    out = {}
    for pair, sub in df.groupby("pair"):
        # Pick direction with largest aggregate te_n
        dir_n = sub.groupby("direction")["te_n"].sum()
        out[pair] = dir_n.idxmax()
    return out


def stats(rs):
    rs = np.asarray(rs, dtype=float)
    n = len(rs)
    if n == 0:
        return {"n": 0, "mean_r": float("nan"), "se": float("nan"),
                "ci_low": float("nan"), "wr": float("nan")}
    if n < 2:
        return {"n": n, "mean_r": float(rs[0]), "se": float("nan"),
                "ci_low": float("nan"), "wr": float("nan")}
    mean_r = float(rs.mean())
    se = float(rs.std(ddof=1) / np.sqrt(n))
    wins = int((rs >= 1.0 - 1e-9).sum())
    losses = int((rs <= -1.0 + 1e-9).sum())
    return {"n": n, "mean_r": mean_r, "se": se,
            "ci_low": mean_r - 1.96 * se,
            "wr": wins / max(wins + losses, 1)}


def analyze(portfolio_csv: Path, spread_csv: Path):
    df = pd.read_csv(portfolio_csv)
    if df.empty:
        return None
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df = df.sort_values("entry_ts").reset_index(drop=True)

    pair_dirs = get_pair_directions(spread_csv)

    # For each pair in df, load D1 direction series
    pairs = df["pair"].unique()
    d1_per_pair = {p: load_pair_d1_direction(p) for p in pairs}

    # Tag each trade
    rows = []
    for _, t in df.iterrows():
        pair = t["pair"]
        ts = t["entry_ts"]
        ny_date = ts.tz_localize("UTC").tz_convert("America/New_York").date() \
            if ts.tzinfo is None else ts.tz_convert("America/New_York").date()
        d1 = d1_per_pair.get(pair)
        if d1 is None or d1.empty or ny_date not in d1.index:
            continue
        d1_open = d1.loc[ny_date, "d1_open"]
        d1_close = d1.loc[ny_date, "d1_close"]
        d1_dir = "long" if d1_close > d1_open else ("short" if d1_close < d1_open else "flat")
        trade_dir = pair_dirs.get(pair, "?")
        if trade_dir == "?":
            continue
        if d1_dir == "flat":
            alignment = "flat"
        else:
            alignment = "with" if trade_dir == d1_dir else "counter"
        rows.append({"r": t["r"], "alignment": alignment, "pair": pair, "trade_dir": trade_dir})

    tagged = pd.DataFrame(rows)
    cut = int(len(tagged) * TRAIN_FRAC)
    train = tagged.iloc[:cut]
    test = tagged.iloc[cut:]

    out = {}
    for half_name, half in (("train", train), ("test", test)):
        out[half_name] = {}
        for align in ["with", "counter", "flat"]:
            rs = half[half["alignment"] == align]["r"].to_numpy()
            out[half_name][align] = stats(rs)
        out[half_name]["all"] = stats(half["r"].to_numpy())
    out["full_n"] = len(tagged)
    return out


def main():
    portfolios = [
        ("Stoch v2 mid",      ROOT / "stoch" / "portfolio_trades.csv",
                              ROOT / "stoch" / "walkforward_spread.csv"),
        ("Stoch v2 limit",    ROOT / "stoch" / "portfolio_trades_limit.csv",
                              ROOT / "stoch" / "walkforward_spread_limit.csv"),
        ("SMA v2 mid",        ROOT / "sma" / "portfolio_trades.csv",
                              ROOT / "sma" / "walkforward_spread.csv"),
        ("SMA v2 limit",      ROOT / "sma" / "portfolio_trades_limit.csv",
                              ROOT / "sma" / "walkforward_spread_limit.csv"),
        ("EMA v2 mid",        ROOT / "ema" / "portfolio_trades.csv",
                              ROOT / "ema" / "walkforward_spread.csv"),
        ("EMA v2 limit",      ROOT / "ema" / "portfolio_trades_limit.csv",
                              ROOT / "ema" / "walkforward_spread_limit.csv"),
        ("RSI v2 mid",        ROOT / "rsi" / "portfolio_trades.csv",
                              ROOT / "rsi" / "walkforward_spread.csv"),
        ("RSI v2 limit",      ROOT / "rsi" / "portfolio_trades_limit.csv",
                              ROOT / "rsi" / "walkforward_spread_limit.csv"),
        ("CCI v2 mid",        ROOT / "cci" / "portfolio_trades.csv",
                              ROOT / "cci" / "walkforward_spread.csv"),
        ("CCI v2 limit",      ROOT / "cci" / "portfolio_trades_limit.csv",
                              ROOT / "cci" / "walkforward_spread_limit.csv"),
        ("MACD limit",        ROOT / "macd" / "portfolio_trades_limit.csv",
                              ROOT / "macd" / "walkforward_spread_limit.csv"),
        ("ATR mid",           ROOT / "atr" / "portfolio_trades.csv",
                              ROOT / "atr" / "walkforward_spread.csv"),
        ("ATR limit",         ROOT / "atr" / "portfolio_trades_limit.csv",
                              ROOT / "atr" / "walkforward_spread_limit.csv"),
        ("Candlestick mid",   ROOT / "candlestick" / "portfolio_trades.csv",
                              ROOT / "candlestick" / "walkforward_spread.csv"),
        ("Ichimoku limit",    ROOT / "ichimoku" / "portfolio_trades_limit.csv",
                              ROOT / "ichimoku" / "walkforward_spread_limit.csv"),
    ]

    cross_test = {"with": [], "counter": []}

    print("=" * 110)
    print(f"{'INDICATOR':<20} {'TR_WITH':<28} {'TR_COUNTER':<28} {'TE_WITH':<28} {'TE_COUNTER':<28}")
    print("=" * 110)
    for label, ptrades, sspread in portfolios:
        if not ptrades.exists():
            print(f"{label:<20} (missing portfolio_trades)")
            continue
        out = analyze(ptrades, sspread)
        if out is None:
            print(f"{label:<20} (no analyzable trades)")
            continue
        tr_w = out["train"]["with"]
        tr_c = out["train"]["counter"]
        te_w = out["test"]["with"]
        te_c = out["test"]["counter"]
        def fmt(s):
            if s["n"] == 0:
                return "n=0"
            if s["n"] < 5 or np.isnan(s.get("ci_low", float("nan"))):
                return f"n={s['n']:>4} mean_R={s['mean_r']:+.3f}"
            return f"n={s['n']:>4} R={s['mean_r']:+.3f} CIlo={s['ci_low']:+.3f}"
        print(f"{label:<20} {fmt(tr_w):<28} {fmt(tr_c):<28} {fmt(te_w):<28} {fmt(te_c):<28}")
        # Test-half cross-indicator aggregation
        if te_w["n"] > 0:
            cross_test["with"].append((label, te_w["mean_r"], te_w["n"]))
        if te_c["n"] > 0:
            cross_test["counter"].append((label, te_c["mean_r"], te_c["n"]))

    print("=" * 110)
    print("CROSS-INDICATOR ALIGNMENT SUMMARY (test half)")
    print("=" * 110)
    for align in ["with", "counter"]:
        items = cross_test[align]
        if not items:
            print(f"{align}: (no data)")
            continue
        total_n = sum(n for _, _, n in items)
        weighted = sum(m * n for _, m, n in items) / max(total_n, 1)
        positives = sum(1 for _, m, _ in items if m > 0)
        print(f"  {align:<10} total_n={total_n:<8} weighted_mean_R={weighted:+.4f}  "
              f"positives={positives}/{len(items)}")


if __name__ == "__main__":
    main()
