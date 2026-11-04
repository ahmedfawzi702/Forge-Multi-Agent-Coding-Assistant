"""Recognize only unambiguous user-supplied file content; never invent code."""
import re

from app.schemas.engineering import CodeProposal, ProposedFile


def direct_proposal(message: str) -> CodeProposal | None:
    path = r"`?([\w./\\-]+\.[\w]+)`?"
    empty = re.fullmatch(r"\s*(?:please\s+)?create\s+(?:an?\s+)?empty\s+file\s+(?:(?:named|called)\s+)?" + path + r"[.\s]*", message, re.I)
    supplied = re.fullmatch(r"\s*(?:please\s+)?(?:create|write|replace|save)\s+(?:the\s+)?(?:file\s+)?(?:(?:named|called)\s+)?" + path +
        r"\s+(?:with\s+(?:exactly\s+)?(?:this\s+)?(?:code|content)|with|containing)\s*:?\s*```[^\n]*\n([\s\S]*?)\n```\s*\.?\s*", message, re.I)
    target = empty or supplied
    if target is None:
        return None
    filename = target[1].replace("\\", "/")
    content = supplied[2] + "\n" if supplied else ""
    return CodeProposal(summary=f"Proposed user-requested file: {filename}", files=[ProposedFile(
        path=filename, content=content, reason="Exact content explicitly supplied by the user" if supplied else "Empty file explicitly requested by the user")])
