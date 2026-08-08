from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from .codex.catalog import CodeXCatalogScanner
from .modstack import resource_root
from .faction_wiring_types import (
    ENTITY_HINTS, SourceUnit, _base_name, _infer_category, _layer_name,
    _match_existing_key, _merge_unit, _paren_balance, _source_priority,
)

SOURCE_SIDE_RE = re.compile(r"(?:^|[_\-.])(nato|ukr|rusa|prc|sov|frg|gdr|csa|usa|ger|eng|fin|pol|rus)(?:[_\-.]|$)", re.I)
SIDE_SUFFIX_RE = re.compile(r"\(([^()]+)\)$")
BLOCK_START_RE = re.compile(r'^\s*\{\s*"?([^"\s{}]+(?:\([^)]*\))?)"?')
MACRO_NAME_RE = re.compile(r"\bname\(([^)]+)\)", re.I)
MACRO_MEMBER_RE = re.compile(r"\b(?:c\d+|crew\d*|member\d*|breed\d*)\(([^:()\s]+):(\d+)\)", re.I)
MEMBER_BLOCK_RE = re.compile(r'\{(?:member|breed)\s+"?([^"\s{}]+)"?\s*(\d+)?', re.I)
VEHICLE_BLOCK_RE = re.compile(r'\{(?:vehicle|entity)\s+"?([^"\s{}]+)', re.I)
VEHICLE_MACRO_RE = re.compile(r"\b(?:vehicle|entity)\(([^)]+)\)", re.I)
ACTION_BLOCK_RE = re.compile(r'\{action\s+"?([^"\s{}]+)', re.I)
ACTION_MACRO_RE = re.compile(r"\baction\(([^)\s]+)\)", re.I)
SIDE_ATTR_RE = re.compile(r"\bside\(([^)\s]+)\)", re.I)
PERIOD_ATTR_RE = re.compile(r"\bperiod\(([^)\s]+)\)", re.I)


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
                for path in sorted(unit_root.rglob("*.set")):
                    if path in visited:
                        continue
                    visited.add(path)
                    filename_side = _side_from_filename(path.name)
                    if not filename_side:
                        continue
                    text = path.read_text(encoding="utf-8-sig", errors="replace")
                    relative = path.relative_to(resources).as_posix()
                    for name, raw, macro_kind in _source_entries(text):
                        side = _side_from_name(name) or _word_attr(raw, "side") or filename_side
                        if not side:
                            continue
                        period = _word_attr(raw, "period") or _period_from_path(path)
                        members = _members(raw)
                        vehicles = _vehicles(raw)
                        has_crew = bool(re.search(r"\bcrew\d*\(", raw, flags=re.I))
                        if not vehicles and (has_crew or any(hint in macro_kind.lower() for hint in ENTITY_HINTS)):
                            inferred = _base_name(name)
                            if inferred:
                                vehicles = [inferred]
                        overlay = SourceUnit(
                            name=name,
                            source_side=side,
                            period=period,
                            category=_infer_category(name, members, vehicles),
                            members=members,
                            vehicles=vehicles,
                            actions=_actions(raw),
                            source_files=[f"{priority}:{root.name}/{relative}"],
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


def _source_entries(text: str) -> Iterator[tuple[str, str, str]]:
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.lstrip()
        if not stripped or stripped.startswith(";") or stripped.startswith("//"):
            index += 1
            continue
        block = BLOCK_START_RE.match(line)
        if block:
            raw_lines = [line]
            depth = line.count("{") - line.count("}")
            cursor = index + 1
            while depth > 0 and cursor < len(lines):
                raw_lines.append(lines[cursor])
                depth += lines[cursor].count("{") - lines[cursor].count("}")
                cursor += 1
            raw = "\n".join(raw_lines)
            name = _word_attr(raw, "name") or block.group(1)
            yield name, raw, ""
            index = cursor
            continue
        if ("name(" in line and "(" in line) or re.match(r'^\s*\(\s*"', line):
            raw_lines = [line]
            depth = _paren_balance(line)
            cursor = index + 1
            while depth > 0 and cursor < len(lines):
                raw_lines.append(lines[cursor])
                depth += _paren_balance(lines[cursor])
                cursor += 1
            raw = "\n".join(raw_lines)
            name = _word_attr(raw, "name")
            if name:
                kind_match = re.match(r'^\s*\(\s*"([^"]+)"', raw)
                yield name, raw, kind_match.group(1) if kind_match else ""
            index = cursor
            continue
        index += 1


def _members(raw: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for breed, count in MEMBER_BLOCK_RE.findall(raw):
        values[breed] = values.get(breed, 0) + int(count or 1)
    for breed, count in MACRO_MEMBER_RE.findall(raw):
        values[breed] = values.get(breed, 0) + int(count)
    return values


def _vehicles(raw: str) -> list[str]:
    values = VEHICLE_BLOCK_RE.findall(raw)
    values.extend(match.strip().strip('"') for match in VEHICLE_MACRO_RE.findall(raw))
    return list(dict.fromkeys(value for value in values if value))


def _actions(raw: str) -> list[str]:
    values = ACTION_BLOCK_RE.findall(raw)
    values.extend(ACTION_MACRO_RE.findall(raw))
    return list(dict.fromkeys(values))


def _word_attr(raw: str, name: str) -> str:
    if name == "name":
        match = MACRO_NAME_RE.search(raw)
    elif name == "side":
        match = SIDE_ATTR_RE.search(raw)
    elif name == "period":
        match = PERIOD_ATTR_RE.search(raw)
    else:
        match = re.search(rf"\b{re.escape(name)}\(([^)]+)\)", raw, re.I)
    return match.group(1).strip().strip('"') if match else ""


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
