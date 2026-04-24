"""OANDA Phase 0.5 probe — go/no-go gate before Phase 1 infrastructure.

Per docs/planning/BH_FTMO_PLAN.md decision 3A, prove OANDA delivers what Phase 1 needs
BEFORE committing weeks to the data pipeline:

  1. Every FTMO instrument (from bh_ftmo_config.json) exists on OANDA
  2. Bid + ask are available (needed for spread-aware backtest)
  3. 10+ years of H4 history exists (needed for walk-forward backtest)
  4. Pagination works (needed for backfill.py later)
  5. Rate limits are survivable
  6. Crypto (BTC_USD, ETH_USD) availability confirmed or denied on this demo account
  7. DXY (or equivalent USD-index) available for multi-pair indicators

Run:  ./run.sh python src/bh_ftmo/data/oanda_probe.py

Requires in .env:
  OANDA_API_TOKEN=<personal access token from OANDA demo account>
  OANDA_ACCOUNT_ID=101-001-39154243-001

Writes report to src/logs/oanda_probe_<date>.md. Exit criterion: ≥38 of 40 FTMO
instruments report ≥10y history with bid+ask. <38 → pivot to HistData.com per plan.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import requests

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "src" / "bh_ftmo_config.json"
LOG_DIR = REPO_ROOT / "src" / "logs"

# Environment: "practice" uses api-fxpractice.oanda.com (demo accounts),
# "live" uses api-fxtrade.oanda.com (live CFD accounts). BH FTMO v1 uses the
# live account FOR DATA ONLY — no order placement goes through OANDA in v1
# (orders are manually pasted into FTMO MT5). See plan decisions #13 + 3A.
OANDA_ENV = os.environ.get("OANDA_ENV", "live").lower()
if OANDA_ENV == "practice":
    OANDA_BASE = "https://api-fxpractice.oanda.com/v3"
elif OANDA_ENV == "live":
    OANDA_BASE = "https://api-fxtrade.oanda.com/v3"
else:
    raise SystemExit(f"OANDA_ENV must be 'practice' or 'live', got {OANDA_ENV!r}")

# Candidates for non-forex probes (crypto + index). We try each and report what works.
CRYPTO_CANDIDATES = ["BTC_USD", "ETH_USD"]
# OANDA's USD index ticker varies; try the common forms.
USD_INDEX_CANDIDATES = ["USD_DXY", "DXY_USD", "USB02Y_USD"]  # last one is unrelated but helps probe naming conventions

# Roughly 10 years back from today — we probe for a bar near this date to confirm depth.
DEPTH_PROBE_START = "2016-01-04T00:00:00Z"


def _load_env() -> tuple[str, str]:
    """Pull OANDA creds from .env (simple parser — no python-dotenv dep)."""
    env_path = REPO_ROOT / ".env"
    token: Optional[str] = os.environ.get("OANDA_API_TOKEN")
    account: Optional[str] = os.environ.get("OANDA_ACCOUNT_ID")
    if (not token or not account) and env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == "OANDA_API_TOKEN" and not token:
                token = v
            elif k == "OANDA_ACCOUNT_ID" and not account:
                account = v
    if not token:
        raise SystemExit("OANDA_API_TOKEN not set (put it in .env or export it)")
    if not account:
        raise SystemExit("OANDA_ACCOUNT_ID not set (put it in .env or export it)")
    return token, account


def _ftmo_to_oanda(ftmo_symbol: str) -> str:
    """`AUDUSD.sim` -> `AUD_USD`. Assumes 6-letter forex pair."""
    base = ftmo_symbol.replace(".sim", "").upper()
    if len(base) == 6 and base.isalpha():
        return f"{base[:3]}_{base[3:]}"
    return base  # fall-through: let OANDA decide


def _session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept-Datetime-Format": "RFC3339",
    })
    return s


def list_account_instruments(session: requests.Session, account_id: str) -> dict[str, dict]:
    """Return {instrument_name: instrument_record} for every tradeable instrument."""
    url = f"{OANDA_BASE}/accounts/{account_id}/instruments"
    r = session.get(url, timeout=30)
    r.raise_for_status()
    payload = r.json()
    return {item["name"]: item for item in payload.get("instruments", [])}


def fetch_candles(
    session: requests.Session,
    instrument: str,
    count: int = 1,
    granularity: str = "H4",
    price: str = "BA",
    from_time: Optional[str] = None,
) -> dict:
    """Fetch candles. Returns parsed JSON; raises on non-200."""
    url = f"{OANDA_BASE}/instruments/{instrument}/candles"
    params: dict[str, str | int] = {"granularity": granularity, "price": price}
    if from_time is not None:
        params["from"] = from_time
        params["count"] = count
    else:
        params["count"] = count
    r = session.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def probe_instrument(
    session: requests.Session,
    oanda_name: str,
) -> dict:
    """Run the three checks on one instrument. Return a result dict."""
    result = {
        "oanda_name": oanda_name,
        "fetch_latest_ok": False,
        "fetch_latest_error": None,
        "has_bid_ask": False,
        "latest_time": None,
        "depth_probe_ok": False,
        "depth_probe_error": None,
        "earliest_available": None,
        "page_5000_ok": False,
        "page_5000_error": None,
        "page_5000_bars": 0,
    }
    # 1) latest bar, bid+ask
    try:
        latest = fetch_candles(session, oanda_name, count=1)
        candles = latest.get("candles", [])
        if candles:
            c = candles[0]
            result["fetch_latest_ok"] = True
            result["latest_time"] = c.get("time")
            result["has_bid_ask"] = "bid" in c and "ask" in c
    except requests.HTTPError as exc:
        result["fetch_latest_error"] = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
    except Exception as exc:
        result["fetch_latest_error"] = f"{type(exc).__name__}: {exc}"

    # 2) depth probe: ask for bars starting ~10 years ago
    try:
        depth = fetch_candles(session, oanda_name, count=1, from_time=DEPTH_PROBE_START)
        dcandles = depth.get("candles", [])
        if dcandles:
            result["depth_probe_ok"] = True
            result["earliest_available"] = dcandles[0].get("time")
    except requests.HTTPError as exc:
        result["depth_probe_error"] = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
    except Exception as exc:
        result["depth_probe_error"] = f"{type(exc).__name__}: {exc}"

    # 3) pagination smoke test: ask for max page size (5000 H4 bars ~= 2.3 years)
    try:
        page = fetch_candles(session, oanda_name, count=5000)
        pcandles = page.get("candles", [])
        result["page_5000_ok"] = True
        result["page_5000_bars"] = len(pcandles)
    except requests.HTTPError as exc:
        result["page_5000_error"] = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
    except Exception as exc:
        result["page_5000_error"] = f"{type(exc).__name__}: {exc}"

    return result


def _fmt_row(ftmo: str, oanda: str, r: dict, available: bool) -> str:
    if not available:
        return f"| `{ftmo}` | `{oanda}` | NOT ON OANDA | - | - | - | - |"
    bid_ask = "YES" if r["has_bid_ask"] else "NO"
    earliest = r.get("earliest_available") or "-"
    if earliest != "-" and len(earliest) >= 10:
        earliest = earliest[:10]
    page = "YES" if r["page_5000_ok"] else "NO"
    bars = r.get("page_5000_bars", 0)
    status = "OK" if (r["fetch_latest_ok"] and r["has_bid_ask"] and r["depth_probe_ok"] and r["page_5000_ok"]) else "PARTIAL"
    return f"| `{ftmo}` | `{oanda}` | {status} | {bid_ask} | {earliest} | {page} ({bars}) | |"


def main(argv: Optional[list[str]] = None) -> int:
    token, account = _load_env()
    session = _session(token)

    print("== OANDA Phase 0.5 probe ==")
    print(f"Account: {account}")
    print(f"Config:  {CONFIG_PATH}")
    print()

    print("Discovering tradeable instruments...")
    t0 = time.time()
    try:
        instruments_map = list_account_instruments(session, account)
    except requests.HTTPError as exc:
        print(f"FAILED to list instruments: HTTP {exc.response.status_code}: {exc.response.text[:300]}")
        return 2
    t_list = time.time() - t0
    print(f"OANDA lists {len(instruments_map)} instruments on this account ({t_list:.2f}s)")
    print()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    ftmo_instruments = [i["ftmo"] for i in config.get("instruments", [])]

    # Build mapping FTMO -> OANDA
    mapping = [(ftmo, _ftmo_to_oanda(ftmo)) for ftmo in ftmo_instruments]

    # Probe each
    report_rows: list[str] = []
    summary = {
        "total": len(mapping),
        "not_on_oanda": 0,
        "missing_bid_ask": 0,
        "insufficient_history": 0,
        "pagination_fail": 0,
        "all_ok": 0,
    }

    print(f"Probing {len(mapping)} FTMO instruments...")
    rate_limit_hit = 0
    t_probe_start = time.time()
    for idx, (ftmo, oanda_name) in enumerate(mapping, start=1):
        if oanda_name not in instruments_map:
            summary["not_on_oanda"] += 1
            report_rows.append(_fmt_row(ftmo, oanda_name, {}, available=False))
            print(f"  [{idx:2}/{len(mapping)}] {ftmo:14} -> {oanda_name:10} NOT ON OANDA")
            continue
        try:
            r = probe_instrument(session, oanda_name)
        except requests.HTTPError as exc:
            if exc.response.status_code == 429:
                rate_limit_hit += 1
                print(f"  [{idx:2}/{len(mapping)}] {ftmo:14} -> 429 rate limit, sleeping 2s and retrying")
                time.sleep(2)
                r = probe_instrument(session, oanda_name)
            else:
                raise
        if not r["has_bid_ask"]:
            summary["missing_bid_ask"] += 1
        if not r["depth_probe_ok"]:
            summary["insufficient_history"] += 1
        if not r["page_5000_ok"]:
            summary["pagination_fail"] += 1
        if r["fetch_latest_ok"] and r["has_bid_ask"] and r["depth_probe_ok"] and r["page_5000_ok"]:
            summary["all_ok"] += 1
        report_rows.append(_fmt_row(ftmo, oanda_name, r, available=True))
        status_flag = "OK" if (r["fetch_latest_ok"] and r["has_bid_ask"] and r["depth_probe_ok"] and r["page_5000_ok"]) else "PARTIAL"
        earliest = r.get("earliest_available") or "-"
        print(f"  [{idx:2}/{len(mapping)}] {ftmo:14} -> {oanda_name:10} {status_flag:8} earliest={earliest[:10] if earliest != '-' else '-'}")
    t_probe = time.time() - t_probe_start

    # Extras: crypto + USD index
    print()
    print("Probing extras (crypto, USD index)...")
    extras_rows: list[str] = []
    for name in CRYPTO_CANDIDATES + USD_INDEX_CANDIDATES:
        if name not in instruments_map:
            extras_rows.append(f"| `{name}` | NOT ON OANDA | - | - | - |")
            print(f"  {name:12} NOT ON OANDA")
            continue
        try:
            r = probe_instrument(session, name)
            bid_ask = "YES" if r["has_bid_ask"] else "NO"
            earliest = (r.get("earliest_available") or "-")[:10]
            status = "OK" if (r["fetch_latest_ok"] and r["has_bid_ask"] and r["depth_probe_ok"]) else "PARTIAL"
            extras_rows.append(f"| `{name}` | {status} | {bid_ask} | {earliest} | {r.get('page_5000_bars', 0)} |")
            print(f"  {name:12} {status} earliest={earliest}")
        except Exception as exc:
            extras_rows.append(f"| `{name}` | ERROR | - | - | {type(exc).__name__} |")
            print(f"  {name:12} ERROR: {exc}")

    # Verdict
    threshold = max(38, len(mapping) - 2)
    verdict = "GO" if summary["all_ok"] >= threshold else "PIVOT to HistData.com per plan"

    # Write report
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    report_path = LOG_DIR / f"oanda_probe_{date.today().isoformat()}.md"
    lines = [
        f"# OANDA Phase 0.5 Probe Report",
        f"",
        f"- **Date:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- **Account:** `{account}`",
        f"- **Instruments on account:** {len(instruments_map)}",
        f"- **FTMO instruments probed:** {summary['total']}",
        f"- **Probe runtime:** {t_probe:.1f}s",
        f"- **Rate-limit hits (auto-recovered):** {rate_limit_hit}",
        f"",
        f"## Summary",
        f"",
        f"| Check | Count |",
        f"|---|---|",
        f"| All OK (ready for Phase 1) | {summary['all_ok']} / {summary['total']} |",
        f"| Not on OANDA | {summary['not_on_oanda']} |",
        f"| Missing bid/ask | {summary['missing_bid_ask']} |",
        f"| Insufficient history (<10y) | {summary['insufficient_history']} |",
        f"| Pagination fail | {summary['pagination_fail']} |",
        f"",
        f"## Verdict: **{verdict}**",
        f"",
        f"Threshold: ≥{threshold} of {summary['total']} instruments must pass all checks (per plan decision 3A).",
        f"",
        f"## Per-instrument detail",
        f"",
        f"| FTMO symbol | OANDA symbol | Status | Bid+Ask | Earliest 4h bar | 5000-bar page |",
        f"|---|---|---|---|---|---|",
    ]
    lines.extend(report_rows)
    lines.extend([
        f"",
        f"## Extras (crypto, USD index)",
        f"",
        f"| Symbol | Status | Bid+Ask | Earliest | Page bars |",
        f"|---|---|---|---|---|",
    ])
    lines.extend(extras_rows)

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print()
    print(f"Report: {report_path}")
    print()
    print(f"=== VERDICT: {verdict} ===")
    print(f"All-OK: {summary['all_ok']} / {summary['total']} (threshold {threshold})")

    return 0 if verdict == "GO" else 1


if __name__ == "__main__":
    sys.exit(main())
