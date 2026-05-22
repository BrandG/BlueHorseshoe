"""
Contrarian short test: do the top-10 baseline recommendations from
BlueHorseshoe lose money in the immediate short term (1.5% TP / 3% SL /
3-day max hold)?

Compares two parallel sims over the same trades:
  LONG  — what BH actually recommends (buy at next-day open, cover at +1.5% TP, -3% SL, or 3d close)
  SHORT — contrarian flip (sell at next-day open, cover at -1.5% TP, +3% SL, or 3d close)

Entry mechanic is "next-day open" rather than a limit at BH's entry_price,
to avoid filtering bias from limit-fill selection.

Stop-vs-target precedence on an inside-bar is conservative against the trade
(SL wins ties) — same convention as the production long backtester.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from bluehorseshoe.core.config import get_settings
from bluehorseshoe.core.container import AppContainer

TP_PCT = 0.015     # 1.5%  (overridden by --tp)
SL_PCT = 0.030     # 3.0%  (overridden by --sl)
HOLD_DAYS = 3      # (overridden by --hold)
TOP_N = 10
LOOKBACK_DAYS = 365


def _fetch_top_n_per_date(db, dates: list[str], bottom: bool = False,
                          min_pool: int = 20) -> dict[str, list[dict]]:
    """For each date, return up to TOP_N baseline picks (symbol + score).

    If bottom=True, takes the lowest-scoring positive picks instead. Dates with
    fewer than min_pool qualified symbols are skipped (bottom-10 of a 5-row
    universe is meaningless).
    """
    out: dict[str, list[dict]] = {}
    coll = db["trade_scores"]
    sort_dir = 1 if bottom else -1
    for d in dates:
        # Require positive scores so "bottom" doesn't just collect zeros.
        query = {"date": d, "strategy": "baseline",
                 "metadata.entry_price": {"$exists": True},
                 "score": {"$gt": 0}}
        pool_size = coll.count_documents(query)
        if pool_size < min_pool:
            continue
        cur = coll.find(
            query,
            {"symbol": 1, "score": 1, "metadata.entry_price": 1, "_id": 0},
        ).sort("score", sort_dir).limit(TOP_N)
        rows = []
        for r in cur:
            meta = r.get("metadata") or {}
            rows.append({"symbol": r["symbol"], "score": r["score"],
                         "bh_entry": meta.get("entry_price")})
        if rows:
            out[d] = rows
    return out


def _simulate_trade(direction: str, future: pd.DataFrame) -> dict:
    """
    Simulate one trade given a DataFrame of >=1 future trading days (sorted asc).
    direction: 'long' or 'short'.

    Entry: at future.iloc[0]['open'].
    TP/SL: ±TP_PCT / ±SL_PCT from entry.
    Stop-vs-target precedence is conservative against the trade (SL wins ties on
    an inside-bar).
    Time exit: close of day index HOLD_DAYS-1 (0-indexed: the 3rd bar).
    """
    if future.empty:
        return {"status": "no_future_data", "pnl_pct": 0.0, "days_held": 0}

    entry = float(future.iloc[0]["open"])
    if direction == "long":
        tp = entry * (1 + TP_PCT)
        sl = entry * (1 - SL_PCT)
    else:
        tp = entry * (1 - TP_PCT)
        sl = entry * (1 + SL_PCT)

    n = min(HOLD_DAYS, len(future))
    for i in range(n):
        bar = future.iloc[i]
        o, h, l, c = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])

        # Conservative: check SL first.
        if direction == "long":
            # On bar 0, the open is the entry — only intra-bar moves matter.
            hit_sl = l <= sl
            hit_tp = h >= tp
            if hit_sl:
                # If a gap-down on bar 0 opens below SL, that gap *is* the entry slippage; here entry==open
                # but we still cover at sl (or open if open < sl, which on bar 0 == entry).
                exit_px = min(o, sl) if i == 0 else (o if o < sl else sl)
                return {"status": "stopped_out", "pnl_pct": (exit_px / entry - 1) * 100, "days_held": i}
            if hit_tp:
                exit_px = max(o, tp) if i == 0 else (o if o > tp else tp)
                return {"status": "success", "pnl_pct": (exit_px / entry - 1) * 100, "days_held": i}
        else:  # short
            hit_sl = h >= sl
            hit_tp = l <= tp
            if hit_sl:
                exit_px = max(o, sl) if i == 0 else (o if o > sl else sl)
                return {"status": "stopped_out", "pnl_pct": (entry / exit_px - 1) * 100, "days_held": i}
            if hit_tp:
                exit_px = min(o, tp) if i == 0 else (o if o < tp else tp)
                return {"status": "success", "pnl_pct": (entry / exit_px - 1) * 100, "days_held": i}

    # Time exit at close of final bar
    last_close = float(future.iloc[n - 1]["close"])
    pnl = (last_close / entry - 1) * 100 if direction == "long" else (entry / last_close - 1) * 100
    status = "time_profit" if pnl > 0 else "time_loss"
    return {"status": status, "pnl_pct": pnl, "days_held": n - 1}


def _summarize(label: str, trades: list[dict]) -> str:
    valid = [t for t in trades if t["status"] != "no_future_data"]
    n = len(valid)
    if n == 0:
        return f"{label}: no valid trades"
    wins = [t for t in valid if t["pnl_pct"] > 0]
    losses = [t for t in valid if t["pnl_pct"] < 0]
    flat = n - len(wins) - len(losses)
    tp_hits = sum(1 for t in valid if t["status"] == "success")
    sl_hits = sum(1 for t in valid if t["status"] == "stopped_out")
    time_wins = sum(1 for t in valid if t["status"] == "time_profit")
    time_losses = sum(1 for t in valid if t["status"] == "time_loss")
    pnls = np.array([t["pnl_pct"] for t in valid])
    avg = pnls.mean()
    med = np.median(pnls)
    cum = pnls.sum()
    win_rate = len(wins) / n * 100
    avg_win = np.mean([t["pnl_pct"] for t in wins]) if wins else 0.0
    avg_loss = np.mean([t["pnl_pct"] for t in losses]) if losses else 0.0
    expectancy = avg
    se = pnls.std(ddof=1) / np.sqrt(n) if n > 1 else 0.0
    ci_lo = avg - 1.96 * se
    ci_hi = avg + 1.96 * se

    return (
        f"\n=== {label} ===\n"
        f"  Trades:           {n}\n"
        f"  Win rate:         {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L / {flat}flat)\n"
        f"  Exit breakdown:   TP={tp_hits}  SL={sl_hits}  time_profit={time_wins}  time_loss={time_losses}\n"
        f"  Avg PnL / trade:  {avg:+.3f}%  (median {med:+.3f}%)\n"
        f"  95% CI on mean:   [{ci_lo:+.3f}%, {ci_hi:+.3f}%]\n"
        f"  Avg winner:       {avg_win:+.3f}%   Avg loser: {avg_loss:+.3f}%\n"
        f"  Cumulative PnL:   {cum:+.2f}% (sum across all trades)\n"
    )


def main():
    global TP_PCT, SL_PCT, HOLD_DAYS
    ap = argparse.ArgumentParser()
    ap.add_argument("--tp", type=float, default=TP_PCT * 100, help="take-profit %, e.g. 5.0")
    ap.add_argument("--sl", type=float, default=SL_PCT * 100, help="stop-loss %, e.g. 3.0")
    ap.add_argument("--hold", type=int, default=HOLD_DAYS, help="max hold trading days")
    ap.add_argument("--tag", type=str, default="", help="suffix for output CSV files")
    ap.add_argument("--bottom", action="store_true", help="use bottom-N (weakest signal) instead of top-N")
    args = ap.parse_args()
    TP_PCT = args.tp / 100.0
    SL_PCT = args.sl / 100.0
    HOLD_DAYS = args.hold

    print("Contrarian-short backtest v1")
    print(f"  Top {TOP_N} baseline per date | TP {TP_PCT*100:.1f}% | SL {SL_PCT*100:.1f}% | hold {HOLD_DAYS}d")
    print(f"  Window: last {LOOKBACK_DAYS} days")
    print(f"  Entry: next-day open after the score date")

    settings = get_settings()
    container = AppContainer(settings=settings)
    db = container.get_database()
    store = container.get_historical_store(read_only=True)

    end = datetime.now()
    start = end - timedelta(days=LOOKBACK_DAYS)
    pipeline = [
        {"$match": {"strategy": "baseline",
                    "date": {"$gte": start.strftime("%Y-%m-%d"),
                              "$lte": end.strftime("%Y-%m-%d")}}},
        {"$group": {"_id": "$date"}},
        {"$sort": {"_id": 1}},
    ]
    dates = [d["_id"] for d in db["trade_scores"].aggregate(pipeline)]
    print(f"  Score dates available: {len(dates)}")

    if not dates:
        print("No baseline score dates in window. Exiting.")
        return 1

    print(f"  Selection: {'BOTTOM' if args.bottom else 'TOP'}-{TOP_N} baseline by score")
    picks_by_date = _fetch_top_n_per_date(db, dates, bottom=args.bottom)
    all_symbols = sorted({r["symbol"] for rows in picks_by_date.values() for r in rows})
    print(f"  Unique symbols across all dates: {len(all_symbols)}")

    # Bulk-load OHLCV from the earliest pick date onward.
    earliest = min(picks_by_date.keys())
    print(f"  Loading OHLCV from DuckDB (start > {earliest})...", flush=True)
    price_data = store.load_symbols_bulk(all_symbols, start_date=earliest)
    print(f"  Got data for {len(price_data)} / {len(all_symbols)} symbols", flush=True)

    # Parse dates once
    for sym, df in price_data.items():
        df["date"] = pd.to_datetime(df["date"])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)

    long_trades: list[dict] = []
    short_trades: list[dict] = []
    per_date_counts: list[dict] = []
    daily_pnl_long: dict[str, float] = defaultdict(float)
    daily_pnl_short: dict[str, float] = defaultdict(float)
    no_data_count = 0

    for d in sorted(picks_by_date):
        cutoff = pd.to_datetime(d)
        date_trades_l: list[dict] = []
        date_trades_s: list[dict] = []
        for pick in picks_by_date[d]:
            sym = pick["symbol"]
            df = price_data.get(sym)
            if df is None:
                no_data_count += 1
                continue
            future = df[df["date"] > cutoff].head(HOLD_DAYS + 1)
            if future.empty:
                no_data_count += 1
                continue
            tl = _simulate_trade("long", future)
            ts = _simulate_trade("short", future)
            tl["symbol"] = sym; tl["score_date"] = d
            ts["symbol"] = sym; ts["score_date"] = d
            long_trades.append(tl); short_trades.append(ts)
            date_trades_l.append(tl); date_trades_s.append(ts)
            daily_pnl_long[d] += tl["pnl_pct"]
            daily_pnl_short[d] += ts["pnl_pct"]
        per_date_counts.append({"date": d, "n": len(date_trades_l)})

    print(f"\nTotal trades simulated: {len(long_trades)}  ({no_data_count} skipped for missing data)")
    print(_summarize("LONG  (what BH recommends)", long_trades))
    print(_summarize("SHORT (contrarian flip)",   short_trades))

    # Recent-window slice (last 90d of score dates)
    recent_cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    long_recent  = [t for t in long_trades  if t["score_date"] >= recent_cutoff]
    short_recent = [t for t in short_trades if t["score_date"] >= recent_cutoff]
    if long_recent:
        print(_summarize(f"LONG  (last 90d, scoredate >= {recent_cutoff})", long_recent))
        print(_summarize(f"SHORT (last 90d, scoredate >= {recent_cutoff})", short_recent))

    # Persist per-trade CSV for follow-up analysis
    out_dir = Path(__file__).parent
    suffix = f"_{args.tag}" if args.tag else ""
    pd.DataFrame(long_trades).to_csv(out_dir / f"long_trades{suffix}.csv", index=False)
    pd.DataFrame(short_trades).to_csv(out_dir / f"short_trades{suffix}.csv", index=False)
    print(f"\nPer-trade CSVs written to {out_dir}")

    # Day-level direction agreement: how often does shorting beat longing on a given prediction day?
    days = sorted(daily_pnl_long.keys())
    short_better_days = sum(1 for d in days if daily_pnl_short[d] > daily_pnl_long[d])
    print(f"\nDay-level: short_basket beat long_basket on {short_better_days}/{len(days)} prediction dates "
          f"({short_better_days / len(days) * 100:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
