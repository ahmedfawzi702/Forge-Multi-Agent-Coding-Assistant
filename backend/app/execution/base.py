from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class ExecutionEnvironment(ABC):
    @abstractmethod
    def read_file(self, path: str) -> str: ...

    @abstractmethod
    def write_file(self, path: str, content: str) -> None: ...

    @abstractmethod
    async def execute(self, argv: list[str], timeout: int = 30) -> ExecutionResult: ...

    @abstractmethod
    async def run_tests(self) -> ExecutionResult: ...
