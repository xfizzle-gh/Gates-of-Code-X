from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from .modstack import resource_root
from .faction_wiring_models import FactionWiringError, ResolutionProblem, _ResolvedComponent
from .faction_wiring_types import CATEGORY_COSTS, SourceUnit, _copy_unit, _merge_unit


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
            result.units[copy.name] = _merge_unit(result.units.get(copy.name), copy) if copy.name in result.units else copy

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
        for name in selector["units"]:
            unit = self.unit_index.resolve(name, side=side) or self.unit_index.resolve(name)
            if unit is None or not unit.materializable:
                severity = "error" if required else "warning"
                result.problems.append(ResolutionProblem(severity, "", result.component_id, f"missing materializable unit {name}"))
                continue
            copy = _copy_unit(unit)
            copy.tier = max(copy.tier, int(selector.get("tier", 1)))
            if selector.get("category"):
                copy.category = selector["category"]
            result.units[copy.name] = _merge_unit(result.units.get(copy.name), copy) if copy.name in result.units else copy

    def _resolve_prefix_selector(self, result: _ResolvedComponent, selector: Mapping[str, Any]) -> None:
        side = selector.get("source_side", "")
        excluded = re.compile(selector["exclude_regex"], re.I) if selector.get("exclude_regex") else None
        matches: list[SourceUnit] = []
        for prefix in selector["prefixes"]:
            matches.extend(self.unit_index.matching(side=side, prefix=prefix))
        matches = [unit for unit in matches if not excluded or not excluded.search(unit.name)]
        if not matches and selector.get("required", True):
            result.problems.append(ResolutionProblem("error", "", result.component_id, "prefix selector matched no units"))
        for unit in matches:
            copy = _copy_unit(unit)
            copy.tier = max(copy.tier, int(selector.get("tier", 1)))
            result.units[copy.name] = _merge_unit(result.units.get(copy.name), copy) if copy.name in result.units else copy

    def _resolve_regex_selector(self, result: _ResolvedComponent, selector: Mapping[str, Any]) -> None:
        side = selector.get("source_side", "")
        matches: dict[str, SourceUnit] = {}
        for pattern in selector["patterns"]:
            for unit in self.unit_index.matching(side=side, pattern=pattern):
                matches[unit.name] = unit
        if not matches and selector.get("required", True):
            result.problems.append(ResolutionProblem("error", "", result.component_id, "regex selector matched no units"))
        for unit in matches.values():
            copy = _copy_unit(unit)
            copy.tier = max(copy.tier, int(selector.get("tier", 1)))
            result.units[copy.name] = _merge_unit(result.units.get(copy.name), copy) if copy.name in result.units else copy

    def _resolve_virtual_selector(self, result: _ResolvedComponent, selector: Mapping[str, Any]) -> None:
        for raw in selector["units"]:
            source_side = raw["source_side"]
            missing = [breed for breed in raw.get("members", {}) if not self._breed_exists(source_side, breed)]
            if missing:
                result.problems.append(ResolutionProblem(
                    "error", "", result.component_id,
                    f"virtual unit {raw['name']} references missing breeds: {', '.join(sorted(missing))}",
                ))
                continue
            unit = SourceUnit(
                name=raw["name"],
                source_side=source_side,
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
            result.units[unit.name] = unit

    def _breed_exists(self, source_side: str, breed: str) -> bool:
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
        return (source_side.lower(), breed.lower()) in self._breed_index
