import re

PATTERNS = [
    re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]*PRIVATE KEY-----|$)"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b"),
]
CREDENTIAL_FIELD = r"(?:api[_-]?key|password|passwd|secret(?:[_-]?key)?|access[_-]?token|auth[_-]?token)"
# A type annotation or reference to an injected secret is source evidence, not
# an embedded credential. Preserve source syntax and redact literal values.
QUOTED_SECRET = re.compile(
    r"(?im)(\b" + CREDENTIAL_FIELD + r"\s*[\"']?\s*(?::\s*(?:str|bytes)\s*)?[:=]\s*)([\"'])(?:\\.|(?!\2)[^\\\r\n])*\2")
ENV_SECRET = re.compile(r"(?m)^([ \t]*(?:API[_-]?KEY|PASSWORD|PASSWD|SECRET(?:[_-]?KEY)?|ACCESS[_-]?TOKEN|AUTH[_-]?TOKEN)[ \t]*=[ \t]*)([A-Za-z0-9_./+\-]{8,})(?=[ \t]*(?:#|$))")


def redact_secrets(text: str) -> str:
    for pattern in PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]"
                           + "\n" * m.group(0).count("\n"), text)
    text = QUOTED_SECRET.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]" + m.group(2), text)
    text = ENV_SECRET.sub(lambda m: m.group(1) + "[REDACTED]", text)
    return text
