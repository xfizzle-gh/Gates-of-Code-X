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

_NATIVE_ID_RE = re.compile(
    r"^(?P<base>.*?)(?:\((?P<side>nato|ukr|rusa|prc|sov|csa|frg)\))?$",
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
    effective purchase ID as ``name(side)``. The manifest and research graph keep
    that effective ID while the rendered macro preserves the native base name.
    """

    side = str(actor["tactical_side"]).lower()
    cache: dict[Path, tuple[SourceEntry, ...]] = {}
    projected: list[ProjectedUnit] = []
    source_entry_names: set[str] = set()
    rendered_entries: list[str] = []

    for unit in sorted(actor["units"], key=lambda row: str(row["unit_name"])):
        unit_name = str(unit["unit_name"])
        if str(unit.get("tactical_side", "")).lower() != side:
            raise ExpandedNationsError(
                f"Actor {actor['actor_id']} unit {unit_name} targets "
                f"{unit.get('tactical_side')}, expected {side}"
            )
        if not unit.get("materializable"):
            raise ExpandedNationsError(f"Actor unit is not materializable: {unit_name}")
        for source_reference in unit.get("source_files", []):
            if _is_generated_source_reference(str(source_reference)):
                raise ExpandedNationsError(
                    f"Actor unit {unit_name} resolved from generated activation source "
                    f"{source_reference}"
                )

        if unit.get("virtual"):
            entry, source_reference = _find_virtual_source_entry(
                unit_name,
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

        source_key = f"{source_reference}:{entry.name}"
        if source_key in source_entry_names:
            raise ExpandedNationsError(
                f"Actor {actor['actor_id']} resolves multiple units to source entry "
                f"{entry.name}"
            )
        source_entry_names.add(source_key)

        source_raw = entry.raw.rstrip()
        rendered_name = (
            _native_macro_name(unit_name, side)
            if entry.form == "macro"
            else unit_name
        )
        renamed_raw = _rename_entry(source_raw, entry, rendered_name)
        projected_raw = _project_source_raw(
            renamed_raw,
            unit_name=unit_name,
            source_side=str(unit.get("source_side") or side).lower(),
            target_side=side,
        )
        projected_scan = scan_source_entries(projected_raw, f"generated:{unit_name}")
        if projected_scan.diagnostics or len(projected_scan.entries) != 1:
            raise ExpandedNationsError(
                f"Projected unit {unit_name} is not one valid GoH definition"
            )
        generated = projected_scan.entries[0]
        _verify_generated_identity(generated, unit_name, side)

        side_calls = [
            call.value.lower() for call in generated.calls if call.family == "side"
        ]
        if side_calls != [side]:
            raise ExpandedNationsError(
                f"Projected unit {unit_name} has tactical sides {side_calls}, "
                f"expected {side}"
            )

        source_hash = sha256_bytes(source_raw.encode("utf-8"))
        rendered_entries.append(
            f"; resolved_unit={unit_name}\n"
            f"; source_entry={entry.name}\n"
            f"; source={source_reference}\n"
            f"; source_sha256={source_hash}\n"
            f"{projected_raw}\n"
        )
        projected.append(
            ProjectedUnit(
                unit_name=unit_name,
                source_entry_name=entry.name,
                source_reference=source_reference,
                source_sha256=source_hash,
                projected_sha256=sha256_bytes(projected_raw.encode("utf-8")),
            )
        )

    return projected, "\n".join(rendered_entries).rstrip() + "\n"


def effective_purchase_id(entry: SourceEntry, side: str) -> str:
    """Return the native purchase ID represented by a parsed definition."""

    normalized_side = side.lower()
    if entry.form == "macro":
        if not entry.name:
            raise ExpandedNationsError("Native squad macro has no name(...) value")
        return f"{entry.name}({normalized_side})"
    return entry.name


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
            f"Native squad macro has an invalid canonical purchase ID: {unit_name}"
        )
    suffix = (match.group("side") or "").lower()
    normalized_side = side.lower()
    if suffix != normalized_side:
        raise ExpandedNationsError(
            f"Native squad macro {unit_name} must carry tactical suffix "
            f"({normalized_side})"
        )
    return str(match.group("base"))


def _verify_generated_identity(
    generated: SourceEntry,
    unit_name: str,
    side: str,
) -> None:
    actual = effective_purchase_id(generated, side)
    if actual != unit_name:
        raise ExpandedNationsError(
            f"Projected unit ID {actual!r} does not match canonical ID {unit_name!r}"
        )
