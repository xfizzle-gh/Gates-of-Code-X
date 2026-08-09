from __future__ import annotations

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
    r"^(?P<base>.*?)(?:\((?P<side>nato|ukr|rusa|prc|sov|csa|frg)\))?$",
    re.IGNORECASE,
)
_SOURCE_REFERENCE_RE = re.compile(r"^(\d+):[^/]+/(.+)$")
_DEFINE_HEADER_RE = re.compile(
    r'^\s*\{\s*define\s+(?:"(?P<quoted>[^"]+)"|(?P<bare>[^\s{}]+))',
    re.IGNORECASE,
)
_WRAPPER_RELATIVE = Path(
    "resource/set/multiplayer/units/conquest/units_goc_national_wrappers.set"
)


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

    Some upstream purchase blocks invoke source-local macros declared through
    ``{define ...}`` blocks in the same source file. Those declarations are part
    of the native purchase contract. Preserve only the recursive dependency
    closure required by selected purchases, keep source order, deduplicate
    byte-identical declarations, and fail closed if selected source files assign
    different bodies to the same required define name.
    """

    side = str(actor["tactical_side"]).lower()
    cache: dict[Path, tuple[SourceEntry, ...]] = {}
    projected: list[ProjectedUnit] = []
    source_entry_names: set[str] = set()
    projected_ids: set[str] = set()
    rendered_entries: list[str] = []
    define_order: list[str] = []
    definitions: dict[str, tuple[str, str]] = {}

    for unit in sorted(actor["units"], key=lambda row: str(row["unit_name"])):
        actor_unit_name = str(unit["unit_name"])
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
                side,
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
            source_path = _source_path_from_reference(source_reference, roots)
            for dependency in _required_define_entries(entry, source_path, cache):
                define_name = defined_macro_name(dependency.raw)
                define_raw = dependency.raw.rstrip()
                previous = definitions.get(define_name)
                if previous is None:
                    definitions[define_name] = (define_raw, source_reference)
                    define_order.append(define_name)
                elif previous[0] != define_raw:
                    raise ExpandedNationsError(
                        f"Actor {actor['actor_id']} source-local define "
                        f"{define_name!r} conflicts between {previous[1]} and "
                        f"{source_reference}"
                    )

        source_key = f"{source_reference}:{entry.name}"
        if source_key in source_entry_names:
            raise ExpandedNationsError(
                f"Actor {actor['actor_id']} resolves multiple units to source "
                f"entry {entry.name}"
            )
        source_entry_names.add(source_key)

        rendered_name = (
            _native_macro_name(actor_unit_name, side)
            if entry.form == "macro"
            else actor_unit_name
        )
        projected_unit_name = (
            f"{rendered_name}({side})"
            if entry.form == "macro"
            else actor_unit_name
        )
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
            source_side=str(unit.get("source_side") or side).lower(),
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
        f"; source={definitions[define_name][1]}\n"
        f"; source_define_sha256="
        f"{sha256_bytes(definitions[define_name][0].encode('utf-8'))}\n"
        f"{definitions[define_name][0]}\n"
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


def defined_macro_name(raw: str) -> str:
    """Return the declared name of one source-local ``{define ...}`` block."""

    match = _DEFINE_HEADER_RE.match(raw)
    if match is None:
        return ""
    return str(match.group("quoted") or match.group("bare") or "")


def _required_define_entries(
    purchase: SourceEntry,
    path: Path,
    cache: dict[Path, tuple[SourceEntry, ...]],
) -> tuple[SourceEntry, ...]:
    """Return source-ordered local defines reachable from one purchase."""

    ordered: list[tuple[str, SourceEntry]] = []
    by_name: dict[str, SourceEntry] = {}
    for entry in _define_entries_for_path(path, cache):
        name = defined_macro_name(entry.raw)
        if not name:
            raise ExpandedNationsError(f"Source define in {path} has no macro name")
        previous = by_name.get(name)
        if previous is None:
            by_name[name] = entry
            ordered.append((name, entry))
        elif previous.raw.rstrip() != entry.raw.rstrip():
            raise ExpandedNationsError(
                f"Source file {path} defines {name!r} with conflicting bodies"
            )

    required: set[str] = set()
    active: set[str] = set()

    def visit(name: str) -> None:
        if name not in by_name or name in required:
            return
        if name in active:
            raise ExpandedNationsError(
                f"Source-local define dependency cycle in {path}: {name}"
            )
        active.add(name)
        dependency = by_name[name]
        visit(dependency.macro_kind)
        active.remove(name)
        required.add(name)

    visit(purchase.macro_kind)
    return tuple(entry for name, entry in ordered if name in required)


def _define_entries_for_path(
    path: Path,
    cache: dict[Path, tuple[SourceEntry, ...]],
) -> tuple[SourceEntry, ...]:
    return tuple(
        entry
        for entry in _entries_for_path(path, cache)
        if entry.form == "block" and entry.name.lower() == "define"
    )


def _source_path_from_reference(
    source_reference: str,
    roots: Sequence[Path],
) -> Path:
    match = _SOURCE_REFERENCE_RE.fullmatch(source_reference)
    if match is None:
        raise ExpandedNationsError(
            f"Cannot resolve source-local defines for {source_reference}"
        )
    priority = int(match.group(1))
    if priority < 0 or priority >= len(roots):
        raise ExpandedNationsError(
            f"Source-local define priority is invalid: {source_reference}"
        )
    path = resource_root(roots[priority]) / match.group(2)
    if not path.is_file():
        raise ExpandedNationsError(
            f"Source-local define file is missing: {source_reference}"
        )
    return path


def _find_virtual_source_entry(
    unit_name: str,
    side: str,
    gates_root: Path,
    cache: dict[Path, tuple[SourceEntry, ...]],
) -> tuple[SourceEntry, str]:
    wrapper_path = gates_root / _WRAPPER_RELATIVE
    entries = _entries_for_path(wrapper_path, cache)
    matches = [
        entry
        for entry in entries
        if _entry_name_matches(entry.name, unit_name, side)
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
