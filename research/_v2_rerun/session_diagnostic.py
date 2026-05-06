"""Phase 1: Per-session expectancy diagnostic across all v2 portfolios.

For each existing portfolio_trades CSV:
  - Tag each trade with its session at entry_ts (ASIA, LONDON, OVERLAP, NY)
  - Split TRAIN/TEST at 70/30 by trade index (matches v2 methodology)
  - Compute per-session (n, mean_R, SE, CI) for TRAIN and TEST halves
  - Print a per-indicator session summary

This is diagnostic only — no v2 cell re-running. The goal is to identify which
sessions are systematically productive vs unproductive across indicators, so a
focused filter test can be designed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/src")
from bh_ftmo.indicators.sessions import session_label, Session


TRAIN_FRAC = 0.7
SESSIONS = [Session.ASIA, Session.LONDON, Session.OVERLAP, Session.NY]
ROOT = Path("/root/BlueHorseshoe/research/_v2_rerun")


def stats(rs):
    rs = np.asarray(rs, dtype=float)
    n = len(rs)
    if n == 0:
        return {"n": 0, "mean_r": float("nan"), "se": float("nan"),
                "ci_low": float("nan"), "ci_high": float("nan"),
                "wr": float("nan")}
    if n == 1:
        return {"n": 1, "mean_r": float(rs[0]), "se": float("nan"),
                "ci_low": float("nan"), "ci_high": float("nan"),
                "wr": 1.0 if rs[0] >= 1 - 1e-9 else (0.0 if rs[0] <= -1 + 1e-9 else float("nan"))}
    mean_r = float(rs.mean())
    se = float(rs.std(ddof=1) / np.sqrt(n))
    wins = int((rs >= 1.0 - 1e-9).sum())
    losses = int((rs <= -1.0 + 1e-9).sum())
    wr = wins / max(wins + losses, 1)
    return {"n": n, "mean_r": mean_r, "se": se,
            "ci_low": mean_r - 1.96 * se, "ci_high": mean_r + 1.96 * se, "wr": wr}


def analyze(csv_path):
    df = pd.read_csv(csv_path)
    if df.empty:
        return None
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df = df.sort_values("entry_ts").reset_index(drop=True)
    df["session"] = session_label(df["entry_ts"]).values

    cut = int(len(df) * TRAIN_FRAC)
    train = df.iloc[:cut]
    test = df.iloc[cut:]

    out = {}
    for half_name, half in (("train", train), ("test", test)):
        out[half_name] = {}
        for s in SESSIONS:
            rs = half[half["session"] == s.value]["r"].to_numpy()
            out[half_name][s.value] = stats(rs)
        out[half_name]["all"] = stats(half["r"].to_numpy())
    out["full_n"] = len(df)
    return out


def fmt(s):
    if s["n"] == 0:
        return f"  n=0"
    if np.isnan(s.get("ci_low", float("nan"))):
        return f"  n={s['n']:>4} mean_R={s['mean_r']:+.3f} (insufficient for CI)"
    return (f"  n={s['n']:>4} WR={s['wr']*100:>5.1f}% mean_R={s['mean_r']:+.3f} "
            f"CI=[{s['ci_low']:+.3f}, {s['ci_high']:+.3f}]")


def gate_pass(s):
    """v2 gate: tr_n>=50, te_n>=30, both CI low > 0."""
    return (s["n"] >= 30 and not np.isnan(s.get("ci_low", float("nan")))
            and s["ci_low"] > 0)


def main():
    portfolios = [
        ("BB v1 mid",         ROOT.parent / "bb_execution_v1" / "portfolio_trades.csv"),
        ("Stoch v2 mid",      ROOT / "stoch" / "portfolio_trades.csv"),
        ("Stoch v2 limit",    ROOT / "stoch" / "portfolio_trades_limit.csv"),
        ("WR v2 mid",         ROOT / "wr" / "portfolio_trades.csv"),
        ("WR v2 limit",       ROOT / "wr" / "portfolio_trades_limit.csv"),
        ("SMA v2 mid",        ROOT / "sma" / "portfolio_trades.csv"),
        ("SMA v2 limit",      ROOT / "sma" / "portfolio_trades_limit.csv"),
        ("EMA v2 mid",        ROOT / "ema" / "portfolio_trades.csv"),
        ("EMA v2 limit",      ROOT / "ema" / "portfolio_trades_limit.csv"),
        ("RSI v2 mid",        ROOT / "rsi" / "portfolio_trades.csv"),
        ("RSI v2 limit",      ROOT / "rsi" / "portfolio_trades_limit.csv"),
        ("CCI v2 mid",        ROOT / "cci" / "portfolio_trades.csv"),
        ("CCI v2 limit",      ROOT / "cci" / "portfolio_trades_limit.csv"),
        ("MACD limit",        ROOT / "macd" / "portfolio_trades_limit.csv"),
        ("MACD stop",         ROOT / "macd" / "portfolio_trades_stop.csv"),
        ("ATR mid",           ROOT / "atr" / "portfolio_trades.csv"),
        ("ATR limit",         ROOT / "atr" / "portfolio_trades_limit.csv"),
        ("ATR stop",          ROOT / "atr" / "portfolio_trades_stop.csv"),
        ("Candlestick mid",   ROOT / "candlestick" / "portfolio_trades.csv"),
        ("Ichimoku limit",    ROOT / "ichimoku" / "portfolio_trades_limit.csv"),
    ]

    # Cross-indicator session aggregate
    cross_test = {s.value: [] for s in SESSIONS}
    cross_train = {s.value: [] for s in SESSIONS}

    print("=" * 100)
    print(f"{'INDICATOR':<20} {'SESSION':<8} {'TRAIN':<55} {'TEST':<55}")
    print("=" * 100)
    for label, path in portfolios:
        if not path.exists():
            print(f"{label:<20} (missing CSV at {path})")
            continue
        out = analyze(path)
        if out is None:
            continue
        for s in SESSIONS:
            tr = out["train"][s.value]
            te = out["test"][s.value]
            tr_str = (f"n={tr['n']:>4} mean_R={tr['mean_r']:+.3f} "
                      f"CI=[{tr['ci_low']:+.3f},{tr['ci_high']:+.3f}]"
                      if tr["n"] >= 5 and not np.isnan(tr.get("ci_low", float("nan")))
                      else f"n={tr['n']}")
            te_str = (f"n={te['n']:>4} mean_R={te['mean_r']:+.3f} "
                      f"CI=[{te['ci_low']:+.3f},{te['ci_high']:+.3f}]"
                      if te["n"] >= 5 and not np.isnan(te.get("ci_low", float("nan")))
                      else f"n={te['n']}")
            gate = " ✓" if gate_pass(te) and gate_pass(tr) else "  "
            print(f"{label:<20} {s.value:<8}{gate} {tr_str:<55} {te_str:<55}")
            # accumulate for cross-indicator view (test halves only, weighted by R distribution)
            if te["n"] > 0:
                cross_test[s.value].append((label, te["mean_r"], te["n"]))
            if tr["n"] > 0:
                cross_train[s.value].append((label, tr["mean_r"], tr["n"]))
        all_te = out["test"]["all"]
        print(f"{'':<20} {'(all)':<8}   "
              f"n={out['train']['all']['n']:>4} mean_R={out['train']['all']['mean_r']:+.3f}".ljust(80)
              + f"  n={all_te['n']:>4} mean_R={all_te['mean_r']:+.3f}")
        print()

    print("=" * 100)
    print("CROSS-INDICATOR SESSION SUMMARY (test half)")
    print("=" * 100)
    print(f"{'SESSION':<10} {'TOTAL_N':<10} {'WEIGHTED_MEAN_R':<18} {'INDICATORS_POSITIVE / COUNT':<35}")
    for s in SESSIONS:
        items = cross_test[s.value]
        if not items:
            print(f"{s.value:<10} (no data)")
            continue
        total_n = sum(n for _, _, n in items)
        weighted = sum(m * n for _, m, n in items) / max(total_n, 1)
        positives = sum(1 for _, m, n in items if m > 0)
        print(f"{s.value:<10} {total_n:<10} {weighted:>+.3f}            {positives}/{len(items)}")


if __name__ == "__main__":
    main()
