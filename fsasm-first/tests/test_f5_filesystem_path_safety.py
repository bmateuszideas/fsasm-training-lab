"""F5 regression tests: filesystem identifier and path safety.

These tests exercise the F5 security contract at the actual persistence boundary:

1. Valid generated UUID and conventional FS-ASM IDs continue to work.
2. Unsafe run IDs are rejected before writes.
3. Unsafe run IDs are rejected before reads.
4. Unsafe evidence IDs are rejected before writes and reads.
5. ``cleanup_run()`` cannot delete an external sentinel directory via traversal.
6. Existing run-directory symlinks cannot redirect an operation outside the
   authorized run (run isolation even when the target stays inside ``runs_dir``).
7. Existing evidence-directory symlinks cannot redirect evidence operations
   outside the run.
8. Where relevant, an existing symlink at a destination file cannot cause an
   unsafe operation.
9. Rejected operations do not mutate external sentinel files or create
   unexpected directories.
10. Normal ``save`` -> ``load`` -> ``cleanup_run`` behavior stays functional.

All destructive targets live inside ``tmp_path``. No default runtime directory
is used.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from fsasm.errors import InvalidIdentifierError
from fsasm.models import (
    ChildTask,
    EvidenceRecord,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationCheck,
    VerificationResult,
    VerificationResultStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.persistence import RuntimePersistence


def _make_plan(run_id: str) -> Plan:
    tasks = [
        ChildTask(
            task_id=f"TASK-{i:03d}",
            sequence=i,
            title=f"Task {i}",
            description=f"Description {i}",
            status=TaskStatus.PENDING,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="ok"),
        )
        for i in range(1, 4)
    ]
    return Plan(
        plan_id=f"plan-{run_id}",
        run_id=run_id,
        goal="Test goal",
        tasks=tasks,
    )


def _make_state(run_id: str) -> RunState:
    return RunState(
        run_id=run_id,
        goal="Test goal",
        status=RunStatus.PLANNED,
    )


def _make_evidence(run_id: str, evidence_id: str) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        run_id=run_id,
        task_id="TASK-001",
        kind="test_result",
        source="pytest",
        payload={"passed": True},
    )


def _make_verification(run_id: str) -> VerificationResult:
    return VerificationResult(
        run_id=run_id,
        task_id="TASK-001",
        status=VerificationResultStatus.PASS,
        checks=[
            VerificationCheck(check_name="ok", passed=True, message="ok"),
        ],
        message="pass",
    )


@pytest.fixture
def persistence(tmp_path: Path) -> RuntimePersistence:
    runtime_dir = tmp_path / "runtime"
    return RuntimePersistence(runtime_dir=runtime_dir)


UNSAFE_RUN_IDS = [
    "../outside",
    "../../outside",
    "foo/../bar",
    "foo/./bar",
    "/absolute/path",
    "/tmp/evil",
    "..\\outside",
    "foo\\bar",
    "C:\\outside",
    "C:/outside",
    "\\\\server\\share",
    ".",
    "..",
    "",
    "   ",
    "run\nid",
    "run\x00id",
    "run/with/slash",
]

UNSAFE_EVIDENCE_IDS = [
    "../outside",
    "../../outside",
    "/absolute/path",
    "..\\outside",
    "C:\\outside",
    ".",
    "..",
    "",
    "   ",
    "evidence\x00id",
    "ev/sub/id",
]

# Evidence IDs that the EvidenceRecord model already rejects at construction
# (empty/whitespace). These cannot reach save_evidence as a model instance, so
# they are exercised through load_evidence (raw strings) and a model test.
MODEL_REJECTED_EVIDENCE_IDS = ["", "   "]

# Evidence IDs that pass model construction but must be rejected by the
# persistence boundary before any write side effect.
PERSISTENCE_REJECTED_EVIDENCE_IDS = [
    eid for eid in UNSAFE_EVIDENCE_IDS if eid not in MODEL_REJECTED_EVIDENCE_IDS
]


class TestValidIdentifiersPreserved:
    """Valid generated UUID and conventional FS-ASM IDs continue to work."""

    def test_uuid_run_id_round_trip(self, persistence: RuntimePersistence) -> None:
        run_id = str(uuid.uuid4())
        plan = _make_plan(run_id)
        state = _make_state(run_id)
        evidence = _make_evidence(run_id, f"evidence-{run_id}")
        verification = _make_verification(run_id)

        persistence.save_plan(plan)
        persistence.save_run_state(state)
        persistence.save_evidence(evidence)
        persistence.save_verification_result(verification)
        persistence.save_run_log_entry(run_id, {"event": "e"})

        assert persistence.load_plan(run_id) is not None
        assert persistence.load_run_state(run_id) is not None
        assert persistence.load_evidence(run_id, evidence.evidence_id) is not None
        assert persistence.run_exists(run_id) is True
        loaded_all = persistence.load_all_evidence(run_id)
        assert len(loaded_all) == 1
        assert persistence.load_run_log(run_id)
        persistence.cleanup_run(run_id)
        assert persistence.run_exists(run_id) is False

    @pytest.mark.parametrize(
        "run_id",
        [
            "run-123",
            "run-test-123",
            "test-run-abc",
            "my-custom-run-id",
            "test-fsasm-m4-scenario-b",
            "test-s2-initial-persistence",
            "evidence-proposal-run-123",
        ],
    )
    def test_conventional_fsasm_run_ids(
        self, persistence: RuntimePersistence, run_id: str
    ) -> None:
        persistence.save_run_state(_make_state(run_id))
        assert persistence.load_run_state(run_id) is not None

    @pytest.mark.parametrize(
        "evidence_id",
        [
            "evidence-1",
            "evidence-123",
            "evidence-proposal-run-123",
            "evidence-m3-execution-run-123",
            "evidence-human-gate-retry-run-123-TASK-001",
        ],
    )
    def test_conventional_fsasm_evidence_ids(
        self, persistence: RuntimePersistence, evidence_id: str
    ) -> None:
        run_id = "run-valid-evidence"
        persistence.save_evidence(_make_evidence(run_id, evidence_id))
        assert persistence.load_evidence(run_id, evidence_id) is not None


class TestUnsafeRunIdsRejectedBeforeWrites:
    """Unsafe run IDs are rejected before any write side effect."""

    @pytest.mark.parametrize("run_id", UNSAFE_RUN_IDS)
    def test_save_run_state_rejects_unsafe_run_id(
        self, persistence: RuntimePersistence, run_id: str, tmp_path: Path
    ) -> None:
        outside_before = {p for p in tmp_path.rglob("*")}
        with pytest.raises(InvalidIdentifierError):
            persistence.save_run_state(_make_state(run_id))
        assert {p for p in tmp_path.rglob("*")} == outside_before

    @pytest.mark.parametrize("run_id", UNSAFE_RUN_IDS)
    def test_save_plan_rejects_unsafe_run_id(
        self, persistence: RuntimePersistence, run_id: str
    ) -> None:
        with pytest.raises(InvalidIdentifierError):
            persistence.save_plan(_make_plan(run_id))

    @pytest.mark.parametrize("run_id", UNSAFE_RUN_IDS)
    def test_save_verification_result_rejects_unsafe_run_id(
        self, persistence: RuntimePersistence, run_id: str
    ) -> None:
        with pytest.raises(InvalidIdentifierError):
            persistence.save_verification_result(_make_verification(run_id))

    @pytest.mark.parametrize("run_id", UNSAFE_RUN_IDS)
    def test_save_run_log_entry_rejects_unsafe_run_id(
        self, persistence: RuntimePersistence, run_id: str
    ) -> None:
        with pytest.raises(InvalidIdentifierError):
            persistence.save_run_log_entry(run_id, {"event": "e"})


class TestUnsafeRunIdsRejectedBeforeReads:
    """Unsafe run IDs are rejected before any read/lookup side effect."""

    @pytest.mark.parametrize("run_id", UNSAFE_RUN_IDS)
    def test_load_plan_rejects_unsafe_run_id(
        self, persistence: RuntimePersistence, run_id: str
    ) -> None:
        with pytest.raises(InvalidIdentifierError):
            persistence.load_plan(run_id)

    @pytest.mark.parametrize("run_id", UNSAFE_RUN_IDS)
    def test_load_run_state_rejects_unsafe_run_id(
        self, persistence: RuntimePersistence, run_id: str
    ) -> None:
        with pytest.raises(InvalidIdentifierError):
            persistence.load_run_state(run_id)

    @pytest.mark.parametrize("run_id", UNSAFE_RUN_IDS)
    def test_load_run_log_rejects_unsafe_run_id(
        self, persistence: RuntimePersistence, run_id: str
    ) -> None:
        with pytest.raises(InvalidIdentifierError):
            persistence.load_run_log(run_id)

    @pytest.mark.parametrize("run_id", UNSAFE_RUN_IDS)
    def test_load_all_evidence_rejects_unsafe_run_id(
        self, persistence: RuntimePersistence, run_id: str
    ) -> None:
        with pytest.raises(InvalidIdentifierError):
            persistence.load_all_evidence(run_id)

    @pytest.mark.parametrize("run_id", UNSAFE_RUN_IDS)
    def test_run_exists_rejects_unsafe_run_id(
        self, persistence: RuntimePersistence, run_id: str
    ) -> None:
        with pytest.raises(InvalidIdentifierError):
            persistence.run_exists(run_id)


class TestUnsafeEvidenceIdsRejected:
    """Unsafe evidence IDs are rejected before writes and reads."""

    @pytest.mark.parametrize("evidence_id", PERSISTENCE_REJECTED_EVIDENCE_IDS)
    def test_save_evidence_rejects_unsafe_evidence_id(
        self, persistence: RuntimePersistence, evidence_id: str, tmp_path: Path
    ) -> None:
        run_id = "run-evidence-safe"
        outside_before = {p for p in tmp_path.rglob("*")}
        with pytest.raises(InvalidIdentifierError):
            persistence.save_evidence(_make_evidence(run_id, evidence_id))
        assert {p for p in tmp_path.rglob("*")} == outside_before

    @pytest.mark.parametrize("evidence_id", MODEL_REJECTED_EVIDENCE_IDS)
    def test_model_rejects_empty_evidence_id_before_persistence(
        self, evidence_id: str
    ) -> None:
        # Empty/whitespace evidence IDs are rejected by the EvidenceRecord model
        # at construction, before persistence is reached. Record this as an
        # already-protected boundary rather than manufacturing a failure.
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError):
            _make_evidence("run-safe", evidence_id)

    @pytest.mark.parametrize("evidence_id", UNSAFE_EVIDENCE_IDS)
    def test_load_evidence_rejects_unsafe_evidence_id(
        self, persistence: RuntimePersistence, evidence_id: str
    ) -> None:
        run_id = "run-evidence-safe"
        with pytest.raises(InvalidIdentifierError):
            persistence.load_evidence(run_id, evidence_id)


class TestCleanupRunCannotEscape:
    """``cleanup_run()`` cannot delete an external sentinel directory."""

    def test_cleanup_traversal_rejected(
        self, persistence: RuntimePersistence, tmp_path: Path
    ) -> None:
        sentinel_dir = tmp_path / "outside"
        sentinel_dir.mkdir()
        sentinel_file = sentinel_dir / "secret.txt"
        sentinel_file.write_text("SENTINEL")

        with pytest.raises(InvalidIdentifierError):
            persistence.cleanup_run("../outside")
        assert sentinel_file.exists()
        assert sentinel_file.read_text() == "SENTINEL"

    def test_cleanup_absolute_rejected(
        self, persistence: RuntimePersistence, tmp_path: Path
    ) -> None:
        sentinel_dir = tmp_path / "abs-outside"
        sentinel_dir.mkdir()
        sentinel_file = sentinel_dir / "secret.txt"
        sentinel_file.write_text("SENTINEL")

        with pytest.raises(InvalidIdentifierError):
            persistence.cleanup_run(str(sentinel_dir))
        assert sentinel_file.exists()


class TestRunDirectorySymlinkIsolation:
    """Run isolation: a symlinked run directory cannot redirect operations into
    another run even when its target stays inside ``runs_dir``."""

    def test_symlinked_run_alias_rejected_and_origin_intact(
        self, persistence: RuntimePersistence, tmp_path: Path
    ) -> None:
        real_run = "run-real"
        alias = "run-alias"
        persistence.save_run_state(_make_state(real_run))
        real_run_dir = persistence.runs_dir / real_run
        alias_dir = persistence.runs_dir / alias
        os.symlink(real_run_dir, alias_dir)

        with pytest.raises(InvalidIdentifierError):
            persistence.save_run_state(_make_state(alias))
        with pytest.raises(InvalidIdentifierError):
            persistence.load_run_state(alias)
        with pytest.raises(InvalidIdentifierError):
            persistence.run_exists(alias)
        with pytest.raises(InvalidIdentifierError):
            persistence.cleanup_run(alias)

        # The original run is unchanged and still readable.
        loaded = persistence.load_run_state(real_run)
        assert loaded is not None
        assert loaded.run_id == real_run
        assert (real_run_dir / "state.json").exists()

    def test_symlinked_run_cannot_receive_evidence(
        self, persistence: RuntimePersistence, tmp_path: Path
    ) -> None:
        real_run = "run-real-ev"
        alias = "run-alias-ev"
        persistence.save_run_state(_make_state(real_run))
        os.symlink(persistence.runs_dir / real_run, persistence.runs_dir / alias)
        with pytest.raises(InvalidIdentifierError):
            persistence.save_evidence(_make_evidence(alias, "evidence-1"))


class TestEvidenceDirectorySymlinkIsolation:
    """An evidence-directory symlink cannot redirect evidence ops outside the run."""

    def test_evidence_dir_symlink_to_outside_rejected(
        self, persistence: RuntimePersistence, tmp_path: Path
    ) -> None:
        run_id = "run-evdir-symlink"
        outside_dir = tmp_path / "outside-evidence"
        outside_dir.mkdir()
        outside_file = outside_dir / "evil.json"
        outside_file.write_text("EVIL")

        persistence.save_run_state(_make_state(run_id))
        evidence_dir = persistence.runs_dir / run_id / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_dir.rmdir()
        os.symlink(outside_dir, evidence_dir)

        with pytest.raises(InvalidIdentifierError):
            persistence.save_evidence(_make_evidence(run_id, "evidence-x"))
        assert outside_file.exists()
        assert outside_file.read_text() == "EVIL"

    def test_evidence_dir_symlink_to_other_run_rejected(
        self, persistence: RuntimePersistence, tmp_path: Path
    ) -> None:
        run_a = "run-a-evdir"
        run_b = "run-b-evdir"
        persistence.save_run_state(_make_state(run_a))
        persistence.save_run_state(_make_state(run_b))
        persistence.save_evidence(_make_evidence(run_b, "evidence-b"))

        evidence_dir_a = persistence.runs_dir / run_a / "evidence"
        evidence_dir_a.mkdir(parents=True, exist_ok=True)
        evidence_dir_a.rmdir()
        os.symlink(persistence.runs_dir / run_b / "evidence", evidence_dir_a)

        # Must not read run_b's evidence through run_a's symlinked evidence dir.
        with pytest.raises(InvalidIdentifierError):
            persistence.load_all_evidence(run_a)
        with pytest.raises(InvalidIdentifierError):
            persistence.load_evidence(run_a, "evidence-b")
        with pytest.raises(InvalidIdentifierError):
            persistence.save_evidence(_make_evidence(run_a, "evidence-a"))

    def test_evidence_file_symlink_in_dir_redirects_load_all_evidence(
        self, persistence: RuntimePersistence, tmp_path: Path
    ) -> None:
        """A symlinked evidence file inside an otherwise-valid evidence directory
        cannot redirect ``load_all_evidence`` into another run's evidence.

        Run A has a valid evidence directory containing a symlinked evidence
        file that points at run B's evidence JSON. ``load_all_evidence(run_a)``
        must raise ``InvalidIdentifierError`` and must not read or return the
        foreign evidence.
        """
        run_a = "run-a-file-alias"
        run_b = "run-b-file-target"
        persistence.save_run_state(_make_state(run_a))
        persistence.save_run_state(_make_state(run_b))
        persistence.save_evidence(_make_evidence(run_b, "evidence-b"))

        run_b_evidence_file = (
            persistence.runs_dir / run_b / "evidence" / "evidence-b.json"
        )
        assert run_b_evidence_file.exists()

        evidence_dir_a = persistence.runs_dir / run_a / "evidence"
        evidence_dir_a.mkdir(parents=True, exist_ok=True)
        os.symlink(run_b_evidence_file, evidence_dir_a / "evidence-b.json")

        with pytest.raises(InvalidIdentifierError):
            persistence.load_all_evidence(run_a)

        # The foreign evidence was neither returned nor altered.
        loaded_b = persistence.load_evidence(run_b, "evidence-b")
        assert loaded_b is not None
        assert loaded_b.run_id == run_b
        assert loaded_b.evidence_id == "evidence-b"


class TestDestinationFileSymlink:
    """An existing symlink at a destination file cannot cause an unsafe op."""

    def test_state_file_symlink_to_outside_rejected(
        self, persistence: RuntimePersistence, tmp_path: Path
    ) -> None:
        run_id = "run-file-symlink"
        outside = tmp_path / "outside-state.json"
        outside.write_text("OUTSIDE")

        run_dir = persistence.runs_dir / run_id
        run_dir.mkdir(parents=True)
        os.symlink(outside, run_dir / "state.json")

        with pytest.raises(InvalidIdentifierError):
            persistence.save_run_state(_make_state(run_id))
        with pytest.raises(InvalidIdentifierError):
            persistence.load_run_state(run_id)

        assert outside.exists()
        assert outside.read_text() == "OUTSIDE"

    def test_evidence_file_symlink_to_outside_rejected(
        self, persistence: RuntimePersistence, tmp_path: Path
    ) -> None:
        run_id = "run-evfile-symlink"
        outside = tmp_path / "outside-evidence.json"
        outside.write_text("OUTSIDE")

        evidence_dir = persistence.runs_dir / run_id / "evidence"
        evidence_dir.mkdir(parents=True)
        os.symlink(outside, evidence_dir / "target.json")

        with pytest.raises(InvalidIdentifierError):
            persistence.save_evidence(_make_evidence(run_id, "target"))
        with pytest.raises(InvalidIdentifierError):
            persistence.load_evidence(run_id, "target")

        assert outside.exists()
        assert outside.read_text() == "OUTSIDE"


class TestRejectedOpsDoNotMutate:
    """Rejected operations leave external sentinels and trees untouched."""

    def test_rejected_save_creates_no_unexpected_dirs(
        self, persistence: RuntimePersistence, tmp_path: Path
    ) -> None:
        before = {p for p in tmp_path.rglob("*")}
        for rid in ["../x", "/abs", "a/b", "..\\z"]:
            with pytest.raises(InvalidIdentifierError):
                persistence.save_run_state(_make_state(rid))
            with pytest.raises(InvalidIdentifierError):
                persistence.save_plan(_make_plan(rid))
            with pytest.raises(InvalidIdentifierError):
                persistence.save_evidence(_make_evidence(rid, "../y"))
        assert {p for p in tmp_path.rglob("*")} == before

    def test_rejected_cleanup_leaves_sentinel(
        self, persistence: RuntimePersistence, tmp_path: Path
    ) -> None:
        sentinel = tmp_path / "sentinel-dir"
        sentinel.mkdir()
        (sentinel / "f.txt").write_text("S")
        for rid in ["../sentinel-dir", "/tmp/x", "a/../../sentinel-dir"]:
            with pytest.raises(InvalidIdentifierError):
                persistence.cleanup_run(rid)
        assert (sentinel / "f.txt").read_text() == "S"


class TestExcessiveLengthRejected:
    """Identifier length limit leaves room for the ``.json`` suffix."""

    def test_overlong_run_id_rejected(self, persistence: RuntimePersistence) -> None:
        huge = "a" * 300
        with pytest.raises(InvalidIdentifierError):
            persistence.save_run_state(_make_state(huge))
        with pytest.raises(InvalidIdentifierError):
            persistence.load_run_state(huge)

    def test_overlong_evidence_id_rejected(
        self, persistence: RuntimePersistence
    ) -> None:
        huge = "e" * 300
        run_id = "run-len"
        with pytest.raises(InvalidIdentifierError):
            persistence.save_evidence(_make_evidence(run_id, huge))
        with pytest.raises(InvalidIdentifierError):
            persistence.load_evidence(run_id, huge)


class TestWindowsReservedNamesRejected:
    """Windows-reserved filenames are rejected for cross-platform safety."""

    @pytest.mark.parametrize(
        "name",
        ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1", "CON.txt", "lpt9"],
    )
    def test_reserved_run_id_rejected(
        self, persistence: RuntimePersistence, name: str
    ) -> None:
        with pytest.raises(InvalidIdentifierError):
            persistence.save_run_state(_make_state(name))

    @pytest.mark.parametrize(
        "name",
        ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1"],
    )
    def test_reserved_evidence_id_rejected(
        self, persistence: RuntimePersistence, name: str
    ) -> None:
        run_id = "run-reserved"
        with pytest.raises(InvalidIdentifierError):
            persistence.save_evidence(_make_evidence(run_id, name))


class TestNormalSaveLoadCleanupFunctional:
    """Normal save -> load -> cleanup remains functional after F5."""

    def test_full_round_trip(self, persistence: RuntimePersistence) -> None:
        run_id = "round-trip-f5"
        persistence.save_plan(_make_plan(run_id))
        persistence.save_run_state(_make_state(run_id))
        persistence.save_evidence(_make_evidence(run_id, "evidence-1"))
        persistence.save_verification_result(_make_verification(run_id))

        assert persistence.load_plan(run_id) is not None
        assert persistence.load_run_state(run_id) is not None
        assert persistence.load_evidence(run_id, "evidence-1") is not None
        assert persistence.run_exists(run_id)
        assert persistence.load_run_log(run_id)

        persistence.cleanup_run(run_id)
        assert not persistence.run_exists(run_id)
