from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .expanded_nations_models import (
    ExpandedNationsError,
    ProjectedUnit,
    sha256_bytes,
)
from .expanded_nations_sources import (
    _entries_for_path,
    _entry_name_matches,
    _find_source_entry,
    _is_generated_source_reference,
    _project_source_raw,
    _rename_entry,
)
from .goh_source import SourceEntry, scan_source_entries
from .modstack import resource_root

_NATIVE_ID_RE = re.compile(
    r"^(?P<base>.*?)(?:\((?P<side>nato|ukr|rusa|prc|sov|csa|frg|goc_[a-z0-9_]+)\))?$",
    re.IGNORECASE,
)
_DEFINE_START_RE = re.compile(
    r'(?im)^[ \t]*\(define[ \t\r\n]+"(?P<name>[^"\r\n]+)"'
)
_WRAPPER_RELATIVE = Path(
    "resource/set/multiplayer/units/conquest/units_goc_national_wrappers.set"
)
_DEFINITION_SUFFIXES = {".set", ".inc", ".goh"}
_REQUIRED_DEFINITION_PREFIXES = ("dp_", "doctrine_", "generic_dp_")


@dataclass(frozen=True, slots=True)
class ParenthesizedDefine:
    name: str
    raw: str
    dependencies: tuple[str, ...]
    source_reference: str
    priority: int
    relative_path: str
    line: int


def project_actor_units(
    actor: Mapping[str, Any],
    roots: Sequence[Path],
    gates_root: Path,
) -> tuple[list[ProjectedUnit], str]:
    """Project actor purchases using native block and macro ID semantics.

    Block definitions carry their complete purchase ID in the outer quoted name.
    Top-level squad macros carry only the base name; Gates of Hell derives their
    effective purchase ID as ``name(side)``. Projected units therefore record the
    effective ID even when the compiler catalog stored only the macro base name.

    Doctrine purchase blocks may depend on parenthesized ``(define "..." ...)``
    declarations stored in a different file from the purchase. Resolve those
    definitions through deterministic installed-stack precedence, preserve only
    the recursive closure not already supplied by the effective Conquest settings
    file, and emit dependencies before purchases.
    """

    side = str(actor["tactical_side"]).lower()
    cache: dict[Path, tuple[SourceEntry, ...]] = {}
    definition_index = _scan_stack_definitions(roots)
    baseline_definitions = _baseline_definition_names(roots)
    projected: list[ProjectedUnit] = []
    source_entry_names: set[str] = set()
    projected_ids: set[str] = set()
    rendered_entries: list[str] = []
    define_order: list[str] = []
    definitions: dict[str, ParenthesizedDefine] = {}

    for unit in sorted(actor["units"], key=lambda row: str(row["unit_name"])):
        actor_unit_name = str(unit["unit_name"])
        source_side = str(unit.get("source_side") or side).lower()
        if str(unit.get("tactical_side", "")).lower() != side:
            raise ExpandedNationsError(
                f"Actor {actor['actor_id']} unit {actor_unit_name} targets "
                f"{unit.get('tactical_side')}, expected {side}"
            )
        if not unit.get("materializable"):
            raise ExpandedNationsError(
                f"Actor unit is not materializable: {actor_unit_name}"
            )
        for source_reference in unit.get("source_files", []):
            if _is_generated_source_reference(str(source_reference)):
                raise ExpandedNationsError(
                    f"Actor unit {actor_unit_name} resolved from generated "
                    f"activation source {source_reference}"
                )

        if unit.get("virtual"):
            entry, source_reference = _find_virtual_source_entry(
                actor_unit_name,
                source_side,
                gates_root,
                cache,
            )
        else:
            entry, source_reference = _find_source_entry(
                unit,
                roots,
                gates_root,
                cache,
            )
            for dependency in _required_define_entries(
                entry,
                definition_index,
                baseline_definitions,
            ):
                previous = definitions.get(dependency.name)
                if previous is None:
                    definitions[dependency.name] = dependency
                    define_order.append(dependency.name)
                elif previous.raw.rstrip() != dependency.raw.rstrip():
                    raise ExpandedNationsError(
                        f"Actor {actor['actor_id']} required define "
                        f"{dependency.name!r} conflicts between "
                        f"{previous.source_reference} and "
                        f"{dependency.source_reference}"
                    )

        source_key = f"{source_reference}:{entry.name}"
        if source_key in source_entry_names:
            raise ExpandedNationsError(
                f"Actor {actor['actor_id']} resolves multiple units to source "
                f"entry {entry.name}"
            )
        source_entry_names.add(source_key)

        if entry.form == "macro":
            rendered_name = _native_macro_name(actor_unit_name, side)
            projected_unit_name = f"{rendered_name}({side})"
        else:
            # Block purchase IDs carry the full effective ID in the quoted name.
            # Remap a source-side parenthetical onto the target engine army token.
            match = _NATIVE_ID_RE.fullmatch(actor_unit_name)
            if (
                match
                and match.group("base")
                and match.group("side")
                and match.group("side").lower() != side.lower()
            ):
                projected_unit_name = f"{match.group('base')}({side})"
            else:
                projected_unit_name = actor_unit_name
            rendered_name = projected_unit_name
        if projected_unit_name in projected_ids:
            raise ExpandedNationsError(
                f"Actor {actor['actor_id']} projects duplicate native purchase "
                f"ID {projected_unit_name}"
            )
        projected_ids.add(projected_unit_name)

        source_raw = entry.raw.rstrip()
        renamed_raw = _rename_entry(source_raw, entry, rendered_name)
        projected_raw = _project_source_raw(
            renamed_raw,
            unit_name=projected_unit_name,
            source_side=source_side,
            target_side=side,
        )
        projected_scan = scan_source_entries(
            projected_raw,
            f"generated:{projected_unit_name}",
        )
        if projected_scan.diagnostics or len(projected_scan.entries) != 1:
            raise ExpandedNationsError(
                f"Projected unit {projected_unit_name} is not one valid GoH definition"
            )
        generated = projected_scan.entries[0]
        _verify_generated_identity(
            generated,
            projected_unit_name,
            side,
        )

        side_calls = [
            call.value.lower() for call in generated.calls if call.family == "side"
        ]
        if side_calls != [side]:
            raise ExpandedNationsError(
                f"Projected unit {projected_unit_name} has tactical sides "
                f"{side_calls}, expected {side}"
            )

        source_hash = sha256_bytes(source_raw.encode("utf-8"))
        actor_alias = (
            ""
            if actor_unit_name == projected_unit_name
            else f"; actor_unit={actor_unit_name}\n"
        )
        rendered_entries.append(
            f"; resolved_unit={projected_unit_name}\n"
            f"{actor_alias}"
            f"; source_entry={entry.name}\n"
            f"; source={source_reference}\n"
            f"; source_sha256={source_hash}\n"
            f"{projected_raw}\n"
        )
        projected.append(
            ProjectedUnit(
                unit_name=projected_unit_name,
                source_entry_name=entry.name,
                source_reference=source_reference,
                source_sha256=source_hash,
                projected_sha256=sha256_bytes(projected_raw.encode("utf-8")),
            )
        )

    rendered_definitions = [
        f"; source_define={define_name}\n"
        f"; source={definitions[define_name].source_reference}\n"
        f"; source_define_sha256="
        f"{sha256_bytes(definitions[define_name].raw.rstrip().encode('utf-8'))}\n"
        f"{definitions[define_name].raw.rstrip()}\n"
        for define_name in define_order
    ]
    body_parts = [*rendered_definitions, *rendered_entries]
    return projected, "\n".join(body_parts).rstrip() + "\n"


def normalize_actor_purchase_ids(
    actor: Mapping[str, Any],
    projected_units: Sequence[ProjectedUnit],
) -> dict[str, Any]:
    """Return an actor view whose units and research use native purchase IDs."""

    ordered_units = sorted(
        actor["units"],
        key=lambda row: str(row["unit_name"]),
    )
    if len(ordered_units) != len(projected_units):
        raise ExpandedNationsError(
            f"Actor {actor['actor_id']} cannot normalize mismatched unit counts"
        )
    mapping = {
        str(row["unit_name"]): projected.unit_name
        for row, projected in zip(ordered_units, projected_units, strict=True)
    }
    if len(set(mapping.values())) != len(mapping):
        raise ExpandedNationsError(
            f"Actor {actor['actor_id']} native purchase normalization collides"
        )

    normalized = dict(actor)
    normalized["units"] = [
        {
            **dict(row),
            "unit_name": mapping[str(row["unit_name"])],
        }
        for row in actor["units"]
    ]
    normalized["research_nodes"] = [
        {
            **dict(node),
            "unlock_units": [
                mapping.get(str(unit_name), str(unit_name))
                for unit_name in node.get("unlock_units", [])
            ],
        }
        for node in actor["research_nodes"]
    ]
    return normalized


def effective_purchase_id(entry: SourceEntry, side: str) -> str:
    """Return the native purchase ID represented by a parsed definition."""

    normalized_side = side.lower()
    if entry.form == "macro":
        if not entry.name:
            raise ExpandedNationsError("Native squad macro has no name(...) value")
        return f"{entry.name}({normalized_side})"
    return entry.name


def scan_parenthesized_defines(
    text: str,
    source_reference: str,
    *,
    priority: int = 0,
    relative_path: str = "",
) -> tuple[ParenthesizedDefine, ...]:
    """Collect bounded top-level ``(define "name" ...)`` declarations."""

    definitions: list[ParenthesizedDefine] = []
    cursor = 0
    while True:
        match = _DEFINE_START_RE.search(text, cursor)
        if match is None:
            break
        start = text.find("(", match.start(), match.end())
        if start < 0:
            raise ExpandedNationsError(
                f"Malformed parenthesized define header in {source_reference}"
            )
        end = _capture_parenthesized(text, start, source_reference)
        raw = text[start:end]
        definitions.append(
            ParenthesizedDefine(
                name=str(match.group("name")),
                raw=raw,
                dependencies=quoted_macro_names(raw),
                source_reference=source_reference,
                priority=priority,
                relative_path=relative_path,
                line=text.count("\n", 0, start) + 1,
            )
        )
        cursor = end
    return tuple(definitions)


def quoted_macro_names(raw: str) -> tuple[str, ...]:
    """Return quoted macro invocations from one GoH block in source order."""

    names: list[str] = []
    seen: set[str] = set()
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
            index += 1
            continue
        if char == '"':
            quote = True
            index += 1
            continue
        if char != "(":
            index += 1
            continue

        token = index + 1
        while token < len(raw) and raw[token].isspace():
            token += 1
        if token >= len(raw) or raw[token] != '"':
            index += 1
            continue
        token += 1
        value: list[str] = []
        escaped_token = False
        while token < len(raw):
            current = raw[token]
            if escaped_token:
                value.append(current)
                escaped_token = False
            elif current == "\\":
                escaped_token = True
            elif current == '"':
                break
            else:
                value.append(current)
            token += 1
        if token >= len(raw):
            raise ExpandedNationsError("Quoted macro invocation is unterminated")
        name = "".join(value)
        if name and name not in seen:
            seen.add(name)
            names.append(name)
        index = token + 1
    return tuple(names)


def definition_requires_projection(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith(_REQUIRED_DEFINITION_PREFIXES)


def _capture_parenthesized(
    text: str,
    start: int,
    source_reference: str,
) -> int:
    depth = 0
    quote = False
    escaped = False
    comment = False
    index = start
    while index < len(text):
        if index - start >= 1_000_000:
            raise ExpandedNationsError(
                f"Parenthesized define is too large in {source_reference}"
            )
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
            depth += 1
            if depth > 256:
                raise ExpandedNationsError(
                    f"Parenthesized define nesting is too deep in {source_reference}"
                )
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
            if depth < 0:
                break
        index += 1
    raise ExpandedNationsError(
        f"Parenthesized define is unterminated in {source_reference}"
    )


def _scan_stack_definitions(
    roots: Sequence[Path],
) -> dict[str, tuple[ParenthesizedDefine, ...]]:
    by_name: dict[str, list[ParenthesizedDefine]] = {}
    for priority, root in enumerate(roots):
        resource = resource_root(root)
        units_root = resource / "set/multiplayer/units"
        if not units_root.is_dir():
            continue
        paths = sorted(
            (
                path
                for path in units_root.rglob("*")
                if path.is_file() and path.suffix.lower() in _DEFINITION_SUFFIXES
            ),
            key=lambda path: path.as_posix().lower(),
        )
        for path in paths:
            relative = path.relative_to(resource).as_posix()
            reference = f"{priority}:{root.name}/{relative}"
            if _is_generated_source_reference(reference):
                continue
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ExpandedNationsError(
                    f"Cannot decode definition source {reference}"
                ) from exc
            for definition in scan_parenthesized_defines(
                text,
                reference,
                priority=priority,
                relative_path=relative,
            ):
                by_name.setdefault(definition.name, []).append(definition)
    return {name: tuple(rows) for name, rows in by_name.items()}


def _baseline_definition_names(roots: Sequence[Path]) -> frozenset[str]:
    relative = Path("set/multiplayer/units/conquest/settings.set")
    for priority in range(len(roots) - 1, -1, -1):
        root = roots[priority]
        resource = resource_root(root)
        path = resource / relative
        if not path.is_file():
            continue
        reference = f"{priority}:{root.name}/{relative.as_posix()}"
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ExpandedNationsError(
                f"Cannot decode effective Conquest settings {reference}"
            ) from exc
        return frozenset(
            definition.name
            for definition in scan_parenthesized_defines(
                text,
                reference,
                priority=priority,
                relative_path=relative.as_posix(),
            )
        )
    return frozenset()


def _required_define_entries(
    purchase: SourceEntry,
    index: Mapping[str, tuple[ParenthesizedDefine, ...]],
    baseline_definitions: frozenset[str],
) -> tuple[ParenthesizedDefine, ...]:
    ordered: list[ParenthesizedDefine] = []
    required: set[str] = set()
    active: list[str] = []

    def visit(name: str) -> None:
        if name in baseline_definitions or name in required:
            return
        candidates = index.get(name, ())
        if not candidates:
            if definition_requires_projection(name):
                chain = " -> ".join([*active, name])
                raise ExpandedNationsError(
                    f"Required purchase define is missing from the effective stack: "
                    f"{chain}"
                )
            return
        if name in active:
            chain = " -> ".join([*active, name])
            raise ExpandedNationsError(
                f"Parenthesized define dependency cycle: {chain}"
            )
        selected = _effective_define(name, candidates)
        active.append(name)
        for dependency in selected.dependencies:
            visit(dependency)
        active.pop()
        required.add(name)
        ordered.append(selected)

    for macro_name in quoted_macro_names(purchase.raw):
        visit(macro_name)
    return tuple(ordered)


def _effective_define(
    name: str,
    candidates: Sequence[ParenthesizedDefine],
) -> ParenthesizedDefine:
    highest = max(row.priority for row in candidates)
    effective = [row for row in candidates if row.priority == highest]
    raw_by_value: dict[str, list[ParenthesizedDefine]] = {}
    for row in effective:
        raw_by_value.setdefault(row.raw.rstrip(), []).append(row)
    if len(raw_by_value) != 1:
        locations = ", ".join(
            f"{row.source_reference}:{row.line}"
            for row in sorted(
                effective,
                key=lambda item: (
                    item.relative_path.lower(),
                    item.line,
                ),
            )
        )
        raise ExpandedNationsError(
            f"Effective stack defines {name!r} with conflicting bodies: "
            f"{locations}"
        )
    return sorted(
        effective,
        key=lambda row: (row.relative_path.lower(), row.line),
    )[0]


def _find_virtual_source_entry(
    unit_name: str,
    source_side: str,
    gates_root: Path,
    cache: dict[Path, tuple[SourceEntry, ...]],
) -> tuple[SourceEntry, str]:
    wrapper_path = gates_root / _WRAPPER_RELATIVE
    entries = _entries_for_path(wrapper_path, cache)
    matches = [
        entry
        for entry in entries
        if _entry_name_matches(entry.name, unit_name, source_side)
    ]
    if len(matches) != 1:
        raise ExpandedNationsError(
            f"Virtual unit {unit_name} requires exactly one committed native wrapper"
        )
    entry = matches[0]
    if entry.form != "macro" or not entry.macro_kind.lower().startswith("squad_with"):
        raise ExpandedNationsError(
            f"Virtual unit {unit_name} must use one top-level squad_with* macro"
        )
    return (
        entry,
        "gates:resource/set/multiplayer/units/conquest/units_goc_national_wrappers.set",
    )


def _native_macro_name(unit_name: str, side: str) -> str:
    match = _NATIVE_ID_RE.fullmatch(unit_name)
    if match is None or not match.group("base"):
        raise ExpandedNationsError(
            f"Native squad macro has an invalid catalog ID: {unit_name}"
        )
    suffix = (match.group("side") or "").lower()
    normalized_side = side.lower()
    if suffix and suffix != normalized_side:
        # Catalog IDs often retain the source-side parenthetical (e.g. squad_arf_rifle(nato))
        # while production GOC armies project onto a distinct engine token (goc_bel).
        # Allow stripping a core/historical source suffix when the target side differs.
        from .goc_tactical_army_registry import CORE_TACTICAL_SIDES, is_goc_tactical_side

        source_sides = set(CORE_TACTICAL_SIDES) | {"sov", "csa", "frg"}
        if not (
            suffix in source_sides
            and (is_goc_tactical_side(normalized_side) or normalized_side in source_sides)
        ):
            raise ExpandedNationsError(
                f"Native squad macro {unit_name} conflicts with tactical side "
                f"{normalized_side}"
            )
    return str(match.group("base"))


def _verify_generated_identity(
    generated: SourceEntry,
    projected_unit_name: str,
    side: str,
) -> None:
    actual = effective_purchase_id(generated, side)
    if actual != projected_unit_name:
        raise ExpandedNationsError(
            f"Projected unit ID {actual!r} does not match canonical native ID "
            f"{projected_unit_name!r}"
        )
