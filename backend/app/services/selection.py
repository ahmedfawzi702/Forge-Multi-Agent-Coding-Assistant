from app.schemas.domain import SelectedCode
from app.security.policy import SafetyViolation


def selection_bounds(source: str, selection: SelectedCode) -> tuple[str, str]:
    lines = source.splitlines(keepends=True)
    if source.endswith("\n"):
        lines.append("")
    if not 1 <= selection.start_line <= selection.end_line <= len(lines):
        raise SafetyViolation("Selected source range is stale or invalid")
    if selection.end_column is None:
        start = sum(map(len, lines[:selection.start_line - 1]))
        end = sum(map(len, lines[:selection.end_line]))
    else:
        def offset(line: int, column: int) -> int:
            text = lines[line - 1].rstrip("\r\n")
            # Monaco columns count UTF-16 code units, not Python code points.
            encoded = text.encode("utf-16-le")
            try:
                prefix = encoded[:(column - 1) * 2].decode("utf-16-le")
            except UnicodeDecodeError as error:
                raise SafetyViolation("Selection splits a Unicode character") from error
            if (column - 1) * 2 > len(encoded):
                raise SafetyViolation("Selected source column is invalid")
            return sum(map(len, lines[:line - 1])) + len(prefix)
        start, end = offset(selection.start_line, selection.start_column), offset(selection.end_line, selection.end_column)
    if start >= end or selection.text is not None and source[start:end] != selection.text:
        raise SafetyViolation("Selected text changed; select the current code again")
    return source[:start], source[end:]


def verify_selection(after: str, bounds: tuple[str, str]) -> None:
    prefix, suffix = bounds
    if len(after) < len(prefix) + len(suffix) or not after.startswith(prefix) or not after.endswith(suffix):
        raise SafetyViolation("Edit changes code outside the selected range. Use a whole-file task to authorize broader changes.")
