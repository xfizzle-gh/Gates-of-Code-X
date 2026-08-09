from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Iterator, Mapping, Sequence

from .faction_wiring_scan import _side_from_filename, _side_from_name
from .goh_source import SourceEntry, scan_source_entries
from .modstack import resource_root
from .expanded_nations_models import (
    BROAD_ROSTER_INCLUDES,
    ExpandedNationsError,
    ProjectedOpponentUnit,
    ProjectedUnit,
    SUPPORTED_TACTICAL_SIDES,
    sha256_bytes,
)

_SOURCE_REFERENCE_RE = re.compile(r"^(\d+):([^/]+)/(.+)$")
_SIDE_CALL_RE = re.compile(r"\bside\s*\(\s*[^)]*\)", re.IGNORECASE)
_PERIOD_ERA1960_RE = re.compile(r"\bperiod\s*\(\s*era1960\s*\)", re.IGNORECASE)
_INCLUDE_RE = re.compile(r'^\s*\(\s*include\s+"([^"]+)"\s*\)\s*$', re.IGNORECASE | re.DOTALL)
_FACTION_SUFFIX_RE = re.compile(
    r"^(?P<base>.*?)(?:\((?P<side>nato|ukr|rusa|prc|sov|csa|frg)\))?$",
    re.IGNORECASE,
)
_GENERATED_SOURCE_NAMES = frozenset(
    {
        "roster_conquest.set",
        "goc_active_actor_units.set",
        "goc_opponent_units.set",
        "unit_research_nato.set",
        "unit_research_ukr.set",
        "unit_research_rusa.set",
        "unit_research_prc.set",
    }
)
_SOVIET_RUSA_CREW_ALIASES: Mapping[str, str] = {
    "grd_vehicleman": "rus_vehicleman",
    "sup_tankman": "rus_vehicleman",
    "sup_vehicleman": "rus_vehicleman",
    "vmf_vehicleman": "rus_vehicleman",
    "sup_guncrew": "rus_supporter",
    "sup_supporter": "rus_supporter",
}


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
        entry, source_reference = _find_source_entry(unit, roots, gates_root, cache)
        if entry.name in source_entry_names:
            raise ExpandedNationsError(
                f"Actor {actor['actor_id']} resolves multiple units to source entry {entry.name}"
            )
        source_entry_names.add(entry.name)
        source_raw = entry.raw.rstrip()
        renamed_raw = _rename_entry(source_raw, entry, unit_name)
        projected_raw = _project_source_raw(
            renamed_raw,
            unit_name=unit_name,
            source_side=str(unit.get("source_side") or side).lower(),
            target_side=side,
        )
        projected_scan = scan_source_entries(projected_raw, f"generated:{unit_name}")
        if projected_scan.diagnostics or len(projected_scan.entries) != 1:
            raise ExpandedNationsError(f"Projected unit {unit_name} is not one valid GoH definition")
        generated = projected_scan.entries[0]
        if generated.name != unit_name:
            raise ExpandedNationsError(
                f"Projected unit ID {generated.name!r} does not match canonical ID {unit_name!r}"
            )
        side_calls = [call.value.lower() for call in generated.calls if call.family == "side"]
        if side_calls != [side]:
            raise ExpandedNationsError(
                f"Projected unit {unit_name} has tactical sides {side_calls}, expected {side}"
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


def _project_source_raw(
    raw: str,
    *,
    unit_name: str,
    source_side: str,
    target_side: str,
) -> str:
    projected, replacements = _SIDE_CALL_RE.subn(f"side({target_side})", raw)
    if replacements != 1:
        raise ExpandedNationsError(
            f"Unit {unit_name} source definition has {replacements} side declarations"
        )

    if source_side == target_side:
        return projected

    if source_side == "sov" and target_side == "rusa":
        projected, periods = _PERIOD_ERA1960_RE.subn("period(2022s)", projected)
        if periods != 1:
            raise ExpandedNationsError(
                f"Soviet-to-RUSA unit {unit_name} requires one era1960 period, found {periods}"
            )
        for source_crew, target_crew in _SOVIET_RUSA_CREW_ALIASES.items():
            pattern = re.compile(
                r"(\bcrew\d*\s*\(\s*)" + re.escape(source_crew) + r"(?=\s*:)",
                re.IGNORECASE,
            )
            projected = pattern.sub(
                lambda match, replacement=target_crew: match.group(1) + replacement,
                projected,
            )
        unresolved = [
            crew
            for crew in _SOVIET_RUSA_CREW_ALIASES
            if re.search(
                r"\bcrew\d*\s*\(\s*" + re.escape(crew) + r"\s*:",
                projected,
                re.IGNORECASE,
            )
        ]
        if unresolved:
            raise ExpandedNationsError(
                f"Soviet-to-RUSA unit {unit_name} retains legacy crew aliases: {unresolved}"
            )
        if _PERIOD_ERA1960_RE.search(projected):
            raise ExpandedNationsError(
                f"Soviet-to-RUSA unit {unit_name} retains era1960 period"
            )
        return projected

    return projected


def project_opponent_units(
    selected_side: str,
    roots: Sequence[Path],
) -> tuple[list[ProjectedOpponentUnit], str]:
    from .expanded_nations_opponent_render import project_opponent_units as implementation
    return implementation(selected_side, roots)


def _walk_effective_include(
    include: str,
    roots: Sequence[Path],
    cache: dict[Path, tuple[SourceEntry, ...]],
    *,
    active: tuple[Path, ...],
) -> Iterator[tuple[SourceEntry, Path, int, str, int]]:
    normalized = include.replace("\\", "/").lstrip("/")
    include_path = Path(normalized)
    if not normalized or include_path.is_absolute() or ".." in include_path.parts:
        raise ExpandedNationsError(f"Unsafe opponent roster include: {include}")
    effective = _effective_include_path(normalized, roots)
    if effective is None:
        raise ExpandedNationsError(f"Opponent roster include cannot be resolved: {include}")
    source_path, priority = effective
    resolved = source_path.resolve()
    if resolved in active:
        chain = " -> ".join(str(path) for path in (*active, resolved))
        raise ExpandedNationsError(f"Opponent roster include cycle: {chain}")
    relative = source_path.relative_to(resource_root(roots[priority])).as_posix()
    source_reference = f"{priority}:{roots[priority].name}/{relative}"
    entries = _entries_for_path(source_path, cache)
    for ordinal, entry in enumerate(entries):
        if entry.macro_kind.lower() == "include":
            match = _INCLUDE_RE.fullmatch(entry.raw)
            if match is None:
                raise ExpandedNationsError(
                    f"Malformed side-less include in opponent roster {source_path}: {entry.raw!r}"
                )
            yield from _walk_effective_include(
                match.group(1),
                roots,
                cache,
                active=(*active, resolved),
            )
            continue
        if not entry.name:
            raise ExpandedNationsError(
                "Unnamed non-include entry in opponent roster cannot be filtered safely: "
                f"{source_path}:{entry.location.line}"
            )
        yield entry, source_path, priority, source_reference, ordinal


def _canonical_entry_side(entry: SourceEntry, source_path: Path) -> str:
    explicit = [call.value.lower() for call in entry.calls if call.family == "side"]
    if len(explicit) > 1:
        raise ExpandedNationsError(
            f"Core roster entry {entry.name!r} in {source_path} has multiple side declarations"
        )
    return (
        _side_from_name(entry.name)
        or (explicit[0] if explicit else "")
        or _side_from_filename(source_path.name)
    )


def _find_source_entry(
    unit: Mapping[str, Any],
    roots: Sequence[Path],
    gates_root: Path,
    cache: dict[Path, tuple[SourceEntry, ...]],
) -> tuple[SourceEntry, str]:
    unit_name = str(unit["unit_name"])
    source_side = str(unit.get("source_side") or unit.get("tactical_side") or "").lower()
    if unit.get("virtual"):
        wrapper_path = (
            gates_root
            / "resource/set/multiplayer/units/conquest/units_goc_national_wrappers.set"
        )
        entries = _entries_for_path(wrapper_path, cache)
        matches = [entry for entry in entries if entry.name == unit_name]
        if len(matches) != 1:
            raise ExpandedNationsError(
                f"Virtual unit {unit_name} requires exactly one committed wrapper definition"
            )
        return (
            matches[0],
            "gates:resource/set/multiplayer/units/conquest/units_goc_national_wrappers.set",
        )

    candidates: list[tuple[int, int, int, SourceEntry, str]] = []
    for source_order, raw_reference in enumerate(unit.get("source_files", [])):
        source_reference = str(raw_reference)
        if _is_generated_source_reference(source_reference):
            raise ExpandedNationsError(
                f"Actor unit {unit_name} cannot use generated activation source {source_reference}"
            )
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
                (priority, int(entry.name == unit_name), source_order, entry, source_reference)
            )
    if not candidates:
        raise ExpandedNationsError(
            f"No purchase-ready source definition found for actor unit {unit_name}"
        )

    expected_priority = int(unit.get("source_priority", max(item[0] for item in candidates)))
    candidates = [item for item in candidates if item[0] == expected_priority]
    if not candidates:
        raise ExpandedNationsError(
            f"Unit {unit_name} has no matching source definition at expected priority {expected_priority}"
        )
    exact = [item for item in candidates if item[1] == 1]
    pool = exact or candidates
    highest_order = max(item[2] for item in pool)
    winners = [item for item in pool if item[2] == highest_order]
    unique = {(item[3].name, item[4]) for item in winners}
    if len(unique) != 1:
        raise ExpandedNationsError(
            f"Actor unit {unit_name} has ambiguous purchase-ready aliases at priority {expected_priority}"
        )
    selected = winners[0]
    return selected[3], selected[4]


def _effective_include_path(
    include: str,
    roots: Sequence[Path],
) -> tuple[Path, int] | None:
    for priority in range(len(roots) - 1, -1, -1):
        candidate = resource_root(roots[priority]) / "set/multiplayer/units" / include
        if candidate.is_file():
            return candidate, priority
    return None


def _entries_for_path(
    path: Path,
    cache: dict[Path, tuple[SourceEntry, ...]],
) -> tuple[SourceEntry, ...]:
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
    entry_match = _FACTION_SUFFIX_RE.fullmatch(entry_name)
    unit_match = _FACTION_SUFFIX_RE.fullmatch(unit_name)
    if entry_match is None or unit_match is None:
        return False
    if entry_match.group("base") != unit_match.group("base"):
        return False
    entry_side = (entry_match.group("side") or "").lower()
    unit_side = (unit_match.group("side") or "").lower()
    allowed = {"", source_side.lower()}
    return entry_side in allowed and unit_side in allowed


def _rename_entry(raw: str, entry: SourceEntry, canonical_name: str) -> str:
    if entry.name == canonical_name:
        return raw
    if entry.form == "block":
        pattern = re.compile(r'^(\s*\{\s*")' + re.escape(entry.name) + r'(")')
        renamed, count = pattern.subn(
            lambda match: f"{match.group(1)}{canonical_name}{match.group(2)}",
            raw,
            count=1,
        )
    elif entry.form == "macro":
        pattern = re.compile(
            r"\bname\s*\(\s*" + re.escape(entry.name) + r"\s*\)",
            re.IGNORECASE,
        )
        renamed, count = pattern.subn(f"name({canonical_name})", raw, count=1)
    else:
        raise ExpandedNationsError(
            f"Unsupported source-entry form for {entry.name}: {entry.form}"
        )
    if count != 1:
        raise ExpandedNationsError(
            f"Could not canonicalize source entry {entry.name!r} to {canonical_name!r}"
        )
    return renamed


def _is_generated_source_reference(source_reference: str) -> bool:
    normalized = source_reference.replace("\\", "/").lower()
    return any(
        normalized.endswith("/" + name) or normalized.endswith(":" + name)
        for name in _GENERATED_SOURCE_NAMES
    )
