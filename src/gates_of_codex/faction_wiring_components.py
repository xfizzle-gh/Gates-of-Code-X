from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from .modstack import resource_root
from .faction_wiring_models import FactionWiringError, ResolutionProblem, _ResolvedComponent
from .faction_wiring_types import CATEGORY_COSTS, SourceUnit, _copy_unit, _merge_unit


_JUNK_AFTER_BRACE_RE = re.compile(r'\}\s*[A-Za-z0-9_]+\s*$')
_REGISTRY_UNIT_RE = re.compile(r'\{\s*"([^"]+)"')


class FactionComponentMixin:
    def _resolve_component(self, component_id: str, component: Mapping[str, Any]) -> _ResolvedComponent:
        result = _ResolvedComponent(component_id=component_id)
        for selector in component["selectors"]:
            kind = selector["kind"]
            if kind == "research_branch":
                self._resolve_branch_selector(result, selector)
            elif kind == "exact":
                self._resolve_exact_selector(result, selector)
            elif kind == "prefix":
                self._resolve_prefix_selector(result, selector)
            elif kind == "regex":
                self._resolve_regex_selector(result, selector)
            elif kind == "virtual":
                self._resolve_virtual_selector(result, selector)
            else:
                raise FactionWiringError(f"Unsupported selector kind: {kind}")
        return result

    def _resolve_branch_selector(self, result: _ResolvedComponent, selector: Mapping[str, Any]) -> None:
        side = selector["source_side"]
        root = selector["root"]
        descendants = self.research_index.descendants(side, root)
        required = selector.get("required", True)
        if not descendants:
            severity = "error" if required else "warning"
            result.problems.append(ResolutionProblem(severity, "", result.component_id, f"missing research branch {side}:{root}"))
            return
        include = re.compile(selector["include_regex"], re.I) if selector.get("include_regex") else None
        exclude = re.compile(selector["exclude_regex"], re.I) if selector.get("exclude_regex") else None
        selected_units: set[str] = set()
        for node in descendants:
            if node.kind != "unit":
                continue
            if include and not include.search(node.node_id):
                continue
            if exclude and exclude.search(node.node_id):
                continue
            selected_units.add(node.node_id)
        included_nodes = self._research_closure(side, root, selected_units)
        result.branch_roots.append(root)
        for node_id in included_nodes:
            node = self.research_index.get(side, node_id)
            if node is None:
                continue
            result.research_nodes[f"{side}:{node.node_id}"] = node
            if node.kind != "unit" or node.node_id not in selected_units:
                continue
            unit = self.unit_index.resolve(node.node_id, side=side) or self.unit_index.resolve(node.node_id)
            if unit is None or not unit.materializable:
                result.problems.append(ResolutionProblem(
                    "warning", "", result.component_id,
                    f"research unit {side}:{node.node_id} has no materializable catalog definition",
                ))
                continue
            copy = _copy_unit(unit)
            copy.tier = max(copy.tier, int(selector.get("tier", 1)))
            copy.research_cost = max(copy.research_cost, node.cost)
            self._add_validated_unit(result, copy, severity="error")

    def _research_closure(self, side: str, root: str, selected_units: set[str]) -> set[str]:
        included: set[str] = {root}
        for unit_id in selected_units:
            current = unit_id
            guard: set[str] = set()
            while current and current not in guard:
                guard.add(current)
                node = self.research_index.get(side, current)
                if node is None:
                    break
                included.add(current)
                if current == root:
                    break
                current = node.prerequisite
        return included

    def _resolve_exact_selector(self, result: _ResolvedComponent, selector: Mapping[str, Any]) -> None:
        side = selector.get("source_side", "")
        required = selector.get("required", True)
        severity = "error" if required else "warning"
        for name in selector["units"]:
            unit = self.unit_index.resolve(name, side=side) or self.unit_index.resolve(name)
            if unit is None or not unit.materializable:
                result.problems.append(ResolutionProblem(severity, "", result.component_id, f"missing materializable unit {name}"))
                continue
            copy = _copy_unit(unit)
            copy.tier = max(copy.tier, int(selector.get("tier", 1)))
            if selector.get("category"):
                copy.category = selector["category"]
            self._add_validated_unit(result, copy, severity=severity)

    def _resolve_prefix_selector(self, result: _ResolvedComponent, selector: Mapping[str, Any]) -> None:
        side = selector.get("source_side", "")
        required = selector.get("required", True)
        severity = "error" if required else "warning"
        excluded = re.compile(selector["exclude_regex"], re.I) if selector.get("exclude_regex") else None
        matches: list[SourceUnit] = []
        for prefix in selector["prefixes"]:
            matches.extend(self.unit_index.matching(side=side, prefix=prefix))
        matches = [unit for unit in matches if not excluded or not excluded.search(unit.name)]
        if not matches and required:
            result.problems.append(ResolutionProblem("error", "", result.component_id, "prefix selector matched no units"))
        for unit in matches:
            copy = _copy_unit(unit)
            copy.tier = max(copy.tier, int(selector.get("tier", 1)))
            self._add_validated_unit(result, copy, severity=severity)

    def _resolve_regex_selector(self, result: _ResolvedComponent, selector: Mapping[str, Any]) -> None:
        side = selector.get("source_side", "")
        required = selector.get("required", True)
        severity = "error" if required else "warning"
        matches: dict[str, SourceUnit] = {}
        for pattern in selector["patterns"]:
            for unit in self.unit_index.matching(side=side, pattern=pattern):
                matches[unit.name] = unit
        if not matches and required:
            result.problems.append(ResolutionProblem("error", "", result.component_id, "regex selector matched no units"))
        for unit in matches.values():
            copy = _copy_unit(unit)
            copy.tier = max(copy.tier, int(selector.get("tier", 1)))
            self._add_validated_unit(result, copy, severity=severity)

    def _resolve_virtual_selector(self, result: _ResolvedComponent, selector: Mapping[str, Any]) -> None:
        for raw in selector["units"]:
            unit = SourceUnit(
                name=raw["name"],
                source_side=raw["source_side"],
                period=raw.get("period", "2022s"),
                category=raw.get("category", "infantry"),
                members={key: int(value) for key, value in raw.get("members", {}).items()},
                vehicles=list(raw.get("vehicles", [])),
                actions=list(raw.get("actions", [])),
                source_files=["Gates-of-Code-X:faction_wiring_manifest"],
                source_layer="Gates of Code:X",
                source_priority=len(self.roots),
                virtual=True,
                tier=int(raw.get("tier", 1)),
                research_cost=int(raw.get("cost", CATEGORY_COSTS.get(raw.get("category", "unknown"), 2))),
            )
            self._add_validated_unit(result, unit, severity="error")

    def _add_validated_unit(
        self,
        result: _ResolvedComponent,
        unit: SourceUnit,
        *,
        severity: str,
    ) -> None:
        problems = self._unit_asset_problems(unit)
        if problems:
            for message in problems:
                result.problems.append(ResolutionProblem(severity, "", result.component_id, message))
            return
        result.units[unit.name] = _merge_unit(result.units.get(unit.name), unit) if unit.name in result.units else unit

    def _unit_asset_problems(self, unit: SourceUnit) -> list[str]:
        problems: list[str] = []
        missing_breeds: list[str] = []
        invalid_breeds: list[str] = []
        for breed in sorted(unit.members):
            path = self._breed_path(unit.source_side, breed)
            if path is None:
                missing_breeds.append(breed)
                continue
            issue = self._breed_quality_issue(path)
            if issue:
                invalid_breeds.append(f"{breed} ({issue})")
        if missing_breeds:
            problems.append(
                f"unit {unit.name} references missing {unit.source_side} breeds: {', '.join(missing_breeds)}"
            )
        if invalid_breeds:
            problems.append(
                f"unit {unit.name} references invalid breed definitions: {', '.join(invalid_breeds)}"
            )

        missing_vehicles = sorted(vehicle for vehicle in set(unit.vehicles) if not self._vehicle_exists(vehicle))
        if missing_vehicles:
            problems.append(
                f"unit {unit.name} references missing vehicle/entity IDs: {', '.join(missing_vehicles)}"
            )
        return problems

    def _breed_path(self, source_side: str, breed: str) -> Path | None:
        if self._breed_index is None:
            values: dict[tuple[str, str], tuple[Path, int]] = {}
            for priority in range(len(self.roots) - 1, -1, -1):
                root = self.roots[priority]
                breed_root = resource_root(root) / "set/breed/mp"
                if not breed_root.is_dir():
                    continue
                for path in sorted(breed_root.rglob("*.set")):
                    relative = path.relative_to(breed_root).parts
                    side = relative[0].lower() if relative else ""
                    values.setdefault((side, path.stem.lower()), (path, priority))
            self._breed_index = values
        value = self._breed_index.get((source_side.lower(), breed.lower()))
        return value[0] if value else None

    def _breed_exists(self, source_side: str, breed: str) -> bool:
        return self._breed_path(source_side, breed) is not None

    @staticmethod
    def _breed_quality_issue(path: Path) -> str:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if text.count("{") != text.count("}"):
            return "unbalanced braces"
        if re.search(r'\{\s*item\s+"\s*"', text, re.I):
            return "empty inventory item"
        for line_number, line in enumerate(text.splitlines(), start=1):
            if _JUNK_AFTER_BRACE_RE.search(line):
                return f"junk after closing brace on line {line_number}"
        return ""

    def _vehicle_exists(self, vehicle: str) -> bool:
        if self._vehicle_index is None:
            values: set[str] = set()
            for root in self.roots:
                resources = resource_root(root)
                registry = resources / "set/registry/unit.reg"
                if registry.is_file():
                    text = registry.read_text(encoding="utf-8-sig", errors="replace")
                    values.update(match.lower() for match in _REGISTRY_UNIT_RE.findall(text))
                entity_root = resources / "entity"
                if entity_root.is_dir():
                    values.update(path.stem.lower() for path in entity_root.rglob("*.def"))
            self._vehicle_index = values
        return vehicle.lower() in self._vehicle_index
