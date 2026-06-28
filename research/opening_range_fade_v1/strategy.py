"""Core strategy logic: build a setup from one session's bars, then simulate it.

This is the validated core. `simulate` is unified across all three experiments:
  - baseline:        simulate(s, bounce_b=0.0, stop_mult=1.0)
  - Variant B:       simulate(s, bounce_b=0.20, stop_mult=1.0)
  - stop sweep:      simulate(s, bounce_b=0.0, stop_mult=m)
Variant A ("extreme must hold") is a pre-filter on s["ext_from_end"], applied by the caller.

Units: U = STOP_FRAC * R_open (the original 1x stop distance, in price). Target sits at +2U.
"""
import config as C


def build_setup(bars):
    """bars: sorted list of (hm, open, high, low, close) for one session, hm <= 11:00.
    Returns a setup dict, or None if the day is untradeable / a doji."""
    opening = [b for b in bars if C.OPEN_START <= b[0] <= C.OPEN_END]
    if len(opening) < 10:
        return None
    H15 = max(b[2] for b in opening)
    L15 = min(b[3] for b in opening)
    R = H15 - L15
    if R <= 0:
        return None
    c_open, c_close = opening[0][1], opening[-1][4]
    sim = [b for b in bars if C.SIM_START <= b[0] <= C.SIM_END]
    if not sim:
        return None

    if c_close < c_open:            # red opening candle -> fade the low -> LONG
        side, entry, tp = "LONG", L15, L15 + C.FIB_TP_NEG * R
        ext_pos = min(range(len(opening)), key=lambda i: opening[i][3])   # bar that made the low
    elif c_close > c_open:          # green opening candle -> fade the high -> SHORT
        side, entry, tp = "SHORT", H15, L15 + C.FIB_TP_POS * R
        ext_pos = max(range(len(opening)), key=lambda i: opening[i][2])   # bar that made the high
    else:
        return None                 # doji: no directional bias

    U = C.STOP_FRAC * R
    return dict(side=side, entry=entry, tp=tp, U=U, R=R, L15=L15, H15=H15, sim=sim,
                ext_from_end=len(opening) - 1 - ext_pos)


def simulate(s, bounce_b=0.0, stop_mult=1.0):
    """Returns (outcome, pnl_in_U). outcome in {WIN, LOSS, TIMEOUT, NEVER_FILLED}.
    Intrabar ties (a bar touching both target and stop) resolve pessimistically as LOSS."""
    side, entry, tp, U = s["side"], s["entry"], s["tp"], s["U"]
    sl = entry - stop_mult * U if side == "LONG" else entry + stop_mult * U
    confirm = (s["L15"] + bounce_b * s["R"]) if side == "LONG" else (s["H15"] - bounce_b * s["R"])
    confirmed = bounce_b <= 0.0
    filled = False
    for (hm, o, h, l, c) in s["sim"]:
        if not confirmed:           # Variant B gate: price must lift off the extreme first
            if (side == "LONG" and h >= confirm) or (side == "SHORT" and l <= confirm):
                confirmed = True
            else:
                continue
        if not filled:
            if (side == "LONG" and l <= entry) or (side == "SHORT" and h >= entry):
                filled = True
            else:
                continue
        if side == "LONG":
            hitTP, hitSL = h >= tp, l <= sl
        else:
            hitTP, hitSL = l <= tp, h >= sl
        if hitTP and hitSL:
            return "LOSS", -stop_mult
        if hitSL:
            return "LOSS", -stop_mult
        if hitTP:
            return "WIN", +2.0
    if not filled:
        return "NEVER_FILLED", None
    exitp = s["sim"][-1][4]          # filled but unresolved -> exit at the 11:00 close
    pnl = (exitp - entry) / U if side == "LONG" else (entry - exitp) / U
    return "TIMEOUT", pnl
