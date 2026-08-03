from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .models import (
    Battalion,
    BattalionRosterEntry,
    BattalionType,
    BattleParticipant,
    CampaignState,
    Faction,
    FactionState,
    PendingBattle,
    Province,
)


def _roster(value: dict[str, Any]) -> BattalionRosterEntry:
    return BattalionRosterEntry(**value)


def campaign_from_dict(data: dict[str, Any]) -> CampaignState:
    factions = {
        key: FactionState(
            faction=Faction(value["faction"]),
            resources=value.get("resources", 1000),
            researched_keys=list(value.get("researched_keys", [])),
            recruited_pool=[_roster(item) for item in value.get("recruited_pool", [])],
            is_human_controlled=value.get("is_human_controlled", False),
            is_eliminated=value.get("is_eliminated", False),
        )
        for key, value in data.get("factions", {}).items()
    }
    provinces = {
        key: Province(
            province_id=value["province_id"],
            display_name=value["display_name"],
            owner=Faction(value.get("owner", "neutral")),
            neighbors=list(value.get("neighbors", [])),
            terrain=value.get("terrain", "temperate"),
            map_region=value.get("map_region", "ostfront"),
            x=float(value.get("x", 0)),
            y=float(value.get("y", 0)),
            resource_yield=int(value.get("resource_yield", 10)),
            fortification=int(value.get("fortification", 0)),
        )
        for key, value in data.get("provinces", {}).items()
    }
    battalions = {
        key: Battalion(
            battalion_id=value["battalion_id"],
            faction=Faction(value["faction"]),
            province_id=value["province_id"],
            battalion_type=BattalionType(value.get("battalion_type", "combined_arms")),
            roster=[_roster(item) for item in value.get("roster", [])],
            is_player_controlled=value.get("is_player_controlled", False),
            movement_remaining=int(value.get("movement_remaining", 1)),
            combat_actions_remaining=int(value.get("combat_actions_remaining", 1)),
            supply=int(value.get("supply", 100)),
            experience=int(value.get("experience", 0)),
            encircled_turns=int(value.get("encircled_turns", 0)),
        )
        for key, value in data.get("battalions", {}).items()
    }
    pending_data = data.get("pending_battle")
    pending = None
    if pending_data:
        pending = PendingBattle(
            battle_id=pending_data["battle_id"],
            origin_province_id=pending_data["origin_province_id"],
            target_province_id=pending_data["target_province_id"],
            attacker_faction=Faction(pending_data["attacker_faction"]),
            defender_faction=Faction(pending_data["defender_faction"]),
            attacking_participants=[
                BattleParticipant(
                    battalion_id=item["battalion_id"],
                    faction=Faction(item["faction"]),
                    stage=item["stage"],
                    is_primary=item.get("is_primary", False),
                )
                for item in pending_data.get("attacking_participants", [])
            ],
            defending_participants=[
                BattleParticipant(
                    battalion_id=item["battalion_id"],
                    faction=Faction(item["faction"]),
                    stage=item["stage"],
                    is_primary=item.get("is_primary", False),
                )
                for item in pending_data.get("defending_participants", [])
            ],
            player_faction=Faction(pending_data["player_faction"]),
            player_is_attacker=pending_data["player_is_attacker"],
            exported_save_path=pending_data.get("exported_save_path", ""),
            started=pending_data.get("started", False),
            completed=pending_data.get("completed", False),
        )
    state = CampaignState(
        campaign_name=data["campaign_name"],
        turn_number=int(data.get("turn_number", 1)),
        current_faction=Faction(data.get("current_faction", "nato")),
        selected_faction=Faction(data.get("selected_faction", "nato")),
        difficulty=data.get("difficulty", "normal"),
        game_directory=data.get("game_directory", ""),
        profile_directory=data.get("profile_directory", ""),
        code_x_directory=data.get("code_x_directory", ""),
        factions=factions,
        provinces=provinces,
        battalions=battalions,
        pending_battle=pending,
        schema_version=int(data.get("schema_version", 1)),
    )
    state.validate()
    return state


def load_campaign(path: str | Path) -> CampaignState:
    source = Path(path)
    return campaign_from_dict(json.loads(source.read_text(encoding="utf-8-sig")))


def save_campaign(state: CampaignState, path: str | Path) -> Path:
    state.validate()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix=f".{destination.name}.",
        suffix=".tmp", dir=destination.parent, delete=False
    ) as temporary:
        temporary.write(payload)
        temporary_path = Path(temporary.name)
    temporary_path.replace(destination)
    return destination
