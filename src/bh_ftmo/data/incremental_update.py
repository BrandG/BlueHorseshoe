"""Incremental top-up of fx_4h.duckdb with the latest OANDA bars.

Designed to run every 4 hours via cron. For each (symbol, granularity):

  1. Read ``store.latest_timestamp(only_complete=True)``
  2. Fetch OANDA candles in ``(latest, now]``
  3. Upsert via ``store.save_candles`` (skips incomplete bars by default)

Per-symbol errors are isolated — one flaky pair doesn't block the rest. Any
failure (partial or total) sends an email via the same SMTP env vars ``backup.sh``
uses. Intended cron line:

    0 */4 * * * cd /root/BlueHorseshoe && ./run.sh python -m bh_ftmo.data.incremental_update >> /root/BlueHorseshoe/src/logs/bh_ftmo_incremental.log 2>&1

Exit codes:
  0 — at least one (symbol, granularity) pair succeeded (may include partial failures)
  1 — every pair failed (systemic issue: auth rejected, OANDA down, etc.)
  2 — config error (token/account missing, bad CLI args)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import smtplib
import socket
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from bh_ftmo.data.backfill import _fmt_rfc3339, _load_ftmo_instruments
from bh_ftmo.data.fx_store import FxStore, Granularity
from bh_ftmo.data.oanda_client import OandaAuthError, OandaClient, OandaError
from bh_ftmo.data.validate import summarize_issues, validate_candles
from bh_ftmo.logging.scrubber import install as install_scrubber

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = REPO_ROOT / "src" / "bh_ftmo_config.json"

log = logging.getLogger("bh_ftmo.data.incremental_update")


@dataclass
class PairResult:
    symbol: str
    granularity: Granularity
    bars_saved: int = 0
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    error: Optional[str] = None
    issues_summary: dict = field(default_factory=dict)


def update_one(
    client: OandaClient,
    store: FxStore,
    *,
    symbol: str,
    granularity: Granularity,
    provider: str = "oanda",
    validate: bool = True,
    now_utc: Optional[datetime] = None,
) -> PairResult:
    """Fetch and upsert bars newer than the store's latest for one pair.

    Raises nothing normally; captures per-pair errors in ``PairResult.error``.
    ``OandaAuthError`` is the one exception that propagates (caller halts).
    """
    result = PairResult(symbol=symbol, granularity=granularity)
    latest = store.latest_timestamp(symbol, granularity=granularity, only_complete=True)
    if latest is None:
        result.error = "no bars in store (run backfill first)"
        return result

    start = latest + timedelta(seconds=1)  # OANDA `from` is inclusive
    end = now_utc or datetime.now(timezone.utc).replace(tzinfo=None)
    result.start = start
    result.end = end
    if start >= end:
        return result

    try:
        all_issues = []
        for page in client.iter_candles_paginated(
            symbol,
            granularity=granularity,
            start=_fmt_rfc3339(start),
            end=_fmt_rfc3339(end),
            price="BA",
        ):
            if not page:
                continue
            if validate:
                issues = validate_candles(page, symbol=symbol)
                if issues:
                    all_issues.extend(issues)
            written = store.save_candles(
                symbol,
                page,
                granularity=granularity,
                provider=provider,
                include_incomplete=False,
            )
            result.bars_saved += written
        if all_issues:
            result.issues_summary = {k.value: v for k, v in summarize_issues(all_issues).items()}
    except OandaAuthError:
        raise  # caller must halt the whole run
    except OandaError as exc:
        result.error = f"OANDA: {exc}"
    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {exc}"
    return result


@dataclass
class RunSummary:
    total: int
    succeeded: int  # pairs with no error (may have bars_saved == 0)
    failed_pairs: list[PairResult]
    bars_saved_total: int
    auth_failure: bool = False
    config_error: Optional[str] = None


def run(
    client: OandaClient,
    store: FxStore,
    *,
    symbols: list[str],
    granularities: list[Granularity],
    validate: bool = True,
    now_utc: Optional[datetime] = None,
) -> tuple[RunSummary, list[PairResult]]:
    """Execute update across every (symbol, granularity) pair."""
    results: list[PairResult] = []
    failed: list[PairResult] = []
    bars_total = 0
    auth_failed = False

    for sym in symbols:
        if auth_failed:
            break
        for gran in granularities:
            try:
                r = update_one(client, store, symbol=sym, granularity=gran, validate=validate, now_utc=now_utc)
            except OandaAuthError as exc:
                log.error("auth rejected; halting: %s", exc)
                auth_failed = True
                # Record a synthetic failure for every remaining pair so the
                # summary reflects actual state.
                r = PairResult(symbol=sym, granularity=gran, error=f"auth: {exc}")
                results.append(r)
                failed.append(r)
                break
            results.append(r)
            if r.error:
                failed.append(r)
            else:
                bars_total += r.bars_saved

    total = len(symbols) * len(granularities)
    summary = RunSummary(
        total=total,
        succeeded=len(results) - len(failed),
        failed_pairs=failed,
        bars_saved_total=bars_total,
        auth_failure=auth_failed,
    )
    return summary, results


# ---- Email alerting ----------------------------------------------------


def _format_failure_body(summary: RunSummary, results: list[PairResult]) -> str:
    lines = [
        f"Host:       {socket.gethostname()}",
        f"Time (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Total:      {summary.total} pair(s)",
        f"Succeeded:  {summary.succeeded}",
        f"Failed:     {len(summary.failed_pairs)}",
        f"Bars saved: {summary.bars_saved_total}",
        "",
    ]
    if summary.auth_failure:
        lines.append("!! OANDA auth rejected — rotate token or verify .env !!")
        lines.append("")
    if summary.failed_pairs:
        lines.append("Failed pairs:")
        for p in summary.failed_pairs:
            lines.append(f"  {p.symbol} {p.granularity}: {p.error}")
    return "\n".join(lines)


def send_failure_email(
    subject: str,
    body: str,
    *,
    smtp_module=smtplib,
) -> bool:
    """Send an alert email via SMTP_* env vars. Returns True on success, False otherwise.

    Mirrors the convention used by backup.sh: silently no-op if SMTP isn't
    configured, log a warning if the send itself fails (don't crash).
    """
    server = os.environ.get("SMTP_SERVER")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    recipient = os.environ.get("EMAIL_RECIPIENT")
    sender = os.environ.get("EMAIL_SENDER", user or "bh-ftmo@localhost")
    port = int(os.environ.get("SMTP_PORT", "587"))

    if not (server and user and password and recipient):
        log.warning("SMTP not fully configured (need SMTP_SERVER/USER/PASSWORD + EMAIL_RECIPIENT) — skipping alert")
        return False

    msg = MIMEText(body)
    msg["Subject"] = f"[BH FTMO] {subject}"
    msg["From"] = sender
    msg["To"] = recipient

    try:
        with smtp_module.SMTP(server, port, timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.sendmail(sender, [recipient], msg.as_string())
        log.info("alert email sent to %s", recipient)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("alert email failed (%s): %s", type(exc).__name__, exc)
        return False


# ---- CLI ---------------------------------------------------------------


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Incremental BH FTMO FX update.")
    p.add_argument("--symbols", help="Comma-separated OANDA symbols (default: all FTMO)")
    p.add_argument(
        "--granularities",
        default="H4,H1",
        help="Comma-separated granularities (default: H4,H1)",
    )
    p.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="bh_ftmo_config.json path")
    p.add_argument("--dry-run", action="store_true", help="Print plan, exit without fetching")
    p.add_argument("--no-validate", action="store_true", help="Skip pre-ingestion candle validation")
    p.add_argument("--no-email", action="store_true", help="Don't send alert email on failure")
    p.add_argument("--db-path", help="Override FxStore path")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    install_scrubber()

    config_path = Path(args.config)
    symbols = (
        [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else _load_ftmo_instruments(config_path)
    )
    granularities: list[Granularity] = [g.strip() for g in args.granularities.split(",") if g.strip()]  # type: ignore[list-item]
    for g in granularities:
        if g not in ("H1", "H4"):
            print(f"unsupported granularity: {g!r}", file=sys.stderr)
            return 2

    print(f"BH FTMO incremental update: {len(symbols)} symbols × {len(granularities)} granularities")
    if args.dry_run:
        print(f"  symbols: {', '.join(symbols)}")
        print(f"  granularities: {granularities}")
        return 0

    try:
        client = OandaClient()
    except OandaError as exc:
        msg = f"OANDA config error: {exc}"
        print(msg, file=sys.stderr)
        if not args.no_email:
            send_failure_email("incremental update: config error", f"{msg}\n\nHost: {socket.gethostname()}")
        return 2

    store = FxStore(db_path=args.db_path) if args.db_path else FxStore()
    try:
        with client:
            summary, results = run(
                client,
                store,
                symbols=symbols,
                granularities=granularities,
                validate=not args.no_validate,
            )
    finally:
        store.close()

    # Per-pair summary lines
    for r in results:
        if r.error:
            print(f"  FAIL {r.symbol} {r.granularity}: {r.error}")
        elif r.bars_saved > 0:
            extras = f" issues={r.issues_summary}" if r.issues_summary else ""
            print(f"  {r.symbol} {r.granularity}: +{r.bars_saved} bars{extras}")

    print()
    print(
        f"Summary: {summary.succeeded}/{summary.total} succeeded, "
        f"{summary.bars_saved_total} bars saved, {len(summary.failed_pairs)} failed"
    )

    if summary.failed_pairs and not args.no_email:
        severity = "TOTAL FAILURE" if summary.succeeded == 0 else "partial failure"
        send_failure_email(
            f"incremental update: {severity} ({len(summary.failed_pairs)}/{summary.total})",
            _format_failure_body(summary, results),
        )

    if summary.succeeded == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
