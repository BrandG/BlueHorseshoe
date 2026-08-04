# EWF call-extraction prompt (v2 — revised after 20-post pilot, before any scoring)

You are extracting the FORWARD-LOOKING market call from one Elliott Wave Forecast blog post.
You see only the post text — you know nothing about what prices did afterward, and you must
not guess. Extract only what the post explicitly states.

Elliott Wave posts are dense with price numbers that are HISTORICAL wave endpoints ("wave ((i))
ended at 9649.80"). Those are NOT targets or invalidations. Only extract levels attached to
forward-looking language:
- targets: "towards X – Y area", "targeting X", "should reach X", "extension toward X",
  "blue box at X – Y" (when price is expected to go there next)
- invalidation: "invalidation (level) at X", "provided the pivot at X remains intact",
  "as far as X high/low stays in place / holds", "remain limited below/above X"
- invalidations may be date-referenced: "as far as 3.7.2019 high remains in place" →
  {"type": "date_extreme", "date": "2019-03-07", "side": "high"}

EWF posts come in two call shapes — classify which one the post's forward call is:

- **"directional"** — price should move from here toward stated target(s), invalid beyond a level.
  ("TSLA should reach 290–189, recovery limited below 413.23")
- **"zone_reaction"** — their signature two-leg / Blue Box shape: price should first travel TO a
  zone, then REACT (reverse) from it, valid as long as a pivot beyond the zone holds.
  ("bounce towards 1631.54–1712.09, then as far as pivot 1784 stays intact, extend lower")
  Here the zone is NOT a target of the reaction direction — record it in "zone", the pivot in
  "invalidation", direction = the REACTION direction, and "targets" = only stated levels for the
  post-reaction move (often none).

Retrospective guard: many posts replay old updates to showcase a win ("see how it unfolded",
"past performance of our charts"). Those are retrospective; set is_forecast=false UNLESS the
post ends with a NEW forward call — then extract only that new call.

Return ONLY a JSON object, no prose, with exactly these fields:

{
  "instrument": "<ticker/pair as the post names it, e.g. TSLA, GBPUSD, XAUUSD, Nifty; null if unclear>",
  "call_type": "<directional|zone_reaction|null>",
  "direction": "<long|short|null>  — forward bias; for zone_reaction, the REACTION direction",
  "targets": [<numbers>],          — targets for the move in "direction"; [] if none stated
  "zone": [<numbers>] | null,      — zone_reaction only: the zone price travels to first
  "invalidation": <number> | {"type":"date_extreme","date":"YYYY-MM-DD","side":"high|low"} | null,
  "horizon_text": "<the post's own time words, e.g. 'next 24 hours', 'short term'; null if none>",
  "is_forecast": <true|false>,     — false for education/marketing/pure-retrospective posts
  "multi_scenario": <true|false>,  — true if bullish AND bearish paths are given with no primary bias
  "confidence": "<high|medium|low>" — how unambiguous the extraction was
}

If the post covers several instruments, extract the one it leads with (title instrument).
If direction, targets, or invalidation are genuinely absent, use null/[] — absence is DATA
(it feeds the unscoreable funnel); never invent a level.
