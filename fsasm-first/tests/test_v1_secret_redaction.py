"""T25 — secret redaction over prompts, observations, stdout/stderr, reports.

Architecture §35/§36 + canonical TODO T25: keys, tokens and marked secrets are
redacted from prompts, observations, stdout/stderr and reports. Redaction is
a one-way sanitization of *diagnostic* output only — it never touches the
authoritative snapshot, never grants PASS/retry/gate and never changes a
domain decision. The original objects are never mutated.
"""

from __future__ import annotations

import re

from fsasm.models import ToolObservation, ToolOperationKind
from fsasm.model_types import ModelMessage, ModelMessageRole, ModelRequest
from fsasm.redaction import (
    REDACTED,
    RedactionPolicy,
    redact_model_request,
    redact_observation,
    redact_observations,
    redact_report,
    redact_text,
    was_redacted,
)


def _obs(
    *,
    content: str = "",
    diff: str | None = None,
    stdout: str = "",
    stderr: str = "",
    reason: str = "",
) -> ToolObservation:
    return ToolObservation(
        operation_id="op-1",
        kind=ToolOperationKind.RUN_CHECKS,
        ok=True,
        content=content,
        diff=diff,
        stdout=stdout,
        stderr=stderr,
        reason=reason,
        exit_code=0,
    )


def _req(content: str) -> ModelRequest:
    return ModelRequest(
        run_id="RUN-1",
        task_id="TASK-001",
        attempt=1,
        step=1,
        messages=[
            ModelMessage(role=ModelMessageRole.SYSTEM, content="be safe"),
            ModelMessage(role=ModelMessageRole.USER, content=content),
        ],
    )


class TestRedactTextDefaultPatterns:
    def test_github_pat_redacted(self):
        token = "ghp_" + "a" * 36
        out = redact_text(f"key={token}")
        assert token not in out
        assert REDACTED in out

    def test_github_fine_grained_pat_redacted(self):
        token = "github_pat_" + "b" * 22
        out = redact_text(f"token: {token}")
        assert token not in out

    def test_sk_key_redacted(self):
        key = "sk-" + "c" * 22
        out = redact_text(f"use {key} now")
        assert key not in out

    def test_mistral_key_redacted(self):
        key = "mistral-" + "d" * 20
        out = redact_text(f"auth {key}")
        assert key not in out

    def test_bearer_token_redacted(self):
        out = redact_text("Authorization: Bearer " + "e" * 30)
        assert "Bearer" not in out
        assert REDACTED in out

    def test_api_key_assignment_redacted(self):
        secret = "f" * 50
        out = redact_text(f'api_key="{secret}"')
        assert secret not in out

    def test_password_assignment_redacted(self):
        secret = "0" * 45
        out = redact_text(f"password={secret}")
        assert secret not in out

    def test_non_secret_text_unchanged(self):
        text = "patch file.py to add a function with 42 lines"
        assert redact_text(text) == text

    def test_empty_string_unchanged(self):
        assert redact_text("") == ""


class TestSecretMarker:
    def test_marker_wraps_arbitrary_span(self):
        out = redact_text("config has <SECRET:my-private-value> inside")
        assert "my-private-value" not in out
        assert REDACTED in out

    def test_marker_multiline(self):
        out = redact_text("pre <SECRET:line1\nline2> post")
        assert "line1" not in out
        assert "line2" not in out

    def test_custom_marker_delimiters(self):
        pol = RedactionPolicy(marker_open="[[", marker_close="]]")
        out = redact_text("v [[secret-thing]] w", pol)
        assert "secret-thing" not in out


class TestCustomExtraPattern:
    def test_extra_pattern_redacts_custom_secret(self):
        pol = RedactionPolicy(extra_patterns=[re.compile(r"CUSTOM-SECRET-\d+")])
        out = redact_text("id=CUSTOM-SECRET-999 here", pol)
        assert "CUSTOM-SECRET-999" not in out


class TestRedactModelRequestNoMutation:
    def test_prompt_secret_redacted(self):
        key = "sk-" + "g" * 22
        req = _req(f"the key is {key}")
        redacted = redact_model_request(req)
        assert key not in redacted.messages[1].content
        assert REDACTED in redacted.messages[1].content

    def test_original_not_mutated(self):
        key = "sk-" + "g" * 22
        original_content = f"the key is {key}"
        req = _req(original_content)
        redact_model_request(req)
        assert req.messages[1].content == original_content

    def test_identifiers_preserved(self):
        key = "sk-" + "g" * 22
        req = _req(f"key {key}")
        redacted = redact_model_request(req)
        assert redacted.run_id == "RUN-1"
        assert redacted.task_id == "TASK-001"
        assert redacted.attempt == 1
        assert redacted.step == 1

    def test_system_message_also_redacted(self):
        req = ModelRequest(
            run_id="R",
            task_id="T",
            attempt=1,
            step=1,
            messages=[
                ModelMessage(
                    role=ModelMessageRole.SYSTEM, content="Bearer " + "h" * 30
                ),
                ModelMessage(role=ModelMessageRole.USER, content="ok"),
            ],
        )
        redacted = redact_model_request(req)
        assert "Bearer" not in redacted.messages[0].content


class TestRedactObservationNoMutation:
    def test_stdout_redacted(self):
        secret = "ghp_" + "a" * 36
        obs = _obs(stdout=f"export TOKEN={secret}")
        redacted = redact_observation(obs)
        assert secret not in redacted.stdout
        assert REDACTED in redacted.stdout

    def test_stderr_redacted(self):
        secret = "sk-" + "c" * 22
        obs = _obs(stderr=f"error: bad key {secret}")
        redacted = redact_observation(obs)
        assert secret not in redacted.stderr

    def test_content_redacted(self):
        secret = "mistral-" + "d" * 20
        obs = _obs(content=f"read {secret}")
        redacted = redact_observation(obs)
        assert secret not in redacted.content

    def test_diff_redacted(self):
        secret = "ghp_" + "a" * 36
        obs = _obs(diff=f"+API_KEY={secret}")
        redacted = redact_observation(obs)
        assert redacted.diff is not None
        assert secret not in redacted.diff

    def test_reason_redacted(self):
        secret = "sk-" + "c" * 22
        obs = _obs(reason=f"blocked: leaked {secret}")
        redacted = redact_observation(obs)
        assert secret not in redacted.reason

    def test_non_secret_observation_unchanged(self):
        obs = _obs(content="all good", stdout="ok", stderr="")
        redacted = redact_observation(obs)
        assert redacted.content == "all good"
        assert redacted.stdout == "ok"

    def test_operation_id_preserved(self):
        obs = _obs(content="sk-" + "c" * 22)
        redacted = redact_observation(obs)
        assert redacted.operation_id == "op-1"
        assert redacted.kind == ToolOperationKind.RUN_CHECKS
        assert redacted.exit_code == 0

    def test_original_not_mutated(self):
        secret = "sk-" + "c" * 22
        obs = _obs(content=f"key {secret}")
        redact_observation(obs)
        assert secret in obs.content


class TestRedactObservationsList:
    def test_list_all_redacted(self):
        s1 = "ghp_" + "a" * 36
        s2 = "sk-" + "c" * 22
        obs_list = [_obs(content=s1), _obs(stdout=s2)]
        redacted = redact_observations(obs_list)
        assert s1 not in redacted[0].content
        assert s2 not in redacted[1].stdout


class TestRedactReport:
    def test_report_secret_redacted(self):
        secret = "ghp_" + "a" * 36
        report = f'{{"status": "PASSED", "note": "key {secret}"}}'
        out = redact_report(report)
        assert secret not in out
        assert REDACTED in out


class TestWasRedactedDiagnostic:
    def test_detects_change(self):
        assert was_redacted("sk-" + "c" * 22, REDACTED) is True

    def test_detects_no_change(self):
        assert was_redacted("plain", "plain") is False
