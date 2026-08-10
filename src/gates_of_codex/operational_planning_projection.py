from __future__ import annotations

import copy
from typing import Any, Iterable

from .models import (
    Alliance,
    CampaignState,
    Faction,
    FactionState,
    ForceEchelon,
    Province,
    StrategicFormation,
)
from .operational_capture import (
    SITE_CONTROL_KEY,
    ensure_site_control_state,
    list_control_sites,
    set_site_control_state,
)
from .operational_movement import move_order_from_dict
from .operational_position import (
    _graph_indexes,
    _position_is_valid,
    load_operational_graph_for_state,
    position_from_dict,
)


class OperationalPlanningProjectionError(ValueError):
    """A restricted S11 planning projection is malformed or over-privileged."""


def build_restricted_p3_planning_state(
    payload: dict[str, Any],
    *,
    visible_subject_keys: Iterable[str],
) -> CampaignState:
    """Construct a detached planner DTO from an already S11-filtered P3 payload.

    This is deliberately not a persisted-campaign loader. The S11 projection has
    removed authoritative actor runtime and hidden formations, so routing it
    through ``campaign_from_dict`` would either fail P2/P3 provenance checks or
    require weakening them. Instead, construct only the state surfaces consumed
    by the operational planner and independently authenticate the public P3 graph.

    Mutable site-capture progress is also absent from the serialized projection.
    After graph authentication, the planner derives only each site's current
    visible controller from the already-visible province owner and initializes a
    zero-progress internal control row. This prevents authored starting ownership
    from overriding an evolved captured province without exposing claimant/progress
    state.

    No actor runtime, catalog content, hidden battalions, commanders, research,
    economy, observation records, or pending-battle details are reconstructed.
    """
    if not isinstance(payload, dict):
        raise OperationalPlanningProjectionError("planning projection must be an object")
    metadata = payload.get("map_metadata")
    if not isinstance(metadata, dict):
        raise OperationalPlanningProjectionError("planning projection metadata must be an object")
    if "earth3_p3_operational_authority" not in metadata:
        raise OperationalPlanningProjectionError("restricted P3 planning authority missing")
    for forbidden in (
        "strategic_actor_runtime",
        "actor_content_runtime",
        SITE_CONTROL_KEY,
    ):
        if forbidden in metadata:
            raise OperationalPlanningProjectionError(
                f"restricted P3 planning projection leaked {forbidden}"
            )
    if payload.get("pending_battle") is not None:
        raise OperationalPlanningProjectionError(
            "restricted P3 planning projection cannot contain pending-battle details"
        )

    raw_forces = payload.get("strategic_formations")
    if not isinstance(raw_forces, dict):
        raise OperationalPlanningProjectionError(
            "restricted P3 strategic_formations must be an object"
        )
    visible = tuple(sorted(str(value) for value in visible_subject_keys))
    if tuple(sorted(str(key) for key in raw_forces)) != visible:
        raise OperationalPlanningProjectionError(
            "restricted P3 planning subjects do not match the declared visible set"
        )

    raw_factions = payload.get("factions")
    if not isinstance(raw_factions, dict):
        raise OperationalPlanningProjectionError("planning factions must be an object")
    factions: dict[str, FactionState] = {}
    for key, row in raw_factions.items():
        if not isinstance(row, dict):
            raise OperationalPlanningProjectionError(f"planning faction {key} must be an object")
        faction = Faction(str(row.get("faction", key)))
        if faction.value != str(key):
            raise OperationalPlanningProjectionError(f"planning faction key mismatch: {key}")
        factions[str(key)] = FactionState(
            faction=faction,
            resources=0,
            is_human_controlled=_strict_bool(
                row.get("is_human_controlled", False),
                name=f"faction[{key}].is_human_controlled",
            ),
            is_eliminated=_strict_bool(
                row.get("is_eliminated", False),
                name=f"faction[{key}].is_eliminated",
            ),
        )

    raw_alliances = payload.get("alliances", {})
    if not isinstance(raw_alliances, dict):
        raise OperationalPlanningProjectionError("planning alliances must be an object")
    alliances: dict[str, Alliance] = {}
    for key, row in raw_alliances.items():
        if not isinstance(row, dict):
            raise OperationalPlanningProjectionError(f"planning alliance {key} must be an object")
        alliance = Alliance(
            alliance_id=str(row.get("alliance_id", "")),
            display_name=str(row.get("display_name", "")),
            factions=[Faction(str(value)) for value in row.get("factions", [])],
            notes=str(row.get("notes", "")),
        )
        if alliance.alliance_id != str(key):
            raise OperationalPlanningProjectionError(f"planning alliance key mismatch: {key}")
        alliance.validate()
        alliances[str(key)] = alliance

    raw_provinces = payload.get("provinces")
    if not isinstance(raw_provinces, dict) or not raw_provinces:
        raise OperationalPlanningProjectionError("planning provinces must be a non-empty object")
    provinces: dict[str, Province] = {}
    for key, row in raw_provinces.items():
        if not isinstance(row, dict):
            raise OperationalPlanningProjectionError(f"planning province {key} must be an object")
        province = Province(
            province_id=str(row.get("province_id", "")),
            display_name=str(row.get("display_name", "")),
            owner=Faction(str(row.get("owner", Faction.NEUTRAL.value))),
            neighbors=[str(value) for value in row.get("neighbors", [])],
            terrain=str(row.get("terrain", "temperate")),
            map_region=str(row.get("map_region", "ostfront")),
            x=float(row.get("x", 0)),
            y=float(row.get("y", 0)),
            resource_yield=int(row.get("resource_yield", 0)),
            fortification=int(row.get("fortification", 0)),
            metadata=copy.deepcopy(row.get("metadata", {})),
        )
        if province.province_id != str(key):
            raise OperationalPlanningProjectionError(f"planning province key mismatch: {key}")
        province.validate()
        provinces[str(key)] = province

    strategic_formations: dict[str, StrategicFormation] = {}
    for key, row in raw_forces.items():
        if not isinstance(row, dict):
            raise OperationalPlanningProjectionError(
                f"planning strategic formation {key} must be an object"
            )
        force = StrategicFormation(
            strategic_formation_id=str(row.get("strategic_formation_id", "")),
            display_name=str(row.get("display_name", "")),
            faction=Faction(str(row.get("faction", ""))),
            province_id=str(row.get("province_id", "")),
            echelon=ForceEchelon(str(row.get("echelon", ForceEchelon.BATTALION.value))),
            commander_id=None,
            battalion_ids=[str(value) for value in row.get("battalion_ids", [])],
            template_formation_id=str(row.get("template_formation_id", "") or ""),
            stack_order=int(row.get("stack_order", 0)),
            movement_state=str(row.get("movement_state", "at_anchor")),
            stance=str(row.get("stance", "standard")),
            actor_id=str(row.get("actor_id", "") or ""),
            condition_summary=int(row.get("condition_summary", 100)),
            supply_summary=int(row.get("supply_summary", 100)),
            experience_summary=int(row.get("experience_summary", 0)),
            is_player_controlled=_strict_bool(
                row.get("is_player_controlled", False),
                name=f"formation[{key}].is_player_controlled",
            ),
            position=position_from_dict(row.get("position")),
            move_order=move_order_from_dict(row.get("move_order")),
            supplied=_strict_bool(row.get("supplied", True), name=f"formation[{key}].supplied"),
            cut_off=_strict_bool(row.get("cut_off", False), name=f"formation[{key}].cut_off"),
            source_hub_id=_optional_string(row.get("source_hub_id")),
            route_cost=_optional_int(row.get("route_cost"), name=f"formation[{key}].route_cost"),
            grace_ticks_remaining=_required_int(
                row.get("grace_ticks_remaining", 0),
                name=f"formation[{key}].grace_ticks_remaining",
            ),
            last_supply_refresh_tick=_optional_int(
                row.get("last_supply_refresh_tick"),
                name=f"formation[{key}].last_supply_refresh_tick",
            ),
            last_supply_refresh_turn=_optional_int(
                row.get("last_supply_refresh_turn"),
                name=f"formation[{key}].last_supply_refresh_turn",
            ),
            last_grace_consuming_tick=_optional_int(
                row.get("last_grace_consuming_tick"),
                name=f"formation[{key}].last_grace_consuming_tick",
            ),
            ambush_ready_tick=_optional_int(
                row.get("ambush_ready_tick"),
                name=f"formation[{key}].ambush_ready_tick",
            ),
            recon_capability=_strict_bool(
                row.get("recon_capability", False),
                name=f"formation[{key}].recon_capability",
            ),
        )
        if force.strategic_formation_id != str(key):
            raise OperationalPlanningProjectionError(
                f"planning strategic formation key mismatch: {key}"
            )
        if force.faction.value not in factions:
            raise OperationalPlanningProjectionError(
                f"planning formation {key} references missing faction"
            )
        if force.province_id not in provinces:
            raise OperationalPlanningProjectionError(
                f"planning formation {key} references missing province"
            )
        force.validate()
        strategic_formations[str(key)] = force

    current_faction = Faction(str(payload.get("current_faction", Faction.NATO.value)))
    selected_faction = Faction(str(payload.get("selected_faction", current_faction.value)))
    state = CampaignState(
        campaign_name=str(payload.get("campaign_name", "restricted-operational-planning")),
        turn_number=int(payload.get("turn_number", 1)),
        current_faction=current_faction,
        selected_faction=selected_faction,
        map_id=str(payload.get("map_id", "")),
        map_metadata=copy.deepcopy(metadata),
        factions=factions,
        alliances=alliances,
        strategic_formations=strategic_formations,
        provinces=provinces,
        pending_battle=None,
        fog_of_war_enabled=False,
        knowledge_by_observer={},
        schema_version=int(payload.get("schema_version", 1)),
    )

    graph = load_operational_graph_for_state(state)
    if graph is None:
        raise OperationalPlanningProjectionError(
            "restricted P3 planning projection has no authenticated graph"
        )
    _install_visible_site_control(state)
    node_ids, edge_ids, edges_by_id, nodes_by_id = _graph_indexes(graph)
    for force_id, force in sorted(state.strategic_formations.items()):
        position = force.position
        if position is None and force.movement_state == "observed_contact":
            continue
        if not _position_is_valid(
            position,
            province_id=force.province_id,
            node_ids=node_ids,
            edge_ids=edge_ids,
            edges_by_id=edges_by_id,
            nodes_by_id=nodes_by_id,
        ):
            raise OperationalPlanningProjectionError(
                f"restricted planning formation {force_id} position is invalid"
            )
    return state


def _install_visible_site_control(state: CampaignState) -> None:
    """Derive planner-only site controllers from visible province ownership.

    The serialized S11 projection intentionally excludes mutable site-control
    claimant/progress rows. Authored graph ownership is starting provenance, not
    current mutable control. Seed a minimal prior row for every legal control site
    using the current province owner, then let the normal validator fill only
    zero-progress structural fields. This keeps current controller visibility while
    preventing hidden capture progress from crossing the observation boundary.
    """
    if SITE_CONTROL_KEY in state.map_metadata:
        raise OperationalPlanningProjectionError(
            "restricted P3 planning projection must not contain mutable site-control state"
        )

    visible_control: dict[str, dict[str, Any]] = {}
    for site in list_control_sites(state):
        site_id = str(site.get("site_id") or "")
        province_id = str(site.get("province_id") or "")
        if not site_id or not province_id:
            continue
        province = state.provinces.get(province_id)
        controller = None
        if province is not None and province.owner != Faction.NEUTRAL:
            controller = province.owner.value
        visible_control[site_id] = {"controller_faction": controller}

    set_site_control_state(state, visible_control)
    ensure_site_control_state(state)

    normalized = state.map_metadata.get(SITE_CONTROL_KEY)
    if not isinstance(normalized, dict):
        raise OperationalPlanningProjectionError(
            "restricted P3 planner could not initialize visible site control"
        )
    for site_id, row in normalized.items():
        if not isinstance(row, dict):
            raise OperationalPlanningProjectionError(
                f"restricted P3 planner site-control row is malformed: {site_id}"
            )
        if (
            row.get("claimant_faction") is not None
            or row.get("claimant_formation_id") is not None
            or row.get("progress_ticks") != 0
        ):
            raise OperationalPlanningProjectionError(
                f"restricted P3 planner leaked capture progress: {site_id}"
            )


def _strict_bool(value: Any, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise OperationalPlanningProjectionError(f"{name} must be bool")
    return value


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise OperationalPlanningProjectionError("optional planning id must be string")
    return value


def _optional_int(value: Any, *, name: str) -> int | None:
    if value is None:
        return None
    return _required_int(value, name=name)


def _required_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OperationalPlanningProjectionError(f"{name} must be a non-negative int")
    return value
