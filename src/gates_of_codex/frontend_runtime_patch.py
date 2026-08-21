from __future__ import annotations

"""Bounded frontend runtime publication for the #207 responsiveness lane.

The initial player launch still receives the complete frontend snapshot. After an
``end_player_round`` command, this module publishes only state that can change at
runtime. Static Earth3 province geometry, edges, research definitions, and other
large presentation payloads remain in Godot's already-validated snapshot.

This is presentation-only. The authoritative campaign is still saved first by the
normal command pipeline. The patch is derived from that same in-memory state and
contains no alternate gameplay authority.
"""

import copy
import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .models import CampaignState, Faction


RUNTIME_PATCH_SCHEMA = "gates-of-codex.frontend-runtime-patch"
RUNTIME_PATCH_SCHEMA_VERSION = 1


def _site_control_rows(state: CampaignState) -> list[dict[str, Any]]:
    """Return full display rows from persisted control state without advancing it."""

    from .operational_position import load_operational_graph_for_state

    raw = state.map_metadata.get("operational_site_control", {})
    if not isinstance(raw, dict):
        return []
    graph = load_operational_graph_for_state(state) or {}
    sites_by_id = {
        str(site.get("site_id")): site
        for site in graph.get("sites", [])
        if isinstance(site, dict) and str(site.get("site_id") or "")
    }
    nodes_by_id = {
        str(node.get("node_id")): node
        for node in graph.get("nodes", [])
        if isinstance(node, dict) and str(node.get("node_id") or "")
    }
    rows: list[dict[str, Any]] = []
    for site_id, value in sorted(raw.items()):
        if not isinstance(value, dict):
            continue
        identity = str(site_id)
        authored = sites_by_id.get(identity, {})
        province_id = str(value.get("province_id") or authored.get("province_id") or "")
        route_node_id = str(value.get("route_node_id") or authored.get("route_node_id") or "")
        node = nodes_by_id.get(route_node_id, {})
        pixel = authored.get("pixel") if isinstance(authored.get("pixel"), list) else node.get("pixel")
        row: dict[str, Any] = {
            "site_id": identity,
            "display_name": str(
                authored.get("display_name")
                or (f"{province_id} control" if province_id else identity)
            ),
            "province_id": province_id,
            "route_node_id": route_node_id,
            "pixel": list(pixel) if isinstance(pixel, list) else [0, 0],
        }
        for key in (
            "controller_faction",
            "claimant_faction",
            "claimant_formation_id",
            "progress_ticks",
            "required_ticks",
            "control_weight_milli",
            "authored_site_id",
            "site_kind",
            "authored_site",
            "synthetic_anchor_control_site",
        ):
            if key in value:
                row[key] = copy.deepcopy(value[key])
        rows.append(row)
    return rows


def _application_patch(state: CampaignState) -> dict[str, Any]:
    return {
        "turn_number": int(state.turn_number),
        "selected_faction": state.selected_faction.value,
        "difficulty": state.difficulty,
        "fog_of_war_enabled": bool(state.fog_of_war_enabled),
    }


def _campaign_rules_patch(state: CampaignState) -> dict[str, Any]:
    from .campaign_rules import campaign_presentation

    return campaign_presentation(state)


def _campaign_patch(state: CampaignState) -> dict[str, Any]:
    from .operational_movement import get_operational_clock

    return {
        "turn_number": int(state.turn_number),
        "current_faction": state.current_faction.value,
        "selected_faction": state.selected_faction.value,
        "difficulty": state.difficulty,
        "outcome": copy.deepcopy(
            state.map_metadata.get("campaign_outcome", {"status": "active"})
        ),
        "operational_clock": get_operational_clock(state),
        "site_control": _site_control_rows(state),
        **_campaign_rules_patch(state),
    }


def _dynamic_factions(state: CampaignState) -> list[dict[str, Any]]:
    from .economy import available_research
    from .frontend import _faction_supply_payload
    from .supply import supply_status_for_faction

    rows: list[dict[str, Any]] = []
    for faction_id, faction in sorted(state.factions.items()):
        report = supply_status_for_faction(state, Faction(faction_id))
        rows.append(
            {
                "id": faction_id,
                "resources": faction.resources,
                "researched_keys": list(faction.researched_keys),
                "available_research": [
                    node.key for node in available_research(state, Faction(faction_id))
                ]
                if state.research_nodes
                else [],
                "reinforcement_pool": [asdict(entry) for entry in faction.reinforcement_pool],
                "income_last_round": faction.income_last_round,
                "maintenance_last_round": faction.maintenance_last_round,
                "is_human_controlled": faction.is_human_controlled,
                "is_eliminated": faction.is_eliminated,
                **_faction_supply_payload(report),
            }
        )
    return rows


def _runtime_construction_options(
    state: CampaignState,
    province,
    faction: Faction,
    *,
    reachable: set[str],
    p2_campaign: bool,
    p2_footprint: set[str],
) -> list[dict[str, Any]]:
    """Read-only equivalent of strategic.construction_options for hot publication.

    The normal helper calls ensure_strategic_layer(), which scans every province.
    Doing that once per operational province would recreate the exact 3.5k-map
    work this patch is intended to avoid. The authoritative save immediately
    before this projection has already normalized infrastructure and actor data.
    """

    from .earth3_bootstrap import earth3_p2_actor_resources
    from .strategic import BUILDING_RULES

    raw_levels = province.metadata.get("infrastructure", {})
    if not isinstance(raw_levels, dict):
        raw_levels = {}
    levels = {
        building: max(0, min(int(raw_levels.get(building, 0)), rules["max_level"]))
        for building, rules in BUILDING_RULES.items()
    }
    outside_p2_footprint = p2_campaign and province.province_id not in p2_footprint
    actor_scope = (
        earth3_p2_actor_resources(state, province.province_id, faction)
        if p2_campaign
        and not outside_p2_footprint
        and province.owner == faction
        else None
    )
    available_resources = (
        int(actor_scope[0]["resources"])
        if actor_scope is not None
        else (0 if p2_campaign else state.factions[faction.value].resources)
    )
    options: list[dict[str, Any]] = []
    for building, rules in BUILDING_RULES.items():
        level = levels[building]
        cost = rules["base_cost"] * (level + 1)
        reasons: list[str] = []
        if outside_p2_footprint:
            reasons.append("outside_scenario_footprint")
        if p2_campaign and building == "supply_hub":
            reasons.append("operational_supply_unavailable_until_p3")
        if province.owner != faction:
            reasons.append("province_not_owned")
        if province.province_id not in reachable:
            reasons.append("province_not_supplied")
        if level >= rules["max_level"]:
            reasons.append("maximum_level")
        if available_resources < cost:
            reasons.append("insufficient_resources")
        options.append(
            {
                "building": building,
                "next_level": min(level + 1, rules["max_level"]),
                "cost": cost,
                "available": not reasons,
            }
        )
    return options


def _dynamic_provinces(
    state: CampaignState,
    *,
    occupied: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Project only mutable province fields across the static Earth3 map."""

    from .earth3_bootstrap import earth3_p2_footprint, is_earth3_p2_campaign
    from .operational_position import load_operational_graph_for_state
    from .supply import reachable_supply_provinces

    graph = load_operational_graph_for_state(state)
    operational_provinces = {
        str(node.get("province_id") or "")
        for node in (graph or {}).get("nodes", [])
        if isinstance(node, dict) and str(node.get("province_id") or "")
    }
    selected = state.selected_faction
    reachable = reachable_supply_provinces(state, selected)
    p2_campaign = is_earth3_p2_campaign(state)
    p2_footprint = set(earth3_p2_footprint(state)) if p2_campaign else set()
    rows: list[dict[str, Any]] = []
    for province in sorted(state.provinces.values(), key=lambda value: value.province_id):
        metadata = province.metadata if isinstance(province.metadata, dict) else {}
        row: dict[str, Any] = {
            "id": province.province_id,
            "owner": province.owner.value,
            "occupied_by": occupied.get(province.province_id, [""])[0],
            "occupied_by_battalions": list(occupied.get(province.province_id, [])),
            "supply_source_for": sorted(
                set(metadata.get("supply_source_for", []))
                | set(metadata.get("static_supply_source_for", []))
            ),
        }
        if province.province_id in operational_provinces:
            row["infrastructure"] = copy.deepcopy(metadata.get("infrastructure", {}))
            row["fortification"] = int(province.fortification)
            row["resource_yield"] = int(province.resource_yield)
            row["construction_options"] = _runtime_construction_options(
                state,
                province,
                selected,
                reachable=reachable,
                p2_campaign=p2_campaign,
                p2_footprint=p2_footprint,
            )
            from .site_upgrade import project_site_upgrade

            row["site_upgrade"] = project_site_upgrade(
                state,
                province,
                selected,
                reachable=reachable,
            )
        rows.append(row)
    return rows


def _dynamic_formations(state: CampaignState) -> list[dict[str, Any]]:
    """Patch only player-relevant recruitment offers on static TOE rows."""

    from .economy import formation_recruitment_offers

    rows: list[dict[str, Any]] = []
    for formation in sorted(state.formations.values(), key=lambda value: value.formation_id):
        if formation.faction != state.selected_faction:
            continue
        rows.append(
            {
                "id": formation.formation_id,
                "recruitment_offers": [
                    asdict(offer)
                    for offer in formation_recruitment_offers(state, formation.formation_id)
                ]
                if state.unit_economy
                else [],
            }
        )
    return rows


def apply_runtime_patch_to_snapshot(
    base: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    candidate = copy.deepcopy(base)
    merge = patch.get("merge") or {}
    if not isinstance(merge, dict):
        raise ValueError("Runtime patch merge block is malformed.")
    for key in ("application", "campaign"):
        row = dict(candidate.get(key) or {}) if isinstance(candidate.get(key), dict) else {}
        incoming = merge.get(key) or {}
        if isinstance(incoming, dict):
            row.update(copy.deepcopy(incoming))
        candidate[key] = row
    for key in ("provinces", "formations"):
        candidate[key] = _merge_rows_by_id(candidate.get(key), merge.get(key))
    replace = patch.get("replace") or {}
    if not isinstance(replace, dict):
        raise ValueError("Runtime patch replace block is malformed.")
    for key, value in replace.items():
        candidate[key] = copy.deepcopy(value)
    return candidate


def persist_runtime_patched_snapshot(path: str | Path, patch: dict[str, Any]) -> Path:
    destination = Path(path)
    if not destination.is_file():
        return destination
    payload = json.loads(destination.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Existing frontend snapshot is not an object.")
    if str(payload.get("schema", "")) != "gates-of-codex.frontend":
        return destination
    from .frontend_snapshot_slim import (
        require_slimmable_frontend_schema,
        slim_unused_frontend_fields,
    )

    require_slimmable_frontend_schema(payload)
    updated = slim_unused_frontend_fields(
        apply_runtime_patch_to_snapshot(payload, patch)
    )
    body = json.dumps(updated, indent=2, ensure_ascii=False) + "\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
        delete=False,
    ) as temporary:
        temporary.write(body)
        temporary_path = Path(temporary.name)
    temporary_path.replace(destination)
    return destination


def _merge_rows_by_id(base: Any, patch: Any) -> list[dict[str, Any]]:
    rows = [copy.deepcopy(item) for item in base or [] if isinstance(item, dict)]
    index = {
        str(row.get("id", "")): idx
        for idx, row in enumerate(rows)
        if str(row.get("id", ""))
    }
    for item in patch or []:
        if not isinstance(item, dict):
            continue
        identity = str(item.get("id", ""))
        if not identity:
            continue
        if identity in index:
            merged = dict(rows[index[identity]])
            merged.update(copy.deepcopy(item))
            rows[index[identity]] = merged
        else:
            index[identity] = len(rows)
            rows.append(copy.deepcopy(item))
    return rows


def build_frontend_runtime_patch(
    state: CampaignState,
    *,
    campaign_path: str | Path | None = None,
    snapshot_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a bounded post-command patch from already-authoritative state."""

    from .frontend import (
        _apply_s11_frontend_filter,
        _battalion_display_pixel,
        _battalion_is_in_supply,
        _commander_display_name,
        _control_block,
        _pending_battle,
    )
    from .operational_movement import move_order_to_dict
    from .operational_order_options import list_operational_move_options
    from .operational_position import position_to_dict, resolve_display_pixel
    from .play_context import list_front_options
    from .presentation import build_stack_presentations
    from .supply import reachable_supply_provinces

    occupied: dict[str, list[str]] = {}
    for battalion in sorted(state.battalions.values(), key=lambda value: value.battalion_id):
        occupied.setdefault(battalion.province_id, []).append(battalion.battalion_id)

    supply_reach = {
        faction.value: reachable_supply_provinces(state, faction)
        for faction in (Faction.NATO, Faction.UKRAINE, Faction.RUSSIA, Faction.PRC)
        if faction.value in state.factions
    }

    option_faction = state.current_faction
    if state.fog_of_war_enabled:
        human_factions = [
            row.faction for row in state.factions.values() if row.is_human_controlled
        ]
        if len(human_factions) != 1:
            raise ValueError("fog_of_war_requires_single_human_faction")
        option_faction = human_factions[0]
    options_visible = (
        not state.fog_of_war_enabled or state.current_faction == option_faction
    )
    front_options = list_front_options(state, option_faction) if options_visible else []
    operational_orders = (
        list_operational_move_options(state, option_faction) if options_visible else []
    )
    stack_payload = build_stack_presentations(
        state,
        front_options,
        operational_options=operational_orders,
    )
    battalion_presentations = stack_payload["battalions"]
    strategic_formation_presentations = stack_payload.get("strategic_formations", {})

    dynamic_snapshot: dict[str, Any] = {
        "application": _application_patch(state),
        "campaign": _campaign_patch(state),
        "factions": _dynamic_factions(state),
        "objectives": copy.deepcopy(
            state.map_metadata.get("operational_objectives", [])
        ),
        "provinces": _dynamic_provinces(state, occupied=occupied),
        "formations": _dynamic_formations(state),
        "strategic_formations": [
            {
                "id": force.strategic_formation_id,
                "display_name": force.display_name,
                "faction": force.faction.value,
                "province_id": force.province_id,
                "position": position_to_dict(force.position),
                "display_pixel": resolve_display_pixel(state, force),
                "move_order": move_order_to_dict(force.move_order),
                "echelon": force.echelon.value,
                "commander_id": force.commander_id,
                "commander_display_name": _commander_display_name(state, force.commander_id),
                "battalion_ids": list(force.battalion_ids),
                "template_formation_id": force.template_formation_id,
                "stack_order": force.stack_order,
                "movement_state": force.movement_state,
                "stance": force.stance,
                "actor_id": force.actor_id,
                "condition_summary": force.condition_summary,
                "supply_summary": force.supply_summary,
                "experience_summary": force.experience_summary,
                "is_player_controlled": force.is_player_controlled,
                "supplied": force.supplied,
                "cut_off": force.cut_off,
                "source_hub_id": force.source_hub_id,
            }
            for force in sorted(
                state.strategic_formations.values(),
                key=lambda value: value.strategic_formation_id,
            )
        ],
        "battalions": [
            {
                "id": battalion.battalion_id,
                "formation_id": battalion.formation_id,
                "strategic_formation_id": battalion.strategic_formation_id,
                "commander_id": battalion.commander_id,
                "commander_display_name": _commander_display_name(
                    state, battalion.commander_id
                ),
                "faction": battalion.faction.value,
                "province_id": battalion.province_id,
                "display_pixel": _battalion_display_pixel(state, battalion),
                "battalion_type": battalion.battalion_type.value,
                "unit_count": battalion.unit_count,
                "authorized_unit_count": battalion.authorized_unit_count,
                "replacement_deficit": battalion.replacement_deficit,
                "condition": battalion.condition,
                "repair_points_needed": 100 - battalion.condition,
                "supply": battalion.supply,
                "is_in_supply": _battalion_is_in_supply(
                    state, battalion, supply_reach
                ),
                "encircled_turns": battalion.encircled_turns,
                "experience": battalion.experience,
                "movement_remaining": battalion.movement_remaining,
                "combat_actions_remaining": battalion.combat_actions_remaining,
                "is_player_controlled": battalion.is_player_controlled,
                "presentation": battalion_presentations.get(
                    battalion.battalion_id, {}
                ),
            }
            for battalion in sorted(
                state.battalions.values(), key=lambda value: value.battalion_id
            )
        ],
        "battalion_stacks": {
            province_id: list(battalion_ids)
            for province_id, battalion_ids in sorted(occupied.items())
        },
        "stack_presentations": stack_payload["stacks"],
        "battalion_presentations": battalion_presentations,
        "strategic_formation_presentations": strategic_formation_presentations,
        "pending_battle": _pending_battle(state),
        "front_options": front_options,
        "operational_orders": operational_orders,
        "control": _control_block(
            state,
            campaign_path,
            snapshot_path,
            environ=environ,
        ),
    }

    from .frontend_snapshot_slim import slim_unused_frontend_fields

    filtered = slim_unused_frontend_fields(
        _apply_s11_frontend_filter(dynamic_snapshot, state)
    )

    # Static map metadata must remain whatever the initial full snapshot already
    # authenticated. The S11 filter may synthesize sanitized metadata dictionaries
    # while processing the partial rows, so never merge those into the static base.
    campaign_patch = dict(filtered.get("campaign", {}))
    campaign_patch.pop("map_metadata", None)
    province_patch = []
    for value in filtered.get("provinces", []):
        if not isinstance(value, dict):
            continue
        row = dict(value)
        row.pop("metadata", None)
        province_patch.append(row)

    payload = {
        "schema": RUNTIME_PATCH_SCHEMA,
        "schema_version": RUNTIME_PATCH_SCHEMA_VERSION,
        "merge": {
            "application": dict(filtered.get("application", {})),
            "campaign": campaign_patch,
            "provinces": province_patch,
            "formations": list(filtered.get("formations", [])),
        },
        "replace": {
            "factions": list(filtered.get("factions", [])),
            "objectives": copy.deepcopy(filtered.get("objectives", [])),
            "strategic_formations": list(
                filtered.get("strategic_formations", [])
            ),
            "battalions": list(filtered.get("battalions", [])),
            "battalion_stacks": copy.deepcopy(
                filtered.get("battalion_stacks", {})
            ),
            "stack_presentations": copy.deepcopy(
                filtered.get("stack_presentations", {})
            ),
            "battalion_presentations": copy.deepcopy(
                filtered.get("battalion_presentations", {})
            ),
            "strategic_formation_presentations": copy.deepcopy(
                filtered.get("strategic_formation_presentations", {})
            ),
            "pending_battle": copy.deepcopy(filtered.get("pending_battle")),
            "front_options": list(filtered.get("front_options", [])),
            "operational_orders": list(filtered.get("operational_orders", [])),
            "control": copy.deepcopy(filtered.get("control", {})),
            "fog_of_war": copy.deepcopy(filtered.get("fog_of_war", {})),
            "last_known_contacts": list(
                filtered.get("last_known_contacts", [])
            ),
        },
    }
    from .frontend_actor_force import build_acting_actor_presentation

    acting_actor = build_acting_actor_presentation(state)
    if acting_actor is not None:
        payload["replace"]["acting_actor"] = acting_actor
    return payload
