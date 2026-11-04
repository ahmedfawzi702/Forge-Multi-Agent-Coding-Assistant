from enum import StrEnum

from pydantic import BaseModel


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SafetyDecision(BaseModel):
    blocked: bool
    risk: RiskLevel
    reason: str
    requires_user_approval: bool


class RiskClassifier:
    def classify(self, operation: str, path: str = "") -> SafetyDecision:
        name = path.lower().replace("\\", "/")
        risk = RiskLevel.MEDIUM
        if operation in {"read", "search", "explain", "list"}:
            risk = RiskLevel.LOW
        if operation in {"delete", "migrate", "git_force"} or any(
            part in name for part in (".env", "auth", "credentials", "secrets")
        ):
            risk = RiskLevel.HIGH
        if operation in {"expose_secret", "delete_database", "system_command"}:
            risk = RiskLevel.CRITICAL
        blocked = risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        return SafetyDecision(blocked=blocked, risk=risk,
                              reason=f"{operation}: {risk.value.lower()} risk",
                              requires_user_approval=blocked)
