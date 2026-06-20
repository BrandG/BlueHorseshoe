"""S/R v3 — shelf-anchored, magnet-optimized, polarity-agnostic levels.

Rebuilt on Brand's critique of v2 (2026-06-18). Five principles:

1. ANCHOR ON SHELVES, NOT SPIKES. A candidate is born from a *consolidation*: a
   window of `shelf_bars` whose whole range <= `flat_band` ATR (price went flat),
   immediately followed by a departure >= `breakaway` ATR. The blip-pivots v2
   mistook for levels (a single-bar V) are not flat, so they no longer qualify.
   ("flat over a few bars, then a big move" — Brand.)

2. ONE ROLE-AGNOSTIC POOL, POLARITY FLIP ON. A shelf that departs UP acted as
   support; one that departs DOWN acted as resistance — but both are just reaction
   events at a price. A level accumulates events from BOTH sides (Brand's 247.0,
   which was hit as support AND resistance). Side is decided only vs current price.

3. MAGNET PRICE. Events within `magnet_band` ATR cluster into one level, and the
   level price is the reaction-magnitude-weighted mean of its events — it migrates
   to the price the market actually keeps reacting at (247.0 beats the 243.34 pivot
   extreme because more reactions land there).

4. STRENGTH = REACTION MAGNITUDE x RECENCY. Each event contributes the size of its
   move-away (ATR), decayed by age. Recent, hard reactions outweigh old, weak ones.

5. STALE = DEAD (no break-invalidation). With polarity flip ON a "break" just turns
   support into resistance, so a level persists until it goes `max_age_bars` with no
   new event. `range_score` (Kaufman efficiency ratio) lets callers keep only
   range-bound symbols, where price actually revisits levels.

POINT-IN-TIME: every event is stamped at its DEPARTURE bar (the first bar we could
know it). Cluster centers/touch-counts are served as-of the query bar via stored
history, so a level never reflects a future event. Verified by truncation test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import numpy as np, pandas as pd

from detector import wilder_atr  # causal ATR

EPS = 1e-9


@dataclass
class SRParamsV3:
    atr_window: int = 14
    shelf_bars: int = 5           # consolidation window length
    flat_band: float = 0.8        # shelf flat if CLOSE range over window <= flat_band*ATR
    breakaway: float = 1.0        # departure / reaction threshold in ATR
    dep_window: int = 8           # bars to look for the departure after a shelf
    magnet_band: float = 0.5      # events within this many ATR cluster into one level
    min_touches: int = 2          # events to CONFIRM a level
    max_age_bars: int = 378       # ~18 months; level stale if no event this long
    recency_halflife: float = 63.0   # ~3 months — recent touches weigh much more
    width_atr: float = 0.15       # half-width of the reported zone (display/tests)


# ----------------------------------------------------------------------------- #
def detect_events(high, low, close, atr, params: SRParamsV3):
    """Causal shelf-departure events. Each = (confirm_bar, shelf_bar, price,
    magnitude_atr, direction). confirm_bar = the DEPARTURE bar (when we may first
    know the shelf was real -> point-in-time gate). shelf_bar = where price actually
    CONSOLIDATED (end of the flat window) -> what we display/date and weight by
    recency. direction +1 = departed up (acted support), -1 = down (resistance)."""
    n = len(close)
    sb = params.shelf_bars
    events = []
    i = max(sb, params.atr_window + 1)
    while i < n:
        a = atr[i]
        if np.isnan(a) or a <= 0:
            i += 1; continue
        w0 = i - sb + 1
        crange = close[w0:i + 1].max() - close[w0:i + 1].min()
        if crange <= params.flat_band * a:              # flat shelf (closes) ending at i
            P = float(close[w0:i + 1].mean())
            jmax = min(i + params.dep_window, n - 1)
            hit = None
            for j in range(i + 1, jmax + 1):
                up = high[j] - P; dn = P - low[j]
                if up >= params.breakaway * a:
                    hit = (j, P, up / a, +1); break
                if dn >= params.breakaway * a:
                    hit = (j, P, dn / a, -1); break
            if hit is not None:
                j, Pp, mag, dr = hit
                events.append((j, i, Pp, mag, dr))   # confirm_bar, shelf_bar, price, mag, dir
                i = j                 # jump past departure (de-dup overlapping shelves)
                continue
        i += 1
    return events


@dataclass
class _Cluster:
    center: float
    confirm_bars: list = field(default_factory=list)  # PIT: when each event became known
    shelf_bars: list = field(default_factory=list)    # display/recency: where price consolidated
    prices: list = field(default_factory=list)
    mags: list = field(default_factory=list)
    dirs: list = field(default_factory=list)
    last_shelf: int = -1
    confirmed_bar: Optional[int] = None
    _w: float = 0.0
    _wp: float = 0.0
    center_hist: list = field(default_factory=list)   # (confirm_bar, center, count)

    def add(self, confirm_bar, shelf_bar, price, mag, direction, min_touches):
        self.confirm_bars.append(confirm_bar); self.shelf_bars.append(shelf_bar)
        self.prices.append(price); self.mags.append(mag); self.dirs.append(direction)
        self.last_shelf = max(self.last_shelf, shelf_bar)
        self._w += mag; self._wp += mag * price
        self.center = self._wp / (self._w + EPS)        # magnitude-weighted magnet
        self.center_hist.append((confirm_bar, self.center, len(self.prices)))
        if self.confirmed_bar is None and len(self.prices) >= min_touches:
            self.confirmed_bar = confirm_bar            # PIT: known only at departure

    def center_asof(self, t):
        ctr = self.center
        for b, cc, _ in self.center_hist:
            if b <= t:
                ctr = cc
            else:
                break
        return ctr


def build_levels(events, atr, params: SRParamsV3):
    """Cluster events (in departure-bar order) into magnet levels. Causal: a new
    event joins the nearest live cluster within magnet_band, else starts one."""
    clusters: list[_Cluster] = []
    for (cbar, sbar, P, mag, direction) in events:
        a = atr[cbar]
        if np.isnan(a) or a <= 0:
            continue
        tol = params.magnet_band * a
        best, bestd = None, tol
        for cl in clusters:
            if cbar - cl.last_shelf > params.max_age_bars:   # stale -> don't absorb
                continue
            d = abs(cl.center - P)
            if d <= bestd:
                best, bestd = cl, d
        if best is None:
            cl = _Cluster(center=P)
            cl.add(cbar, sbar, P, mag, direction, params.min_touches)
            clusters.append(cl)
        else:
            best.add(cbar, sbar, P, mag, direction, params.min_touches)
    return clusters


@dataclass
class LevelView3:
    center: float
    halfwidth: float
    touches: int
    up_touches: int          # acted as support (departed up)
    down_touches: int        # acted as resistance (departed down)
    strength: float
    confirmed_bar: int
    first_bar: int
    last_bar: int
    touch_bars: list          # shelf bars (where price consolidated)
    touch_prices: list        # the actual consolidation price of each touch


def active_levels(clusters, t, params: SRParamsV3, atr=None):
    """Confirmed, non-stale levels as of bar t (point-in-time)."""
    out = []
    for cl in clusters:
        if cl.confirmed_bar is None or cl.confirmed_bar > t:
            continue
        # PIT visibility: only events whose departure (confirm) bar is known by t.
        known = [k for k, cb in enumerate(cl.confirm_bars) if cb <= t]
        if not known:
            continue
        last_le = max(cl.shelf_bars[k] for k in known)
        if t - last_le > params.max_age_bars:
            continue
        ctr = cl.center_asof(t)
        ups = sum(1 for k in known if cl.dirs[k] > 0)
        downs = len(known) - ups
        # strength: magnitude x recency, dated to the SHELF (when price was there).
        strg = sum(cl.mags[k] * 0.5 ** ((t - cl.shelf_bars[k]) / params.recency_halflife)
                   for k in known)
        a = atr[t] if (atr is not None and not np.isnan(atr[t])) else (ctr * params.width_atr)
        hw = params.width_atr * a
        pairs = sorted((cl.shelf_bars[k], cl.prices[k]) for k in known)
        out.append(LevelView3(center=ctr, halfwidth=hw, touches=len(known),
                              up_touches=ups, down_touches=downs, strength=strg,
                              confirmed_bar=cl.confirmed_bar, first_bar=pairs[0][0],
                              last_bar=last_le, touch_bars=[p[0] for p in pairs],
                              touch_prices=[p[1] for p in pairs]))
    return out


def detect(high, low, close, params: SRParamsV3 = SRParamsV3(), atr=None):
    high = np.asarray(high, float); low = np.asarray(low, float); close = np.asarray(close, float)
    if atr is None:
        atr = wilder_atr(high, low, close, params.atr_window)
    events = detect_events(high, low, close, atr, params)
    clusters = build_levels(events, atr, params)
    return clusters, atr


def dedupe_levels(views, atr_at, min_sep_atr=1.0):
    """Non-max suppression: keep the strongest level in any min_sep_atr-ATR
    neighborhood, drop near-duplicates. One clean line per zone (Brand: levels
    stacked within ~1 ATR read as one zone, not four)."""
    kept = []
    for v in sorted(views, key=lambda z: -z.strength):
        if all(abs(v.center - k.center) >= min_sep_atr * atr_at for k in kept):
            kept.append(v)
    return kept


def range_score(close, window=100):
    """Kaufman efficiency ratio, averaged. LOW = choppy/range-bound (good for S/R);
    HIGH (->1) = clean trend (price rarely revisits a level)."""
    c = np.asarray(close, float)
    if len(c) <= window + 5:
        return np.nan
    diff = np.abs(np.diff(c))
    er = []
    for t in range(window, len(c)):
        noise = diff[t - window:t].sum()
        if noise > 0:
            er.append(abs(c[t] - c[t - window]) / noise)
    return float(np.mean(er)) if er else np.nan


# ----------------------------------------------------------------------------- #
def _smoke(symbol="AAPL", start="2015-01-01", params=None):
    import duckdb
    from pathlib import Path
    params = params or SRParamsV3()
    db = Path(__file__).resolve().parents[2] / "data" / "ohlcv.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    d = con.execute("SELECT date,open,high,low,close,volume FROM ohlcv "
                    "WHERE symbol=? AND date>=? ORDER BY date", [symbol, start]).df()
    con.close()
    if d.empty:
        print("no data"); return
    dates = pd.to_datetime(d.date).dt.strftime("%Y-%m-%d").to_numpy()
    h, l, c = (d[x].to_numpy(float) for x in ("high", "low", "close"))
    clusters, atr = detect(h, l, c, params)
    asof = len(c) - 1
    live = active_levels(clusters, asof, params, atr)
    rs = range_score(c)
    print(f"{symbol}: range_score(ER)={rs:.3f}  events->{len(clusters)} clusters; "
          f"{len(live)} active confirmed levels as of {dates[asof]} (close={c[asof]:.2f})")
    for v in sorted(live, key=lambda z: -z.strength):
        side = "support" if v.center < c[asof] else "resistance"
        td = ";".join(dates[b] for b in v.touch_bars)
        print(f"  {v.center:8.2f} {side:11} touches={v.touches} "
              f"(S{v.up_touches}/R{v.down_touches}) strength={v.strength:.2f} | {td}")


if __name__ == "__main__":
    import sys
    _smoke(sys.argv[1] if len(sys.argv) > 1 else "AAPL")
