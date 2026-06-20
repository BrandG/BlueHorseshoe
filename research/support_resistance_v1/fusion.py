"""Fusion S/R: location from the Volume Profile, validation from reactions.

Profile peaks give objective, parameter-light LOCATION; v3 shelf-departure events
give the "price actually REVERSED here" filter the profile lacks. A profile peak is
kept only if >= min_reactions reaction events sit within snap_atr of it -- which
drops the pass-through nodes (Brand's VZ 37.44 "opposite of S/R").

fuse_levels() -> (levels, atr, atr_at, as_of). Each level:
  price   : the profile peak (objective location)
  weight  : profile peak height (volume x recency)
  touches : # reaction events near it ; up/down = acted support/resistance
  reactions : list of (confirm_bar, shelf_bar, price, mag_atr, dir)
"""
from __future__ import annotations
import numpy as np

from detector import wilder_atr
from detector_v3 import detect_events, SRParamsV3
from profile import compute_profile, ProfileParams


def fuse_levels(high, low, close, volume, as_of=None,
                pp: ProfileParams = None, vp: SRParamsV3 = None,
                snap_atr: float = 0.6, min_reactions: int = 2):
    pp = pp or ProfileParams(); vp = vp or SRParamsV3()
    high = np.asarray(high, float); low = np.asarray(low, float)
    close = np.asarray(close, float); volume = np.asarray(volume, float)
    n = len(close)
    if as_of is None:
        as_of = n - 1

    _, _, peaks, atr_at, _ = compute_profile(high, low, close, volume, pp, as_of)
    atr = wilder_atr(high, low, close, vp.atr_window)
    events = [e for e in detect_events(high, low, close, atr, vp) if e[1] <= as_of]

    levels = []
    for pk in peaks:
        near = [e for e in events if abs(e[2] - pk["price"]) <= snap_atr * atr_at]
        if len(near) < min_reactions:
            continue
        ups = sum(1 for e in near if e[4] > 0)
        levels.append(dict(price=pk["price"], weight=pk["weight"], reactions=near,
                           touches=len(near), up=ups, down=len(near) - ups))
    levels.sort(key=lambda d: -d["weight"])
    return levels, atr, atr_at, as_of
