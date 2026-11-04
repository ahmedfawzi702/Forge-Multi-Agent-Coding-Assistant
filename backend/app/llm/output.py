"""Validate model text before it enters chat, history, or an agent result."""
import json
import re
from typing import Any

MALFORMED_RESPONSE = (
    "The model returned a malformed response. No changes were applied. Please retry the request."
)


def completion_problem(answer: str, *, structured: bool = False) -> str | None:
    if not answer.strip():
        return "empty response"
    if len(answer) > 80000:
        return "response exceeds the text limit"
    if structured:
        cleaned = answer.strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            cleaned = "\n".join(cleaned.splitlines()[1:-1])
        try:
            value = json.loads(cleaned)
        except ValueError:
            return "invalid structured JSON"
        return None if isinstance(value, dict) else "structured result is not an object"
    # Examples inside code fences/inline code are valid documentation. Check prose,
    # not strings in code that the user may legitimately be asking about.
    prose = re.sub(r"```[\s\S]*?```|`[^`\n]+`", "", answer)
    if re.search(r"</?(?:think|analysis|reasoning)\b[^>]*>|<EOS_TOKEN>|<\|(?:im_start|im_end|endoftext|start_header_id|end_header_id|eot_id)\|>", prose, re.I):
        return "model protocol or reasoning markers in final text"
    if (re.match(r'\s*\{\s*"(?:content|role|custom_data)"\s*:', prose)
            and re.search(r'"(?:custom_data|tool_calls)"\s*:', prose)):
        return "serialized tool/assistant envelope instead of an answer"
    if re.match(r"\s*(?:Cannot run commands|Tool execution is disabled in this environment)[.!\s]*$", prose, re.I):
        return "fabricated tool response"
    return None


def public_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Older persisted failures are displayed safely without destroying audit data."""
    if result and isinstance(result.get("answer"), str) and completion_problem(result["answer"]):
        return {**result, "answer": MALFORMED_RESPONSE, "status": "failed", "task_status": "FAILED", "confidence": "LOW"}
    return result
