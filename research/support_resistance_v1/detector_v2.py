"""Rejection-confirmed support/resistance zones (v2).

Rebuilt to Brand's spec (2026-06-18): a level is NOT a level until it has been
*rejected and retested*. A zone is a RANGE around a price, seeded by a swing
pivot, and only becomes CONFIRMED after >= min_touches distinct touches, where a
"distinct" touch requires price to have first DEPARTED the zone by >= D ATR and
to be separated from the prior touch by >= min_bars. A body close beyond the zone
kills it (broken = dead; polarity flip deferred).

This fixes the v1 failures Brand caught:
  * single-pivot "levels" (287.38 hit once)  -> min_touches >= 2 required
  * "three similar highs" with no rejection   -> departure (>=D ATR) + min_bars
                                                  between touches required
  * no invalidation                           -> body-close-beyond kills the zone

Decisions locked:
  width      : ATR-relative primary, % supported (sweep both via width_mode)
  touch      : WICK into the zone (low<=top / high>=bot), close not beyond
  center     : VOLUME-WEIGHTED mean of touch extremes
  broken     : dead (no flip in v2)
  invalidation strictness : swept (invalidation_confirm_bars)

POINT-IN-TIME: swing pivots confirmed k bars late; every touch/departure/break is
decided from bars <= t; volume median is trailing-only. A zone's confirmed_bar is
stamped when its M-th touch lands -- never retroactively.

Primary entry points:
  detect_zones(...)  -> (zones, stats)   full lifecycle + respect/break tallies
  active_levels(zones, t) -> confirmed & alive zones as of bar t (for features/dump)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd

from detector import wilder_atr, fractal_pivots  # reuse causal primitives

EPS = 1e-9


@dataclass
class SRParamsV2:
    atr_window: int = 14
    fractal_k: int = 3
    width_mode: str = "atr"          # "atr" | "pct"
    width_atr: float = 0.25          # half-width = width_atr * ATR(anchor)
    width_pct: float = 0.0015        # half-width = width_pct * price(anchor)
    breakaway_depth_atr: float = 1.0  # D: min departure from zone between touches
    min_bars_between: int = 5         # G: min bars between distinct touches
    min_touches: int = 2              # M: touches needed to CONFIRM
    max_age_bars: int = 252           # expire if untouched this long (0 = never)
    invalidation_buffer_atr: float = 0.0   # extra cushion before a close "breaks" it
    invalidation_confirm_bars: int = 1     # consecutive closes beyond to kill
    use_volume_gate: bool = False
    touch_vol_min: float = 1.0        # touch vol >= alpha * trailing median
    breakaway_vol_max: float = 1.0    # departure-bar vol <= beta * trailing median
    vol_median_window: int = 60


@dataclass
class _Zone:
    side: str                 # "support" | "resistance"
    center: float
    halfwidth: float
    anchor_bar: int
    touch_bars: list = field(default_factory=list)
    last_touch_bar: int = -1
    departed: bool = False    # has price left the zone by >= D since last touch?
    confirmed_bar: Optional[int] = None
    death_bar: Optional[int] = None
    death_reason: str = ""    # "break" | "expire"
    breach_run: int = 0
    _vw: float = 0.0          # sum(vol)
    _vwp: float = 0.0         # sum(vol * touch_price)
    center_hist: list = field(default_factory=list)  # (bar, center) after each touch

    def center_asof(self, t):
        """Center as it stood at bar t (last touch <= t) — point-in-time safe."""
        ctr = self.center
        for b, cc in self.center_hist:
            if b <= t:
                ctr = cc
            else:
                break
        return ctr

    @property
    def top(self):
        return self.center + self.halfwidth

    @property
    def bot(self):
        return self.center - self.halfwidth

    @property
    def alive(self):
        return self.death_bar is None

    @property
    def confirmed(self):
        return self.confirmed_bar is not None

    def add_touch(self, bar, price, vol):
        self.touch_bars.append(bar)
        self.last_touch_bar = bar
        self._vw += vol
        self._vwp += vol * price
        if self._vw > 0:
            self.center = self._vwp / self._vw   # volume-weighted re-center
        self.center_hist.append((bar, self.center))
        self.departed = False


def prepare(high, low, close, volume, params: SRParamsV2 = SRParamsV2()):
    """Precompute the param-independent-ish inputs (ATR, swing pivots, trailing
    volume median) so a sweep can reuse them across every combo that shares
    (atr_window, fractal_k, vol_median_window). Returns a `prep` tuple."""
    high = np.asarray(high, float); low = np.asarray(low, float)
    close = np.asarray(close, float); volume = np.asarray(volume, float)
    atr = wilder_atr(high, low, close, params.atr_window)
    sh, sl = fractal_pivots(high, low, params.fractal_k)
    medv = (pd.Series(volume).rolling(params.vol_median_window, min_periods=10)
            .median().shift(1).to_numpy())
    return atr, sh, sl, medv


def detect_zones(high, low, close, volume, params: SRParamsV2 = SRParamsV2(),
                 price_rng=None, prep=None):
    """Run the zone state machine forward. Returns (zones, stats).

    price_rng: if given (a numpy Generator), the MATCHED RANDOM BASELINE — anchors
    are seeded at the same bars/sides/density as the real swing pivots, but at a
    random price (close +/- U(-3,3) ATR) instead of the pivot's extreme. Same
    confirmation+respect machine, lines drawn at random => the chance-level respect
    rate. Everything else identical, so (real - baseline) isolates the structure.

    stats accumulates, for CONFIRMED zones only:
      tests_respected : post-confirmation touches (price returned and bounced)
      tests_broken    : confirmed zones killed by a body-close-beyond
      n_confirmed     : confirmed zones
      n_zones         : all candidate zones seeded
    """
    high = np.asarray(high, float); low = np.asarray(low, float)
    close = np.asarray(close, float); volume = np.asarray(volume, float)
    n = len(close)
    if prep is not None:
        atr, sh, sl, medv = prep
    else:
        atr, sh, sl, medv = prepare(high, low, close, volume, params)

    D = params.breakaway_depth_atr
    G = params.min_bars_between
    M = params.min_touches
    buf = params.invalidation_buffer_atr
    age = params.max_age_bars
    k = params.fractal_k

    active: list[_Zone] = []     # alive zones (hot loop scans only these)
    archive: list[_Zone] = []    # dead zones, retained for historical snapshots
    stats = dict(tests_respected=0, tests_broken=0, n_confirmed=0, n_zones=0)

    def hw(anchor_price, a):
        if params.width_mode == "pct":
            return params.width_pct * anchor_price
        return params.width_atr * a

    def volume_ok_touch(t):
        if not params.use_volume_gate:
            return True
        if np.isnan(medv[t]):
            return False
        return volume[t] >= params.touch_vol_min * medv[t]

    for t in range(n):
        a = atr[t]
        if np.isnan(a) or a <= 0:
            continue

        for z in active:
            # ---- departure: price left the zone by >= D ATR since last touch ----
            if not z.departed:
                if z.side == "support" and high[t] >= z.top + D * a:
                    z.departed = True
                elif z.side == "resistance" and low[t] <= z.bot - D * a:
                    z.departed = True

            # ---- touch (wick into zone), only after a departure + G-bar gap ----
            is_touch = False
            if z.departed and (t - z.last_touch_bar) >= G and volume_ok_touch(t):
                if z.side == "support" and low[t] <= z.top and close[t] >= z.bot - buf * a:
                    z.add_touch(t, low[t], volume[t]); is_touch = True
                elif z.side == "resistance" and high[t] >= z.bot and close[t] <= z.top + buf * a:
                    z.add_touch(t, high[t], volume[t]); is_touch = True
            if is_touch:
                if z.confirmed and z.last_touch_bar == t:
                    stats["tests_respected"] += 1     # a retest of an already-real level
                if z.confirmed_bar is None and len(z.touch_bars) >= M:
                    z.confirmed_bar = t
                    stats["n_confirmed"] += 1

            # ---- invalidation: body close beyond the zone (+buffer) ----
            broke = (close[t] < z.bot - buf * a) if z.side == "support" \
                else (close[t] > z.top + buf * a)
            if broke:
                z.breach_run += 1
                if z.breach_run >= params.invalidation_confirm_bars:
                    z.death_bar = t; z.death_reason = "break"
                    if z.confirmed:
                        stats["tests_broken"] += 1
                    continue
            else:
                z.breach_run = 0

            # ---- expiry ----
            if age and (t - z.last_touch_bar) > age:
                z.death_bar = t; z.death_reason = "expire"

        # ---- seed new candidate zones from the pivot confirmed at t (i=t-k) ----
        i = t - k
        if i >= 0 and not np.isnan(atr[i]) and atr[i] > 0:
            for is_piv, side, anchor_px in ((sl[i], "support", low[i]),
                                            (sh[i], "resistance", high[i])):
                if not is_piv:
                    continue
                if price_rng is not None:        # matched random-line baseline
                    anchor_px = close[i] + float(price_rng.uniform(-3.0, 3.0)) * atr[i]
                    if anchor_px <= 0:
                        continue
                w = hw(anchor_px, atr[i])
                # skip if this pivot is already inside a live same-side zone
                inside = any(z.side == side and abs(z.center - anchor_px) <= z.halfwidth
                             for z in active)
                if inside:
                    continue
                z = _Zone(side=side, center=anchor_px, halfwidth=w, anchor_bar=i)
                z.add_touch(i, anchor_px, volume[i])   # the anchor is touch #1
                # initialise departure using only bars i..t (point-in-time safe)
                seg_hi = high[i + 1:t + 1]; seg_lo = low[i + 1:t + 1]
                if side == "support" and seg_hi.size and seg_hi.max() >= z.top + D * a:
                    z.departed = True
                if side == "resistance" and seg_lo.size and seg_lo.min() <= z.bot - D * a:
                    z.departed = True
                active.append(z)
                stats["n_zones"] += 1

        # ---- archive any zone that died this bar (keeps the hot loop small) ----
        if active and any(not z.alive for z in active):
            archive.extend(z for z in active if not z.alive)
            active = [z for z in active if z.alive]

    return active + archive, stats


@dataclass
class LevelView:
    """Point-in-time view of a confirmed zone as of a query bar."""
    side: str
    center: float
    halfwidth: float
    top: float
    bot: float
    touches: int
    confirmed_bar: int
    anchor_bar: int
    touch_bars: list
    zone: "_Zone"


def active_levels(zones: list[_Zone], t: int) -> list[LevelView]:
    """Confirmed & alive zones as of bar t (point-in-time): confirmed on or before
    t, not yet dead as of t, with the center/touches FROZEN to t (no future leak)."""
    out = []
    for z in zones:
        if z.confirmed_bar is not None and z.confirmed_bar <= t and \
           (z.death_bar is None or z.death_bar > t):
            ctr = z.center_asof(t)
            tb = [b for b in z.touch_bars if b <= t]
            out.append(LevelView(
                side=z.side, center=ctr, halfwidth=z.halfwidth,
                top=ctr + z.halfwidth, bot=ctr - z.halfwidth,
                touches=len(tb), confirmed_bar=z.confirmed_bar,
                anchor_bar=z.anchor_bar, touch_bars=tb, zone=z))
    return out


# --------------------------------------------------------------------------- #
def _smoke(symbol="AAPL", start="2015-01-01", params=SRParamsV2()):
    import duckdb
    from pathlib import Path
    db = Path(__file__).resolve().parents[2] / "data" / "ohlcv.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    d = con.execute("SELECT date,open,high,low,close,volume FROM ohlcv "
                    "WHERE symbol=? AND date>=? ORDER BY date", [symbol, start]).df()
    con.close()
    if d.empty:
        print("no data"); return
    dates = pd.to_datetime(d.date).dt.strftime("%Y-%m-%d").to_numpy()
    h, l, c, v = (d[x].to_numpy(float) for x in ("high", "low", "close", "volume"))
    zones, stats = detect_zones(h, l, c, v, params)
    asof = len(c) - 1
    live = active_levels(zones, asof)
    rr = stats["tests_respected"] / max(stats["tests_respected"] + stats["tests_broken"], 1)
    print(f"{symbol}: {stats['n_zones']} candidates -> {stats['n_confirmed']} confirmed; "
          f"respect_rate={rr:.2f} ({stats['tests_respected']}R/{stats['tests_broken']}B)")
    print(f"active confirmed levels as of {dates[asof]} (close={c[asof]:.2f}):")
    for z in sorted(live, key=lambda z: z.center):
        side = "support" if z.center < c[asof] else "resistance"
        tdates = ";".join(dates[b] for b in z.touch_bars)
        print(f"  {z.center:8.2f} {side:11} touches={len(z.touch_bars)} "
              f"conf={dates[z.confirmed_bar]} | {tdates}")


if __name__ == "__main__":
    import sys
    _smoke(sys.argv[1] if len(sys.argv) > 1 else "AAPL")
