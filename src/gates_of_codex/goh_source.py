from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Sequence


MAX_ENTRY_CHARS = 1_000_000
MAX_NESTING_DEPTH = 256


@dataclass(frozen=True, slots=True)
class SourceLocation:
    source: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class SourceDiagnostic:
    code: str
    message: str
    location: SourceLocation
    captured: str


@dataclass(frozen=True, slots=True)
class MacroCall:
    name: str
    family: str
    ordinal: int | None
    value: str
    location: SourceLocation


@dataclass(frozen=True, slots=True)
class SourceEntry:
    name: str
    form: str
    macro_kind: str
    raw: str
    location: SourceLocation
    calls: Sequence[MacroCall]


@dataclass(frozen=True, slots=True)
class SourceScanResult:
    entries: Sequence[SourceEntry]
    diagnostics: Sequence[SourceDiagnostic]


def scan_source_entries(text: str, source: str) -> SourceScanResult:
    """Collect bounded top-level GoH block and macro definitions from *text*."""
    line_starts = _line_starts(text)
    entries: list[SourceEntry] = []
    diagnostics: list[SourceDiagnostic] = []
    index = 0
    quote = False
    escaped = False
    comment = False
    paren_depth = 0
    brace_depth = 0

    while index < len(text):
        char = text[index]
        if comment:
            if char == "\n":
                comment = False
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            index += 1
            continue
        if char == ";" or text.startswith("//", index):
            comment = True
            index += 1
            continue
        if char == '"':
            quote = True
            index += 1
            continue

        form = (
            _definition_form(text, index)
            if paren_depth == 0 and brace_depth == 0
            else None
        )
        if form is None:
            if char == "(":
                paren_depth += 1
            elif char == ")":
                paren_depth = max(0, paren_depth - 1)
            elif char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth = max(0, brace_depth - 1)
            index += 1
            continue

        end, diagnostic, recovery = _capture_entry(
            text,
            source,
            index,
            form,
            line_starts,
        )
        if diagnostic is not None:
            diagnostics.append(diagnostic)
            index = recovery
            quote = False
            escaped = False
            comment = False
            paren_depth = 0
            brace_depth = 0
            continue

        raw = text[index:end]
        calls = _parse_calls(raw, source, index, form, line_starts)
        if form == "macro":
            macro_kind = _macro_kind(raw)
            name = next(
                (call.value for call in calls if call.name.lower() == "name"),
                "",
            )
        else:
            macro_kind = ""
            name = _block_name(raw)
        entries.append(
            SourceEntry(
                name=name,
                form=form,
                macro_kind=macro_kind,
                raw=raw,
                location=_location(source, index, line_starts),
                calls=calls,
            )
        )
        index = end

    return SourceScanResult(entries=entries, diagnostics=diagnostics)


def _capture_entry(
    text: str,
    source: str,
    start: int,
    form: str,
    line_starts: Sequence[int],
) -> tuple[int, SourceDiagnostic | None, int]:
    paren_depth = 1 if form == "macro" else 0
    brace_depth = 1 if form == "block" else 0
    quote = False
    escaped = False
    comment = False
    index = start + 1

    while index < len(text):
        if index - start >= MAX_ENTRY_CHARS:
            recovery = _find_recovery(text, index)
            return index, _diagnostic(
                "entry_too_large",
                f"entry exceeded {MAX_ENTRY_CHARS} characters",
                text,
                source,
                start,
                line_starts,
            ), recovery

        char = text[index]
        if comment:
            if char == "\n":
                comment = False
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            index += 1
            continue
        if char == ";" or text.startswith("//", index):
            comment = True
            index += 1
            continue
        if char == '"':
            quote = True
            index += 1
            continue

        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth -= 1
            if paren_depth < 0:
                return _malformed_close(text, source, start, index, line_starts, "parenthesis")
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth -= 1
            if brace_depth < 0:
                return _malformed_close(text, source, start, index, line_starts, "block")

        if paren_depth + brace_depth > MAX_NESTING_DEPTH:
            recovery = _find_recovery(text, index + 1)
            return index + 1, _diagnostic(
                "nesting_depth_exceeded",
                f"entry exceeded nesting depth {MAX_NESTING_DEPTH}",
                text,
                source,
                start,
                line_starts,
                capture_end=index + 1,
            ), recovery

        index += 1
        root_closed = (
            (form == "macro" and paren_depth == 0)
            or (form == "block" and brace_depth == 0)
        )
        if not root_closed:
            continue
        if form == "macro" and brace_depth:
            return index, _diagnostic(
                "malformed_nested_block",
                "macro closed with an unclosed nested block",
                text,
                source,
                start,
                line_starts,
                capture_end=index,
            ), index
        if form == "block" and paren_depth:
            return index, _diagnostic(
                "malformed_nested_parenthesis",
                "block closed with an unclosed nested parenthesis",
                text,
                source,
                start,
                line_starts,
                capture_end=index,
            ), index
        return index, None, index

    recovery = _find_recovery(text, start + 1)
    return len(text), _diagnostic(
        "unterminated_entry",
        (
            "entry did not close before the next top-level definition"
            if recovery < len(text)
            else "entry reached end of source before its closing delimiter"
        ),
        text,
        source,
        start,
        line_starts,
        capture_end=recovery,
    ), recovery


def _malformed_close(
    text: str,
    source: str,
    start: int,
    index: int,
    line_starts: Sequence[int],
    delimiter: str,
) -> tuple[int, SourceDiagnostic, int]:
    end = index + 1
    return end, _diagnostic(
        "unexpected_closer",
        f"entry contained an unexpected closing {delimiter}",
        text,
        source,
        start,
        line_starts,
        capture_end=end,
    ), _find_recovery(text, end)


def _diagnostic(
    code: str,
    message: str,
    text: str,
    source: str,
    start: int,
    line_starts: Sequence[int],
    *,
    capture_end: int | None = None,
) -> SourceDiagnostic:
    end = len(text) if capture_end is None else capture_end
    captured = text[start : min(end, start + MAX_ENTRY_CHARS)]
    return SourceDiagnostic(
        code=code,
        message=message,
        location=_location(source, start, line_starts),
        captured=captured,
    )


def _parse_calls(
    raw: str,
    source: str,
    source_start: int,
    form: str,
    line_starts: Sequence[int],
) -> list[MacroCall]:
    if form == "block":
        return _parse_block_calls(raw, source, source_start, line_starts)
    return _parse_macro_calls(raw, source, source_start, line_starts)


def _parse_macro_calls(
    raw: str,
    source: str,
    source_start: int,
    line_starts: Sequence[int],
) -> list[MacroCall]:
    calls: list[MacroCall] = []
    paren_depth = 1
    brace_depth = 0
    index = 1
    quote = False
    escaped = False
    comment = False

    while index < len(raw) - 1:
        char = raw[index]
        if comment:
            if char == "\n":
                comment = False
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            index += 1
            continue
        if char == ";" or raw.startswith("//", index):
            comment = True
            index += 1
            continue
        if char == '"':
            quote = True
            index += 1
            continue
        if char == "{":
            brace_depth += 1
            index += 1
            continue
        if char == "}":
            brace_depth -= 1
            index += 1
            continue
        if char == ")":
            paren_depth -= 1
            index += 1
            continue
        if char == "(":
            paren_depth += 1
            index += 1
            continue

        if paren_depth == 1 and brace_depth == 0 and _is_identifier_start(char):
            name_start = index
            index += 1
            while index < len(raw) and _is_identifier_part(raw[index]):
                index += 1
            name = raw[name_start:index]
            call_open = _skip_horizontal_space(raw, index)
            if call_open < len(raw) and raw[call_open] == "(":
                call_end = _matching_parenthesis(raw, call_open)
                if call_end is not None:
                    value = _clean_value(raw[call_open + 1 : call_end])
                    family, ordinal = _call_parts(name)
                    calls.append(
                        MacroCall(
                            name=name,
                            family=family,
                            ordinal=ordinal,
                            value=value,
                            location=_location(source, source_start + name_start, line_starts),
                        )
                    )
                    index = call_end + 1
                    continue
            continue
        index += 1
    return calls


def _parse_block_calls(
    raw: str,
    source: str,
    source_start: int,
    line_starts: Sequence[int],
) -> list[MacroCall]:
    calls: list[MacroCall] = []
    depth = 1
    index = 1
    quote = False
    escaped = False
    comment = False

    while index < len(raw) - 1:
        char = raw[index]
        if comment:
            if char == "\n":
                comment = False
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            index += 1
            continue
        if char == ";" or raw.startswith("//", index):
            comment = True
            index += 1
            continue
        if char == '"':
            quote = True
            index += 1
            continue
        if char == "}":
            depth -= 1
            index += 1
            continue
        if char != "{":
            index += 1
            continue

        depth += 1
        index += 1
        if depth != 2:
            continue
        name_start = _skip_space_and_comments(raw, index)
        if name_start >= len(raw) or not _is_identifier_start(raw[name_start]):
            continue
        name_end = name_start + 1
        while name_end < len(raw) and _is_identifier_part(raw[name_end]):
            name_end += 1
        value_start = _skip_space_and_comments(raw, name_end)
        value, _ = _block_value(raw, value_start)
        family, ordinal = _call_parts(raw[name_start:name_end])
        calls.append(
            MacroCall(
                name=raw[name_start:name_end],
                family=family,
                ordinal=ordinal,
                value=value,
                location=_location(source, source_start + name_start, line_starts),
            )
        )
        index = name_end
    return calls


def _definition_form(text: str, index: int) -> str | None:
    if index >= len(text):
        return None
    if text[index] == "{":
        token_start = _skip_space_and_comments(text, index + 1)
        if token_start >= len(text):
            return None
        if text[token_start] == '"':
            value, end = _quoted_value(text, token_start)
            return "block" if end is not None and value else None
        return "block" if _is_name_char(text[token_start]) else None
    if text[index] != "(":
        return None
    kind_start = _skip_space_and_comments(text, index + 1)
    if kind_start >= len(text) or text[kind_start] != '"':
        return None
    value, end = _quoted_value(text, kind_start)
    return "macro" if end is not None and value else None


def _find_recovery(text: str, index: int) -> int:
    cursor = index
    if cursor > 0 and text[cursor - 1] != "\n":
        newline = text.find("\n", cursor)
        cursor = len(text) if newline < 0 else newline + 1
    while cursor < len(text):
        candidate = cursor
        while candidate < len(text) and text[candidate] in " \t\r":
            candidate += 1
        if _recovery_definition_form(text, candidate) is not None:
            return candidate
        newline = text.find("\n", candidate)
        cursor = len(text) if newline < 0 else newline + 1
    return len(text)


def _recovery_definition_form(text: str, index: int) -> str | None:
    form = _definition_form(text, index)
    if form != "block":
        return form
    token_start = _skip_space_and_comments(text, index + 1)
    return form if token_start < len(text) and text[token_start] == '"' else None


def _macro_kind(raw: str) -> str:
    start = _skip_space_and_comments(raw, 1)
    value, _ = _quoted_value(raw, start)
    return value


def _block_name(raw: str) -> str:
    start = _skip_space_and_comments(raw, 1)
    if start < len(raw) and raw[start] == '"':
        value, _ = _quoted_value(raw, start)
        return value
    end = start
    while end < len(raw) and _is_name_char(raw[end]):
        end += 1
    return raw[start:end]


def _matching_parenthesis(text: str, open_index: int) -> int | None:
    depth = 1
    index = open_index + 1
    quote = False
    escaped = False
    comment = False
    while index < len(text):
        char = text[index]
        if comment:
            if char == "\n":
                comment = False
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            index += 1
            continue
        if char == ";" or text.startswith("//", index):
            comment = True
            index += 1
            continue
        if char == '"':
            quote = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _clean_value(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith('"'):
        unquoted, end = _quoted_value(cleaned, 0)
        if end == len(cleaned):
            return unquoted
    return cleaned


def _block_value(text: str, start: int) -> tuple[str, int]:
    if start >= len(text):
        return "", start
    if text[start] == '"':
        value, end = _quoted_value(text, start)
        return value, end if end is not None else len(text)
    end = start
    while end < len(text) and not text[end].isspace() and text[end] not in "{}":
        end += 1
    return text[start:end], end


def _quoted_value(text: str, start: int) -> tuple[str, int | None]:
    if start >= len(text) or text[start] != '"':
        return "", None
    chars: list[str] = []
    escaped = False
    index = start + 1
    while index < len(text):
        char = text[index]
        if escaped:
            chars.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            return "".join(chars), index + 1
        else:
            chars.append(char)
        index += 1
    return "".join(chars), None


def _call_parts(name: str) -> tuple[str, int | None]:
    split = len(name)
    while split > 0 and name[split - 1].isdigit():
        split -= 1
    family = name[:split].lower()
    ordinal = int(name[split:]) if split < len(name) else None
    return family, ordinal


def _skip_space_and_comments(text: str, index: int) -> int:
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        if text[index] == ";" or text.startswith("//", index):
            newline = text.find("\n", index)
            if newline < 0:
                return len(text)
            index = newline + 1
            continue
        break
    return index


def _skip_horizontal_space(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def _is_identifier_start(char: str) -> bool:
    return char.isalpha() or char == "_"


def _is_identifier_part(char: str) -> bool:
    return char.isalnum() or char == "_"


def _is_name_char(char: str) -> bool:
    return not char.isspace() and char not in '{}"'


def _line_starts(text: str) -> list[int]:
    starts = [0]
    starts.extend(index + 1 for index, char in enumerate(text) if char == "\n")
    return starts


def _location(source: str, index: int, line_starts: Sequence[int]) -> SourceLocation:
    line_index = bisect_right(line_starts, index) - 1
    return SourceLocation(
        source=source,
        line=line_index + 1,
        column=index - line_starts[line_index] + 1,
    )
