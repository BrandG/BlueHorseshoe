"""BH FTMO operator tool — position sizing calculator.

Answers "how many lots do I type into FTMO?" for a given entry/stop and a
dollar risk budget, using the same instrument table and the same arithmetic
the H4 briefing uses, so the number here always matches the number in
src/bh_briefing_ftmo_orders.json.

The one equation, for every instrument in the table:

    lots = risk_usd / (stop_distance_in_pips x dollar_per_pip_per_lot)

rounded DOWN to the broker's min-lot increment (so rounding always underrisks,
never overshoots the slot).

This module also owns ``compute_lots``/``round_down_to_lot`` — they live here
rather than in briefing_ftmo so both the briefing and this CLI share one
implementation, and so the CLI stays import-cheap (no pandas, no FxStore).

Examples:
  ./run.sh python src/bud/size.py EURUSD 1.0850 1.0800 --risk 80
        # long, 50-pip stop, $80 slot -> lots

  ./run.sh python src/bud/size.py USDJPY 147.20 146.50 --risk 80 --target 148.60
        # also prints R:R and the dollar value at target

  ./run.sh python src/bud/size.py GBPCAD 1.7400 1.7460 --lots 0.17
        # reverse: what does 0.17 lots actually risk here?

  ./run.sh python src/bud/size.py --list
        # dump the instrument table (symbol, pip size, $/pip/lot, min lot)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Optional

from bud.envelope import DEFAULT_CONFIG_PATH, load_config

# --- pure sizing math (shared with bud.briefing_ftmo) ---------------------


def round_down_to_lot(lots: float, min_lot: float) -> float:
    """Round lots down to the broker's min-lot increment."""
    if min_lot <= 0 or lots <= 0:
        return 0.0
    return math.floor(lots / min_lot) * min_lot


def compute_lots(entry: float, stop: float, risk_usd: float,
                 instrument: dict) -> tuple[float, float]:
    """Returns (lots, actual_risk_usd). 0.0 if anything degenerate."""
    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0:
        return 0.0, 0.0
    pip_size = float(instrument["pip_size"])
    dpp = float(instrument["dollar_per_pip_per_lot"])
    risk_in_pips = risk_per_unit / pip_size
    if risk_in_pips <= 0 or dpp <= 0:
        return 0.0, 0.0
    raw_lots = risk_usd / (risk_in_pips * dpp)
    lots = round_down_to_lot(raw_lots, float(instrument["min_lot"]))
    actual_risk = lots * risk_in_pips * dpp
    return lots, actual_risk


# --- symbol resolution ----------------------------------------------------


def normalize_symbol(raw: str) -> str:
    """Any of eurusd / EUR/USD / EUR_USD / EURUSD.sim -> EURUSD.sim.

    Operators paste symbols from four different places (OANDA pair names, the
    FTMO platform, the briefing table, memory), so accept all of them.
    """
    s = raw.strip().upper().replace("/", "").replace("_", "").replace("-", "")
    if s.endswith(".SIM"):
        s = s[:-4]
    return s + ".sim"


def resolve_instrument(raw: str, config: dict) -> dict:
    """Look up one instrument, or exit with the closest matches."""
    by_ftmo = {inst["ftmo"]: inst for inst in config["instruments"]}
    want = normalize_symbol(raw)
    if want in by_ftmo:
        return by_ftmo[want]

    stem = want.replace(".sim", "")
    near = sorted(sym for sym in by_ftmo
                  if stem[:3] in sym or (len(stem) >= 6 and stem[3:6] in sym))
    msg = f"unknown instrument {raw!r} (looked for {want})"
    if near:
        msg += "\n  did you mean: " + ", ".join(s.replace(".sim", "") for s in near[:8])
    msg += f"\n  {len(by_ftmo)} instruments configured — run with --list to see them all."
    sys.exit(f"ERROR: {msg}")


def price_decimals(pip_size: float) -> int:
    """5 for 0.0001-pip pairs, 3 for JPY/HUF-style 0.01-pip pairs."""
    return int(round(-math.log10(pip_size))) + 1


# --- reporting ------------------------------------------------------------


def build_result(inst: dict, entry: float, stop: float, risk_usd: float,
                 target: Optional[float], forced_lots: Optional[float]) -> dict:
    """All the numbers the CLI prints, as a plain dict (also the --json body)."""
    pip_size = float(inst["pip_size"])
    dpp = float(inst["dollar_per_pip_per_lot"])
    min_lot = float(inst["min_lot"])

    stop_pips = abs(entry - stop) / pip_size
    side = "LONG" if stop < entry else "SHORT"

    reverse = forced_lots is not None
    if reverse:
        lots = forced_lots
        actual_risk = lots * stop_pips * dpp
    else:
        lots, actual_risk = compute_lots(entry, stop, risk_usd, inst)

    res = {
        "ftmo_symbol": inst["ftmo"],
        "name": inst["name"],
        "side": side,
        "entry": entry,
        "stop": stop,
        "stop_pips": round(stop_pips, 1),
        "pip_size": pip_size,
        "dollar_per_pip_per_lot": dpp,
        "min_lot": min_lot,
        "lots": round(lots, 2),
        "reverse": reverse,
        # In reverse mode the operator supplied the lots, so there is no slot
        # budget to compare against — don't invent one from the config.
        "risk_target_usd": None if reverse else round(risk_usd, 2),
        "risk_actual_usd": round(actual_risk, 2),
        "dollars_per_pip": round(lots * dpp, 4),
        "step_usd": round(min_lot * stop_pips * dpp, 2),
    }

    if target is not None:
        target_pips = abs(target - entry) / pip_size
        wrong_side = (side == "LONG" and target <= entry) or \
                     (side == "SHORT" and target >= entry)
        res.update({
            "target": target,
            "target_pips": round(target_pips, 1),
            "rr": round(target_pips / stop_pips, 2) if stop_pips > 0 else 0.0,
            "reward_usd": round(lots * target_pips * dpp, 2),
            "target_wrong_side": wrong_side,
        })
    return res


def render(res: dict) -> str:
    """Human-readable block. Loud about anything that would misfire live."""
    dec = price_decimals(res["pip_size"])
    out: list[str] = []
    a = out.append

    a(f"{res['ftmo_symbol']:<12} {res['name']:<9} {res['side']}")
    a(f"  entry {res['entry']:.{dec}f}   stop {res['stop']:.{dec}f}"
      f"   ->  {res['stop_pips']:.1f} pips")
    a(f"  ${res['dollar_per_pip_per_lot']:.2f} per pip per lot"
      f"   (min lot {res['min_lot']:g})")
    a("")

    budget = res["risk_target_usd"]

    if res["lots"] <= 0:
        min_risk = res["step_usd"]
        a(f"  LOTS: 0.00  — stop too wide for a ${budget:.2f} slot.")
        a(f"  The smallest tradeable size ({res['min_lot']:g} lots) already risks "
          f"${min_risk:.2f}.")
        a(f"  Either widen the slot to ${min_risk:.2f}+ or tighten the stop to "
          f"{budget / (res['min_lot'] * res['dollar_per_pip_per_lot']):.1f} pips.")
        return "\n".join(out)

    against = "" if budget is None else f"   (target ${budget:.2f})"
    a(f"  LOTS: {res['lots']:.2f}          risk ${res['risk_actual_usd']:.2f}{against}")
    a(f"  ${res['dollars_per_pip']:.2f} per pip"
      f"        one {res['min_lot']:g}-lot step = ${res['step_usd']:.2f}")

    if "target" in res:
        a("")
        a(f"  target {res['target']:.{dec}f}   {res['target_pips']:.1f} pips"
          f"   R:R {res['rr']:.2f}   reward ${res['reward_usd']:.2f}")
        if res["target_wrong_side"]:
            a(f"  !! TARGET IS ON THE WRONG SIDE for a {res['side']} — check the ticket.")

    # Rounding down to the lot step can leave a slot materially underused; on
    # wide stops one step is a large fraction of the budget, so say so.
    shortfall = 0.0 if budget is None else budget - res["risk_actual_usd"]
    if budget is not None and budget > 0 and shortfall / budget > 0.10:
        a("")
        a(f"  note: lot rounding leaves ${shortfall:.2f} of the slot unused "
          f"({shortfall / res['risk_target_usd'] * 100:.0f}%) — one more step "
          f"would risk ${res['risk_actual_usd'] + res['step_usd']:.2f}.")
    return "\n".join(out)


def render_table(config: dict) -> str:
    """The instrument table, so the operator can audit V without reading JSON."""
    rows = sorted(config["instruments"], key=lambda i: (i.get("tier", 9), i["ftmo"]))
    out = [f"{'SYMBOL':<12} {'NAME':<9} {'PIP':>8} {'$/PIP/LOT':>10} "
           f"{'MIN LOT':>8} {'$/1.00 MOVE':>12} {'TIER':>5}",
           "-" * 70]
    for i in rows:
        pip, dpp = float(i["pip_size"]), float(i["dollar_per_pip_per_lot"])
        out.append(f"{i['ftmo'].replace('.sim', ''):<12} {i['name']:<9} {pip:>8g} "
                   f"{dpp:>10.2f} {float(i['min_lot']):>8g} {dpp / pip:>12,.0f} "
                   f"{i.get('tier', ''):>5}")
    out.append("")
    out.append(f"{len(rows)} instruments.  $/1.00 MOVE = $/pip/lot / pip size — "
               f"the V in  lots = risk / (|entry-stop| x V).")
    return "\n".join(out)


# --- CLI ------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="bud.size",
        description="FTMO lot-size calculator (shares the briefing's instrument "
                    "table and sizing math).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  size.py EURUSD 1.0850 1.0800 --risk 80\n"
               "  size.py USDJPY 147.20 146.50 --risk 80 --target 148.60\n"
               "  size.py GBPCAD 1.7400 1.7460 --lots 0.17\n"
               "  size.py --list\n")
    p.add_argument("symbol", nargs="?", help="EURUSD, EUR/USD, EUR_USD or EURUSD.sim")
    p.add_argument("entry", nargs="?", type=float, help="entry price")
    p.add_argument("stop", nargs="?", type=float, help="stop price (side is inferred)")
    p.add_argument("--risk", type=float, default=None,
                   help="dollar risk for this trade (default: from bud/config.json)")
    p.add_argument("--risk-pct", type=float, default=None,
                   help="risk as %% of account instead of dollars, e.g. 0.8")
    p.add_argument("--target", type=float, default=None,
                   help="take-profit price; adds R:R and reward $")
    p.add_argument("--lots", type=float, default=None,
                   help="reverse mode: given this lot size, what is the real risk?")
    p.add_argument("--list", action="store_true", help="print the instrument table and exit")
    p.add_argument("--json", action="store_true", help="emit JSON instead of the text block")
    p.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="path to bud/config.json")
    args = p.parse_args(argv)

    config = load_config(args.config)

    if args.list:
        print(render_table(config))
        return 0

    if args.symbol is None or args.entry is None or args.stop is None:
        p.error("SYMBOL, ENTRY and STOP are required (or pass --list)")

    if args.entry <= 0 or args.stop <= 0:
        sys.exit("ERROR: prices must be positive.")
    if args.entry == args.stop:
        sys.exit("ERROR: entry and stop are identical — no risk distance to size against.")

    account_size = float(config["account"]["size"])
    if args.risk is not None and args.risk_pct is not None:
        sys.exit("ERROR: pass --risk or --risk-pct, not both.")
    if args.risk_pct is not None:
        risk_usd = account_size * args.risk_pct / 100.0
    elif args.risk is not None:
        risk_usd = args.risk
    else:
        risk_usd = account_size * float(config["risk"]["max_risk_per_trade_pct"])
    if risk_usd <= 0 and args.lots is None:
        sys.exit("ERROR: risk must be positive.")
    if args.lots is not None and args.lots <= 0:
        sys.exit("ERROR: --lots must be positive.")

    inst = resolve_instrument(args.symbol, config)
    res = build_result(inst, args.entry, args.stop, risk_usd, args.target, args.lots)

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(render(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
