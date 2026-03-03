# Session Handoff

**Date:** March 3, 2026
**Status:** Weight optimization complete. V3 deployed to production. Research droplet destroyed. All clear.

---

## What Was Done This Session (March 3, Session 2)

1. **V3.1 backtest completed** — 30/30 dates, results copied locally
2. **Three-way comparison** (V2 vs V3 vs V3.1) — V3 won decisively
3. **Deployed V3 weights to production** (`568b4ae`)
4. **Destroyed research droplet** — no longer needed
5. **Deleted `weights_v31.json`** — V3.1 lost the comparison, file removed

### Three-Way Results (30 stratified dates)

| Metric | V2 | V3 | V3.1 |
|--------|----|----|------|
| Trades | 434 | 264 | 269 |
| Win Rate | 59.9% | **61.4%** | 59.1% |
| Avg P&L | +0.16% | **+0.32%** | +0.30% |
| Total P&L | +71.3% | **+84.0%** | +79.8% |
| Profit Factor | 1.19 | 1.40 | 1.40 |
| Avg/StdDev | 0.070 | 0.130 | 0.131 |
| Avg Loss | -2.15% | -2.04% | **-1.83%** |
| Profitable Days | **21/30** | 19/30 | 19/30 |
| H2H (3-way) | **13** | 10 | 7 |

**V3 vs V3.1:** V3 won 17/30 days. V3.1's ADX+AD_LINE restoration added noise — worst in strong bull regime (-30.7% vs V3's -12.6%).

### Per-Regime Summary

| Regime | V2 P&L | V3 P&L | V3.1 P&L | Best |
|--------|--------|--------|----------|------|
| Strong Bear | -68.5% | **-13.3%** | -17.8% | V3 |
| Mild Bear | **+41.5%** | +18.3% | +38.5% | V2 |
| Neutral | **+71.4%** | +66.2% | +70.7% | V2 |
| Mild Bull | **+51.6%** | +25.3% | +19.0% | V2 |
| Strong Bull | -24.7% | **-12.6%** | -30.7% | V3 |

**Key insight:** V3's edge is damage control in extreme regimes. V2 captures more upside in favorable conditions but gives it all back in bear markets.

---

## What Was Done March 3 (Session 1)

1. **Connors RSI(2) badge** — Flags mean reversion candidates matching Connors setup (RSI(2)<10, price>SMA200) with a gold star in the HTML report
2. **Market-cap pre-filter for `-p`** — Skips ~1,012 symbols without market cap data (ETFs, warrants, SPACs, shells) that never produce scores
3. **Active-only default for `-u`** — Now active-only by default (use `--all` to override), skipping ~4,800 inactive symbols during data updates

---

## What Was Done March 2

1. **Completed V2 backtest** — 30/30 dates
2. **Completed V3 backtest** — 30/30 dates
3. **Full V2 vs V3 comparison**
4. **Leave-one-in analysis** — ADX (+3.24) and AD_LINE (+2.64) identified
5. **Built V3.1 weights** and kicked off backtest on research droplet

---

## Weight Optimization — COMPLETE

**V2 (original hand-tuned):** `src/weights_v2.json` — reference only
**V3 (data-driven, DEPLOYED):** `src/weights_v3.json` — also in `src/weights.json`
**V3.1 (V3 + ADX + AD_LINE):** Deleted — did not improve over V3

Backtest CSVs: `src/logs/clean_backtest_v2.csv`, `clean_backtest_v3.csv`, `clean_backtest_v31.csv`

---

## Next Steps

- **2 pre-existing test failures** to investigate (`test_loo_analyzer`, `test_split_exit`) — not caused by weight change
- Consider whether V2's mild bear/neutral/mild bull advantage warrants a regime-adaptive weight system
- Monitor production results with V3 weights over coming weeks
- See `TO-DO.md` for full backlog

---

## Key Decisions

- **V3 weights deployed** — zeroed out Donchian, SuperTrend, TTM Squeeze, Aroon, Keltner, VWAP from baseline
- **Container limits**: 6GB RAM / 3 CPUs. Production prediction completes in ~50 min
- **`-u` now active-only by default** — use `--all` flag to update all symbols
- **`-p` now filters by market cap** — skips ETFs/warrants/SPACs/shells automatically
- **Research droplet destroyed** — no active droplets

---

## Infrastructure

### Research Droplet
- **Status:** DESTROYED (March 3, 2026)
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
**Latest pushed commit:** `568b4ae` — feat: Deploy V3 data-driven weights to production
**Uncommitted:** `SESSION_HANDOFF.md`, `TO-DO.md`, `src/analyze_indicator_impact.py` (symbol source fix)

---

**Last Updated:** March 3, 2026
