from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .codex.catalog import CodeXCatalogScanner
from .goh_source import MacroCall, SourceEntry, scan_source_entries
from .modstack import resource_root
from .faction_wiring_types import (
    ENTITY_HINTS, DefinitionReference, ReferenceKind, SourceUnit, _base_name,
    _infer_category, _layer_name, _match_existing_key, _merge_unit,
    _source_priority,
)

SOURCE_SIDE_RE = re.compile(r"(?:^|[_\-.])(nato|ukr|rusa|prc|sov|frg|gdr|csa|usa|ger|eng|fin|pol|rus)(?:[_\-.]|$)", re.I)
SIDE_SUFFIX_RE = re.compile(r"\(([^()]+)\)$")
MEMBER_BLOCK_RE = re.compile(r'\{(?:member|breed)\s+"?([^"\s{}]+)"?\s*(\d+)?', re.I)
MACRO_MEMBER_RE = re.compile(r"\b(?:c\d+|crew\d*|member\d*|breed\d*)\(([^:()\s]+):(\d+)\)", re.I)


@dataclass(slots=True)
class SourceUnitIndex:
    units: dict[str, SourceUnit]
    aliases: dict[str, list[str]]

    @classmethod
    def build(cls, roots: Sequence[Path]) -> "SourceUnitIndex":
        units: dict[str, SourceUnit] = {}
        try:
            catalog = CodeXCatalogScanner().scan_stack(roots)
        except (FileNotFoundError, ValueError):
            catalog = None
        if catalog is not None:
            raw_values = catalog.units.raw_values() if hasattr(catalog.units, "raw_values") else catalog.units.values()
            for unit in raw_values:
                source_files = list(getattr(unit, "source_files", []))
                priority = max((_source_priority(item) for item in source_files), default=-1)
                units[unit.name] = SourceUnit(
                    name=unit.name,
                    source_side=unit.side,
                    period=unit.period,
                    category=unit.category,
                    members=dict(unit.members),
                    vehicles=list(unit.vehicles),
                    actions=list(unit.actions),
                    source_files=source_files,
                    source_layer=_layer_name(roots, priority),
                    source_priority=priority,
                    research_cost=max(0, int(getattr(unit, "doctrine_cost", 0))),
                )

        for priority, root in enumerate(roots):
            resources = resource_root(root)
            unit_roots = (
                resources / "set/multiplayer/units/conquest",
                resources / "set/multiplayer/units",
            )
            visited: set[Path] = set()
            for unit_root in unit_roots:
                if not unit_root.is_dir():
                    continue
                for path in sorted(
                    candidate
                    for candidate in unit_root.rglob("*")
                    if candidate.is_file() and candidate.suffix.lower() in {".set", ".goh"}
                ):
                    if path in visited:
                        continue
                    visited.add(path)
                    filename_side = _side_from_filename(path.name)
                    text = path.read_text(encoding="utf-8-sig", errors="replace")
                    relative = path.relative_to(resources).as_posix()
                    source = f"{priority}:{root.name}/{relative}"
                    for entry in scan_source_entries(text, source).entries:
                        name = entry.name
                        side = _side_from_name(name) or _call_value(entry.calls, "side") or filename_side
                        if not side:
                            continue
                        period = _call_value(entry.calls, "period") or _period_from_path(path)
                        members = _members(entry.raw, entry.calls)
                        vehicles = _vehicles(entry.calls)
                        references = _definition_references(entry)
                        has_crew = any(call.family == "crew" for call in entry.calls)
                        if not vehicles and (has_crew or any(hint in entry.macro_kind.lower() for hint in ENTITY_HINTS)):
                            inferred = _base_name(name)
                            if inferred:
                                vehicles = [inferred]
                                references.append(
                                    DefinitionReference(
                                        identifier=inferred,
                                        kind=ReferenceKind.VEHICLE_ENTITY,
                                        source=entry.location.source,
                                        line=entry.location.line,
                                        column=entry.location.column,
                                    )
                                )
                        overlay = SourceUnit(
                            name=name,
                            source_side=side,
                            period=period,
                            category=_infer_category(name, members, vehicles),
                            members=members,
                            vehicles=vehicles,
                            actions=_actions(entry.calls),
                            definition_references=references,
                            source_files=[source],
                            source_layer=root.name,
                            source_priority=priority,
                        )
                        existing_key = _match_existing_key(units, name, side)
                        if existing_key is not None:
                            units[existing_key] = _merge_unit(units[existing_key], overlay)
                        else:
                            storage_name = name
                            if storage_name in units and units[storage_name].source_side != side:
                                storage_name = f"{_base_name(name)}({side})"
                                overlay.name = storage_name
                            units[storage_name] = overlay

        aliases: dict[str, list[str]] = defaultdict(list)
        for name in sorted(units):
            for alias in {name, _base_name(name), name.lower(), _base_name(name).lower()}:
                aliases[alias].append(name)
        return cls(units=units, aliases=dict(aliases))

    def resolve(self, name: str, *, side: str = "") -> SourceUnit | None:
        if name in self.units and (not side or self.units[name].source_side == side):
            return self.units[name]
        candidates = (
            self.aliases.get(name, [])
            or self.aliases.get(name.lower(), [])
            or self.aliases.get(_base_name(name), [])
            or self.aliases.get(_base_name(name).lower(), [])
        )
        if side:
            candidates = [candidate for candidate in candidates if self.units[candidate].source_side == side]
        if not candidates:
            return None
        return self.units[sorted(candidates)[0]]

    def matching(self, *, side: str = "", prefix: str = "", pattern: str = "") -> list[SourceUnit]:
        regex = re.compile(pattern, re.I) if pattern else None
        values = []
        for unit in self.units.values():
            if side and unit.source_side != side:
                continue
            if prefix and not unit.name.lower().startswith(prefix.lower()):
                continue
            if regex and not regex.search(unit.name):
                continue
            values.append(unit)
        return sorted(values, key=lambda unit: unit.name)


def _members(raw: str, calls: Sequence[MacroCall]) -> dict[str, int]:
    values: dict[str, int] = {}
    for breed, count in MEMBER_BLOCK_RE.findall(raw):
        values[breed] = values.get(breed, 0) + int(count or 1)
    for call in calls:
        if call.family not in {"c", "crew", "member", "breed"} or ":" not in call.value:
            continue
        breed, count = call.value.rsplit(":", 1)
        if breed and count.isdigit():
            values[breed] = values.get(breed, 0) + int(count)
    if not any(":" in call.value for call in calls):
        for breed, count in MACRO_MEMBER_RE.findall(raw):
            values[breed] = values.get(breed, 0) + int(count)
    return values


def _vehicles(calls: Sequence[MacroCall]) -> list[str]:
    return list(dict.fromkeys(
        call.value for call in calls
        if call.family in {"vehicle", "entity"} and call.value
    ))


def _actions(calls: Sequence[MacroCall]) -> list[str]:
    return list(dict.fromkeys(
        call.value for call in calls if call.family == "action" and call.value
    ))


def _call_value(calls: Sequence[MacroCall], family: str) -> str:
    return next((call.value for call in calls if call.family == family), "")


def _definition_references(entry: SourceEntry) -> list[DefinitionReference]:
    kind = (
        ReferenceKind.STRATEGIC_CALL_IN
        if _is_strategic_call_in(entry)
        else ReferenceKind.VEHICLE_ENTITY
    )
    return [
        DefinitionReference(
            identifier=call.value,
            kind=kind,
            source=call.location.source,
            line=call.location.line,
            column=call.location.column,
        )
        for call in entry.calls
        if call.family in {"vehicle", "entity"} and call.value
    ]


def _is_strategic_call_in(entry: SourceEntry) -> bool:
    macro_kind = entry.macro_kind.lower()
    has_call_in_kind = "strategic" in macro_kind or "offmap" in macro_kind
    has_call_in_action = any(
        call.family == "action"
        and call.value.lower() in {"callin", "call_in", "strategic", "offmap"}
        for call in entry.calls
    )
    return has_call_in_kind and has_call_in_action


def _side_from_filename(name: str) -> str:
    match = re.search(r"(?:^|_)(?:units|inf)_([a-z0-9]+)", name.lower())
    if match:
        return match.group(1)
    match = SOURCE_SIDE_RE.search(name)
    return match.group(1).lower() if match else ""


def _side_from_name(name: str) -> str:
    match = SIDE_SUFFIX_RE.search(name)
    return match.group(1).lower() if match else ""


def _period_from_path(path: Path) -> str:
    for part in path.parts:
        lowered = part.lower()
        if re.fullmatch(r"20\d\ds|19\d\ds|early|mid|late", lowered):
            return lowered
    era = re.search(r"era(\d{4})", path.name.lower())
    return era.group(1) if era else ""
