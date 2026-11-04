from pathlib import Path
from typing import Any

from app.execution.local import LocalExecutionEnvironment, is_link
from app.security.policy import SafetyViolation
from app.security.redaction import redact_secrets


class RulesLoader:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)

    def load(self, paths: list[str] | None = None) -> list[dict[str, Any]]:
        candidates = {"AGENTS.md", "FORGE.md"}
        for path in paths or []:
            relative = Path(path)
            if relative.is_absolute() or ".." in relative.parts:
                continue
            for parent in relative.parents:
                if str(parent) == ".":
                    continue
                candidates.add((parent / "AGENTS.md").as_posix())
                candidates.add((parent / "FORGE.md").as_posix())
        rule_dir = self.root / ".forge" / "rules"
        if rule_dir.is_dir() and not is_link(self.root / ".forge") and not is_link(rule_dir):
            candidates.update(path.relative_to(self.root).as_posix() for path in sorted(rule_dir.glob("*.md"))[:20] if not is_link(path))
        source = LocalExecutionEnvironment(self.root, max_file_bytes=32768)
        result: list[dict[str, Any]] = []
        budget = 16000
        for path in sorted(candidates, key=lambda p: (len(Path(p).parts), p)):
            try:
                content = redact_secrets(source.read_file(path))
            except (OSError, SafetyViolation):
                continue
            excerpt = content[:min(6000, budget)]
            if not excerpt:
                continue
            result.append({"file": path, "content": excerpt, "truncated": len(excerpt) < len(content)})
            budget -= len(excerpt)
            if budget <= 0:
                break
        return result

    def instructions(self, paths: list[str] | None = None) -> str:
        return "\n\n".join(f"RULES {item['file']}{' (truncated)' if item['truncated'] else ''}:\n{item['content']}" for item in self.load(paths))
