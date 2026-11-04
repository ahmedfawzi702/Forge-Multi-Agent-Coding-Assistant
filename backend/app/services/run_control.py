from dataclasses import dataclass, field

from app.security.policy import SafetyViolation


class SteeringUpdate(Exception):
    def __init__(self, messages: list[str]):
        self.messages = messages


class RunInterrupted(Exception):
    def __init__(self, cancelled: bool = False):
        self.cancelled = cancelled
        super().__init__("Task cancelled" if cancelled else "Task paused by the user")


@dataclass
class RunControl:
    project_id: str
    pending: list[str] = field(default_factory=list)
    stopped: bool = False
    cancelled: bool = False
    updates: int = 0

    def steer(self, message: str) -> None:
        if self.updates >= 5:
            raise SafetyViolation("This task has reached its five-update limit; start a new task")
        self.updates += 1
        self.pending.append(message)

    def boundary(self) -> None:
        if self.stopped:
            raise RunInterrupted(self.cancelled)
        if self.pending:
            messages, self.pending = self.pending, []
            raise SteeringUpdate(messages)
