"""Production Alpha Vantage fundamentals puller for PIT solvency data.

Pulls quarterly income statement, balance sheet, and cash-flow data, aligns each
quarter to the already-validated earnings ``reportedDate`` calendar, computes
statement-derived fields, and upserts rows into DuckDB's ``fundamentals`` table.
"""
import argparse
import json
import time
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from bluehorseshoe.core.config import get_settings
from bluehorseshoe.data.duckdb_store import DuckDBStore

STATEMENTS = (
    ("INCOME_STATEMENT", "inc"),
    ("BALANCE_SHEET", "bal"),
    ("CASH_FLOW", "cf"),
)
DEFAULT_EARNINGS_PARQUET = "data/earnings.parquet"
DEFAULT_CHECKPOINT = "data/fundamentals_pull_checkpoint.json"
SLEEP_SECONDS = 0.55
MAX_CONSEC_RATE_GATES = 3


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _is_rate_gate(message: Optional[str]) -> bool:
    if not message:
        return False
    text = message.lower()
    return any(token in text for token in (
        "call frequency",
        "premium",
        "thank you for using",
        "rate limit",
        "higher api",
    ))


def _fetch_statement(function: str, symbol: str, api_key: str) -> Tuple[List[dict], Optional[str]]:
    url = (
        "https://www.alphavantage.co/query"
        f"?function={function}&symbol={symbol}&apikey={api_key}"
    )
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    gates = [payload[key] for key in ("Note", "Information", "Error Message") if key in payload]
    gate = gates[0][:180] if gates else None
    return payload.get("quarterlyReports", []), gate


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _earnings_report_map(earnings_parquet: str) -> Dict[str, Dict[str, str]]:
    earnings = pd.read_parquet(earnings_parquet)
    repmap: Dict[str, Dict[str, str]] = {}
    for symbol, group in earnings.groupby("symbol"):
        repmap[str(symbol)] = {
            str(fd): str(rd)[:10]
            for fd, rd in zip(group.fiscalDateEnding, group.reportedDate)
            if pd.notna(rd)
        }
    return repmap


def _incremental_symbols(
    earnings_parquet: str,
    store: DuckDBStore,
    symbols: Optional[Iterable[str]] = None,
) -> List[str]:
    earnings = pd.read_parquet(earnings_parquet)
    latest_earnings = (
        earnings.dropna(subset=["reportedDate"])
        .assign(reportedDate=lambda x: pd.to_datetime(x["reportedDate"]).dt.date)
        .groupby("symbol")["reportedDate"]
        .max()
    )
    existing = store.get_latest_fundamental_reported_dates()
    if symbols:
        requested = {str(s).upper() for s in symbols}
        latest_earnings = latest_earnings[latest_earnings.index.isin(requested)]

    todo = []
    for symbol, latest in latest_earnings.items():
        prev = existing.get(str(symbol))
        if prev is None or pd.to_datetime(prev).date() < latest:
            todo.append(str(symbol))
    return sorted(todo)


def rows_for_symbol(symbol: str, rec: dict, reported_dates: Dict[str, str]) -> List[dict]:
    """Compute quarterly PIT fundamentals rows for one symbol."""
    if not rec.get("inc") or not rec.get("bal") or not rec.get("cf"):
        return []

    inc = {row["fiscalDateEnding"]: row for row in rec["inc"]}
    bal = {row["fiscalDateEnding"]: row for row in rec["bal"]}
    cf = {row["fiscalDateEnding"]: row for row in rec["cf"]}
    quarters = sorted(set(inc) & set(bal) & set(cf))

    ni = [_float(inc[q].get("netIncome")) for q in quarters]
    ocf = [_float(cf[q].get("operatingCashflow")) for q in quarters]
    rev = [_float(inc[q].get("totalRevenue")) for q in quarters]
    gp = [_float(inc[q].get("grossProfit")) for q in quarters]
    ebit = [_float(inc[q].get("ebit")) for q in quarters]
    ta = [_float(bal[q].get("totalAssets")) for q in quarters]
    tl = [_float(bal[q].get("totalLiabilities")) for q in quarters]
    ca = [_float(bal[q].get("totalCurrentAssets")) for q in quarters]
    cl = [_float(bal[q].get("totalCurrentLiabilities")) for q in quarters]
    debt = [_float(bal[q].get("shortLongTermDebtTotal")) for q in quarters]
    retained = [_float(bal[q].get("retainedEarnings")) for q in quarters]
    shares = [_float(bal[q].get("commonStockSharesOutstanding")) for q in quarters]

    def ttm(values, idx):
        window = values[idx - 3:idx + 1]
        return np.nan if any(np.isnan(v) for v in window) else sum(window)

    out = []
    for idx, quarter in enumerate(quarters):
        if idx < 7:
            continue
        ni_ttm, ocf_ttm = ttm(ni, idx), ttm(ocf, idx)
        rev_ttm, gp_ttm = ttm(rev, idx), ttm(gp, idx)
        ebit_ttm = ttm(ebit, idx)
        ni_prev = ttm(ni, idx - 4)
        rev_prev, gp_prev = ttm(rev, idx - 4), ttm(gp, idx - 4)
        ta_now, ta_prev = ta[idx], ta[idx - 4]

        components = [
            ni_ttm > 0,
            ocf_ttm > 0,
            (ni_ttm / ta_now) > (ni_prev / ta_prev) if ta_now and ta_prev else np.nan,
            ocf_ttm > ni_ttm,
            (debt[idx] / ta_now) < (debt[idx - 4] / ta_prev) if ta_now and ta_prev else np.nan,
            (ca[idx] / cl[idx]) > (ca[idx - 4] / cl[idx - 4]) if cl[idx] and cl[idx - 4] else np.nan,
            shares[idx] <= shares[idx - 4] if not np.isnan(shares[idx]) and not np.isnan(shares[idx - 4]) else np.nan,
            (gp_ttm / rev_ttm) > (gp_prev / rev_prev) if rev_ttm and rev_prev else np.nan,
            (rev_ttm / ta_now) > (rev_prev / ta_prev) if ta_now and ta_prev else np.nan,
        ]
        available = [c for c in components if not (isinstance(c, float) and np.isnan(c))]
        reported = reported_dates.get(quarter)
        if not reported:
            reported = (pd.to_datetime(quarter) + pd.Timedelta(days=45)).strftime("%Y-%m-%d")
        out.append({
            "symbol": symbol,
            "fiscalDateEnding": quarter,
            "reportedDate": reported,
            "fscore": sum(1 for c in available if bool(c)),
            "n_avail": len(available),
            "ni_ttm": ni_ttm,
            "ocf_ttm": ocf_ttm,
            "rev_ttm": rev_ttm,
            "ebit_ttm": ebit_ttm,
            "total_assets": ta_now,
            "total_liabilities": tl[idx],
            "total_debt": debt[idx],
            "current_assets": ca[idx],
            "current_liabilities": cl[idx],
            "retained_earnings": retained[idx],
            "shares_out": shares[idx],
        })
    return out


def pull_fundamentals(
    symbols: Optional[Iterable[str]] = None,
    db_path: Optional[str] = None,
    earnings_parquet: str = DEFAULT_EARNINGS_PARQUET,
    checkpoint_path: str = DEFAULT_CHECKPOINT,
    api_key: Optional[str] = None,
) -> int:
    """Fetch incremental statement data and upsert computed fundamentals rows."""
    settings = get_settings()
    api_key = api_key or settings.alphavantage_key
    if not api_key:
        raise RuntimeError("ALPHAVANTAGE_KEY is required")

    store = DuckDBStore(db_path or settings.duckdb_path)
    checkpoint_file = Path(checkpoint_path)
    cache = _load_json(checkpoint_file)
    repmap = _earnings_report_map(earnings_parquet)
    todo = _incremental_symbols(earnings_parquet, store, symbols=symbols)
    consecutive_gates = 0
    rows: List[dict] = []

    try:
        for symbol in todo:
            cached = cache.get(symbol)
            if cached and all(key in cached for _, key in STATEMENTS):
                rec = cached
            else:
                rec = {}
                rate_hit = False
                for function, key in STATEMENTS:
                    reports, gate = _fetch_statement(function, symbol, api_key)
                    if gate:
                        if _is_rate_gate(gate):
                            consecutive_gates += 1
                            rate_hit = True
                            time.sleep(SLEEP_SECONDS)
                            break
                        rec[key] = []
                        time.sleep(SLEEP_SECONDS)
                        continue
                    consecutive_gates = 0
                    rec[key] = reports
                    time.sleep(SLEEP_SECONDS)
                if rate_hit:
                    if consecutive_gates >= MAX_CONSEC_RATE_GATES:
                        break
                    continue
                cache[symbol] = {**rec, "gate": None}
                _save_json(checkpoint_file, cache)

            rows.extend(rows_for_symbol(symbol, rec, repmap.get(symbol, {})))

        if rows:
            df = pd.DataFrame(rows)
            store.save_fundamentals(df)
        return len(rows)
    finally:
        _save_json(checkpoint_file, cache)
        store.close()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Pull and upsert PIT fundamentals into DuckDB.")
    parser.add_argument("--symbols", nargs="*", help="Optional symbol subset for targeted refresh.")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--earnings-parquet", default=DEFAULT_EARNINGS_PARQUET)
    parser.add_argument("--checkpoint", default=DEFAULT_CHECKPOINT)
    args = parser.parse_args(argv)
    rows = pull_fundamentals(
        symbols=args.symbols,
        db_path=args.db_path,
        earnings_parquet=args.earnings_parquet,
        checkpoint_path=args.checkpoint,
    )
    print(f"upserted {rows} fundamentals rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
