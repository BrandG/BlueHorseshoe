# Session Handoff

**Date:** February 28, 2026
**Status:** Stratified test dates built (30 dates). Backtest scripts updated to use them. V2 backtest running on research droplet. Old V2/V3 results (partial, 8/18 dates) cleared.

---

## What Was Done This Session

### 1. Verified Stratified Test Dates (complete)

`src/test_dates.json` was generated last session and confirmed valid this session:
- 30 dates across 5 regime buckets (6 per bucket)
- Date range: 2024-06-04 through 2026-02-18
- Scores use SPY/QQQ EMAs + 19-stock breadth (0-10 scale)
- Minimum 5 calendar-day gap between selected dates
- Builder script: `src/build_test_dates.py`

| Bucket | Score Range | Example Dates |
|--------|------------|---------------|
| Strong Bull | 9-10 | 2024-06-04, 2024-12-02, 2025-07-30 |
| Mild Bull | 7-8 | 2024-07-19, 2025-02-21, 2025-12-05 |
| Neutral | 5-6 | 2024-09-09, 2025-05-01, 2026-02-04 |
| Mild Bear | 3-4 | 2024-08-08, 2025-03-24, 2026-02-18 |
| Strong Bear | 0-2 | 2025-03-18, 2025-04-02, 2025-04-14 |

### 2. Confirmed Backtest Scripts Already Updated (last session, uncommitted)

Both `run_clean_backtest.py` and `compare_clean_backtests.py` were updated last session to load dates from `test_dates.json` instead of hardcoded lists. These changes are **local only — not committed to git**.

### 3. Cleared Old Partial Results

Deleted old `clean_backtest_v2.csv` and `clean_backtest_v3.csv` on the research droplet (they used the old 8/18-date sets and are not comparable to the new 30-date runs).

### 4. Kicked Off V2 Backtest on Research Droplet

V2 backtest running over all 30 stratified dates on `bh-research` (s-4vcpu-8gb, ~$0.07/hr).

**Note:** The updated scripts (`run_clean_backtest.py`, `compare_clean_backtests.py`, `build_test_dates.py`, `test_dates.json`) were SCP'd to the droplet since they aren't committed to git yet. Future `git pull` on the droplet will overwrite them with old versions unless committed first.

---

## What Was Done Last Session (for reference)

- Added 5 dedicated mean-reversion indicators (RSI Divergence, Z-Score, Connors RSI, DV2, Short-Period ROC)
- Fixed report strategy balance (top 25 per strategy instead of combined top 50)
- Ran V3 backtest over 18 dates (old set): 52.2% win rate, -3.80% total P&L
- Backfilled SPY + QQQ to 2000 (6621 days each)
- Built stratified test date builder script

---

## In Progress

### V2 Backtest (running on bh-research)
```bash
# Check progress (use script-file workaround for cd):
echo 'cd /root/BlueHorseshoe && tail -20 src/logs/clean_backtest_v2.csv' > /tmp/remote_cmd.sh
ssh root@10.132.0.4 bash < /tmp/remote_cmd.sh
```

### After V2 completes:
1. Copy results: `scp root@10.132.0.4:/root/BlueHorseshoe/src/logs/clean_backtest_v2.csv src/logs/`
2. Clear V2 CSV on droplet, kick off V3 backtest over the same 30 dates
3. Copy V3 results when done

---

## V2/V3/V3.1 Status

**V2 (original hand-tuned weights):**
- Clean backtest: RUNNING on research droplet (30 stratified dates)
- Weights: `src/weights_v2.json`

**V3 (data-driven weights + new MR indicators):**
- Clean backtest: NEEDS RE-RUN over 30 stratified dates (old 18-date results deleted)
- Weights: `src/weights_v3.json`

**V3.1 (restore key indicators):**
- NOT STARTED — depends on leave-one-in analysis
- Leave-one-in script ready: `src/analyze_indicator_impact.py`

**Current `weights.json`** has new `mean_reversion_specific` and `mr_mean_reversion_specific` categories.

---

## Next Steps

1. ~~Finish test date builder~~ — done, 30 dates verified
2. ~~Update backtest scripts to use test_dates.json~~ — done (uncommitted)
3. **Re-run V2 backtest** over 30 stratified dates — IN PROGRESS
4. **Re-run V3 backtest** over 30 stratified dates — queued after V2
5. **Run leave-one-in analysis** to identify which zeroed indicators to restore for V3.1
6. **Build V3.1 weights** and backtest over same 30 dates
7. **Three-way comparison** (V2 vs V3 vs V3.1)
8. **Commit** updated scripts and test_dates.json to git

---

## Key Decisions

- **5 regime buckets** (Strong Bull / Mild Bull / Neutral / Mild Bear / Strong Bear) with 6 dates each = 30 total
- **SPY + QQQ + breadth** for regime classification (same logic as MarketRegime class)
- **Per-strategy top-25** instead of combined top-50 to guarantee both strategies in reports
- **MR indicator weights** conservative starting values, baseline all 0.0 to avoid contamination

---

## Infrastructure

### Research Droplet
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

**Droplet cost:** s-4vcpu-8gb = $0.067/hr (~$0.80 for 12 hours)

### Production
```bash
docker exec bluehorseshoe python src/main.py -p        # Prediction
docker exec bluehorseshoe python src/main.py -u        # Data update
docker exec bluehorseshoe pytest -v                    # Tests (223 pass, 2 pre-existing failures)
docker exec bluehorseshoe ./lint.sh                    # Lint (clean)
```

---

## Git Status

**Branch:** master
**Latest pushed commit:** `e017c4b` — feat: Add 5 dedicated mean-reversion indicators and fix report strategy balance
**Uncommitted changes:**
- `SESSION_HANDOFF.md` — modified
- `TO-DO.md` — modified
- `src/run_clean_backtest.py` — modified (loads from test_dates.json)
- `src/compare_clean_backtests.py` — modified (loads from test_dates.json)
- `src/build_test_dates.py` — untracked (new)
- `src/test_dates.json` — untracked (new)

---

**Last Updated:** February 28, 2026
