# Session Handoff

**Date:** March 4, 2026
**Status:** Regime-adaptive weight experiment complete. V3 remains production. No active research droplets.

---

## What Was Done This Session (March 4)

1. **Built regime-adaptive weight selection infrastructure** (`f3ac5d7`)
   - Exposed raw regime score (0-10) in `market_regime.get_market_health()`
   - Added `ConfigManager.load_regime_weights()` and `select_weights_for_regime(score)` to `config.py`
   - Created `weights_v2_full.json` (V2 baseline + production MR categories, 13 categories)
   - Added `--version adaptive` to `run_clean_backtest.py` (per-date V2/V3 switching)
   - Added 12 tests in `test_regime_weights.py` (all passing, 193/193 total)

2. **Ran live adaptive backtest on research droplet** (30 dates, ~19 hours)
   - Paper simulation predicted +138.6% theoretical ceiling
   - Live result: **+83.6%** — essentially tied with V3 (+84.0%)
   - Paper simulation was inflated because V2 reference CSV used higher TOP_N (~15 vs 10)

3. **Conclusion: regime switching adds no value** — reverted `strategy.py` integration
   - Production `swing_predict()` does NOT do regime weight switching
   - Infrastructure remains for future research (`config.py` methods, `--version adaptive`)

4. **Research droplet created and destroyed** (555784220, s-4vcpu-8gb, ~19 hours)

### Adaptive vs V3 Results (30 stratified dates, TOP_N=10)

| Metric | V3 | Adaptive |
|--------|----|----------|
| Trades | 264 | 272 |
| Win Rate | 61.4% | 62.1% |
| Avg P&L | +0.32% | +0.31% |
| Total P&L | **+84.0%** | +83.6% |

**Key insight:** V2's apparent per-regime advantage was driven by taking more positions (avg 14.5/date vs 10), not better weight selection. When normalized to TOP_N=10, V3 matches or beats V2 across all regimes.

---

## Previous Session (March 3, Session 2)

1. **V3.1 backtest completed** — 30/30 dates, V3 won decisively
2. **Deployed V3 weights to production** (`568b4ae`)
3. **Deleted `weights_v31.json`** — lost the comparison

### Three-Way Results (30 stratified dates)

| Metric | V2 | V3 | V3.1 |
|--------|----|----|------|
| Trades | 434 | 264 | 269 |
| Win Rate | 59.9% | **61.4%** | 59.1% |
| Avg P&L | +0.16% | **+0.32%** | +0.30% |
| Total P&L | +71.3% | **+84.0%** | +79.8% |

---

## Weight Optimization — COMPLETE

**V2 (original hand-tuned):** `src/weights_v2.json` — reference only
**V2-full (V2 baseline + prod MR):** `src/weights_v2_full.json` — research only
**V3 (data-driven, DEPLOYED):** `src/weights_v3.json` — also in `src/weights.json`
**V3.1 (V3 + ADX + AD_LINE):** Deleted — did not improve over V3

Backtest CSVs: `src/logs/clean_backtest_v2.csv`, `clean_backtest_v3.csv`, `clean_backtest_v31.csv`, `clean_backtest_adaptive.csv`

---

## Next Steps

- Monitor production results with V3 weights over coming weeks
- See `TO-DO.md` for full backlog

---

## Key Decisions

- **V3 weights deployed** — zeroed out Donchian, SuperTrend, TTM Squeeze, Aroon, Keltner, VWAP from baseline
- **Regime-adaptive switching rejected** — no uplift over V3 when using identical TOP_N
- **Container limits**: 6GB RAM / 3 CPUs. Production prediction completes in ~50 min
- **`-u` now active-only by default** — use `--all` flag to update all symbols
- **`-p` now filters by market cap** — skips ETFs/warrants/SPACs/shells automatically
- **Research droplet destroyed** — no active droplets

---

## Infrastructure

### Research Droplet
- **Status:** DESTROYED (March 4, 2026)
*************** DO NOT EDIT THE FOLLOWING SECTION WHEN UPDATING SESSION_HANDOFF.md
**IMPORTANT:** All SSH commands to the research droplet MUST `cd /root/BlueHorseshoe` first.
The default login directory is `/root`, NOT the repo directory.

**Workaround for Claude Code:** Write remote commands to `/tmp/remote_cmd.sh` and pipe via `ssh root@10.132.0.4 bash < /tmp/remote_cmd.sh` — this reliably includes the `cd`.

```bash
ssh root@10.132.0.4
# All commands must run from /root/BlueHorseshoe
# Direct SSH (for humans):
ssh root@10.132.0.4 "cd /root/BlueHorseshoe && docker exec bh-research python src/run_clean_backtest.py --version v3"
# Copy results:
scp root@10.132.0.4:/root/BlueHorseshoe/src/logs/clean_backtest_v3.csv src/logs/
# Destroy when done:
doctl compute droplet delete bh-research --force
```
*************** END OF IMMUTABLE SECTION

**Droplet cost:** s-4vcpu-8gb = $0.067/hr (~$0.80 for 12 hours)

### Production
```bash
docker exec bluehorseshoe python src/main.py -p        # Prediction (~50 min)
docker exec bluehorseshoe python src/main.py -u        # Data update (active-only default)
docker exec bluehorseshoe python src/main.py -u --all  # Data update (all symbols)
docker exec bluehorseshoe pytest -v                    # Tests
docker exec bluehorseshoe ./lint.sh                    # Lint
```

**Cron pipeline:** Runs at 02:00 UTC (Mon-Sat)

---

## Git Status

**Branch:** master
**Latest pushed commit:** `f3ac5d7` — feat: Add regime-adaptive weight selection infrastructure

---

**Last Updated:** March 4, 2026
