from __future__ import annotations

import json
from pathlib import Path

from .control import default_alliances
from .models import (
    Battalion,
    BattalionRosterEntry,
    BattalionType,
    CampaignState,
    Faction,
    FactionState,
    Province,
)
from .strategic import ensure_strategic_layer
from .europe_mediterranean_map import DEFAULT_OUTPUT_DIR, MAP_ID


def default_manifest_path() -> Path:
    return Path(DEFAULT_OUTPUT_DIR) / "map_manifest.json"


def load_manifest(path: str | Path | None = None) -> dict:
    manifest_path = Path(path) if path else default_manifest_path()
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Europe-Mediterranean prototype manifest not found: {manifest_path}. "
            "Run: gates-of-codex generate-europe-mediterranean-prototype"
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def build_europe_mediterranean_prototype_campaign(
    *,
    manifest_path: str | Path | None = None,
    selected_faction: Faction = Faction.NATO,
) -> CampaignState:
    """Non-canonical campaign whose provinces exactly match the EM prototype manifest."""

    manifest = load_manifest(manifest_path)
    if str(manifest.get("map_id")) != MAP_ID:
        raise ValueError(f"Expected map_id {MAP_ID}, got {manifest.get('map_id')}")

    provinces: dict[str, Province] = {}
    for row in manifest.get("province_table", []):
        province_id = str(row["province_id"])
        anchor = row.get("marker_anchor") or [0.0, 0.0]
        neighbors = [str(item) for item in row.get("source_neighbors", [])]
        provinces[province_id] = Province(
            province_id=province_id,
            display_name=str(row.get("display_name", province_id)),
            owner=Faction.NEUTRAL,
            neighbors=neighbors,
            terrain="temperate",
            map_region="europe_mediterranean",
            x=float(anchor[0]),
            y=float(anchor[1]),
            resource_yield=12,
            fortification=0,
            metadata={
                "europe_mediterranean_prototype": True,
                "provenance": dict(row.get("provenance", {})),
                "rgb": list(row.get("rgb", [])),
            },
        )

    ownership = _seed_ownership(provinces)
    for province_id, owner in ownership.items():
        provinces[province_id].owner = owner
        # Sample facilities on owned hubs.
        if province_id in {
            "em_paris",
            "em_berlin",
            "em_london",
            "em_rome",
            "em_moscow",
            "em_kyiv",
            "em_istanbul",
            "em_cairo",
            "em_algiers",
        }:
            provinces[province_id].metadata["infrastructure"] = {
                "supply_hub": 1,
                "air_base": 1,
                "port": 1 if province_id in {"em_london", "em_rome", "em_istanbul", "em_cairo", "em_algiers"} else 0,
            }
            provinces[province_id].fortification = 1

    state = CampaignState(
        campaign_name="Gates of CodeX: Europe-Mediterranean Prototype",
        selected_faction=selected_faction,
        current_faction=selected_faction,
        map_id=MAP_ID,
        map_metadata={
            "strategic_map_id": MAP_ID,
            "strategic_map_manifest": "assets/maps/europe_mediterranean/prototype/map_manifest.json",
            "strategic_map_provenance": "research_derived_europe_mediterranean_prototype_v2",
            "europe_mediterranean_prototype": True,
            "canonical": False,
            "note": "Non-canonical prototype campaign matching europe_mediterranean_prototype manifest.",
            "operational_objectives": [
                {
                    "id": "western-breakthrough",
                    "coalition": "western-coalition",
                    "display_name": "Secure Eastern Hubs",
                    "kind": "control",
                    "targets": ["em_moscow", "em_kyiv", "em_minsk"],
                    "required": 2,
                    "reward_each": 300,
                    "primary": True,
                    "progress": 0,
                    "completed": False,
                    "completed_turn": 0,
                    "rewarded": False,
                },
                {
                    "id": "eastern-breakthrough",
                    "coalition": "eastern-coalition",
                    "display_name": "Secure Western Hubs",
                    "kind": "control",
                    "targets": ["em_paris", "em_berlin", "em_warsaw"],
                    "required": 2,
                    "reward_each": 300,
                    "primary": True,
                    "progress": 0,
                    "completed": False,
                    "completed_turn": 0,
                    "rewarded": False,
                },
            ],
            "coalition_capitals": {
                "western-coalition": ["em_paris", "em_london", "em_berlin"],
                "eastern-coalition": ["em_moscow", "em_kyiv", "em_minsk"],
            },
        },
        factions={
            Faction.NATO.value: FactionState(Faction.NATO, resources=1500, is_human_controlled=True),
            Faction.UKRAINE.value: FactionState(Faction.UKRAINE, resources=1200),
            Faction.RUSSIA.value: FactionState(Faction.RUSSIA, resources=1500),
            Faction.PRC.value: FactionState(Faction.PRC, resources=1200),
        },
        alliances=default_alliances(),
        provinces=provinces,
        schema_version=5,
    )
    _seed_sample_battalions(state)
    ensure_strategic_layer(state)
    state.validate()
    return state


def _seed_ownership(provinces: dict[str, Province]) -> dict[str, Faction]:
    owners = {pid: Faction.NEUTRAL for pid in provinces}
    for province in provinces.values():
        lon = float(province.metadata.get("provenance", {}).get("lon", 0.0))
        if lon < 8:
            owners[province.province_id] = Faction.NATO
        elif lon < 24:
            owners[province.province_id] = Faction.UKRAINE
        elif lon < 38:
            owners[province.province_id] = Faction.RUSSIA
        else:
            owners[province.province_id] = Faction.PRC
    return owners


def _seed_sample_battalions(state: CampaignState) -> None:
    templates = {
        Faction.NATO: ("em_paris", "infantry(nato)"),
        Faction.UKRAINE: ("em_kyiv", "infantry(ukr)"),
        Faction.RUSSIA: ("em_moscow", "infantry(rusa)"),
        Faction.PRC: ("em_ankara", "infantry(prc)"),
    }
    for faction, (preferred, unit) in templates.items():
        province_id = preferred if preferred in state.provinces else _first_owned(state, faction)
        if province_id is None:
            continue
        battalion_id = f"em-{faction.value}-1"
        state.battalions[battalion_id] = Battalion(
            battalion_id=battalion_id,
            faction=faction,
            province_id=province_id,
            battalion_type=BattalionType.INFANTRY,
            roster=[BattalionRosterEntry(unit, 4, category="infantry")],
            authorized_roster=[BattalionRosterEntry(unit, 4, category="infantry")],
            is_player_controlled=faction == state.selected_faction,
            supply=100,
            condition=100,
        )


def _first_owned(state: CampaignState, faction: Faction) -> str | None:
    for province in sorted(state.provinces.values(), key=lambda value: value.province_id):
        if province.owner == faction:
            return province.province_id
    return None
