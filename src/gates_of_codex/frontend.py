from __future__ import annotations

import copy
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from .earth3_campaign import (
    CAMPAIGN_DATASET_IDENTIFIER,
    CAMPAIGN_MANIFEST_IDENTIFIER,
    EARTH3_MANIFEST_PATH,
    EARTH3_MAP_ID,
    EARTH3_SCENARIO_ID,
    PRODUCTION_AUTHORITY_IDENTIFIER,
    Earth3AuthorityError,
    load_earth3_authority,
)
from .economy import available_research, formation_recruitment_offers
from .map_layout import apply_marker_layout, is_human_readable_name, province_name_coverage
from .models import CampaignState, Faction
from .play_context import list_front_options
from .strategic import (
    construction_options,
    ensure_strategic_layer,
    evaluate_campaign_outcome,
    infrastructure_levels,
    update_operational_objectives,
)
from .supply import (
    formation_supplied_for_battalion,
    reachable_supply_provinces,
    supply_status_for_faction,
)


FRONTEND_SCHEMA_VERSION = 15
FRONTEND_PYTHON_MODULE = "gates_of_codex"
LEGACY_GOE_MAP_ID = "goe_europe_alpha_graph_v1"
_LEGACY_GOE_COMPATIBILITY_ALIASES = ("goe_europe", "interim_goe_europe")
_MAP_MANIFEST_BY_ID = {
    EARTH3_MAP_ID: "assets/maps/earth3_europe_mediterranean/map_manifest.json",
    "europe_mediterranean_from_goe": "assets/maps/europe_mediterranean/from_goe/map_manifest.json",
    LEGACY_GOE_MAP_ID: "assets/maps/europe/interim_goe/map_manifest.json",
    "goe_europe": "assets/maps/europe/interim_goe/map_manifest.json",
    "interim_goe_europe": "assets/maps/europe/interim_goe/map_manifest.json",
}
_LEGACY_MAP_IDS = (
    LEGACY_GOE_MAP_ID,
    *_LEGACY_GOE_COMPATIBILITY_ALIASES,
    "europe_mediterranean_from_goe",
)


def _declares_earth3_authority(state: CampaignState) -> bool:
    metadata = state.map_metadata
    return any(
        (
            state.map_id == EARTH3_MAP_ID,
            metadata.get("strategic_map_id") == EARTH3_MAP_ID,
            metadata.get("scenario_id") == EARTH3_SCENARIO_ID,
            metadata.get("manifest_identifier") == CAMPAIGN_MANIFEST_IDENTIFIER,
            metadata.get("dataset_identifier") == CAMPAIGN_DATASET_IDENTIFIER,
            metadata.get("production_authority_identifier")
            == PRODUCTION_AUTHORITY_IDENTIFIER,
        )
    )


def _faction_supply_payload(report) -> dict:
    operational = report.authority == "operational_graph"
    return {
        "supply_authority": report.authority,
        "supply_reachable_provinces": (
            None if operational else report.reachable_provinces
        ),
        "legacy_admin_supply_reachable_provinces": (
            report.legacy_admin_reachable_provinces
        ),
        "operational_supply_source_ids": (
            list(report.sources) if operational else []
        ),
        "operational_connected_formations": len(
            report.connected_formations
        ),
        "operational_disconnected_formations": len(
            report.disconnected_formations
        ),
        "operational_grace_formations": len(report.grace_formations),
        "operational_cut_off_formations": len(report.cut_off_formations),
    }


def build_frontend_snapshot(
    state: CampaignState,
    *,
    campaign_path: str | Path | None = None,
    snapshot_path: str | Path | None = None,
) -> dict:
    # Frontend export is a pure projection. Existing helper functions may normalize
    # derived state, so operate only on a detached copy.
    state = copy.deepcopy(state)
    ensure_strategic_layer(state)
    from .force_migration import ensure_strategic_formations
    from .operational_movement import (
        ensure_move_orders,
        get_operational_clock,
        move_order_to_dict,
    )
    from .operational_position import (
        ensure_operational_positions,
        position_to_dict,
        resolve_display_pixel,
    )

    from .operational_capture import site_control_snapshot
    from .operational_supply import refresh_operational_supply

    ensure_strategic_formations(state)
    ensure_operational_positions(state)
    ensure_move_orders(state)
    operational_clock = get_operational_clock(state)
    site_control = site_control_snapshot(state)
    refresh_operational_supply(state, consume_grace=False)
    if not _declares_earth3_authority(state):
        apply_marker_layout(state)
    objectives = update_operational_objectives(state)
    outcome = evaluate_campaign_outcome(state)
    state.validate()

    occupied: dict[str, list[str]] = {}
    for battalion in sorted(state.battalions.values(), key=lambda value: value.battalion_id):
        occupied.setdefault(battalion.province_id, []).append(battalion.battalion_id)

    xs = [province.x for province in state.provinces.values()]
    ys = [province.y for province in state.provinces.values()]
    edges = sorted(
        {
            tuple(sorted((province.province_id, neighbor_id)))
            for province in state.provinces.values()
            for neighbor_id in province.neighbors
            if province.province_id != neighbor_id
        }
    )
    supply_reach = {
        faction.value: reachable_supply_provinces(state, faction)
        for faction in (Faction.NATO, Faction.UKRAINE, Faction.RUSSIA, Faction.PRC)
        if faction.value in state.factions
    }
    supply_status = {
        faction_id: supply_status_for_faction(state, Faction(faction_id))
        for faction_id in sorted(state.factions)
    }
    option_faction = state.current_faction
    if state.fog_of_war_enabled:
        human_factions = [
            row.faction for row in state.factions.values()
            if row.is_human_controlled
        ]
        if len(human_factions) != 1:
            raise ValueError("fog_of_war_requires_single_human_faction")
        option_faction = human_factions[0]
    front_options = (
        list_front_options(state, option_faction)
        if not state.fog_of_war_enabled or state.current_faction == option_faction
        else []
    )
    from .presentation import build_stack_presentations

    stack_payload = build_stack_presentations(state, front_options)
    battalion_presentations = stack_payload["battalions"]
    strategic_formation_presentations = stack_payload.get("strategic_formations", {})

    snapshot = {
        "schema": "gates-of-codex.frontend",
        "schema_version": FRONTEND_SCHEMA_VERSION,
        "application": _application_block(state, campaign_path),
        "campaign": {
            "name": state.campaign_name,
            "turn_number": state.turn_number,
            "current_faction": state.current_faction.value,
            "selected_faction": state.selected_faction.value,
            "difficulty": state.difficulty,
            "map_id": state.map_id,
            "map_metadata": state.map_metadata,
            "catalog_signature": state.catalog_signature,
            "outcome": asdict(outcome),
            "operational_clock": operational_clock,
            "site_control": site_control,
        },
        "strategic_map": _strategic_map_block(state, snapshot_path),
        "bounds": {
            "min_x": min(xs),
            "max_x": max(xs),
            "min_y": min(ys),
            "max_y": max(ys),
        },
        "factions": [
            {
                "id": faction_id,
                "resources": faction.resources,
                "researched_keys": list(faction.researched_keys),
                "available_research": [
                    node.key for node in available_research(state, Faction(faction_id))
                ] if state.research_nodes else [],
                "reinforcement_pool": [asdict(entry) for entry in faction.reinforcement_pool],
                "income_last_round": faction.income_last_round,
                "maintenance_last_round": faction.maintenance_last_round,
                "is_human_controlled": faction.is_human_controlled,
                "is_eliminated": faction.is_eliminated,
                **_faction_supply_payload(supply_status[faction_id]),
            }
            for faction_id, faction in sorted(state.factions.items())
        ],
        "alliances": [
            {
                "id": alliance.alliance_id,
                "display_name": alliance.display_name,
                "factions": [faction.value for faction in alliance.factions],
                "notes": alliance.notes,
            }
            for alliance in sorted(state.alliances.values(), key=lambda value: value.alliance_id)
        ],
        "objectives": objectives,
        "provinces": [
            {
                "id": province.province_id,
                "display_name": province.display_name,
                "name_is_human_readable": is_human_readable_name(province.display_name),
                "name_source": str(province.metadata.get("name_source", "")),
                "owner": province.owner.value,
                "x": province.x,
                "y": province.y,
                "id_color": dict(province.metadata.get("id_color", {})),
                "terrain": province.terrain,
                "map_region": province.map_region,
                "resource_yield": province.resource_yield,
                "fortification": province.fortification,
                "infrastructure": infrastructure_levels(province),
                "construction_options": construction_options(
                    state, state.selected_faction, province.province_id
                ),
                "occupied_by": occupied.get(province.province_id, [""])[0],
                "occupied_by_battalions": list(occupied.get(province.province_id, [])),
                "supply_source_for": sorted(
                    set(province.metadata.get("supply_source_for", []))
                    | set(province.metadata.get("static_supply_source_for", []))
                ),
                "metadata": province.metadata,
            }
            for province in sorted(state.provinces.values(), key=lambda value: value.province_id)
        ],
        "edges": [[left, right] for left, right in edges],
        "research": [
            {
                "key": node.key,
                "faction": node.faction.value,
                "display_name": node.display_name,
                "cost": node.cost,
                "prerequisites": list(node.prerequisites),
                "unlock_categories": list(node.unlock_categories),
                "unlock_doctrines": list(node.unlock_doctrines),
                "unlock_units": list(node.unlock_units),
                "source": node.source,
            }
            for node in sorted(state.research_nodes.values(), key=lambda value: value.key)
        ],
        "formations": [
            {
                "id": formation.formation_id,
                "display_name": formation.display_name,
                "faction": formation.faction.value,
                "nation": formation.nation,
                "kind": formation.kind.value,
                "deployment_zone": formation.deployment_zone,
                "doctrine_tags": list(formation.doctrine_tags),
                "preferred_categories": list(formation.preferred_categories),
                "is_foreign_contingent": formation.is_foreign_contingent,
                "notes": formation.notes,
                "recruitment_offers": [
                    asdict(offer) for offer in formation_recruitment_offers(state, formation.formation_id)
                ] if state.unit_economy else [],
            }
            for formation in sorted(state.formations.values(), key=lambda value: value.formation_id)
        ],
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
                state.strategic_formations.values(), key=lambda value: value.strategic_formation_id
            )
        ],
        "commanders": [
            {
                "id": commander.commander_id,
                "display_name": commander.display_name,
                "rank": commander.rank,
                "portrait_key": commander.portrait_key,
                "assigned_strategic_formation_id": commander.assigned_strategic_formation_id,
                "assigned_battalion_id": commander.assigned_battalion_id,
                "status": commander.status.value,
                "experience": commander.experience,
                "source": commander.source,
                "provenance": commander.provenance,
            }
            for commander in sorted(state.commanders.values(), key=lambda value: value.commander_id)
        ],
        "battalions": [
            {
                "id": battalion.battalion_id,
                "formation_id": battalion.formation_id,
                "strategic_formation_id": battalion.strategic_formation_id,
                "commander_id": battalion.commander_id,
                "commander_display_name": _commander_display_name(state, battalion.commander_id),
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
                "roster": [asdict(entry) for entry in battalion.roster],
                "authorized_roster": [asdict(entry) for entry in battalion.authorized_roster],
                "presentation": battalion_presentations.get(battalion.battalion_id, {}),
            }
            for battalion in sorted(state.battalions.values(), key=lambda value: value.battalion_id)
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
        "control": _control_block(state, campaign_path, snapshot_path),
        "province_names": dict(
            state.map_metadata.get("province_names") or province_name_coverage(state)
        ),
    }
    return _apply_s11_frontend_filter(snapshot, state)


def _apply_s11_frontend_filter(snapshot: dict, state: CampaignState) -> dict:
    if not state.fog_of_war_enabled:
        snapshot["fog_of_war"] = {
            "enabled": False,
            "observer_faction": None,
            "observer_scope_id": None,
        }
        snapshot["last_known_contacts"] = []
        return snapshot

    from .observation import (
        current_and_last_known_records,
        knowledge_record_to_dict,
        observer_factions,
        observer_scope_id,
    )
    from .models import InformationTier

    humans = [row.faction for row in state.factions.values() if row.is_human_controlled]
    if len(humans) != 1:
        raise ValueError("fog_of_war_requires_single_human_faction")
    observer = humans[0]
    coalition = observer_factions(state, observer)
    scope = observer_scope_id(state, observer)
    current, stale = current_and_last_known_records(state, observer)
    full_force_rows = {row["id"]: row for row in snapshot.get("strategic_formations", [])}
    filtered_forces: list[dict] = []
    fully_observed_subjects: set[str] = set()
    for force in sorted(state.strategic_formations.values(), key=lambda row: row.strategic_formation_id):
        full = full_force_rows.get(force.strategic_formation_id, {})
        if force.faction in coalition:
            friendly = dict(full)
            friendly["information_tier"] = "friendly"
            filtered_forces.append(friendly)
            fully_observed_subjects.add(force.strategic_formation_id)
            continue
        record = current.get(force.strategic_formation_id)
        if record is None:
            continue
        if record.tier == InformationTier.FULLY_OBSERVED:
            row = dict(full)
            row.pop("move_order", None)
            row.pop("stance", None)
            row["information_tier"] = record.tier.value
            row["source_ids"] = list(record.source_ids)
            filtered_forces.append(row)
            fully_observed_subjects.add(force.strategic_formation_id)
            continue
        row = _frontend_contact_row(state, record)
        filtered_forces.append(row)
    snapshot["strategic_formations"] = filtered_forces

    allowed_battalions: set[str] = set()
    for force_id in fully_observed_subjects:
        force = state.strategic_formations.get(force_id)
        if force is not None:
            allowed_battalions.update(force.battalion_ids)
    snapshot["battalions"] = [
        row for row in snapshot.get("battalions", []) if row.get("id") in allowed_battalions
    ]
    allowed_commanders = {
        row.get("commander_id")
        for row in snapshot["strategic_formations"]
        if row.get("commander_id")
    } | {
        row.get("commander_id")
        for row in snapshot["battalions"]
        if row.get("commander_id")
    }
    snapshot["commanders"] = [
        row for row in snapshot.get("commanders", []) if row.get("id") in allowed_commanders
    ]
    snapshot["battalion_stacks"] = {
        province_id: [item for item in items if item in allowed_battalions]
        for province_id, items in snapshot.get("battalion_stacks", {}).items()
        if any(item in allowed_battalions for item in items)
    }
    observer_has_turn = state.current_faction == observer
    actionable_battalions = {
        battalion.battalion_id
        for battalion in state.battalions.values()
        if observer_has_turn and battalion.faction == observer
    }
    snapshot["battalion_presentations"] = {
        key: _sanitize_battalion_presentation(
            value,
            allowed_battalions,
            actionable=key in actionable_battalions,
        )
        for key, value in snapshot.get("battalion_presentations", {}).items()
        if key in allowed_battalions
    }
    for row in snapshot["battalions"]:
        row["presentation"] = snapshot["battalion_presentations"].get(
            row.get("id"), {}
        )
    snapshot["strategic_formation_presentations"] = {
        key: _sanitize_strategic_formation_presentation(
            value,
            friendly=(
                state.strategic_formations.get(key) is not None
                and state.strategic_formations[key].faction in coalition
            ),
            actionable=(
                observer_has_turn
                and state.strategic_formations.get(key) is not None
                and state.strategic_formations[key].faction == observer
            ),
        )
        for key, value in snapshot.get(
            "strategic_formation_presentations", {}
        ).items()
        if key in fully_observed_subjects
    }
    snapshot["stack_presentations"] = {
        province_id: _sanitize_stack_presentation(
            row,
            actionable_battalions=actionable_battalions,
        )
        for province_id, row in snapshot.get("stack_presentations", {}).items()
        if isinstance(row, dict)
        and bool(row.get("battalion_ids"))
        and all(
            item in allowed_battalions
            for item in row.get("battalion_ids", [])
        )
    }

    allowed_templates = {
        force.template_formation_id
        for force in state.strategic_formations.values()
        if force.faction in coalition
        or force.strategic_formation_id in fully_observed_subjects
    }
    filtered_templates: list[dict] = []
    for row in snapshot.get("formations", []):
        template_id = row.get("id")
        if template_id not in allowed_templates:
            continue
        sanitized = dict(row)
        template = state.formations.get(str(template_id))
        if template is not None and template.faction not in coalition:
            for key in (
                "deployment_zone",
                "doctrine_tags",
                "preferred_categories",
                "notes",
                "recruitment_offers",
            ):
                sanitized.pop(key, None)
        filtered_templates.append(sanitized)
    snapshot["formations"] = filtered_templates
    snapshot["research"] = [
        row for row in snapshot.get("research", []) if Faction(row.get("faction")) in coalition
    ]
    for faction_row in snapshot.get("factions", []):
        try:
            faction = Faction(faction_row.get("id"))
        except ValueError:
            continue
        if faction not in coalition:
            keep = {
                "id": faction_row.get("id"),
                "is_human_controlled": False,
                "is_eliminated": faction_row.get("is_eliminated", False),
            }
            faction_row.clear()
            faction_row.update(keep)

    visible_battalion_ids = {row.get("id") for row in snapshot.get("battalions", [])}
    for province in snapshot.get("provinces", []):
        owner_raw = province.get("owner")
        try:
            owner = Faction(owner_raw)
        except ValueError:
            owner = Faction.NEUTRAL
        province["occupied_by_battalions"] = [
            item for item in province.get("occupied_by_battalions", [])
            if item in visible_battalion_ids
        ]
        province["occupied_by"] = (
            province["occupied_by_battalions"][0]
            if province["occupied_by_battalions"] else ""
        )
        province["supply_source_for"] = [
            item
            for item in province.get("supply_source_for", [])
            if item in {member.value for member in coalition}
        ]
        if owner not in coalition:
            province["infrastructure"] = {}
            province["construction_options"] = []
            province.pop("resource_yield", None)
            province.pop("fortification", None)
            metadata = province.get("metadata", {})
            if isinstance(metadata, dict):
                province["metadata"] = {
                    key: value
                    for key, value in metadata.items()
                    if key in {"id_color", "name_source", "layout_source"}
                }

    safe_site_control = []
    for row in snapshot.get("campaign", {}).get("site_control", []):
        sanitized = dict(row)
        raw_controller = sanitized.get("controller_faction")
        try:
            controller = Faction(raw_controller) if raw_controller else None
        except ValueError:
            controller = None
        if controller not in coalition:
            for key in (
                "controller_faction", "claimant_faction", "claimant_formation_id",
                "progress_ticks", "required_ticks", "control_weight_milli"
            ):
                sanitized.pop(key, None)
        safe_site_control.append(sanitized)
    snapshot.setdefault("campaign", {})["site_control"] = safe_site_control
    metadata = snapshot["campaign"].get("map_metadata", {})
    if isinstance(metadata, dict):
        snapshot["campaign"]["map_metadata"] = {
            key: value for key, value in metadata.items()
            if key not in {
                "operational_site_control", "strategic_actor_runtime",
                "actor_content_runtime", "operational_objectives",
                "last_round_economy", "unit_presentations",
                "operational_edge_retreat_nodes"
            }
        }

    snapshot["front_options"] = [
        row
        for row in snapshot.get("front_options", [])
        if row.get("battalion_id") in actionable_battalions
        and all(item in allowed_battalions for item in row.get("enemies", []))
    ]

    if not _observer_participates_in_pending_battle(state, coalition):
        snapshot["pending_battle"] = (
            {"operational_pause": True}
            if state.pending_battle is not None
            else None
        )

    snapshot["fog_of_war"] = {
        "enabled": True,
        "observer_faction": observer.value,
        "observer_scope_id": scope,
    }
    snapshot["last_known_contacts"] = [
        _frontend_contact_row(state, row, stale=True) for row in stale
    ]
    return snapshot


def _frontend_contact_row(state: CampaignState, record, *, stale: bool = False) -> dict:
    row = {
        "id": record.opaque_contact_id if record.tier.value == "contact" else record.subject_formation_id,
        "information_tier": record.tier.value,
        "current": False if stale else bool(record.current),
        "province_id": record.last_seen_province_id,
        "last_seen_node_id": record.last_seen_node_id,
        "last_seen_edge_id": record.last_seen_edge_id,
        "last_seen_turn": record.last_seen_turn,
        "last_seen_tick": record.last_seen_tick,
        "source_ids": list(record.source_ids),
        "display_pixel": _observation_display_pixel(state, record),
    }
    if record.tier.value != "contact":
        row.update({
            "display_name": record.display_name,
            "faction": record.faction_id,
            "actor_id": record.actor_id,
            "echelon": record.echelon,
        })
    if record.tier.value in {"assessed", "fully_observed"}:
        row.update({
            "strength_band": record.strength_band,
            "condition_band": record.condition_band,
            "supply_band": record.supply_band,
            "last_seen_direction": record.last_seen_direction,
        })
    if record.tier.value == "fully_observed" and record.last_seen_progress_milli is not None:
        row["last_seen_progress_milli"] = record.last_seen_progress_milli
    return row


def _observation_display_pixel(state: CampaignState, record) -> list[int] | None:
    from .models import InformationTier
    from .operational_position import _pixel_from_position, load_operational_graph_for_state
    from .operational_schema import FormationOperationalPosition, PositionMode

    graph = load_operational_graph_for_state(state)
    if graph is not None:
        nodes = {str(row.get("node_id")): row for row in graph.get("nodes", []) if isinstance(row, dict)}
        if record.last_seen_node_id in nodes:
            pixel = nodes[record.last_seen_node_id].get("pixel")
            if isinstance(pixel, list) and len(pixel) >= 2:
                return [int(pixel[0]), int(pixel[1])]
        if record.last_seen_edge_id:
            if (
                record.tier == InformationTier.FULLY_OBSERVED
                and record.last_seen_progress_milli is not None
            ):
                exact = _pixel_from_position(
                    FormationOperationalPosition(
                        mode=PositionMode.ON_EDGE.value,
                        edge_id=record.last_seen_edge_id,
                        progress_milli=record.last_seen_progress_milli,
                        facing_node_id=record.last_seen_direction or None,
                    ),
                    graph,
                )
                if exact is not None:
                    return exact
            edge = next((row for row in graph.get("edges", []) if isinstance(row, dict) and str(row.get("edge_id")) == record.last_seen_edge_id), None)
            if edge is not None:
                a, b = nodes.get(str(edge.get("a"))), nodes.get(str(edge.get("b")))
                if a and b and isinstance(a.get("pixel"), list) and isinstance(b.get("pixel"), list):
                    return [int(round((a["pixel"][0] + b["pixel"][0]) / 2)), int(round((a["pixel"][1] + b["pixel"][1]) / 2))]
    province = state.provinces.get(record.last_seen_province_id)
    return None if province is None else [int(round(province.x)), int(round(province.y))]



def _sanitize_strategic_formation_presentation(
    value: dict, *, friendly: bool, actionable: bool
) -> dict:
    result = copy.deepcopy(value)
    if not friendly:
        # Enemy movement orders remain hidden at every information tier.
        result.pop("move_order", None)
    if not actionable:
        result["can_act"] = False
    return result


def _sanitize_battalion_presentation(
    value: dict,
    allowed_battalions: set[str],
    *,
    actionable: bool,
) -> dict:
    result = copy.deepcopy(value)
    if not actionable:
        result["legal_options"] = []
        result["legal_option_count"] = 0
        result["can_act"] = False
        return result
    legal = [
        row
        for row in result.get("legal_options", [])
        if not row.get("enemies")
        or all(item in allowed_battalions for item in row.get("enemies", []))
    ]
    result["legal_options"] = legal
    result["legal_option_count"] = len(legal)
    result["can_act"] = bool(legal)
    return result


def _sanitize_stack_presentation(
    value: dict,
    *,
    actionable_battalions: set[str],
) -> dict:
    result = copy.deepcopy(value)
    result["can_act"] = any(
        item in actionable_battalions
        for item in result.get("battalion_ids", [])
    )
    return result


def _observer_participates_in_pending_battle(
    state: CampaignState,
    coalition: frozenset[Faction],
) -> bool:
    pending = state.pending_battle
    if pending is None:
        return False
    return any(
        participant.faction in coalition
        for participant in (
            pending.attacking_participants + pending.defending_participants
        )
    )


def write_frontend_snapshot(
    state: CampaignState,
    path: str | Path,
    *,
    campaign_path: str | Path | None = None,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            build_frontend_snapshot(
                state,
                campaign_path=campaign_path,
                snapshot_path=destination,
            ),
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
        delete=False,
    ) as temporary:
        temporary.write(payload)
        temporary_path = Path(temporary.name)
    temporary_path.replace(destination)
    return destination


def build_frontend_apply_invocation(control: dict) -> tuple[str, list[str]]:
    executable = str(control.get("python_executable", "")).strip()
    module = str(control.get("python_module", FRONTEND_PYTHON_MODULE)).strip()
    campaign_path = str(control.get("campaign_path", "")).strip()
    snapshot_path = str(control.get("snapshot_path", "")).strip()
    commands_path = str(control.get("commands_path", "")).strip()
    if not executable:
        raise ValueError("control.python_executable is required")
    if not module:
        raise ValueError("control.python_module is required")
    if not campaign_path or not snapshot_path or not commands_path:
        raise ValueError("control campaign, snapshot, and commands paths are required")
    return executable, [
        "-m",
        module,
        "apply-frontend",
        campaign_path,
        "--snapshot",
        snapshot_path,
        "--commands",
        commands_path,
    ]


def _commander_display_name(state: CampaignState, commander_id: str | None) -> str:
    """Presentation-only fallback. Does not invent serialized commander records."""

    if not commander_id:
        return "Unassigned Commander"
    commander = state.commanders.get(commander_id)
    if commander is None or not commander.display_name.strip():
        return "Unassigned Commander"
    return commander.display_name


def _battalion_display_pixel(state: CampaignState, battalion) -> list[int] | None:
    from .operational_position import resolve_display_pixel

    force = state.strategic_formations.get(battalion.strategic_formation_id)
    if force is None:
        province = state.provinces.get(battalion.province_id)
        if province is None:
            return None
        return [int(round(province.x)), int(round(province.y))]
    return resolve_display_pixel(state, force)


def _battalion_is_in_supply(
    state: CampaignState,
    battalion,
    supply_reach: dict[str, set[str]],
) -> bool:
    operational = formation_supplied_for_battalion(state, battalion)
    if operational is not None:
        return operational
    return battalion.province_id in supply_reach.get(
        battalion.faction.value, set()
    )


def _pending_battle(state: CampaignState) -> dict | None:
    pending = state.pending_battle
    if pending is None:
        return None
    return {
        "id": pending.battle_id,
        "origin_province_id": pending.origin_province_id,
        "target_province_id": pending.target_province_id,
        "attacker_faction": pending.attacker_faction.value,
        "defender_faction": pending.defender_faction.value,
        "player_faction": pending.player_faction.value,
        "player_is_attacker": pending.player_is_attacker,
        "started": pending.started,
        "completed": pending.completed,
        "attacking_battalions": [value.battalion_id for value in pending.attacking_participants],
        "defending_battalions": [value.battalion_id for value in pending.defending_participants],
        "attacking_participants": [
            _pending_battle_participant(state, value)
            for value in pending.attacking_participants
        ],
        "defending_participants": [
            _pending_battle_participant(state, value)
            for value in pending.defending_participants
        ],
        "encounter_node_id": pending.encounter_node_id,
        "encounter_kind": pending.encounter_kind,
        "attacker_formation_id": pending.attacker_formation_id,
        "defender_formation_id": pending.defender_formation_id,
        "encounter_edge_id": pending.encounter_edge_id,
        "encounter_progress_milli": pending.encounter_progress_milli,
        "encounter_pixel": list(pending.encounter_pixel or []),
    }


def _pending_battle_participant(state: CampaignState, participant) -> dict:
    battalion = state.battalions.get(participant.battalion_id)
    strategic_formation_id = (
        str(battalion.strategic_formation_id or "") if battalion is not None else ""
    )
    force = state.strategic_formations.get(strategic_formation_id)
    return {
        "battalion_id": participant.battalion_id,
        "strategic_formation_id": strategic_formation_id,
        "formation_display_name": (
            force.display_name if force is not None else strategic_formation_id
        ),
        "faction": participant.faction.value,
        "stage": participant.stage,
        "is_primary": participant.is_primary,
        "contact_initiator": participant.contact_initiator,
        "ambush_eligible": participant.ambush_eligible,
        "ambush_triggered": participant.ambush_triggered,
        "ambush_strength_multiplier_milli": participant.ambush_strength_multiplier_milli,
        "ambush_readiness_consumed": participant.ambush_readiness_consumed,
    }


def _strategic_map_block(
    state: CampaignState,
    snapshot_path: str | Path | None,
) -> dict:
    persisted_map_id = str(state.map_metadata.get("strategic_map_id", state.map_id))
    if _declares_earth3_authority(state):
        return _earth3_strategic_map_block(state)

    snapshot_directory = Path(snapshot_path).resolve().parent if snapshot_path else None
    configured = str(state.map_metadata.get("strategic_map_manifest", "")).strip()
    map_id = persisted_map_id
    candidates: list[Path] = []
    if configured:
        configured_path = Path(configured).expanduser()
        if configured_path.is_absolute():
            candidates.append(configured_path)
        else:
            if snapshot_directory is not None:
                candidates.append(snapshot_directory / configured_path)
            # Repo-root exports often use godot/assets/... while the snapshot lives in godot/.
            candidates.append(Path.cwd() / configured_path)
            candidates.append(Path.cwd() / "godot" / configured_path)
            if configured_path.parts and configured_path.parts[0] != "godot":
                candidates.append(Path.cwd() / "godot" / configured_path)
    relative = _MAP_MANIFEST_BY_ID.get(map_id)
    if relative is not None:
        if snapshot_directory is not None:
            candidates.append(snapshot_directory / relative)
        candidates.append(Path.cwd() / "godot" / relative)

    resolved: Path | None = None
    for candidate in candidates:
        try:
            path = candidate.resolve()
        except OSError:
            continue
        if path.is_file():
            resolved = path
            break
    if map_id == "europe_mediterranean_from_goe":
        default_prov = "derived_from_interim_goe_europe_theatre_crop"
        status = "legacy"
        fallback = "marker_non_authoritative"
    elif map_id == LEGACY_GOE_MAP_ID or map_id in _LEGACY_GOE_COMPATIBILITY_ALIASES:
        default_prov = "interim_goe_reference_asset"
        status = "legacy"
        fallback = "marker_non_authoritative"
    else:
        default_prov = "configured_campaign_map"
        status = "custom"
        fallback = "none"
    return {
        "enabled": bool(resolved and resolved.is_file()),
        "manifest_path": str(resolved) if resolved else "",
        "configured": bool(configured),
        "map_id": map_id,
        "status": status,
        "available_map_ids": [map_id] if resolved else [],
        "production_map_ids": [EARTH3_MAP_ID],
        "legacy_map_ids": list(_LEGACY_MAP_IDS),
        "provenance": str(state.map_metadata.get("strategic_map_provenance", default_prov)),
        "fallback": fallback,
    }


def _require_earth3_persisted_value(
    state: CampaignState,
    field: str,
    expected,
) -> None:
    actual = state.map_metadata.get(field)
    if actual != expected:
        raise Earth3AuthorityError(
            f"Earth3 campaign {field} mismatch: expected {expected!r}, got {actual!r}"
        )


def _earth3_strategic_map_block(state: CampaignState) -> dict:
    if state.map_id != EARTH3_MAP_ID:
        raise Earth3AuthorityError(
            f"Earth3 campaign state.map_id mismatch: expected {EARTH3_MAP_ID!r}, "
            f"got {state.map_id!r}"
        )
    _require_earth3_persisted_value(state, "strategic_map_id", EARTH3_MAP_ID)
    _require_earth3_persisted_value(
        state,
        "strategic_map_manifest",
        CAMPAIGN_MANIFEST_IDENTIFIER,
    )
    _require_earth3_persisted_value(
        state,
        "manifest_identifier",
        CAMPAIGN_MANIFEST_IDENTIFIER,
    )
    _require_earth3_persisted_value(
        state,
        "dataset_identifier",
        CAMPAIGN_DATASET_IDENTIFIER,
    )
    _require_earth3_persisted_value(
        state,
        "production_authority_identifier",
        PRODUCTION_AUTHORITY_IDENTIFIER,
    )

    try:
        authority = load_earth3_authority()
    except Earth3AuthorityError as exc:
        if str(exc).startswith("Earth3 manifest missing:"):
            raise FileNotFoundError(
                f"Earth3 map manifest missing: {CAMPAIGN_MANIFEST_IDENTIFIER}"
            ) from exc
        raise

    for field, expected in (
        ("manifest_sha256", authority.manifest_sha256),
        ("dataset_sha256", authority.dataset_sha256),
        ("embedded_dataset_sha256", authority.embedded_dataset_sha256),
        ("geometry_sha256", authority.geometry_sha256),
        ("production_asset_version", authority.production_asset_version),
        ("included_ids_sha256", authority.included_ids_sha256),
        ("topology_edge_count", authority.topology_edge_count),
    ):
        _require_earth3_persisted_value(state, field, expected)

    manifest_path = authority.root / EARTH3_MANIFEST_PATH
    return {
        "enabled": True,
        "manifest_path": str(manifest_path),
        "configured": True,
        "map_id": EARTH3_MAP_ID,
        "status": "production",
        "available_map_ids": [EARTH3_MAP_ID],
        "production_map_ids": [EARTH3_MAP_ID],
        "legacy_map_ids": list(_LEGACY_MAP_IDS),
        "provenance": str(
            state.map_metadata.get(
                "strategic_map_provenance",
                "earth3_production_authority",
            )
        ),
        "fallback": "none",
    }


def _application_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("gates-of-codex")
    except PackageNotFoundError:
        from . import __version__

        return str(__version__)


def _application_block(state: CampaignState, campaign_path: str | Path | None) -> dict:
    """Player-facing application identity shown by the Godot strategic shell."""
    campaign = Path(campaign_path).resolve() if campaign_path else None
    metadata = state.map_metadata
    return {
        "name": "Gates of CodeX",
        "version": _application_version(),
        "scenario_id": str(metadata.get("scenario_id", "")),
        "scenario_status": str(metadata.get("scenario_status", "")),
        "scenario_display_name": str(metadata.get("scenario_display_name", "")),
        "map_id": state.map_id,
        "campaign_path": str(campaign) if campaign else "",
        "campaign_name": state.campaign_name,
        "turn_number": state.turn_number,
        "selected_faction": state.selected_faction.value,
        "difficulty": state.difficulty,
        "fog_of_war_enabled": bool(state.fog_of_war_enabled),
    }


def _player_launch_block(state: CampaignState, campaign_path: str | Path | None) -> dict:
    """Arguments the Godot shell replays to run New/Continue Campaign.

    The launcher owns campaign creation and continuation; the snapshot only
    carries the already-persisted launch settings so the frontend never invents
    a scenario, stack, or path of its own.
    """
    campaign = Path(campaign_path).resolve() if campaign_path else None
    if campaign is None:
        return {"enabled": False, "new_args": [], "continue_args": []}
    metadata = state.map_metadata
    scenario_id = str(metadata.get("scenario_id", "")).strip()
    shared: list[str] = ["--campaign", str(campaign), "--no-launch"]
    if scenario_id:
        shared.extend(["--scenario", scenario_id])
    new_args = ["play", "--new", "--force-new", *shared]
    new_args.extend(["--faction", state.selected_faction.value])
    new_args.extend(["--difficulty", state.difficulty])
    new_args.extend(["--fog-of-war", "on" if state.fog_of_war_enabled else "off"])
    for flag, value in (
        ("--stack-config", metadata.get("stack_config")),
        ("--game", state.game_directory),
        ("--profile", state.profile_directory),
        ("--tactical-map", metadata.get("preferred_map")),
    ):
        text = str(value or "").strip()
        if text:
            new_args.extend([flag, text])
    return {
        "enabled": True,
        "new_args": new_args,
        "continue_args": ["play", "--continue", *shared],
    }


def _control_block(
    state: CampaignState,
    campaign_path: str | Path | None,
    snapshot_path: str | Path | None,
) -> dict:
    snapshot = Path(snapshot_path).resolve() if snapshot_path else None
    campaign = Path(campaign_path).resolve() if campaign_path else None
    commands = snapshot.with_name("frontend_commands.json") if snapshot is not None else None
    return {
        "play": _player_launch_block(state, campaign_path),
        "enabled": campaign is not None and snapshot is not None,
        "campaign_path": str(campaign) if campaign else "",
        "snapshot_path": str(snapshot) if snapshot else "",
        "commands_path": str(commands) if commands else "",
        "python_executable": str(Path(sys.executable).resolve()),
        "python_module": FRONTEND_PYTHON_MODULE,
        "supported_ops": [
            "move",
            "issue_move_order",
            "cancel_move_order",
            "commit_move_orders",
            "advance_operational_tick",
            "end_turn",
            "run_ai",
            "auto_resolve",
            "construct",
            "repair",
            "handoff",
            "refresh",
        ],
    }
