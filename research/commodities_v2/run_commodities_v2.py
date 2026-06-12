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
from bh_ftmo.data.validate import IssueKind, validate_stored
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
REGATE_DIR = OUT_DIR / "regate"
COMPARISON_FOREX = ("EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD")
STOP_PCT = 0.01
TARGET_PCT = 0.01
MAX_HOLD_BARS = 84
LIMIT_OFFSET_STOP_MULT = 0.25
FINANCING_DRAG_PCT_PER_DAY = (0.00005, 0.0001, 0.0002)


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
    stop_pct: float = STOP_PCT,
    target_pct: float = TARGET_PCT,
    max_hold_bars: int = MAX_HOLD_BARS,
    financing_drag_pct_per_day: float = 0.0,
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
            offset = LIMIT_OFFSET_STOP_MULT * abs(entry * stop_pct)
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
        hold_days = hold_bars / bars_per_day
        if financing_missing:
            notional_per_lot = entry * (instrument.dollar_per_pip_per_lot / instrument.pip_size)
            swap_r = max(financing_drag_pct_per_day, 0.0) * notional_per_lot * lots_for_1r * hold_days if direction > 0 else 0.0
            long_notional_r_days = notional_per_lot * lots_for_1r * hold_days if direction > 0 else 0.0
        else:
            swap_r = abs(swap_per_day_per_lot) * lots_for_1r * hold_days
            long_notional_r_days = 0.0
        net_r = gross_r - spread_r - swap_r
        # Memory: only the fields consumed by the summaries are kept. The
        # full ~1.15M-trade run (signal + every-bar baselines) OOM-killed the
        # 7.8GB box with the original 19-field dicts.
        trades.append(
            {
                "instrument": instrument.symbol,
                "family": cell.family,
                "cell": cell.cell,
                "timeframe": cell.timeframe,
                "entry_mode": cell.entry_mode,
                "direction": direction,
                "bars_held": hold_bars,
                "long_notional_r_days": long_notional_r_days,
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


def build_baseline_cells() -> list[Cell]:
    cells: list[Cell] = []
    for timeframe in ("H4", "D1"):
        for entry_mode in ("market", "limit"):
            for direction in (1, -1):
                cells.append(
                    Cell(
                        "baseline",
                        "always_in",
                        timeframe,
                        entry_mode,
                        direction,
                        lambda b: pd.Series(True, index=b.index),
                    )
                )
    return cells


def _bootstrap_excess_ci(signal: np.ndarray, baseline: np.ndarray, block_len: int, *, reps: int = 200) -> tuple[float, float, float]:
    signal = signal[np.isfinite(signal)]
    baseline = baseline[np.isfinite(baseline)]
    if len(signal) < 2 or len(baseline) < 2:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(20260612)
    block_len = max(1, min(block_len, len(signal), len(baseline)))

    def sample_means(values: np.ndarray) -> np.ndarray:
        # Circular moving-block bootstrap, vectorized: one (reps, n_blocks,
        # block_len) index tensor instead of a Python loop per draw.
        n = len(values)
        n_blocks = math.ceil(n / block_len)
        starts = rng.integers(0, n, size=(reps, n_blocks))
        idx = (starts[:, :, None] + np.arange(block_len)[None, None, :]) % n
        return values[idx.reshape(reps, -1)[:, :n]].mean(axis=1)

    draws = sample_means(signal) - sample_means(baseline)
    return float(draws.std(ddof=1)), float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))


def _summarize_groups(df: pd.DataFrame, group_cols: list[str]) -> list[dict[str, object]]:
    cell_rows: list[dict[str, object]] = []
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
    return cell_rows


def summarize_with_baselines(
    trades: "pd.DataFrame | list[dict[str, object]]",
    baseline_trades: "pd.DataFrame | list[dict[str, object]]",
    *,
    bootstrap_excess: bool = True,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    df = trades if isinstance(trades, pd.DataFrame) else pd.DataFrame(trades)
    baseline_df = baseline_trades if isinstance(baseline_trades, pd.DataFrame) else pd.DataFrame(baseline_trades)
    if df.empty:
        return [], [], []
    group_cols = ["instrument", "family", "cell", "timeframe", "entry_mode", "direction"]
    cell_rows = _summarize_groups(df, group_cols)
    baseline_rows = _summarize_groups(baseline_df, ["instrument", "timeframe", "entry_mode", "direction"])

    baseline_map = {
        (row["instrument"], row["timeframe"], row["entry_mode"], row["direction"]): row
        for row in baseline_rows
    }
    baseline_values = {
        key: group["net_r"].to_numpy(dtype=float)
        for key, group in baseline_df.groupby(["instrument", "timeframe", "entry_mode", "direction"], dropna=False)
    }
    baseline_drag = {
        key: float(group["long_notional_r_days"].mean())
        for key, group in baseline_df.groupby(["instrument", "timeframe", "entry_mode", "direction"], dropna=False)
    }
    signal_values = {
        key: group["net_r"].to_numpy(dtype=float)
        for key, group in df.groupby(group_cols, dropna=False)
    }
    signal_drag = {
        key: float(group["long_notional_r_days"].mean())
        for key, group in df.groupby(group_cols, dropna=False)
    }

    for row in cell_rows:
        base_key = (row["instrument"], row["timeframe"], row["entry_mode"], row["direction"])
        signal_key = (row["instrument"], row["family"], row["cell"], row["timeframe"], row["entry_mode"], row["direction"])
        base = baseline_map.get(base_key, {})
        baseline_mean = float(base.get("mean_r", float("nan")))
        row["baseline_n"] = base.get("n", 0)
        row["baseline_mean_r"] = baseline_mean
        row["excess_r"] = float(row["mean_r"]) - baseline_mean
        drag_delta = signal_drag.get(signal_key, 0.0) - baseline_drag.get(base_key, 0.0)
        row["drag_pct_per_day_to_zero_excess"] = float(row["excess_r"]) / drag_delta if drag_delta > 0 and float(row["excess_r"]) > 0 else float("nan")
        block_len = int(row["nw_lag"]) if int(row["nw_lag"]) > 0 else 1
        if bootstrap_excess:
            se, ci_low, ci_high = _bootstrap_excess_ci(signal_values[signal_key], baseline_values.get(base_key, np.array([])), block_len)
        else:
            se, ci_low, ci_high = float("nan"), float("nan"), float("nan")
        row["excess_block_len"] = block_len
        row["excess_boot_se"] = se
        row["excess_ci_low"] = ci_low
        row["excess_ci_high"] = ci_high

    book_rows = _summarize_groups(df, ["instrument", "family", "timeframe", "entry_mode"])
    for row in book_rows:
        baselines = [
            baseline_map.get((row["instrument"], row["timeframe"], row["entry_mode"], direction), {})
            for direction in (1, -1)
        ]
        means = [float(base["mean_r"]) for base in baselines if "mean_r" in base]
        row["matched_baseline_mean_r"] = float(np.mean(means)) if means else float("nan")
        row["raw_minus_avg_direction_baseline_r"] = float(row["mean_r"]) - row["matched_baseline_mean_r"]

    return cell_rows, baseline_rows, book_rows


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


def _session_profile(store: FxStore, instrument: Instrument) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for granularity in ("H4", "H1"):
        raw = store.load(instrument.symbol, granularity=granularity, include_incomplete=False)
        if raw.empty:
            rows.append({
                "instrument": instrument.symbol,
                "granularity": granularity,
                "row_count": 0,
                "min_timestamp": "",
                "max_timestamp": "",
                "weekday_hour_pattern_utc": "",
            })
            continue
        ts = pd.to_datetime(raw["timestamp"])
        by_weekday: dict[int, list[int]] = {}
        for weekday, group in ts.groupby(ts.dt.weekday):
            by_weekday[int(weekday)] = sorted(int(hour) for hour in group.dt.hour.unique())
        pattern = "; ".join(f"{weekday}:{','.join(str(hour).zfill(2) for hour in hours)}" for weekday, hours in sorted(by_weekday.items()))
        rows.append({
            "instrument": instrument.symbol,
            "granularity": granularity,
            "row_count": len(raw),
            "min_timestamp": ts.min().isoformat(),
            "max_timestamp": ts.max().isoformat(),
            "weekday_hour_pattern_utc": pattern,
        })
    return rows


def _validation_rows(store: FxStore, instrument: Instrument) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for granularity in ("H4", "H1"):
        cov = store.coverage(granularity=granularity).get(instrument.symbol)
        if cov is None or cov.min_timestamp is None or cov.max_timestamp is None:
            rows.append({
                "instrument": instrument.symbol,
                "granularity": granularity,
                "start": "",
                "end": "",
                "issue_kind": "missing_all",
                "issue_count": 1,
                "first_issue_ts": "",
                "last_issue_ts": "",
                "overlaps_sweep_window": True,
            })
            continue
        end = cov.max_timestamp + pd.Timedelta(hours=4 if granularity == "H4" else 1)
        issues = validate_stored(
            store,
            symbol=instrument.symbol,
            granularity=granularity,  # type: ignore[arg-type]
            start=cov.min_timestamp,
            end=end.to_pydatetime() if isinstance(end, pd.Timestamp) else end,
            instrument_type="commodity",
            include_holiday_gaps=True,
        )
        if not issues:
            rows.append({
                "instrument": instrument.symbol,
                "granularity": granularity,
                "start": cov.min_timestamp.isoformat(),
                "end": cov.max_timestamp.isoformat(),
                "issue_kind": "clean",
                "issue_count": 0,
                "first_issue_ts": "",
                "last_issue_ts": "",
                "overlaps_sweep_window": False,
            })
            continue
        for kind in sorted({issue.kind for issue in issues}, key=lambda item: item.value):
            subset = [issue for issue in issues if issue.kind == kind]
            timestamps = [issue.timestamp for issue in subset if issue.timestamp is not None]
            rows.append({
                "instrument": instrument.symbol,
                "granularity": granularity,
                "start": cov.min_timestamp.isoformat(),
                "end": cov.max_timestamp.isoformat(),
                "issue_kind": kind.value,
                "issue_count": len(subset),
                "first_issue_ts": min(timestamps).isoformat() if timestamps else "",
                "last_issue_ts": max(timestamps).isoformat() if timestamps else "",
                "overlaps_sweep_window": kind == IssueKind.DATA_GAP,
            })
    return rows


def _with_financing_drag(df: pd.DataFrame, drag: float) -> pd.DataFrame:
    # Column-level adjustment; the original per-dict copy tripled the full
    # trade set in memory and OOM-killed the first run of this script.
    return df.assign(net_r=df["net_r"] - drag * df["long_notional_r_days"])


def _financing_sensitivity(
    trades: pd.DataFrame,
    baseline_trades: pd.DataFrame,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for drag in FINANCING_DRAG_PCT_PER_DAY:
        cell_rows, _, _ = summarize_with_baselines(
            _with_financing_drag(trades, drag),
            _with_financing_drag(baseline_trades, drag),
            bootstrap_excess=False,
        )
        for row in cell_rows:
            if float(row["excess_r"]) > 0:
                rows.append({
                    "drag_pct_per_day": drag,
                    "drag_bp_per_day": drag * 10_000.0,
                    "instrument": row["instrument"],
                    "family": row["family"],
                    "cell": row["cell"],
                    "timeframe": row["timeframe"],
                    "entry_mode": row["entry_mode"],
                    "direction": row["direction"],
                    "n": row["n"],
                    "mean_r": row["mean_r"],
                    "baseline_mean_r": row["baseline_mean_r"],
                    "excess_r": row["excess_r"],
                    "drag_pct_per_day_to_zero_excess": row["drag_pct_per_day_to_zero_excess"],
                    "excess_ci_low": row["excess_ci_low"],
                    "excess_ci_high": row["excess_ci_high"],
                })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=REGATE_DIR)
    parser.add_argument("--skip-financing-sensitivity", action="store_true")
    args = parser.parse_args()
    out_dir = args.out_dir
    instruments = load_instruments()
    commodities = [item for item in instruments if item.instrument_type == "commodity"]
    comparison = [item for item in instruments if item.symbol in COMPARISON_FOREX]
    rates = {}
    instrument_payload = {}
    explicit_commodity_payload = {}
    try:
        with OandaClient() as client:
            instrument_payload = client.list_instruments()
            try:
                explicit_commodity_payload = client.list_instruments([item.symbol for item in commodities])
            except OandaError as exc:
                # Practice accounts reject the explicit commodity query with
                # INSTRUMENT_NOT_TRADEABLE — the account serves candles but
                # cannot trade these CFDs. Keep forex financing alive.
                print(f"explicit commodity instrument query failed: {exc}")
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
                "listed_with_explicit_query": item.symbol in explicit_commodity_payload,
                "financing_present": financing is not None,
                "pip_size": item.pip_size,
                "dollar_per_pip_per_lot": item.dollar_per_pip_per_lot,
                "median_h4_spread_r": _median_spread_r(cost_store, item.symbol, stop_pct=STOP_PCT),
                "expected_swap_per_lot_day_abs": swap_abs,
            })
    finally:
        cost_store.close()
    write_csv(
        out_dir / "cost_model.csv",
        cost_rows,
        [
            "instrument", "name", "type", "ftmo", "oanda", "listed_for_financing",
            "listed_with_explicit_query", "financing_present", "pip_size", "dollar_per_pip_per_lot",
            "median_h4_spread_r", "expected_swap_per_lot_day_abs",
        ],
    )

    missing_listing = [item.symbol for item in commodities if item.symbol not in instrument_payload]
    if args.audit_only:
        print(f"Commodity instrument-list entries missing: {', '.join(missing_listing)}")
        write_csv(
            out_dir / "per_cell_results.csv",
            [],
            ["instrument", "family", "cell", "timeframe", "entry_mode", "direction", "n", "mean_r", "nw_lag", "nw_se", "ci_low", "ci_high", "baseline_n", "baseline_mean_r", "excess_r", "drag_pct_per_day_to_zero_excess", "excess_block_len", "excess_boot_se", "excess_ci_low", "excess_ci_high"],
        )
        write_csv(
            out_dir / "book_summary.csv",
            [],
            ["instrument", "family", "timeframe", "entry_mode", "n", "mean_r", "nw_lag", "nw_se", "ci_low", "ci_high", "matched_baseline_mean_r", "raw_minus_avg_direction_baseline_r"],
        )
        return 0

    store = FxStore(read_only=True)
    trades: list[dict[str, object]] = []
    baseline_trades: list[dict[str, object]] = []
    session_rows: list[dict[str, object]] = []
    validation_rows: list[dict[str, object]] = []
    sensitivity_rows: list[dict[str, object]] = []
    signal_frames: list[pd.DataFrame] = []
    baseline_frames: list[pd.DataFrame] = []
    try:
        cells = build_cells()
        baseline_cells = build_baseline_cells()
        for item in commodities:
            session_rows.extend(_session_profile(store, item))
            validation_rows.extend(_validation_rows(store, item))
            h4 = _load_mid(store, item.symbol, "H4")
            d1 = _resample_d1(h4)
            for cell in cells:
                bars = h4 if cell.timeframe == "H4" else d1
                financing = rates.get(item.symbol)
                swap = None if financing is None else max(abs(financing.long_rate), abs(financing.short_rate))
                trades.extend(_simulate_cell(item, bars, cell, swap))
            for cell in baseline_cells:
                bars = h4 if cell.timeframe == "H4" else d1
                financing = rates.get(item.symbol)
                swap = None if financing is None else max(abs(financing.long_rate), abs(financing.short_rate))
                baseline_trades.extend(_simulate_cell(item, bars, cell, swap))
            # Compact per-instrument: a DataFrame is ~10x smaller than the
            # equivalent list of dicts, and this run holds ~1.15M trades.
            if trades:
                signal_frames.append(pd.DataFrame(trades))
                trades.clear()
            if baseline_trades:
                baseline_frames.append(pd.DataFrame(baseline_trades))
                baseline_trades.clear()
    finally:
        store.close()
    trades_df = pd.concat(signal_frames, ignore_index=True) if signal_frames else pd.DataFrame()
    baseline_df = pd.concat(baseline_frames, ignore_index=True) if baseline_frames else pd.DataFrame()
    signal_frames.clear()
    baseline_frames.clear()
    if not args.skip_financing_sensitivity and not any(rates.get(item.symbol) for item in commodities):
        sensitivity_rows = _financing_sensitivity(trades_df, baseline_df)
    cell_rows, baseline_rows, book_rows = summarize_with_baselines(trades_df, baseline_df)
    write_csv(
        out_dir / "per_cell_results.csv",
        cell_rows,
        ["instrument", "family", "cell", "timeframe", "entry_mode", "direction", "n", "mean_r", "nw_lag", "nw_se", "ci_low", "ci_high", "baseline_n", "baseline_mean_r", "excess_r", "drag_pct_per_day_to_zero_excess", "excess_block_len", "excess_boot_se", "excess_ci_low", "excess_ci_high"],
    )
    write_csv(
        out_dir / "baseline_results.csv",
        baseline_rows,
        ["instrument", "timeframe", "entry_mode", "direction", "n", "mean_r", "nw_lag", "nw_se", "ci_low", "ci_high"],
    )
    write_csv(
        out_dir / "book_summary.csv",
        book_rows,
        ["instrument", "family", "timeframe", "entry_mode", "n", "mean_r", "nw_lag", "nw_se", "ci_low", "ci_high", "matched_baseline_mean_r", "raw_minus_avg_direction_baseline_r"],
    )
    write_csv(
        out_dir / "session_profile.csv",
        session_rows,
        ["instrument", "granularity", "row_count", "min_timestamp", "max_timestamp", "weekday_hour_pattern_utc"],
    )
    write_csv(
        out_dir / "stored_validation.csv",
        validation_rows,
        ["instrument", "granularity", "start", "end", "issue_kind", "issue_count", "first_issue_ts", "last_issue_ts", "overlaps_sweep_window"],
    )
    write_csv(
        out_dir / "financing_sensitivity.csv",
        sensitivity_rows,
        ["drag_pct_per_day", "drag_bp_per_day", "instrument", "family", "cell", "timeframe", "entry_mode", "direction", "n", "mean_r", "baseline_mean_r", "excess_r", "drag_pct_per_day_to_zero_excess", "excess_ci_low", "excess_ci_high"],
    )
    print(f"wrote {len(trades_df)} signal trades and {len(baseline_df)} baseline trades at {datetime.now(UTC).isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
