from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterator, Sequence

from .expanded_nations_models import (
    BROAD_ROSTER_INCLUDES,
    ExpandedNationsError,
    ProjectedOpponentUnit,
    supported_tactical_sides,
    sha256_bytes,
)
from .faction_wiring_scan import _side_from_filename, _side_from_name
from .goh_source import SourceEntry, scan_source_entries
from .modstack import resource_root

_INCLUDE_AT_RE = re.compile(r'\(\s*include\s+"([^"]+)"\s*\)', re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _OrderedItem:
    line: int
    column: int
    entry: SourceEntry | None = None
    include: str = ""


def project_opponent_units(
    selected_side: str,
    roots: Sequence[Path],
) -> tuple[list[ProjectedOpponentUnit], str]:
    """Flatten and filter the effective broad roster include graph.

    Side resolution is exactly the compiler scanner's authority order:
    name suffix, explicit side call, then source filename. Include directives
    are never copied into the generated file. They are resolved through layer
    precedence, recursively flattened, and filtered entry by entry so a
    side-less include cannot reintroduce the selected tactical side.
    """

    if selected_side not in supported_tactical_sides():
        raise ExpandedNationsError(f"Unsupported selected tactical side: {selected_side}")
    projected: list[ProjectedOpponentUnit] = []
    rendered_entries: list[str] = []
    cache: dict[Path, tuple[_OrderedItem, ...]] = {}

    for include in BROAD_ROSTER_INCLUDES:
        if _effective_include_path(include, roots) is None:
            continue
        for entry, source_path, priority, source_reference, ordinal in _walk_effective_include(
            include,
            roots,
            cache,
            active=(),
        ):
            entry_side = _canonical_entry_side(entry, source_path)
            if entry_side == selected_side:
                continue
            raw = entry.raw.rstrip()
            source_hash = sha256_bytes(raw.encode("utf-8"))
            rendered_entries.append(
                f"; opponent_source={source_reference}\n"
                f"; opponent_ordinal={ordinal}\n"
                f"; opponent_side={entry_side or 'shared'}\n"
                f"; source_sha256={source_hash}\n"
                f"{raw}\n"
            )
            projected.append(
                ProjectedOpponentUnit(
                    entry_name=entry.name,
                    tactical_side=entry_side,
                    source_reference=source_reference,
                    source_sha256=source_hash,
                    projected_sha256=source_hash,
                )
            )
    return projected, "\n".join(rendered_entries).rstrip() + "\n"


def _walk_effective_include(
    include: str,
    roots: Sequence[Path],
    cache: dict[Path, tuple[_OrderedItem, ...]],
    *,
    active: tuple[Path, ...],
) -> Iterator[tuple[SourceEntry, Path, int, str, int]]:
    normalized = include.replace("\\", "/").lstrip("/")
    include_path = Path(normalized)
    if not normalized or include_path.is_absolute() or ".." in include_path.parts:
        raise ExpandedNationsError(f"Unsafe opponent roster include: {include}")
    effective = _effective_include_path(normalized, roots)
    if effective is None:
        raise ExpandedNationsError(f"Nested opponent roster include cannot be resolved: {include}")
    source_path, priority = effective
    resolved = source_path.resolve()
    if resolved in active:
        chain = " -> ".join(str(path) for path in (*active, resolved))
        raise ExpandedNationsError(f"Opponent roster include cycle: {chain}")

    relative = source_path.relative_to(resource_root(roots[priority])).as_posix()
    source_reference = f"{priority}:{roots[priority].name}/{relative}"
    ordinal = 0
    for item in _ordered_items(source_path, cache):
        if item.include:
            yield from _walk_effective_include(
                item.include,
                roots,
                cache,
                active=(*active, resolved),
            )
            continue
        entry = item.entry
        if entry is None or not entry.name:
            raise ExpandedNationsError(
                f"Unnamed opponent roster entry cannot be filtered safely: {source_path}:{item.line}"
            )
        yield entry, source_path, priority, source_reference, ordinal
        ordinal += 1


def _ordered_items(
    path: Path,
    cache: dict[Path, tuple[_OrderedItem, ...]],
) -> tuple[_OrderedItem, ...]:
    resolved = path.resolve()
    if resolved in cache:
        return cache[resolved]
    text = resolved.read_text(encoding="utf-8-sig", errors="replace")
    scan = scan_source_entries(text, str(resolved))
    if scan.diagnostics:
        raise ExpandedNationsError(
            f"Source file has parser diagnostics and cannot be projected: {resolved}: "
            + "; ".join(item.message for item in scan.diagnostics)
        )
    items = [
        _OrderedItem(entry.location.line, entry.location.column, entry=entry)
        for entry in scan.entries
    ]
    items.extend(
        _OrderedItem(line, column, include=value)
        for line, column, value in _top_level_includes(text)
    )
    ordered = tuple(sorted(items, key=lambda item: (item.line, item.column, not bool(item.include))))
    cache[resolved] = ordered
    return ordered


def _top_level_includes(text: str) -> list[tuple[int, int, str]]:
    result: list[tuple[int, int, str]] = []
    index = 0
    line = 1
    column = 1
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
            line, column = _advance_position(char, line, column)
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            line, column = _advance_position(char, line, column)
            index += 1
            continue
        if char == ";" or text.startswith("//", index):
            comment = True
            if text.startswith("//", index):
                index += 1
                column += 1
            line, column = _advance_position(char, line, column)
            index += 1
            continue
        if char == '"':
            quote = True
            line, column = _advance_position(char, line, column)
            index += 1
            continue
        if paren_depth == 0 and brace_depth == 0 and char == "(":
            match = _INCLUDE_AT_RE.match(text, index)
            if match is not None:
                result.append((line, column, match.group(1)))
                consumed = match.group(0)
                for consumed_char in consumed:
                    line, column = _advance_position(consumed_char, line, column)
                index = match.end()
                continue
        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth = max(0, paren_depth - 1)
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth = max(0, brace_depth - 1)
        line, column = _advance_position(char, line, column)
        index += 1
    return result


def _advance_position(char: str, line: int, column: int) -> tuple[int, int]:
    return (line + 1, 1) if char == "\n" else (line, column + 1)


def _canonical_entry_side(entry: SourceEntry, source_path: Path) -> str:
    explicit = [call.value.lower() for call in entry.calls if call.family == "side"]
    if len(explicit) > 1:
        raise ExpandedNationsError(
            f"Core roster entry {entry.name!r} in {source_path} has multiple side declarations"
        )
    return _side_from_name(entry.name) or (explicit[0] if explicit else "") or _side_from_filename(
        source_path.name
    )


def _effective_include_path(include: str, roots: Sequence[Path]) -> tuple[Path, int] | None:
    for priority in range(len(roots) - 1, -1, -1):
        candidate = resource_root(roots[priority]) / "set/multiplayer/units" / include
        if candidate.is_file():
            return candidate, priority
    return None
