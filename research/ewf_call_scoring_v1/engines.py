"""LLM engines for blind call extraction: headless `claude -p` or `codex exec`.

Why two engines
---------------
`claude -p` boots a full Claude Code session per invocation (~25k tokens of scaffolding,
~18k of it cache-creation billed at 2x and discarded on exit). Measured 2026-07-30: a
9-token prompt cost $0.0399 and took ~40s. It also draws on the Anthropic monthly spend
limit, which this study exhausted twice.

`codex exec` measured ~9.5k tokens and ~11s for the same trivial prompt, authenticates
against a ChatGPT subscription (a SEPARATE budget), and supports `--output-schema`, which
enforces the response shape at the API level instead of hoping the model emits clean JSON.

Both engines are driven through the same `run(text, timeout, schema)` interface so the
extractor logic, integrity gates, and infra-abort behaviour are identical either way.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
from pathlib import Path

BARE_CWD = Path("/root/.claude/jobs/cda3d028/tmp/bare")

# Infrastructure failures are NOT data — see extract_calls.py header.
#
# EVERY marker here must be a phrase that CANNOT occur in market prose. Bare HTTP codes
# ("429", "503") and bare words ("quota", "insufficient") are forbidden: EWF posts are
# wall-to-wall price levels and hedged language, so "target 429.50" or "insufficient
# momentum" would masquerade as a billing failure and abort a multi-hour run.
# (Caught 2026-07-30 when codex echoed the prompt — including post text — to stderr.)
INFRA_MARKERS = (
    "monthly spend limit", "usage limit", "rate limit", "credit balance",
    "authentication_error", "invalid api key", "overloaded_error",
    "quota exceeded", "insufficient credit", "insufficient_quota",
    "please run /login", "not logged in", "http 429", "http 503",
    "status 429", "status 503", "error 429", "error 503",
)

ABORT = threading.Event()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class InfraFailure(RuntimeError):
    """The engine never actually examined the input (billing/auth/transport)."""


def is_infra_failure(text: str) -> bool:
    t = (text or "").lower()
    return any(m in t for m in INFRA_MARKERS)


def _guard(raw: str, stderr: str, rc: int) -> str:
    """Decide infra-failure vs data, WITHOUT scanning model-visible content.

    stderr is only consulted when the process actually failed (rc != 0). On success,
    codex writes its banner and a full echo of the prompt — including post text — to
    stderr, so scanning it would classify market prose as a billing error.

    A rc==0 response that is merely unparseable is NOT judged here: the caller checks
    it with `is_infra_failure` only after JSON parsing fails, so a valid answer can
    never be mistaken for an outage.
    """
    if rc != 0:
        msg = (stderr or raw)[:500] or "empty-response"
        if is_infra_failure(msg):
            ABORT.set()
            raise InfraFailure(msg)
    return raw


class ClaudeEngine:
    name = "claude"
    model = "haiku"

    def run(self, text: str, timeout: int, schema: Path | None = None) -> str:
        if ABORT.is_set():
            raise InfraFailure("aborted")
        BARE_CWD.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            ["claude", "-p", "--model", self.model,
             "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}'],
            input=text, capture_output=True, text=True, timeout=timeout, cwd=BARE_CWD,
        )
        return _guard((r.stdout or "").strip(), r.stderr or "", r.returncode)


class CodexEngine:
    name = "codex"

    def __init__(self, model: str | None = None):
        self.model = model

    def run(self, text: str, timeout: int, schema: Path | None = None) -> str:
        if ABORT.is_set():
            raise InfraFailure("aborted")
        BARE_CWD.mkdir(parents=True, exist_ok=True)
        cmd = ["codex", "exec", "--ephemeral", "--skip-git-repo-check",
               "--ignore-user-config", "-s", "read-only", "-C", str(BARE_CWD),
               "--color", "never"]
        if self.model:
            cmd += ["-m", self.model]
        if schema is not None:
            cmd += ["--output-schema", str(schema)]
        r = subprocess.run(cmd, input=text, capture_output=True, text=True,
                           timeout=timeout, cwd=BARE_CWD)
        return _guard(_ANSI.sub("", (r.stdout or "").strip()), r.stderr or "", r.returncode)


def get_engine(name: str, model: str | None = None):
    if name == "claude":
        return ClaudeEngine()
    if name == "codex":
        return CodexEngine(model)
    raise ValueError(f"unknown engine {name!r}")


# ---------------------------------------------------------------------------
# response parsing
# ---------------------------------------------------------------------------

def last_json_value(raw: str, want: type = dict):
    """Return the last TOP-LEVEL JSON value of type `want` in `raw`, else None.

    Engines wrap the answer in banners, prompt echoes, and token counters, and codex
    prints its final message twice — so we want the LAST value, but only among
    *top-level* ones.

    Scanning backwards for the last opening brace is wrong: in `{"calls":[{...},{...}]}`
    the last `{` is the final element INSIDE the wrapper, which parses cleanly as a dict
    and silently shadows the wrapper. (That bug made every codex batch of >2 posts look
    like a parse failure.) Instead we walk forward with raw_decode, skipping past each
    value we consume, so nested structures are never mistaken for top-level ones.
    """
    dec = json.JSONDecoder()
    found = None
    i, n = 0, len(raw)
    while i < n:
        ch = raw[i]
        if ch not in "{[":
            i += 1
            continue
        try:
            val, end = dec.raw_decode(raw, i)
        except ValueError:
            i += 1
            continue
        if isinstance(val, want):
            found = val
        i = end  # skip the whole value: its children are not top-level
    return found
