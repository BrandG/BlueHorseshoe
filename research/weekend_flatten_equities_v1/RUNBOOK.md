# Weekend-Flatten Equities v1 — Droplet Deployment Runbook

**Status:** Lean simulator (`generate_baseline_ledger_lean.py`) validated locally at 10 and 100 symbol scales. Ready for full-universe deployment.

See [`docs/planning/WEEKEND_FLATTEN_EQUITIES_v1.md`](../../docs/planning/WEEKEND_FLATTEN_EQUITIES_v1.md) for the study design.

## Pre-flight decisions

Two choices to make before provisioning:

### 1. Sampling cadence

| Mode | `--interval-days` | Date count | Est. trades produced | Est. wall time (8-core) |
|---|---|---|---|---|
| Daily (production-shape) | 1 | 2,772 | ~50,000 | ~2 days **w/ Phase B parallelism added** |
| Weekly (efficient) | 7 | 588 | ~10,000+ | ~9 hours single-threaded |
| Monthly | 30 | 137 | ~2,500 | ~2 hours single-threaded |

**Recommendation: weekly first.** Clears the design-doc statistical-power gate (≥10K trades) and finishes in a single droplet day. If the result is borderline or the regime stratification needs more samples, re-run daily with Phase B parallelism added.

The forex precedent test ran at the natural signal cadence (every H4 bar), which is the equivalent of daily here. But weekly sampling preserves the hold-time distribution (which is what the weekend question hinges on) and avoids counting the same signal repeatedly across consecutive days.

### 2. Phase B parallelism

Currently single-threaded (Phase A is parallel via ProcessPoolExecutor). Parallelizing Phase B by date is straightforward but unimplemented — would use fork inheritance of the indicator cache (free on Linux, ~3GB shared via copy-on-write across N workers).

**If running weekly:** skip the parallelism work; ~9 hours single-threaded is acceptable.
**If running daily:** add it before deployment. Otherwise 14 days single-threaded is unworkable.

## Droplet provisioning

Per the existing pattern in `reference_research_droplet_march29.md`:

- **Size:** 8 vCPU, 16 GB RAM, 100 GB SSD. The 16 GB is sufficient with `--max-workers 8` and the COW-shared cache; bump to 32 GB if running daily with Phase B parallelism.
- **Image:** Ubuntu 24.04 LTS with the standard repo dependencies (Python 3.12, TA-Lib, DuckDB)
- **Region:** SFO3 (matches prior research droplets; lowest latency to home)

```bash
# Provision (example — actual command depends on your DO config)
doctl compute droplet create bh-weekend-flatten-equities \
    --image ubuntu-24-04-x64 \
    --size c-8 \
    --region sfo3 \
    --ssh-keys $SSH_KEY_ID \
    --enable-monitoring

# Wait for IP; SSH host key prompt — verify fingerprint
ssh root@<droplet-ip>
```

## Repo + data sync

```bash
# From local machine
rsync -avz --progress -e ssh \
    --exclude '.venv' --exclude 'data/ohlcv.duckdb' --exclude 'src/logs' \
    --exclude 'src/graphs' --exclude '__pycache__' \
    /root/BlueHorseshoe/ root@<droplet-ip>:/root/BlueHorseshoe/

# DuckDB file separately (large; ~few GB)
rsync -avz --progress -e ssh \
    /root/BlueHorseshoe/data/ohlcv.duckdb root@<droplet-ip>:/root/BlueHorseshoe/data/

# .env separately (so secrets aren't in the bulk rsync log)
scp /root/BlueHorseshoe/.env root@<droplet-ip>:/root/BlueHorseshoe/.env
```

## On the droplet — setup

```bash
ssh root@<droplet-ip>
cd /root/BlueHorseshoe

# System deps (TA-Lib needs the C library)
apt-get update && apt-get install -y build-essential python3.12 python3.12-venv \
    python3.12-dev libta-lib0-dev pkg-config

# Python venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -r requirements.txt

# Sanity-check DuckDB + universe filter
./run.sh python -c "
from bluehorseshoe.data.duckdb_store import DuckDBStore
from bluehorseshoe.core.config import get_settings
s = DuckDBStore(get_settings().duckdb_path, read_only=True)
print(s._con.execute(\"SELECT COUNT(DISTINCT symbol), MIN(date), MAX(date) FROM ohlcv\").fetchone())
s.close()
"
```

## Run

**Weekly sample (recommended first pass):**

```bash
cd /root/BlueHorseshoe
nohup ./run.sh python research/weekend_flatten_equities_v1/generate_baseline_ledger_lean.py \
    --start 2015-01-01 --end 2026-05-01 \
    --universe-start 2015-01-01 --universe-end 2026-05-01 \
    --interval-days 7 \
    --max-workers 8 \
    --output research/weekend_flatten_equities_v1/baseline_ledger_weekly.csv \
    > research/weekend_flatten_equities_v1/run.log 2>&1 &
disown

tail -f research/weekend_flatten_equities_v1/run.log
```

**Daily sample (only if Phase B parallelism is added):**

```bash
nohup ./run.sh python research/weekend_flatten_equities_v1/generate_baseline_ledger_lean.py \
    --start 2015-01-01 --end 2026-05-01 \
    --interval-days 1 \
    --max-workers 8 \
    --output research/weekend_flatten_equities_v1/baseline_ledger_daily.csv \
    > research/weekend_flatten_equities_v1/run.log 2>&1 &
disown
```

## Sync results back

```bash
# From local machine, after the run completes
rsync -avz --progress -e ssh \
    root@<droplet-ip>:/root/BlueHorseshoe/research/weekend_flatten_equities_v1/baseline_ledger*.csv \
    /root/BlueHorseshoe/research/weekend_flatten_equities_v1/
```

## Teardown

```bash
# From local
doctl compute droplet delete bh-weekend-flatten-equities
```

## Phase 2 + 3 (local, after baseline ledger is back)

Once `baseline_ledger.csv` is local:

1. Write `simulate_uniform_flatten.py` (~150 lines): re-process the ledger, splitting weekend-spanning trades into pre-Friday-close + post-Monday-open segments. Output: `uniform_flatten_ledger.csv`.
2. Write `simulate_asymmetric_flatten.py` (~150 lines): same but only flatten if MTM unrealized > 0 at Friday close.
3. Write `compare_arms.py` (~100 lines): groupby + bootstrap-stability check + ship/no-ship decision per design-doc rule. Output: `WEEKEND_FLATTEN_EQUITIES_v1_RESULTS.md` and a memory entry `project_weekend_flatten_equities_v1_RESULTS.md`.

All three are local-CPU work — minutes, not hours.

## Statistical-power gate check (mandatory before Phase 2)

Before running the simulators, verify the baseline ledger clears all four design-doc gates:

```bash
./run.sh python -c "
import pandas as pd
df = pd.read_csv('research/weekend_flatten_equities_v1/baseline_ledger_weekly.csv')
print(f'Total trades:        {len(df)}')
print(f'Weekend-spanning:    {(df.spans_weekends > 0).sum()} ({(df.spans_weekends > 0).mean()*100:.1f}%)')
print(f'Trades by regime:')
print(df.regime.value_counts())
"
```

Gates:
1. Total ≥ 10,000
2. Weekend-spanning ≥ 50% of total
3. Each major regime (vol_2018, covid_2020, bear_2022, trend_2023_2026) ≥ 1,000 trades
4. Bootstrap-stable result (applied in Phase 3)

If any of (1)-(3) fail, the run is undersized — re-run with daily sampling, broader universe, or both. Document the failure mode rather than acting on weak data.
