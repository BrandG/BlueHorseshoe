"""Read-only price-data audit for data/ohlcv.duckdb — BEFORE trusting any edge number.
Quantifies the contamination I saw (divide-by-zero, -16% means): zero/neg closes,
unadjusted-split gaps, delisting tails, and — critically — how much survives the
entry-eligibility filter via the FORWARD window (c[t+h]/c[t])."""
import numpy as np, pandas as pd, duckdb
con=duckdb.connect("data/ohlcv.duckdb",read_only=True)

print("=== schema / scope ===")
print(con.execute("DESCRIBE ohlcv").df().to_string(index=False))
tot=con.execute("SELECT count(*) n, count(DISTINCT symbol) s, min(date) lo, max(date) hi FROM ohlcv").df()
print(tot.to_string(index=False))

print("\n=== degenerate prices (whole table) ===")
q=con.execute("""SELECT
  sum(CASE WHEN close IS NULL THEN 1 ELSE 0 END) close_null,
  sum(CASE WHEN close<=0 THEN 1 ELSE 0 END) close_le0,
  sum(CASE WHEN close>0 AND close<1 THEN 1 ELSE 0 END) close_subpenny,
  sum(CASE WHEN open<=0 OR high<=0 OR low<=0 THEN 1 ELSE 0 END) ohlc_le0,
  sum(CASE WHEN high<low THEN 1 ELSE 0 END) hi_lt_lo,
  sum(CASE WHEN volume IS NULL OR volume<0 THEN 1 ELSE 0 END) vol_bad
  FROM ohlcv""").df()
print(q.to_string(index=False))

print("\n=== overnight gap blow-ups (open/prev_close), likely unadjusted splits ===")
g=con.execute("""
WITH w AS (SELECT symbol,date,open,close,volume,
             lag(close) OVER (PARTITION BY symbol ORDER BY date) pc FROM ohlcv)
SELECT
  sum(CASE WHEN pc>0 AND open/pc>1.9 THEN 1 ELSE 0 END) gap_up_2x,
  sum(CASE WHEN pc>0 AND open/pc<0.55 THEN 1 ELSE 0 END) gap_dn_half,
  sum(CASE WHEN pc>0 AND open/pc>4 THEN 1 ELSE 0 END) gap_up_4x,
  sum(CASE WHEN pc>0 AND open/pc<0.28 THEN 1 ELSE 0 END) gap_dn_quarter
FROM w""").df()
print(g.to_string(index=False))

print("\n=== worst forward-return offenders that PASS the entry filter (c in [5,500], vol20>100k) ===")
print("    these are what poison c[t+10]/c[t] even though the ENTRY bar looked clean:")
off=con.execute("""
WITH w AS (
  SELECT symbol,date,close,volume,
    avg(volume) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) v20,
    lead(close,10) OVER (PARTITION BY symbol ORDER BY date) c10
  FROM ohlcv)
SELECT symbol,date,close,c10, round(c10/close-1,2) ret10, round(v20,0) v20
FROM w
WHERE close BETWEEN 5 AND 500 AND v20>100000 AND c10 IS NOT NULL AND close>0
ORDER BY abs(c10/close-1) DESC LIMIT 15""").df()
print(off.to_string(index=False))

print("\n=== how many eligible entry bars have an EXTREME 10d forward move (|ret|>0.6) ===")
ext=con.execute("""
WITH w AS (
  SELECT symbol,date,close,volume,
    avg(volume) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) v20,
    lead(close,10) OVER (PARTITION BY symbol ORDER BY date) c10
  FROM ohlcv)
SELECT
  count(*) eligible_bars,
  sum(CASE WHEN abs(c10/close-1)>0.6 THEN 1 ELSE 0 END) extreme_fwd,
  round(100.0*sum(CASE WHEN abs(c10/close-1)>0.6 THEN 1 ELSE 0 END)/count(*),3) pct
FROM w WHERE close BETWEEN 5 AND 500 AND v20>100000 AND c10 IS NOT NULL AND close>0""").df()
print(ext.to_string(index=False))
