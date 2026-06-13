"""Regenerate deployed v2 limit-cell ledgers through the restored harness.

This intentionally uses the archived strategy trigger code in ``harness/`` and
the live deployment cell list from ``bud.briefing``.  It is the regression gate
for the executable-fill analysis: with the archived fill rule, generated rows
must match the seed ledgers row-for-row on pair, entry_ts, exit_ts, and r.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().parent / "harness"
sys.path.insert(0, str(HARNESS))
sys.path.insert(0, str(ROOT / "src"))

from bud.briefing import CELLS  # noqa: E402
from run_atr_v2 import collect_trades as collect_atr  # noqa: E402
from run_ichimoku_v2 import collect_trades as collect_ichimoku  # noqa: E402
from run_macd_v2 import collect_trades as collect_macd  # noqa: E402

LIMIT_STEMS = {
    "atr": "atr_limit",
    "macd": "macd_limit",
    "ichimoku": "ichimoku_limit",
}


def _collect_cell(cell) -> list[dict]:
    p = cell.params
    if cell.strategy == "atr":
        return collect_atr(
            cell.pair,
            int(p["atr_period"]),
            float(p["k"]),
            p["trigger"],
            cell.direction,
            entry_mode="limit",
        )
    if cell.strategy == "macd":
        return collect_macd(
            cell.pair,
            int(p["fast"]),
            int(p["slow"]),
            int(p["signal"]),
            p["trigger"],
            cell.direction,
            entry_mode="limit",
        )
    if cell.strategy == "ichimoku":
        return collect_ichimoku(
            cell.pair,
            int(p["tenkan"]),
            int(p["kijun"]),
            int(p["senkou_b"]),
            int(p["displacement"]),
            p["trigger"],
            cell.direction,
            entry_mode="limit",
        )
    raise ValueError(f"unsupported limit strategy: {cell.strategy}")


def generate_ledgers(out_dir: Path) -> dict[str, pd.DataFrame]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ledgers: dict[str, pd.DataFrame] = {}
    for strategy, stem in LIMIT_STEMS.items():
        rows = []
        for cell in CELLS:
            if cell.strategy == strategy and cell.entry_mode == "limit":
                rows.extend(_collect_cell(cell))
        df = pd.DataFrame(rows, columns=["pair", "entry_ts", "exit_ts", "r"])
        df = df.sort_values(["entry_ts", "pair", "exit_ts", "r"]).reset_index(drop=True)
        df.to_csv(out_dir / f"{stem}.csv", index=False)
        ledgers[stem] = df
    return ledgers


def _canonical(df: pd.DataFrame) -> pd.DataFrame:
    out = df[["pair", "entry_ts", "exit_ts", "r"]].copy()
    out["entry_ts"] = pd.to_datetime(out["entry_ts"]).dt.tz_localize(None)
    out["exit_ts"] = pd.to_datetime(out["exit_ts"]).dt.tz_localize(None)
    out["r"] = out["r"].astype(float)
    return out.sort_values(["entry_ts", "pair", "exit_ts", "r"]).reset_index(drop=True)


def verify_against_seed(generated: dict[str, pd.DataFrame], seed_dir: Path) -> None:
    for stem, df in generated.items():
        expected = _canonical(pd.read_csv(seed_dir / f"{stem}.csv"))
        seed_max_entry = expected["entry_ts"].max()
        actual = _canonical(df)
        actual = actual[actual["entry_ts"] <= seed_max_entry].reset_index(drop=True)
        if len(actual) != len(expected):
            raise AssertionError(f"{stem}: row count mismatch generated={len(actual)} seed={len(expected)}")
        keys = ["pair", "entry_ts", "exit_ts"]
        mismatch = actual[keys].ne(expected[keys]).any(axis=1)
        r_mismatch = (actual["r"] - expected["r"]).abs() > 1e-10
        bad = mismatch | r_mismatch
        if bad.any():
            i = int(bad[bad].index[0])
            raise AssertionError(
                f"{stem}: first row mismatch at sorted row {i}: "
                f"generated={actual.iloc[i].to_dict()} seed={expected.iloc[i].to_dict()}"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--verify-seed-dir", type=Path)
    args = parser.parse_args()

    generated = generate_ledgers(args.out_dir)
    if args.verify_seed_dir:
        verify_against_seed(generated, args.verify_seed_dir)
        print("regression: generated limit ledgers match seed ledgers row-for-row")
    for stem, df in generated.items():
        print(f"{stem}: {len(df)} trades -> {args.out_dir / (stem + '.csv')}")


if __name__ == "__main__":
    main()
