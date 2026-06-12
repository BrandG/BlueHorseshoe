"""Tracking-only options-fear annotation for DeepOS-family fires.

Research lineage (2026-06): deepos_options_deeptail robustness pass. These
fields freeze into ``journal_signals`` and flow to matured hypothetical trades
so the forward record can split deep fires by options skew. NOT a gate, NOT
sizing, NOT selection.

Point-in-time safety: the caller must gate this to live predictions only.
Alpha Vantage HISTORICAL_OPTIONS is called without a date parameter so pre-open
prediction runs receive the most recent EOD chain.
"""
import logging
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
import requests
from ratelimit import limits, sleep_and_retry

from bluehorseshoe.core.symbols import ALPHAVANTAGE_KEY, CPS

logger = logging.getLogger(__name__)

# Frozen from deepos_options_deeptail research pass; do not recompute live.
SK_FEAR_CUT = 0.107      # q67 skew_25d, covered nonbull fires 2016-2026
DD10_DEEP_CUT = 4.68     # q67 DD10/ATR, covered nonbull fires (same run)
DTE_MIN, DTE_MAX = 7, 90
DTE_TARGET, DTE_LO, DTE_HI = 30, 20, 60
DELTA_SLIM = (0.05, 0.95)
P25_BAND = (-0.45, -0.10)
C25_BAND = (0.10, 0.45)
IV_VALID = (0.01, 5.0)
ANNOTATION_CAP = 200

SCORE_KEYS = ("deep_os_score", "deep_os_ha_score")
OPTIONS_URL = "https://www.alphavantage.co/query"


def _num(value: Any) -> float:
    try:
        if value in (None, "", "None"):
            return float("nan")
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _finite_or_none(value: Any) -> Optional[float]:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


@sleep_and_retry
@limits(calls=1, period=1.0 / CPS)
def fetch_chain(symbol: str, api_key: Optional[str] = None, timeout: int = 30) -> List[Dict[str, Any]]:
    """Fetch the latest EOD Alpha Vantage HISTORICAL_OPTIONS chain.

    Intentionally sends no ``date`` parameter: live prediction runs pre-open, so
    Alpha Vantage's most recent EOD chain is the fire-date close convention used
    by the research pull.
    """
    key = api_key or ALPHAVANTAGE_KEY or os.environ.get("ALPHAVANTAGE_KEY", "")
    if not key:
        raise RuntimeError("ALPHAVANTAGE_KEY not set in environment")

    sym = symbol.upper().strip()
    if not sym:
        raise ValueError("symbol is required")

    response = requests.get(
        OPTIONS_URL,
        params={"function": "HISTORICAL_OPTIONS", "symbol": sym, "apikey": key},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if "Note" in payload or "Information" in payload:
        msg = str(payload.get("Note") or payload.get("Information"))[:160]
        raise RuntimeError(f"Alpha Vantage options gate: {msg}")
    if "Error Message" in payload:
        return []
    return payload.get("data", []) or []


def _contracts_from_chain(chain: Any) -> List[Dict[str, Any]]:
    if isinstance(chain, dict):
        data = chain.get("data", [])
    else:
        data = chain
    return data if isinstance(data, list) else []


def _slim_chain(chain: Any, fire_date: str) -> pd.DataFrame:
    try:
        fdt = datetime.strptime(str(fire_date)[:10], "%Y-%m-%d").date()
    except ValueError:
        return pd.DataFrame()

    rows = []
    for row in _contracts_from_chain(chain):
        exp = row.get("expiration")
        try:
            dte = (datetime.strptime(str(exp)[:10], "%Y-%m-%d").date() - fdt).days
        except (TypeError, ValueError):
            continue
        delta = _num(row.get("delta"))
        if dte < DTE_MIN or dte > DTE_MAX:
            continue
        if not DELTA_SLIM[0] <= abs(delta) <= DELTA_SLIM[1]:
            continue
        rows.append({
            "expiration": str(exp)[:10],
            "dte": int(dte),
            "strike": _num(row.get("strike")),
            "type": str(row.get("type", "")).lower(),
            "iv": _num(row.get("implied_volatility")),
            "delta": delta,
        })
    return pd.DataFrame(rows)


def _target_expiration(df: pd.DataFrame) -> tuple[Optional[str], Optional[int]]:
    dtes = np.array(sorted(df["dte"].dropna().astype(int).unique()))
    band = dtes[(dtes >= DTE_LO) & (dtes <= DTE_HI)]
    choices = band if len(band) else dtes[dtes >= DTE_MIN]
    if not len(choices):
        return None, None
    dte = int(sorted(choices, key=lambda x: (abs(x - DTE_TARGET), x))[0])
    exp = df.loc[df["dte"] == dte, "expiration"].sort_values().iloc[0]
    return str(exp), dte


def _valid_iv(series: pd.Series) -> pd.Series:
    return series.notna() & (series > IV_VALID[0]) & (series < IV_VALID[1])


def _delta_iv(df: pd.DataFrame, typ: str, target: float, lo: float, hi: float) -> Optional[float]:
    mask = df["type"].eq(typ) & _valid_iv(df["iv"]) & df["delta"].between(lo, hi)
    legs = df.loc[mask].copy()
    if legs.empty:
        return None
    legs["dist"] = (legs["delta"] - target).abs()
    return float(legs.sort_values(["dist", "strike"]).iloc[0]["iv"])


def _resolve_close(chain: Any, close: Optional[float]) -> Optional[float]:
    if close is not None:
        return _finite_or_none(close)
    if isinstance(chain, dict):
        for key in ("close", "underlying_price", "underlyingPrice", "last_close"):
            resolved = _finite_or_none(chain.get(key))
            if resolved is not None:
                return resolved
    return None


def compute_options_features(
    chain: Any,
    fire_date: str,
    close: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Compute research-faithful 25-delta skew and ATM IV features.

    Returns ``None`` when no slim contracts survive. Invalid-IV chains still
    return a feature row with ``skew``/``atm_iv`` as ``None`` so deep_nochain is
    distinguishable from failed fetch.
    """
    df = _slim_chain(chain, fire_date)
    if df.empty:
        return None

    exp, dte = _target_expiration(df)
    tdf = df[df["expiration"].eq(exp)].copy() if exp is not None else df.iloc[0:0].copy()
    if tdf.empty:
        return None

    atm_iv = None
    px = _resolve_close(chain, close)
    if px is not None and px > 0 and tdf["strike"].notna().any():
        atm_strike = float(tdf.iloc[(tdf["strike"] - px).abs().argsort()[:1]]["strike"].iloc[0])
        atm = tdf[tdf["strike"].eq(atm_strike)]
        atm_valid = atm.loc[_valid_iv(atm["iv"]), "iv"]
        if not atm_valid.empty:
            atm_iv = float(atm_valid.mean())

    put_iv = _delta_iv(tdf, "put", -0.25, P25_BAND[0], P25_BAND[1])
    call_iv = _delta_iv(tdf, "call", 0.25, C25_BAND[0], C25_BAND[1])
    skew = put_iv - call_iv if put_iv is not None and call_iv is not None else None

    return {
        "skew": _finite_or_none(skew),
        "atm_iv": _finite_or_none(atm_iv),
        "dte_used": int(dte) if dte is not None else None,
        "n_contracts": int(len(df)),
    }


def compute_dd10(closes: Sequence[Any], atr: Any) -> float:
    """(rolling-10 max close - close) / ATR at the fire bar."""
    atr_val = _finite_or_none(atr)
    if atr_val is None or atr_val <= 0:
        return float("nan")
    vals = [_finite_or_none(x) for x in (closes or [])]
    vals = [x for x in vals if x is not None]
    if not vals:
        return float("nan")
    tail = vals[-10:]
    return float((max(tail) - tail[-1]) / atr_val)


def classify_arm(dd10: Any, feats: Optional[Dict[str, Any]]) -> str:
    """Research arm for forward evaluation."""
    dd = _finite_or_none(dd10)
    if dd is None or dd <= DD10_DEEP_CUT:
        return "shallow"
    if not feats:
        return "deep_nochain"
    skew = _finite_or_none(feats.get("skew"))
    if skew is None:
        return "deep_nochain"
    return "deep_fear" if skew > SK_FEAR_CUT else "deep_calm"


def _row_close(row: Dict[str, Any]) -> Optional[float]:
    for setup_key in ("deep_os_setup", "deep_os_ha_setup"):
        setup = row.get(setup_key) or {}
        close = _finite_or_none(setup.get("actual_close"))
        if close is not None:
            return close
    return None


def _row_dd10(row: Dict[str, Any]) -> float:
    hist = row.get("options_history") or {}
    return compute_dd10(hist.get("closes", []), hist.get("atr"))


def annotate_deepos_results(
    valid_results: List[Dict[str, Any]],
    *,
    target_date: str,
    fetch=fetch_chain,
    max_symbols: int = ANNOTATION_CAP,
) -> int:
    """Attach options_* fields to DeepOS-family fire rows in place.

    A failed fetch leaves the row un-annotated (fields absent). An evaluated but
    unusable chain stamps ``options_arm='deep_nochain'`` when the fire is deep.
    """
    fire_rows = [
        row for row in valid_results
        if any(row.get(key, 0) > 0 for key in SCORE_KEYS)
    ]
    symbols = sorted({row["symbol"] for row in fire_rows})
    if not symbols:
        return 0
    if len(symbols) > max_symbols:
        logger.warning(
            "options annotation: %d fire symbols exceeds cap %d - annotating first %d, "
            "dropping %d", len(symbols), max_symbols, max_symbols, len(symbols) - max_symbols,
        )
        symbols = symbols[:max_symbols]
    keep = set(symbols)

    feats_by_symbol: Dict[str, Optional[Dict[str, Any]]] = {}
    for symbol in symbols:
        row = next(r for r in fire_rows if r["symbol"] == symbol)
        try:
            chain = fetch(symbol)
            feats_by_symbol[symbol] = compute_options_features(
                chain, target_date, close=_row_close(row),
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "options annotation: fetch failed for %s (%s) - row left un-annotated",
                symbol, exc,
            )

    annotated = 0
    for row in fire_rows:
        sym = row["symbol"]
        if sym not in keep or sym not in feats_by_symbol:
            continue
        feats = feats_by_symbol[sym]
        dd10 = _row_dd10(row)
        row["options_skew"] = feats.get("skew") if feats else None
        row["options_atm_iv"] = feats.get("atm_iv") if feats else None
        row["options_dte"] = feats.get("dte_used") if feats else None
        row["options_dd10"] = _finite_or_none(dd10)
        row["options_arm"] = classify_arm(dd10, feats)
        annotated += 1
    logger.info(
        "options annotation: %d DeepOS-family rows annotated across %d symbols for %s",
        annotated, len(feats_by_symbol), target_date,
    )
    return annotated
