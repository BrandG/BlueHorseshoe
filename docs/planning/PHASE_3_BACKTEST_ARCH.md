# Phase 3 — Backtest Architecture

**Status:** Drafted 2026-04-24 → revised 2026-04-25 after `/plan-eng-review` (10 decisions locked).
**Owner:** Brand
**Authority hierarchy:** `BH_FTMO_PLAN.md` (locked phase decisions) → `FTMO_RULES.md` (rule spec) → this doc (Phase 3 detail). Conflicts resolve up the chain.

---

## 1. Purpose

Phase 3 of BH FTMO ships the backtest framework that gates everything downstream:

- It measures whether the locked Baseline + MeanReversion strategies have edge over three null baselines (decision 17B).
- It enforces the strict entry-edge gate (decision 16A) that determines whether Phase 4 (edge-exits) is worth building at all.
- It is the substrate that Phase 2c (indicator tuning) and Phase 4 (exit scoring) both run on top of — every walk-forward optimization in BH FTMO routes through this engine.

If this engine is wrong, every downstream conclusion is wrong. Faithfulness to FTMO_RULES.md and bid/ask economics is non-negotiable.

## 2. Scope (in/out)

**In scope for Phase 3:**

- Bid/ask-aware fill simulator on the 4h bar grid with 1h-path intrabar resolution
- **Portfolio-level event ordering** across all open positions (account-wide breach faithfulness)
- FTMO rule enforcement per `FTMO_RULES.md` §3–§6 (daily loss, max DD, profit target, min/max trading days, CE(S)T resets, Wed-triple swap, commission)
- Walk-forward fold harness: 18mo IS / 6mo OOS / 6mo roll (decision 8) — for OOS evaluation only in Phase 3; grid-search optimizer deferred to Phase 2c
- Three reference baselines: random-entry+ATR, Mon-in/Fri-out, RSI(14) (decision 17B)
- Risk exits (locked decision 14): weekend-flatten + deadline-awareness ship in Phase 3
- Calendar-provider Protocol stub (Phase 5 seam)
- Metrics: Sharpe, Sortino, profit factor, win rate, max DD, R-expectancy, FTMO pass-rate with bootstrap CI
- Reporter: HTML + CSV with per-cluster, per-session, per-strategy breakdowns
- Entry-edge gate evaluator (decision 16A): Sharpe ≥ 1.0, PF ≥ 1.3, WR ≥ 45%, MaxDD ≤ 10%, **AND beats best baseline pass-rate by ≥ 10pp**, FTMO pass-rate lower-CI ≥ 70%

**Out of scope for Phase 3 (deferred):**

- Walk-forward grid-search **optimizer** (deferred to Phase 2c — see decision P3-9)
- Edge-exit scoring (Phase 4, gated on Phase 3 passing)
- Real economic-calendar feed (Phase 5; Phase 3 ships `NullCalendarProvider`)
- ML-based exit logic (Phase 4 stretch)
- Live execution (post-cutover)
- Equity-side walk-forward backport (decision 9A)

## 3. Package Layout

```
src/bh_ftmo/backtest/
├── __init__.py
├── types.py            # Trade, Position, FillEvent, RuleBreach, ChallengeResult, ExitEvent
├── pip_value.py        # FX pip mechanics + quote-currency conversion (§6.7)
├── trade_factory.py    # Signal → entry/stop/target/lots derivation
├── intrabar.py         # 1h-path event extraction per position
├── event_queue.py      # Portfolio-level chronological event applier (Codex #1)
├── position.py         # Open-position bookkeeping
├── equity.py           # Mark-to-market equity tracker (uses bid/ask), pinned sampling basis
├── swap.py             # Per-instrument swap rate provider (OANDA financing), Wed triple
├── commission.py       # Per-lot round-turn charge — half-at-open / half-at-close
├── calendar_provider.py # Protocol + NullCalendarProvider (Phase 5 seam)
├── risk_exits.py       # Weekend flatten + deadline awareness (decision 14)
├── ftmo_rules.py       # Daily loss / max DD (static OR trailing) / profit target / min&max trading days
├── engine.py           # Main simulator: bars + signals → ledger + equity curve (process-safe)
├── walk_forward.py     # IS/OOS window splitter (decision 8)
├── metrics.py          # Sharpe, Sortino, PF, WR, MaxDD, R-expectancy, FTMO pass-rate w/ bootstrap CI
├── baselines.py        # random-entry+ATR, Mon/Fri, RSI(14) (decision 17B)
├── gate.py             # Entry-edge gate evaluator (decision 16A + baseline-relative)
└── reporter.py         # HTML + CSV output (per-cluster, per-session, per-strategy)
```

**External dependencies:**
- `src/bh_ftmo/data/fx_store.py` — bid/ask 4h + 1h bars
- `src/bh_ftmo/data/fx_time_utils.py` — DST-aware CE(S)T reset boundaries (`ftmo_day_boundary`), holiday calendars, `prior_forex_day` for fold edge snapping (Codex A1, #12)

Tests mirror under `src/tests/bh_ftmo/backtest/`.

## 4. Data Flow

```
Phase 2b output: cluster-filtered Signal list
              │
              ▼
     trade_factory.derive() ── Signal + ATR(14) + pip_value → Position(entry, stop, target, lots)
              │
              ▼
   ┌────── engine.run_challenge() loop over 4h bars ───────────────────┐
   │                                                                   │
   │  for bar in bars:                                                 │
   │    1. ftmo_rules.session_reset_if_due()                           │  ← uses fx_time_utils.ftmo_day_boundary
   │    2. swap.apply_if_rollover()                                    │  ← Wed triple per FTMO_RULES §5.2
   │       (note: swap applied BEFORE reset baseline computed for the  │
   │        new day — new day's daily-loss anchor is post-swap equity. │
   │        Codex #8 explicit ordering)                                │
   │    3. risk_exits.weekend_flatten_if_due()                         │  ← decision 14
   │       risk_exits.deadline_check()                                 │
   │    4. for pos in open:                                            │
   │         events.extend(intrabar.extract_events(pos, bar, 1h_bars)) │  ← per-position events
   │    5. event_queue.sort_chronologically(events)                    │  ← Codex #1: portfolio order
   │    6. for ev in events:                                           │
   │         apply_event(ev)                                           │  ← updates positions + cash
   │         equity.update(ts=ev.ts, bid_at, ask_at)                   │
   │         breach = ftmo_rules.check_intrabar(equity, ts)            │
   │         if breach: halt_challenge(); break                        │
   │    7. equity.mark_to_market(bar.close, bid, ask)                  │  ← bar-close sample
   │    8. trade_factory.open_new(signals_at_bar)                      │  ← if rules permit, capacity allows,
   │                                                                       1h data available, calendar allows
   └───────────────────────────────────────────────────────────────────┘
              │
              ▼
   Trade ledger + equity curve + ChallengeResult
              │
              ▼
   metrics.summarize() → reporter.render() → gate.evaluate(vs baselines)
```

**Equity sampling basis (pinned per Codex #13):** equity recorded at every event timestamp inside step 6 + every bar close (step 7) + every FTMO reset (step 1). Sharpe / Sortino / MaxDD compute from the **1h-resampled equity series** to make the sampling basis frequency-independent across runs. `ChallengeResult.equity_curve` is the full 1h-resampled series; `equity_curve_daily` is FTMO-day-end samples for reporter charts.

## 5. Component Specifications

### 5.1 `types.py`

```python
@dataclass(frozen=True)
class Trade:
    symbol: str
    strategy: str
    direction: int
    open_ts: datetime
    open_price: float           # ask for long, bid for short
    close_ts: datetime
    close_price: float          # bid for long, ask for short
    stop: float
    target: float
    lots: float
    pnl_account_ccy: float      # net of spread, swap, commission, in account currency
    swap_account_ccy: float
    commission_account_ccy: float
    exit_reason: Literal[
        "target", "stop", "ftmo_breach", "session_close",
        "weekend_flatten", "deadline_flatten",
    ]
    components: dict[str, float]  # carried from Signal for explainability

@dataclass(frozen=True)
class ExitEvent:
    """One position-affecting event with a precise timestamp for chronological ordering."""
    ts: datetime
    symbol: str
    kind: Literal["stop", "target", "swap", "weekend_flatten", "deadline", "session_close"]
    price: float                # the price at which the event resolves
    position_id: int            # which open position this event closes/affects

@dataclass(frozen=True)
class RuleBreach:
    rule: Literal["daily_loss", "max_loss", "max_trading_days"]
    timestamp: datetime
    equity_at_breach: float
    threshold: float

@dataclass(frozen=True)
class ChallengeResult:
    start_ts: datetime
    end_ts: datetime
    outcome: Literal["passed", "failed", "push", "in_progress"]
    failed_by: Optional[str]
    target_hit_at: Optional[datetime]
    trading_days: int
    final_equity_account_ccy: float
    trades: list[Trade]
    breaches: list[RuleBreach]
    equity_curve: pd.Series         # 1h-resampled, full
    equity_curve_daily: pd.Series   # FTMO-day-end for charts
```

Account-currency-agnostic naming throughout (Codex #4). The `*_usd` suffixes from the prior draft are removed; values are in `ftmo_config["account_currency"]`.

### 5.2 `pip_value.py` (NEW per Codex #4)

FX sizing mechanics. Without this, the 0.5%-risk sizing formula is fictional.

```python
@dataclass(frozen=True)
class PairSpec:
    symbol: str
    pip_size: float            # 0.0001 for non-JPY, 0.01 for JPY-quoted
    contract_size: int         # 100_000 units for standard FX

def pip_value_in_account_ccy(
    pair: PairSpec,
    account_ccy: str,
    quote_to_account_rate: float,  # current bid/ask of QUOTE/ACCOUNT pair
) -> float:
    """pip value (per lot) in account currency.

    For EURUSD with USD account: pip_size=0.0001, quote=USD, rate=1.0
        → pip_value = 0.0001 × 100_000 / 1.0 = $10/pip/lot

    For EURGBP with USD account: pip_size=0.0001, quote=GBP, rate=GBPUSD
        → pip_value = 0.0001 × 100_000 / (1/GBPUSD) = $10 × GBPUSD/pip/lot
    """
```

Property tests cross-check against FTMO's spec page values for a sample of 8 pairs spanning major / cross / JPY-quoted / non-USD-base. Directly addresses the BH Lite priority TODO ("dollar_per_pip_per_lot 10x error on exotic pairs"). Verified pip values port forward into `bh_ftmo_config.json`.

### 5.3 `trade_factory.py`

Converts a `Signal` (Phase 2b) into a tradeable `Position`. Phase 2b signals carry score + components but no levels — this is the missing piece.

**Default level derivation:**
- Entry: next 4h bar's actual open at ask (long) or bid (short) — directly from `fx_store` (Codex #6 — the 4h-close-spread snapshot from the prior draft is removed)
- Stop: `entry − k_stop × ATR(14)` for long; mirror for short. Default `k_stop = 1.5`.
- Target: `entry + k_target × ATR(14)` for long; mirror for short. Default `k_target = 2.5` (1.67 R:R).
- Lots: `(equity × risk_pct) / (stop_distance_in_pips × pip_value_in_account_ccy)` via `pip_value.py`. Default `risk_pct = 0.005`.

`k_stop`, `k_target`, and the ATR window are configurable per-strategy in `bh_ftmo_weights.json`. Phase 2c grid-searches them alongside indicator weights.

**Refuse-to-open conditions (Codex #2):**
- 1h bars missing for the entry pair for the next ~5 trading days → skip; log `skipped_reason="missing_1h_data"`
- `calendar_provider.is_blackout(ts, currencies)` returns True → skip
- Concurrency cap reached (§6.4) → skip

### 5.4 `intrabar.py`

When a position has both stop and target inside a single 4h bar's H-L range, the engine cannot determine fill order from 4h data alone. The 1h store provides intrabar resolution.

```python
def extract_events(position: Position, bar_4h: pd.Series, bars_1h: pd.DataFrame) -> list[ExitEvent]:
    """Walk the 4 1h sub-bars; emit ExitEvent for every stop/target hit
    encountered, with the 1h-bar-close timestamp as event ts.

    Cases collapsed by the refuse-to-open rule (§5.3):
      - 1h missing entirely: trade was never opened, never reaches here
      - both stop+target inside same 1h bar: still emitted; engine_queue applies
        them in the order they appear in the 4 1h-bar walk (deterministic)
    """
```

The `unresolved` count from the prior draft is removed — the refuse-to-open rule eliminates that category.

### 5.5 `event_queue.py` (NEW per Codex #1)

Portfolio-level chronological applier. Critical for FTMO correctness: a stop on USDJPY at 14:00 NY must impact equity *before* a target on EURUSD at 15:30 NY, even if they're inside the same 4h bar.

```python
def collect_and_sort(open_positions: list[Position], bar_4h: pd.Series, bars_1h: dict[str, pd.DataFrame]) -> list[ExitEvent]:
    """Gather intrabar events from every open position, return chronologically sorted."""

def apply_in_order(
    events: list[ExitEvent],
    state: SimState,
    rule_engine: FtmoRuleEngine,
) -> Optional[RuleBreach]:
    """Apply events in order. Update equity after each. Check intrabar breach.
    Return first breach encountered or None.
    """
```

Tie-breaking when two events share a timestamp: deterministic by `(symbol_alphabetical, kind_priority)` where `stop > target` (worst-for-account first, conservative).

### 5.6 `equity.py`

Tracks running cash + floating P&L on open positions, mark-to-market against bid/ask. Equity is what FTMO rules check against.

```python
def equity(cash: float, positions: list[Position], bid_at: dict[str, float], ask_at: dict[str, float]) -> float:
    """cash + Σ floating_pnl(pos), each long marked at bid, short at ask."""
```

Sampling basis (pinned, Codex #13):
- 1h bar closes (primary metric basis)
- Every event timestamp during event_queue.apply_in_order
- Every FTMO-day reset

`equity_curve_1h` is the canonical series for Sharpe/Sortino/MaxDD. Using a different sampling basis would change the metric — the basis is part of the gate spec.

### 5.7 `swap.py`

Loads per-instrument financing rates from OANDA `/v3/accounts/{id}/instruments` (cached daily; rates versioned in `data/swap_rates_<date>.json`).

```python
def apply_swap(positions: list[Position], date: date, rates: dict[tuple[str, int], float]) -> float:
    """Total swap charge in account currency for a given FTMO-day rollover.

    Wednesday: triple per FTMO_RULES §5.2.
    Ordering note: swap is applied at rollover BEFORE the new daily-loss baseline
    is captured (§4 step 2 → step 1 of next day). The new day's reference equity
    is post-swap.
    """
```

### 5.8 `commission.py` (Codex #7 update)

Half-at-open / half-at-close. Charging full commission only at close gives back headroom that FTMO took immediately and biases backtest pass-rates upward.

```python
def commission_at_open(lots: float, per_lot_round_turn: float) -> float:
    return 0.5 * lots * per_lot_round_turn

def commission_at_close(lots: float, per_lot_round_turn: float) -> float:
    return 0.5 * lots * per_lot_round_turn
```

### 5.9 `calendar_provider.py` (NEW from review A2)

Phase 5 seam. Phase 3 ships `NullCalendarProvider`; Phase 5 adds a real ForexFactory-backed implementation.

```python
class CalendarProvider(Protocol):
    def is_blackout(self, ts: datetime, currencies: set[str]) -> bool: ...
    def next_blackout_end(self, ts: datetime, currencies: set[str]) -> Optional[datetime]: ...

class NullCalendarProvider:
    def is_blackout(self, ts, currencies): return False
    def next_blackout_end(self, ts, currencies): return None
```

Engine consults `provider.is_blackout()` in `trade_factory.derive()` (refuse-to-open) and at FTMO-day-reset (decide whether to flatten through the event window — config-driven).

### 5.10 `risk_exits.py` (NEW per Codex #11 / locked decision 14)

Weekend flatten + deadline awareness. Locked decision 14 says these ship in Phase 3 as risk-exits, not Phase 4 edge-exits.

```python
def weekend_flatten_if_due(
    open_positions: list[Position],
    ts: datetime,
    config: dict,
) -> list[ExitEvent]:
    """If ts is within `weekend_flatten_hours_before_close` of Friday NY close,
    emit close events for all open positions at current bid/ask."""

def deadline_check(
    ts: datetime,
    deadline: Optional[date],
    config: dict,
) -> DeadlineState:
    """Returns: NORMAL | TIGHTENED | NO_NEW_ENTRIES | HARD_FLATTEN.
    Per locked decision 15 graduated thresholds (>7d / 3-7d / <3d / on_date)."""
```

These wire into `engine.run_challenge()` step 3 in §4.

### 5.11 `ftmo_rules.py`

Stateful evaluator implementing FTMO_RULES.md §3–§6. Reads `bh_ftmo_config.json` `ftmo` block.

**Hard-block on placeholders (Codex #3 / locked P3-3):**
```python
class FtmoConfigUnverifiedError(Exception): ...

REQUIRED_FIELDS = {
    "initial_balance", "account_currency", "phase",
    "profit_target_pct", "daily_loss_pct", "max_loss_pct", "max_loss_type",
    "min_trading_days", "max_trading_days",
    "server_timezone", "commission_per_lot_round_turn", "swap_model",
}

def load_ftmo_config(path: Path) -> dict:
    cfg = json.loads(Path(path).read_text())["ftmo"]
    # Strip metadata keys (underscore-prefixed are convention for non-data keys)
    data = {k: v for k, v in cfg.items() if not k.startswith("_")}
    missing = REQUIRED_FIELDS - data.keys()
    placeholders = [k for k, v in data.items() if isinstance(v, str) and "PLACEHOLDER" in v]
    if missing or placeholders:
        raise FtmoConfigUnverifiedError(
            f"FTMO config incomplete. Missing: {sorted(missing)}; "
            f"unfilled: {placeholders}. Fill from FTMO dashboard before running. "
            "See FTMO_RULES.md §2."
        )
    if data["max_loss_type"] not in ("static", "trailing"):
        raise FtmoConfigUnverifiedError(
            f"max_loss_type must be 'static' or 'trailing'; got {data['max_loss_type']!r}"
        )
    return data
```

No `--allow-placeholders` flag. Sub-phase 3.0 ships with the engine refusing to run until Brand fills `bh_ftmo_config.json` `ftmo` block.

**Static vs trailing max-DD (Codex #3):** `ftmo_config["max_loss_type"]` = `"static"` | `"trailing"`. Static branch anchors threshold at `initial_balance × (1 − max_loss_pct)`. Trailing branch tracks running peak equity and recalculates threshold on every equity update. Must be set; no default — that's the architectural fork Codex flagged.

**DST-aware CE(S)T resets (review A1 + Codex #12):** `ftmo_rules.session_reset_if_due` calls `fx_time_utils.ftmo_day_boundary(ts, server_tz=ftmo_config["server_timezone"])`. The `fx_time_utils` module is the single source of truth for DST and holiday handling — including the US/EU DST mismatch weeks (Codex #12) where the Prague-NY offset is non-constant.

### 5.12 `engine.py`

The main loop. Tight, deterministic, no I/O during the run (data loaded ahead). **Process-safe (review A3):** no module-level state, no shared mutable args, all inputs picklable.

```python
def run_challenge(
    bars_4h: dict[str, pd.DataFrame],
    bars_1h: dict[str, pd.DataFrame],
    signals: list[Signal],
    ftmo_config: dict,
    sizing_config: dict,
    swap_rates: dict,
    calendar_provider: CalendarProvider,
    start_ts: datetime,
    start_equity: float,
    rng_seed: int,
) -> ChallengeResult: ...

def run_n_randomized(
    challenges: list[StartConfig],
    *,
    max_workers: int = None,
) -> list[ChallengeResult]:
    """ProcessPoolExecutor fan-out for the gate's pass-rate metric.
    Determinism: each StartConfig carries its own rng_seed; same seed → same result
    regardless of pool size."""
```

### 5.13 `walk_forward.py`

```python
def fold_windows(start: date, end: date, is_months: int = 18, oos_months: int = 6, roll_months: int = 6) -> Iterator[Fold]: ...
```

Fold edges snap to trading days via `fx_time_utils.prior_forex_day` so a fold doesn't start on Christmas. **OOS-contamination assertion** required (plan §Phase 3): after fold split, shuffling OOS rows must not change IS scores (property test).

**Phase 3 uses folds for OOS evaluation only.** The grid-search optimizer (`optimizer.py` in the prior draft) is removed from Phase 3 and deferred to Phase 2c per locked decision P3-9 (Codex #14).

### 5.14 `metrics.py`

Pure functions over `list[Trade]` and the 1h-resampled equity series.

- Sharpe, Sortino — annualized; sampling basis is the 1h equity curve (pinned §5.6)
- Profit factor, win rate, R-expectancy, payoff ratio
- Max drawdown (peak-to-trough in account ccy and %), worst-DD trade chain
- **FTMO pass rate with bootstrap 95% CI** — Codex #9: pass/fail outcomes from the **non-overlapping-start cohort** are bootstrap-resampled (B=1000) to produce a CI on pass rate

### 5.15 `baselines.py` (decision 17B)

Three null strategies implementing the same `Signal`-producing interface as `BaselineStrategy`:

1. `RandomEntryAtrExitStrategy` — uniform random entry direction at random bars, ATR-based exit. Seeded.
2. `MondayInFridayOutStrategy` — every Monday Asia open: long EUR_USD; close Friday before NY close.
3. `SimpleRsi14Strategy` — RSI(14)<30 long, RSI(14)>70 short.

Each runs through the same engine over the same OOS folds. Reporter places them side-by-side with BH FTMO. Each baseline produces its own pass-rate distribution that the gate compares against.

### 5.16 `gate.py` (Codex #9 + #10)

```python
def evaluate_gate(
    metrics: BacktestMetrics,
    baseline_metrics: dict[str, BacktestMetrics],
) -> GateResult:
    """Per locked decision 16A + Codex #9/#10."""
```

**Updated criteria (decision P3-10):**

| Criterion | Threshold |
|---|---|
| Sharpe ratio | ≥ 1.0 |
| Profit factor | ≥ 1.3 |
| Win rate | ≥ 45% |
| Max drawdown | ≤ 10% |
| **FTMO pass-rate lower-95%-CI bound** | **≥ 70%** (non-overlapping starts; Codex #9) |
| **FTMO pass-rate vs best baseline** | **≥ 10pp better** (Codex #10) |

If any criterion fails, gate fails. Reporter surfaces verdict prominently with per-criterion detail.

### 5.17 `reporter.py`

Writes:
- `src/logs/bh_ftmo_backtest_<run_id>.csv` — per-trade ledger
- `src/graphs/bh_ftmo_backtest_<run_id>.html` — equity curve, per-cluster/per-session/per-strategy breakdowns, baselines side-by-side, gate verdict, worst-DD chain visualization, pass-rate bootstrap-CI histogram

Modeled on `src/bluehorseshoe/reporting/html_reporter.py` but standalone (decision 15D).

## 6. Sub-Phase Sequencing

| # | Sub-phase | Deliverables | Ends with |
|---|---|---|---|
| 3.0 | Primitives + sizing | `types.py`, `pip_value.py`, `position.py`, `equity.py`, `swap.py`, `commission.py`, `intrabar.py`, `event_queue.py`, `trade_factory.py`, `calendar_provider.py`, `risk_exits.py` | All primitives unit-tested. `pip_value.py` property tests against FTMO spec values for 8 sample pairs. Brand fills `bh_ftmo_config.json` `ftmo` block (no placeholders). |
| 3.1 | Engine + rules | `ftmo_rules.py`, `engine.py` | Single-challenge run on EURUSD 2023 produces sane ledger. Rule-precedence + portfolio-event-ordering tests green. |
| 3.2 | Baselines | `baselines.py` | Three null strategies run end-to-end through engine. |
| 3.3 | Metrics + reporter | `metrics.py`, `reporter.py` | HTML report renders for one challenge run. Bootstrap CI computed correctly on toy fixture. |
| 3.4 | Walk-forward + gate | `walk_forward.py`, `gate.py` | OOS-contamination assertion green; 17 folds enumerated correctly; gate evaluates locked Phase 2b weights with verdict. |

Optimizer (formerly sub-phase 3.4) is **deferred to Phase 2c per decision P3-9**.

Total: ~1.5 weeks if budgets hold.

## 7. Locked Decisions This Doc Adds

| # | Decision | Resolution |
|---|---|---|
| P3-1 | Position sizing | Fixed-% equity-at-risk, default 0.5%; via `pip_value.py` for non-USD pairs |
| P3-2 | Stop/target derivation | ATR(14), `k_stop=1.5`, `k_target=2.5` defaults |
| P3-3 | FTMO §2 placeholders | **HARD-BLOCK** via `FtmoConfigUnverifiedError`. No flag override. Sub-phase 3.0 exit gate is Brand filling `ftmo` block from FTMO dashboard. |
| P3-4 | Concurrency cap | `max_concurrent_positions=5`, `max_concurrent_per_currency=2`, **`max_concurrent_per_usd_basket=3`** (USD-correlation guard, Codex #5: long EURUSD + long GBPUSD + short USDJPY all bet against USD; cap the sum) |
| P3-5 | Primary mode | Randomized-start with **non-overlapping windows** (~120 starts in 10y); bootstrap 95% CI on pass rate |
| P3-6 | Spread snapshot | **Use next 4h bar's actual open ask/bid** from `fx_store` (Codex #6, replaces prior P3-6) |
| P3-7 | Reuse `fx_time_utils.py` | `ftmo_rules.py` and `walk_forward.py` consume `ftmo_day_boundary` + `prior_forex_day` (review A1) |
| P3-8 | CalendarProvider Protocol | Phase 3 ships `NullCalendarProvider`; Phase 5 swaps in real (review A2) |
| P3-9 | Process-safe engine + ProcessPoolExecutor | `run_challenge()` is pure; `run_n_randomized()` fans out (review A3) |
| P3-10 | Conservative concurrency rules | Repeat-direction skip; opposing-direction skip; cap-skip (review A4) |
| P3-11 | Portfolio event ordering | Events from all open positions collected and sorted before applying (Codex #1) |
| P3-12 | Refuse-to-open if 1h missing | Eliminates the unresolved-trade category (Codex #2, supersedes C-1's "exclude from P&L" treatment for Phase 3+) |
| P3-13 | Static vs trailing max-DD | `ftmo_config["max_loss_type"]` required; no default. Each branch is its own code path. (Codex #3) |
| P3-14 | FX sizing mechanics | New `pip_value.py` module; per-pair pip_size, contract size, quote-currency conversion (Codex #4) |
| P3-15 | Half-at-open / half-at-close commission | (Codex #7) |
| P3-16 | Swap-then-reset ordering | New daily-loss baseline computed AFTER rollover swap applied (Codex #8) |
| P3-17 | Pinned equity sampling basis | 1h-resampled series is the canonical basis for Sharpe/Sortino/MaxDD (Codex #13) |
| P3-18 | Risk-exits in Phase 3 | `risk_exits.py` ships in sub-phase 3.0; weekend-flatten + deadline awareness (Codex #11 / locked decision 14) |
| P3-19 | Gate adds baseline-relative threshold | Pass-rate lower-CI ≥ 70% AND ≥ 10pp better than best baseline (Codex #10) |
| P3-20 | Optimizer deferred | `optimizer.py` removed from Phase 3; relocated to Phase 2c (Codex #14) |

Decision C-1's "exclude unresolved from P&L stats" is **superseded by P3-12** for Phase 3+: refuse-to-open eliminates the category. C-1 remains a soft fallback if data quality degrades post-launch.

## 8. Test Strategy

| Test category | What it covers | Location |
|---|---|---|
| Unit — primitives | swap, commission, equity-mark-to-market, intrabar event extraction | `test_*.py` per module |
| Unit — pip_value | property tests against FTMO spec for 8 sample pairs (majors, JPY, exotic, cross) | `test_pip_value.py` |
| Unit — rules | each FTMO_RULES §3 rule fires; precedence per §6; static vs trailing DD | `test_ftmo_rules.py` |
| Unit — config | `FtmoConfigUnverifiedError` raised on placeholder | `test_ftmo_rules.py` |
| Unit — concurrency | A4 rules: repeat-skip, opposing-skip, cap-skip, USD-basket cap | `test_concurrency.py` |
| Unit — calendar seam | NullProvider passthrough; mock provider blocks new entry + flattens through window | `test_calendar_provider.py` |
| Unit — risk exits | weekend flatten exact timing; deadline graduated thresholds | `test_risk_exits.py` |
| Unit — event queue | chronological ordering across multi-position events; tie-breaking | `test_event_queue.py` |
| Property — no-lookahead | Engine output for bar T unchanged when bars > T are added (R-1 extended) | `test_engine_lookahead.py` |
| Property — OOS contamination | Shuffling OOS rows leaves IS scores invariant | `test_walk_forward.py` |
| Property — parallel determinism | Same seed → identical N=120 result regardless of pool size | `test_engine_parallel.py` |
| Integration — known-outcome | Hand-built trade sequence with arithmetic-checked P&L | `test_engine_integration.py` |
| Integration — DST | Challenge spanning DST boundary (incl. US/EU mismatch weeks Codex #12) computes resets correctly | `test_dst_resets.py` |
| Integration — fx_time_utils | `ftmo_day_boundary` reused; no duplicate DST logic in `ftmo_rules.py` | `test_time_integration.py` |
| Integration — portfolio breach ordering | Cross-position scenario where order determines pass/fail outcome | `test_portfolio_ordering.py` |
| Golden — frozen run | One canonical backtest's ledger frozen; future changes flag diffs | `test_golden_run.py` |

## 9. Risks + Mitigations

| Risk | Mitigation |
|---|---|
| Engine has subtle look-ahead via signal lookup misalignment | Strict no-lookahead property test before sub-phase 3.1 closes |
| Event-queue tie-breaking introduces non-determinism | Deterministic tie-break: `(symbol_alphabetical, kind_priority)` with `stop > target` |
| OANDA financing rates drift from FTMO actuals | Quarterly verification; rates versioned in `data/swap_rates_<date>.json` |
| Walk-forward windows leak via shared indicator state | Indicators are stateless (Phase 2a confirmed); no module-level caches |
| FTMO §2 fields stay placeholder accidentally | Engine raises `FtmoConfigUnverifiedError` on load. Cron cutover (Phase 6) hard-checks. |
| Optimizer overfits in-sample weights | Optimizer not built in Phase 3 (P3-20 defers). Phase 2c adds it on top of fold infrastructure. |
| Reporter HTML diverges from equity-side reporter | Acceptable per decision 15D; cosmetic divergence expected |
| Engine wall-clock too slow for 120 starts × 17 folds | ProcessPoolExecutor (P3-9); profile after 3.1; expect <30s per challenge serial |
| `pip_value.py` math wrong for exotic pairs (BH Lite TODO) | Property tests against FTMO spec page values; verified BH Lite config gets ported, not re-derived |
| US/EU DST mismatch weeks compute wrong CE(S)T-NY offset | Explicit integration test (Codex #12); `fx_time_utils` is canonical source |

## 10. Exit Criteria for Phase 3

1. All sub-phase tests green; `./run.sh pytest src/tests/bh_ftmo/backtest/` all pass
2. `bh_ftmo_config.json` `ftmo` block fully filled (no placeholders) per FTMO dashboard verification
3. First gate evaluation run on locked Phase 2b weights produces a verdict
4. Reporter HTML rendered and reviewed for sanity
5. If gate passes → unblock Phase 4 (edge-exits) + Phase 2c (lookback tuning + optimizer)
6. If gate fails → halt, debug entries, do NOT enter Phase 4

## 11. References

- `docs/planning/BH_FTMO_PLAN.md` §Phase 3 (locked plan + decisions 8, 14, 16A, 17B)
- `docs/planning/FTMO_RULES.md` (canonical rule spec)
- `docs/planning/FX_TIME_SPEC.md` (timestamp / DST / holiday rules)
- `src/bh_ftmo/data/fx_store.py` (data substrate)
- `src/bh_ftmo/data/fx_time_utils.py` (DST + holiday + gap classification — reused per P3-7)
- `src/bh_ftmo/analysis/strategy.py` + `signal_generator.py` + `cluster_filter.py` (Phase 2b output)

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 4 architecture issues + 14 outside-voice findings, 18 decisions locked (P3-1..P3-20) |
| Outside Voice | `codex exec` (inline, eng) | Independent 2nd opinion | 1 | RESOLVED | 14 findings, 13 incorporated as locked decisions, 1 (#5) folded into P3-4 USD-basket cap |
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | n/a (parent BH_FTMO_PLAN already CEO-cleared) |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | n/a (no UI scope; HTML reporter is non-interactive) |
| DX Review | `/plan-devex-review` | Developer experience | 0 | — | n/a (internal tooling) |

- **CROSS-MODEL:** Claude review found 4 issues (A1–A4). Codex independently found 14. Strong consensus on calendar-provider seam (A2 ↔ #11 risk-exits-architecture-as-seam) and parallel execution (A3 ↔ #9 statistical methodology). Codex caught what Claude missed: portfolio event ordering, FX sizing mechanics, half-at-open commission, equity sampling basis. Cross-model agreement signal: high.
- **UNRESOLVED:** 0
- **VERDICT:** ENG CLEARED — ready to implement Sub-phase 3.0 once `bh_ftmo_config.json` `ftmo` block is filled (P3-3 hard-block prerequisite).
