"""10-year resumable backfill of OANDA 4h + 1h forex bars.

Per plan decision 1-4 + Phase 1 "Data Foundation" section. Pulls every FTMO
instrument from ``src/bh_ftmo_config.json``, fetches H4 + H1 candles from OANDA
v20, validates and saves them via :class:`FxStore`.

Checkpointing is year-chunked: a ``(symbol, granularity, year)`` triple marked
complete is skipped on resume. An interrupted mid-year run re-downloads only
the current year (idempotent via FxStore upsert). Checkpoint lives at
``data/fx_backfill_checkpoint.json`` by default.

Usage:
    ./run.sh python -m bh_ftmo.data.backfill --years 10
    ./run.sh python -m bh_ftmo.data.backfill --symbols EUR_USD,USD_JPY --dry-run
    ./run.sh python -m bh_ftmo.data.backfill --granularities H4 --years 1
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Protocol

from bh_ftmo.data.fx_store import FxStore, Granularity
from bh_ftmo.data.oanda_client import OandaClient, OandaError
from bh_ftmo.data.validate import (
    IssueKind,
    ValidationIssue,
    summarize_issues,
    validate_candles,
)
from bh_ftmo.logging.scrubber import install as install_scrubber

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CHECKPOINT_PATH = REPO_ROOT / "data" / "fx_backfill_checkpoint.json"
DEFAULT_CONFIG_PATH = REPO_ROOT / "src" / "bh_ftmo_config.json"

log = logging.getLogger("bh_ftmo.data.backfill")


# ---- Client protocol for testability -----------------------------------


class CandleClient(Protocol):
    """Minimal surface :func:`backfill_symbol` needs from an OANDA client."""

    def iter_candles_paginated(
        self,
        instrument: str,
        *,
        granularity: str = ...,
        start: str,
        end: Optional[str] = ...,
        price: str = ...,
        page_size: int = ...,
    ) -> Iterable[list[dict[str, Any]]]: ...


# ---- Checkpoint store --------------------------------------------------


class CheckpointStore:
    """JSON-backed checkpoint tracking per-(symbol, granularity) progress."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict[str, dict[str, Any]]] = self._load()

    def _load(self) -> dict[str, dict[str, dict[str, Any]]]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("checkpoint load failed at %s: %s — starting fresh", self._path, exc)
            return {}

    def _section(self, symbol: str, granularity: Granularity) -> dict[str, Any]:
        sym = self._data.setdefault(symbol, {})
        return sym.setdefault(granularity, {})

    def get_completed_years(self, symbol: str, granularity: Granularity) -> set[int]:
        section = self._data.get(symbol, {}).get(granularity, {})
        return set(section.get("completed_years", []))

    def add_completed_year(self, symbol: str, granularity: Granularity, year: int) -> None:
        section = self._section(symbol, granularity)
        years = set(section.get("completed_years", []))
        years.add(year)
        section["completed_years"] = sorted(years)

    def get_latest_saved(self, symbol: str, granularity: Granularity) -> Optional[datetime]:
        val = self._data.get(symbol, {}).get(granularity, {}).get("latest_saved")
        if not val:
            return None
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            return None

    def update_latest_saved(
        self,
        symbol: str,
        granularity: Granularity,
        timestamp: datetime,
    ) -> None:
        section = self._section(symbol, granularity)
        section["latest_saved"] = timestamp.isoformat()

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)


# ---- Per-symbol backfill ----------------------------------------------


@dataclass
class BackfillResult:
    symbol: str
    granularity: Granularity
    years_processed: list[int] = field(default_factory=list)
    years_skipped: list[int] = field(default_factory=list)
    bars_saved: int = 0
    issues: list[ValidationIssue] = field(default_factory=list)
    error: Optional[str] = None


def _year_bounds_utc(year: int) -> tuple[datetime, datetime]:
    """Return (year_start, year_end_exclusive) as tz-naive UTC datetimes."""
    return datetime(year, 1, 1), datetime(year + 1, 1, 1)


def _fmt_rfc3339(dt: datetime) -> str:
    """OANDA's from/to params want RFC3339 UTC strings with 'Z' suffix."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def backfill_symbol(
    client: CandleClient,
    store: FxStore,
    *,
    symbol: str,
    granularity: Granularity,
    start: datetime,
    end: datetime,
    checkpoint: Optional[CheckpointStore] = None,
    provider: str = "oanda",
    validate: bool = True,
    include_incomplete: bool = False,
    page_size: int = 5000,
) -> BackfillResult:
    """Backfill one (symbol, granularity) from ``start`` (inclusive) to ``end`` (exclusive).

    Iterates calendar years, skipping those marked complete in ``checkpoint``.
    Safe to re-run: every OANDA page is upserted via :meth:`FxStore.save_candles`.
    """
    if start >= end:
        return BackfillResult(symbol=symbol, granularity=granularity)

    result = BackfillResult(symbol=symbol, granularity=granularity)
    completed = checkpoint.get_completed_years(symbol, granularity) if checkpoint else set()

    today_year = datetime.now(timezone.utc).year
    first_year = start.year
    last_year = (end - timedelta(microseconds=1)).year

    for year in range(first_year, last_year + 1):
        if year in completed:
            result.years_skipped.append(year)
            continue

        y_start, y_end_excl = _year_bounds_utc(year)
        chunk_start = max(y_start, start)
        chunk_end = min(y_end_excl, end)
        if chunk_start >= chunk_end:
            continue

        try:
            pages = client.iter_candles_paginated(
                symbol,
                granularity=granularity,
                start=_fmt_rfc3339(chunk_start),
                end=_fmt_rfc3339(chunk_end),
                price="BA",
                page_size=page_size,
            )
            for page in pages:
                if not page:
                    continue
                if validate:
                    issues = validate_candles(page, symbol=symbol)
                    if issues:
                        result.issues.extend(issues)
                written = store.save_candles(
                    symbol,
                    page,
                    granularity=granularity,
                    provider=provider,
                    include_incomplete=include_incomplete,
                )
                result.bars_saved += written
                if page and checkpoint is not None:
                    last_ts = page[-1].get("time")
                    if last_ts:
                        try:
                            parsed = datetime.fromisoformat(last_ts.rstrip("Z").split(".")[0])
                            checkpoint.update_latest_saved(symbol, granularity, parsed)
                        except ValueError:
                            pass
        except OandaError as exc:
            result.error = f"OANDA error on year {year}: {exc}"
            log.error("backfill %s %s year %d failed: %s", symbol, granularity, year, exc)
            if checkpoint is not None:
                checkpoint.save()
            return result

        # Only mark a year complete if it's fully past (not the partial tail).
        if y_end_excl <= end:
            result.years_processed.append(year)
            if checkpoint is not None:
                checkpoint.add_completed_year(symbol, granularity, year)

    if checkpoint is not None:
        checkpoint.save()
    return result


# ---- Multi-symbol orchestration ---------------------------------------


def backfill_all(
    client: CandleClient,
    store: FxStore,
    *,
    symbols: list[str],
    granularities: list[Granularity],
    start: datetime,
    end: datetime,
    checkpoint: Optional[CheckpointStore] = None,
    provider: str = "oanda",
    validate: bool = True,
    progress: Optional[Callable[[str], None]] = None,
) -> list[BackfillResult]:
    """Run :func:`backfill_symbol` for every ``(symbol, granularity)`` pair."""
    results: list[BackfillResult] = []
    total = len(symbols) * len(granularities)
    pair_idx = 0
    for sym in symbols:
        for gran in granularities:
            pair_idx += 1
            if progress:
                progress(f"[{pair_idx}/{total}] {sym} {gran} starting")
            r = backfill_symbol(
                client,
                store,
                symbol=sym,
                granularity=gran,
                start=start,
                end=end,
                checkpoint=checkpoint,
                provider=provider,
                validate=validate,
            )
            results.append(r)
            if progress:
                n_done = len(r.years_processed)
                n_skip = len(r.years_skipped)
                issue_summary = summarize_issues(r.issues)
                progress(
                    f"[{pair_idx}/{total}] {sym} {gran} done: "
                    f"{r.bars_saved} bars, years={n_done} skipped={n_skip}, issues={dict(issue_summary)}"
                )
    return results


# ---- CLI ---------------------------------------------------------------


def _load_ftmo_instruments(config_path: Path) -> list[str]:
    """Read bh_ftmo_config.json and return the OANDA-format instrument list."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    out: list[str] = []
    for item in config.get("instruments", []):
        ftmo = item.get("ftmo", "")
        base = ftmo.replace(".sim", "").upper()
        if len(base) == 6 and base.isalpha():
            out.append(f"{base[:3]}_{base[3:]}")
    return out


def _default_start(years_back: int, now_utc: Optional[datetime] = None) -> datetime:
    now = now_utc or datetime.now(timezone.utc).replace(tzinfo=None)
    return datetime(now.year - years_back, 1, 1)


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill OANDA FX bars into FxStore.")
    p.add_argument("--symbols", help="Comma-separated OANDA symbols (default: all FTMO)")
    p.add_argument(
        "--granularities",
        default="H4,H1",
        help="Comma-separated granularities (default: H4,H1)",
    )
    p.add_argument("--years", type=int, default=10, help="Years back from now (default: 10)")
    p.add_argument("--end", help="End date ISO (default: now UTC)")
    p.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT_PATH), help="Checkpoint JSON path")
    p.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="bh_ftmo_config.json path")
    p.add_argument("--dry-run", action="store_true", help="Print plan and exit without fetching")
    p.add_argument("--no-checkpoint", action="store_true", help="Do not load or write checkpoint")
    p.add_argument("--no-validate", action="store_true", help="Skip pre-ingestion candle validation")
    p.add_argument("--db-path", help="Override FxStore path (defaults to data/fx_4h.duckdb)")
    return p.parse_args(argv)


def _progress(line: str) -> None:
    print(line, flush=True)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    install_scrubber()  # Decision C-2: scrub tokens from any log output before OANDA calls

    config_path = Path(args.config)
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = _load_ftmo_instruments(config_path)
    granularities = [g.strip() for g in args.granularities.split(",") if g.strip()]
    for g in granularities:
        if g not in ("H1", "H4"):
            print(f"unsupported granularity: {g!r}", file=sys.stderr)
            return 2

    end_utc = (
        datetime.fromisoformat(args.end).replace(tzinfo=None)
        if args.end
        else datetime.now(timezone.utc).replace(tzinfo=None)
    )
    start_utc = _default_start(args.years, now_utc=end_utc)

    print(f"Backfill plan: {len(symbols)} symbols × {len(granularities)} granularities")
    print(f"  range: {start_utc.isoformat()} → {end_utc.isoformat()} (UTC)")
    print(f"  symbols: {', '.join(symbols[:5])}{'...' if len(symbols) > 5 else ''}")
    print(f"  granularities: {granularities}")
    print(f"  checkpoint: {args.checkpoint if not args.no_checkpoint else '(disabled)'}")
    if args.dry_run:
        return 0

    try:
        client = OandaClient()
    except OandaError as exc:
        print(f"OANDA config error: {exc}", file=sys.stderr)
        return 2

    store = FxStore(db_path=args.db_path) if args.db_path else FxStore()
    checkpoint = None if args.no_checkpoint else CheckpointStore(Path(args.checkpoint))

    with client:
        try:
            results = backfill_all(
                client,
                store,
                symbols=symbols,
                granularities=granularities,  # type: ignore[arg-type]
                start=start_utc,
                end=end_utc,
                checkpoint=checkpoint,
                validate=not args.no_validate,
                progress=_progress,
            )
        finally:
            store.close()

    total_bars = sum(r.bars_saved for r in results)
    errors = [r for r in results if r.error]
    total_issues = sum(len(r.issues) for r in results)
    data_gaps = sum(
        sum(1 for i in r.issues if i.kind == IssueKind.DATA_GAP) for r in results
    )

    print()
    print("Backfill complete.")
    print(f"  pairs processed: {len(results)}")
    print(f"  bars saved:      {total_bars:,}")
    print(f"  errors:          {len(errors)}")
    print(f"  issues total:    {total_issues}")
    print(f"  data gaps:       {data_gaps}")

    if errors:
        for r in errors:
            print(f"    ERROR {r.symbol} {r.granularity}: {r.error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
