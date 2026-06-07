"""Paper-gateway verification for fractional-share bracket orders.

The DEPLOY GATE for the fractional-share sizing change (commit 85cc4dd): the entry
leg is a DAY limit (fine), but the take-profit / stop-loss child legs ride as GTC, and
IBKR's support for GTC + fractional quantity is broker/contract-dependent. This could
not be verified in unit tests (no live gateway). This script clears the gate by placing
ONE real fractional bracket on the PAPER account and reporting whether each leg — the
GTC children in particular — was accepted or rejected.

It is deliberately safe:
  * Refuses to run unless the connected account is a paper account (id starts 'DU').
  * Entry limit is set far BELOW market, so the parent rests and CANNOT fill — we are
    testing order ACCEPTANCE, not execution.
  * Uses a dedicated client_id (default 8) so it never collides with PaperTrader (1)
    or bh_swing (7).
  * Cancels all legs in a finally block (unless --no-cancel), then disconnects.

Usage (gateway must be up; PAPER_TRADING_ENABLED not required — we force read_only=False):
    ./run.sh python src/verify_fractional_bracket.py
    ./run.sh python src/verify_fractional_bracket.py --symbol MSFT --qty 0.25
    ./run.sh python src/verify_fractional_bracket.py --dry-run     # prices only, no order

Exit code 0 = fractional bracket accepted (gate cleared); 1 = rejected or error.
"""
import argparse
import sys

from bluehorseshoe.core.config import Settings
from bluehorseshoe.data.ibkr_client import IBKRClient, IBKRConfig


def _leg_status(ib, order_id):
    """(status, error_text) for an order_id by inspecting live Trade objects."""
    trade = next((t for t in ib.trades() if getattr(t.order, "orderId", None) == order_id), None)
    if trade is None:
        return "MISSING", "no Trade object found"
    status = getattr(trade.orderStatus, "status", "Unknown")
    errs = [f"{e.errorCode}: {e.message}" for e in getattr(trade, "log", [])
            if getattr(e, "errorCode", 0)]
    return status, "; ".join(errs)


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify fractional bracket on paper account")
    ap.add_argument("--symbol", default="AAPL", help="liquid, fractional-eligible symbol")
    ap.add_argument("--qty", type=float, default=0.5, help="fractional share quantity")
    ap.add_argument("--client-id", type=int, default=8, help="dedicated client id")
    ap.add_argument("--no-cancel", action="store_true", help="leave legs working (debug)")
    ap.add_argument("--dry-run", action="store_true", help="compute prices, place nothing")
    args = ap.parse_args()

    if args.qty <= 0 or args.qty == int(args.qty):
        print(f"ERROR: --qty {args.qty} is not fractional; pick a non-integer (e.g. 0.5)")
        return 1

    s = Settings()
    client = IBKRClient(IBKRConfig(
        host=s.ibkr_host, port=s.ibkr_port, client_id=args.client_id,
        read_only=False,  # MUST place orders; we guard with a paper-account check below
    ))

    placed_ids: list[int] = []
    try:
        # get_quote() connects lazily; use it to fetch a live price and warm the connection.
        q = client.get_quote(args.symbol)
        ref = next((p for p in (q.last, q.close, q.ask, q.bid) if p), None)
        if not ref:
            print(f"ERROR: no quote for {args.symbol} (gateway up? market data?) — {q.error}")
            return 1

        acct = client.get_account_summary().get("account_id", "")
        if not str(acct).startswith("DU"):
            print(f"ABORT: connected account '{acct}' is not a paper account (expected 'DU...'). "
                  "Refusing to place a fractional order outside paper.")
            return 1

        # Entry far below market => rests, cannot fill. Geometry keeps tp>entry>sl.
        entry = round(ref * 0.5, 2)
        take_profit = round(entry * 1.10, 2)
        stop_loss = round(entry * 0.95, 2)
        print(f"account={acct}  {args.symbol} ref={ref:.2f}  qty={args.qty} (fractional)")
        print(f"  entry={entry} (far below mkt, won't fill)  tp={take_profit}  sl={stop_loss}")

        if args.dry_run:
            print("DRY-RUN: no order placed.")
            return 0

        result = client.place_bracket_order(
            symbol=args.symbol, quantity=args.qty, limit_price=entry,
            take_profit_price=take_profit, stop_loss_price=stop_loss,
        )
        placed_ids = result.get("order_ids", [])
        print(f"\nplace_bracket_order -> status={result.get('status')} "
              f"error={result.get('error')} ids={placed_ids}")
        if result.get("status") != "submitted" or len(placed_ids) != 3:
            print("\nVERDICT: ✗ FAIL — bracket not submitted (see error above).")
            return 1

        client.sleep(3)  # let IBKR ack/reject asynchronously (pumps the ib_async loop)

        legs = ["ENTRY (DAY)", "TAKE-PROFIT (GTC)", "STOP-LOSS (GTC)"]
        print("\nleg statuses:")
        accepted_ok = {"Submitted", "PreSubmitted", "Filled", "ApiPending", "PendingSubmit"}
        all_ok = True
        for label, oid in zip(legs, placed_ids):
            status, err = _leg_status(client._ib, oid)  # noqa: SLF001
            ok = status in accepted_ok and not err
            all_ok = all_ok and ok
            print(f"  {'✓' if ok else '✗'} {label:<20} id={oid} status={status}"
                  + (f"  ERR[{err}]" if err else ""))

        all_errs = " ".join(_leg_status(client._ib, oid)[1] for oid in placed_ids)  # noqa: SLF001
        if all_ok:
            verdict = ("✓ PASS — fractional bracket accepted incl. GTC child legs. "
                       "Gate cleared; safe to set paper_fractional_shares=True.")
        elif "10243" in all_errs:
            verdict = ("✗ FAIL — IBKR Error 10243: the ACCOUNT cannot place fractional orders "
                       "via the API (TWS-desktop only). This blocks the entry leg, not just the "
                       "children. FIX: enable fractional-share trading on the IBKR account, then "
                       "re-run. Keep paper_fractional_shares=False until this PASSes.")
        else:
            verdict = ("✗ FAIL — a leg was rejected (see ERR codes above). Keep "
                       "paper_fractional_shares=False; investigate before enabling.")
        print("\nVERDICT: " + verdict)
        return 0 if all_ok else 1

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"ERROR: {e}")
        return 1
    finally:
        if placed_ids and not args.no_cancel:
            print("\ncleanup: cancelling placed legs...")
            for oid in placed_ids:
                r = client.cancel_order(oid)
                print(f"  cancel id={oid} -> {r.get('status')}")
            if client.is_connected():
                client.sleep(1)
        client.close()


if __name__ == "__main__":
    sys.exit(main())
