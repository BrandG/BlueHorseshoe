"""Batch-extraction integrity tests.

The whole risk of batching is cross-contamination: one post's instrument or levels
landing in another post's row. The gate is that returned post_ids must match the batch
EXACTLY — anything else discards the batch and falls back to per-post extraction.
These tests pin that behaviour; they never hit the network.

Run:  ./run.sh pytest research/ewf_call_scoring_v1/test_extract_batch.py -v
"""
import pytest

import extract_calls as E
import engines

POSTS = [
    {"id": 1, "date_gmt": "2020-01-01", "title": "A", "content_text": "x"},
    {"id": 2, "date_gmt": "2020-01-02", "title": "B", "content_text": "y"},
]


@pytest.fixture(autouse=True)
def _clear_abort():
    engines.ABORT.clear()
    E.ENGINE = _StubEngine()
    yield
    engines.ABORT.clear()


class _StubEngine:
    name = "stub"
    reply = ""
    def run(self, text, timeout=0, schema=None):
        return self.reply


def _stub(monkeypatch, raw):
    eng = _StubEngine()
    eng.reply = raw
    monkeypatch.setattr(E, "ENGINE", eng)


@pytest.mark.parametrize("label,raw", [
    ("dropped post", '[{"post_id":1,"instrument":"AAPL"}]'),
    ("hallucinated id", '[{"post_id":1},{"post_id":99}]'),
    ("duplicate id", '[{"post_id":1},{"post_id":1}]'),
    ("missing post_id", '[{"instrument":"AAPL"},{"instrument":"TSLA"}]'),
    ("single object not array", '{"post_id":1,"instrument":"AAPL"}'),
    ("prose refusal", "sorry I cannot help with that"),
    ("truncated json", '[{"post_id":1,"instrument":"AAP'),
])
def test_bad_batches_are_rejected(monkeypatch, label, raw):
    """Any id mismatch must discard the WHOLE batch — never guess alignment."""
    _stub(monkeypatch, raw)
    assert E.extract_batch(POSTS) == [], label


def test_exact_match_accepted(monkeypatch):
    _stub(monkeypatch, '[{"post_id":1,"instrument":"AAPL","direction":"long"},'
                       ' {"post_id":2,"instrument":"TSLA","direction":"short"}]')
    recs = E.extract_batch(POSTS)
    assert [r["post_id"] for r in recs] == [1, 2]
    assert recs[0]["instrument"] == "AAPL" and recs[1]["instrument"] == "TSLA"
    # metadata comes from OUR record, never from the model
    assert recs[0]["title"] == "A" and recs[0]["date_gmt"] == "2020-01-01"


def test_out_of_order_realigns_by_id(monkeypatch):
    """Model may return objects in any order; alignment is by echoed id, not position."""
    _stub(monkeypatch, '[{"post_id":2,"instrument":"TSLA"},{"post_id":1,"instrument":"AAPL"}]')
    recs = E.extract_batch(POSTS)
    assert [(r["post_id"], r["instrument"]) for r in recs] == [(1, "AAPL"), (2, "TSLA")]


def test_string_ids_accepted(monkeypatch):
    """Models often quote numbers; coerce rather than reject."""
    _stub(monkeypatch, '[{"post_id":"1","instrument":"AAPL"},{"post_id":"2","instrument":"TSLA"}]')
    assert len(E.extract_batch(POSTS)) == 2


def test_fences_and_prose_tolerated(monkeypatch):
    _stub(monkeypatch, 'Here you go:\n```json\n[{"post_id":1},{"post_id":2}]\n```\nDone.')
    assert len(E.extract_batch(POSTS)) == 2


def test_infra_failure_propagates(monkeypatch):
    """A spend/rate limit inside a batch must raise, not return an empty batch —
    otherwise process_batch would 'fall back' and burn per-post calls into the wall."""
    class Boom:
        name = "stub"
        def run(self, text, timeout=0, schema=None):
            raise E.InfraFailure("monthly spend limit")
    monkeypatch.setattr(E, "ENGINE", Boom())
    with pytest.raises(E.InfraFailure):
        E.extract_batch(POSTS)
    with pytest.raises(E.InfraFailure):
        E.process_batch(POSTS)


def test_fallback_runs_per_post_when_batch_fails(monkeypatch):
    """Batch rejected -> every post still gets extracted individually."""
    monkeypatch.setattr(E, "extract_batch", lambda posts: [])
    monkeypatch.setattr(E, "extract_one",
                        lambda p: {"post_id": int(p["id"]), "instrument": "X"})
    recs, n_fell = E.process_batch(POSTS)
    assert [r["post_id"] for r in recs] == [1, 2]
    assert n_fell == 2


def test_model_cannot_inject_metadata(monkeypatch):
    """A model echoing its own date/title must not overwrite archive truth."""
    _stub(monkeypatch, '[{"post_id":1,"date_gmt":"1999-01-01","title":"HACKED"},'
                       ' {"post_id":2}]')
    recs = E.extract_batch(POSTS)
    assert recs[0]["date_gmt"] == "2020-01-01"
    assert recs[0]["title"] == "A"


# --- false-positive guards on the infra detector ---------------------------------
# Market prose is full of numbers and hedged words. An infra marker that can appear in
# a post would abort a multi-hour run and look like a billing outage. Caught in the
# wild 2026-07-30: codex echoes the prompt (post text included) to stderr.

@pytest.mark.parametrize("text", [
    "SPX target 429.50, invalidation 503.20",
    "wave ((iii)) ended at 4290; support 5030",
    "insufficient momentum to clear the 429 pivot",
    "the rally stalled — quota of buyers exhausted near 503",
    "Elliott Wave count suggests a limit at 429",
])
def test_market_prose_is_not_an_infra_failure(text):
    assert not engines.is_infra_failure(text)


@pytest.mark.parametrize("text", [
    "You've hit your monthly spend limit",
    "API Error: rate limit exceeded",
    "Credit balance is too low",
    "quota exceeded for this org",
    "HTTP 429 Too Many Requests",
    "Please run /login to authenticate",
])
def test_real_infra_messages_still_detected(text):
    assert engines.is_infra_failure(text)


def test_success_stderr_is_never_scanned():
    """rc==0 with post text echoed to stderr must NOT abort (the codex banner case)."""
    engines.ABORT.clear()
    noisy = "banner\nuser\nSPX target 429.50 with invalidation 503.20\n"
    assert engines._guard('{"calls":[]}', noisy, 0) == '{"calls":[]}'
    assert not engines.ABORT.is_set()


def test_failed_process_stderr_is_scanned():
    engines.ABORT.clear()
    with pytest.raises(engines.InfraFailure):
        engines._guard("", "You've hit your monthly spend limit", 1)
    engines.ABORT.clear()


def test_unparseable_billing_response_aborts(monkeypatch):
    """The original poisoning case: rc==0 but the body IS the billing message."""
    engines.ABORT.clear()
    _stub(monkeypatch, "You've hit your monthly spend limit · raise it at claude.ai")
    with pytest.raises(E.InfraFailure):
        E.extract_batch(POSTS)
    engines.ABORT.clear()


# --- JSON extraction from noisy engine output ------------------------------------

@pytest.mark.parametrize("raw,want,expect", [
    # THE REGRESSION: wrapper object must win over its own last child.
    ('{"calls":[{"post_id":1},{"post_id":2}]}', dict, {"calls": [{"post_id": 1}, {"post_id": 2}]}),
    ('banner\n{"calls":[{"post_id":9,"instrument":"SIL"}]}\ntokens used\n4,375',
     dict, {"calls": [{"post_id": 9, "instrument": "SIL"}]}),
    # codex prints the final message twice -> last top-level wins
    ('{"calls":[{"post_id":1}]}\nx\n{"calls":[{"post_id":2}]}',
     dict, {"calls": [{"post_id": 2}]}),
    ('```json\n[{"a":1},{"b":2}]\n```', list, [{"a": 1}, {"b": 2}]),
    ('prose {"not":"it"} then [{"post_id":7}]', list, [{"post_id": 7}]),
    ('text [brackets] then [{"s":"a[b]c"}]', list, [{"s": "a[b]c"}]),
    ('[{"s":"has \\" quote and ] bracket"}]', list, [{"s": 'has " quote and ] bracket'}]),
    ('no json here', list, None),
    ('truncated [{"a":1', list, None),
])
def test_last_top_level_json(raw, want, expect):
    assert engines.last_json_value(raw, want) == expect


def test_nested_child_never_shadows_parent():
    """Explicit guard: the last `{` in the string is a CHILD; it must not be returned."""
    raw = '{"calls":[{"post_id":1,"instrument":"A"},{"post_id":2,"instrument":"B"}]}'
    got = engines.last_json_value(raw, dict)
    assert "calls" in got and len(got["calls"]) == 2


def test_batch_accepts_wrapper_object(monkeypatch):
    """extract_batch must read the {"calls": [...]} shape codex returns under schema."""
    _stub(monkeypatch, '{"calls":[{"post_id":1,"instrument":"AAPL"},'
                       '{"post_id":2,"instrument":"TSLA"}]}')
    recs = E.extract_batch(POSTS)
    assert [(r["post_id"], r["instrument"]) for r in recs] == [(1, "AAPL"), (2, "TSLA")]
