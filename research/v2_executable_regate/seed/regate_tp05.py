"""Re-gate the 34 v2 production cells at the DEPLOYED geometry (TP=0.5%, stop=1%).

Fires are TP-invariant, so we reuse the archived spread ledgers' entry timestamps
(/tmp/nw_regate/ledgers/) and re-simulate only the exits against FxStore bid/ask
H4 bars, with the exact _lib.py sim conventions (stop checked before TP within a
bar; limit fills excluded from exit checks on the fill bar; timeout at close on
the opposite side; MAX_HOLD=84 bars).

Validation: re-simulating at TP=1% must reproduce the ledger's r values. Trades
that fail to match (data drift, ts not found) are reported and dropped from the
TP=0.5% analysis so the comparison stays apples-to-apples.

Outputs: /tmp/nw_regate/ledger_tp05.csv, /tmp/nw_regate/tp05_results.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/src")
from bud.briefing import CELLS  # noqa: E402
from bh_ftmo.data.fx_store import FxStore  # noqa: E402

LEDGER_DIR = Path("/tmp/nw_regate/ledgers")
OUT_DIR = Path("/tmp/nw_regate")
STOP_PCT = 0.01
MAX_HOLD = 14 * 6
TRAIN_FRAC = 0.7

LEDGER_FILE = {
    "stoch": "stoch_mid", "bb": "bb_mid", "cci": "cci_mid", "ema": "ema_mid",
    "sma": "sma_mid", "rsi": "rsi_mid", "candle": "candlestick_mid",
    "macd": "macd_limit", "atr": "atr_limit", "ichimoku": "ichimoku_limit",
}


def sim_exit(arr: dict, i_entry: int, entry: float, direction: str,
             tp_pct: float, *, is_limit: bool) -> tuple[float, int] | tuple[None, None]:
    """Walk exits from the bar after entry/fill. Mirrors _lib.py spread sims."""
    if direction == "long":
        tp = entry * (1 + tp_pct)
        stop = entry * (1 - STOP_PCT)
        risk = entry - stop
        lo, hi, tclose = arr["lb"], arr["hb"], arr["cb"]
    else:
        tp = entry * (1 - tp_pct)
        stop = entry * (1 + STOP_PCT)
        risk = stop - entry
        lo, hi, tclose = arr["la"], arr["ha"], arr["ca"]
    n = len(tclose)
    if i_entry + MAX_HOLD >= n:
        return None, None
    for j in range(1, MAX_HOLD + 1):
        k = i_entry + j
        if direction == "long":
            if lo[k] <= stop:
                return -1.0, k
            if hi[k] >= tp:
                return (tp - entry) / risk, k
        else:
            if hi[k] >= stop:
                return -1.0, k
            if lo[k] <= tp:
                return (entry - tp) / risk, k
    k = i_entry + MAX_HOLD
    if direction == "long":
        return (tclose[k] - entry) / risk, k
    return (entry - tclose[k]) / risk, k


def nw_se(rs: np.ndarray, lag: int) -> float:
    n = len(rs)
    if n < 2:
        return float("nan")
    d = rs - rs.mean()
    var = float(d @ d) / n
    lag = min(lag, n - 1)
    for l in range(1, lag + 1):
        var += 2.0 * (1.0 - l / (lag + 1.0)) * float(d[l:] @ d[:-l]) / n
    return float(np.sqrt(max(var, 0.0) / n))


def overlap_lag95(entry: np.ndarray, exit_: np.ndarray) -> int:
    n = len(entry)
    if n < 2:
        return 0
    counts = [int(np.searchsorted(entry[i + 1:], exit_[i], side="left"))
              for i in range(n)]
    return int(np.ceil(np.percentile(counts, 95)))


def half_stats(df: pd.DataFrame) -> dict:
    rs = df["r"].to_numpy(dtype=float)
    n = len(rs)
    out = {"n": n, "mean": np.nan, "iid_lo": np.nan, "nw_lo": np.nan, "lag95": 0}
    if n < 2:
        return out
    out["mean"] = float(rs.mean())
    iid = float(rs.std(ddof=1) / np.sqrt(n))
    out["iid_lo"] = out["mean"] - 1.96 * iid
    lag = overlap_lag95(df["entry_ts"].to_numpy("datetime64[ns]"),
                        df["exit_ts"].to_numpy("datetime64[ns]"))
    out["lag95"] = lag
    out["nw_lo"] = out["mean"] - 1.96 * nw_se(rs, lag)
    return out


def live_replicable(sub: pd.DataFrame) -> pd.DataFrame:
    kept, busy = [], pd.Timestamp.min
    for _, t in sub.iterrows():
        if t.entry_ts >= busy:
            kept.append(t)
            busy = t.exit_ts
    return pd.DataFrame(kept)


def main() -> None:
    ledgers = {s: pd.read_csv(LEDGER_DIR / f"{f}.csv",
                              parse_dates=["entry_ts", "exit_ts"])
               for s, f in LEDGER_FILE.items()}

    store = FxStore(read_only=True)
    bars: dict[str, dict] = {}
    try:
        for pair in sorted({c.pair for c in CELLS}):
            raw = store.load(pair, granularity="H4", include_incomplete=False)
            ts = pd.to_datetime(raw["timestamp"]).dt.tz_localize(None)
            bars[pair] = {
                "idx": {t: i for i, t in enumerate(ts)},
                "ts": ts.to_numpy(),
                "ca": raw["close_ask"].to_numpy(float),
                "cb": raw["close_bid"].to_numpy(float),
                "ha": raw["high_ask"].to_numpy(float),
                "hb": raw["high_bid"].to_numpy(float),
                "la": raw["low_ask"].to_numpy(float),
                "lb": raw["low_bid"].to_numpy(float),
            }
    finally:
        store.close()

    rows05 = []
    n_checked = n_match = n_missing = 0
    worst = 0.0
    for cell in CELLS:
        led = ledgers[cell.strategy]
        sub = (led[led["pair"] == cell.pair]
               .sort_values("entry_ts").reset_index(drop=True))
        arr = bars[cell.pair]
        for _, t in sub.iterrows():
            i = arr["idx"].get(t.entry_ts.tz_localize(None)
                               if t.entry_ts.tzinfo else t.entry_ts)
            if i is None:
                n_missing += 1
                continue
            if cell.entry_mode == "mid":
                entry = arr["ca"][i] if cell.direction == "long" else arr["cb"][i]
                i_anchor = i
            else:  # limit: ledger entry_ts = fill bar; limit set on signal bar i-1
                sig = i - 1
                entry = (arr["lb"][sig] if cell.direction == "long"
                         else arr["ha"][sig])
                i_anchor = i
            # validation at ledger geometry (TP=1%)
            r1, _ = sim_exit(arr, i_anchor, entry, cell.direction, 0.01,
                             is_limit=cell.entry_mode == "limit")
            n_checked += 1
            if r1 is not None and abs(r1 - t.r) < 1e-6:
                n_match += 1
            else:
                worst = max(worst, abs((r1 if r1 is not None else np.nan) - t.r))
                continue  # drop unverifiable trades from the tp05 set
            r05, k05 = sim_exit(arr, i_anchor, entry, cell.direction, 0.005,
                                is_limit=cell.entry_mode == "limit")
            if r05 is None:
                continue
            rows05.append({
                "strategy": cell.strategy, "pair": cell.pair,
                "direction": cell.direction, "entry_mode": cell.entry_mode,
                "entry_ts": t.entry_ts, "exit_ts": arr["ts"][k05], "r": r05,
            })

    print(f"validation: {n_match}/{n_checked} trades reproduce ledger r at TP=1% "
          f"(missing ts: {n_missing}, worst |dr| among drops: {worst:.4f})")
    df05 = pd.DataFrame(rows05)
    df05.to_csv(OUT_DIR / "ledger_tp05.csv", index=False)

    # ---- per-cell gates at TP=0.5% ----
    out = []
    for cell in CELLS:
        sub = (df05[(df05["strategy"] == cell.strategy)
                    & (df05["pair"] == cell.pair)]
               .sort_values("entry_ts").reset_index(drop=True))
        if sub.empty:
            continue
        cut = int(len(sub) * TRAIN_FRAC)
        tr, te = half_stats(sub.iloc[:cut]), half_stats(sub.iloc[cut:])
        lr = live_replicable(sub).reset_index(drop=True)
        lcut = int(len(lr) * TRAIN_FRAC)
        ltr, lte = half_stats(lr.iloc[:lcut]), half_stats(lr.iloc[lcut:])
        out.append({
            "strategy": cell.strategy, "pair": cell.pair,
            "direction": cell.direction, "entry_mode": cell.entry_mode,
            "tr_n": tr["n"], "te_n": te["n"],
            "tr_mean": tr["mean"], "te_mean": te["mean"],
            "tr_iid_lo": tr["iid_lo"], "te_iid_lo": te["iid_lo"],
            "tr_nw_lo": tr["nw_lo"], "te_nw_lo": te["nw_lo"],
            "lr_tr_lo": ltr["iid_lo"], "lr_te_lo": lte["iid_lo"],
            "iid_pass": (tr["iid_lo"] > 0 and te["iid_lo"] > 0
                         and tr["n"] >= 50 and te["n"] >= 30),
            "nw_pass": (tr["nw_lo"] > 0 and te["nw_lo"] > 0
                        and tr["n"] >= 50 and te["n"] >= 30),
            "te_nw_pass": te["nw_lo"] > 0,
        })
    res = pd.DataFrame(out)
    res.to_csv(OUT_DIR / "tp05_results.csv", index=False)
    with pd.option_context("display.float_format", "{:+.3f}".format,
                           "display.width", 200):
        print(res.to_string(index=False))
    print(f"\nTP=0.5%: iid gate passes {int(res['iid_pass'].sum())}/34 | "
          f"NW both halves {int(res['nw_pass'].sum())}/34 | "
          f"NW test-half {int(res['te_nw_pass'].sum())}/34")

    # ---- portfolio level, live-replicable pool ----
    print("\n== portfolio (live-replicable per pair), TP=0.5%/1% ==")
    for label, cells in (("ALL", CELLS),
                         ("mid", [c for c in CELLS if c.entry_mode == "mid"]),
                         ("limit", [c for c in CELLS if c.entry_mode == "limit"])):
        pool = []
        for cell in cells:
            sub = (df05[(df05["strategy"] == cell.strategy)
                        & (df05["pair"] == cell.pair)]
                   .sort_values("entry_ts"))
            if not sub.empty:
                pool.append(live_replicable(sub))
        p = pd.concat(pool).sort_values("entry_ts").reset_index(drop=True)
        cut = int(len(p) * TRAIN_FRAC)
        for hl, half in (("train", p.iloc[:cut]), ("test", p.iloc[cut:]),
                         ("full", p)):
            s = half_stats(half.reset_index(drop=True))
            print(f"  {label:<6} {hl:<6} n={s['n']:5d} mean={s['mean']:+.4f} "
                  f"iid_lo={s['iid_lo']:+.4f} NW_lo={s['nw_lo']:+.4f} "
                  f"(lag95={s['lag95']})")


if __name__ == "__main__":
    main()
