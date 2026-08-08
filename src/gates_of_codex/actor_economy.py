from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .models import BattalionRosterEntry, CampaignState, Faction
from .strategic_actors import (
    ACTOR_RUNTIME_KEY,
    StrategicActorState,
    ensure_strategic_actor_runtime,
    install_bundled_strategic_actors,
    validate_strategic_actor_runtime,
)

ACTOR_CONTENT_KEY = "actor_content_runtime"
ACTOR_CONTENT_SCHEMA_VERSION = 1
ACTOR_CONTENT_CAMPAIGN_SCHEMA_VERSION = 10
RESOLVED_SCHEMA = "gates-of-codex.resolved-factions"
RESOLVED_SCHEMA_VERSION = 1
RESEARCH_RESOURCE_MULTIPLIER = 50

CATEGORY_PURCHASE_BASE = {
    "infantry": 70,
    "recon": 120,
    "anti_armor": 130,
    "vehicle": 190,
    "apc": 230,
    "ifv": 260,
    "tank": 360,
    "artillery": 280,
    "air_defense": 260,
    "aviation": 520,
    "logistics": 100,
    "unknown": 90,
}


@dataclass(frozen=True, slots=True)
class ActorResearchOption:
    actor_id: str
    key: str
    display_name: str
    cost: int
    prerequisites: tuple[str, ...]
    unlock_units: tuple[str, ...]
    source_node: str = ""
    component_id: str = ""


@dataclass(frozen=True, slots=True)
class ActorResearchPurchase:
    actor_id: str
    key: str
    cost: int
    resources_remaining: int


@dataclass(frozen=True, slots=True)
class ActorRecruitmentOffer:
    actor_id: str
    strategic_formation_id: str
    unit_name: str
    category: str
    purchase_cost: int
    maintenance_cost: int
    repair_cost_per_point: int
    research_options: tuple[str, ...]
    missing_research: tuple[str, ...]
    unlocked: bool
    preferred: bool
    tactical_side: str
    source_side: str
    component_id: str
    infrastructure_discount: float = 0.0


@dataclass(frozen=True, slots=True)
class ActorReinforcementPurchase:
    actor_id: str
    strategic_formation_id: str
    unit_name: str
    quantity: int
    unit_cost: int
    total_cost: int
    pool_quantity: int
    resources_remaining: int


@dataclass(frozen=True, slots=True)
class ActorReinforcementTransfer:
    actor_id: str
    strategic_formation_id: str
    battalion_id: str
    unit_name: str
    quantity: int
    replacements: int
    expansion: int
    pool_remaining: int


@dataclass(frozen=True, slots=True)
class ActorRepairResult:
    actor_id: str
    strategic_formation_id: str
    battalion_id: str
    points_repaired: int
    cost: int
    condition: int
    resources_remaining: int


@dataclass(frozen=True, slots=True)
class ActorRoundEconomyReport:
    actor_id: str
    income: int
    maintenance_due: int
    maintenance_paid: int
    shortfall: int
    resources_remaining: int


def load_resolved_factions(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def install_actor_content(
    state: CampaignState,
    resolved_payload: Mapping[str, Any],
    *,
    selected_actor_id: str | None = None,
    allow_warnings: bool = False,
) -> dict[str, Any]:
    """Install a live resolved roster/research payload into a campaign.

    Installation is explicit. Normal legacy load/save paths remain untouched until
    this function or the actor-content CLI is invoked.
    """

    if selected_actor_id is not None:
        actors = install_bundled_strategic_actors(state, selected_actor_id=selected_actor_id)
    else:
        actors = ensure_strategic_actor_runtime(state)
    _validate_resolved_payload(resolved_payload, actors, allow_warnings=allow_warnings)

    content_actors: dict[str, dict[str, Any]] = {}
    for raw_actor in sorted(resolved_payload["actors"], key=lambda item: item["actor_id"]):
        actor_id = raw_actor["actor_id"]
        research_nodes = _build_research_nodes(raw_actor)
        unit_unlocks: dict[str, list[str]] = {unit["unit_name"]: [] for unit in raw_actor["units"]}
        for node in research_nodes.values():
            for unit_name in node["unlock_units"]:
                unit_unlocks.setdefault(unit_name, []).append(node["key"])
        units = {
            raw_unit["unit_name"]: _build_unit_economy(raw_unit, unit_unlocks.get(raw_unit["unit_name"], []))
            for raw_unit in sorted(raw_actor["units"], key=lambda item: item["unit_name"])
        }
        content_actors[actor_id] = {
            "actor_id": actor_id,
            "display_name": raw_actor["display_name"],
            "tactical_side": raw_actor["tactical_side"],
            "roster_class": raw_actor["roster_class"],
            "units": units,
            "research_nodes": research_nodes,
        }

    migration_exceptions: list[dict[str, str]] = []
    for actor_id, actor in actors.items():
        nodes = content_actors[actor_id]["research_nodes"]
        valid_keys = set(nodes)
        roots = {key for key, node in nodes.items() if node["node_type"] == "root"}
        actor.researched_keys = sorted(set(actor.researched_keys) & valid_keys | roots)

    for battalion in sorted(state.battalions.values(), key=lambda item: item.battalion_id):
        actor_id = _actor_for_battalion(state, battalion.battalion_id, actors)
        actor_content = content_actors[actor_id]
        for entry in battalion.roster:
            unit = actor_content["units"].get(entry.unit_name)
            if unit is None:
                migration_exceptions.append({
                    "actor_id": actor_id,
                    "battalion_id": battalion.battalion_id,
                    "unit_name": entry.unit_name,
                    "reason": "current unit is outside the installed actor roster; retained as grandfathered equipment",
                })
                continue
            research_options = unit["research_options"]
            if research_options:
                chosen = min(
                    research_options,
                    key=lambda key: (actor_content["research_nodes"][key]["cost"], key),
                )
                _grant_research_closure(actor, actor_content["research_nodes"], chosen)

    _commit_actor_states(state, actors)
    runtime = {
        "schema_version": ACTOR_CONTENT_SCHEMA_VERSION,
        "resolved_schema": resolved_payload["schema"],
        "resolved_schema_version": resolved_payload["schema_version"],
        "wiring_signature": resolved_payload["wiring_signature"],
        "stack_signature": resolved_payload["stack_signature"],
        "manifest_sha256": resolved_payload["manifest_sha256"],
        "source_policy": resolved_payload["source_policy"],
        "source_layers": resolved_payload["source_layers"],
        "actor_count": len(content_actors),
        "actors": content_actors,
        "reinforcement_pool": [],
        "migration_exceptions": migration_exceptions,
        "warning_count": int(resolved_payload.get("warning_count", 0)),
    }
    state.map_metadata[ACTOR_CONTENT_KEY] = runtime
    state.schema_version = max(state.schema_version, ACTOR_CONTENT_CAMPAIGN_SCHEMA_VERSION)
    validate_actor_content_runtime(state)
    state.validate()
    return runtime


def actor_content_snapshot(state: CampaignState) -> dict[str, Any]:
    runtime = _runtime(state)
    validate_actor_content_runtime(state)
    return json.loads(json.dumps(runtime, sort_keys=True))


def available_actor_research(state: CampaignState, actor_id: str) -> list[ActorResearchOption]:
    runtime = _runtime(state)
    actors = ensure_strategic_actor_runtime(state)
    actor = _require_actor(actors, actor_id)
    nodes = runtime["actors"][actor_id]["research_nodes"]
    researched = set(actor.researched_keys)
    values = [
        ActorResearchOption(
            actor_id=actor_id,
            key=node["key"],
            display_name=node["display_name"],
            cost=node["cost"],
            prerequisites=tuple(node["prerequisites"]),
            unlock_units=tuple(node["unlock_units"]),
            source_node=node["source_node"],
            component_id=node["component_id"],
        )
        for node in nodes.values()
        if node["key"] not in researched and set(node["prerequisites"]).issubset(researched)
    ]
    return sorted(values, key=lambda item: (item.cost, item.key))


def purchase_actor_research(state: CampaignState, actor_id: str, key: str) -> ActorResearchPurchase:
    runtime = _runtime(state)
    actors = ensure_strategic_actor_runtime(state)
    actor = _require_actor(actors, actor_id)
    nodes = runtime["actors"][actor_id]["research_nodes"]
    node = nodes.get(key)
    if node is None:
        raise KeyError(f"Unknown research key for {actor_id}: {key}")
    if key in actor.researched_keys:
        raise ValueError(f"Research already completed: {key}")
    missing = sorted(set(node["prerequisites"]) - set(actor.researched_keys))
    if missing:
        raise ValueError(f"Research prerequisites not met for {key}: {', '.join(missing)}")
    if actor.resources < node["cost"]:
        raise ValueError(f"Insufficient resources for {key}: need {node['cost']}")
    actor.resources -= node["cost"]
    actor.researched_keys = sorted(set(actor.researched_keys) | {key})
    _commit_actor_states(state, actors)
    return ActorResearchPurchase(actor_id, key, node["cost"], actor.resources)


def actor_recruitment_offers(
    state: CampaignState,
    strategic_formation_id: str,
) -> list[ActorRecruitmentOffer]:
    runtime = _runtime(state)
    actors = ensure_strategic_actor_runtime(state)
    force, actor = _force_actor(state, strategic_formation_id, actors)
    actor_content = runtime["actors"][actor.actor_id]
    researched = set(actor.researched_keys)
    template = state.formations.get(force.template_formation_id)
    preferred_categories = set(template.preferred_categories if template else [])
    discount = 0.0
    if template is not None:
        from .strategic import recruitment_discount_for_formation

        discount = recruitment_discount_for_formation(state, template.formation_id)

    offers: list[ActorRecruitmentOffer] = []
    for unit in actor_content["units"].values():
        options = tuple(unit["research_options"])
        unlocked = not options or any(key in researched for key in options)
        missing = () if unlocked else options
        discounted = max(1, int(math.ceil(unit["purchase_cost"] * (1.0 - discount) / 5.0) * 5))
        offers.append(
            ActorRecruitmentOffer(
                actor_id=actor.actor_id,
                strategic_formation_id=strategic_formation_id,
                unit_name=unit["unit_name"],
                category=unit["category"],
                purchase_cost=discounted,
                maintenance_cost=unit["maintenance_cost"],
                repair_cost_per_point=unit["repair_cost_per_point"],
                research_options=options,
                missing_research=missing,
                unlocked=unlocked,
                preferred=unit["category"] in preferred_categories,
                tactical_side=unit["tactical_side"],
                source_side=unit["source_side"],
                component_id=unit["component_id"],
                infrastructure_discount=discount,
            )
        )
    return sorted(
        offers,
        key=lambda item: (not item.unlocked, not item.preferred, item.purchase_cost, item.unit_name),
    )


def purchase_actor_reinforcements(
    state: CampaignState,
    strategic_formation_id: str,
    unit_name: str,
    quantity: int = 1,
) -> ActorReinforcementPurchase:
    if quantity < 1:
        raise ValueError("Reinforcement quantity must be positive")
    runtime = _runtime(state)
    actors = ensure_strategic_actor_runtime(state)
    _force, actor = _force_actor(state, strategic_formation_id, actors)
    offer = next(
        (item for item in actor_recruitment_offers(state, strategic_formation_id) if item.unit_name == unit_name),
        None,
    )
    if offer is None:
        raise ValueError(f"Unit {unit_name} is outside actor {actor.actor_id}'s roster")
    if not offer.unlocked:
        raise ValueError(f"Unit {unit_name} requires one of: {', '.join(offer.missing_research)}")
    total_cost = offer.purchase_cost * quantity
    if actor.resources < total_cost:
        raise ValueError(f"Insufficient resources: need {total_cost}")
    actor.resources -= total_cost
    pool = runtime["reinforcement_pool"]
    entry = next(
        (
            value
            for value in pool
            if value["actor_id"] == actor.actor_id
            and value["strategic_formation_id"] == strategic_formation_id
            and value["unit_name"] == unit_name
        ),
        None,
    )
    if entry is None:
        entry = {
            "actor_id": actor.actor_id,
            "strategic_formation_id": strategic_formation_id,
            "unit_name": unit_name,
            "quantity": 0,
            "category": offer.category,
            "unit_cost": offer.purchase_cost,
        }
        pool.append(entry)
    entry["quantity"] += quantity
    pool.sort(key=lambda value: (value["actor_id"], value["strategic_formation_id"], value["unit_name"]))
    _commit_actor_states(state, actors)
    validate_actor_content_runtime(state)
    return ActorReinforcementPurchase(
        actor_id=actor.actor_id,
        strategic_formation_id=strategic_formation_id,
        unit_name=unit_name,
        quantity=quantity,
        unit_cost=offer.purchase_cost,
        total_cost=total_cost,
        pool_quantity=entry["quantity"],
        resources_remaining=actor.resources,
    )


def assign_actor_reinforcements(
    state: CampaignState,
    strategic_formation_id: str,
    unit_name: str,
    quantity: int = 1,
    *,
    battalion_id: str | None = None,
) -> ActorReinforcementTransfer:
    if quantity < 1:
        raise ValueError("Transfer quantity must be positive")
    runtime = _runtime(state)
    actors = ensure_strategic_actor_runtime(state)
    force, actor = _force_actor(state, strategic_formation_id, actors)
    target = _force_battalion(state, force.battalion_ids, battalion_id)
    pool = runtime["reinforcement_pool"]
    entry = next(
        (
            value
            for value in pool
            if value["actor_id"] == actor.actor_id
            and value["strategic_formation_id"] == strategic_formation_id
            and value["unit_name"] == unit_name
        ),
        None,
    )
    if entry is None or entry["quantity"] < quantity:
        available = entry["quantity"] if entry else 0
        raise ValueError(f"Only {available} {unit_name} reinforcement(s) available")
    current = _entry_quantity(target.roster, unit_name)
    authorized = _entry_quantity(target.authorized_roster, unit_name)
    replacements = min(quantity, max(0, authorized - current))
    expansion = quantity - replacements
    _add_roster_quantity(target.roster, unit_name, entry["category"], quantity)
    if expansion:
        _add_roster_quantity(target.authorized_roster, unit_name, entry["category"], expansion)
    entry["quantity"] -= quantity
    remaining = entry["quantity"]
    if remaining == 0:
        pool.remove(entry)
    validate_actor_content_runtime(state)
    state.validate()
    return ActorReinforcementTransfer(
        actor_id=actor.actor_id,
        strategic_formation_id=strategic_formation_id,
        battalion_id=target.battalion_id,
        unit_name=unit_name,
        quantity=quantity,
        replacements=replacements,
        expansion=expansion,
        pool_remaining=remaining,
    )


def repair_actor_formation(
    state: CampaignState,
    strategic_formation_id: str,
    points: int | None = None,
    *,
    battalion_id: str | None = None,
) -> ActorRepairResult:
    runtime = _runtime(state)
    actors = ensure_strategic_actor_runtime(state)
    force, actor = _force_actor(state, strategic_formation_id, actors)
    target = _force_battalion(state, force.battalion_ids, battalion_id)
    if target.condition >= 100:
        return ActorRepairResult(actor.actor_id, strategic_formation_id, target.battalion_id, 0, 0, 100, actor.resources)
    if target.supply < 50 or target.encircled_turns > 0:
        raise ValueError(f"Formation {strategic_formation_id} must be supplied to repair")
    units = runtime["actors"][actor.actor_id]["units"]
    cost_per_point = max(
        1,
        sum(
            units.get(entry.unit_name, {"repair_cost_per_point": 1})["repair_cost_per_point"] * entry.quantity
            for entry in target.roster
        ),
    )
    missing = 100 - target.condition
    requested = missing if points is None else min(missing, max(0, points))
    if requested == 0:
        return ActorRepairResult(actor.actor_id, strategic_formation_id, target.battalion_id, 0, 0, target.condition, actor.resources)
    affordable = actor.resources // cost_per_point
    repaired = min(requested, affordable)
    if points is not None and repaired < requested:
        raise ValueError(f"Insufficient resources to repair {requested} points")
    if repaired <= 0:
        raise ValueError("Insufficient resources to repair formation")
    cost = repaired * cost_per_point
    actor.resources -= cost
    target.condition += repaired
    _commit_actor_states(state, actors)
    state.validate()
    return ActorRepairResult(
        actor.actor_id,
        strategic_formation_id,
        target.battalion_id,
        repaired,
        cost,
        target.condition,
        actor.resources,
    )


def settle_actor_round_economy(state: CampaignState) -> list[ActorRoundEconomyReport]:
    runtime = _runtime(state)
    actors = ensure_strategic_actor_runtime(state)
    income_by_actor = {actor_id: 0 for actor_id in actors}
    for province in state.provinces.values():
        actor_id = province.metadata.get("owner_actor_id")
        if actor_id in income_by_actor:
            income_by_actor[str(actor_id)] += province.resource_yield

    battalions_by_actor: dict[str, list[Any]] = {actor_id: [] for actor_id in actors}
    for battalion in state.battalions.values():
        actor_id = _actor_for_battalion(state, battalion.battalion_id, actors)
        battalions_by_actor[actor_id].append(battalion)

    reports: list[ActorRoundEconomyReport] = []
    for actor_id in sorted(actors):
        actor = actors[actor_id]
        units = runtime["actors"][actor_id]["units"]
        income = income_by_actor[actor_id]
        maintenance = sum(
            units.get(entry.unit_name, {"maintenance_cost": 2})["maintenance_cost"] * entry.quantity
            for battalion in battalions_by_actor[actor_id]
            for entry in battalion.roster
        )
        actor.resources += income
        paid = min(actor.resources, maintenance)
        actor.resources -= paid
        shortfall = maintenance - paid
        if shortfall:
            for battalion in battalions_by_actor[actor_id]:
                battalion.condition = max(25, battalion.condition - 5)
        reports.append(
            ActorRoundEconomyReport(
                actor_id=actor_id,
                income=income,
                maintenance_due=maintenance,
                maintenance_paid=paid,
                shortfall=shortfall,
                resources_remaining=actor.resources,
            )
        )
    _commit_actor_states(state, actors)
    runtime["last_round_economy"] = [asdict(report) for report in reports]
    state.validate()
    return reports


def validate_actor_content_runtime(state: CampaignState) -> None:
    runtime = state.map_metadata.get(ACTOR_CONTENT_KEY)
    if not isinstance(runtime, dict) or runtime.get("schema_version") != ACTOR_CONTENT_SCHEMA_VERSION:
        raise ValueError("Campaign actor content runtime is missing or unsupported")
    actors = ensure_strategic_actor_runtime(state)
    content_actors = runtime.get("actors")
    if not isinstance(content_actors, dict) or set(content_actors) != set(actors):
        raise ValueError("Actor content set does not match strategic actor runtime")
    for actor_id, content in content_actors.items():
        if content.get("actor_id") != actor_id:
            raise ValueError(f"Actor content key mismatch: {actor_id}")
        if content.get("tactical_side") != actors[actor_id].tactical_side.value:
            raise ValueError(f"Actor content tactical-side mismatch: {actor_id}")
        units = content.get("units")
        nodes = content.get("research_nodes")
        if not isinstance(units, dict) or not isinstance(nodes, dict):
            raise ValueError(f"Actor content {actor_id} must contain units and research nodes")
        if actors[actor_id].playable and (not units or not nodes):
            raise ValueError(f"Playable actor {actor_id} has empty content")
        _validate_research_graph(actor_id, nodes, set(units))
        for unit_name, unit in units.items():
            if unit.get("unit_name") != unit_name:
                raise ValueError(f"Actor {actor_id} unit key mismatch: {unit_name}")
            if unit.get("tactical_side") != actors[actor_id].tactical_side.value:
                raise ValueError(f"Actor {actor_id} unit tactical-side mismatch: {unit_name}")
            if not unit.get("materializable"):
                raise ValueError(f"Actor {actor_id} unit is not materializable: {unit_name}")
            if min(unit["purchase_cost"], unit["maintenance_cost"], unit["repair_cost_per_point"]) < 0:
                raise ValueError(f"Actor {actor_id} unit has invalid economy: {unit_name}")
            for key in unit["research_options"]:
                if key not in nodes:
                    raise ValueError(f"Actor {actor_id} unit references missing research: {unit_name} -> {key}")
    pool = runtime.get("reinforcement_pool")
    if not isinstance(pool, list):
        raise ValueError("Actor reinforcement pool must be an array")
    seen: set[tuple[str, str, str]] = set()
    for entry in pool:
        key = (entry["actor_id"], entry["strategic_formation_id"], entry["unit_name"])
        if key in seen:
            raise ValueError(f"Duplicate actor reinforcement pool entry: {key}")
        seen.add(key)
        if entry["actor_id"] not in actors:
            raise ValueError(f"Actor reinforcement references missing actor: {entry['actor_id']}")
        if entry["quantity"] < 1 or entry["unit_cost"] < 0:
            raise ValueError(f"Actor reinforcement entry has invalid quantity/cost: {key}")
        if entry["unit_name"] not in content_actors[entry["actor_id"]]["units"]:
            raise ValueError(f"Actor reinforcement references out-of-roster unit: {key}")


def _validate_resolved_payload(
    payload: Mapping[str, Any],
    actors: Mapping[str, StrategicActorState],
    *,
    allow_warnings: bool,
) -> None:
    required = {
        "schema",
        "schema_version",
        "stack_signature",
        "manifest_sha256",
        "wiring_signature",
        "source_policy",
        "source_layers",
        "actor_count",
        "actors",
        "error_count",
        "warning_count",
    }
    missing = required - set(payload)
    if missing:
        raise ValueError(f"Resolved faction payload is missing fields: {', '.join(sorted(missing))}")
    if payload["schema"] != RESOLVED_SCHEMA or payload["schema_version"] != RESOLVED_SCHEMA_VERSION:
        raise ValueError("Unsupported resolved faction payload schema")
    if int(payload["error_count"]) != 0:
        raise ValueError(f"Resolved faction payload has {payload['error_count']} error(s)")
    if int(payload["warning_count"]) and not allow_warnings:
        raise ValueError(f"Resolved faction payload has {payload['warning_count']} warning(s)")
    raw_actors = payload["actors"]
    if not isinstance(raw_actors, list) or int(payload["actor_count"]) != len(raw_actors):
        raise ValueError("Resolved faction actor_count does not match actors")
    actor_ids = [item["actor_id"] for item in raw_actors]
    if len(actor_ids) != len(set(actor_ids)):
        raise ValueError("Resolved faction payload contains duplicate actors")
    if set(actor_ids) != set(actors):
        missing_runtime = sorted(set(actor_ids) - set(actors))
        missing_payload = sorted(set(actors) - set(actor_ids))
        raise ValueError(
            f"Resolved actor set mismatch; runtime_missing={missing_runtime} payload_missing={missing_payload}"
        )
    for raw_actor in raw_actors:
        actor_id = raw_actor["actor_id"]
        if raw_actor["tactical_side"] != actors[actor_id].tactical_side.value:
            raise ValueError(f"Resolved actor tactical-side mismatch: {actor_id}")
        if not isinstance(raw_actor.get("units"), list) or not isinstance(raw_actor.get("research_nodes"), list):
            raise ValueError(f"Resolved actor {actor_id} is missing units or research")
        unit_names = [unit["unit_name"] for unit in raw_actor["units"]]
        if len(unit_names) != len(set(unit_names)):
            raise ValueError(f"Resolved actor {actor_id} contains duplicate units")
        node_keys = [node["key"] for node in raw_actor["research_nodes"]]
        if len(node_keys) != len(set(node_keys)):
            raise ValueError(f"Resolved actor {actor_id} contains duplicate research nodes")
        nodes = {node["key"]: node for node in raw_actor["research_nodes"]}
        _validate_research_graph(actor_id, nodes, set(unit_names))
        if actors[actor_id].playable and (not unit_names or not nodes):
            raise ValueError(f"Resolved playable actor {actor_id} is empty")
        for unit in raw_actor["units"]:
            if unit["actor_id"] != actor_id or unit["tactical_side"] != actors[actor_id].tactical_side.value:
                raise ValueError(f"Resolved unit ownership mismatch: {actor_id}:{unit['unit_name']}")
            if not unit.get("materializable"):
                raise ValueError(f"Resolved unit is not materializable: {actor_id}:{unit['unit_name']}")


def _validate_research_graph(actor_id: str, nodes: Mapping[str, Mapping[str, Any]], units: set[str]) -> None:
    for key, node in nodes.items():
        if node.get("key") != key:
            raise ValueError(f"Research key mismatch for actor {actor_id}: {key}")
        if not key.startswith(f"actor:{actor_id}:"):
            raise ValueError(f"Research key is not actor-scoped: {key}")
        for prerequisite in node.get("prerequisites", []):
            if prerequisite not in nodes:
                raise ValueError(f"Research node {key} references missing prerequisite {prerequisite}")
        for unit_name in node.get("unlock_units", []):
            if unit_name not in units:
                raise ValueError(f"Research node {key} unlocks missing unit {unit_name}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visited:
            return
        if key in visiting:
            raise ValueError(f"Research graph contains a cycle for actor {actor_id}: {key}")
        visiting.add(key)
        for prerequisite in nodes[key].get("prerequisites", []):
            visit(prerequisite)
        visiting.remove(key)
        visited.add(key)

    for key in sorted(nodes):
        visit(key)


def _build_research_nodes(raw_actor: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for raw in raw_actor["research_nodes"]:
        source_cost = max(0, int(raw.get("cost", 0)))
        cost = 0 if raw.get("node_type") == "root" else max(50, source_cost * RESEARCH_RESOURCE_MULTIPLIER)
        values[raw["key"]] = {
            "key": raw["key"],
            "actor_id": raw_actor["actor_id"],
            "node_type": raw["node_type"],
            "display_name": raw["display_name"],
            "cost": cost,
            "source_cost": source_cost,
            "prerequisites": sorted(set(raw.get("prerequisites", []))),
            "unlock_units": sorted(set(raw.get("unlock_units", []))),
            "source_node": raw.get("source_node", ""),
            "source_file": raw.get("source_file", ""),
            "component_id": raw.get("component_id", ""),
        }
    return values


def _build_unit_economy(raw: Mapping[str, Any], research_options: Sequence[str]) -> dict[str, Any]:
    category = raw.get("category", "unknown")
    base = CATEGORY_PURCHASE_BASE.get(category, CATEGORY_PURCHASE_BASE["unknown"])
    manpower = sum(max(0, int(value)) for value in raw.get("members", {}).values())
    vehicle_count = len(set(raw.get("vehicles", [])))
    tier = max(1, int(raw.get("tier", 1)))
    source_research_cost = max(0, int(raw.get("research_cost", 0)))
    purchase = base + manpower * 18 + vehicle_count * 55 + (tier - 1) * 30 + source_research_cost * 10
    purchase = max(50, int(math.ceil(purchase / 5.0) * 5))
    return {
        "unit_name": raw["unit_name"],
        "actor_id": raw["actor_id"],
        "component_id": raw.get("component_id", ""),
        "source_side": raw["source_side"],
        "tactical_side": raw["tactical_side"],
        "period": raw.get("period", ""),
        "category": category,
        "members": dict(sorted(raw.get("members", {}).items())),
        "vehicles": sorted(set(raw.get("vehicles", []))),
        "actions": sorted(set(raw.get("actions", []))),
        "materializable": bool(raw.get("materializable", False)),
        "source_files": sorted(set(raw.get("source_files", []))),
        "source_layer": raw.get("source_layer", ""),
        "source_priority": int(raw.get("source_priority", -1)),
        "virtual": bool(raw.get("virtual", False)),
        "tier": tier,
        "source_research_cost": source_research_cost,
        "research_options": sorted(set(research_options)),
        "purchase_cost": purchase,
        "maintenance_cost": max(2, math.ceil(purchase * 0.035)),
        "repair_cost_per_point": max(1, math.ceil(purchase * 0.0025)),
        "manpower_estimate": manpower,
    }


def _runtime(state: CampaignState) -> dict[str, Any]:
    runtime = state.map_metadata.get(ACTOR_CONTENT_KEY)
    if not isinstance(runtime, dict):
        raise ValueError("Actor content is not installed in this campaign")
    return runtime


def _require_actor(
    actors: Mapping[str, StrategicActorState],
    actor_id: str,
) -> StrategicActorState:
    actor = actors.get(actor_id)
    if actor is None:
        raise KeyError(f"Unknown strategic actor: {actor_id}")
    return actor


def _commit_actor_states(
    state: CampaignState,
    actors: Mapping[str, StrategicActorState],
) -> None:
    raw = state.map_metadata.get(ACTOR_RUNTIME_KEY)
    if not isinstance(raw, dict):
        raise ValueError("Strategic actor runtime is not installed")
    raw["actors"] = {key: actors[key].to_dict() for key in sorted(actors)}
    validate_strategic_actor_runtime(state)


def _force_actor(
    state: CampaignState,
    strategic_formation_id: str,
    actors: Mapping[str, StrategicActorState],
):
    force = state.strategic_formations.get(strategic_formation_id)
    if force is None:
        raise KeyError(f"Unknown strategic formation: {strategic_formation_id}")
    actor = actors.get(force.actor_id)
    if actor is None:
        raise ValueError(f"Strategic formation {strategic_formation_id} has no valid actor")
    if actor.tactical_side != force.faction:
        raise ValueError(f"Strategic formation {strategic_formation_id} actor tactical-side mismatch")
    return force, actor


def _actor_for_battalion(
    state: CampaignState,
    battalion_id: str,
    actors: Mapping[str, StrategicActorState],
) -> str:
    battalion = state.battalions[battalion_id]
    if battalion.strategic_formation_id:
        force = state.strategic_formations.get(battalion.strategic_formation_id)
        if force and force.actor_id in actors:
            actor = actors[force.actor_id]
            if actor.tactical_side == battalion.faction:
                return actor.actor_id
    matching = sorted(
        actor.actor_id
        for actor in actors.values()
        if actor.tactical_side == battalion.faction and actor.playable
    )
    if not matching:
        raise ValueError(f"Battalion {battalion_id} has no compatible strategic actor")
    return matching[0]


def _force_battalion(
    state: CampaignState,
    battalion_ids: Sequence[str],
    battalion_id: str | None,
):
    available = sorted(item for item in battalion_ids if item in state.battalions)
    if battalion_id is not None:
        if battalion_id not in available:
            raise ValueError(f"Battalion {battalion_id} is not in the strategic formation")
        return state.battalions[battalion_id]
    if len(available) != 1:
        raise ValueError("Specify battalion_id when a strategic formation has zero or multiple battalions")
    return state.battalions[available[0]]


def _grant_research_closure(
    actor: StrategicActorState,
    nodes: Mapping[str, Mapping[str, Any]],
    key: str,
) -> None:
    node = nodes[key]
    for prerequisite in node["prerequisites"]:
        _grant_research_closure(actor, nodes, prerequisite)
    actor.researched_keys = sorted(set(actor.researched_keys) | {key})


def _entry_quantity(roster: Sequence[BattalionRosterEntry], unit_name: str) -> int:
    return sum(entry.quantity for entry in roster if entry.unit_name == unit_name)


def _add_roster_quantity(
    roster: list[BattalionRosterEntry],
    unit_name: str,
    category: str,
    quantity: int,
) -> None:
    entry = next((value for value in roster if value.unit_name == unit_name), None)
    if entry is None:
        roster.append(BattalionRosterEntry(unit_name, quantity=quantity, category=category))
    else:
        entry.quantity += quantity
