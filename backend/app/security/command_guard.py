import re
from collections.abc import Sequence
from pathlib import PurePath

from app.security.risk_classifier import RiskLevel, SafetyDecision


class CommandGuard:
    """Default-deny argv policy. No string shell commands are accepted.

    Default policy permits only two read-only Git queries at the boundary;
    LocalExecutionEnvironment still disables ALL process execution.
    """

    ALLOWED = {("git", "status", "--short"), ("git", "diff", "--stat")}
    DANGEROUS = re.compile(
        r"(?:\brm\b|\brmdir\b|\bremove-item\b|\bdel\b|\bformat\b|\bshutdown\b|\breboot\b|"
        r"\bdrop\s+(?:database|table)\b|\breset\b.*--hard|\bclean\b.*-[a-z]*[fd]|"
        r"\bpush\b.*(?:--force|-f\b)|\b(?:powershell|pwsh|cmd|bash|sh|python|node|pip|npm)\b)",
        re.IGNORECASE,
    )

    def inspect(self, argv: Sequence[str] | str, *, allow_tools: bool = False) -> SafetyDecision:
        if isinstance(argv, str) or not argv or any(not isinstance(a, str) for a in argv):
            return self._blocked("Use a non-empty argument array; shell strings are forbidden")
        joined = " ".join(argv)
        if any(re.search(r"[;&|`$<>\r\n\x00]", part) for part in argv):
            return self._blocked("Shell syntax and control characters are forbidden")
        if any(".." in PurePath(p.replace("\\", "/")).parts for p in argv):
            return self._blocked("Directory traversal is forbidden")
        if allow_tools and self._is_validation_tool(list(argv)):
            return SafetyDecision(blocked=False, risk=RiskLevel.MEDIUM,
                                  reason="Restricted validation tool", requires_user_approval=False)
        if self.DANGEROUS.search(joined):
            return self._blocked("Potentially destructive command or arbitrary code execution")
        if tuple(argv) not in self.ALLOWED:
            return self._blocked("Command is outside the read-only allowlist")
        return SafetyDecision(blocked=False, risk=RiskLevel.LOW, reason="Read-only Git query",
                              requires_user_approval=False)

    @staticmethod
    def _is_validation_tool(argv: list[str]) -> bool:
        if argv == ["python", "-I", "-m", "ruff", "check", "--isolated", "--select", "E9,F63,F7,F82", "."]:
            return True
        if argv == ["python", "-I", "-m", "bandit", "-r", ".", "-f", "json", "-q"]:
            return True
        prefix = ["python", "-I", "-m", "pytest", "-q", "--maxfail=3", "-o", "pythonpath=."]
        return argv[:len(prefix)] == prefix and all(
            not item.startswith("-") and not PurePath(item).is_absolute()
            and ":" not in item and item.endswith(".py") for item in argv[len(prefix):])

    @staticmethod
    def _blocked(reason: str) -> SafetyDecision:
        return SafetyDecision(blocked=True, risk=RiskLevel.HIGH, reason=reason,
                              requires_user_approval=True)

    def development(self, argv: Sequence[str]) -> SafetyDecision:
        """Agent development policy. The manual PTY is a separate human capability."""
        if not argv or isinstance(argv, str) or any(not isinstance(arg, str) or len(arg) > 16000 for arg in argv):
            return self._blocked("A bounded argument array is required")
        if any(re.search(r"[;&|`$<>\r\n\x00]", arg) for arg in argv):
            return self._blocked("Agent commands cannot contain shell operators or redirections")
        if any(".." in PurePath(arg.replace("\\", "/")).parts for arg in argv):
            return self._blocked("Agent command paths cannot traverse outside the workspace")
        name = argv[0].lower()
        if name not in {"python", "python3", "py", "pytest", "ruff", "mypy", "bandit", "node", "npm", "npx", "pip", "git"}:
            return self._blocked("This executable is not an approved development tool")
        joined = " ".join(argv).lower()
        if re.search(r"\b(?:shutdown|reboot|remove-item|rmdir|rm|del|diskpart)\b|git\s+(?:push|reset|clean)|\b(?:curl|wget|invoke-webrequest)\b", joined):
            return self._blocked("Destructive commands, remote shell downloads and Git push/reset/clean are blocked for agents")
        install = name in {"pip", "npx"} or name == "npm" and len(argv) > 1 and argv[1] in {"install", "i", "ci", "add", "exec"} or "-m pip" in joined
        return SafetyDecision(blocked=False, risk=RiskLevel.HIGH if install else RiskLevel.MEDIUM,
            reason="Package/network execution requires explicit permission" if install else "Workspace development command",
            requires_user_approval=install)
