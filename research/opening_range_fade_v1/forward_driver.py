"""Forward micro-futures paper driver — the last true out-of-sample check for the opening-range fade.

Runs once per US session (cron ~16:10 UTC = after the 11:00-ET window closes, DST-safe). For EACH of
MNQ / MES / M2K (the validated 3-instrument book) each run:
  1. refreshes that front-month's 1-min + daily cache from the project's paper IB Gateway,
  2. builds today's Variant B setup (09:30-11:00 ET, ATR-filtered) and simulates the paper fill,
  3. appends ONE row to forward_paper_log.csv — every run, with an explicit status, so the log
     doubles as a liveness record (a quiet day is distinguishable from a broken driver).

Idempotent per (ET date, instrument): re-running is a no-op for instruments already logged terminal,
and one instrument's fetch_error never blocks the others. Live fills with no look-back are the only
test left that hindsight can't game; this accumulates them day by day across all three.

    ./run.sh python research/opening_range_fade_v1/forward_driver.py                 # live, today, all 3
    ./run.sh python research/opening_range_fade_v1/forward_driver.py --root MES       # just one
    ./run.sh python research/opening_range_fade_v1/forward_driver.py --day 2026-06-24 --no-fetch  # replay cached
"""
import os, sys, csv, time
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import data as D
from strategy import build_setup, simulate
from paper_forward import rt_cost, FUT

ET = ZoneInfo("America/New_York")
ROOTS = ["MNQ", "MES", "M2K"]
LOG = os.path.join(C.STUDY_DIR, "forward_paper_log.csv")
FIELDS = ["run_ts_utc", "trade_date_et", "root", "contract", "status", "side",
          "n_morning_bars", "R", "entry", "tp", "stop", "U_dollars",
          "outcome", "gross", "cost", "net"]
# A day is "done" only on a terminal status. fetch_error is NON-terminal: a transient gateway
# failure must not permanently block capturing the real session, so a later tick can retry.
TERMINAL = {"WIN", "LOSS", "TIMEOUT", "NEVER_FILLED", "no_session", "below_atr_floor", "doji_or_thin"}


def _already_logged(day, root):
    if not os.path.exists(LOG):
        return False
    with open(LOG, newline="") as f:
        return any(r["trade_date_et"] == day and r["root"] == root and r["status"] in TERMINAL
                   for r in csv.DictReader(f))


def _append(row):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def assess(root, day, contract=""):
    """Classify today's session and (if it qualifies) simulate the Variant B paper trade.
    Returns a fully-populated log row. Pure read from cache — fetch happens in run()."""
    mult = FUT[root]["mult"]
    rt = rt_cost(root, "central")
    row = {k: "" for k in FIELDS}
    row.update(run_ts_utc=datetime.now(tz=ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S"),
               trade_date_et=day, root=root, contract=contract, gross=0.0, cost=0.0, net=0.0)

    bars = D.load_intraday(root).get(day)
    row["n_morning_bars"] = len(bars) if bars else 0
    if not bars:
        now = datetime.now(ET)
        # If we're asking about TODAY before the 11:00-ET window has closed, the morning simply
        # isn't in yet -> pre_market (NON-terminal, retries later). A weekday/holiday with no
        # session after the window, or any past date with no bars, is a terminal no_session.
        pre = (day == now.date().isoformat() and now.strftime("%H:%M:%S") < C.SIM_END)
        row["status"] = "pre_market" if pre else "no_session"
        return row
    s = build_setup(bars)
    if not s:
        row["status"] = "doji_or_thin"          # doji open, <10 opening bars, or zero range
        return row
    atr = D.get_atr(root).get(day)
    row.update(side=s["side"], R=round(s["R"], 3), entry=round(s["entry"], 3),
               tp=round(s["tp"], 3), U_dollars=round(s["U"] * mult, 2),
               stop=round(s["entry"] - s["U"] if s["side"] == "LONG" else s["entry"] + s["U"], 3))
    if atr is None or s["R"] < C.ATR_MULT * atr:
        row["status"] = "below_atr_floor"        # range too small vs ATR_14 -> no trade
        return row

    outcome, pnl = simulate(s, C.BOUNCE_B)
    row["status"], row["outcome"] = outcome, outcome
    if outcome != "NEVER_FILLED":
        gross = pnl * s["U"] * mult
        row.update(gross=round(gross, 2), cost=round(rt, 2), net=round(gross - rt, 2))
    return row


def _fetch(root, retries=2):
    """Refresh `root`'s front-month cache. Returns the pull dict, or None on failure.
    A failed fetch returns n_daily==0 (the daily series always has history when the farm answers)."""
    import gateway_pull
    for i in range(retries):
        try:
            res = gateway_pull.pull(root, days=5)
            if res and res.get("n_daily", 0) > 0:
                return res
        except Exception as e:  # noqa: BLE001
            print(f"  {root} fetch attempt {i+1} raised: {e!r}")
        time.sleep(20)
    return None


def run_one(root, day, fetch=True):
    if _already_logged(day, root):
        print(f"{root} {day}: already logged (terminal) — no-op")
        return
    contract = ""
    if fetch:
        res = _fetch(root)
        if not res:                       # gateway/data-farm failure -> NON-terminal, retry later
            row = {k: "" for k in FIELDS}
            row.update(run_ts_utc=datetime.now(tz=ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S"),
                       trade_date_et=day, root=root, status="fetch_error",
                       n_morning_bars=0, gross=0.0, cost=0.0, net=0.0)
            _append(row)
            print(f"{root} {day}: fetch_error (gateway/data farm unavailable) — will retry next tick")
            return
        contract = res["contract"]
    row = assess(root, day, contract)
    _append(row)
    print(f"{root} {day} [{contract or 'cache'}]: {row['status']}"
          + (f"  {row['side']} -> net ${row['net']:+.2f}/contract" if row.get("outcome") else "")
          + f"  (logged to {os.path.basename(LOG)})")


def run(day=None, fetch=True, roots=None):
    day = day or datetime.now(ET).date().isoformat()
    for root in (roots or ROOTS):         # each instrument independent: one failure won't block others
        run_one(root, day, fetch)


if __name__ == "__main__":
    a = sys.argv[1:]
    day = a[a.index("--day") + 1] if "--day" in a else None
    roots = [a[a.index("--root") + 1]] if "--root" in a else None
    run(day=day, fetch="--no-fetch" not in a, roots=roots)
