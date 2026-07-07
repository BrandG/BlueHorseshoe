"""Production signal-emission CLI for BH FTMO.

This module turns the latest locally ingested OANDA H4 bars into a small
manual-trading report: signals, entry/stop/target levels, lots, and account
risk. It deliberately reuses the backtest pipeline helpers so live emission
does not drift from the validated strategy path.
"""

from __future__ import annotations

import argparse
import html
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from bh_ftmo.analysis.strategy import Signal, load_weights
from bh_ftmo.analysis.sandbox_strategy import SandboxStrategy
from bh_ftmo.backtest.cli import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_OUTPUT_HTML_DIR,
    DEFAULT_WEIGHTS_PATH,
    _apply_configured_universe_filter,
    _build_pair_specs,
    _compute_atr_by_symbol,
    _generate_bh_ftmo_signals,
    _load_full_config,
    _load_universe_filter_config,
    _select_symbols,
)
from bh_ftmo.backtest.pip_value import quote_to_account_rate
from bh_ftmo.backtest.trade_factory import derive_position
from bh_ftmo.backtest.types import Position
from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.data.incremental_update import send_failure_email
from bh_ftmo.logging.scrubber import install as install_scrubber

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "fx_4h.duckdb"
DEFAULT_LOOKBACK_DAYS = 60
DEFAULT_LIVE_STRATEGIES = (SandboxStrategy.name,)

LOG = logging.getLogger("bh_ftmo.predict")


@dataclass(frozen=True)
class LiveSignal:
    signal: Signal
    position: Position
    price_precision: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit BH FTMO live manual-entry signals.")
    parser.add_argument("--equity", type=float, required=True, help="Current account equity")
    parser.add_argument("--target-date", type=_parse_date, help="Latest UTC date to consider")
    parser.add_argument("--no-email", action="store_true", help="Do not email the HTML report")
    parser.add_argument("--symbols", help="Comma-separated canonical symbols (default: all config instruments)")
    parser.add_argument(
        "--strategies",
        type=_parse_strategies,
        default=None,
        help="Comma-separated strategies to run (default: sandbox_v1)",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Config JSON path")
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS_PATH, help="Weights JSON path")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="FxStore DuckDB path")
    parser.add_argument("--output-html", type=Path, help="HTML report path")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS, help="H4 warmup lookback days")
    return parser


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO date: {value!r}") from exc


def _parse_strategies(value: str) -> list[str]:
    selected: list[str] = []
    choices = set(DEFAULT_LIVE_STRATEGIES)
    for raw_name in value.split(","):
        name = raw_name.strip().lower()
        if name not in choices:
            raise argparse.ArgumentTypeError(
                f"invalid strategy: {name!r}. Choices: {', '.join(DEFAULT_LIVE_STRATEGIES)}"
            )
        if name not in selected:
            selected.append(name)
    return selected


def _resolve_strategy_names(weights_path: Path, requested: Optional[list[str]]) -> list[str]:
    names = list(requested) if requested is not None else list(DEFAULT_LIVE_STRATEGIES)
    weights = load_weights(weights_path)
    enabled: list[str] = []
    for name in names:
        block = weights.get(name, {})
        if isinstance(block, dict) and block.get("enabled") is False:
            continue
        enabled.append(name)
    return enabled


def _target_end(target_date: Optional[date]) -> datetime:
    if target_date is None:
        return datetime.now(UTC).replace(tzinfo=None)
    return datetime.combine(target_date + timedelta(days=1), time.min)


def _load_recent_bars(
    symbols: list[str],
    *,
    store: FxStore,
    start: datetime,
    end: datetime,
) -> dict[str, pd.DataFrame]:
    bars = {symbol: store.load(symbol, granularity="H4", start=start, end=end) for symbol in symbols}
    missing = [symbol for symbol, frame in bars.items() if frame.empty]
    if missing:
        raise ValueError(f"missing H4 bars for: {', '.join(missing)}")
    return bars


def _completed_signal_and_entry_ts(bars_4h: dict[str, pd.DataFrame]) -> tuple[datetime, datetime]:
    common: Optional[set[pd.Timestamp]] = None
    for frame in bars_4h.values():
        timestamps = set(pd.to_datetime(frame["timestamp"]))
        common = timestamps if common is None else common & timestamps
    ordered = sorted(common or [])
    if len(ordered) < 2:
        raise ValueError("need at least two common H4 bars to identify a completed signal bar")
    signal_ts = ordered[-2]
    entry_ts = ordered[-1]
    return signal_ts.to_pydatetime(), entry_ts.to_pydatetime()


def _row_at(frame: pd.DataFrame, ts: datetime) -> pd.Series:
    matches = frame.loc[pd.to_datetime(frame["timestamp"]) == pd.Timestamp(ts)]
    if matches.empty:
        raise KeyError(f"missing bar at {ts}")
    return matches.iloc[0]


def _mid_close(row: pd.Series) -> float:
    return (float(row["close_bid"]) + float(row["close_ask"])) / 2.0


def _rates_snapshot_at(bars_4h: dict[str, pd.DataFrame], ts: datetime) -> dict[str, float]:
    rates: dict[str, float] = {}
    for symbol, frame in bars_4h.items():
        try:
            rates[symbol] = _mid_close(_row_at(frame, ts))
        except KeyError:
            continue
    return rates


def _price_precision(pip_size: float) -> int:
    text = f"{pip_size:.10f}".rstrip("0")
    decimals = len(text.split(".", 1)[1]) if "." in text else 0
    return decimals + 1


def _size_live_signals(
    signals: list[Signal],
    *,
    bars_4h: dict[str, pd.DataFrame],
    signal_ts: datetime,
    entry_ts: datetime,
    atr_by_symbol: dict[str, pd.Series],
    pair_specs: dict,
    config: dict,
    equity: float,
) -> list[LiveSignal]:
    sizing_config = {
        "risk_pct_per_trade": float(config["risk"]["max_risk_per_trade_pct"]),
        "k_stop": 1.5,
        "k_target": 2.5,
        "max_concurrent_positions": int(config["risk"]["max_concurrent_positions"]),
    }
    ftmo_config = config["ftmo"]
    rates = _rates_snapshot_at(bars_4h, entry_ts)
    out: list[LiveSignal] = []
    for idx, signal in enumerate(sorted(signals, key=lambda s: s.score, reverse=True), start=1):
        try:
            quote_rate = quote_to_account_rate(signal.symbol, ftmo_config["account_currency"], rates)
            next_bar = _row_at(bars_4h[signal.symbol], entry_ts)
            atr_value = float(atr_by_symbol[signal.symbol].loc[pd.Timestamp(signal_ts)])
        except (KeyError, ValueError):
            LOG.warning("skipping %s: missing entry/rate/ATR data", signal.symbol)
            continue
        position = derive_position(
            signal,
            next_bar=next_bar,
            atr_14=atr_value,
            pair_spec=pair_specs[signal.symbol],
            sizing_config=sizing_config,
            account_currency=ftmo_config["account_currency"],
            current_equity=equity,
            quote_to_account=quote_rate,
            next_position_id=idx,
        )
        if position is None:
            continue
        out.append(
            LiveSignal(
                signal=signal,
                position=position,
                price_precision=_price_precision(pair_specs[signal.symbol].pip_size),
            )
        )
    return out


def run_prediction(
    *,
    equity: float,
    target_date: Optional[date],
    config_path: Path,
    weights_path: Path,
    db_path: Path,
    output_html: Optional[Path],
    symbols_arg: Optional[str],
    strategies_arg: Optional[list[str]],
    lookback_days: int,
    email: bool,
    store: Optional[FxStore] = None,
) -> tuple[str, Path, list[LiveSignal], datetime, datetime, int, int]:
    if equity <= 0:
        raise ValueError("--equity must be positive")
    if lookback_days < 30:
        raise ValueError("--lookback-days must be at least 30")

    config = _load_full_config(config_path)
    pair_specs = _build_pair_specs(config)
    symbols = _select_symbols(config, symbols_arg)
    strategy_names = _resolve_strategy_names(weights_path, strategies_arg)
    end = _target_end(target_date)
    start = end - timedelta(days=lookback_days)

    own_store = store is None
    fx_store = store or FxStore(db_path, read_only=True)
    try:
        bars_4h = _load_recent_bars(symbols, store=fx_store, start=start, end=end)
    finally:
        if own_store:
            fx_store.close()

    universe_cfg = _load_universe_filter_config(weights_path, strategy_names)
    filtered_symbols = _apply_configured_universe_filter(symbols, bars_4h, universe_cfg)
    filtered_bars = {symbol: bars_4h[symbol] for symbol in filtered_symbols}
    signal_ts, entry_ts = _completed_signal_and_entry_ts(filtered_bars)
    atr_by_symbol = _compute_atr_by_symbol(filtered_bars)

    all_signals = _generate_bh_ftmo_signals(filtered_bars, weights_path, filtered_symbols, strategy_names)
    live_candidates = [
        signal
        for signal in all_signals
        if pd.Timestamp(signal.timestamp).to_pydatetime() == signal_ts
        and signal.above_threshold
        and signal.direction != 0
    ]
    live_signals = _size_live_signals(
        live_candidates,
        bars_4h=filtered_bars,
        signal_ts=signal_ts,
        entry_ts=entry_ts,
        atr_by_symbol=atr_by_symbol,
        pair_specs=pair_specs,
        config=config,
        equity=equity,
    )

    html_path = output_html or (DEFAULT_OUTPUT_HTML_DIR / f"bh_ftmo_signals_{signal_ts.date().isoformat()}.html")
    console = render_console(
        live_signals,
        equity=equity,
        risk_pct=float(config["risk"]["max_risk_per_trade_pct"]),
        signal_ts=signal_ts,
        entry_ts=entry_ts,
        symbols_total=len(symbols),
        symbols_filtered=len(filtered_symbols),
    )
    html_report = render_html(
        live_signals,
        equity=equity,
        risk_pct=float(config["risk"]["max_risk_per_trade_pct"]),
        signal_ts=signal_ts,
        entry_ts=entry_ts,
        symbols_total=len(symbols),
        symbols_filtered=len(filtered_symbols),
    )
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html_report, encoding="utf-8")
    if email:
        send_failure_email(
            f"BH FTMO Signals - {signal_ts.date().isoformat()}",
            console,  # plain-text fallback (clean ASCII table for Outlook/text clients)
            html_body=html_report,  # rich HTML alternative
        )
    return console, html_path, live_signals, signal_ts, entry_ts, len(filtered_symbols), len(symbols)


def _fmt_price(value: float, precision: int) -> str:
    return f"{value:.{precision}f}"


def _direction(direction: int) -> str:
    return "long" if direction > 0 else "short"


def _console_rows(live_signals: list[LiveSignal]) -> list[list[str]]:
    rows: list[list[str]] = []
    for idx, item in enumerate(live_signals, start=1):
        pos = item.position
        sig = item.signal
        rows.append(
            [
                str(idx),
                sig.symbol,
                sig.strategy,
                _direction(sig.direction),
                f"{sig.score:.2f}",
                _fmt_price(pos.open_price, item.price_precision),
                _fmt_price(pos.stop, item.price_precision),
                _fmt_price(pos.target, item.price_precision),
                f"{pos.lots:.2f}",
                f"$ {pos.risk_at_open_account_ccy:,.2f}",
            ]
        )
    return rows


def render_console(
    live_signals: list[LiveSignal],
    *,
    equity: float,
    risk_pct: float,
    signal_ts: datetime,
    entry_ts: datetime,
    symbols_total: int,
    symbols_filtered: int,
    now_utc: Optional[datetime] = None,
) -> str:
    now = now_utc or datetime.now(UTC).replace(tzinfo=None)
    lines = [
        f"BH FTMO Signals - {now:%Y-%m-%d %H:%M} UTC (signal bar: {signal_ts:%Y-%m-%d %H:%M} UTC, entry bar: {entry_ts:%Y-%m-%d %H:%M} UTC)",
        f"Account equity: ${equity:,.2f} | Risk per trade: {risk_pct * 100:.1f}% | Filter: {symbols_filtered} of {symbols_total} pairs",
        "",
    ]
    if not live_signals:
        lines.append("No signals fired this bar.")
        return "\n".join(lines)

    headers = ["#", "Pair", "Strategy", "Direction", "Score", "Entry", "Stop", "Target", "Lots", "Risk$"]
    rows = _console_rows(live_signals)
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]
    lines.append("  " + "  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    lines.append("  " + "  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        lines.append("  " + "  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))
    return "\n".join(lines)


def render_html(
    live_signals: list[LiveSignal],
    *,
    equity: float,
    risk_pct: float,
    signal_ts: datetime,
    entry_ts: datetime,
    symbols_total: int,
    symbols_filtered: int,
) -> str:
    headers = ["Pair", "Strategy", "Direction", "Score", "Entry", "Stop", "Target", "Lots", "Risk$"]

    # Inline styles — Gmail and most clients strip <style> blocks and pseudo-
    # selectors like :nth-child, so each cell carries its own style attribute.
    text_cell_style = (
        "padding:12px 22px; border:1px solid #d8e0e8; "
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; "
        "white-space:nowrap; text-align:left;"
    )
    direction_cell_style = (
        "padding:12px 22px; border:1px solid #d8e0e8; "
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; "
        "white-space:nowrap; text-align:center; text-transform:uppercase; "
        "font-size:12px; letter-spacing:0.04em;"
    )
    num_cell_style = (
        "padding:12px 28px 12px 22px; border:1px solid #d8e0e8; "
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; "
        "white-space:nowrap; text-align:right; "
        "font-variant-numeric:tabular-nums;"
    )

    th_base = (
        "padding:12px 22px; border:1px solid #2c4258; "
        "background:#24364b; color:#ffffff; font-weight:600; "
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; "
        "white-space:nowrap;"
    )
    th_styles = []
    for idx, header in enumerate(headers):
        if idx == 2:  # Direction
            th_styles.append(th_base + " text-align:center;")
        elif idx >= 3:  # numeric columns
            th_styles.append(th_base + " text-align:right; padding-right:28px;")
        else:
            th_styles.append(th_base + " text-align:left;")

    header_row = "".join(
        f'<th style="{th_styles[idx]}">{header}</th>'
        for idx, header in enumerate(headers)
    )

    row_html = []
    for row_idx, item in enumerate(live_signals):
        sig = item.signal
        pos = item.position
        cells = [
            sig.symbol,
            sig.strategy,
            _direction(sig.direction),
            f"{sig.score:.2f}",
            _fmt_price(pos.open_price, item.price_precision),
            _fmt_price(pos.stop, item.price_precision),
            _fmt_price(pos.target, item.price_precision),
            f"{pos.lots:.2f}",
            f"$ {pos.risk_at_open_account_ccy:,.2f}",
        ]
        zebra = "#f9fafb" if row_idx % 2 else "#ffffff"
        td_html = []
        for col_idx, value in enumerate(cells):
            if col_idx == 2:
                style = direction_cell_style
            elif col_idx >= 3:
                style = num_cell_style
            else:
                style = text_cell_style
            td_html.append(
                f'<td style="{style} background:{zebra};">{html.escape(value)}</td>'
            )
        row_html.append("<tr>" + "".join(td_html) + "</tr>")

    if not row_html:
        empty_style = (
            "padding:24px; border:1px solid #d8e0e8; text-align:center; "
            "color:#51606f; "
            "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        )
        row_html.append(
            f'<tr><td colspan="{len(headers)}" style="{empty_style}">'
            f'No signals fired this bar.</td></tr>'
        )

    table_style = (
        "border-collapse:collapse; background:#ffffff; "
        "border:1px solid #d8e0e8; margin-top:24px;"
    )

    body_style = (
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; "
        "color:#17202a; margin:32px; background:#f7f9fb;"
    )
    h1_style = "font-size:28px; margin:0 0 8px;"
    meta_style = "color:#51606f; margin:4px 0;"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>BH FTMO Signals - {signal_ts.date().isoformat()}</title>
</head>
<body style="{body_style}">
  <h1 style="{h1_style}">BH FTMO Signals</h1>
  <p style="{meta_style}">Signal bar: {signal_ts:%Y-%m-%d %H:%M} UTC | Entry bar: {entry_ts:%Y-%m-%d %H:%M} UTC</p>
  <p style="{meta_style}">Account equity: ${equity:,.2f} | Risk per trade: {risk_pct * 100:.1f}% | Filter: {symbols_filtered} of {symbols_total} pairs</p>
  <table border="0" cellspacing="0" cellpadding="0" style="{table_style}">
    <thead><tr>{header_row}</tr></thead>
    <tbody>{"".join(row_html)}</tbody>
  </table>
</body>
</html>
"""


def main(argv: Optional[list[str]] = None) -> int:
    install_scrubber()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        console, html_path, *_ = run_prediction(
            equity=args.equity,
            target_date=args.target_date,
            config_path=args.config,
            weights_path=args.weights,
            db_path=args.db_path,
            output_html=args.output_html,
            symbols_arg=args.symbols,
            strategies_arg=args.strategies,
            lookback_days=args.lookback_days,
            email=not args.no_email,
        )
    except Exception as exc:  # noqa: BLE001
        LOG.error("predict failed: %s", exc)
        print(f"ERROR: {exc}")
        return 1
    print(console)
    print(f"\nHTML report: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
