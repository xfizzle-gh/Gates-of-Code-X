from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

from .faction_wiring_models import (
    ACTOR_TYPES, MANIFEST_SCHEMA, MANIFEST_VERSION, PROVENANCE_POLICIES, RESEARCH_MODES,
    ROSTER_CLASSES, SELECTOR_KINDS, SUPPORTED_TACTICAL_SIDES,
    FactionWiringError, ResolvedResearchNode,
)


def load_faction_manifest(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        base = files("gates_of_codex").joinpath("data")
        payload = json.loads(base.joinpath("faction_wiring.json").read_text(encoding="utf-8"))
        return _expand_manifest_files(payload, base)
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    return _expand_manifest_files(payload, source.parent)


def _expand_manifest_files(payload: dict[str, Any], base: Any) -> dict[str, Any]:
    if "components_file" not in payload and "actors_file" not in payload:
        return payload
    allowed = {
        "schema",
        "schema_version",
        "source_policy",
        "components_file",
        "actors_file",
        "audit_adjustments_file",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise FactionWiringError(f"Manifest index has unknown fields: {sorted(unknown)}")
    if not payload.get("components_file") or not payload.get("actors_file"):
        raise FactionWiringError("Manifest index requires components_file and actors_file")

    components = json.loads(base.joinpath(payload["components_file"]).read_text(encoding="utf-8"))
    actors = json.loads(base.joinpath(payload["actors_file"]).read_text(encoding="utf-8"))
    adjustments_file = payload.get("audit_adjustments_file")
    if adjustments_file:
        adjustments = json.loads(base.joinpath(adjustments_file).read_text(encoding="utf-8"))
        _apply_audit_adjustments(components, actors, adjustments)

    return {
        "schema": payload["schema"],
        "schema_version": payload["schema_version"],
        "source_policy": payload["source_policy"],
        "components": components,
        "actors": actors,
    }


def _apply_audit_adjustments(
    components: dict[str, Any],
    actors: list[dict[str, Any]],
    adjustments: Mapping[str, Any],
) -> None:
    allowed = {
        "component_exact_unit_additions",
        "component_selector_exclusions",
        "actor_component_removals",
        "actor_note_additions",
    }
    unknown = set(adjustments) - allowed
    if unknown:
        raise FactionWiringError(f"Audit adjustments have unknown fields: {sorted(unknown)}")

    actor_by_id = {actor.get("actor_id"): actor for actor in actors}

    for adjustment in adjustments.get("component_exact_unit_additions", []):
        required = {"component_id", "selector_index", "units", "reason"}
        if set(adjustment) != required:
            raise FactionWiringError("Component audit adjustment has invalid fields")
        component_id = adjustment["component_id"]
        component = components.get(component_id)
        if component is None:
            raise FactionWiringError(f"Audit adjustment references unknown component {component_id}")
        selector_index = int(adjustment["selector_index"])
        selectors = component.get("selectors", [])
        if selector_index < 0 or selector_index >= len(selectors):
            raise FactionWiringError(
                f"Audit adjustment selector index is invalid for {component_id}: {selector_index}"
            )
        selector = selectors[selector_index]
        if selector.get("kind") != "exact":
            raise FactionWiringError(
                f"Audit adjustment for {component_id} must target an exact selector"
            )
        units = adjustment["units"]
        if not isinstance(units, list) or not units or not all(isinstance(unit, str) and unit for unit in units):
            raise FactionWiringError(f"Audit adjustment for {component_id} has invalid units")
        selector["units"] = list(dict.fromkeys([*selector.get("units", []), *units]))

    for adjustment in adjustments.get("component_selector_exclusions", []):
        required = {"component_id", "selector_index", "exclude_regex", "reason"}
        if not isinstance(adjustment, Mapping) or set(adjustment) != required:
            raise FactionWiringError("Component selector-exclusion audit adjustment has invalid fields")
        component_id = adjustment["component_id"]
        component = components.get(component_id)
        if component is None:
            raise FactionWiringError(f"Audit adjustment references unknown component {component_id}")
        selector_index = adjustment["selector_index"]
        if isinstance(selector_index, bool) or not isinstance(selector_index, int):
            raise FactionWiringError(
                f"Audit adjustment selector index is invalid for {component_id}: {selector_index}"
            )
        selectors = component.get("selectors", [])
        if selector_index < 0 or selector_index >= len(selectors):
            raise FactionWiringError(
                f"Audit adjustment selector index is invalid for {component_id}: {selector_index}"
            )
        selector = selectors[selector_index]
        if selector.get("kind") not in {"research_branch", "prefix"}:
            raise FactionWiringError(
                f"Selector exclusion for {component_id} must target a selector supporting exclude_regex"
            )
        pattern = adjustment["exclude_regex"]
        reason = adjustment["reason"]
        if not isinstance(pattern, str) or not pattern or not isinstance(reason, str) or not reason:
            raise FactionWiringError(f"Selector exclusion for {component_id} is incomplete")
        try:
            re.compile(pattern, re.I)
        except re.error as exc:
            raise FactionWiringError(
                f"Selector exclusion regex is invalid for {component_id}: {exc}"
            ) from exc
        existing = str(selector.get("exclude_regex", "") or "")
        selector["exclude_regex"] = (
            f"(?:{existing})|(?:{pattern})" if existing else pattern
        )

    for adjustment in adjustments.get("actor_component_removals", []):
        required = {"actor_id", "components", "reason"}
        if set(adjustment) != required:
            raise FactionWiringError("Actor component-removal adjustment has invalid fields")
        actor_id = adjustment["actor_id"]
        actor = actor_by_id.get(actor_id)
        if actor is None:
            raise FactionWiringError(f"Audit adjustment references unknown actor {actor_id}")
        removals = set(adjustment["components"])
        missing = removals - set(actor.get("components", []))
        if missing:
            raise FactionWiringError(
                f"Audit adjustment cannot remove absent components from {actor_id}: {sorted(missing)}"
            )
        actor["components"] = [
            component_id
            for component_id in actor["components"]
            if component_id not in removals
        ]
        if not actor["components"]:
            raise FactionWiringError(f"Audit adjustment removed every component from {actor_id}")

    note_additions = adjustments.get("actor_note_additions", {})
    if not isinstance(note_additions, dict):
        raise FactionWiringError("actor_note_additions must be an object")
    for actor_id, notes in note_additions.items():
        actor = actor_by_id.get(actor_id)
        if actor is None:
            raise FactionWiringError(f"Audit note references unknown actor {actor_id}")
        if not isinstance(notes, list) or not all(isinstance(note, str) and note for note in notes):
            raise FactionWiringError(f"Audit notes are invalid for actor {actor_id}")
        actor["notes"] = list(dict.fromkeys([*actor.get("notes", []), *notes]))


def validate_faction_manifest(manifest: Mapping[str, Any]) -> None:
    required_top = {"schema", "schema_version", "source_policy", "components", "actors"}
    unknown = set(manifest) - required_top
    missing = required_top - set(manifest)
    if missing or unknown:
        raise FactionWiringError(f"Manifest top-level shape mismatch; missing={sorted(missing)} unknown={sorted(unknown)}")
    if manifest["schema"] != MANIFEST_SCHEMA or manifest["schema_version"] != MANIFEST_VERSION:
        raise FactionWiringError("Unsupported faction-wiring manifest schema")
    if not isinstance(manifest["components"], dict) or not manifest["components"]:
        raise FactionWiringError("Manifest components must be a non-empty object")
    if not isinstance(manifest["actors"], list) or not manifest["actors"]:
        raise FactionWiringError("Manifest actors must be a non-empty array")

    for component_id, component in manifest["components"].items():
        if not _valid_id(component_id):
            raise FactionWiringError(f"Invalid component ID: {component_id}")
        allowed_component_fields = {
            "description", "selectors", "provenance_policy", "research_label",
        }
        if not {"description", "selectors"}.issubset(component) or set(component) - allowed_component_fields:
            raise FactionWiringError(f"Component {component_id} has invalid fields")
        policy = component.get("provenance_policy", "mixed")
        if policy not in PROVENANCE_POLICIES:
            raise FactionWiringError(
                f"Component {component_id} has invalid provenance policy {policy}"
            )
        label = component.get("research_label", "")
        if not isinstance(label, str) or (label and not label.strip()):
            raise FactionWiringError(f"Component {component_id} has invalid research label")
        if not isinstance(component["selectors"], list) or not component["selectors"]:
            raise FactionWiringError(f"Component {component_id} must have selectors")
        for selector in component["selectors"]:
            kind = selector.get("kind")
            if kind not in SELECTOR_KINDS:
                raise FactionWiringError(f"Component {component_id} has invalid selector kind {kind}")
            if kind == "research_branch":
                _require_selector_fields(component_id, selector, {"kind", "source_side", "root"}, {"include_regex", "exclude_regex", "required", "tier"})
            elif kind == "exact":
                _require_selector_fields(component_id, selector, {"kind", "units"}, {"source_side", "required", "tier", "category"})
                if not selector["units"]:
                    raise FactionWiringError(f"Component {component_id} exact selector is empty")
            elif kind == "prefix":
                _require_selector_fields(component_id, selector, {"kind", "prefixes"}, {"source_side", "exclude_regex", "required", "tier"})
            elif kind == "regex":
                _require_selector_fields(component_id, selector, {"kind", "patterns"}, {"source_side", "required", "tier"})
            elif kind == "virtual":
                _require_selector_fields(component_id, selector, {"kind", "units"}, set())
                for unit in selector["units"]:
                    required = {"name", "source_side", "category", "members", "tier", "cost"}
                    allowed = required | {"period", "vehicles", "actions"}
                    if required - set(unit) or set(unit) - allowed:
                        raise FactionWiringError(f"Virtual unit in {component_id} has invalid fields")
                    if not unit["members"] and not unit.get("vehicles"):
                        raise FactionWiringError(f"Virtual unit {unit['name']} is not materializable")

    actor_ids: set[str] = set()
    for actor in manifest["actors"]:
        required = {
            "actor_id", "display_name", "actor_type", "coalition_id", "tactical_side",
            "playable", "roster_class", "components", "research", "required_categories", "notes",
        }
        allowed = required | {"short_name", "host_actor_id"}
        missing_actor = required - set(actor)
        unknown_actor = set(actor) - allowed
        if missing_actor or unknown_actor:
            raise FactionWiringError(
                f"Actor shape mismatch for {actor.get('actor_id', '<unknown>')}; missing={sorted(missing_actor)} unknown={sorted(unknown_actor)}"
            )
        actor_id = actor["actor_id"]
        if not _valid_id(actor_id) or actor_id in actor_ids:
            raise FactionWiringError(f"Invalid or duplicate actor ID: {actor_id}")
        actor_ids.add(actor_id)
        if actor["actor_type"] not in ACTOR_TYPES:
            raise FactionWiringError(f"Actor {actor_id} has invalid actor_type")
        if actor["tactical_side"] not in SUPPORTED_TACTICAL_SIDES:
            raise FactionWiringError(f"Actor {actor_id} has unsupported tactical side")
        if actor["roster_class"] not in ROSTER_CLASSES:
            raise FactionWiringError(f"Actor {actor_id} has invalid roster_class")
        if not actor["components"] or len(set(actor["components"])) != len(actor["components"]):
            raise FactionWiringError(f"Actor {actor_id} must have unique components")
        unknown_components = set(actor["components"]) - set(manifest["components"])
        if unknown_components:
            raise FactionWiringError(f"Actor {actor_id} references unknown components {sorted(unknown_components)}")
        if set(actor["research"]) - {"mode", "display_name"} or "mode" not in actor["research"]:
            raise FactionWiringError(f"Actor {actor_id} research shape is invalid")
        if actor["research"]["mode"] not in RESEARCH_MODES:
            raise FactionWiringError(f"Actor {actor_id} has invalid research mode")
    for actor in manifest["actors"]:
        host = actor.get("host_actor_id")
        if host and host not in actor_ids:
            raise FactionWiringError(f"Actor {actor['actor_id']} references unknown host actor {host}")


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[a-z][a-z0-9_]*", value))


def _topological_research_order(nodes: Mapping[str, ResolvedResearchNode]) -> list[ResolvedResearchNode]:
    indegree = {key: 0 for key in nodes}
    children: dict[str, list[str]] = defaultdict(list)
    for key, node in nodes.items():
        for prerequisite in node.prerequisites:
            if prerequisite not in nodes:
                raise FactionWiringError(f"Research node {key} references missing prerequisite {prerequisite}")
            indegree[key] += 1
            children[prerequisite].append(key)
    ready = sorted(key for key, value in indegree.items() if value == 0)
    ordered: list[ResolvedResearchNode] = []
    while ready:
        key = ready.pop(0)
        ordered.append(nodes[key])
        for child in sorted(children.get(key, [])):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    if len(ordered) != len(nodes):
        cyclic = sorted(key for key, value in indegree.items() if value > 0)
        raise FactionWiringError(f"Research graph contains a cycle: {', '.join(cyclic[:10])}")
    return ordered


def _require_selector_fields(component_id: str, selector: Mapping[str, Any], required: set[str], optional: set[str]) -> None:
    missing = required - set(selector)
    unknown = set(selector) - required - optional
    if missing or unknown:
        raise FactionWiringError(
            f"Selector in {component_id} has invalid shape; missing={sorted(missing)} unknown={sorted(unknown)}"
        )


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
