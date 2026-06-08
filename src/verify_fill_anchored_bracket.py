"""Paper-gateway smoke test for fill-anchored brackets.

Places one staged paper order, runs PaperTrader.execute_open(), and checks that
the returned stop/target levels are anchored to the actual entry fill.

Usage:
    ./run.sh python src/verify_fill_anchored_bracket.py --symbol AAPL

Requires PAPER_TRADING_ENABLED=true and FILL_ANCHORED_EXECUTION=true. Refuses to
run unless the connected account is a paper account (id starts "DU").
"""
import argparse
import sys
from datetime import datetime

from pymongo import MongoClient

from bluehorseshoe.core.config import Settings
from bluehorseshoe.data.ibkr_client import IBKRClient, IBKRConfig
from bluehorseshoe.trading.paper_trader import PaperTradeConfig, PaperTrader


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify fill-anchored paper bracket")
    ap.add_argument("--symbol", default="AAPL", help="liquid paper-test symbol")
    ap.add_argument("--client-id", type=int, default=8, help="dedicated client id")
    ap.add_argument("--qty", type=int, default=1, help="whole-share quantity")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    args = ap.parse_args()

    if args.qty < 1:
        print("ERROR: --qty must be at least 1 whole share")
        return 1

    s = Settings()
    if not s.paper_trading_enabled or not s.fill_anchored_execution:
        print("ERROR: requires PAPER_TRADING_ENABLED=true and FILL_ANCHORED_EXECUTION=true")
        return 1

    client = IBKRClient(IBKRConfig(
        host=s.ibkr_host,
        port=s.ibkr_port,
        client_id=args.client_id,
        read_only=False,
    ))
    mongo = MongoClient(s.mongo_uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
    db = mongo[s.mongo_db]

    try:
        quote = client.get_quote(args.symbol)
        ref = next((p for p in (quote.last, quote.ask, quote.bid, quote.close) if p), None)
        if not ref:
            print(f"ERROR: no quote for {args.symbol}: {quote.error}")
            return 1

        acct = client.get_account_summary().get("account_id", "")
        if not str(acct).startswith("DU"):
            print(f"ABORT: connected account {acct!r} is not a paper account")
            return 1

        entry_model = round(float(ref), 2)
        r_offset = round(entry_model * 0.03, 2)
        tp_offset = round(r_offset * 1.96, 2)
        t1_offset = round(entry_model * 0.02, 2)
        stage_doc = {
            "date": args.date,
            "symbol": args.symbol,
            "strategy": "DeepOS",
            "total_qty": args.qty,
            "t1_qty": 0,
            "t2_qty": args.qty,
            "entry_model": entry_model,
            "R": r_offset,
            "tp_offset": tp_offset,
            "t1_offset": t1_offset,
            "status": "staged",
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        db["staged_orders"].update_one(
            {"date": args.date, "symbol": args.symbol, "strategy": "DeepOS"},
            {"$set": stage_doc},
            upsert=True,
        )
        print(
            f"staged {args.symbol}: qty={args.qty} entry_model={entry_model:.2f} "
            f"R={r_offset:.2f} tp_offset={tp_offset:.2f}"
        )

        trader = PaperTrader(
            ibkr_client=client,
            config=PaperTradeConfig(
                total_investment=s.paper_total_investment,
                max_positions=s.paper_max_positions,
                logs_path=s.logs_path,
                fill_anchored_execution=True,
                fractional_shares=False,
            ),
            database=db,
        )
        results = trader.execute_open(args.date)
        result = next((r for r in results if r.symbol == args.symbol), None)
        if result is None or result.status not in ("submitted", "partial"):
            print(f"FAIL: execute_open did not submit {args.symbol}: {result}")
            return 1

        expected_stop = round(result.entry_price - r_offset, 2)
        expected_target = round(result.entry_price + tp_offset, 2)
        ok = (
            abs(result.stop_loss_price - expected_stop) <= 0.01
            and abs(result.take_profit_price - expected_target) <= 0.01
        )
        print(
            f"fill={result.entry_price:.2f} stop={result.stop_loss_price:.2f} "
            f"target={result.take_profit_price:.2f}"
        )
        if not ok:
            print(f"FAIL: expected stop={expected_stop:.2f} target={expected_target:.2f}")
            return 1
        print("PASS: exits are anchored to the actual fill")
        return 0
    finally:
        try:
            client.close()
        finally:
            mongo.close()


if __name__ == "__main__":
    sys.exit(main())
