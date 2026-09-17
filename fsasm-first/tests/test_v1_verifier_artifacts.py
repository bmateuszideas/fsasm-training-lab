"""T13 — Independent Verifier and Evidence Plane.

Proves the v1 Verifier reads the REAL artifact and a REAL run_checks
observation, never the Executor's claim, and binds the result to one attempt +
operation + artifact + check. A negative check, missing evidence, a stale
attempt, a foreign artifact or a "DONE" claim without effect all block PASS;
only a real patch + a passing check of the CURRENT attempt yields PASS, and
only the Domain Core grants the transition (architecture §29, §30; canonical
TODO T13; F8 protections preserved at the Domain Core boundary).
"""

import pathlib

import pytest

from fsasm.domain import (
    EvidenceAccepted,
    TaskActivated,
    TaskVerificationPassed,
    apply_event,
)
from fsasm.errors import InvalidTransitionError
from fsasm.models import (
    CheckKind,
    ChildTask,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationResultStatus,
    VerificationSpec,
    VerificationType,
    artifact_id_for,
    evidence_id_for,
    operation_id_for,
)
from fsasm.tool_broker import ToolBroker
from fsasm.verifier import ArtifactVerifier, VerifyRequest

RUN = "r"
TASK = "TASK-r-1"


def _running_state(run_id: str = RUN, task_id: str = TASK) -> RunState:
    """A RunState with one task RUNNING (attempt 1) for Domain Core tests."""
    task = ChildTask(
        task_id=task_id,
        sequence=1,
        title="t",
        description="d",
        status=TaskStatus.READY,
        verification=VerificationSpec(type=VerificationType.SCHEMA, expected="ok"),
        max_attempts=3,
    )
    plan = Plan(plan_id=f"plan-{run_id}", run_id=run_id, goal="g", tasks=[task])
    state = RunState(run_id=run_id, goal="g", status=RunStatus.RUNNING, plan=plan)
    return apply_event(state, TaskActivated(run_id=run_id, task_id=task_id))


@pytest.fixture()
def workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    # A helper check that asserts the artifact contains the expected effect;
    # exits 0 when the patched code is present, non-zero otherwise.
    (tmp_path / "assert_effect.py").write_text(
        "import sys\n"
        "content = open('calc.py').read()\n"
        "sys.exit(0 if 'return a - b' in content else 1)\n",
        encoding="utf-8",
    )
    return tmp_path


def _broker(root: pathlib.Path) -> ToolBroker:
    return ToolBroker(workspace_root=root, workspace_scope=[])


def _check_obs(
    run_id: str,
    task_id: str,
    attempt: int,
    step: int,
    broker: ToolBroker,
    *,
    kind: CheckKind = CheckKind.CUSTOM,
    args: list[str] | None = None,
) -> "object":
    return broker.run_checks(run_id, task_id, attempt, step, kind, args)


def _verify_request(
    run_id: str,
    task_id: str,
    attempt: int,
    artifact_path: str,
    patch_op_step: int,
    check_obs,
) -> VerifyRequest:
    patch_op = operation_id_for(run_id, task_id, attempt, patch_op_step)
    return VerifyRequest(
        run_id=run_id,
        task_id=task_id,
        attempt=attempt,
        artifact_path=artifact_path,
        patch_observation_id=patch_op,
        check_observation_id=check_obs.operation_id,
        check_observation=check_obs,
    )


class TestRealPatchAndCheckPass:
    """A real patch + a passing real check of the current attempt = PASS."""

    def test_real_patch_and_check_yields_pass(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        patch = broker.apply_patch(
            RUN,
            TASK,
            1,
            1,
            "calc.py",
            "def add(a, b):\n    return a - b\n",
            allowed_files=["calc.py"],
        )
        assert patch.ok
        check = broker.run_checks(
            RUN, TASK, 1, 2, CheckKind.CUSTOM, ["python", "assert_effect.py"]
        )
        assert check.ok and check.exit_code == 0
        verifier = ArtifactVerifier(
            broker=broker,
            allowed_files=["calc.py"],
            expected_exit_code=0,
        )
        result, evidence = verifier.verify(
            _verify_request(RUN, TASK, 1, "calc.py", 1, check)
        )
        assert result.status is VerificationResultStatus.PASS
        assert result.attempt == 1
        assert result.artifact_id == artifact_id_for(RUN, TASK, 1)
        assert result.evidence_refs  # non-empty evidence authorizes PASS
        # Evidence is bound to the full identity of the attempt.
        assert all(e.run_id == RUN for e in evidence)
        assert all(e.task_id == TASK for e in evidence)
        assert all(e.attempt == 1 for e in evidence)
        assert all(e.artifact_id == artifact_id_for(RUN, TASK, 1) for e in evidence)
        assert all(e.check_identity is not None for e in evidence)
        kinds = {e.kind for e in evidence}
        assert "artifact" in kinds and "check_result" in kinds


class TestG2DoneWithoutEffect:
    """G2 reproducer: a 'DONE' claim with no real change cannot PASS."""

    def test_no_patch_done_claim_does_not_pass(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        # The executor claims DONE but never patches calc.py (still 'return a+b').
        check = broker.run_checks(
            RUN, TASK, 1, 2, CheckKind.CUSTOM, ["python", "assert_effect.py"]
        )
        assert check.ok and check.exit_code == 1  # the real check fails
        verifier = ArtifactVerifier(broker=broker, allowed_files=["calc.py"])
        result, _ = verifier.verify(_verify_request(RUN, TASK, 1, "calc.py", 1, check))
        assert result.status is VerificationResultStatus.FAIL
        assert result.evidence_refs == []
        # No PASS is granted by the verifier; it has no transition authority.
        assert not hasattr(result, "granted")


class TestNegativeCheck:
    """A real check returning non-zero is an honest FAIL, never PASS."""

    def test_negative_check_fails(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        broker.apply_patch(
            RUN,
            TASK,
            1,
            1,
            "calc.py",
            "def add(a, b):\n    return a - b\n",
            allowed_files=["calc.py"],
        )
        # A check that fails (asserts a different effect than the patch).
        bad_checker = workspace / "assert_effect.py"
        bad_checker.write_text(
            "import sys\ncontent = open('calc.py').read()\nsys.exit(0 if 'return a * b' in content else 1)\n",
            encoding="utf-8",
        )
        check = broker.run_checks(
            RUN, TASK, 1, 2, CheckKind.CUSTOM, ["python", "assert_effect.py"]
        )
        assert check.exit_code == 1
        verifier = ArtifactVerifier(broker=broker, allowed_files=["calc.py"])
        result, _ = verifier.verify(_verify_request(RUN, TASK, 1, "calc.py", 1, check))
        assert result.status is VerificationResultStatus.FAIL


class TestMissingArtifact:
    """An artifact that does not exist (or is unreadable) blocks PASS."""

    def test_missing_artifact_fails(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        check = broker.run_checks(
            RUN, TASK, 1, 2, CheckKind.CUSTOM, ["python", "assert_effect.py"]
        )
        verifier = ArtifactVerifier(broker=broker, allowed_files=["calc.py"])
        result, _ = verifier.verify(
            _verify_request(RUN, TASK, 1, "nonexistent.py", 1, check)
        )
        assert result.status is VerificationResultStatus.FAIL
        assert result.evidence_refs == []


class TestStaleAttempt:
    """A check observation from a different attempt cannot authorize PASS."""

    def test_stale_check_observation_rejected(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        broker.apply_patch(
            RUN,
            TASK,
            1,
            1,
            "calc.py",
            "def add(a, b):\n    return a - b\n",
            allowed_files=["calc.py"],
        )
        # The check ran in attempt 2, but we present it for attempt 1.
        check = broker.run_checks(
            RUN, TASK, 2, 2, CheckKind.CUSTOM, ["python", "assert_effect.py"]
        )
        verifier = ArtifactVerifier(broker=broker, allowed_files=["calc.py"])
        # request claims attempt 1 but the observation is bound to attempt 2.
        req = VerifyRequest(
            run_id=RUN,
            task_id=TASK,
            attempt=1,
            artifact_path="calc.py",
            patch_observation_id=operation_id_for(RUN, TASK, 1, 1),
            check_observation_id=check.operation_id,
            check_observation=check,
        )
        result, _ = verifier.verify(req)
        assert result.status is VerificationResultStatus.FAIL
        # The identity check must have failed.
        assert any(
            "attempt" in c.message.lower() or "bound" in c.message.lower()
            for c in result.checks
            if not c.passed
        )


class TestForeignArtifact:
    """An artifact outside allowed_files (foreign) blocks PASS."""

    def test_foreign_artifact_outside_scope_fails(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        (workspace / "secret.py").write_text("return a - b\n", encoding="utf-8")
        broker.apply_patch(
            RUN,
            TASK,
            1,
            1,
            "calc.py",
            "def add(a, b):\n    return a - b\n",
            allowed_files=["calc.py"],
        )
        check = broker.run_checks(
            RUN, TASK, 1, 2, CheckKind.CUSTOM, ["python", "assert_effect.py"]
        )
        assert check.exit_code == 0
        # Verifier restricted to calc.py; asking it to inspect a foreign file.
        verifier = ArtifactVerifier(
            broker=broker, allowed_files=["calc.py"], expected_exit_code=0
        )
        req = VerifyRequest(
            run_id=RUN,
            task_id=TASK,
            attempt=1,
            artifact_path="secret.py",
            patch_observation_id=operation_id_for(RUN, TASK, 1, 1),
            check_observation_id=check.operation_id,
            check_observation=check,
        )
        result, _ = verifier.verify(req)
        assert result.status is VerificationResultStatus.FAIL


class TestBlockedCheck:
    """A policy-blocked check observation cannot PASS."""

    def test_blocked_check_fails(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        broker.apply_patch(
            RUN,
            TASK,
            1,
            1,
            "calc.py",
            "def add(a, b):\n    return a - b\n",
            allowed_files=["calc.py"],
        )
        # A blocked run_checks (non-allowlisted kind).
        blocked = broker.run_checks(RUN, TASK, 1, 2, "rm", ["-rf", "."])  # type: ignore[arg-type]
        assert blocked.blocked
        verifier = ArtifactVerifier(broker=broker, allowed_files=["calc.py"])
        result, _ = verifier.verify(
            _verify_request(RUN, TASK, 1, "calc.py", 1, blocked)
        )
        assert result.status is VerificationResultStatus.FAIL
        assert result.evidence_refs == []


class TestEvidenceIdentityBinding:
    """Evidence binds run_id/task_id/attempt/operation_id/artifact_id/check_identity."""

    def test_evidence_full_identity(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        broker.apply_patch(
            RUN,
            TASK,
            1,
            1,
            "calc.py",
            "def add(a, b):\n    return a - b\n",
            allowed_files=["calc.py"],
        )
        check = broker.run_checks(
            RUN, TASK, 1, 2, CheckKind.CUSTOM, ["python", "assert_effect.py"]
        )
        verifier = ArtifactVerifier(broker=broker, allowed_files=["calc.py"])
        _, evidence = verifier.verify(
            _verify_request(RUN, TASK, 1, "calc.py", 1, check)
        )
        for e in evidence:
            assert e.run_id == RUN
            assert e.task_id == TASK
            assert e.attempt == 1
            assert e.artifact_id == artifact_id_for(RUN, TASK, 1)
            assert e.check_identity == CheckKind.CUSTOM.value
            assert e.operation_id is not None
        # evidence ids are deterministic for the attempt + kind.
        ids = {e.evidence_id for e in evidence}
        assert evidence_id_for(RUN, TASK, 1, "artifact") in ids
        assert evidence_id_for(RUN, TASK, 1, "check") in ids


class TestVerifierGrantsNoTransition:
    """The verifier returns a result; only the Domain Core grants PASS."""

    def test_verifier_has_no_state_mutation_method(self) -> None:
        verifier = ArtifactVerifier(broker=ToolBroker(workspace_root=pathlib.Path(".")))
        for forbidden in ("grant_pass", "pass_task", "transition", "apply", "commit"):
            assert not hasattr(verifier, forbidden)

    def test_domain_core_rejects_pass_without_evidence(self) -> None:
        # F8 preserved at the Domain Core boundary: TaskVerificationPassed with
        # verification_passed=True but no accepted_evidence_refs is rejected.
        state = _running_state()
        # No EvidenceAccepted event -> accepted_evidence_refs is empty.
        with pytest.raises(InvalidTransitionError):
            apply_event(
                state,
                TaskVerificationPassed(
                    run_id=RUN, task_id=TASK, verification_passed=True
                ),
            )

    def test_domain_core_rejects_pass_without_verification_flag(self) -> None:
        state = _running_state()
        state.plan.tasks[0].accepted_evidence_refs = ["evidence-r-TASK-r-1-1-artifact"]
        with pytest.raises(InvalidTransitionError):
            apply_event(
                state,
                TaskVerificationPassed(
                    run_id=RUN, task_id=TASK, verification_passed=False
                ),
            )

    def test_domain_core_accepts_pass_with_evidence_and_flag(self) -> None:
        state = _running_state()
        ref = "evidence-r-TASK-r-1-1-artifact"
        state = apply_event(
            state, EvidenceAccepted(run_id=RUN, task_id=TASK, evidence_refs=[ref])
        )
        assert state.plan.tasks[0].accepted_evidence_refs == [ref]
        state = apply_event(
            state,
            TaskVerificationPassed(run_id=RUN, task_id=TASK, verification_passed=True),
        )
        assert state.plan.tasks[0].status is TaskStatus.PASSED


class TestEvidencePersistsBeforeSnapshot:
    """Evidence is produced (and would be persisted) before the snapshot accepts refs.

    The verifier returns evidence records for the CURRENT attempt; the caller
    persists them then applies EvidenceAccepted. The Domain Core enforces
    non-empty current-attempt refs for PASS (above). This test proves the
    ordering: on PASS, evidence_refs match the produced evidence ids; on FAIL,
    no refs are offered (so a later PASS attempt is impossible without rework).
    """

    def test_pass_yields_refs_matching_evidence(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        broker.apply_patch(
            RUN,
            TASK,
            1,
            1,
            "calc.py",
            "def add(a, b):\n    return a - b\n",
            allowed_files=["calc.py"],
        )
        check = broker.run_checks(
            RUN, TASK, 1, 2, CheckKind.CUSTOM, ["python", "assert_effect.py"]
        )
        verifier = ArtifactVerifier(broker=broker, allowed_files=["calc.py"])
        result, evidence = verifier.verify(
            _verify_request(RUN, TASK, 1, "calc.py", 1, check)
        )
        assert result.status is VerificationResultStatus.PASS
        assert set(result.evidence_refs) == {e.evidence_id for e in evidence}

    def test_fail_yields_no_refs(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        check = broker.run_checks(
            RUN, TASK, 1, 2, CheckKind.CUSTOM, ["python", "assert_effect.py"]
        )
        verifier = ArtifactVerifier(broker=broker, allowed_files=["calc.py"])
        result, _ = verifier.verify(_verify_request(RUN, TASK, 1, "calc.py", 1, check))
        assert result.status is VerificationResultStatus.FAIL
        assert result.evidence_refs == []


class TestExpectedArtifactContent:
    """The verifier can require the real artifact to contain the expected effect."""

    def test_expected_content_missing_fails(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        # Patch to something, but not the expected effect.
        broker.apply_patch(
            RUN,
            TASK,
            1,
            1,
            "calc.py",
            "def add(a, b):\n    return a * b\n",
            allowed_files=["calc.py"],
        )
        # A check that passes regardless (exit 0) but the artifact content is wrong.
        (workspace / "always_ok.py").write_text(
            "import sys\nsys.exit(0)\n", encoding="utf-8"
        )
        check = broker.run_checks(
            RUN, TASK, 1, 2, CheckKind.CUSTOM, ["python", "always_ok.py"]
        )
        assert check.exit_code == 0
        verifier = ArtifactVerifier(
            broker=broker,
            allowed_files=["calc.py"],
            expected_exit_code=0,
            expected_artifact_contains="return a - b",
        )
        result, _ = verifier.verify(_verify_request(RUN, TASK, 1, "calc.py", 1, check))
        # The check passed but the artifact lacks the expected effect -> FAIL.
        assert result.status is VerificationResultStatus.FAIL
