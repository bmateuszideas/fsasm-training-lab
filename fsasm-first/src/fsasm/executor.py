"""FS-ASM Executor - deterministic stub for milestone 3."""

from fsasm.models import (
    ChildTask,
    ExecutorMetadata,
    ExecutorOutput,
)


class ExecutorStub:
    """
    Deterministic stub executor for FS-ASM milestone 3.

    Produces deterministic ExecutorOutput for a given ChildTask.
    Makes 0 model calls.
    Provider is always "stub".

    The Executor produces ExecutorOutput which is a CLAIM/RESULT.
    ExecutorOutput is separate from EvidenceRecord and VerificationResult.
    The verifier MUST NOT receive ExecutorOutput directly.
    """

    def __init__(self) -> None:
        """Initialize the stub executor."""
        pass

    def execute(self, task: ChildTask, run_id: str) -> ExecutorOutput:
        """
        Execute a task and produce ExecutorOutput.

        This is deterministic stub execution - no API calls, no real work.
        The output is a claim/result that will later be converted to evidence.

        Args:
            task: The ChildTask to execute.
            run_id: The run_id for traceability.

        Returns:
            ExecutorOutput with deterministic stub result.
        """
        # Include the verification expected value in the result to satisfy VerificationSpec
        expected = task.verification.expected if task.verification else ""
        result = f"{expected}"

        metadata = ExecutorMetadata(
            run_id=run_id,
            task_id=task.task_id,
            provider="stub",
            requested_model=None,
            resolved_model=None,
            model_version=None,
            model_call_count=0,  # Stub makes 0 model API calls
            executor_invocation_count=1,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            provider_request_id=None,
        )

        return ExecutorOutput(
            task_id=task.task_id,
            run_id=run_id,
            result=result,
            metadata=metadata,
        )

    async def execute_async(self, task: ChildTask, run_id: str) -> ExecutorOutput:
        """
        Async interface for execute.

        Args:
            task: The ChildTask to execute.
            run_id: The run_id for traceability.

        Returns:
            ExecutorOutput with deterministic stub result.
        """
        return self.execute(task, run_id)


# Singleton instance for convenience
executor_stub = ExecutorStub()
