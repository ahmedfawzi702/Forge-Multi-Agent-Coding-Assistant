import hashlib
from pathlib import Path

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from app.schemas.domain import CodeSymbol


def syntax_tree(path: str, source: str) -> Node:
    suffix = Path(path).suffix.lower()
    capsule = (tree_sitter_typescript.language_tsx() if suffix == ".tsx" else
               tree_sitter_typescript.language_typescript() if suffix == ".ts" else
               tree_sitter_javascript.language())
    return Parser(Language(capsule)).parse(source.encode()).root_node


class TreeSitterParser:
    def parse(self, path: str, source: str) -> list[CodeSymbol]:
        root = syntax_tree(path, source)
        data = source.encode()
        symbols: list[CodeSymbol] = []
        stack: list[tuple[Node, str | None]] = [(root, None)]
        while stack:
            node, parent = stack.pop()
            kind = {"function_declaration": "function", "class_declaration": "class", "method_definition": "method",
                    "interface_declaration": "interface", "type_alias_declaration": "type"}.get(node.type)
            if node.type == "variable_declarator":
                value = node.child_by_field_name("value")
                if value is not None and value.type in {"arrow_function", "function_expression"}:
                    kind = "function"
            name_node = node.child_by_field_name("name")
            owner = parent
            if kind and name_node:
                name = data[name_node.start_byte:name_node.end_byte].decode()
                symbols.append(CodeSymbol(id=hashlib.sha256(f"{path}:{node.start_byte}:{name}".encode()).hexdigest()[:20],
                    name=name, type=kind, file_path=path,
                    language="typescript" if Path(path).suffix in {".ts", ".tsx"} else "javascript",
                    start_line=node.start_point.row + 1, end_line=node.end_point.row + 1,
                    signature=source.splitlines()[node.start_point.row].strip(), parent=parent))
                owner = name
            stack.extend((child, owner) for child in reversed(node.named_children))
        return symbols
