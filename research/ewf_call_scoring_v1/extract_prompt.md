# EWF call-extraction prompt (v3 — ACTIVE from 2026-07-31; call_type is time-based, not vocabulary-based)

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

EWF posts come in two call shapes. Classify by WHERE PRICE IS RELATIVE TO THE ZONE
**as of this post**, never by vocabulary. EWF uses "blue box", "equal legs", and
"extreme area" for BOTH shapes — those words alone decide nothing.

Ask one question: **does price still have to travel to the zone before the trade works?**

- **"zone_reaction"** — the zone is still AHEAD. The post is waiting for price to reach it
  ("we like selling the rallies INTO 450-456", "expect a push higher TOWARD 2.752-2.778
  before turning lower", "looking for a bounce to the blue box"). Record the zone in
  "zone", the pivot beyond it in "invalidation", direction = the REACTION direction, and
  "targets" = only stated levels for the move AFTER the reaction (often none).

- **"directional"** — the zone is BEHIND, or there is no zone. Price has already reached
  and reacted from it and the post now expects continuation ("found buyers there as we
  expected, now while above 1.3176 look for more upside", "reaction higher taking place
  from the blue box area"). Also any ordinary from-here call. Put the forward levels in
  "targets" and the protective level in "invalidation"; leave "zone" null. A post whose
  TITLE celebrates a blue box ("Forecasting The Rally From The Blue Box") is usually this
  shape — the box is the setup that already fired.

Tie-breaker: if the post states the zone was reached, touched, or reacted from at any
point before publication, it is "directional". Only an un-reached zone is "zone_reaction".

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
