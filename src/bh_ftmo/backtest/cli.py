"""BH FTMO Phase 3 backtest CLI driver."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import traceback
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from bh_ftmo.analysis.cluster_filter import cluster_filter
from bh_ftmo.analysis.mean_reversion import MeanReversionStrategy
from bh_ftmo.analysis.sandbox_strategy import SandboxStrategy
from bh_ftmo.analysis.signal_generator import SignalGenerator
from bh_ftmo.analysis.strategy import BaselineStrategy, Signal, load_weights
from bh_ftmo.backtest.engine import StartConfig
from bh_ftmo.backtest.ftmo_rules import FtmoConfigUnverifiedError, load_ftmo_config
from bh_ftmo.backtest.gate import evaluate_gate
from bh_ftmo.backtest.metrics import cohort_metrics
from bh_ftmo.backtest.reporter import render_html_report, write_csv_ledger
from bh_ftmo.backtest.runner import run_full_comparison
from bh_ftmo.backtest.swap_rates import fetch_or_load_cached
from bh_ftmo.backtest.swap import SwapRates
from bh_ftmo.backtest.types import ChallengeResult, PairSpec
from bh_ftmo.backtest.universe_filter import UniverseFilterConfig, apply_universe_filter
from bh_ftmo.backtest.walk_forward import fold_windows, non_overlapping_starts
from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.data.oanda_client import OandaClient, OandaConfig, OandaError
from bh_ftmo.indicators.volatility import atr
from bh_ftmo.logging.scrubber import install as install_scrubber

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_HTML_DIR = REPO_ROOT / "src" / "graphs"
DEFAULT_OUTPUT_CSV_DIR = REPO_ROOT / "src" / "logs"
DEFAULT_CONFIG_PATH = REPO_ROOT / "src" / "bh_ftmo_config.json"
DEFAULT_WEIGHTS_PATH = REPO_ROOT / "src" / "bh_ftmo_weights.json"
DEFAULT_SANDBOX_MAX_WORKERS = 2

LOG = logging.getLogger("bh_ftmo.backtest.cli")
SWAP_APPROXIMATION_NOTE = (
    "Swap approximation: today's OANDA financing snapshot is applied uniformly across the full historical window "
    "because OANDA does not expose historical financing archives via REST."
)
DEFAULT_STRATEGY_NAMES = (BaselineStrategy.name, MeanReversionStrategy.name)
STRATEGY_NAMES = (*DEFAULT_STRATEGY_NAMES, SandboxStrategy.name)


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse surface for the Phase 3 CLI."""
    parser = argparse.ArgumentParser(description="Run the BH FTMO Phase 3 gate evaluation.")
    parser.add_argument("--output-html", type=Path, help="HTML report path")
    parser.add_argument("--output-csv", type=Path, help="Trade ledger CSV path")
    parser.add_argument("--start-date", type=_parse_date, help="Backtest window start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=_parse_date, help="Backtest window end date (YYYY-MM-DD)")
    parser.add_argument("--symbols", help="Comma-separated canonical symbols (default: all config instruments)")
    parser.add_argument("--no-swap", action="store_true", help="Skip OANDA financing lookup and use zero swap")
    parser.add_argument("--max-workers", type=int, help="ProcessPoolExecutor worker count")
    parser.add_argument("--rng-seed", type=int, default=42, help="Bootstrap/cohort RNG seed")
    parser.add_argument("--limit-folds", type=int, help="Only evaluate the first N walk-forward folds")
    parser.add_argument("--limit-starts", type=int, help="Only evaluate the first N starts per fold")
    parser.add_argument(
        "--strategies",
        type=_parse_strategies,
        default=None,
        help=(
            "Comma-separated subset of strategies to run. Choices: "
            "baseline, mean_reversion, sandbox_v1. Default: baseline,mean_reversion."
        ),
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Config JSON path")
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS_PATH, help="Weights JSON path")
    return parser


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO date: {value!r}") from exc


def _parse_strategies(value: str) -> list[str]:
    choices = set(STRATEGY_NAMES)
    selected: list[str] = []
    for raw_name in value.split(","):
        name = raw_name.strip().lower()
        if name not in choices:
            raise argparse.ArgumentTypeError(
                f"invalid strategy: {name!r}. Choices: {', '.join(STRATEGY_NAMES)}"
            )
        if name not in selected:
            selected.append(name)
    return selected


def _resolve_max_workers(strategy_names: list[str], requested_max_workers: Optional[int]) -> Optional[int]:
    if requested_max_workers is not None:
        return requested_max_workers
    if SandboxStrategy.name in strategy_names:
        return DEFAULT_SANDBOX_MAX_WORKERS
    return None


def _compute_run_id(args: argparse.Namespace, now_utc: Optional[datetime] = None) -> str:
    moment = now_utc or datetime.now(UTC).replace(tzinfo=None)
    material = {
        "config": str(Path(args.config).resolve()),
        "weights": str(Path(args.weights).resolve()),
        "start_date": args.start_date.isoformat(),
        "end_date": args.end_date.isoformat(),
        "symbols": list(args.symbols),
        "no_swap": bool(args.no_swap),
        "max_workers": args.max_workers,
        "rng_seed": args.rng_seed,
        "limit_folds": args.limit_folds,
        "limit_starts": args.limit_starts,
        "strategies": list(args.strategies) if args.strategies else list(DEFAULT_STRATEGY_NAMES),
    }
    digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()[:7]
    return f"{moment:%Y%m%d_%H%M%S}_{digest}"


def _default_window(today: Optional[date] = None) -> tuple[date, date]:
    end_date = today or datetime.now(UTC).date()
    return end_date - timedelta(days=365 * 10), end_date


def _canonical_symbol(item: dict) -> Optional[str]:
    ftmo = str(item.get("ftmo", "")).replace(".sim", "").upper()
    if len(ftmo) == 6 and ftmo.isalpha():
        return f"{ftmo[:3]}_{ftmo[3:]}"
    return None


def _load_full_config(config_path: Path) -> dict:
    return json.loads(config_path.read_text(encoding="utf-8"))


def _build_pair_specs(config: dict) -> dict[str, PairSpec]:
    specs: dict[str, PairSpec] = {}
    for item in config.get("instruments", []):
        symbol = _canonical_symbol(item)
        if symbol is None:
            continue
        specs[symbol] = PairSpec(
            symbol=symbol,
            pip_size=float(item["pip_size"]),
            contract_size=100_000,
        )
    if not specs:
        raise ValueError("config contains no usable instruments")
    return specs


def _select_symbols(config: dict, requested: Optional[str]) -> list[str]:
    available = [symbol for symbol in (_canonical_symbol(item) for item in config.get("instruments", [])) if symbol]
    if requested is None:
        return available
    selected = [symbol.strip().upper() for symbol in requested.split(",") if symbol.strip()]
    missing = sorted(set(selected) - set(available))
    if missing:
        raise ValueError(f"requested symbols are not present in config: {', '.join(missing)}")
    return selected


def _resolve_outputs(args: argparse.Namespace, run_id: str) -> tuple[Path, Path]:
    output_html = args.output_html or (DEFAULT_OUTPUT_HTML_DIR / f"bh_ftmo_gate_{run_id}.html")
    output_csv = args.output_csv or (DEFAULT_OUTPUT_CSV_DIR / f"bh_ftmo_gate_{run_id}.csv")
    return Path(output_html), Path(output_csv)


def _load_bars(
    symbols: list[str],
    start: datetime,
    end: datetime,
    *,
    store: FxStore | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    own_store = store is None
    resolved_store = store or FxStore(read_only=True)
    try:
        bars_4h = {symbol: resolved_store.load(symbol, granularity="H4", start=start, end=end) for symbol in symbols}
        bars_1h = {symbol: resolved_store.load(symbol, granularity="H1", start=start, end=end) for symbol in symbols}
    finally:
        if own_store:
            resolved_store.close()
    missing_4h = [symbol for symbol, frame in bars_4h.items() if frame.empty]
    missing_1h = [symbol for symbol, frame in bars_1h.items() if frame.empty]
    if missing_4h:
        raise ValueError(f"missing H4 bars for: {', '.join(missing_4h)}")
    if missing_1h:
        raise ValueError(f"missing H1 bars for: {', '.join(missing_1h)}")
    return bars_4h, bars_1h


def _mid_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    mid = pd.DataFrame({"timestamp": pd.to_datetime(frame["timestamp"])})
    mid["open"] = (frame["open_bid"] + frame["open_ask"]) / 2.0
    mid["high"] = (frame["high_bid"] + frame["high_ask"]) / 2.0
    mid["low"] = (frame["low_bid"] + frame["low_ask"]) / 2.0
    mid["close"] = (frame["close_bid"] + frame["close_ask"]) / 2.0
    return mid


def _compute_atr_by_symbol(bars_4h: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
    atr_by_symbol: dict[str, pd.Series] = {}
    for symbol, frame in bars_4h.items():
        # Engine looks up ATR via series.loc[bar_ts]; index must be timestamps.
        series = atr(_mid_ohlc(frame), period=14)
        series.index = pd.to_datetime(frame["timestamp"]).reset_index(drop=True)
        atr_by_symbol[symbol] = series
    return atr_by_symbol


def _generate_bh_ftmo_signals(
    bars_4h: dict[str, pd.DataFrame],
    weights_path: Path,
    symbols: list[str],
    strategy_names: list[str],
) -> list[Signal]:
    weights = load_weights(weights_path)
    available = {
        BaselineStrategy.name: lambda: BaselineStrategy(weights=weights),
        MeanReversionStrategy.name: lambda: MeanReversionStrategy(weights=weights),
        SandboxStrategy.name: lambda: SandboxStrategy(weights=weights),
    }
    strategies = [available[name]() for name in strategy_names]
    generator = SignalGenerator(strategies=strategies)
    return cluster_filter(generator.generate(bars_4h, symbols=symbols))


def _load_universe_filter_config(weights_path: Path, strategy_names: list[str]) -> UniverseFilterConfig:
    if SandboxStrategy.name not in strategy_names:
        return UniverseFilterConfig()
    weights = load_weights(weights_path)
    sandbox_weights = weights.get(SandboxStrategy.name, {})
    if not isinstance(sandbox_weights, dict):
        return UniverseFilterConfig()
    payload = sandbox_weights.get("universe_filter")
    return UniverseFilterConfig.from_mapping(payload if isinstance(payload, dict) else None)


def _apply_configured_universe_filter(
    symbols: list[str],
    bars_4h: dict[str, pd.DataFrame],
    config: UniverseFilterConfig,
) -> list[str]:
    passing = apply_universe_filter({symbol: bars_4h[symbol] for symbol in symbols}, config)
    filtered_symbols = [symbol for symbol in symbols if symbol in passing]
    if config.enabled:
        dropped = [symbol for symbol in symbols if symbol not in passing]
        LOG.info("universe filter dropped %d/%d pairs: %s", len(dropped), len(symbols), dropped)
        if not filtered_symbols:
            raise ValueError("universe filter dropped all pairs")
    return filtered_symbols


def _risk_overlay_config(weights_path: Path, strategy_names: list[str]) -> dict[str, dict]:
    weights = load_weights(weights_path)
    return {
        strategy_name: dict(weights[strategy_name]["risk_overlay"])
        for strategy_name in strategy_names
        if isinstance(weights.get(strategy_name, {}).get("risk_overlay"), dict)
    }


def _enumerate_starts(
    fold_iter: list,
    challenge_window_days: int,
    rng_seed_base: int,
    limit_folds: Optional[int],
    limit_starts: Optional[int],
) -> list[StartConfig]:
    starts: list[StartConfig] = []
    selected_folds = fold_iter[:limit_folds] if limit_folds is not None else fold_iter
    for fold_index, fold in enumerate(selected_folds):
        fold_starts = non_overlapping_starts(fold, challenge_window_days=challenge_window_days)
        if limit_starts is not None:
            fold_starts = fold_starts[:limit_starts]
        LOG.info("[fold %d/%d] enumerating %d starts", fold_index + 1, len(selected_folds), len(fold_starts))
        for start_day in fold_starts:
            start_ts = datetime.combine(start_day, time.min)
            starts.append(
                StartConfig(
                    start_ts=start_ts,
                    end_ts=start_ts + timedelta(days=challenge_window_days),
                    rng_seed=rng_seed_base + len(starts),
                )
            )
    return starts


def _combine_results_for_reporting(results: list[ChallengeResult]) -> ChallengeResult:
    if not results:
        raise ValueError("results must not be empty")
    template = results[0]
    all_trades = tuple(trade for result in results for trade in result.trades)
    all_breaches = tuple(breach for result in results for breach in result.breaches)
    combined_hourly = _concat_series([result.equity_curve for result in results], freq="1h")
    combined_daily = _concat_series([result.equity_curve_daily for result in results], freq="1D")
    pass_count = sum(result.outcome == "passed" for result in results)
    fail_count = sum(result.outcome == "failed" for result in results)
    push_count = sum(result.outcome == "push" for result in results)
    if pass_count >= max(fail_count, push_count):
        outcome = "passed"
    elif fail_count >= push_count:
        outcome = "failed"
    else:
        outcome = "push"
    return ChallengeResult(
        start_ts=min(result.start_ts for result in results),
        end_ts=max(result.end_ts for result in results),
        outcome=outcome,
        failed_by=template.failed_by,
        target_hit_at=min((result.target_hit_at for result in results if result.target_hit_at is not None), default=None),
        trading_days=sum(result.trading_days for result in results),
        final_equity_account_ccy=float(sum(result.final_equity_account_ccy for result in results) / len(results)),
        trades=all_trades,
        breaches=all_breaches,
        equity_curve=combined_hourly,
        equity_curve_daily=combined_daily,
        skipped_signals=tuple(item for result in results for item in result.skipped_signals),
        rng_seed=template.rng_seed,
        non_convertible_position_events=sum(result.non_convertible_position_events for result in results),
        n_blocked_entries=sum(result.n_blocked_entries for result in results),
        n_liquidations=sum(result.n_liquidations for result in results),
    )


def _concat_series(series_list: list[pd.Series], *, freq: str) -> pd.Series:
    pieces: list[pd.Series] = []
    cursor = datetime(2000, 1, 1)
    step = pd.Timedelta(freq).to_pytimedelta()
    for series in series_list:
        if series.empty:
            continue
        normalized = series.astype(float).reset_index(drop=True)
        normalized.index = pd.date_range(cursor, periods=len(normalized), freq=freq)
        pieces.append(normalized)
        cursor = normalized.index[-1].to_pydatetime() + step
    if not pieces:
        return pd.Series(dtype=float)
    return pd.concat(pieces)


def _inject_report_note(output_html: Path, note: str) -> None:
    html = output_html.read_text(encoding="utf-8")
    marker = "</header>"
    insert = f'<p><strong>Note:</strong> {note}</p>{marker}'
    if marker in html and note not in html:
        html = html.replace(marker, insert, 1)
        output_html.write_text(html, encoding="utf-8")


def _format_percent(value: float) -> str:
    return f"{value * 100.0:.1f}%"


def _criterion_row(
    label: str,
    actual: float,
    threshold: float,
    passed: bool,
    *,
    pct: bool = False,
    inverse: bool = False,
    plus_pp: bool = False,
    color: bool = False,
) -> str:
    actual_str = _format_percent(actual) if pct else f"{actual:.2f}"
    if plus_pp:
        actual_str = f"{actual:+.1f}pp"
    threshold_str = _format_percent(threshold) if pct else f"{threshold:.2f}"
    threshold_str = f"(≤ {threshold_str})" if inverse else f"(≥ {threshold_str})"
    status = "PASS" if passed else "FAIL"
    if color:
        status = f"\033[32m{status}\033[0m" if passed else f"\033[31m{status}\033[0m"
    return f" {label:<31} {actual_str:>8}  {threshold_str:<11} {status}"


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _render_verdict_block(run_id: str, gate_result, output_html: Path, output_csv: Path) -> str:
    criteria = {criterion.name: criterion for criterion in gate_result.criteria}
    color = sys.stdout.isatty()
    lines = [
        "============================================================",
        f" BH FTMO PHASE 3 GATE — RUN {run_id}",
        "============================================================",
        f" Verdict: {'PASSED' if gate_result.overall_passed else 'FAILED'}",
        "",
        _criterion_row("Sharpe (annualized, 1h basis):", criteria["sharpe"].actual, criteria["sharpe"].threshold, criteria["sharpe"].passed, color=color),
        _criterion_row("Profit factor:", criteria["profit_factor"].actual, criteria["profit_factor"].threshold, criteria["profit_factor"].passed, color=color),
        _criterion_row("Win rate:", criteria["win_rate"].actual, criteria["win_rate"].threshold, criteria["win_rate"].passed, pct=True, color=color),
        _criterion_row("Max drawdown:", criteria["max_dd"].actual, criteria["max_dd"].threshold, criteria["max_dd"].passed, pct=True, inverse=True, color=color),
        _criterion_row("FTMO pass-rate (lower 95% CI):", criteria["pass_rate_lower_ci"].actual, criteria["pass_rate_lower_ci"].threshold, criteria["pass_rate_lower_ci"].passed, pct=True, color=color),
        _criterion_row("Margin vs best baseline:", criteria["vs_best_baseline"].actual, criteria["vs_best_baseline"].threshold, criteria["vs_best_baseline"].passed, plus_pp=True, color=color),
        f"                                   (best baseline: {gate_result.best_baseline_name or 'n/a'} @ {_format_percent(gate_result.best_baseline_pass_rate)})",
        "",
        f" HTML report: {_display_path(output_html)}",
        f" CSV ledger:  {_display_path(output_csv)}",
        "============================================================",
    ]
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    """Run the Phase 3 gate and return a shell-friendly exit code."""
    args = build_parser().parse_args(argv)
    default_start, default_end = _default_window()
    args.start_date = args.start_date or default_start
    args.end_date = args.end_date or default_end

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    install_scrubber()

    try:
        config = _load_full_config(args.config)
        ftmo_config = load_ftmo_config(args.config)
        pair_specs = _build_pair_specs(config)
        args.symbols = _select_symbols(config, args.symbols)
        strategy_names = args.strategies or list(DEFAULT_STRATEGY_NAMES)
        run_id = _compute_run_id(args)
        output_html, output_csv = _resolve_outputs(args, run_id)

        if args.end_date < args.start_date:
            raise ValueError("--end-date must be on or after --start-date")

        LOG.info("run_id=%s symbols=%d start=%s end=%s", run_id, len(args.symbols), args.start_date, args.end_date)
        start_dt = datetime.combine(args.start_date, time.min)
        end_dt = datetime.combine(args.end_date + timedelta(days=1), time.min)

        client: Optional[OandaClient] = None
        try:
            if not args.no_swap:
                client = OandaClient(OandaConfig.from_env())
            swap_rates = fetch_or_load_cached(client, args.end_date, no_swap=args.no_swap)
            swap_rates = {symbol: swap_rates.get(symbol, SwapRates(0.0, 0.0)) for symbol in args.symbols}
        finally:
            if client is not None:
                client.close()

        LOG.info("loading bars for %d symbols", len(args.symbols))
        bars_4h, bars_1h = _load_bars(args.symbols, start_dt, end_dt)
        universe_filter_config = _load_universe_filter_config(args.weights, strategy_names)
        args.symbols = _apply_configured_universe_filter(args.symbols, bars_4h, universe_filter_config)
        swap_rates = {symbol: swap_rates[symbol] for symbol in args.symbols}
        atr_by_symbol = _compute_atr_by_symbol({symbol: bars_4h[symbol] for symbol in args.symbols})

        LOG.info("generating Phase 2b signals")
        bh_ftmo_signals = _generate_bh_ftmo_signals(
            {symbol: bars_4h[symbol] for symbol in args.symbols},
            args.weights,
            args.symbols,
            strategy_names,
        )

        folds = fold_windows(args.start_date, args.end_date)
        starts = _enumerate_starts(
            folds,
            challenge_window_days=int(ftmo_config["max_trading_days"]),
            rng_seed_base=args.rng_seed,
            limit_folds=args.limit_folds,
            limit_starts=args.limit_starts,
        )
        if not starts:
            raise ValueError("no walk-forward start dates were generated for the requested window")

        sizing_config = {
            "risk_pct_per_trade": float(config["risk"]["max_risk_per_trade_pct"]),
            "k_stop": 1.5,
            "k_target": 2.5,
            "max_concurrent_positions": int(config["risk"]["max_concurrent_positions"]),
        }

        LOG.info("running cohort across %d starts", len(starts))
        max_workers = _resolve_max_workers(strategy_names, args.max_workers)
        cohort_results_by_strategy = run_full_comparison(
            bars_4h={symbol: bars_4h[symbol] for symbol in args.symbols},
            bars_1h={symbol: bars_1h[symbol] for symbol in args.symbols},
            atr_by_symbol=atr_by_symbol,
            pair_specs={symbol: pair_specs[symbol] for symbol in args.symbols},
            ftmo_config=ftmo_config,
            sizing_config=sizing_config,
            swap_rates_by_symbol=swap_rates,
            bh_ftmo_signals=bh_ftmo_signals,
            starts=starts,
            rng_seed=args.rng_seed,
            max_workers=max_workers,
            risk_overlay_config=_risk_overlay_config(args.weights, strategy_names),
        )

        cohort_metrics_by_strategy = {
            strategy: cohort_metrics(results, bootstrap_b=1000, rng_seed=args.rng_seed)
            for strategy, results in cohort_results_by_strategy.items()
        }
        gate_result = evaluate_gate(
            cohort_results_by_strategy["bh_ftmo"],
            {name: results for name, results in cohort_results_by_strategy.items() if name != "bh_ftmo"},
            bootstrap_b=1000,
            rng_seed=args.rng_seed,
        )

        report_results = {
            strategy: _combine_results_for_reporting(results)
            for strategy, results in cohort_results_by_strategy.items()
        }
        render_html_report(
            report_results,
            output_html,
            cohort_metrics_by_strategy=cohort_metrics_by_strategy,
            cohort_results_by_strategy=cohort_results_by_strategy,
            gate_result=gate_result,
            title="BH FTMO Phase 3 Gate Report",
            run_id=run_id,
        )
        _inject_report_note(output_html, SWAP_APPROXIMATION_NOTE)
        write_csv_ledger(report_results, output_csv)

        sys.stdout.write(_render_verdict_block(run_id, gate_result, output_html, output_csv))
        sys.stdout.write("\n")
        return 0 if gate_result.overall_passed else 1
    except (FtmoConfigUnverifiedError, OandaError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
