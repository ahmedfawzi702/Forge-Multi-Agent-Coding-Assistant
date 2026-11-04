import re
from dataclasses import dataclass

from app.schemas.domain import ChatMode, Intent


@dataclass(frozen=True)
class RoutingDecision:
    intents: list[Intent]
    workflow: str
    read_only: bool


class Orchestrator:
    """Multi-intent routing with mode-enforced capability limits, independent of an LLM."""

    def detect(self, message: str) -> list[Intent]:
        text = message.lower()
        intents: list[Intent] = []
        if re.search(r"\b(?:security|vulnerabilit\w*|injection|exposed secrets)\b", text):
            intents.append(Intent.SECURITY_REVIEW)
        if re.search(r"\breview\b", text) and Intent.SECURITY_REVIEW not in intents:
            intents.append(Intent.REVIEW)
        if re.search(r"\b(?:fix|debug|traceback|fails?|failing|error|bug|broken)\b", text):
            intents.append(Intent.DEBUG)
        if re.search(r"\brefactor\b", text):
            intents.append(Intent.REFACTOR)
        if re.search(r"\b(?:edit|modify|change|replace|rename|fix)\b", text):
            intents.append(Intent.EDIT)
        if re.match(r"\s*(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?(?:make\s+(?:it|this|the\b)|restrict\b|limit\b|update\b|enable\b|disable\b|convert\b|support\b|allow\b)", text):
            intents.append(Intent.EDIT)
        if re.search(r"\b(?:implement|create|build|add|write|generate)\b", text):
            intents.append(Intent.CODE)
        if re.search(r"\btests?\b", text) and re.search(r"\b(?:run|write|generate|add|fix|test)\b", text):
            intents.append(Intent.TEST)
        if re.search(r"\b(?:architecture|entire project|whole project|understand.*project)\b", text):
            intents.append(Intent.PROJECT_ANALYSIS)
        if re.search(r"\b(?:explain|why|how|line by line)\b", text):
            intents.append(Intent.EXPLAIN)
        if re.search(r"\bplan\b", text):
            intents.append(Intent.PLAN)
        return list(dict.fromkeys(intents)) or [Intent.ASK]

    def route(self, message: str, mode: ChatMode) -> RoutingDecision:
        text = message.lower()
        if re.search(r"\b(?:delete|remove|drop|wipe)\b.*\b(?:all|database|table|directory|files|folder)\b|git\s+(?:reset|clean|push).*?(?:--hard|--force|-fd)", text):
            return RoutingDecision([Intent.EDIT], "blocked", True)
        explicit = {"explain": Intent.EXPLAIN, "edit": Intent.EDIT, "debug": Intent.DEBUG,
                    "test": Intent.TEST, "review": Intent.REVIEW, "security_review": Intent.SECURITY_REVIEW}
        intents = [explicit[mode]] if mode in explicit else self.detect(message)
        if mode == "plan" or intents == [Intent.PLAN] or re.match(r"\s*(?:plan\b|make a plan\b|create a plan\b)", text):
            return RoutingDecision([Intent.PLAN, *[i for i in intents if i != Intent.PLAN]], "plan", True)
        question = bool(re.match(r"\s*(?:why\b|how\b|what\b|explain\b|where\b|can you explain\b)", text))
        mutate = any(i in intents for i in (Intent.CODE, Intent.EDIT, Intent.REFACTOR)) and not question
        if mode == "ask":
            mutate = False
        if mutate:
            return RoutingDecision(intents, "modify", False)
        if Intent.SECURITY_REVIEW in intents:
            return RoutingDecision(intents, "security", True)
        if Intent.REVIEW in intents:
            return RoutingDecision(intents, "review", True)
        if Intent.DEBUG in intents:
            return RoutingDecision(intents, "debug", True)
        if Intent.TEST in intents and mode != "ask" and not question:
            return RoutingDecision(intents, "test", False)
        if Intent.PROJECT_ANALYSIS in intents:
            return RoutingDecision(intents, "analyze", True)
        return RoutingDecision(intents, "explain", True)

    def classify(self, message: str, mode: ChatMode) -> Intent:
        return self.route(message, mode).intents[0]
