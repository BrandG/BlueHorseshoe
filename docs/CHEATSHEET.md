# BlueHorseshoe Cheat Sheet

Operator quick-reference for the common-path controls. This is the "what knob do I turn"
sheet — not exhaustive. For the full map see [`PROJECTS.md`](PROJECTS.md); for the deep
runbook see [`SUBSYSTEMS_GUIDE.md`](SUBSYSTEMS_GUIDE.md).

The repo is two products (named after *Wall Street*, 1987):
- **GORDON** = US equities (IBKR) — Engine (`src/main.py` + `bluehorseshoe/`) does
  signal/prediction; Manager (`src/gordon/` + `bh_swing/`) does post-fill stop management.
- **BUD** = forex/FTMO (OANDA) — *section TBD.*

Everything runs through the venv wrapper: `./run.sh python src/main.py <flag>`.

---

## GORDON

### Daily driver — `./run.sh python src/main.py <flag>`

| Flag | Common args | What it does |
|---|---|---|
| `-u` | `--symbols A,B`, `--all`, `--refresh-overviews` | Update recent OHLCV (fast path, ~100 bars) |
| `-b` | `--resume`, `--limit N`, `--symbols A,B`, `--deep` | Full historical backfill (slow; needed for SPY/QQQ 200+ days) |
| `-p` | `[DATE]`, `--symbols A,B`, **`--no-paper`** | Predict candidates → report → (if enabled) submit paper brackets. `--no-paper` blocks execution for this run regardless of `.env`. |
| `--execute-open` | `[DATE]` | Fire staged fill-anchored orders (pairs with `FILL_ANCHORED_EXECUTION`) |
| `-r` | `[DATE]` | Regenerate HTML report from saved scores (no rescoring) |
| `-t` | `DATE --end --interval --strategy baseline\|mean_reversion --hold --target --stop --trailing --split` | Backtest (single date or range) |
| `-s` | `--live`, `--refresh-token` | Portfolio snapshot (paper; `--live` hits real acct, `--refresh-token` does 2FA) |
| `-q SYM…` / `-m` / `-i SYM E S T` | — | Live quote / watchlist monitor loop / intraday level check |
| `--journal-*` | `review`, `weekly`, `reconcile`, `import-ibkr`, `import-csv`, `log-ideas` | Trade-journal operations |

> `-o` (weight optimizer) is **retired** — the additive scorer has no validated selection
> edge, so weight tuning polishes noise. `-w`/`-f`/`-g` (weight/forward/impact analysis) exist
> but are research-only.

### Execution controls — `.env` (the knobs that move money)

| Var | Default | Effect |
|---|---|---|
| **`PAPER_TRADING_ENABLED`** | `false` | Global on/off for auto-execution during `-p` |
| **`PAPER_TOTAL_INVESTMENT`** | `10000` | Capital deployed across positions |
| **`PAPER_MAX_POSITIONS`** | `10` | "At most N on the book" cap (not N per run) |
| **`IBKR_READ_ONLY`** | `yes` | Set to `not` to allow order placement; anything else refuses mutations |
| `PAPER_CONVICTION_SIZING` | `true` | Edge-weight sizing vs flat equal-weight |
| `PAPER_MAX_POSITION_MULT` | `2.5` | Cap on conviction multiple of base size |
| `PAPER_SLOTS_DEEP_OVERSOLD` | `0` | Reserved slots for the deep-oversold sleeve |
| `PAPER_FRACTIONAL_SHARES` | `false` | Fractional orders (currently blocked by IBKR Error 10243) |
| `DEEP_OVERSOLD_NONBULL_GATE` | `false` | Block deep-oversold signals outside bullish regimes |
| `DEEP_OVERSOLD_SOLVENCY_FILTER` | `false` | Altman-Z″ solvency filter on deep-oversold |
| `HOLIDAY_MODE` | `false` | Skip trading on US market holidays |
| `IBKR_HOST` / `IBKR_PORT` / `IBKR_CLIENT_ID` | `127.0.0.1` / `4004` / `1` | Gateway target |
| `ALPHAVANTAGE_KEY` / `ALPHAVANTAGE_CPS` | — / `2` | Market data key + rate limit |
| `MONGO_URI` / `MONGO_DB` / `DUCKDB_PATH` | local / `bluehorseshoe` / host-specific | Storage |

### Tuning files (edit with research backing only)

- `src/weights.json` — indicator multipliers; `0.0` disables an indicator.
- `src/bluehorseshoe/analysis/constants.py` — price filters (`MIN/MAX_STOCK_PRICE` $5–$500),
  liquidity floor (`MIN_DOLLAR_VOLUME` $5M), the validated `DEEP_OVERSOLD_*` sleeve params,
  `SIGNAL_STRENGTH_THRESHOLDS`, `ENTRY_DISCOUNT_BY_SIGNAL`.

### Manager (post-fill stop management) — `src/gordon/`

| Tool | Key flags | Purpose |
|---|---|---|
| `swing_monitor.py` | `--manage` / `--manage-dry-run` / (none) | Cronned every 5 min in market hours. Live stop moves / journal `would_*` only / read-only reconcile. Uses `client_id=7`. |
| `swing_status.py` | `--events N`, `--no-broker` | Read-only dashboard |
| `swing_flatten.py` | **`--execute`**, `--sort worst\|best\|biggest`, `--symbols` | Emergency flatten (dry-run by default) |
| `swing_friday_flatten.py` | `--dry-run`, `--force` | Weekend close (live by default) |

**Kill switches** — `touch` a sentinel file at repo root to halt without editing cron:
- `.bh_swing_pause_management` — pauses all live stop mutations
- `.bh_swing_pause_friday_flatten` — disables the Friday flatten
- `.score_backfill_pause` — pauses the background score backfill

Safety gates (`bh_swing/trading/safety.py`): 15 mutations/tick, position cap 10,
stop-*widening* is structurally refused.

### Service / API / cron

- **systemd:** `systemctl {start|stop|restart} bluehorseshoe-api` (port 8001)
- **API:** `POST /api/v1/{pipeline/run, predict}` · `GET /api/v1/{tasks/{id}, reports[/{date}[/email]], arcade/{date}, quote/{symbol}, health}`
- **cron:** daily pipeline (Tue–Sat 01:00 UTC) · swing monitor (5-min, market hours) ·
  Friday flatten · IBGW watchdog (5-min) · log rotation (03:30 UTC)

---

## BUD

Bud = OANDA forex / FTMO. **Auto** (`src/bud/auto_trader.py`) is the autonomous trader running v2
cells; **Briefing** (`src/bud/briefing.py` + `briefing_ftmo.py`) is the human-in-loop path; the
**Envelope** is `src/bud/config.json` + the `CELLS` table. The FTMO challenge book is **hand-maintained**
in `src/bud/positions.json` (not auto-synced from the OANDA demo).

### Daily driver — `./run.sh python src/bud/<tool>.py <flag>`

| Tool | Common args | What it does |
|---|---|---|
| `auto_trader.py` | **`--dry-run`** | Autonomous run: evaluate v2 cells, place/close OANDA orders. `--dry-run` logs signals only. Cron'd every 4h. |
| `briefing.py` | `--verbose`, `--email`, `--email-only-if-fires` | Human-readable v2-cell fire report (HTML, archived) |
| `briefing_ftmo.py` | `--dry-run`, `--email`, `--email-only-if-activity`, `--trace` | Sized orders + position-health email; writes `bh_briefing_ftmo_orders.json` |
| `positions.py` | `list` · `add SYM [--entry --stop --target --lots --side]` · `close SYM [--close-price --pnl]` · `sync [--dry-run --yes --only-untagged]` · `validate` | Maintain the hand-kept `positions.json` (FTMO challenge book) |
| `reconcile.py` | `--dry-run` | Join OANDA closed trades → outcomes; auto-runs at end of each `auto_trader` run |
| `status.py` | `--hours N` (48) | Account state + open positions (worst-first) + recent journal activity |
| `flatten.py` | — | Emergency close of OANDA positions |

Data/research (Lab): `python -m bh_ftmo.data.incremental_update` (4h fetch) ·
`python -m bh_ftmo.data.backfill --years 10 [--symbols --granularities --dry-run]` (resumable) ·
`python -m bh_ftmo.predict --equity 10000 [--no-email --symbols --strategies]` (legacy manual-entry signals).

### Execution controls — `.env`

| Var | Effect |
|---|---|
| **`OANDA_DEMO_TOKEN`** / **`OANDA_DEMO_ACCOUNT_ID`** | Practice account creds (the demo `auto_trader` book, `101-001-39154243-001`) |
| `OANDA_API_TOKEN` / `OANDA_ACCOUNT_ID` | Generic creds; `OANDA_ENV` / `OANDA_BASE` select demo vs live endpoint |
| `BH_FTMO_FX_DB` | Override FxStore path (default `data/fx_4h.duckdb`) |
| `SMTP_*` / `EMAIL_FROM` / `EMAIL_TO` | Email briefings (only used with `--email`) |

> There is **no `.env` on/off flag** for autonomous trading — the live switch is the crontab entry
> for `run_bh_ftmo_trader.sh`. To pause: comment it out (or run with `--dry-run`). Bud has **no**
> sentinel kill-switch file like Gordon's `.bh_swing_pause_management`.

### Sizing & safety — code constants (not env)

| Knob | Value | Where |
|---|---|---|
| Risk per trade | `0.005` (0.5%) | `auto_trader.py:67` `V2_RISK_PER_TRADE_PCT` · `briefing_ftmo.py:59` |
| Max concurrent positions | `5` (envelope default 3) | `briefing_ftmo.py:60` |
| Max new orders per run | `5` | `auto_trader.py:68` `MAX_NEW_ORDERS_PER_RUN` |
| Margin-utilization gate | `0.40` of NAV — aborts run if exceeded | `bh_ftmo/trading/safety.py:18` |
| Net-direction gate | `12` max `|n_long − n_short|` | `bh_ftmo/trading/safety.py:19` |
| TP / STOP (v2 cells) | `0.01` / `0.01` (1%) | `briefing.py` |
| Position aging caps | rising_3bar 14d (retired) · v2 limit 5d · v2 mid none | `bh_ftmo_config.json::bh_ftmo_trader` |

These gates reject ~75% of fires; rejections are journaled (`skip_margin_budget`,
`skip_direction_imbalance`, `skip_cap`), not silent.

### Tuning files (the Envelope)

- `src/bud/config.json` — instruments (38-pair subset), pip sizes, correlation `clusters`
  (opener skips an occupied cluster), and envelope risk defaults.
- `src/bud/briefing.py::CELLS` — the deployed v2 cell table (~33 cells across
  `{macd,atr,ichimoku,stoch,bb,cci,ema,sma,rsi}`); `CELL_QUALITY_RANK` prioritizes under the cap.
- `src/bud/positions.json` — source-of-truth open positions (FTMO challenge, hand-maintained);
  `positions_closed.json` is the append-only close log.
- `src/bh_ftmo_config.json` — full FTMO ruleset + aging caps + 40-pair universe (reference).

### Cron (every 4h: 01/05/09/13/17/21 UTC, staggered by minute)

| Min | Job | Purpose |
|---|---|---|
| :05 | `bh_ftmo.data.incremental_update` | Fetch latest OANDA H4 bars |
| :10 | `bh_ftmo.predict --equity 10000` | Legacy signal email |
| :16 | `run_bh_ftmo_trader.sh` | **Auto trader** — place/close orders + reconcile |
| :20 | `run_bh_briefing.sh` | v2-cell report (no email) |
| :25 | `run_bh_briefing_ftmo.sh` | Sized FTMO orders + health email |

Plus a weekday 22:30 UTC summary email. Logs: `src/logs/bh_ftmo_trader{.log,_journal.csv}`,
`bh_ftmo_outcomes.csv`, `bh_briefing*.log`; HTML archives under `src/logs/briefings/`.

### Quick reference

```bash
./run.sh python src/bud/status.py                 # account + activity (48h)
./run.sh python src/bud/auto_trader.py --dry-run  # detect signals, place nothing
./run.sh python src/bud/positions.py list
./run.sh python src/bud/positions.py add EURJPY.sim --entry 162.45 --stop 164.07 --target 161.64 --lots 0.06 --side sell
./run.sh python src/bud/positions.py sync --dry-run   # preview vs live OANDA
./run.sh python src/bud/reconcile.py              # journal closed-trade outcomes
./run.sh python src/bud/briefing_ftmo.py --trace  # sized orders + funnel trace
```
