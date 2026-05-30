# Logfire Fail-Safe Bug — 2026-05-30

**Status:** OPEN. Filed against commit `11f041b` (Sat 2026-05-30 00:17 UTC).

## Symptom

Saturday's `run_daily_pipeline.sh` (`main.py -p`, started 01:00 UTC) hung for
**~1 hour** after scoring finished. Last log line: `Scored USFD` @ 02:17:44 UTC.
htop showed 0% CPU; `pgrep` showed three Python processes alive holding 5.5 GB
RSS combined. Killed at ~03:19 UTC.

## Diagnosis

Kernel stacks via `/proc/<pid>/stack`:

| PID | RSS | State | wchan |
|---|---|---|---|
| 642192 (parent) | 1.8 GB | S, 15 threads | `futex_wait_queue` (Python lock) |
| 648557 (worker) | 1.7 GB | S, 4 threads | `pipe_read` (ProcessPool idle) |
| 648561 (worker) | 2.0 GB | S, 4 threads | `futex_wait_queue` |

Open sockets via `/proc/<pid>/fd` resolved against `/proc/net/tcp`:

- **Healthy:** `127.0.0.1:27017` (MongoDB) ESTABLISHED — Mongo fine.
- **Not present:** any connection to `127.0.0.1:4004` (IBKR Gateway) — pipeline
  never reached `PaperTrader.submit_orders()`, so **no equity orders submitted**.
- **The smoking gun:** two HTTPS sockets in `CLOSE_WAIT` to Cloudflare IPs
  `104.26.9.129:443` + `172.67.69.88:443` — these are `logfire-us.pydantic.dev`.
  `CLOSE_WAIT` means the peer sent FIN but our application's `recv()` never
  returned and never closed.

## Root cause

`src/main.py` lines ~86–105 (added in `11f041b`):

```python
try:
    import logfire
    logfire.configure(service_name="gordon", send_to_logfire="if-token-present",
                      inspect_arguments=False)
    _lf_handler = logfire.LogfireLoggingHandler()
    _lf_handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(_lf_handler)
    _LOGFIRE = logfire
except Exception:
    _LOGFIRE = None  # observability must never break the pipeline
```

The `try/except` makes **setup** fail-safe, and `_span()` falls back to
`contextlib.nullcontext` — those are fine. **But** `logfire.configure()`
installs a `BatchSpanProcessor` whose flush worker runs in a **background
thread outside the try/except**. The `LogfireLoggingHandler` routes every
`INFO+` stdlib log through Logfire, so a multi-hour run queues thousands of
trace exports.

When Logfire's CDN closed the keepalive TCP socket but the OTLP HTTP transport
had no socket-level timeout, the exporter thread blocked on `recv()` forever.
At pipeline exit / span context-exit, the main thread blocked acquiring the
processor's flush lock — that's the `futex_wait_queue` on PID 642192.

The "instrumentation can NEVER break the pipeline" commit-message claim is
true for *startup* and *span creation*; it does **not** extend to the
export-thread's network I/O at flush time.

## Fixes (any one closes the hole)

1. **Bounded export timeout (recommended).** Pass an explicit `timeout` (e.g.
   `10s`) to the OTLP HTTP exporter, plus a bounded `force_flush()` window at
   atexit. The SDK's per-request defaults are not socket-level on all transports.
2. **Daemon export thread + bounded atexit.** Mark the BatchSpanProcessor's
   thread as daemon and cap atexit flush at e.g. 5 s; let pending spans drop
   rather than hang.
3. **Stop routing stdlib logs through Logfire.** `LogfireLoggingHandler` is the
   blast-radius amplifier — every INFO line becomes a remote write. Spans-only
   is enough for `gordon.predict` / `gordon.update`.
4. **Drop-on-full bounded queue.** Configure the processor with `max_queue_size`
   and `max_export_batch_size` so backpressure is dropped, not blocked.

Pick (1) + (3) for a fully closed loop.

## Operational follow-up

The 1am cron has no human watcher; a wedge stays wedged until somebody notices
in the morning. Add a process-age watchdog (e.g. `run_daily_pipeline_watchdog.sh`
that SIGTERMs `main.py` if elapsed > 90 min and emails the journal tail).

## Impact

- Tonight's `-p` did **not** submit IBKR orders — no equity positions opened.
- Memory tied up for 1h (5.5 GB) but recovered cleanly on SIGTERM.
- The hang blocked the Gordon/Bud Tier 1 rename window by ~1h; not a permanent
  loss but cost us cache time.

## References

- Memory: `project_logfire_failsafe_hole.md`, `project_logfire_instrumentation.md`
- Commit: `11f041b`
- Affected file: `src/main.py` (~lines 86–105)
