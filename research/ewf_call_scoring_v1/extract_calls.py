"""Phase 3: extract structured calls from posts via a headless LLM (see engines.py).

Blind extraction: the model sees ONLY the post text (SPEC.md §1) — no price data.
Resumable: appends to data/calls.jsonl, skips post ids already present.

BATCHING
--------
Both engines pay a large fixed per-invocation overhead (Claude ~25k tokens of session
scaffolding; codex ~9.5k). That overhead is per CALL, not per post, so we amortize it by
sending N posts per call. Integrity gate: every returned object must echo its own post_id
and the returned id set must match the batch EXACTLY — otherwise the batch is discarded
and re-run one post at a time, so a conflated or dropped post can never become a data row.

Usage:
  ./run_research.sh python .../extract_calls.py --engine codex --batch 20 --workers 3
  ./run_research.sh python .../extract_calls.py --verify 40 --engine codex   # batched vs stored
  ./run_research.sh python .../extract_calls.py --control 40                 # noise floor
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import threading

import pandas as pd

import engines
from engines import ABORT, InfraFailure, get_engine, is_infra_failure, last_json_value

HERE = Path(__file__).parent
PROMPT = (HERE / "extract_prompt.md").read_text()
OUT = HERE / "data" / "calls.jsonl"
SCHEMA = HERE / "data" / "batch_schema.json"
LOCK = threading.Lock()

MAX_POST_CHARS = 8000
ENGINE = None  # set in main()

FIELDS = ("instrument", "call_type", "direction", "targets", "zone",
          "invalidation", "horizon_text", "is_forecast", "multi_scenario", "confidence")

BATCH_INSTRUCTION = """
--------------------------------------------------------------------------------
You will now be given {n} posts, each delimited by a line of the form `=== POST id=N ===`.

Apply ALL of the instructions above to EACH post INDEPENDENTLY. Judge every post solely on
its own text. Never let one post's instrument, levels, or direction influence another's —
they are unrelated posts that merely happen to be sent together.

Return ONLY a JSON object of the form {{"calls": [ ... ]}} containing exactly {n} objects,
in the same order as the posts given. Each object must contain every field listed above,
PLUS a "post_id" field echoing that post's id exactly as it appears in its
`=== POST id=N ===` header.

No prose, no markdown fences — just the object.
--------------------------------------------------------------------------------
"""


def write_schema() -> Path:
    """JSON Schema for the batch response (codex --output-schema)."""
    num = {"type": "number"}
    call = {
        "type": "object",
        "properties": {
            "post_id": {"type": "integer"},
            "instrument": {"type": ["string", "null"]},
            "call_type": {"type": ["string", "null"],
                          "enum": ["directional", "zone_reaction", None]},
            "direction": {"type": ["string", "null"], "enum": ["long", "short", None]},
            "targets": {"type": "array", "items": num},
            "zone": {"type": ["array", "null"], "items": num},
            "invalidation": {"anyOf": [
                num,
                {"type": "object",
                 "properties": {"type": {"type": "string"},
                                "date": {"type": "string"},
                                "side": {"type": "string"}},
                 "required": ["type", "date", "side"], "additionalProperties": False},
                {"type": "null"},
            ]},
            "horizon_text": {"type": ["string", "null"]},
            "is_forecast": {"type": "boolean"},
            "multi_scenario": {"type": "boolean"},
            "confidence": {"type": ["string", "null"]},
        },
        "required": ["post_id", *FIELDS],
        "additionalProperties": False,
    }
    schema = {"type": "object", "properties": {"calls": {"type": "array", "items": call}},
              "required": ["calls"], "additionalProperties": False}
    SCHEMA.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA.write_text(json.dumps(schema, indent=2))
    return SCHEMA


def _post_block(post: dict) -> str:
    return (f"=== POST id={post['id']} ===\n"
            f"POST DATE: {post['date_gmt']}\nTITLE: {post['title']}\n\n"
            f"{post['content_text'][:MAX_POST_CHARS]}\n")


def _base_rec(post: dict) -> dict:
    return {"post_id": int(post["id"]), "date_gmt": str(post["date_gmt"]),
            "title": post["title"]}


def _merge(post: dict, obj: dict) -> dict:
    """Archive metadata always wins; the model only supplies FIELDS."""
    rec = _base_rec(post)
    rec.update({k: obj.get(k) for k in FIELDS})
    return rec


# ---------------------------------------------------------------------------

def _abort_if_infra(raw: str) -> None:
    """Raise InfraFailure if an UNPARSEABLE response is really a billing/auth message."""
    if is_infra_failure(raw or ""):
        ABORT.set()
        raise InfraFailure((raw or "")[:500])


def extract_one(post: dict) -> dict:
    text = f"{PROMPT}\n\n{_post_block(post)}"
    raw = ENGINE.run(text, timeout=300)
    obj = last_json_value(raw, dict)
    if obj is None:
        # Only NOW is it safe to read the text as a billing/outage signal: we have no
        # usable answer, so the response is not data. (A parseable answer is never an
        # infra failure, even if the post happens to discuss limits.)
        _abort_if_infra(raw)
        rec = _base_rec(post)
        rec["error"] = (raw or "")[:500] or "no-json"
        return rec
    return _merge(post, obj)


def extract_batch(posts: list[dict]) -> list[dict]:
    """Extract a batch in one call. Returns [] if the batch fails the integrity gate."""
    text = (PROMPT + BATCH_INSTRUCTION.format(n=len(posts)) + "\n"
            + "\n".join(_post_block(p) for p in posts))
    schema = SCHEMA if (ENGINE.name == "codex" and SCHEMA.exists()) else None
    raw = ENGINE.run(text, timeout=1200, schema=schema)

    payload = last_json_value(raw, dict)
    arr = payload.get("calls") if isinstance(payload, dict) else None
    if not isinstance(arr, list):
        arr = last_json_value(raw, list)
    if not isinstance(arr, list):
        _abort_if_infra(raw)
        return []

    by_id = {}
    for obj in arr:
        if isinstance(obj, dict) and obj.get("post_id") is not None:
            try:
                by_id[int(obj["post_id"])] = obj
            except (TypeError, ValueError):
                continue
    want = {int(p["id"]) for p in posts}
    # INTEGRITY GATE: exact id-set match or the whole batch is thrown away.
    if set(by_id) != want:
        return []
    return [_merge(p, by_id[int(p["id"])]) for p in posts]


def process_batch(posts: list[dict]) -> tuple[list[dict], int]:
    """Batch first; on gate failure fall back to per-post. Returns (recs, n_fellback)."""
    recs = extract_batch(posts)
    if recs:
        return recs, 0
    out = []
    for p in posts:
        try:
            out.append(extract_one(p))
        except InfraFailure:
            if out:
                return out, len(posts)
            raise
    return out, len(posts)


def _write(recs: list[dict]) -> None:
    with LOCK, OUT.open("a") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")


# ---------------------------------------------------------------------------
# comparison harnesses
# ---------------------------------------------------------------------------

KEYS = ("instrument", "call_type", "direction", "is_forecast")


def _compare(stored: dict, fresh: dict[int, dict], label: str) -> None:
    agree = dict.fromkeys(KEYS, 0)
    lvl = 0
    for pid, new in fresh.items():
        old = stored[pid]
        for k in KEYS:
            if str(old.get(k)).strip().upper() == str(new.get(k)).strip().upper():
                agree[k] += 1
        if (old.get("invalidation") == new.get("invalidation")
                and (old.get("targets") or []) == (new.get("targets") or [])):
            lvl += 1
    n = len(fresh)
    print(f"\n{label}  (n={n})")
    for k in KEYS:
        print(f"  {k:14} {agree[k]:3d}/{n} = {agree[k]/n:.0%}")
    print(f"  {'levels':14} {lvl:3d}/{n} = {lvl/n:.0%}")


def _sample_done(df: pd.DataFrame, done: dict, n: int) -> list[dict]:
    have = [r for r in df.to_dict("records")
            if int(r["id"]) in done and "error" not in done[int(r["id"])]]
    return pd.DataFrame(have).sample(min(n, len(have)), random_state=7).to_dict("records")


def run_verify(df, done, n, batch) -> None:
    """Batched re-extraction vs the stored single-post rows."""
    posts = _sample_done(df, done, n)
    print(f"verify: re-extracting {len(posts)} posts with engine={ENGINE.name} "
          f"in batches of {batch}", flush=True)
    fresh = {}
    for i in range(0, len(posts), batch):
        try:
            for rec in extract_batch(posts[i:i + batch]):
                fresh[rec["post_id"]] = rec
        except InfraFailure as e:
            print(f"aborted: {e}", file=sys.stderr)
            break
    if not fresh:
        print("no batch results — batching may be broken", file=sys.stderr)
        sys.exit(2)
    _compare(done, fresh, f"batched({ENGINE.name}) vs stored single-post")


def _batched_pass(posts, batch) -> dict[int, dict]:
    out = {}
    for i in range(0, len(posts), batch):
        try:
            for rec in extract_batch(posts[i:i + batch]):
                out[rec["post_id"]] = rec
        except InfraFailure as e:
            print(f"aborted: {e}", file=sys.stderr)
            break
    return out


def run_selftest(df, done, n, batch) -> None:
    """PROMPT AMBIGUITY: run the same posts twice with the CURRENT prompt and compare
    the two fresh runs to each other.

    Comparing a new prompt against stored rows only measures 'did the answers change',
    which a deliberate rule change is supposed to do. Self-consistency isolates the
    thing we actually want: how often the prompt's rules force a coin-flip. Higher is
    a less ambiguous rule."""
    posts = _sample_done(df, done, n)
    print(f"selftest: two independent passes over {len(posts)} posts, "
          f"engine={ENGINE.name}, batch={batch}", flush=True)
    a = _batched_pass(posts, batch)
    b = _batched_pass(posts, batch)
    common = {pid: b[pid] for pid in b if pid in a}
    if not common:
        print("no overlapping results", file=sys.stderr)
        sys.exit(2)
    _compare(a, common, f"run1 vs run2 ({ENGINE.name}, batch={batch})  [PROMPT SELF-CONSISTENCY]")


def run_control(df, done, n, workers) -> None:
    """NOISE FLOOR: re-extract the same posts ONE AT A TIME with the same engine and
    compare to the stored single-post rows. Any disagreement here is pure run-to-run
    instability — it is the yardstick that makes the batched numbers interpretable.
    Without it, baseline extractor noise looks like damage caused by batching."""
    posts = _sample_done(df, done, n)
    print(f"control: re-extracting {len(posts)} posts SINGLY with engine={ENGINE.name}",
          flush=True)
    fresh = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(extract_one, p): p for p in posts}
        for fut in as_completed(futs):
            try:
                rec = fut.result()
            except InfraFailure as e:
                print(f"aborted: {e}", file=sys.stderr)
                break
            if "error" not in rec:
                fresh[rec["post_id"]] = rec
    if not fresh:
        print("no control results", file=sys.stderr)
        sys.exit(2)
    _compare(done, fresh, f"single({ENGINE.name}) vs stored single-post  [NOISE FLOOR]")


# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="claude", choices=["claude", "codex"])
    ap.add_argument("--model", default=None, help="engine-specific model override")
    ap.add_argument("--pilot", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--batch", type=int, default=20, help="posts per call (1 = no batching)")
    ap.add_argument("--verify", type=int, default=0,
                    help="re-extract N done posts in BATCH mode; compare; write nothing")
    ap.add_argument("--control", type=int, default=0,
                    help="re-extract N done posts SINGLY; compare; write nothing "
                         "(establishes the run-to-run noise floor)")
    ap.add_argument("--selftest", type=int, default=0,
                    help="run the SAME N posts twice with the current prompt and compare "
                         "the two fresh runs — measures how ambiguous the prompt's rules "
                         "are, independent of any stored data. Writes nothing.")
    ap.add_argument("--prompt", default=None,
                    help="alternate prompt file (default: extract_prompt.md)")
    args = ap.parse_args()

    global PROMPT
    if args.prompt:
        PROMPT = Path(args.prompt).read_text()

    global ENGINE
    ENGINE = get_engine(args.engine, args.model)
    if args.engine == "codex":
        write_schema()

    df = pd.read_parquet(HERE / "data" / "ewf_posts.parquet")
    done: dict[int, dict] = {}
    if OUT.exists():
        with OUT.open() as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    done[int(r["post_id"])] = r

    if args.verify:
        return run_verify(df, done, args.verify, max(1, args.batch))
    if args.control:
        return run_control(df, done, args.control, args.workers)
    if args.selftest:
        return run_selftest(df, done, args.selftest, max(1, args.batch))

    if args.pilot:
        nyears = df.date_gmt.dt.year.nunique()
        df = (df.assign(year=df.date_gmt.dt.year)
              .groupby("year", group_keys=False)
              .apply(lambda g: g.sample(min(len(g), max(1, args.pilot // nyears + 1)),
                                        random_state=11), include_groups=False)
              .head(args.pilot))

    todo = [r for r in df.to_dict("records") if int(r["id"]) not in done]
    bs = max(1, args.batch)
    batches = [todo[i:i + bs] for i in range(0, len(todo), bs)]
    print(f"{len(todo)} posts to extract ({len(done)} already done) in "
          f"{len(batches)} batches of {bs}, engine={ENGINE.name}", flush=True)

    n = fell = 0
    infra_msg = None
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(process_batch, b) for b in batches]
        for fut in as_completed(futures):
            try:
                recs, nf = fut.result()
            except InfraFailure as e:
                infra_msg = infra_msg or str(e)
                continue
            _write(recs)
            n += len(recs)
            fell += nf
            print(f"{n}/{len(todo)} extracted"
                  + (f" ({fell} via per-post fallback)" if fell else ""), flush=True)

    if infra_msg:
        print(f"\nABORTED after {n} extractions — infrastructure failure, not a data result:\n"
              f"  {infra_msg[:300]}\n"
              f"Re-running this command resumes cleanly once the cause is fixed.",
              file=sys.stderr, flush=True)
        sys.exit(2)
    print("done", flush=True)


if __name__ == "__main__":
    main()
