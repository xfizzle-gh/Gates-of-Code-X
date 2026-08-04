from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

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
from .supply import reachable_supply_provinces


FRONTEND_SCHEMA_VERSION = 7
FRONTEND_PYTHON_MODULE = "gates_of_codex"


def build_frontend_snapshot(
    state: CampaignState,
    *,
    campaign_path: str | Path | None = None,
    snapshot_path: str | Path | None = None,
) -> dict:
    ensure_strategic_layer(state)
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

    return {
        "schema": "gates-of-codex.frontend",
        "schema_version": FRONTEND_SCHEMA_VERSION,
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
                "supply_reachable_provinces": len(supply_reach.get(faction_id, set())),
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
        "battalions": [
            {
                "id": battalion.battalion_id,
                "formation_id": battalion.formation_id,
                "faction": battalion.faction.value,
                "province_id": battalion.province_id,
                "battalion_type": battalion.battalion_type.value,
                "unit_count": battalion.unit_count,
                "authorized_unit_count": battalion.authorized_unit_count,
                "replacement_deficit": battalion.replacement_deficit,
                "condition": battalion.condition,
                "repair_points_needed": 100 - battalion.condition,
                "supply": battalion.supply,
                "is_in_supply": battalion.province_id in supply_reach.get(battalion.faction.value, set()),
                "encircled_turns": battalion.encircled_turns,
                "experience": battalion.experience,
                "movement_remaining": battalion.movement_remaining,
                "combat_actions_remaining": battalion.combat_actions_remaining,
                "is_player_controlled": battalion.is_player_controlled,
                "roster": [asdict(entry) for entry in battalion.roster],
                "authorized_roster": [asdict(entry) for entry in battalion.authorized_roster],
            }
            for battalion in sorted(state.battalions.values(), key=lambda value: value.battalion_id)
        ],
        "battalion_stacks": {
            province_id: list(battalion_ids)
            for province_id, battalion_ids in sorted(occupied.items())
        },
        "pending_battle": _pending_battle(state),
        "front_options": list_front_options(state, state.current_faction),
        "control": _control_block(campaign_path, snapshot_path),
        "province_names": dict(
            state.map_metadata.get("province_names") or province_name_coverage(state)
        ),
    }


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
    }


def _strategic_map_block(
    state: CampaignState,
    snapshot_path: str | Path | None,
) -> dict:
    snapshot_directory = Path(snapshot_path).resolve().parent if snapshot_path else None
    configured = str(state.map_metadata.get("strategic_map_manifest", "")).strip()
    map_id = str(state.map_metadata.get("strategic_map_id", state.map_id))
    if configured:
        manifest = Path(configured).expanduser()
        if not manifest.is_absolute() and snapshot_directory is not None:
            manifest = snapshot_directory / manifest
    elif snapshot_directory is not None:
        relative = {
            "europe_mediterranean_from_goe": "assets/maps/europe_mediterranean/from_goe/map_manifest.json",
            "goe_europe": "assets/maps/europe/interim_goe/map_manifest.json",
            "interim_goe_europe": "assets/maps/europe/interim_goe/map_manifest.json",
        }.get(map_id, "assets/maps/europe/interim_goe/map_manifest.json")
        manifest = snapshot_directory / relative
    else:
        manifest = None
    resolved = manifest.resolve() if manifest is not None else None
    default_prov = "interim_goe_reference_asset"
    if map_id == "europe_mediterranean_from_goe":
        default_prov = "derived_from_interim_goe_europe_theatre_crop"
    return {
        "enabled": bool(resolved and resolved.is_file()),
        "manifest_path": str(resolved) if resolved else "",
        "configured": bool(configured),
        "map_id": map_id,
        "available_map_ids": ["interim_goe_europe", "europe_mediterranean_from_goe"],
        "provenance": str(state.map_metadata.get("strategic_map_provenance", default_prov)),
        "fallback": "marker_non_authoritative",
    }


def _control_block(campaign_path: str | Path | None, snapshot_path: str | Path | None) -> dict:
    snapshot = Path(snapshot_path).resolve() if snapshot_path else None
    campaign = Path(campaign_path).resolve() if campaign_path else None
    commands = snapshot.with_name("frontend_commands.json") if snapshot is not None else None
    return {
        "enabled": campaign is not None and snapshot is not None,
        "campaign_path": str(campaign) if campaign else "",
        "snapshot_path": str(snapshot) if snapshot else "",
        "commands_path": str(commands) if commands else "",
        "python_executable": str(Path(sys.executable).resolve()),
        "python_module": FRONTEND_PYTHON_MODULE,
        "supported_ops": [
            "move",
            "end_turn",
            "run_ai",
            "auto_resolve",
            "construct",
            "repair",
            "handoff",
            "refresh",
        ],
    }
