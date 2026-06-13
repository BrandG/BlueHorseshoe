"""Compare archived mid-touch limit fills with executable bid/ask-touch fills."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bud.briefing import CELLS  # noqa: E402

BASE = Path(__file__).resolve().parent
SEED_LEDGER_DIR = BASE.parent / "v2_executable_regate_seed" / "ledgers"
EXEC_LEDGER_DIR = BASE / "ledgers_executable"
OUT_DIR = BASE / "results"
TRAIN_FRAC = 0.7

LEDGER_FILE = {
    "stoch": "stoch_mid",
    "bb": "bb_mid",
    "cci": "cci_mid",
    "ema": "ema_mid",
    "sma": "sma_mid",
    "rsi": "rsi_mid",
    "candle": "candlestick_mid",
    "macd": "macd_limit",
    "atr": "atr_limit",
    "ichimoku": "ichimoku_limit",
}


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


def overlap_lags(entry: np.ndarray, exit_: np.ndarray) -> tuple[int, int]:
    n = len(entry)
    if n < 2:
        return 0, 0
    counts = np.empty(n, dtype=int)
    for i in range(n):
        counts[i] = int(np.searchsorted(entry[i + 1:], exit_[i], side="left"))
    return int(np.ceil(np.percentile(counts, 95))), int(counts.max())


def stats(df: pd.DataFrame) -> dict:
    rs = df["r"].to_numpy(float)
    n = len(rs)
    out = {"n": n, "mean_r": np.nan, "nw_se": np.nan, "nw_lo": np.nan, "lag95": 0, "lagmax": 0}
    if n == 0:
        return out
    out["mean_r"] = float(rs.mean())
    if n < 2:
        return out
    lag95, lagmax = overlap_lags(
        df["entry_ts"].to_numpy("datetime64[ns]"),
        df["exit_ts"].to_numpy("datetime64[ns]"),
    )
    se = nw_se(rs, lag95)
    out.update({"nw_se": se, "nw_lo": out["mean_r"] - 1.96 * se, "lag95": lag95, "lagmax": lagmax})
    return out


def live_replicable(df: pd.DataFrame) -> pd.DataFrame:
    kept = []
    busy_by_pair: dict[str, pd.Timestamp] = {}
    for _, t in df.sort_values(["entry_ts", "pair"]).iterrows():
        busy = busy_by_pair.get(t.pair, pd.Timestamp.min)
        if t.entry_ts >= busy:
            kept.append(t)
            busy_by_pair[t.pair] = t.exit_ts
    return pd.DataFrame(kept)


def load_ledger(path: Path, *, strategy: str, entry_mode: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["entry_ts", "exit_ts"])
    df["strategy"] = strategy
    df["entry_mode"] = entry_mode
    return df


def load_book(limit_rule: str) -> dict[str, pd.DataFrame]:
    out = {}
    for strategy, stem in LEDGER_FILE.items():
        entry_mode = "limit" if stem.endswith("_limit") else "mid"
        ledger_dir = EXEC_LEDGER_DIR if entry_mode == "limit" and limit_rule == "executable" else SEED_LEDGER_DIR
        df = load_ledger(ledger_dir / f"{stem}.csv", strategy=strategy, entry_mode=entry_mode)
        out[strategy] = df
    return out


def cell_frame(books: dict[str, pd.DataFrame], limit_rule: str) -> pd.DataFrame:
    rows = []
    for cell in CELLS:
        df = books[cell.strategy]
        sub = df[df["pair"] == cell.pair].sort_values("entry_ts").reset_index(drop=True).copy()
        if cell.entry_mode == "limit" and limit_rule == "executable":
            seed = pd.read_csv(SEED_LEDGER_DIR / f"{LEDGER_FILE[cell.strategy]}.csv", parse_dates=["entry_ts", "exit_ts"])
            max_entry = seed["entry_ts"].max()
            sub = sub[sub["entry_ts"] <= max_entry].reset_index(drop=True)
        sub["direction"] = cell.direction
        sub["cell"] = f"{cell.strategy}:{cell.pair}:{cell.direction}:{cell.entry_mode}"
        rows.append(sub)
    return pd.concat(rows, ignore_index=True).sort_values(["entry_ts", "pair", "cell"]).reset_index(drop=True)


def assert_limit_subset(mid_limit: pd.DataFrame, exe_limit: pd.DataFrame) -> None:
    mid_keys = set(zip(mid_limit["strategy"], mid_limit["pair"], mid_limit["entry_ts"]))
    exe_keys = set(zip(exe_limit["strategy"], exe_limit["pair"], exe_limit["entry_ts"]))
    extra = exe_keys - mid_keys
    if extra:
        raise AssertionError(f"executable limit ledger has {len(extra)} entries not present in mid-touch ledger")
    if len(exe_keys) >= len(mid_keys):
        raise AssertionError("executable limit ledger is not a strict subset of mid-touch ledger")


def add_split_rows(rows: list[dict], label: str, df: pd.DataFrame, **meta) -> None:
    df = df.sort_values("entry_ts").reset_index(drop=True)
    cut = int(len(df) * TRAIN_FRAC)
    for half, sub in (("train", df.iloc[:cut]), ("test", df.iloc[cut:]), ("full", df)):
        row = {"label": label, "half": half}
        row.update(meta)
        row.update(stats(sub.reset_index(drop=True)))
        rows.append(row)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mid_book = load_book("mid_touch")
    exe_book = load_book("executable")
    mid_cells = cell_frame(mid_book, "mid_touch")
    exe_cells = cell_frame(exe_book, "executable")

    mid_limit = mid_cells[mid_cells["entry_mode"] == "limit"].copy()
    exe_limit = exe_cells[exe_cells["entry_mode"] == "limit"].copy()
    assert_limit_subset(mid_limit, exe_limit)

    ledger_dir = OUT_DIR / "ledgers_horizon"
    ledger_dir.mkdir(exist_ok=True)
    for stem in ("atr_limit", "macd_limit", "ichimoku_limit"):
        df = exe_limit[exe_limit["strategy"] == stem.replace("_limit", "")]
        df[["pair", "entry_ts", "exit_ts", "r"]].to_csv(ledger_dir / f"{stem}.csv", index=False)

    cell_rows = []
    for fill_rule, cells in (("mid_touch", mid_cells), ("executable", exe_cells)):
        for cell, sub in cells.groupby("cell", sort=True):
            if sub["entry_mode"].iloc[0] != "limit":
                continue
            add_split_rows(
                cell_rows,
                cell,
                sub,
                fill_rule=fill_rule,
                strategy=sub["strategy"].iloc[0],
                pair=sub["pair"].iloc[0],
                direction=sub["direction"].iloc[0],
            )
    pd.DataFrame(cell_rows).to_csv(OUT_DIR / "per_cell_limit_nw.csv", index=False)

    portfolio_rows = []
    for fill_rule, cells in (("mid_touch", mid_cells), ("executable", exe_cells)):
        for scope, sub in (("limit", cells[cells["entry_mode"] == "limit"]), ("combined", cells)):
            add_split_rows(portfolio_rows, scope, sub, fill_rule=fill_rule, pool="full_pool")
            add_split_rows(portfolio_rows, scope, live_replicable(sub), fill_rule=fill_rule, pool="live_replicable")
    portfolio = pd.DataFrame(portfolio_rows)
    portfolio.to_csv(OUT_DIR / "portfolio_nw.csv", index=False)

    comparison_rows = []
    for fill_rule, sub in (("mid_touch", mid_limit), ("executable", exe_limit)):
        for strategy, sdf in sub.groupby("strategy", sort=True):
            row = {"fill_rule": fill_rule, "scope": strategy}
            row.update(stats(sdf.sort_values("entry_ts").reset_index(drop=True)))
            comparison_rows.append(row)
        row = {"fill_rule": fill_rule, "scope": "limit_sleeve"}
        row.update(stats(sub.sort_values("entry_ts").reset_index(drop=True)))
        comparison_rows.append(row)
    comparison = pd.DataFrame(comparison_rows)
    comparison.to_csv(OUT_DIR / "midtouch_vs_executable_limit.csv", index=False)

    print("limit subset: executable entries are a strict subset of mid-touch entries")
    print(f"mid-touch limit trades: {len(mid_limit)}")
    print(f"executable limit trades: {len(exe_limit)}")
    print(f"drop: {(1.0 - len(exe_limit) / len(mid_limit)) * 100.0:.2f}%")
    key = portfolio[(portfolio["fill_rule"] == "executable")
                    & (portfolio["label"] == "combined")
                    & (portfolio["pool"] == "live_replicable")
                    & (portfolio["half"] == "full")].iloc[0]
    print(f"combined executable live-replicable full: n={int(key.n)} mean={key.mean_r:+.4f} nw_lo={key.nw_lo:+.4f}")


if __name__ == "__main__":
    main()
