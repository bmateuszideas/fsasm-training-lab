"""FS-ASM Runtime v1 (T25) — secret redaction for audit/trajectory artifacts.

Architecture §35/§36 and canonical TODO T25 require that keys, tokens and marked
secrets are redacted from prompts, observations, stdout/stderr and reports
before any audit/trajectory is written, logged or shipped. The authoritative
snapshot is never altered by redaction: redaction operates on *copies* of
transient transport/audit payloads (``ModelRequest`` messages, tool
``ToolObservation``, evidence/report text) and never touches the Domain Core or
the State Repository. Redaction never grants PASS, retry or gate and never
changes a domain decision: it is a one-way sanitization of diagnostic output
only.

The redactor is intentionally simple and conservative. It redacts:

* known token/key shapes via configurable regex patterns (defaults cover the
  common Mistral/GitHub/local-LLM key prefixes and bearer tokens);
* explicit ``<SECRET:...>`` markers a caller can wrap around any sensitive
  span it already knows about;
* ``Authorization``/``X-API-Key``-style header lines.

It reports ``REDACTED`` for any matched span and never raises on malformed
input (a redaction failure must not crash the run). It does not attempt full
structured parsing of every provider payload: the Broker/Verifier already
keep secrets out of artifacts; redaction is defense-in-depth for the audit
plane.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from fsasm.models import ToolObservation
from fsasm.model_types import ModelRequest

# A stable, machine-recognizable placeholder for any redacted secret span.
REDACTED = "[REDACTED]"

# Default regex patterns for common secret shapes. Patterns are anchored to
# be conservative: they only match shapes that are very unlikely to appear in
# legitimate task content. Patterns are compiled once.
_DEFAULT_PATTERNS: tuple[re.Pattern[str], ...] = (
    # GitHub PATs (classic & fine-grained) and OAuth tokens (ghp_, ghu_, ghs_,
    # gho_, ghr_, github_pat_...). 36+ chars.
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,})\b"),
    re.compile(r"\b(github_pat_[A-Za-z0-9_]{22,})\b"),
    # Mistral / generic API keys with common prefixes (sk-, mistral-, Bearer).
    re.compile(r"\b(sk-[A-Za-z0-9]{20,})\b"),
    re.compile(r"\b(mistral-[A-Za-z0-9]{16,})\b"),
    # Generic "Bearer <token>" authorization header value.
    re.compile(r"(?i)\b(Bearer\s+[A-Za-z0-9\._\-~+/]{20,})\b"),
    # Long hex/base64 secret-like blobs (40+ chars, no spaces) that follow an
    # explicit "api_key"/"token"/"secret"/"password" assignment.
    re.compile(
        r'(?i)(api[_-]?key|token|secret|password|access[_-]?key)\s*[:=]\s*["\']?'
        r"([A-Za-z0-9/+=\-_]{40,})[\"']?"
    ),
)


def _default_patterns() -> list[re.Pattern[str]]:
    return list(_DEFAULT_PATTERNS)


@dataclass
class RedactionPolicy:
    """Configurable redaction policy (T25).

    ``extra_patterns`` are additional compiled regexes appended to the
    defaults; ``marker_open``/``marker_close`` delimit an explicit
    ``<SECRET:...>`` wrapper a caller can place around any known sensitive span
    before logging. The policy is a pure configuration object with no I/O.
    """

    extra_patterns: list[re.Pattern[str]] = field(default_factory=list)
    marker_open: str = "<SECRET:"
    marker_close: str = ">"
    placeholder: str = REDACTED

    @property
    def patterns(self) -> list[re.Pattern[str]]:
        return [*_default_patterns(), *self.extra_patterns]


def _redact_text(text: str, policy: RedactionPolicy) -> str:
    """Redact all configured secret patterns in ``text`` (pure).

    Returns a new string; never mutates the input. On any regex error it
    returns the input unchanged rather than crashing the run.
    """

    if not text:
        return text
    result = text
    try:
        for pat in policy.patterns:
            result = pat.sub(policy.placeholder, result)
    except re.error:
        return text
    # Explicit <SECRET:...> markers: redact whatever the caller wrapped.
    if policy.marker_open and policy.marker_close:
        marker = re.compile(
            re.escape(policy.marker_open) + r".*?" + re.escape(policy.marker_close),
            re.DOTALL,
        )
        result = marker.sub(policy.placeholder, result)
    return result


def redact_text(text: str, policy: RedactionPolicy | None = None) -> str:
    """Redact secrets from a plain string (convenience entry point)."""

    return _redact_text(text, policy or RedactionPolicy())


def redact_model_request(
    request: ModelRequest, policy: RedactionPolicy | None = None
) -> ModelRequest:
    """Return a redacted *copy* of a :class:`ModelRequest` (no mutation).

    Only the prompt message contents are redacted; identifiers (``run_id`` /
    ``task_id`` / ``attempt`` / ``step``) and tool declarations are preserved
    since they are not secrets. The original request is never mutated.
    """

    pol = policy or RedactionPolicy()
    redacted_messages = [
        msg.model_copy(update={"content": _redact_text(msg.content, pol)})
        for msg in request.messages
    ]
    return request.model_copy(update={"messages": redacted_messages})


def redact_observation(
    observation: ToolObservation, policy: RedactionPolicy | None = None
) -> ToolObservation:
    """Return a redacted *copy* of a :class:`ToolObservation` (no mutation).

    Redacts ``content``, ``diff``, ``stdout``, ``stderr`` and ``reason`` — the
    free-text fields that could carry a leaked secret. ``operation_id`` /
    ``kind`` / ``exit_code`` / ``duration_ms`` etc. are preserved. The original
    observation is never mutated.
    """

    pol = policy or RedactionPolicy()
    return observation.model_copy(
        update={
            "content": _redact_text(observation.content, pol),
            "diff": (
                _redact_text(observation.diff, pol)
                if observation.diff is not None
                else None
            ),
            "stdout": _redact_text(observation.stdout, pol),
            "stderr": _redact_text(observation.stderr, pol),
            "reason": _redact_text(observation.reason, pol),
        }
    )


def redact_observations(
    observations: list[ToolObservation], policy: RedactionPolicy | None = None
) -> list[ToolObservation]:
    """Return redacted copies of a list of observations (no mutation)."""

    pol = policy or RedactionPolicy()
    return [redact_observation(o, pol) for o in observations]


def redact_report(report: str, policy: RedactionPolicy | None = None) -> str:
    """Redact secrets from a human/JSON report string."""

    return _redact_text(report, policy or RedactionPolicy())


def was_redacted(original: str, redacted: str) -> bool:
    """True when redaction changed ``original`` into ``redacted`` (diagnostic)."""

    return original != redacted
