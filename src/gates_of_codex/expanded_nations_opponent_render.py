from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .expanded_nations_models import (
    BROAD_ROSTER_INCLUDES,
    ExpandedNationsError,
    ProjectedOpponentUnit,
    SUPPORTED_TACTICAL_SIDES,
    sha256_bytes,
)
from .expanded_nations_opponents import (
    _canonical_entry_side,
    _effective_include_path,
    _walk_effective_include,
)
from .goh_source import (
    SourceEntry,
    _definition_form,
    _matching_parenthesis,
    scan_source_entries,
)


def project_opponent_units(
    selected_side: str,
    roots: Sequence[Path],
) -> tuple[list[ProjectedOpponentUnit], str]:
    """Flatten, filter, and canonicalize opponent purchase definitions.

    The resolver classifies every source entry by the compiler authority order:
    name suffix, explicit side call, then source filename. When that authority
    infers a non-empty side without an explicit ``side(...)`` call, the emitted
    definition receives one. This keeps the generated artifact self-contained
    and lets semantic verification prove the same side without consulting the
    original source tree.
    """

    if selected_side not in SUPPORTED_TACTICAL_SIDES:
        raise ExpandedNationsError(f"Unsupported selected tactical side: {selected_side}")

    projected: list[ProjectedOpponentUnit] = []
    rendered_entries: list[str] = []
    cache: dict[Path, tuple[object, ...]] = {}

    for include in BROAD_ROSTER_INCLUDES:
        if _effective_include_path(include, roots) is None:
            continue
        for entry, source_path, priority, source_reference, ordinal in _walk_effective_include(
            include,
            roots,
            cache,  # type: ignore[arg-type]
            active=(),
        ):
            entry_side = _canonical_entry_side(entry, source_path)
            if entry_side == selected_side:
                continue

            source_raw = entry.raw.rstrip()
            projected_raw = _materialize_side(entry, source_raw, entry_side)
            source_hash = sha256_bytes(source_raw.encode("utf-8"))
            projected_hash = sha256_bytes(projected_raw.encode("utf-8"))
            rendered_entries.append(
                f"; opponent_source={source_reference}\n"
                f"; opponent_ordinal={ordinal}\n"
                f"; opponent_side={entry_side or 'shared'}\n"
                f"; source_sha256={source_hash}\n"
                f"; projected_sha256={projected_hash}\n"
                f"{projected_raw}\n"
            )
            projected.append(
                ProjectedOpponentUnit(
                    entry_name=entry.name,
                    tactical_side=entry_side,
                    source_reference=source_reference,
                    source_sha256=source_hash,
                    projected_sha256=projected_hash,
                )
            )

    return projected, "\n".join(rendered_entries).rstrip() + "\n"


def _materialize_side(entry: SourceEntry, raw: str, side: str) -> str:
    explicit = [call.value.lower() for call in entry.calls if call.family == "side"]
    if len(explicit) > 1:
        raise ExpandedNationsError(
            f"Opponent entry {entry.name!r} has multiple side declarations"
        )
    if explicit:
        if explicit != [side]:
            raise ExpandedNationsError(
                f"Opponent entry {entry.name!r} explicit side {explicit[0]!r} "
                f"disagrees with canonical side {side!r}"
            )
        return raw
    if not side:
        return raw

    if entry.form == "macro":
        close = _matching_parenthesis(raw, 0)
        if close is None:
            raise ExpandedNationsError(
                f"Opponent macro {entry.name!r} has no matching closing parenthesis"
            )
        projected = _insert_side(raw, close, side)
    elif entry.form == "block":
        start = _first_direct_macro(raw)
        if start is None:
            raise ExpandedNationsError(
                f"Opponent block {entry.name!r} has no direct purchase macro for side materialization"
            )
        close = _matching_parenthesis(raw, start)
        if close is None:
            raise ExpandedNationsError(
                f"Opponent block {entry.name!r} has an unterminated purchase macro"
            )
        projected = _insert_side(raw, close, side)
    else:
        raise ExpandedNationsError(
            f"Opponent entry {entry.name!r} has unsupported source form {entry.form!r}"
        )

    scan = scan_source_entries(projected, f"generated-opponent:{entry.name}")
    if scan.diagnostics or len(scan.entries) != 1:
        raise ExpandedNationsError(
            f"Opponent entry {entry.name!r} became malformed while materializing side {side}"
        )
    generated = scan.entries[0]
    generated_sides = [
        call.value.lower() for call in generated.calls if call.family == "side"
    ]
    if generated.name != entry.name or generated_sides != [side]:
        raise ExpandedNationsError(
            f"Opponent entry {entry.name!r} failed side materialization: {generated_sides}"
        )
    return projected


def _insert_side(raw: str, close: int, side: str) -> str:
    prefix = raw[:close]
    separator = "" if prefix.endswith((" ", "\t", "\r", "\n")) else " "
    return f"{prefix}{separator}side({side}){raw[close:]}"


def _first_direct_macro(raw: str) -> int | None:
    brace_depth = 0
    paren_depth = 0
    index = 0
    quote = False
    escaped = False
    comment = False

    while index < len(raw):
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
            index += 2 if raw.startswith("//", index) else 1
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
            brace_depth = max(0, brace_depth - 1)
            index += 1
            continue
        if char == "(":
            if (
                brace_depth == 1
                and paren_depth == 0
                and _definition_form(raw, index) == "macro"
            ):
                return index
            paren_depth += 1
            index += 1
            continue
        if char == ")":
            paren_depth = max(0, paren_depth - 1)
        index += 1

    return None
