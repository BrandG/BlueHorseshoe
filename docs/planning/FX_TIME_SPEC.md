# FX Time Specification

**Status:** canonical time/DST/holiday rules for BH FTMO (Phase 1 deliverable per plan decision 7A).
**Authority:** this document is the contract. `src/bh_ftmo/data/fx_time_utils.py` implements it. If they disagree, the spec wins and the code gets fixed.
**Drafted:** 2026-04-24

---

## 1. Canonical Storage: UTC

All timestamps persisted to `data/fx_4h.duckdb` (and any other store) are **timezone-naive UTC**. The canonical form is `TIMESTAMP` at wall-clock UTC (no tz suffix). Timezone conversions happen at read time — never at storage time.

Rationale: UTC is monotonic. DST transitions don't duplicate or skip UTC hours. Every downstream computation that needs "a specific moment in time" is trivial with UTC; every computation that needs a session-relative view is one `zoneinfo.ZoneInfo("America/New_York")` conversion away.

## 2. Session Anchor: NY 5pm

The 4h bar grid is **anchored to New York 5pm close**.

- **Bar open hours (NY local):** 17, 21, 01, 05, 09, 13
- **Bar close hours (NY local):** 21, 01, 05, 09, 13, 17
- Each H4 bar spans exactly 4 consecutive hours of NY local wall-clock time

In UTC, the H4 grid shifts with DST:

| US DST status | NY offset | H4 bar opens (UTC) |
| --- | --- | --- |
| EST (standard, ~Nov–Mar) | UTC−5 | 22, 02, 06, 10, 14, 18 |
| EDT (daylight, ~Mar–Nov) | UTC−4 | 21, 01, 05, 09, 13, 17 |

The bar grid is a property of **NY local time**, not UTC. UTC is how we store it; NY local is how the market sees it.

## 3. Forex Week: Sun 5pm NY → Fri 5pm NY

- **Week open:** Sunday 5pm NY (first H4 bar opens 5pm Sun, closes 9pm Sun)
- **Week close:** Friday 5pm NY (final H4 bar opens 1pm Fri, closes 5pm Fri)
- **Weekend (market closed):** Friday 5pm NY → Sunday 5pm NY (inclusive of Fri 17:00:00, exclusive of Sun 17:00:00)

Total expected bars per normal week: `1 (Sun) + 6×4 (Mon-Thu) + 5 (Fri) = 30`.

The Sunday bar (5pm NY → 9pm NY) is the **first bar of the upcoming Monday session** for session-day purposes (section 6).

## 4. DST Transitions

US DST is the authoritative transition (NY is the anchor). The market does not close for DST — bars continue at their NY local hours and the UTC representation shifts by one hour.

### Spring-Forward (second Sunday of March)

- NY local clock jumps 02:00 → 03:00
- The UTC hour 07:00 still exists but is never "02:00 NY" — it is "03:00 NY"
- Forex is closed all weekend up to Sun 5pm NY, so the DST transition happens mid-weekend
- First bar of the new week (Sun 5pm NY) opens at **21:00 UTC** (EDT)
- No bars are lost; the UTC grid shifts from `{22, 02, 06, 10, 14, 18}` to `{21, 01, 05, 09, 13, 17}` between Fri 5pm NY and Sun 5pm NY
- **No special-case logic required** in the code path — we always compute from NY local, so the shift is implicit

### Fall-Back (first Sunday of November)

- NY local clock jumps 02:00 → 01:00 (the hour 01:00 NY happens twice)
- Same as spring-forward: forex is closed through Sun 5pm NY, so the transition is bridged during the weekend
- First bar of the new week (Sun 5pm NY) opens at **22:00 UTC** (EST)
- Code path: always compute from NY local; UTC representation follows
- The duplicate 01:00 NY hour is never a forex-open hour (fall-back happens at 2am, Sun is still closed)

### Test coverage required

- A Fri 5pm NY → Sun 5pm NY boundary that straddles the spring-forward Sunday: verify `expected_h4_bars(...)` produces EDT-aligned UTC timestamps for Monday onward.
- Same for fall-back: verify EST-aligned UTC timestamps post-transition.

## 5. Holiday-Shortened Weeks

Forex markets (unlike equity markets) do **not close** for most holidays. Liquidity collapses but bars still print. FTMO's MT5 feed reflects this — a Christmas Day 4h bar will exist with minuscule tick volume.

**Classification only, not gap suppression.** We do not suppress bars on holidays. We *classify* them in observability so a missing bar can be labeled "thin-liquidity holiday" vs. "data provider gap."

Reference calendars via `exchange_calendars`:

- **US market holidays:** `XNYS` (NYSE). Covers New Year's Day, MLK Day, Presidents Day, Good Friday, Memorial Day, Juneteenth, July 4, Labor Day, Thanksgiving, Christmas. Also half-days (Christmas Eve, Black Friday, July 3).
- **UK bank holidays:** `XLON` (LSE). Covers UK-specific dates that affect GBP liquidity.
- **Extreme-closure dates** (forex actually quiet): December 25, January 1. These are the only two days where OANDA may legitimately return sparse/no bars.

## 6. NY Calendar Day (Daily-Pivot Derivation)

Daily pivots use the OHLC of the **prior NY calendar day** (midnight-to-midnight NY local time).

- `ny_calendar_day(dt_utc) -> date` — convert a UTC timestamp to NY local and return the date component
- `prior_forex_day(d) -> date` — return the prior **trading day** (Mon–Fri), skipping weekends. Does *not* skip US holidays (forex is open).
- Pivot for a bar at timestamp T: compute from OHLC of `prior_forex_day(ny_calendar_day(T))`.

Edge cases:

- For a Monday bar at 01:00 NY (Sun 10pm EST in UTC during EDT: 05:00 UTC): `ny_calendar_day` = Monday's date; `prior_forex_day(Mon)` = Friday.
- For the Sunday open bar (17:00 NY = 21:00 UTC EDT): `ny_calendar_day` = Sunday's date; `prior_forex_day(Sun)` = Friday (skip Saturday).

## 7. Missing-Bar Detection

Given a set of observed bars and a (start, end) UTC range, classify every missing expected bar:

```
BarGapKind = "weekend" | "us_holiday" | "uk_holiday" | "data_gap"
```

Algorithm:

1. Generate expected bar open timestamps for the range (`expected_h4_bar_opens` / `expected_h1_bar_opens`).
2. Set-subtract observed from expected.
3. For each missing timestamp:
   - If it falls in the Fri-5pm-NY → Sun-5pm-NY closed window → `weekend` (this should not appear; we don't emit weekend bars from `expected_*`, but the classifier defends against bad inputs)
   - Else look up NY calendar date:
     - If `XNYS.is_session(d) == False` → `us_holiday`
     - Elif `XLON.is_session(d) == False` → `uk_holiday`
     - Else → `data_gap` (the only kind that should page anyone)

Only `data_gap` is actionable. The rest are informational.

## 8. Granularities

This spec applies to both H4 (primary signal grid) and H1 (intrabar stop/target resolution, per plan decision 4A).

- H4 grid: bars open at NY hours `{17, 21, 1, 5, 9, 13}`
- H1 grid: bars open at every NY hour `{0..23}`, subject to forex-open rules

Both grids honor the same forex-week boundaries (Sun 5pm NY → Fri 5pm NY) and the same holiday classification rules.

## 9. What This Spec Does NOT Cover

- Quote-vs-trade timestamps (OANDA gives trade/close timestamps; we use those directly)
- Sub-minute resolution (S5/S10 granularities not used in v1)
- Tick data (not stored in v1 — we trust OANDA's aggregated H1/H4 candles)
- Future calendar events / news blackouts (Phase 5 deliverable, separate spec)
