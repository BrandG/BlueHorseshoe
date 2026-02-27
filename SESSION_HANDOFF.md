# Session Handoff

**Date:** February 26, 2026
**Status:** Leave-One-In analysis script written and ready but NOT yet run. Prediction for 2026-02-25 needs to be re-run (was killed by OOM from concurrent analysis attempts).

---

## What Was Done This Session

### 1. Leave-One-In Indicator Restoration Analysis Script
Created `src/analyze_indicator_impact.py` — a two-pass analysis script to identify which of 11 zeroed-out V3 indicators should be restored for a "V3.1" build.

**Context:** V3 data-driven weights zeroed 11 indicators and underperformed V2 (-64% vs +6% total P&L over 18 weeks). Root cause: V3 picks higher-volatility stocks with wider ATR-based stop-losses (~2x wider than V2).

**How it works:**
- **Pass 1:** Scores all ~4400 symbols with V2 + V3 base weights, keeps top 200 per date
- **Pass 2:** Re-scores those ~200 with 12 indicator-restoration variants (V3 + one zeroed indicator restored at its V2 weight)
- **3 representative dates:** 2025-11-12 (bad V3), 2025-11-19 (good V3), 2025-12-10 (average)
- **Metrics:** Score spread, V2 top-10 overlap, ATR/price ratio of picks, composite impact ranking
- **Key technique:** Patches `weights_config._weights` in-memory between runs (no file I/O)

### 2. CLAUDE.md Container Process Safety Rule
Added rule: **never run concurrent heavy processes alongside `-u` or `-p`**. Multiple OOM kills from concurrent analysis + prediction taught this lesson.

### 3. Diagnosed Prediction Failure
The 2026-02-25 prediction (`-p`) was killed mid-run (only scored through early A-symbols) by OOM from concurrent analysis scripts. No report was generated.

---

## In Progress

### Prediction Re-run Needed
The `-p` prediction for 2026-02-25 did NOT complete. Must re-run:
```bash
docker exec bluehorseshoe python src/main.py -p
```
**Wait for it to finish before running any analysis scripts.**

### Leave-One-In Analysis NOT YET RUN
Script is ready but was never successfully completed due to repeated OOM issues. Run after prediction completes:
```bash
docker exec -e PYTHONUNBUFFERED=1 bluehorseshoe python src/analyze_indicator_impact.py
```
**Estimated runtime:** ~30-45 min on clean container (two-pass design stays under 4GB).

---

## Next Steps

1. **Re-run prediction** — `docker exec bluehorseshoe python src/main.py -p` (wait for completion)
2. **Run leave-one-in analysis** — `docker exec -e PYTHONUNBUFFERED=1 bluehorseshoe python src/analyze_indicator_impact.py`
3. **Interpret results** — Identify which indicators to restore for V3.1
4. **Build V3.1 weights** — Update `weights.json` with restored indicators
5. **Backtest V3.1** — Compare against V2 and V3 baseline
6. **Commit changes** — All V3/V3.1 work is still uncommitted

---

## Key Decisions

- **Two-pass design for memory safety:** Full universe scoring (4400+ symbols) with all 14 variants simultaneously OOMs the 4GB container. Solution: Pass 1 narrows to top 200 candidates, Pass 2 does variant comparison on that subset only.
- **Direct MongoDB access:** Script queries `historical_prices_recent` collection directly (bypasses `load_historical_data()` overhead). Each symbol loaded individually and discarded after scoring.
- **Container safety rule:** Added to CLAUDE.md — never run analysis concurrently with `-u` or `-p`. The container only has 4GB.

---

## Key Technical Details

### OOM History This Session
- 4 analysis runs OOM-killed before landing on two-pass design
- Root cause: holding 4400+ enriched DataFrames in memory OR running concurrent with `-p` workers
- Container memory limit: 4GB (`docker inspect --format '{{.HostConfig.Memory}}'`)

### Weight Patching Approach
```python
from bluehorseshoe.core.config import weights_config
weights_config._weights = new_weights_dict  # No file I/O, instant
```

### Profiling Results (100-symbol sample)
- DB loading: 38ms/symbol
- Technical indicators: 64ms/symbol
- Scoring: 147ms/symbol
- Per-symbol GC: doubles total time — removed from per-symbol loop

---

## Uncommitted Changes

All prior session changes still uncommitted, plus:
- `SESSION_HANDOFF.md` — this file
- `CLAUDE.md` — added Container Process Safety section
- `src/analyze_indicator_impact.py` — NEW, leave-one-in analysis script
- `src/bluehorseshoe/analysis/indicator_impact.py` — existing indicator impact analyzer (from prior work)
- All V3 weight system changes from prior session (see prior handoff for full list)

---

## Git Status

**Branch:** master
**Latest pushed commit:** `358ec2e` - feat: Replace Alpha Vantage with Tiingo API and add concurrent fetching
**Tests:** Not verified this session (no code changes to production files)

---

## Quick Commands

```bash
# Check container processes (ALWAYS do this before running anything heavy)
docker top bluehorseshoe

# Re-run prediction (DO THIS FIRST)
docker exec bluehorseshoe python src/main.py -p

# Run leave-one-in analysis (ONLY after prediction completes)
docker exec -e PYTHONUNBUFFERED=1 bluehorseshoe python src/analyze_indicator_impact.py

# Standard commands
docker exec bluehorseshoe pytest -v
docker exec bluehorseshoe ./lint.sh
```

---

**Last Updated:** February 26, 2026
