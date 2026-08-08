from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .goh_source import SourceEntry, scan_source_entries
from .modstack import resource_root
from .expanded_nations_models import ExpandedNationsError, ProjectedUnit, sha256_bytes

_SOURCE_REFERENCE_RE = re.compile(r"^(\d+):([^/]+)/(.+)$")
_SIDE_CALL_RE = re.compile(r"\bside\s*\(\s*[^)]*\)", re.IGNORECASE)
_FACTION_SUFFIX_RE = re.compile(r"\((?:nato|ukr|rusa|prc|sov|csa|frg)\)$", re.IGNORECASE)


def project_actor_units(
    actor: Mapping[str, Any],
    roots: Sequence[Path],
    gates_root: Path,
) -> tuple[list[ProjectedUnit], str]:
    side = str(actor["tactical_side"])
    cache: dict[Path, tuple[SourceEntry, ...]] = {}
    projected: list[ProjectedUnit] = []
    source_entry_names: set[str] = set()
    rendered_entries: list[str] = []

    for unit in sorted(actor["units"], key=lambda row: str(row["unit_name"])):
        unit_name = str(unit["unit_name"])
        if str(unit.get("tactical_side")) != side:
            raise ExpandedNationsError(
                f"Actor {actor['actor_id']} unit {unit_name} targets {unit.get('tactical_side')}, expected {side}"
            )
        if not unit.get("materializable"):
            raise ExpandedNationsError(f"Actor unit is not materializable: {unit_name}")
        entry, source_reference = _find_source_entry(unit, roots, gates_root, cache)
        if entry.name in source_entry_names:
            raise ExpandedNationsError(
                f"Actor {actor['actor_id']} resolves multiple units to source entry {entry.name}"
            )
        source_entry_names.add(entry.name)
        source_raw = entry.raw.rstrip()
        projected_raw, replacements = _SIDE_CALL_RE.subn(f"side({side})", source_raw)
        if replacements != 1:
            raise ExpandedNationsError(
                f"Unit {unit_name} source entry {entry.name} has {replacements} side declarations"
            )
        source_hash = sha256_bytes(source_raw.encode("utf-8"))
        rendered_entries.append(
            f"; resolved_unit={unit_name}\n"
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


def _find_source_entry(
    unit: Mapping[str, Any],
    roots: Sequence[Path],
    gates_root: Path,
    cache: dict[Path, tuple[SourceEntry, ...]],
) -> tuple[SourceEntry, str]:
    unit_name = str(unit["unit_name"])
    source_side = str(unit.get("source_side") or unit.get("tactical_side") or "")
    if unit.get("virtual"):
        wrapper_path = gates_root / "resource/set/multiplayer/units/conquest/units_goc_national_wrappers.set"
        entries = _entries_for_path(wrapper_path, cache)
        matches = [entry for entry in entries if entry.name == unit_name]
        if len(matches) != 1:
            raise ExpandedNationsError(
                f"Virtual unit {unit_name} requires exactly one committed wrapper definition"
            )
        return matches[0], "gates:resource/set/multiplayer/units/conquest/units_goc_national_wrappers.set"

    candidates: list[tuple[int, int, int, int, SourceEntry, str]] = []
    for source_order, raw_reference in enumerate(unit.get("source_files", [])):
        source_reference = str(raw_reference)
        match = _SOURCE_REFERENCE_RE.fullmatch(source_reference)
        if match is None:
            continue
        priority = int(match.group(1))
        relative = match.group(3)
        if not relative.lower().endswith((".set", ".goh")):
            continue
        if priority < 0 or priority >= len(roots):
            continue
        source_path = resource_root(roots[priority]) / relative
        if not source_path.is_file():
            continue
        for entry in _entries_for_path(source_path, cache):
            if not _entry_name_matches(entry.name, unit_name, source_side):
                continue
            candidates.append(
                (
                    priority,
                    int(priority == int(unit.get("source_priority", -1))),
                    int(entry.name == unit_name),
                    source_order,
                    entry,
                    source_reference,
                )
            )
    if not candidates:
        raise ExpandedNationsError(f"No purchase-ready source definition found for actor unit {unit_name}")
    candidates.sort(key=lambda item: item[:4])
    selected = candidates[-1]
    expected_priority = int(unit.get("source_priority", selected[0]))
    if selected[0] != expected_priority:
        raise ExpandedNationsError(
            f"Unit {unit_name} resolved source priority {selected[0]}, expected {expected_priority}"
        )
    return selected[4], selected[5]


def _entries_for_path(path: Path, cache: dict[Path, tuple[SourceEntry, ...]]) -> tuple[SourceEntry, ...]:
    resolved = path.resolve()
    if resolved in cache:
        return cache[resolved]
    if not resolved.is_file():
        raise FileNotFoundError(f"Projected source file does not exist: {resolved}")
    scan = scan_source_entries(
        resolved.read_text(encoding="utf-8-sig", errors="replace"),
        str(resolved),
    )
    if scan.diagnostics:
        raise ExpandedNationsError(
            f"Source file has parser diagnostics and cannot be projected: {resolved}: "
            + "; ".join(item.message for item in scan.diagnostics)
        )
    cache[resolved] = tuple(scan.entries)
    return cache[resolved]


def _entry_name_matches(entry_name: str, unit_name: str, source_side: str) -> bool:
    if entry_name == unit_name:
        return True
    if f"{entry_name}({source_side})" == unit_name:
        return True
    if f"{unit_name}({source_side})" == entry_name:
        return True
    return _FACTION_SUFFIX_RE.sub("", entry_name) == _FACTION_SUFFIX_RE.sub("", unit_name)
