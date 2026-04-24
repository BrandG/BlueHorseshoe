"""Logging filter that redacts OANDA tokens and FTMO/OANDA account IDs.

Per BH FTMO plan decision C-2: a single log line that leaks a personal-access
token is a production incident. The filter is attached once at process start
via :func:`install` and protects every downstream handler.

Strategy (belt + suspenders):
  1. **Exact-secret match** — secrets pulled from env/.env at filter construction
     time are matched literally and replaced. Zero false negatives for known
     values, zero false positives for lookalikes.
  2. **Pattern match** — regexes catch OANDA-shaped tokens and account-ID
     strings even if the exact value wasn't known at install time (e.g., a
     token rotation that environment reload missed).

The filter scrubs ``record.msg``, ``record.args``, and ``record.exc_text``.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Iterable, Optional, Pattern

REPO_ROOT = Path(__file__).resolve().parents[3]
REDACTION = "[REDACTED]"

# OANDA personal-access tokens: 32 hex + dash + 32 hex.
_OANDA_TOKEN_PATTERN = re.compile(r"\b[a-fA-F0-9]{32}-[a-fA-F0-9]{32}\b")
# OANDA / FTMO account IDs: NNN-NNN-NNNNNNNN-NNN (digit counts vary 6-9 in the middle).
_ACCOUNT_ID_PATTERN = re.compile(r"\b\d{3}-\d{3}-\d{6,9}-\d{3}\b")

DEFAULT_PATTERNS: tuple[Pattern[str], ...] = (_OANDA_TOKEN_PATTERN, _ACCOUNT_ID_PATTERN)
DEFAULT_ENV_VARS: tuple[str, ...] = (
    "OANDA_API_TOKEN",
    "OANDA_ACCOUNT_ID",
    "FTMO_ACCOUNT_ID",
)


class SecretScrubber(logging.Filter):
    """Redacts known secrets and secret-shaped patterns from every log record."""

    def __init__(
        self,
        secrets: Optional[Iterable[str]] = None,
        patterns: Optional[Iterable[Pattern[str]]] = None,
    ) -> None:
        super().__init__()
        # Longest-first so a token that embeds an account-id-shaped substring
        # isn't half-replaced.
        self._exact_secrets: list[str] = sorted(
            {s for s in (secrets or ()) if s and len(s) >= 4},
            key=len,
            reverse=True,
        )
        self._patterns: list[Pattern[str]] = list(patterns) if patterns is not None else list(DEFAULT_PATTERNS)

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 — logging API
        try:
            formatted = record.getMessage()
        except Exception:  # noqa: BLE001
            formatted = str(record.msg)
        scrubbed = self._scrub(formatted)
        if scrubbed != formatted:
            record.msg = scrubbed
            record.args = ()
        if record.exc_text:
            record.exc_text = self._scrub(record.exc_text)
        return True

    def _scrub(self, text: str) -> str:
        for secret in self._exact_secrets:
            if secret in text:
                text = text.replace(secret, REDACTION)
        for pattern in self._patterns:
            text = pattern.sub(REDACTION, text)
        return text


def secrets_from_env(
    env_vars: Iterable[str] = DEFAULT_ENV_VARS,
    *,
    env_path: Optional[Path] = None,
) -> list[str]:
    """Read secret values from process env, falling back to ``.env`` at repo root.

    Returns only non-empty values. Order matches ``env_vars``.
    """
    env_vars = tuple(env_vars)
    values: dict[str, str] = {}
    for k in env_vars:
        v = os.environ.get(k)
        if v:
            values[k] = v

    missing = [k for k in env_vars if k not in values]
    if missing:
        path = env_path if env_path is not None else REPO_ROOT / ".env"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k in missing and k not in values and v:
                    values[k] = v

    return [values[k] for k in env_vars if k in values]


def install(
    logger: Optional[logging.Logger] = None,
    *,
    secrets: Optional[Iterable[str]] = None,
    patterns: Optional[Iterable[Pattern[str]]] = None,
    load_env: bool = True,
) -> SecretScrubber:
    """Attach a :class:`SecretScrubber` to ``logger`` (defaults to the root logger).

    Also attaches the filter to every existing handler on the logger. Handlers
    added *after* install do not inherit the filter automatically — call
    ``handler.addFilter(scrubber)`` or re-install.
    """
    target = logger if logger is not None else logging.getLogger()
    resolved_secrets: list[str] = list(secrets) if secrets is not None else []
    if load_env:
        resolved_secrets.extend(secrets_from_env())
    scrubber = SecretScrubber(secrets=resolved_secrets, patterns=patterns)
    target.addFilter(scrubber)
    for handler in target.handlers:
        handler.addFilter(scrubber)
    return scrubber
