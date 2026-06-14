# ATR-Regime Campaign — Session Handoff (2026-06-14)

**One-line restart:** The BUD (forex/FTMO H4) edge-hunt reached its **first deploy candidate** — a
volatility-regime sizing conditioner. Everything through **P3 is committed on `master`
(`c18e7a2`)**. The next action is **P4 (FTMO-constrained sim)** — the last research gate before a
production-wiring decision. The full P4 contract is embedded in §5 below (and in `/tmp/nextaction.md`).

---

## 1. The campaign arc (compressed)

Hunting a tradeable edge for BUD on H4 forex. Three doors tried, in order:

| Door | Verdict | Doc |
|---|---|---|
| **Confluence** (combine 2 signals) | DEAD — controls beat candidates 7:1; no independent edge to combine | `docs/planning/CONFLUENCE_SWEEP_v1.md` |
| **Dislocation-depth** (deeper = better, equity transfer) | DEAD — 0/12; equity deep-oversold doesn't transfer to forex | `docs/planning/DISLOCATION_DEPTH_v1.md` |
| **Volatility-regime** (MR works in calm vol) | **SURVIVED → deploy candidate** | `docs/planning/ATR_REGIME_v1.md` (§13–§16) |

Each door's null was a *constructive* close: confluence's `bb+ema` tick-up → depth; depth's
ATR-stratification → vol-regime. The vol-regime thread is the live one.

**Method laws reinforced (apply these to P4+):** judge at the **book/sleeve level under Newey-West**,
not per-cell (the v2 NW lesson: per-cell collapses, the book survives); **audit the harness before
accepting an agent's verdict** — this session overruled false-negative gates in P1/P1b, tempered a
too-rosy "corroborated" in P2b, and agreed with P3. Argue from significance, not point estimates.

## 2. The deploy candidate (the result)

**`size_down_high_0_5`** — on the **causal/PIT w252 rolling ATR percentile** (per-pair, 252-bar),
size MR entries: **low 1.0× / mid 1.0× / high 0.5×** (half-size when the pair's vol is in its top
third relative to its own recent ~6 weeks).

Strong-4 long MR book (bb/rsi/ema/stoch, deduped one trade per pair-bar): **return/DD 1.74→2.37
(+36%), maxDD −21%, throughput-neutral (0% — it down-sizes, doesn't skip), stable in both halves.**
Alpha arbiter (vs same conditioner on a random-entry book): **return/return-DD gain = MR cell-alpha**
(down-sizing hurts a random book, helps MR); **DD reduction = generic vol-beta**. Both deployable.

**Caveats to carry forward:** (1) the return-alpha is **strong-4-specific** (full-6 adds only +4.6R →
mostly DD control on the broad book); (2) P3 is **R-space, not FTMO-constrained**; (3) `hard_gate`
(skip high) has better risk numbers (return/DD 2.87, maxDD 459) at **−36% throughput** — a real
deploy choice vs the throughput-neutral `size_down`.

## 3. Current git state

- `master` = `origin/master` = **`c18e7a2`** ("Merge branch 'codex/atr-regime-p3'"). Clean tree.
- All ATR-regime research is under `research/atr_regime_v1/` + `docs/planning/ATR_REGIME_v1.md`.
- **No dangling branches or worktrees** from this campaign. Parked worktrees `deepos-fill-anchored`
  and `solvency-deepos` are **unrelated** (other threads) — leave them.

## 4. Reusable harness (reuse, don't rebuild)

- `research/atr_regime_v1/atr_regime_{p1b,p2,p2b,p3}.py` — sleeve construction, w252 regime
  bucketing, all-bars baseline, NW + date-cluster SE, book sim, sizing forms.
- `research/dislocation_depth_v1/depth_fires.csv` — **154k fires** with `pair,evaluator,direction,
  entry_mode,ts,raw_depth,atr_norm_depth,entry_ATR,ATR_percentile` (the trade universe + regime).
- `research/dislocation_depth_v1/depth_extract.py`, `research/confluence_v1/{factor_grouping,co_fire}.py`
  — `DIR_MASKERS`, `choose_params`, `deployed_cells` (faithful to production `_EVALUATORS`).
- `research/v2_executable_regate/harness/_lib.py` — `sim_{long,short}_{mid,limit}`, 1%/1% R.
- `research/v2_executable_regate/seed/nw_regate.py` — Newey-West.
- **For P4:** `src/bh_ftmo/backtest/ftmo_rules.py` — `load_ftmo_config`, `FtmoRuleEngine`,
  `ChallengeState` (real daily-loss/max-loss/target/trading-day enforcement).

## 5. IMMEDIATE NEXT — kick off P4 (FTMO-constrained sim)

**Why:** P3's win is R-space; P4 tests whether it survives the hard FTMO constraints (daily-loss /
max-loss limits, position/slot cap, slot redeployment of freed capacity). FTMO-native metric =
**challenge pass-rate** (hit target before breaching, within day limit), not total R.

**Cadence (plan A):** branch `codex/atr-regime-p4` from `master` → worktree → symlinks → trust →
launch → poll → audit → commit (Bubo) → merge `--no-ff` → push → teardown. See §6 for the recipe.

**The P4 contract is ready in `/tmp/nextaction.md`** (and regenerable from here). Its spine:
- Reuse `FtmoRuleEngine` + the **verified** FTMO config (the bh_ftmo backtester already loads one) —
  **hard-stop if the config is placeholder (`FtmoConfigUnverifiedError`); never hand-type limits.**
- $10k Swing account, base risk + max-concurrent-positions/slot cap from the deployed v2 config
  (`bh_ftmo_config.json` / v2_paper) — read & document them.
- Three books: **unconditioned**, **`size_down_high_0_5`**, **`hard_gate_skip_high`**.
- **Headline = rolling-window challenge pass-rate** per book + max-loss/daily breach counts.
- **Slot/redeployment:** with the cap binding, does down-sizing high-ATR free capacity low/mid trades
  fill? (the thing P3 couldn't see.)
- Verdict: clear pass-rate / DD-breach improvement → **deploy-recommend** the schedule; no
  improvement once constrained → R-space benefit doesn't survive, say so.

## 6. How to run a Codex phase (the repeatable recipe)

1. `git branch codex/<name> master` (no checkout); `git worktree add /root/worktrees/<name> codex/<name>`.
2. Symlink into the worktree: `.venv`, `.env`, `data/fx_4h.duckdb` → `/root/BlueHorseshoe/*`
   (FxStore derives its path from REPO_ROOT, so the db symlink is required).
3. Trust the worktree path in `~/.codex/config.toml`:
   `[projects."/root/worktrees/<name>"]\n trust_level = "trusted"`.
4. Write the contract to `/tmp/nextaction.md` (AGENTS.md protocol format: Objective/Allowed/
   Forbidden/Steps/Validation/Report). **Codex CANNOT git-commit** (sandbox can't write the worktree
   index under main `.git/worktrees/`) — tell it to leave deliverables uncommitted; **Bubo commits**.
5. Launch detached: `tmux new-session -d -s codex-<name> "cd <wt> && codex exec -s workspace-write
   -C <wt> - < /tmp/nextaction.md 2>&1 | tee /tmp/codex-<name>.log; ..."`.
6. Poll the log / deliverables. **Audit the result skeptically** (don't relay Codex's framing — see
   §1 method laws). Then Bubo commits, `git merge --no-ff` → `git push`, `git worktree remove
   --force` + `git branch -d`.
- **Process safety:** `pgrep -f "main.py"` — if a `-u/-p` pipeline runs, wait; **else proceed**. The
  blackout is **Tue–Sat 01:00 only** (`run_daily_pipeline.sh`); Sun/Mon are clear. **Do NOT** put
  "wait 00:30–03:30" in a contract without the day caveat — Codex once parked ~2.5h on a Sunday.

## 7. Pending decisions / fences

- **P4 verdict → deploy / don't.** If it survives FTMO constraints, the next step is the production
  wiring — a **w252 vol-regime sizing multiplier in the v2 sizing path (`bud/`)**. That's a
  **production change, explicitly approval-gated by Brand + needs validation** — NOT an auto-proceed.
- If P4 shows the R-space win doesn't survive constraints → the vol-regime thread closes as a
  risk-control footnote; the orthogonal unopened door is **relative-value / cointegration** (door #2,
  untouched all campaign).

## 8. Memory pointers

- `project_confluence_closed_dislocation_depth.md` — the full campaign rollup (confluence→depth→
  vol-regime, P1…P3, the deploy candidate). MEMORY.md index line points to it.
- `project_pipeline_oom_concurrent_claude.md` — updated with the **day-gated blackout** (Tue–Sat
  01:00) + pgrep-gate guidance.
- Reference the v2/NW method memories: `project_v2_methodology`, `project_deoverlap_signflip_newey_west`.
