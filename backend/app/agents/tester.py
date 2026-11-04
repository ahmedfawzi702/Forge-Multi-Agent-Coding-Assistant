import hashlib
from pathlib import Path

from app.config import Settings
from app.execution.local import LocalExecutionEnvironment
from app.execution.process import ValidationRunner
from app.schemas.engineering import TestReport
from app.security.policy import SafetyViolation


class TesterAgent:
    async def run(self, root: Path, files: list[str], settings: Settings,
                  allow_execution: bool, targets: list[str] | None = None,
                  expected_hashes: dict[str, str] | None = None) -> TestReport:
        tests = [path for path in files if Path(path).name.startswith("test_") and path.endswith(".py")
                 or Path(path).name.endswith("_test.py")]
        if not tests:
            return TestReport(status="not_found", summary="No Python tests found; execution was not claimed.")
        if not allow_execution:
            return TestReport(status="awaiting_approval", framework="pytest",
                              summary="Local pytest execution requires your permission. Tests can execute project code outside this folder; this is not an OS sandbox.")
        source = LocalExecutionEnvironment(root, settings.max_file_bytes)
        def hashes() -> dict[str, str]:
            return {path: hashlib.sha256(source.read_file(path).encode()).hexdigest() for path in set(files)}
        try:
            before = hashes()
            if expected_hashes is not None and any(before.get(path) != value for path, value in expected_hashes.items()):
                return TestReport(status="blocked", summary="Validation source changed since review; regenerate the ChangeSet.")
        except (OSError, SafetyViolation):
            return TestReport(status="blocked", summary="Validation source is unavailable or violates file policy.")
        selected = [path for path in targets or [] if path in tests]
        result = await ValidationRunner(root, allow_tests=True, output_limit=settings.execution_output_bytes).run(
            "pytest", selected, timeout=settings.execution_timeout_seconds)
        try:
            unchanged = hashes() == before
        except (OSError, SafetyViolation):
            unchanged = False
        summary = "Timed out; process tree terminated" if result.timed_out else "pytest finished"
        if not unchanged:
            summary = "Tests modified indexed validation source; results cannot approve this ChangeSet."
        return TestReport(status="passed" if result.exit_code == 0 and not result.timed_out and unchanged else "failed",
                          framework="pytest", command=["python", "-I", "-m", "pytest", *selected],
                          exit_code=result.exit_code, stdout=result.stdout, stderr=result.stderr,
                          summary=summary, evidence="VERIFIED")
