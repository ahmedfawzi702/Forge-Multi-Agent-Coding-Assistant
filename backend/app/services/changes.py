from difflib import unified_diff

from app.security.policy import SafetyViolation


def proposed_diff(path: str, before: str, after: str) -> str:
    if (not path or path.startswith(("/", "\\")) or ".." in path.replace("\\", "/").split("/")
            or ":" in path or any(ord(character) < 32 for character in path)):
        raise SafetyViolation("Diff paths must be project-relative")
    lines = unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                         fromfile=f"a/{path}", tofile=f"b/{path}")
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)
