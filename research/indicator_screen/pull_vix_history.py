"""
pull_vix_history.py — one-time full VIX history pull for the VIX×DeepOS condition test (spec B).

Source : CBOE full daily history CSV (free, no key, back to 1990).
         https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv
Output : data/vix_history.parquet  (date-indexed daily OHLC + close)

The DeepOS research window is 2011-2026; this source covers 1990+ so coverage is ample.
Downstream (deepos_vix_condition.py) builds vix_asof(date) with "most recent on or
before" semantics — the same rule get_vix_snapshot uses — plus 20d-SMA / 90d-percentile
derivations as needed. We store raw OHLC here and compute derived metrics at use time.
"""
import io
import sys
from pathlib import Path

import pandas as pd
import requests

from bluehorseshoe.core.config import REPO_ROOT

CBOE_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
OUT = Path(REPO_ROOT) / "data" / "vix_history.parquet"

# Known VIX spikes for a sanity check (date, approx close floor we expect to clear).
SPIKE_CHECKS = [
    ("2008-10-24", 79.0),   # GFC
    ("2018-02-05", 37.0),   # Volmageddon
    ("2020-03-16", 82.0),   # COVID crash (record close ~82.69)
    ("2022-06-13", 34.0),   # 2022 bear
]


def main() -> int:
    resp = requests.get(CBOE_URL, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.BytesIO(resp.content))
    df.columns = [c.strip().lower() for c in df.columns]  # DATE,OPEN,HIGH,LOW,CLOSE
    df["date"] = pd.to_datetime(df["date"], format="%m/%d/%Y")
    df = df.sort_values("date").reset_index(drop=True)
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["close"])
    print(f"rows={len(df)}  range={df['date'].min().date()} -> {df['date'].max().date()}")

    # Sanity: known spikes must be present and clear their expected floor.
    idx = df.set_index("date")["close"]
    ok = True
    for d, floor in SPIKE_CHECKS:
        ts = pd.Timestamp(d)
        # nearest trading day on or before
        sub = idx[idx.index <= ts]
        val = sub.iloc[-1] if len(sub) else float("nan")
        flag = "OK" if (val >= floor) else "FAIL"
        if val < floor:
            ok = False
        print(f"  spike {d}: close={val:.2f} (expect >= {floor})  {flag}")

    if not ok:
        print("SANITY CHECK FAILED — not writing parquet.", file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df[["date", "open", "high", "low", "close"]].to_parquet(OUT, index=False)
    print(f"wrote {OUT}  ({len(df)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
