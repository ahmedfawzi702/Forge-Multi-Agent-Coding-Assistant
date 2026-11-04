from app.code_intelligence.parser import PythonASTParser
from app.llm.base import CompletionRequest, LLMProvider


class EvidenceProvider(LLMProvider):
    """Useful offline inspection, explicitly not AI reasoning or simulated chat."""

    name = "evidence"

    async def complete(self, request: CompletionRequest) -> str:
        project = request.project_map
        symbols = []
        for chunk in request.context:
            if chunk.evidence.file.endswith(".py"):
                excerpt = "\n" * (chunk.evidence.start_line - 1) + "\n".join(
                    line.partition(": ")[2] for line in chunk.content.splitlines())
                symbols.extend(PythonASTParser().parse(chunk.evidence.file, excerpt))
        facts = [
            "## Project evidence\n\nEvidence-only mode is active. This is an index report, not an AI explanation. "
            "Configure Ollama or an OpenAI-compatible provider in `.env` for natural-language reasoning.",
            f"**Known facts from the project-map snapshot:** {len(project.files)} indexed files; languages: {', '.join(project.language) or 'unknown'}. "
            f"Manifest frameworks: {', '.join(project.framework) or 'unknown'}.",
            f"Scan timestamp: `{project.scanned_at}`. Refresh the index after external changes. "
            "Source excerpts below were reread for this request. Only fully parseable excerpts contribute symbol listings.",
            "### Related code\n" + ("\n".join(
                f"- `{s.file_path}:{s.start_line}-{s.end_line}` — {s.type} `{s.name}`"
                for s in symbols[:20]) or "No Python symbols were found in the retrieved files."),
            "### Retrieved sources\n" + ("\n".join(
                f"- `{c.evidence.file}:{c.evidence.start_line}-{c.evidence.end_line}`"
                for c in request.context) or "No source excerpts are available."),
            "**Unknown:** runtime behavior, correctness, cross-file execution flow and root causes "
            "have not been established. No tests or security scanner ran. No files were modified.",
        ]
        if project.warnings:
            facts.append("### Coverage limits\n" + "\n".join(f"- {w}" for w in project.warnings))
        return "\n\n".join(facts)
