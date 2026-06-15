"""Relative-Value door #2 — Phase 0 cointegration screen (BUD H4 forex).

For every unordered FX pair, test whether the spread log(A) - beta*log(B) is
mean-reverting AND has enough amplitude to clear 2x round-trip cost. The
amplitude-vs-cost gate is the existential test: RV pays two spreads, and spread
killed everything else this campaign. Reports a funnel + survivor list.

Validation: last 24 months reserved as untouched holdout; cointegration tested
in interleaved calendar-quarter blocks A and B (COVID in both). Estimation uses
the pre-holdout era only. See docs/planning/RELATIVE_VALUE_v1.md.
"""
from __future__ import annotations

import itertools
import json
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, coint

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators._common import ohlc_mid

warnings.simplefilter("ignore")

HOLDOUT_MONTHS = 24
P_GATE = 0.05
I1_GATE = 0.10                  # each leg must be I(1): ADF p>0.10 on its log-level
HL_MIN, HL_MAX = 30, 250        # H4 bars (~5-42 trading days) — FX reverts over weeks/months
AMP_GATE = 1.0                  # 2*sigma_spread >= round-trip cost
MIN_BLOCK = 500                 # min bars per block for a meaningful coint test

CFG = json.load(open("src/bh_ftmo_config.json"))
COMM = ("XAU","XAG","XPT","XPD","XCU","WTICO","BCO","NATGAS","CORN","WHEAT","SOYBN","SUGAR")
PAIRS = [i["name"].replace("/", "_") for i in CFG["instruments"]
         if "/" in i["name"] and not any(c in i["name"].replace("/", "_") for c in COMM)]


def load_panel():
    """Aligned log-mid-close panel + per-pair relative spread (median (ask-bid)/mid)."""
    store = FxStore(read_only=True)
    logmid, relspread = {}, {}
    try:
        for p in PAIRS:
            df = store.load(p, granularity="H4", include_incomplete=False)
            if df is None or len(df) < 2000:
                continue
            df = df.set_index("timestamp")
            mid = ohlc_mid(df)["close"]
            logmid[p] = np.log(mid)
            rs = ((df["close_ask"] - df["close_bid"]) / mid).median()
            relspread[p] = float(rs)
    finally:
        store.close()
    panel = pd.DataFrame(logmid).sort_index()
    return panel, relspread


def half_life(s: np.ndarray) -> float:
    """OU half-life from dS_t = lambda*S_{t-1} + c. Returns +inf if non-reverting."""
    s = s[np.isfinite(s)]
    if len(s) < 50:
        return np.inf
    lag = s[:-1]
    d = np.diff(s)
    A = np.vstack([lag, np.ones_like(lag)]).T
    lam = np.linalg.lstsq(A, d, rcond=None)[0][0]
    if lam >= 0:
        return np.inf
    return float(-np.log(2) / lam)


def main():
    panel, relspread = load_panel()
    pairs = [p for p in PAIRS if p in panel.columns]
    cutoff = panel.index.max() - pd.DateOffset(months=HOLDOUT_MONTHS)
    pre = panel.loc[panel.index < cutoff]
    q = pre.index.year * 4 + (pre.index.quarter - 1)          # quarter ordinal
    mask_A = (q % 2 == 0)
    print(f"pairs={len(pairs)}  pre-holdout bars={len(pre)} "
          f"({pre.index.min().date()}..{pre.index.max().date()})  "
          f"holdout reserved from {cutoff.date()}")
    print(f"block A bars={int(mask_A.sum())}  block B bars={int((~mask_A).sum())}\n")

    # Engle-Granger precondition: each leg must be I(1) (unit root not rejected on
    # its own log-level). This voids degenerate near-zero-beta "cointegrations"
    # where the spread is really one stationary leg = single-pair MR in disguise.
    i1 = {}
    for p in pairs:
        s = pre[p].dropna().to_numpy()
        i1[p] = adfuller(s, maxlag=1, autolag=None)[1] > I1_GATE
    n_i1 = sum(i1.values())
    print(f"legs individually I(1) (non-stationary): {n_i1}/{len(pairs)}\n")

    funnel = dict(combos=0, both_data=0, i1_both=0, coint_both=0, hl_ok=0, amp_ok=0)
    rows = []
    for a, b in itertools.combinations(pairs, 2):
        funnel["combos"] += 1
        if not (i1[a] and i1[b]):                            # both legs must be I(1)
            continue
        funnel["i1_both"] += 1
        sub = pre[[a, b]].dropna()
        if len(sub) < 2 * MIN_BLOCK:
            continue
        la, lb = sub[a].to_numpy(), sub[b].to_numpy()
        mA = mask_A[pre.index.isin(sub.index)]
        if mA.sum() < MIN_BLOCK or (~mA).sum() < MIN_BLOCK:
            continue
        funnel["both_data"] += 1
        try:
            # fixed small lag (autolag off) — the AIC lag search is the screen's
            # dominant cost and is overkill for a stationarity go/no-go.
            pA = coint(la[mA], lb[mA], maxlag=1, autolag=None)[1]
            pB = coint(la[~mA], lb[~mA], maxlag=1, autolag=None)[1]
        except Exception:
            continue
        if not (pA < P_GATE and pB < P_GATE):
            continue
        funnel["coint_both"] += 1
        # Record EVERY coint-both pair (gates as flags, not row-drops) so the
        # half-life / amplitude distributions are visible for the audit.
        beta = np.polyfit(lb, la, 1)[0]                       # full pre-holdout hedge ratio
        spread = la - beta * lb
        hl = half_life(spread)
        sigma = float(np.std(spread))
        cost = relspread[a] + abs(beta) * relspread[b]
        amp = 2 * sigma / cost if cost > 0 else np.inf
        hl_ok = HL_MIN <= hl <= HL_MAX
        funnel["hl_ok"] += int(hl_ok)
        funnel["amp_ok"] += int(hl_ok and amp >= AMP_GATE)
        rows.append(dict(a=a, b=b, pA=pA, pB=pB, beta=beta, half_life_bars=hl,
                         sigma=sigma, cost=cost, amp_ratio=amp,
                         hl_ok=hl_ok, passes=bool(hl_ok and amp >= AMP_GATE)))

    R = pd.DataFrame(rows).sort_values("amp_ratio", ascending=False) if rows else pd.DataFrame()
    print("=== FUNNEL ===")
    print(f"  {funnel['combos']:4d} pair combos")
    print(f"  {funnel['i1_both']:4d} with BOTH legs I(1) (genuine 2-leg candidates)")
    print(f"  {funnel['both_data']:4d} with enough data in both blocks")
    print(f"  {funnel['coint_both']:4d} cointegrated (p<{P_GATE}) in BOTH halves")
    print(f"  {funnel['hl_ok']:4d} half-life in [{HL_MIN},{HL_MAX}] bars")
    print(f"  {funnel['amp_ok']:4d} amplitude 2*sigma >= bid/ask cost (carry NOT yet modelled)")
    if len(R):
        # Audit: distributions across ALL coint-both pairs (why the gates bite).
        hl = R["half_life_bars"].replace([np.inf, -np.inf], np.nan).dropna()
        print("\n=== AUDIT: distributions across the coint-both pairs ===")
        print(f"  half-life bars   (n={len(hl)} finite): "
              f"min {hl.min():.0f} | p25 {hl.quantile(.25):.0f} | median {hl.median():.0f} "
              f"| p75 {hl.quantile(.75):.0f} | max {hl.max():.0f}")
        print(f"  non-reverting (half-life = inf): {int((~np.isfinite(R['half_life_bars'])).sum())}")
        print(f"  amplitude ratio  (2*sigma/cost): "
              f"min {R.amp_ratio.min():.2f} | median {R.amp_ratio.median():.2f} "
              f"| p90 {R.amp_ratio.quantile(.9):.2f} | max {R.amp_ratio.max():.2f}")
        print(f"  pairs with half-life <= 250 bars (~42d): {int((R.half_life_bars<=250).sum())}")
        print(f"  pairs with amp_ratio >= 1 (any half-life): {int((R.amp_ratio>=1).sum())}")
        out = "research/relative_value_v1/rv_p0_survivors.csv"
        R.to_csv(out, index=False)
        show = R.head(20).copy()
        for c in ["pA","pB","beta","sigma","cost"]:
            show[c] = show[c].map(lambda x: f"{x:.4f}")
        show["half_life_bars"] = show["half_life_bars"].map(lambda x: f"{x:.0f}")
        show["amp_ratio"] = show["amp_ratio"].map(lambda x: f"{x:.2f}")
        print("\n=== top candidates by amplitude ratio (all passed coint-both + half-life) ===")
        print(show.to_string(index=False))
        print(f"\nwrote {out} ({len(R)} cointegrated+half-life rows, "
              f"{int(R.passes.sum())} clear the amplitude gate)")
    else:
        print("\nno pair cleared coint-both + half-life — door looks shut at the screen.")


if __name__ == "__main__":
    main()
