from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .models import CampaignState, Faction
from .supply import reachable_supply_provinces


FRONTEND_SCHEMA_VERSION = 2


def build_frontend_snapshot(state: CampaignState) -> dict:
    state.validate()
    occupied = {battalion.province_id: battalion.battalion_id for battalion in state.battalions.values()}
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
        },
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
        "provinces": [
            {
                "id": province.province_id,
                "display_name": province.display_name,
                "owner": province.owner.value,
                "x": province.x,
                "y": province.y,
                "terrain": province.terrain,
                "map_region": province.map_region,
                "resource_yield": province.resource_yield,
                "fortification": province.fortification,
                "occupied_by": occupied.get(province.province_id, ""),
                "supply_source_for": list(province.metadata.get("supply_source_for", [])),
                "metadata": province.metadata,
            }
            for province in sorted(state.provinces.values(), key=lambda value: value.province_id)
        ],
        "edges": [[left, right] for left, right in edges],
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
                "supply": battalion.supply,
                "is_in_supply": battalion.province_id in supply_reach.get(battalion.faction.value, set()),
                "encircled_turns": battalion.encircled_turns,
                "experience": battalion.experience,
                "movement_remaining": battalion.movement_remaining,
                "combat_actions_remaining": battalion.combat_actions_remaining,
                "is_player_controlled": battalion.is_player_controlled,
            }
            for battalion in sorted(state.battalions.values(), key=lambda value: value.battalion_id)
        ],
        "pending_battle": _pending_battle(state),
    }


def write_frontend_snapshot(state: CampaignState, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(build_frontend_snapshot(state), indent=2, ensure_ascii=False) + "\n"
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
