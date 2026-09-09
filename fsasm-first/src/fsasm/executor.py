"""FS-ASM Executor - deterministic stub for milestone 3 and 4."""

from fsasm.models import (
    ChildTask,
    ExecutorMetadata,
    ExecutorOutput,
)


class ExecutorStub:
    """
    Deterministic stub executor for FS-ASM milestone 3 and 4.

    Produces deterministic ExecutorOutput for a given ChildTask.
    Makes 0 model calls.
    Provider is always "stub".

    The Executor produces ExecutorOutput which is a CLAIM/RESULT.
    ExecutorOutput is separate from EvidenceRecord and VerificationResult.
    The verifier MUST NOT receive ExecutorOutput directly.

    For M4, supports configurable failure behavior via stub_fail_first_n_attempts:
    - 0 = first attempt passes
    - 1 = first fails, second passes
    - 999 = all attempts fail (deterministic exhaustion)
    """

    def __init__(self, stub_fail_first_n_attempts: int = 0) -> None:
        """Initialize the stub executor.

        Args:
            stub_fail_first_n_attempts: Number of initial attempts that should fail.
                0 = always pass on first attempt
                1 = fail first, pass second
                999 = always fail (for testing exhaustion)
        """
        self.stub_fail_first_n_attempts = stub_fail_first_n_attempts

    def execute(self, task: ChildTask, run_id: str, attempt: int = 0) -> ExecutorOutput:
        """
        Execute a task and produce ExecutorOutput.

        This is deterministic stub execution - no API calls, no real work.
        The output is a claim/result that will later be converted to evidence.

        For M4: If attempt < stub_fail_first_n_attempts, the result will cause verification FAIL.
        Otherwise, the result will satisfy verification.

        Args:
            task: The ChildTask to execute.
            run_id: The run_id for traceability.
            attempt: The current attempt number (0-indexed).

        Returns:
            ExecutorOutput with deterministic stub result.
        """
        # Include the verification expected value in the result to satisfy VerificationSpec
        expected = task.verification.expected if task.verification else ""

        # For M4: determine if this attempt should fail
        # stub_fail_first_n_attempts=0: always pass (attempt 1, 1 < 0+1 is True for attempt 1, False for attempt 0)
        # stub_fail_first_n_attempts=1: first attempt fails (attempt 1 < 1+1=2 is True)
        # stub_fail_first_n_attempts=999: always fail (attempt < 999+1=1000 always true for reasonable attempts)
        # Note: attempt is 1-indexed in workflow (incremented on READY->RUNNING)
        # We want: fail_first_n_attempts=0 means first attempt (attempt=1) passes
        # So: fail if attempt <= stub_fail_first_n_attempts
        # But attempt starts at 1 for first execution
        # stub_fail_first_n_attempts=0: fail if attempt <= 0, never true for attempt >= 1, so always pass
        # stub_fail_first_n_attempts=1: fail if attempt <= 1, true for attempt 1, false for attempt 2
        # stub_fail_first_n_attempts=999: fail if attempt <= 999, always true
        if attempt <= self.stub_fail_first_n_attempts:
            # This attempt should fail - return wrong result that does NOT contain expected
            result = "FAILURE_XYZ_WRONG"
        else:
            # This attempt should pass - return correct result
            result = expected

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

    async def execute_async(
        self, task: ChildTask, run_id: str, attempt: int = 0
    ) -> ExecutorOutput:
        """
        Async interface for execute.

        Args:
            task: The ChildTask to execute.
            run_id: The run_id for traceability.
            attempt: The current attempt number (0-indexed).

        Returns:
            ExecutorOutput with deterministic stub result.
        """
        return self.execute(task, run_id, attempt)


# Singleton instance for convenience
executor_stub = ExecutorStub()
