"""Commodity v2 indicator sweep over FxStore OANDA candles.

This mirrors the lightweight per-trade-R research harness in
``bh_ftmo.research.test_signal`` while adding:

- configured commodity universe loading
- bid/ask spread cost in R
- expected swap cost in R from OANDA financing snapshots
- Newey-West book-level SEs with lag = median hold - 1

The script is intentionally research-only. It does not touch live routing,
CELLS, or briefing code.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from bh_ftmo.backtest.swap_rates import fetch_oanda_financing_rates
from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.data.oanda_client import OandaClient, OandaError
from bh_ftmo.indicators import (
    atr,
    bollinger_bands,
    cci,
    donchian,
    ema,
    macd,
    ohlc_mid,
    rsi,
    sma,
    stochastic,
    supertrend,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "src" / "bh_ftmo_config.json"
OUT_DIR = REPO_ROOT / "research" / "commodities_v2"
COMPARISON_FOREX = ("EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD")


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    ftmo: str
    oanda: str
    instrument_type: str
    pip_size: float
    dollar_per_pip_per_lot: float


@dataclass(frozen=True)
class Cell:
    family: str
    cell: str
    timeframe: str
    entry_mode: str
    direction: int
    signal_fn: Callable[[pd.DataFrame], pd.Series]


def load_instruments() -> list[Instrument]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    out: list[Instrument] = []
    for item in payload.get("instruments", []):
        oanda = str(item.get("oanda", "")).strip()
        if not oanda:
            ftmo = str(item.get("ftmo", "")).replace(".sim", "").upper()
            oanda = f"{ftmo[:3]}_{ftmo[3:]}" if len(ftmo) == 6 else ""
        if not oanda:
            continue
        out.append(
            Instrument(
                symbol=oanda.upper(),
                name=str(item.get("name", oanda)),
                ftmo=str(item.get("ftmo", "")),
                oanda=oanda.upper(),
                instrument_type=str(item.get("type", "forex")),
                pip_size=float(item["pip_size"]),
                dollar_per_pip_per_lot=float(
                    item.get("dollar_per_pip_per_lot", float(item["pip_size"]) * 100_000)
                ),
            )
        )
    return out


def _load_mid(store: FxStore, symbol: str, granularity: str) -> pd.DataFrame:
    raw = store.load(symbol, granularity=granularity, include_incomplete=False)
    if raw is None or raw.empty:
        return pd.DataFrame()
    out = ohlc_mid(raw).copy()
    out["timestamp"] = pd.to_datetime(raw["timestamp"])
    out["spread"] = raw["close_ask"].astype(float) - raw["close_bid"].astype(float)
    return out.reset_index(drop=True)


def _resample_d1(h4: pd.DataFrame) -> pd.DataFrame:
    if h4.empty:
        return h4
    indexed = h4.set_index("timestamp")
    daily = pd.DataFrame(
        {
            "open": indexed["open"].resample("1D").first(),
            "high": indexed["high"].resample("1D").max(),
            "low": indexed["low"].resample("1D").min(),
            "close": indexed["close"].resample("1D").last(),
            "spread": indexed["spread"].resample("1D").median(),
        }
    ).dropna()
    daily["timestamp"] = daily.index
    return daily.reset_index(drop=True)


def _nw_se(values: np.ndarray, lag: int) -> float:
    values = values[np.isfinite(values)]
    n = len(values)
    if n < 2:
        return float("nan")
    demeaned = values - values.mean()
    gamma0 = float(np.dot(demeaned, demeaned) / n)
    variance = gamma0
    max_lag = min(max(lag, 0), n - 1)
    for k in range(1, max_lag + 1):
        gamma = float(np.dot(demeaned[k:], demeaned[:-k]) / n)
        variance += 2.0 * (1.0 - k / (max_lag + 1.0)) * gamma
    return math.sqrt(max(variance, 0.0) / n)


def _simulate_cell(
    instrument: Instrument,
    bars: pd.DataFrame,
    cell: Cell,
    swap_per_day_per_lot: float | None,
    *,
    stop_pct: float = 0.005,
    target_pct: float = 0.0075,
    max_hold_bars: int = 84,
) -> list[dict[str, object]]:
    if bars.empty:
        return []
    signals = cell.signal_fn(bars).fillna(False).astype(bool)
    direction = cell.direction
    trades: list[dict[str, object]] = []
    closes = bars["close"].to_numpy(dtype=float)
    highs = bars["high"].to_numpy(dtype=float)
    lows = bars["low"].to_numpy(dtype=float)
    spreads = bars["spread"].to_numpy(dtype=float)
    timestamps = bars["timestamp"].to_numpy()
    max_hold = min(max_hold_bars, max(1, len(bars) // 4))
    bars_per_day = 6.0 if cell.timeframe == "H4" else 1.0
    for i, fired in enumerate(signals.to_numpy()):
        if not fired or i + max_hold >= len(bars):
            continue
        entry = closes[i]
        if cell.entry_mode == "limit":
            offset = 0.25 * abs(entry * stop_pct)
            entry = entry - direction * offset
        stop = entry * (1.0 - direction * stop_pct)
        target = entry * (1.0 + direction * target_pct)
        exit_idx = i + max_hold
        exit_price = closes[exit_idx]
        outcome = "timeout"
        for j in range(1, max_hold + 1):
            k = i + j
            if direction > 0:
                if lows[k] <= stop:
                    exit_idx, exit_price, outcome = k, stop, "loss"
                    break
                if highs[k] >= target:
                    exit_idx, exit_price, outcome = k, target, "win"
                    break
            else:
                if highs[k] >= stop:
                    exit_idx, exit_price, outcome = k, stop, "loss"
                    break
                if lows[k] <= target:
                    exit_idx, exit_price, outcome = k, target, "win"
                    break
        risk_price = abs(entry - stop)
        gross_r = direction * (exit_price - entry) / risk_price
        spread_r = float(spreads[i] / risk_price)
        hold_bars = exit_idx - i
        lots_for_1r = 1.0 / ((risk_price / instrument.pip_size) * instrument.dollar_per_pip_per_lot)
        financing_missing = swap_per_day_per_lot is None
        swap_r = 0.0 if financing_missing else abs(swap_per_day_per_lot) * lots_for_1r * (hold_bars / bars_per_day)
        net_r = gross_r - spread_r - swap_r
        trades.append(
            {
                "instrument": instrument.symbol,
                "family": cell.family,
                "cell": cell.cell,
                "timeframe": cell.timeframe,
                "entry_mode": cell.entry_mode,
                "direction": direction,
                "entry_ts": pd.Timestamp(timestamps[i]).isoformat(),
                "exit_ts": pd.Timestamp(timestamps[exit_idx]).isoformat(),
                "outcome": outcome,
                "bars_held": hold_bars,
                "gross_r": gross_r,
                "spread_r": spread_r,
                "swap_r": swap_r,
                "financing_missing": financing_missing,
                "net_r": net_r,
            }
        )
    return trades


def build_cells() -> list[Cell]:
    cells: list[Cell] = []
    for entry_mode in ("market", "limit"):
        cells.extend(
            [
                Cell("mr_under_limit", "bb_p20_2", "H4", entry_mode, 1, lambda b: b["close"] < bollinger_bands(b, period=20, n_std=2.0)["lower"]),
                Cell("mr_under_limit", "rsi14_lt30", "H4", entry_mode, 1, lambda b: rsi(b, period=14) < 30),
                Cell("mr_under_limit", "stoch14_k20", "H4", entry_mode, 1, lambda b: stochastic(b, k_period=14, d_period=3)["k"] < 20),
                Cell("mr_under_limit", "cci20_lt-100", "H4", entry_mode, 1, lambda b: cci(b, period=20) < -100),
                Cell("mr_under_limit", "sma50_dist_low", "H4", entry_mode, 1, lambda b: (b["close"] / sma(b, period=50) - 1.0) < -0.01),
                Cell("mr_under_limit", "ema50_dist_low", "H4", entry_mode, 1, lambda b: (b["close"] / ema(b, period=50) - 1.0) < -0.01),
                Cell("mr_under_limit", "macd_hist_low", "H4", entry_mode, 1, lambda b: macd(b)["histogram"] < macd(b)["histogram"].rolling(100).quantile(0.1)),
                Cell("mr_under_limit", "atr_range_exp", "H4", entry_mode, 1, lambda b: (b["high"] - b["low"]) > 1.5 * atr(b, period=14)),
            ]
        )
        for timeframe in ("H4", "D1"):
            for direction in (1, -1):
                cells.extend(
                    [
                        Cell("trend", "donchian55", timeframe, entry_mode, direction, lambda b, d=direction: (b["close"] > donchian(b, period=55)["upper"].shift(1)) if d > 0 else (b["close"] < donchian(b, period=55)["lower"].shift(1))),
                        Cell("trend", "supertrend10x3", timeframe, entry_mode, direction, lambda b, d=direction: supertrend(b, period=10, multiplier=3.0)["direction"] == d),
                        Cell("trend", "tsmom63", timeframe, entry_mode, direction, lambda b, d=direction: (d * (b["close"] - b["close"].shift(63))) > 0),
                    ]
                )
    return cells


def summarize(trades: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if not trades:
        return [], []
    df = pd.DataFrame(trades)
    cell_rows: list[dict[str, object]] = []
    group_cols = ["instrument", "family", "cell", "timeframe", "entry_mode", "direction"]
    for keys, group in df.groupby(group_cols, dropna=False):
        rs = group["net_r"].to_numpy(dtype=float)
        hold = int(max(0, round(float(group["bars_held"].median())) - 1))
        se = _nw_se(rs, hold)
        mean = float(rs.mean())
        cell_rows.append(dict(zip(group_cols, keys)) | {
            "n": len(group),
            "mean_r": mean,
            "nw_lag": hold,
            "nw_se": se,
            "ci_low": mean - 1.96 * se if math.isfinite(se) else float("nan"),
            "ci_high": mean + 1.96 * se if math.isfinite(se) else float("nan"),
        })
    book_rows: list[dict[str, object]] = []
    for keys, group in df.groupby(["family", "timeframe", "entry_mode"], dropna=False):
        rs = group["net_r"].to_numpy(dtype=float)
        hold = int(max(0, round(float(group["bars_held"].median())) - 1))
        se = _nw_se(rs, hold)
        mean = float(rs.mean())
        book_rows.append({
            "family": keys[0],
            "timeframe": keys[1],
            "entry_mode": keys[2],
            "n": len(group),
            "mean_r": mean,
            "nw_lag": hold,
            "nw_se": se,
            "ci_low": mean - 1.96 * se if math.isfinite(se) else float("nan"),
            "ci_high": mean + 1.96 * se if math.isfinite(se) else float("nan"),
        })
    return cell_rows, book_rows


def write_csv(path: Path, rows: Iterable[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _median_spread_r(store: FxStore, symbol: str, *, stop_pct: float = 0.005) -> float:
    bars = _load_mid(store, symbol, "H4")
    if bars.empty:
        return float("nan")
    risk_price = bars["close"].astype(float) * stop_pct
    values = bars["spread"].astype(float) / risk_price.replace(0, np.nan)
    return float(values.median())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    instruments = load_instruments()
    commodities = [item for item in instruments if item.instrument_type == "commodity"]
    comparison = [item for item in instruments if item.symbol in COMPARISON_FOREX]
    rates = {}
    instrument_payload = {}
    try:
        with OandaClient() as client:
            instrument_payload = client.list_instruments()
            rates = fetch_oanda_financing_rates(client)
    except OandaError as exc:
        print(f"OANDA metadata unavailable: {exc}")

    cost_rows = []
    cost_store = FxStore(read_only=True)
    try:
        for item in [*comparison, *commodities]:
            present = item.symbol in instrument_payload if instrument_payload else False
            financing = rates.get(item.symbol)
            swap_abs = max(abs(financing.long_rate), abs(financing.short_rate)) if financing else float("nan")
            cost_rows.append({
                "instrument": item.symbol,
                "name": item.name,
                "type": item.instrument_type,
                "ftmo": item.ftmo,
                "oanda": item.oanda,
                "listed_for_financing": present,
                "financing_present": financing is not None,
                "pip_size": item.pip_size,
                "dollar_per_pip_per_lot": item.dollar_per_pip_per_lot,
                "median_h4_spread_r": _median_spread_r(cost_store, item.symbol),
                "expected_swap_per_lot_day_abs": swap_abs,
            })
    finally:
        cost_store.close()
    write_csv(
        OUT_DIR / "cost_model.csv",
        cost_rows,
        [
            "instrument", "name", "type", "ftmo", "oanda", "listed_for_financing",
            "financing_present", "pip_size", "dollar_per_pip_per_lot",
            "median_h4_spread_r", "expected_swap_per_lot_day_abs",
        ],
    )

    missing_listing = [item.symbol for item in commodities if item.symbol not in instrument_payload]
    if args.audit_only:
        print(f"Commodity instrument-list entries missing: {', '.join(missing_listing)}")
        write_csv(
            OUT_DIR / "per_cell_results.csv",
            [],
            ["instrument", "family", "cell", "timeframe", "entry_mode", "direction", "n", "mean_r", "nw_lag", "nw_se", "ci_low", "ci_high"],
        )
        write_csv(
            OUT_DIR / "book_summary.csv",
            [],
            ["family", "timeframe", "entry_mode", "n", "mean_r", "nw_lag", "nw_se", "ci_low", "ci_high"],
        )
        return 0

    store = FxStore(read_only=True)
    trades: list[dict[str, object]] = []
    try:
        cells = build_cells()
        for item in commodities:
            h4 = _load_mid(store, item.symbol, "H4")
            d1 = _resample_d1(h4)
            for cell in cells:
                bars = h4 if cell.timeframe == "H4" else d1
                financing = rates.get(item.symbol)
                swap = None if financing is None else max(abs(financing.long_rate), abs(financing.short_rate))
                trades.extend(_simulate_cell(item, bars, cell, swap))
    finally:
        store.close()
    cell_rows, book_rows = summarize(trades)
    write_csv(
        OUT_DIR / "per_cell_results.csv",
        cell_rows,
        ["instrument", "family", "cell", "timeframe", "entry_mode", "direction", "n", "mean_r", "nw_lag", "nw_se", "ci_low", "ci_high"],
    )
    write_csv(
        OUT_DIR / "book_summary.csv",
        book_rows,
        ["family", "timeframe", "entry_mode", "n", "mean_r", "nw_lag", "nw_se", "ci_low", "ci_high"],
    )
    print(f"wrote {len(trades)} trades at {datetime.now(UTC).isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
