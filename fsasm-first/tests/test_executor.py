"""Tests for FS-ASM Executor (Milestone 3)."""

import pytest

from fsasm.models import (
    ChildTask,
    ExecutorBackend,
    ExecutorConfig,
    ExecutorMetadata,
    ExecutorOutput,
    TaskStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.executor import ExecutorStub, executor_stub


class TestExecutorStub:
    """Tests for the ExecutorStub class."""

    def test_executor_stub_creation(self):
        """Test that ExecutorStub can be created."""
        executor = ExecutorStub()
        assert executor is not None

    def test_executor_stub_singleton(self):
        """Test that executor_stub singleton exists."""
        assert executor_stub is not None
        assert isinstance(executor_stub, ExecutorStub)

    def test_execute_produces_output(self):
        """Test that execute produces ExecutorOutput."""
        executor = ExecutorStub()
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test Task",
            description="Test description",
            status=TaskStatus.PENDING,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA,
                expected="test",
            ),
        )
        run_id = "test-run-001"

        output = executor.execute(task, run_id)

        assert isinstance(output, ExecutorOutput)
        assert output.task_id == "TASK-001"
        assert output.run_id == run_id
        assert "Stub execution completed" in output.result
        assert "TASK-001" in output.result
        assert "Test Task" in output.result

    def test_execute_metadata_stub_provider(self):
        """Test that ExecutorOutput metadata has stub provider."""
        executor = ExecutorStub()
        task = ChildTask(
            task_id="TASK-002",
            sequence=2,
            title="Test Task 2",
            description="Test description 2",
            status=TaskStatus.PENDING,
            verification=VerificationSpec(
                type=VerificationType.EXISTS,
                expected="test",
            ),
        )
        run_id = "test-run-002"

        output = executor.execute(task, run_id)

        assert output.metadata.provider == "stub"
        assert output.metadata.model_call_count == 0
        assert output.metadata.task_id == "TASK-002"
        assert output.metadata.run_id == run_id

    def test_execute_metadata_zero_model_calls(self):
        """Test that stub executor makes 0 model API calls."""
        executor = ExecutorStub()
        task = ChildTask(
            task_id="TASK-003",
            sequence=3,
            title="Test Task 3",
            description="Test description 3",
            status=TaskStatus.PENDING,
            verification=VerificationSpec(
                type=VerificationType.CUSTOM,
                expected="test",
            ),
        )
        run_id = "test-run-003"

        output = executor.execute(task, run_id)

        assert output.metadata.model_call_count == 0
        assert output.metadata.executor_invocation_count == 1
        assert output.metadata.input_tokens is None
        assert output.metadata.output_tokens is None
        assert output.metadata.total_tokens is None
        assert output.metadata.provider_request_id is None

    def test_execute_async(self):
        """Test async execute interface."""
        import asyncio

        executor = ExecutorStub()
        task = ChildTask(
            task_id="TASK-004",
            sequence=4,
            title="Test Task 4",
            description="Test description 4",
            status=TaskStatus.PENDING,
            verification=VerificationSpec(
                type=VerificationType.COUNT,
                expected="test",
            ),
        )
        run_id = "test-run-004"

        async def run_test():
            output = await executor.execute_async(task, run_id)
            assert isinstance(output, ExecutorOutput)
            assert output.task_id == "TASK-004"
            assert output.run_id == run_id

        asyncio.run(run_test())


class TestExecutorOutput:
    """Tests for ExecutorOutput model."""

    def test_executor_output_valid(self):
        """Test ExecutorOutput with valid data."""
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
        assert output.task_id == "TASK-001"
        assert output.run_id == "test-run"
        assert output.result == "Test result"
        assert output.metadata == metadata

    def test_executor_output_empty_task_id_rejected(self):
        """Test that empty task_id is rejected."""
        metadata = ExecutorMetadata(
            run_id="test-run",
            task_id="TASK-001",
            provider="stub",
            model_call_count=0,
        )
        with pytest.raises(ValueError, match="text cannot be empty"):
            ExecutorOutput(
                task_id="",
                run_id="test-run",
                result="Test result",
                metadata=metadata,
            )

    def test_executor_output_empty_run_id_rejected(self):
        """Test that empty run_id is rejected."""
        metadata = ExecutorMetadata(
            run_id="",
            task_id="TASK-001",
            provider="stub",
            model_call_count=0,
        )
        with pytest.raises(ValueError, match="text cannot be empty"):
            ExecutorOutput(
                task_id="TASK-001",
                run_id="",
                result="Test result",
                metadata=metadata,
            )

    def test_executor_output_empty_result_rejected(self):
        """Test that empty result is rejected."""
        metadata = ExecutorMetadata(
            run_id="test-run",
            task_id="TASK-001",
            provider="stub",
            model_call_count=0,
        )
        with pytest.raises(ValueError, match="text cannot be empty"):
            ExecutorOutput(
                task_id="TASK-001",
                run_id="test-run",
                result="",
                metadata=metadata,
            )

    def test_validate_provenance_pass(self):
        """Test provenance validation passes with matching IDs."""
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

        assert output.validate_provenance("TASK-001", "test-run") is True

    def test_validate_provenance_fail_task_id(self):
        """Test provenance validation fails with mismatched task_id."""
        metadata = ExecutorMetadata(
            run_id="test-run",
            task_id="TASK-002",  # Different from output.task_id
            provider="stub",
            model_call_count=0,
        )
        output = ExecutorOutput(
            task_id="TASK-001",
            run_id="test-run",
            result="Test result",
            metadata=metadata,
        )

        # metadata.task_id doesn't match expected
        assert output.validate_provenance("TASK-001", "test-run") is False

    def test_validate_provenance_fail_run_id(self):
        """Test provenance validation fails with mismatched run_id."""
        metadata = ExecutorMetadata(
            run_id="different-run",  # Different from expected
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

        # metadata.run_id doesn't match expected
        assert output.validate_provenance("TASK-001", "test-run") is False


class TestExecutorConfig:
    """Tests for ExecutorConfig model."""

    def test_executor_config_stub(self):
        """Test ExecutorConfig with STUB backend."""
        config = ExecutorConfig(
            backend=ExecutorBackend.STUB,
            max_tokens=4096,
            temperature=0.0,
        )
        assert config.backend == ExecutorBackend.STUB
        assert config.model_name is None
        assert config.max_tokens == 4096
        assert config.temperature == 0.0

    def test_executor_config_default_values(self):
        """Test ExecutorConfig default values."""
        config = ExecutorConfig(backend=ExecutorBackend.STUB)
        assert config.max_tokens == 4096
        assert config.temperature == 0.0
        assert config.model_name is None
        assert config.model_version is None


class TestExecutorMetadata:
    """Tests for ExecutorMetadata model."""

    def test_executor_metadata_stub(self):
        """Test ExecutorMetadata for stub provider."""
        metadata = ExecutorMetadata(
            run_id="test-run",
            task_id="TASK-001",
            provider="stub",
            model_call_count=0,
        )
        assert metadata.run_id == "test-run"
        assert metadata.task_id == "TASK-001"
        assert metadata.provider == "stub"
        assert metadata.model_call_count == 0
        assert metadata.executor_invocation_count == 1

    def test_executor_metadata_hash_validation(self):
        """Test that ExecutorMetadata accepts hashes."""
        metadata = ExecutorMetadata(
            run_id="test-run",
            task_id="TASK-001",
            provider="stub",
            model_call_count=0,
            provider_request_id="abc123",
        )
        assert metadata.provider_request_id == "abc123"


class TestExecutorBackend:
    """Tests for ExecutorBackend enum."""

    def test_executor_backend_values(self):
        """Test ExecutorBackend enum values."""
        assert ExecutorBackend.STUB.value == "stub"
        assert ExecutorBackend.LOCAL.value == "local"
        assert ExecutorBackend.MISTRAL.value == "mistral"

    def test_executor_backend_members(self):
        """Test ExecutorBackend enum members."""
        assert "STUB" in ExecutorBackend.__members__
        assert "LOCAL" in ExecutorBackend.__members__
        assert "MISTRAL" in ExecutorBackend.__members__
