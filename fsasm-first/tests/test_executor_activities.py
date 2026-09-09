"""Tests for FS-ASM Executor Activities (Milestone 3)."""

import pytest

from fsasm.models import (
    ChildTask,
    EvidenceRecord,
    ExecutorBackend,
    ExecutorConfig,
    ExecutorMetadata,
    ExecutorOutput,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationResult,
    VerificationResultStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.executor_activities import (
    execute_task_activity,
    validate_executor_output_provenance_activity,
    convert_executor_output_to_evidence_activity,
    verify_task_execution_activity,
    prepare_task_activity,
    finalize_task_activity,
    ProvenanceValidationError,
)
from fsasm.errors import ConfigurationError


class TestExecuteTaskActivity:
    """Tests for execute_task_activity."""

    @pytest.mark.asyncio
    async def test_execute_task_stub_backend(self):
        """Test execute_task_activity with STUB backend."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test Task",
            description="Test description",
            status=TaskStatus.READY,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA,
                expected="test",
            ),
        )
        run_id = "test-run-001"
        config = ExecutorConfig(backend=ExecutorBackend.STUB)

        output = await execute_task_activity(task, run_id, config)

        assert isinstance(output, ExecutorOutput)
        assert output.task_id == "TASK-001"
        assert output.run_id == run_id
        assert output.metadata.provider == "stub"
        assert output.metadata.model_call_count == 0

    @pytest.mark.asyncio
    async def test_execute_task_non_stub_backend_raises(self):
        """Test that non-STUB backend raises ConfigurationError for M3."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test Task",
            description="Test description",
            status=TaskStatus.READY,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA,
                expected="test",
            ),
        )
        run_id = "test-run-001"
        config = ExecutorConfig(backend=ExecutorBackend.MISTRAL)

        with pytest.raises(ConfigurationError):
            await execute_task_activity(task, run_id, config)


class TestValidateExecutorOutputProvenanceActivity:
    """Tests for validate_executor_output_provenance_activity."""

    @pytest.mark.asyncio
    async def test_validate_provenance_pass(self):
        """Test provenance validation passes with matching IDs."""
        from fsasm.models import ExecutorMetadata, ExecutorOutput
        metadata = ExecutorMetadata(
            run_id="test-run",
            task_id="TASK-001",
            provider="stub",
            model_call_count=0,
        )
        output = ExecutorOutput(
            task_id="TASK-001",
            run_id="test-run",
            result="Test result",
            metadata=metadata,
        )

        validated = await validate_executor_output_provenance_activity(
            output, "TASK-001", "test-run"
        )
        assert validated == output

    @pytest.mark.asyncio
    async def test_validate_provenance_fail_output_task_id(self):
        """Test provenance validation fails with mismatched output task_id."""
        from fsasm.models import ExecutorMetadata, ExecutorOutput
        metadata = ExecutorMetadata(
            run_id="test-run",
            task_id="TASK-001",
            provider="stub",
            model_call_count=0,
        )
        output = ExecutorOutput(
            task_id="TASK-002",  # Mismatch
            run_id="test-run",
            result="Test result",
            metadata=metadata,
        )

        with pytest.raises(ProvenanceValidationError):
            await validate_executor_output_provenance_activity(
                output, "TASK-001", "test-run"
            )

    @pytest.mark.asyncio
    async def test_validate_provenance_fail_metadata_task_id(self):
        """Test provenance validation fails with mismatched metadata task_id."""
        from fsasm.models import ExecutorMetadata, ExecutorOutput
        metadata = ExecutorMetadata(
            run_id="test-run",
            task_id="TASK-002",  # Mismatch with expected
            provider="stub",
            model_call_count=0,
        )
        output = ExecutorOutput(
            task_id="TASK-001",
            run_id="test-run",
            result="Test result",
            metadata=metadata,
        )

        with pytest.raises(ProvenanceValidationError):
            await validate_executor_output_provenance_activity(
                output, "TASK-001", "test-run"
            )

    @pytest.mark.asyncio
    async def test_validate_provenance_fail_metadata_run_id(self):
        """Test provenance validation fails with mismatched metadata run_id."""
        from fsasm.models import ExecutorMetadata, ExecutorOutput
        metadata = ExecutorMetadata(
            run_id="different-run",  # Mismatch with expected
            task_id="TASK-001",
            provider="stub",
            model_call_count=0,
        )
        output = ExecutorOutput(
            task_id="TASK-001",
            run_id="different-run",
            result="Test result",
            metadata=metadata,
        )

        with pytest.raises(ProvenanceValidationError):
            await validate_executor_output_provenance_activity(
                output, "TASK-001", "test-run"
            )


class TestConvertExecutorOutputToEvidenceActivity:
    """Tests for convert_executor_output_to_evidence_activity."""

    @pytest.mark.asyncio
    async def test_convert_with_expected_evidence(self):
        """Test conversion with expected evidence kinds."""
        from fsasm.models import ExecutorMetadata, ExecutorOutput
        metadata = ExecutorMetadata(
            run_id="test-run",
            task_id="TASK-001",
            provider="stub",
            model_call_count=0,
        )
        output = ExecutorOutput(
            task_id="TASK-001",
            run_id="test-run",
            result="Test result",
            metadata=metadata,
        )
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test Task",
            description="Test description",
            status=TaskStatus.READY,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA,
                expected="test",
            ),
            expected_evidence=["test_output", "test_log"],
        )

        evidence_records = await convert_executor_output_to_evidence_activity(
            output, task, 0
        )

        assert len(evidence_records) == 2
        assert evidence_records[0].kind == "test_output"
        assert evidence_records[1].kind == "test_log"
        assert all(e.run_id == "test-run" for e in evidence_records)
        assert all(e.task_id == "TASK-001" for e in evidence_records)
        assert all(e.source == "executor_stub" for e in evidence_records)

    @pytest.mark.asyncio
    async def test_convert_with_empty_expected_evidence(self):
        """Test conversion with empty expected evidence (fallback)."""
        from fsasm.models import ExecutorMetadata, ExecutorOutput
        metadata = ExecutorMetadata(
            run_id="test-run",
            task_id="TASK-001",
            provider="stub",
            model_call_count=0,
        )
        output = ExecutorOutput(
            task_id="TASK-001",
            run_id="test-run",
            result="Test result",
            metadata=metadata,
        )
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test Task",
            description="Test description",
            status=TaskStatus.READY,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA,
                expected="test",
            ),
            expected_evidence=[],
        )

        evidence_records = await convert_executor_output_to_evidence_activity(
            output, task, 0
        )

        assert len(evidence_records) == 1
        assert evidence_records[0].kind == "executor_output"
        assert evidence_records[0].run_id == "test-run"
        assert evidence_records[0].task_id == "TASK-001"

    @pytest.mark.asyncio
    async def test_convert_evidence_ids_are_deterministic(self):
        """Test that evidence IDs are deterministic with counter."""
        from fsasm.models import ExecutorMetadata, ExecutorOutput
        metadata = ExecutorMetadata(
            run_id="test-run",
            task_id="TASK-001",
            provider="stub",
            model_call_count=0,
        )
        output = ExecutorOutput(
            task_id="TASK-001",
            run_id="test-run",
            result="Test result",
            metadata=metadata,
        )
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test Task",
            description="Test description",
            status=TaskStatus.READY,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA,
                expected="test",
            ),
            expected_evidence=["evidence_a"],
        )

        evidence_records = await convert_executor_output_to_evidence_activity(
            output, task, 5
        )

        assert evidence_records[0].evidence_id == "evidence-test-run-TASK-001-exec-005-000"


class TestVerifyTaskExecutionActivity:
    """Tests for verify_task_execution_activity."""

    @pytest.mark.asyncio
    async def test_verify_pass(self):
        """Test verification passes with valid evidence."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test Task",
            description="Test description",
            status=TaskStatus.RUNNING,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA,
                expected="Stub execution completed for task: TASK-001",
            ),
            expected_evidence=["test_output"],
        )
        run_id = "test-run"
        evidence_records = [
            EvidenceRecord(
                evidence_id="evidence-1",
                run_id=run_id,
                task_id="TASK-001",
                kind="test_output",
                source="executor_stub",
                payload={
                    "executor_output": {
                        "task_id": "TASK-001",
                        "run_id": run_id,
                        "result": "Stub execution completed for task: TASK-001 - Test Task",
                        "metadata": {},
                    },
                    "original_evidence_kind": "test_output",
                    "evidence_index": 0,
                },
            )
        ]

        result = await verify_task_execution_activity(run_id, task, evidence_records)

        assert result.status == VerificationResultStatus.PASS
        assert result.task_id == "TASK-001"
        assert result.run_id == run_id
        assert any(c.passed for c in result.checks)

    @pytest.mark.asyncio
    async def test_verify_fail_no_evidence(self):
        """Test verification fails with no evidence."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test Task",
            description="Test description",
            status=TaskStatus.RUNNING,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA,
                expected="test",
            ),
            expected_evidence=["test_output"],
        )
        run_id = "test-run"

        result = await verify_task_execution_activity(run_id, task, [])

        assert result.status == VerificationResultStatus.FAIL
        assert any("No evidence records" in c.message for c in result.checks)

    @pytest.mark.asyncio
    async def test_verify_fail_wrong_run_id(self):
        """Test verification fails with wrong run_id in evidence."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test Task",
            description="Test description",
            status=TaskStatus.RUNNING,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA,
                expected="test",
            ),
            expected_evidence=["test_output"],
        )
        run_id = "test-run"
        evidence_records = [
            EvidenceRecord(
                evidence_id="evidence-1",
                run_id="wrong-run",  # Wrong run_id
                task_id="TASK-001",
                kind="test_output",
                source="executor_stub",
                payload={"data": "test"},
            )
        ]

        result = await verify_task_execution_activity(run_id, task, evidence_records)

        assert result.status == VerificationResultStatus.FAIL
        assert any("run_id" in c.message and "!=" in c.message for c in result.checks)

    @pytest.mark.asyncio
    async def test_verify_fail_wrong_task_id(self):
        """Test verification fails with wrong task_id in evidence."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test Task",
            description="Test description",
            status=TaskStatus.RUNNING,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA,
                expected="test",
            ),
            expected_evidence=["test_output"],
        )
        run_id = "test-run"
        evidence_records = [
            EvidenceRecord(
                evidence_id="evidence-1",
                run_id=run_id,
                task_id="TASK-002",  # Wrong task_id
                kind="test_output",
                source="executor_stub",
                payload={"data": "test"},
            )
        ]

        result = await verify_task_execution_activity(run_id, task, evidence_records)

        assert result.status == VerificationResultStatus.FAIL
        assert any("task_id" in c.message and "!=" in c.message for c in result.checks)

    @pytest.mark.asyncio
    async def test_verify_fail_missing_expected_evidence(self):
        """Test verification fails with missing expected evidence kind."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test Task",
            description="Test description",
            status=TaskStatus.RUNNING,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA,
                expected="test",
            ),
            expected_evidence=["test_output", "test_log"],
        )
        run_id = "test-run"
        evidence_records = [
            EvidenceRecord(
                evidence_id="evidence-1",
                run_id=run_id,
                task_id="TASK-001",
                kind="test_output",  # Missing test_log
                source="executor_stub",
                payload={"data": "test"},
            )
        ]

        result = await verify_task_execution_activity(run_id, task, evidence_records)

        assert result.status == VerificationResultStatus.FAIL
        assert any("Missing expected evidence kinds" in c.message for c in result.checks)

    @pytest.mark.asyncio
    async def test_verify_requires_all_expected_kinds(self):
        """Test that verification requires ALL declared expected evidence kinds."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test Task",
            description="Test description",
            status=TaskStatus.RUNNING,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA,
                expected="test",
            ),
            expected_evidence=["kind_a", "kind_b", "kind_c"],
        )
        run_id = "test-run"
        evidence_records = [
            EvidenceRecord(
                evidence_id="evidence-1",
                run_id=run_id,
                task_id="TASK-001",
                kind="kind_a",
                source="executor_stub",
                payload={"data": "test"},
            ),
            EvidenceRecord(
                evidence_id="evidence-2",
                run_id=run_id,
                task_id="TASK-001",
                kind="kind_b",
                source="executor_stub",
                payload={"data": "test"},
            ),
            # Missing kind_c
        ]

        result = await verify_task_execution_activity(run_id, task, evidence_records)

        assert result.status == VerificationResultStatus.FAIL
        assert any("kind_c" in c.message for c in result.checks)

    @pytest.mark.asyncio
    async def test_verify_empty_expected_evidence_fallback(self):
        """Test verification with empty expected evidence (fallback)."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test Task",
            description="Test description",
            status=TaskStatus.RUNNING,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA,
                expected="",
            ),
            expected_evidence=[],
        )
        run_id = "test-run"
        evidence_records = [
            EvidenceRecord(
                evidence_id="evidence-1",
                run_id=run_id,
                task_id="TASK-001",
                kind="executor_output",
                source="executor_stub",
                payload={
                    "executor_output": {
                        "task_id": "TASK-001",
                        "run_id": run_id,
                        "result": "Stub execution completed for task: TASK-001 - Test Task",
                        "metadata": {},
                    },
                    "original_evidence_kinds": [],
                },
            )
        ]

        result = await verify_task_execution_activity(run_id, task, evidence_records)

        assert result.status == VerificationResultStatus.PASS


class TestPrepareTaskActivity:
    """Tests for prepare_task_activity."""

    @pytest.mark.asyncio
    async def test_prepare_task_sets_running(self):
        """Test that prepare sets task to RUNNING."""
        plan = Plan(
            plan_id="test-plan",
            run_id="test-run",
            goal="Test goal",
            tasks=[
                ChildTask(
                    task_id="TASK-001",
                    sequence=1,
                    title="Task 1",
                    description="Desc 1",
                    status=TaskStatus.READY,
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA,
                        expected="test",
                    ),
                ),
                ChildTask(
                    task_id="TASK-002",
                    sequence=2,
                    title="Task 2",
                    description="Desc 2",
                    status=TaskStatus.PENDING,
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA,
                        expected="test",
                    ),
                ),
                ChildTask(
                    task_id="TASK-003",
                    sequence=3,
                    title="Task 3",
                    description="Desc 3",
                    status=TaskStatus.PENDING,
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA,
                        expected="test",
                    ),
                ),
            ],
        )
        state = RunState(
            run_id="test-run",
            goal="Test goal",
            status=RunStatus.RUNNING,
            plan=plan,
            active_task_id=None,
            completed_task_ids=[],
            failed_task_ids=[],
        )
        task = plan.tasks[0]

        updated_state, updated_task = await prepare_task_activity(state, task)

        assert updated_task.status == TaskStatus.RUNNING
        assert updated_state.active_task_id == "TASK-001"
        assert updated_state.status == RunStatus.RUNNING
        # Check that plan in state was updated
        assert updated_state.plan.tasks[0].status == TaskStatus.RUNNING
        assert updated_state.plan.tasks[1].status == TaskStatus.PENDING
        assert updated_state.plan.tasks[2].status == TaskStatus.PENDING


class TestFinalizeTaskActivity:
    """Tests for finalize_task_activity."""

    @pytest.mark.asyncio
    async def test_finalize_pass_path(self):
        """Test finalize PASS path."""
        plan = Plan(
            plan_id="test-plan",
            run_id="test-run",
            goal="Test goal",
            tasks=[
                ChildTask(
                    task_id="TASK-001",
                    sequence=1,
                    title="Task 1",
                    description="Desc 1",
                    status=TaskStatus.RUNNING,
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA,
                        expected="test",
                    ),
                ),
                ChildTask(
                    task_id="TASK-002",
                    sequence=2,
                    title="Task 2",
                    description="Desc 2",
                    status=TaskStatus.PENDING,
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA,
                        expected="test",
                    ),
                ),
                ChildTask(
                    task_id="TASK-003",
                    sequence=3,
                    title="Task 3",
                    description="Desc 3",
                    status=TaskStatus.PENDING,
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA,
                        expected="test",
                    ),
                ),
            ],
        )
        state = RunState(
            run_id="test-run",
            goal="Test goal",
            status=RunStatus.RUNNING,
            plan=plan,
            active_task_id="TASK-001",
            completed_task_ids=[],
            failed_task_ids=[],
        )
        task = plan.tasks[0]
        verification_result = VerificationResult(
            run_id="test-run",
            task_id="TASK-001",
            status=VerificationResultStatus.PASS,
            checks=[],
            message="PASS",
        )
        evidence_records = [
            EvidenceRecord(
                evidence_id="evidence-1",
                run_id="test-run",
                task_id="TASK-001",
                kind="test_output",
                source="executor_stub",
                payload={"data": "test"},
            )
        ]

        updated_state, updated_task = await finalize_task_activity(
            state, task, verification_result, evidence_records
        )

        assert updated_task.status == TaskStatus.PASSED
        assert "TASK-001" in updated_state.completed_task_ids
        assert "TASK-001" not in updated_state.failed_task_ids
        assert updated_state.active_task_id is None
        assert updated_state.status == RunStatus.RUNNING
        # Check that plan in state was updated
        assert updated_state.plan.tasks[0].status == TaskStatus.PASSED
        assert updated_state.plan.tasks[1].status == TaskStatus.PENDING
        assert updated_state.plan.tasks[2].status == TaskStatus.PENDING

    @pytest.mark.asyncio
    async def test_finalize_fail_path(self):
        """Test finalize FAIL path."""
        plan = Plan(
            plan_id="test-plan",
            run_id="test-run",
            goal="Test goal",
            tasks=[
                ChildTask(
                    task_id="TASK-001",
                    sequence=1,
                    title="Task 1",
                    description="Desc 1",
                    status=TaskStatus.RUNNING,
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA,
                        expected="test",
                    ),
                ),
                ChildTask(
                    task_id="TASK-002",
                    sequence=2,
                    title="Task 2",
                    description="Desc 2",
                    status=TaskStatus.PENDING,
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA,
                        expected="test",
                    ),
                ),
                ChildTask(
                    task_id="TASK-003",
                    sequence=3,
                    title="Task 3",
                    description="Desc 3",
                    status=TaskStatus.PENDING,
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA,
                        expected="test",
                    ),
                ),
            ],
        )
        state = RunState(
            run_id="test-run",
            goal="Test goal",
            status=RunStatus.RUNNING,
            plan=plan,
            active_task_id="TASK-001",
            completed_task_ids=[],
            failed_task_ids=[],
        )
        task = plan.tasks[0]
        verification_result = VerificationResult(
            run_id="test-run",
            task_id="TASK-001",
            status=VerificationResultStatus.FAIL,
            checks=[],
            message="FAIL",
        )
        evidence_records = []

        updated_state, updated_task = await finalize_task_activity(
            state, task, verification_result, evidence_records
        )

        assert updated_task.status == TaskStatus.FAILED
        assert "TASK-001" in updated_state.failed_task_ids
        assert "TASK-001" not in updated_state.completed_task_ids
        assert updated_state.active_task_id is None
        assert updated_state.status == RunStatus.RUNNING
        # Check that plan in state was updated
        assert updated_state.plan.tasks[0].status == TaskStatus.FAILED
        assert updated_state.plan.tasks[1].status == TaskStatus.PENDING
        assert updated_state.plan.tasks[2].status == TaskStatus.PENDING
