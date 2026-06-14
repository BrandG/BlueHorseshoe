"""ATR-regime P4 FTMO-constrained pre-deploy simulation."""
# pylint: disable=import-error,wrong-import-order,wrong-import-position
# pylint: disable=missing-function-docstring,too-many-arguments,too-many-locals
# pylint: disable=too-many-statements,too-many-branches,too-many-instance-attributes
# pylint: disable=too-many-positional-arguments,protected-access,duplicate-code
# pylint: disable=missing-class-docstring
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
CONFLUENCE_DIR = ROOT / "research" / "confluence_v1"
HARNESS_DIR = ROOT / "research" / "v2_executable_regate" / "harness"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(CONFLUENCE_DIR))
sys.path.insert(0, str(HARNESS_DIR))

from atr_regime_p1 import REGIME_ORDER, _markdown_table  # noqa: E402
from atr_regime_p2b import (  # noqa: E402
    PRIMARY_DIRECTION,
    PRIMARY_SLEEVE,
    _attach_metric_values,
    _build_sleeves,
    _load_fires_and_pairs,
    _metric_frames,
    _simulate_all_depth_trades,
)
from atr_regime_p3 import BUCKET_COL, CONDITIONERS, _book_frame  # noqa: E402
from bh_ftmo.backtest.ftmo_rules import (  # noqa: E402
    FtmoRuleEngine,
    load_ftmo_config,
)
from bh_ftmo.data.fx_store import FxStore  # noqa: E402

SWING_CONFIG_PATH = ROOT / "src" / "bh_ftmo_swing_config.json"
RISK_CONFIG_PATH = ROOT / "src" / "bh_ftmo_config.json"
AUTO_V2_PATH = ROOT / "src" / "bud" / "auto_v2.py"
CSV_PATH = OUT_DIR / "atr_regime_p4_ftmo.csv"
REPORT_PATH = OUT_DIR / "ATR_REGIME_P4.md"
OUT_PATH = OUT_DIR / "atr_regime_p4_ftmo.out"
BASE_RISK_PER_TRADE_PCT = 0.005
ANALYSIS_HORIZONS = (180, 120, 365)
HEADLINE_HORIZON = 180
BOOKS = ("unconditioned", "size_down_high_0_5", "hard_gate_skip_high")
SAMPLES = (PRIMARY_SLEEVE, "long_mr_full6")
ROLLING_START_FREQ = "30D"


@dataclass(frozen=True)
class SimConfig:
    ftmo: dict[str, object]
    max_concurrent_positions: int
    max_daily_risk_pct: float
    server_timezone: str


@dataclass
class OpenPosition:
    trade_id: int
    pair: str
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    risk_pct: float
    risk_account_ccy: float
    pnl_account_ccy: float
    regime: str


@dataclass
class WindowResult:
    sample: str
    book: str
    horizon_days: int
    challenge_window: str
    start_ts: pd.Timestamp
    end_ts: pd.Timestamp
    outcome: str
    breach_type: str
    target_hit_at: str
    days_to_target: float
    trading_days: int
    final_equity: float
    max_drawdown_pct: float
    opened_trades: int
    skipped_slot: int
    skipped_daily_risk: int
    skipped_engine: int
    skipped_regime: int
    low_opened: int
    mid_opened: int
    high_opened: int
    slot_block_low_mid: int
    slot_block_high: int
    daily_risk_block_low_mid: int
    daily_risk_block_high: int


class UnlimitedTimerFtmoRuleEngine(FtmoRuleEngine):
    """FTMO engine wrapper for Swing accounts with no challenge timer."""

    def can_open_new(self, ts: datetime) -> tuple[bool, str | None]:
        if self._ftmo_config["max_trading_days"] is not None:
            return super().can_open_new(ts)
        self._last_seen_ts = ts
        if self._state.breached is not None:
            return False, "breached"
        if (
            self._state.target_hit_at is not None
            and self.trading_days_count() >= int(self._ftmo_config["min_trading_days"])
        ):
            return False, "target_already_passed"
        return True, None

    def is_pushed(self) -> bool:
        if self._ftmo_config["max_trading_days"] is None:
            return False
        return super().is_pushed()


def _load_sim_config() -> SimConfig:
    ftmo = load_ftmo_config(SWING_CONFIG_PATH)
    with RISK_CONFIG_PATH.open(encoding="utf-8") as handle:
        risk = json.load(handle)["risk"]
    return SimConfig(
        ftmo=ftmo,
        max_concurrent_positions=int(risk["max_concurrent_positions"]),
        max_daily_risk_pct=float(risk["max_daily_risk_pct"]),
        server_timezone=str(ftmo["server_timezone"]),
    )


def _exit_timestamps(samples: dict[str, pd.DataFrame], pairs: list[str]) -> dict[tuple[str, int], pd.Timestamp]:
    needed: dict[str, set[int]] = {pair: set() for pair in pairs}
    for frame in samples.values():
        for row in frame[["pair", "exit_idx"]].itertuples(index=False):
            needed[str(row.pair)].add(int(row.exit_idx))
    out: dict[tuple[str, int], pd.Timestamp] = {}
    with FxStore(read_only=True) as store:
        for pair, indices in needed.items():
            if not indices:
                continue
            raw = store.load(pair, granularity="H4", include_incomplete=False)
            timestamps = pd.to_datetime(raw["timestamp"]).reset_index(drop=True)
            for idx in indices:
                out[(pair, idx)] = pd.Timestamp(timestamps.iloc[idx])
    return out


def _sample_frames() -> dict[str, pd.DataFrame]:
    fires, pairs = _load_fires_and_pairs()
    start_ts = pd.Timestamp(fires["ts"].min())
    end_ts = pd.Timestamp(fires["ts"].max())
    with FxStore(read_only=True) as store:
        metric_frames = _metric_frames(store, pairs, start_ts, end_ts)
    all_trades, _drop_rows = _simulate_depth_trades(fires, pairs)
    all_trades = _attach_metric_values(all_trades, metric_frames)
    sleeve_trades, _dedup_rows = _build_sleeves(all_trades)
    samples = {
        PRIMARY_SLEEVE: _book_frame(
            sleeve_trades[(PRIMARY_SLEEVE, PRIMARY_DIRECTION)],
            PRIMARY_SLEEVE,
        ),
        "long_mr_full6": _book_frame(sleeve_trades[("long_mr_full6", "long")], "long_mr_full6"),
    }
    exits = _exit_timestamps(samples, pairs)
    for sample, frame in samples.items():
        enriched = frame.copy()
        enriched["trade_id"] = np.arange(len(enriched), dtype=int)
        enriched["exit_ts"] = [
            exits[(str(row.pair), int(row.exit_idx))]
            for row in enriched[["pair", "exit_idx"]].itertuples(index=False)
        ]
        enriched["regime"] = enriched[BUCKET_COL]
        enriched = enriched.sort_values(["ts", "pair", "bar_idx"]).reset_index(drop=True)
        enriched["_ts_ns"] = enriched["ts"].to_numpy(dtype="datetime64[ns]").astype("int64")
        samples[sample] = enriched
    return samples


def _simulate_depth_trades(fires: pd.DataFrame, pairs: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    return _simulate_all_depth_trades(fires, pairs)


def _analysis_start_dates(frame: pd.DataFrame) -> list[pd.Timestamp]:
    first = pd.Timestamp(frame["ts"].min()).ceil("D")
    last = pd.Timestamp(frame["ts"].max()).floor("D") - pd.Timedelta(days=max(ANALYSIS_HORIZONS))
    dates = list(pd.date_range(first, last, freq=ROLLING_START_FREQ))
    if not dates:
        raise RuntimeError("sample is too short for the requested horizons")
    return [pd.Timestamp(value) for value in dates]


def _server_day(ts: pd.Timestamp, timezone: str) -> object:
    local = ts.to_pydatetime().replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(timezone))
    return local.date()


def _reset_if_due(
    engine: UnlimitedTimerFtmoRuleEngine,
    ts: pd.Timestamp,
    equity: float,
) -> None:
    stamp = ts.to_pydatetime()
    if engine.is_session_reset_due(stamp):
        engine.on_session_reset(stamp, equity)


def _max_drawdown_pct(equity_points: list[float]) -> float:
    values = pd.Series(equity_points, dtype=float)
    peaks = values.cummax()
    drawdowns = (peaks - values) / float(values.iloc[0])
    return float(drawdowns.max())


def _outcome_from_engine(
    engine: UnlimitedTimerFtmoRuleEngine,
    horizon_end: pd.Timestamp,
    equity: float,
) -> tuple[str, str, str, float]:
    _reset_if_due(engine, horizon_end, equity)
    breach = engine.on_equity_update(horizon_end.to_pydatetime(), equity)
    if breach is not None:
        return "fail", str(breach.rule), "", np.nan
    if engine.is_passed():
        target_ts = pd.Timestamp(engine.state.target_hit_at)
        days_to_target = float((target_ts.date() - engine.state.challenge_start_ts.date()).days + 1)
        return "pass", "", target_ts.isoformat(), days_to_target
    return "push", "", "", np.nan


def _entry_allowed_by_risk(
    day_risk: dict[object, float],
    day_key: object,
    risk_pct: float,
    max_daily_risk_pct: float,
) -> bool:
    return day_risk.get(day_key, 0.0) + risk_pct <= max_daily_risk_pct + 1e-12


def _window_trade_slice(
    frame: pd.DataFrame,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    ts_values = frame["_ts_ns"].to_numpy(dtype=np.int64)
    left = int(np.searchsorted(ts_values, start_ts.value, side="left"))
    right = int(np.searchsorted(ts_values, end_ts.value, side="right"))
    return frame.iloc[left:right]


def _record_skip(result: dict[str, int], reason: str, regime: str) -> None:
    result[reason] += 1
    if reason == "skipped_slot":
        if regime in REGIME_ORDER[:2]:
            result["slot_block_low_mid"] += 1
        elif regime == REGIME_ORDER[2]:
            result["slot_block_high"] += 1
    if reason == "skipped_daily_risk":
        if regime in REGIME_ORDER[:2]:
            result["daily_risk_block_low_mid"] += 1
        elif regime == REGIME_ORDER[2]:
            result["daily_risk_block_high"] += 1


def _simulate_window(
    frame: pd.DataFrame,
    *,
    sample: str,
    book: str,
    start_ts: pd.Timestamp,
    horizon_days: int,
    config: SimConfig,
) -> WindowResult:
    horizon_end = start_ts + pd.Timedelta(days=horizon_days)
    engine = UnlimitedTimerFtmoRuleEngine(
        config.ftmo,
        start_equity=float(config.ftmo["initial_balance"]),
        start_ts=start_ts.to_pydatetime(),
        server_tz=config.server_timezone,
    )
    multipliers = CONDITIONERS[book]
    equity = float(config.ftmo["initial_balance"])
    open_positions: list[OpenPosition] = []
    day_risk: dict[object, float] = {}
    equity_points = [equity]
    counters = {
        "skipped_slot": 0,
        "skipped_daily_risk": 0,
        "skipped_engine": 0,
        "skipped_regime": 0,
        "low_opened": 0,
        "mid_opened": 0,
        "high_opened": 0,
        "slot_block_low_mid": 0,
        "slot_block_high": 0,
        "daily_risk_block_low_mid": 0,
        "daily_risk_block_high": 0,
    }
    trades = _window_trade_slice(frame, start_ts, horizon_end)
    for trade in trades.itertuples(index=False):
        event_ts = pd.Timestamp(trade.ts)
        exits = [position for position in open_positions if position.exit_ts <= event_ts]
        for position in sorted(exits, key=lambda item: (item.exit_ts, item.pair, item.trade_id)):
            _reset_if_due(engine, position.exit_ts, equity)
            equity += position.pnl_account_ccy
            engine.on_trade_event(position.exit_ts.to_pydatetime())
            breach = engine.on_equity_update(position.exit_ts.to_pydatetime(), equity)
            equity_points.append(equity)
            open_positions.remove(position)
            if breach is not None or engine.is_passed():
                return _window_result(
                    sample, book, horizon_days, start_ts, horizon_end, engine, equity,
                    equity_points, _opened_count(counters), counters,
                )
        _reset_if_due(engine, event_ts, equity)
        regime = str(trade.regime)
        multiplier = float(multipliers[regime])
        if multiplier <= 0.0:
            counters["skipped_regime"] += 1
            continue
        can_open, reason = engine.can_open_new(event_ts.to_pydatetime())
        if not can_open:
            counters["skipped_engine"] += 1
            if reason in {"breached", "target_already_passed"}:
                break
            continue
        if len(open_positions) >= config.max_concurrent_positions:
            _record_skip(counters, "skipped_slot", regime)
            continue
        risk_pct = BASE_RISK_PER_TRADE_PCT * multiplier
        day_key = _server_day(event_ts, config.server_timezone)
        if not _entry_allowed_by_risk(
            day_risk,
            day_key,
            risk_pct,
            config.max_daily_risk_pct,
        ):
            _record_skip(counters, "skipped_daily_risk", regime)
            continue
        risk_account = equity * risk_pct
        open_positions.append(OpenPosition(
            trade_id=int(trade.trade_id),
            pair=str(trade.pair),
            entry_ts=event_ts,
            exit_ts=pd.Timestamp(trade.exit_ts),
            risk_pct=risk_pct,
            risk_account_ccy=risk_account,
            pnl_account_ccy=risk_account * float(trade.R),
            regime=regime,
        ))
        day_risk[day_key] = day_risk.get(day_key, 0.0) + risk_pct
        engine.on_trade_event(event_ts.to_pydatetime())
        if regime == REGIME_ORDER[0]:
            counters["low_opened"] += 1
        elif regime == REGIME_ORDER[1]:
            counters["mid_opened"] += 1
        elif regime == REGIME_ORDER[2]:
            counters["high_opened"] += 1
    for position in sorted(
        [item for item in open_positions if item.exit_ts <= horizon_end],
        key=lambda item: (item.exit_ts, item.pair, item.trade_id),
    ):
        _reset_if_due(engine, position.exit_ts, equity)
        equity += position.pnl_account_ccy
        engine.on_trade_event(position.exit_ts.to_pydatetime())
        breach = engine.on_equity_update(position.exit_ts.to_pydatetime(), equity)
        equity_points.append(equity)
        if breach is not None or engine.is_passed():
            break
    return _window_result(
        sample, book, horizon_days, start_ts, horizon_end, engine, equity, equity_points,
        _opened_count(counters), counters,
    )


def _opened_count(counters: dict[str, int]) -> int:
    return sum(counters[key] for key in ("low_opened", "mid_opened", "high_opened"))


def _window_result(
    sample: str,
    book: str,
    horizon_days: int,
    start_ts: pd.Timestamp,
    horizon_end: pd.Timestamp,
    engine: UnlimitedTimerFtmoRuleEngine,
    equity: float,
    equity_points: list[float],
    opened_trades: int,
    counters: dict[str, int],
) -> WindowResult:
    outcome, breach_type, target_hit_at, days_to_target = _outcome_from_engine(
        engine,
        horizon_end,
        equity,
    )
    return WindowResult(
        sample=sample,
        book=book,
        horizon_days=horizon_days,
        challenge_window=f"{start_ts.date()}__{horizon_end.date()}",
        start_ts=start_ts,
        end_ts=horizon_end,
        outcome=outcome,
        breach_type=breach_type,
        target_hit_at=target_hit_at,
        days_to_target=days_to_target,
        trading_days=engine.trading_days_count(),
        final_equity=equity,
        max_drawdown_pct=_max_drawdown_pct(equity_points),
        opened_trades=opened_trades,
        skipped_slot=counters["skipped_slot"],
        skipped_daily_risk=counters["skipped_daily_risk"],
        skipped_engine=counters["skipped_engine"],
        skipped_regime=counters["skipped_regime"],
        low_opened=counters["low_opened"],
        mid_opened=counters["mid_opened"],
        high_opened=counters["high_opened"],
        slot_block_low_mid=counters["slot_block_low_mid"],
        slot_block_high=counters["slot_block_high"],
        daily_risk_block_low_mid=counters["daily_risk_block_low_mid"],
        daily_risk_block_high=counters["daily_risk_block_high"],
    )


def _run_windows(samples: dict[str, pd.DataFrame], config: SimConfig) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for sample in SAMPLES:
        starts = _analysis_start_dates(samples[sample])
        for horizon_days in ANALYSIS_HORIZONS:
            for start_ts in starts:
                if start_ts + pd.Timedelta(days=horizon_days) > samples[sample]["ts"].max():
                    continue
                for book in BOOKS:
                    result = _simulate_window(
                        samples[sample],
                        sample=sample,
                        book=book,
                        start_ts=start_ts,
                        horizon_days=horizon_days,
                        config=config,
                    )
                    rows.append({"row_type": "window", **result.__dict__})
    return pd.DataFrame(rows)


def _aggregate(windows: pd.DataFrame) -> pd.DataFrame:
    rows = []
    grouped = windows[windows["row_type"] == "window"].groupby(
        ["sample", "book", "horizon_days"],
        sort=True,
    )
    for (sample, book, horizon), sub in grouped:
        outcomes = sub["outcome"].value_counts()
        rows.append({
            "row_type": "aggregate",
            "sample": sample,
            "book": book,
            "horizon_days": int(horizon),
            "challenge_window": "ALL",
            "windows": len(sub),
            "pass_rate": outcomes.get("pass", 0) / len(sub),
            "fail_rate": outcomes.get("fail", 0) / len(sub),
            "push_rate": outcomes.get("push", 0) / len(sub),
            "median_days_to_target": sub.loc[sub["outcome"] == "pass", "days_to_target"].median(),
            "daily_loss_breaches": int((sub["breach_type"] == "daily_loss").sum()),
            "max_loss_breaches": int((sub["breach_type"] == "max_loss").sum()),
            "median_final_equity": float(sub["final_equity"].median()),
            "median_max_drawdown_pct": float(sub["max_drawdown_pct"].median()),
            "opened_trades": int(sub["opened_trades"].sum()),
            "skipped_slot": int(sub["skipped_slot"].sum()),
            "skipped_daily_risk": int(sub["skipped_daily_risk"].sum()),
            "skipped_regime": int(sub["skipped_regime"].sum()),
            "low_opened": int(sub["low_opened"].sum()),
            "mid_opened": int(sub["mid_opened"].sum()),
            "high_opened": int(sub["high_opened"].sum()),
            "slot_block_low_mid": int(sub["slot_block_low_mid"].sum()),
            "slot_block_high": int(sub["slot_block_high"].sum()),
            "daily_risk_block_low_mid": int(sub["daily_risk_block_low_mid"].sum()),
            "daily_risk_block_high": int(sub["daily_risk_block_high"].sum()),
        })
    return pd.DataFrame(rows)


def _select_agg(agg: pd.DataFrame, sample: str, book: str, horizon: int) -> pd.Series:
    sub = agg[
        (agg["sample"] == sample)
        & (agg["book"] == book)
        & (agg["horizon_days"] == horizon)
    ]
    if sub.empty:
        raise RuntimeError(f"missing aggregate {sample} {book} {horizon}")
    return sub.iloc[0]


def _fmt_pct(value: float) -> str:
    if not np.isfinite(value):
        return "nan"
    return f"{100.0 * value:.1f}%"


def _fmt_num(value: float) -> str:
    if not np.isfinite(value):
        return "nan"
    return f"{value:.3g}"


def _report(agg: pd.DataFrame, config: SimConfig) -> str:
    primary = PRIMARY_SLEEVE
    base = _select_agg(agg, primary, "unconditioned", HEADLINE_HORIZON)
    size_down = _select_agg(agg, primary, "size_down_high_0_5", HEADLINE_HORIZON)
    hard_gate = _select_agg(agg, primary, "hard_gate_skip_high", HEADLINE_HORIZON)
    best = max(
        [base, size_down, hard_gate],
        key=lambda row: (float(row.pass_rate), -float(row.fail_rate), -float(row.max_loss_breaches)),
    )
    if str(best.book) == "unconditioned":
        deploy_call = "no improvement once constrained"
    else:
        deploy_call = f"deploy-recommend `{best.book}`"
    view_cols = [
        "sample",
        "book",
        "horizon_days",
        "windows",
        "pass_rate",
        "fail_rate",
        "push_rate",
        "median_days_to_target",
        "daily_loss_breaches",
        "max_loss_breaches",
        "median_max_drawdown_pct",
        "opened_trades",
        "skipped_slot",
        "skipped_daily_risk",
        "skipped_regime",
    ]
    table = agg[agg["horizon_days"] == HEADLINE_HORIZON].copy()
    for col in ["pass_rate", "fail_rate", "push_rate", "median_max_drawdown_pct"]:
        table[col] = table[col].map(_fmt_pct)
    sensitivity = agg[
        (agg["sample"] == primary)
        & (agg["horizon_days"].isin([120, 365]))
    ].copy()
    for col in ["pass_rate", "fail_rate", "push_rate", "median_max_drawdown_pct"]:
        sensitivity[col] = sensitivity[col].map(_fmt_pct)
    slot = agg[
        (agg["sample"] == primary)
        & (agg["horizon_days"] == HEADLINE_HORIZON)
    ].copy()
    slot["low_mid_opened"] = slot["low_opened"] + slot["mid_opened"]
    slot["low_mid_slot_blocks"] = slot["slot_block_low_mid"]
    slot["high_slot_blocks"] = slot["slot_block_high"]
    slot["low_mid_daily_risk_blocks"] = slot["daily_risk_block_low_mid"]
    slot["high_daily_risk_blocks"] = slot["daily_risk_block_high"]
    lines = [
        "# ATR Regime P4",
        "",
        "## Headline",
        (
            f"FTMO-constrained call on `{primary}` at the {HEADLINE_HORIZON}-calendar-day "
            f"external censoring horizon: **{deploy_call}**."
        ),
        (
            f"`size_down_high_0_5` pass/fail/push is "
            f"{_fmt_pct(float(size_down.pass_rate))}/"
            f"{_fmt_pct(float(size_down.fail_rate))}/"
            f"{_fmt_pct(float(size_down.push_rate))} vs unconditioned "
            f"{_fmt_pct(float(base.pass_rate))}/"
            f"{_fmt_pct(float(base.fail_rate))}/"
            f"{_fmt_pct(float(base.push_rate))}. Max-loss breaches: "
            f"{int(size_down.max_loss_breaches)} vs {int(base.max_loss_breaches)}; "
            f"daily-loss breaches: {int(size_down.daily_loss_breaches)} vs "
            f"{int(base.daily_loss_breaches)}."
        ),
        (
            f"`hard_gate_skip_high` pass/fail/push is "
            f"{_fmt_pct(float(hard_gate.pass_rate))}/"
            f"{_fmt_pct(float(hard_gate.fail_rate))}/"
            f"{_fmt_pct(float(hard_gate.push_rate))}; max-loss breaches "
            f"{int(hard_gate.max_loss_breaches)} and daily-loss breaches "
            f"{int(hard_gate.daily_loss_breaches)}."
        ),
        "",
        "The 180-day horizon is a reporting/censoring convention for a finite probability estimate; "
        "the loaded Swing FTMO config has `max_trading_days = null`, so the rule engine imposes no "
        "challenge expiry and pushes here mean the external analysis horizon expired.",
        "",
        "## FTMO And Risk Inputs",
        (
            f"FTMO config: `{SWING_CONFIG_PATH.relative_to(ROOT)}`; initial_balance="
            f"{config.ftmo['initial_balance']}, phase={config.ftmo['phase']}, "
            f"target={_fmt_pct(float(config.ftmo['profit_target_pct']))}, "
            f"daily_loss={_fmt_pct(float(config.ftmo['daily_loss_pct']))}, "
            f"max_loss={_fmt_pct(float(config.ftmo['max_loss_pct']))}, "
            f"max_loss_type={config.ftmo['max_loss_type']}, min_trading_days="
            f"{config.ftmo['min_trading_days']}, max_trading_days="
            f"{config.ftmo['max_trading_days']}, timezone={config.server_timezone}."
        ),
        (
            "Base risk/trade: 0.5% from `src/bud/auto_v2.py:87` "
            "(`RISK_PER_TRADE_PCT = 0.005`). Slot cap and daily risk cap: "
            f"{config.max_concurrent_positions} concurrent positions and "
            f"{_fmt_pct(config.max_daily_risk_pct)} daily risk from "
            "`src/bh_ftmo_config.json` risk block."
        ),
        "",
        "## Headline Aggregates",
    ]
    lines.extend(_markdown_table(table, view_cols))
    lines.extend([
        "",
        "## Horizon Sensitivity",
    ])
    lines.extend(_markdown_table(sensitivity, view_cols))
    lines.extend([
        "",
        "## Slot And Redeployment",
        (
            "The position-count cap binds heavily. `size_down_high_0_5` reduces high-ATR dollars at "
            "risk but still consumes one of the three slots, so it does not materially redeploy "
            "freed count capacity into low/mid trades. Hard-gate frees count slots by skipping high "
            "ATR entirely, but that is the same throughput cut P3 flagged."
        ),
    ])
    lines.extend(_markdown_table(
        slot,
        [
            "book",
            "opened_trades",
            "low_mid_opened",
            "high_opened",
            "skipped_slot",
            "low_mid_slot_blocks",
            "high_slot_blocks",
            "skipped_daily_risk",
            "low_mid_daily_risk_blocks",
            "high_daily_risk_blocks",
            "skipped_regime",
        ],
    ))
    lines.extend([
        "",
        "## Method",
        (
            "Trade stream: deployed long-MR strong-4 primary sleeve and long-MR full-6 cross-check, "
            "deduped one trade per `(pair, entry_bar)`, mid-entry 1%/1% R converted to account "
            "P/L using the deployed 0.5% base risk and the book's ATR-regime multiplier. Entries "
            "are accepted sequentially under the three-position cap and 4% daily risk cap; exits "
            "realize per-trade R at the H4 exit timestamp. FTMO daily-loss, max-loss, target, and "
            "minimum-trading-day enforcement is delegated to `FtmoRuleEngine`; only the null "
            "max-trading-days Swing guard is wrapped locally."
        ),
        (
            f"Rolling starts are every 30 calendar days (`{ROLLING_START_FREQ}`) and each window is censored at "
            "120, 180, and 365 calendar days. A pass requires target hit before breach and at "
            "least the configured minimum trading days; a fail is a daily/max-loss breach; a push "
            "is horizon expiry with neither."
        ),
        "",
        "## Artifacts",
        f"- `{CSV_PATH.name}`: window rows plus aggregate rows.",
        f"- `{OUT_PATH.name}`: run summary.",
        "",
        "Production wiring is intentionally out of scope for P4.",
        "",
    ])
    return "\n".join(lines)


def run() -> tuple[pd.DataFrame, str]:
    config = _load_sim_config()
    samples = _sample_frames()
    windows = _run_windows(samples, config)
    agg = _aggregate(windows)
    combined = pd.concat([windows, agg], ignore_index=True, sort=False)
    combined.to_csv(CSV_PATH, index=False)
    report = _report(agg, config)
    REPORT_PATH.write_text(report, encoding="utf-8")
    primary = _select_agg(agg, PRIMARY_SLEEVE, "size_down_high_0_5", HEADLINE_HORIZON)
    base = _select_agg(agg, PRIMARY_SLEEVE, "unconditioned", HEADLINE_HORIZON)
    out_lines = [
        "ATR-regime P4 FTMO run complete",
        f"csv={CSV_PATH}",
        f"report={REPORT_PATH}",
        f"out={OUT_PATH}",
        f"ftmo_config={SWING_CONFIG_PATH}",
        f"initial_balance={config.ftmo['initial_balance']}",
        f"target_pct={config.ftmo['profit_target_pct']}",
        f"daily_loss_pct={config.ftmo['daily_loss_pct']}",
        f"max_loss_pct={config.ftmo['max_loss_pct']}",
        f"max_trading_days={config.ftmo['max_trading_days']}",
        f"base_risk_per_trade_pct={BASE_RISK_PER_TRADE_PCT}",
        f"max_concurrent_positions={config.max_concurrent_positions}",
        f"max_daily_risk_pct={config.max_daily_risk_pct}",
        f"headline_horizon_days={HEADLINE_HORIZON}",
        f"unconditioned_pass_rate={base.pass_rate:.6f}",
        f"size_down_high_0_5_pass_rate={primary.pass_rate:.6f}",
        f"size_down_high_0_5_fail_rate={primary.fail_rate:.6f}",
    ]
    OUT_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return combined, report


def main() -> None:
    run()


if __name__ == "__main__":
    main()
