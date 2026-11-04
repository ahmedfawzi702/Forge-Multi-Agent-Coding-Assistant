import ast
import hashlib
from typing import Protocol

from app.schemas.domain import CodeSymbol


class CodeParser(Protocol):
    def parse(self, path: str, source: str) -> list[CodeSymbol]: ...


class PythonASTParser:
    """Python's built-in AST now; Tree-sitter adapters can share CodeParser later."""

    def parse(self, path: str, source: str) -> list[CodeSymbol]:
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError):
            return []
        symbols: list[CodeSymbol] = []
        lines = source.splitlines()

        def visit(node: ast.AST, parent: str | None = None, parent_kind: str | None = None) -> None:
            for child in ast.iter_child_nodes(node):
                owner = parent
                owner_kind = parent_kind
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    kind = "class" if isinstance(child, ast.ClassDef) else "function"
                    if parent_kind == "class" and kind == "function":
                        kind = "method"
                    symbols.append(CodeSymbol(
                        id=hashlib.sha256(f"{path}:{child.lineno}:{child.name}".encode()).hexdigest()[:20],
                        name=child.name, type=kind, file_path=path, language="python",
                        start_line=child.lineno, end_line=child.end_lineno or child.lineno,
                        signature=lines[child.lineno - 1].strip(), docstring=ast.get_docstring(child),
                        parent=parent,
                    ))
                    owner = child.name
                    owner_kind = kind
                visit(child, owner, owner_kind)

        visit(tree)
        return symbols
