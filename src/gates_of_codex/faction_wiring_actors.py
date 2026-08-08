from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from .faction_wiring_models import ResolutionProblem, ResolvedResearchNode, _ResolvedComponent
from .faction_wiring_types import (
    CATEGORY_COSTS, SourceResearchNode, SourceUnit, _base_name, _category_rank,
    _copy_unit, _display_name, _merge_unit, _slug,
)
from .faction_wiring_manifest import _topological_research_order


class FactionActorMixin:
    def _resolve_actor(
        self,
        actor: Mapping[str, Any],
        components: Mapping[str, _ResolvedComponent],
    ) -> tuple[dict[str, Any], list[ResolutionProblem]]:
        actor_id = actor["actor_id"]
        tactical_side = actor["tactical_side"]
        combined_units: dict[str, tuple[SourceUnit, str]] = {}
        selected_research: dict[str, tuple[SourceResearchNode, str]] = {}
        problems: list[ResolutionProblem] = []
        for component_id in actor["components"]:
            component = components[component_id]
            for problem in component.problems:
                problems.append(ResolutionProblem(problem.severity, actor_id, component_id, problem.message))
            for name, unit in component.units.items():
                if name in combined_units:
                    combined_units[name] = (_merge_unit(combined_units[name][0], unit), component_id)
                else:
                    combined_units[name] = (_copy_unit(unit), component_id)
            for key, node in component.research_nodes.items():
                selected_research[key] = (node, component_id)

        units = [
            unit.to_dict(actor_id=actor_id, tactical_side=tactical_side, component_id=component_id)
            for unit, component_id in sorted(combined_units.values(), key=lambda item: item[0].name)
        ]
        if actor.get("playable", False) and not units:
            problems.append(ResolutionProblem("error", actor_id, "", "playable actor resolved to an empty roster"))
        if actor.get("playable", False) and not any(item["materializable"] for item in units):
            problems.append(ResolutionProblem("error", actor_id, "", "playable actor has no materializable units"))

        research_nodes = self._compile_actor_research(
            actor,
            combined_units,
            selected_research,
            components,
        )
        if actor.get("playable", False) and not research_nodes:
            problems.append(ResolutionProblem("error", actor_id, "", "playable actor resolved to an empty research tree"))

        category_counts: dict[str, int] = defaultdict(int)
        modern_count = 0
        legacy_count = 0
        virtual_count = 0
        for item in units:
            category_counts[item["category"]] += 1
            virtual_count += int(item["virtual"])
            layer = item["source_layer"].lower()
            if item["source_side"] in {"sov", "frg", "gdr", "csa"} or "west81" in layer or "2897299509" in layer:
                legacy_count += 1
            else:
                modern_count += 1
        required_categories = actor.get("required_categories", [])
        missing_categories = [category for category in required_categories if category_counts.get(category, 0) == 0]
        if missing_categories:
            severity = "warning" if actor["roster_class"] in {"national_hybrid", "coalition_fallback", "proxy_hybrid"} else "error"
            problems.append(ResolutionProblem(
                severity, actor_id, "",
                f"missing required roster categories: {', '.join(missing_categories)}",
            ))

        result = {
            "actor_id": actor_id,
            "display_name": actor["display_name"],
            "short_name": actor.get("short_name", actor["display_name"]),
            "actor_type": actor["actor_type"],
            "coalition_id": actor["coalition_id"],
            "tactical_side": tactical_side,
            "host_actor_id": actor.get("host_actor_id"),
            "playable": bool(actor.get("playable", False)),
            "roster_class": actor["roster_class"],
            "research_mode": actor["research"]["mode"],
            "components": list(actor["components"]),
            "component_metadata": [
                {
                    "component_id": component_id,
                    "provenance_policy": components[component_id].provenance_policy,
                    "research_label": components[component_id].research_label,
                }
                for component_id in actor["components"]
            ],
            "unit_count": len(units),
            "modern_unit_count": modern_count,
            "legacy_unit_count": legacy_count,
            "virtual_unit_count": virtual_count,
            "category_counts": dict(sorted(category_counts.items())),
            "required_categories": list(required_categories),
            "missing_categories": missing_categories,
            "units": units,
            "research_node_count": len(research_nodes),
            "research_nodes": [node.to_dict() for node in research_nodes],
            "notes": list(actor.get("notes", [])),
        }
        return result, problems

    def _compile_actor_research(
        self,
        actor: Mapping[str, Any],
        units: Mapping[str, tuple[SourceUnit, str]],
        selected_research: Mapping[str, tuple[SourceResearchNode, str]],
        components: Mapping[str, _ResolvedComponent],
    ) -> list[ResolvedResearchNode]:
        actor_id = actor["actor_id"]
        mode = actor["research"]["mode"]
        root_key = f"actor:{actor_id}:root"
        nodes: dict[str, ResolvedResearchNode] = {
            root_key: ResolvedResearchNode(
                key=root_key,
                actor_id=actor_id,
                node_type="root",
                display_name=actor["research"].get("display_name", f"{actor['display_name']} Armed Forces"),
                cost=0,
            )
        }
        source_key_map: dict[tuple[str, str], str] = {}
        if mode in {"native", "hybrid"}:
            ordered_sources = sorted(
                selected_research.values(),
                key=lambda item: (item[0].side, item[0].source_priority, item[0].node_id),
            )
            for source, component_id in ordered_sources:
                key = f"actor:{actor_id}:source:{_slug(source.side)}:{_slug(source.node_id)}"
                source_key_map[(source.side, source.node_id)] = key
                nodes[key] = ResolvedResearchNode(
                    key=key,
                    actor_id=actor_id,
                    node_type=source.kind,
                    display_name=_display_name(source.node_id),
                    cost=max(0, source.cost),
                    source_node=source.node_id,
                    source_file=source.source_file,
                    component_id=component_id,
                )
            for source, _component_id in ordered_sources:
                key = source_key_map[(source.side, source.node_id)]
                parent = self._nearest_source_parent(source, source_key_map)
                nodes[key].prerequisites = [parent or root_key]
                if source.kind == "unit":
                    unit = self.unit_index.resolve(source.node_id, side=source.side) or self.unit_index.resolve(source.node_id)
                    if unit is not None and unit.name in units:
                        nodes[key].unlock_units = [unit.name]

        already_unlocked = {name for node in nodes.values() for name in node.unlock_units}
        extras = [(name, value) for name, value in units.items() if name not in already_unlocked]
        if mode in {"generated", "hybrid"} or extras:
            category_nodes: dict[tuple[str, str, int], str] = {}
            component_roots: dict[str, str] = {}
            for name, (unit, component_id) in sorted(extras, key=lambda item: (item[1][0].tier, _category_rank(item[1][0].category), item[0])):
                tier = max(1, int(unit.tier))
                category = unit.category if unit.category in CATEGORY_COSTS else "unknown"
                component = components[component_id]
                scope = component_id if component.research_label else ""
                parent_root = root_key
                if component.research_label:
                    parent_root = component_roots.get(component_id, "")
                    if not parent_root:
                        parent_root = f"actor:{actor_id}:component:{_slug(component_id)}"
                        component_roots[component_id] = parent_root
                        nodes[parent_root] = ResolvedResearchNode(
                            key=parent_root,
                            actor_id=actor_id,
                            node_type="component",
                            display_name=component.research_label,
                            cost=0,
                            prerequisites=[root_key],
                            component_id=component_id,
                        )
                category_key = category_nodes.get((scope, category, tier))
                if category_key is None:
                    scope_segment = f":{_slug(component_id)}" if scope else ""
                    category_key = (
                        f"actor:{actor_id}:generated{scope_segment}:"
                        f"{_slug(category)}:tier-{tier}"
                    )
                    category_nodes[(scope, category, tier)] = category_key
                    previous = category_nodes.get((scope, category, tier - 1), parent_root)
                    nodes[category_key] = ResolvedResearchNode(
                        key=category_key,
                        actor_id=actor_id,
                        node_type="category",
                        display_name=f"{_display_name(category)} Tier {tier}",
                        cost=max(0, CATEGORY_COSTS.get(category, 2) + tier - 1),
                        prerequisites=[previous],
                        component_id=component_id,
                    )
                unit_scope = f":{_slug(component_id)}" if scope else ""
                unit_key = f"actor:{actor_id}:generated{unit_scope}:unit:{_slug(name)}"
                nodes[unit_key] = ResolvedResearchNode(
                    key=unit_key,
                    actor_id=actor_id,
                    node_type="unit",
                    display_name=_display_name(_base_name(name)),
                    cost=max(1, unit.research_cost or CATEGORY_COSTS.get(category, 2) + tier),
                    prerequisites=[category_key],
                    unlock_units=[name],
                    component_id=component_id,
                )

        return _topological_research_order(nodes)

    def _nearest_source_parent(
        self,
        source: SourceResearchNode,
        key_map: Mapping[tuple[str, str], str],
    ) -> str | None:
        prerequisite = source.prerequisite
        visited: set[str] = set()
        while prerequisite and prerequisite not in visited:
            visited.add(prerequisite)
            key = key_map.get((source.side, prerequisite))
            if key:
                return key
            parent = self.research_index.get(source.side, prerequisite)
            if parent is None:
                break
            prerequisite = parent.prerequisite
        return None
