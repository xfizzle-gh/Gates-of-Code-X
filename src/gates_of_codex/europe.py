from __future__ import annotations

import base64
import gzip
import json
from importlib.resources import files

from .control import apply_modern_control_profile, default_alliances
from .formations import default_formations, seed_formation_battalions
from .models import CampaignState, Faction, FactionState, Province


_GRAPH_CHUNKS = tuple(f"data/goe_graph_{index:02d}.b85" for index in range(6))


def load_goe_europe_graph() -> dict:
    package = files("gates_of_codex")
    encoded = "".join(package.joinpath(path).read_text(encoding="ascii") for path in _GRAPH_CHUNKS)
    payload = gzip.decompress(base64.b85decode(encoded.encode("ascii")))
    return json.loads(payload.decode("utf-8"))


def build_goe_europe_campaign() -> CampaignState:
    graph = load_goe_europe_graph()
    provinces = {
        province_id: Province(
            province_id=province_id,
            display_name=value["display_name"],
            owner=Faction.NEUTRAL,
            neighbors=list(value.get("neighbors", [])),
            terrain="unknown",
            map_region="goe_europe",
            x=float(value.get("x", 0)),
            y=float(value.get("y", 0)),
            resource_yield=10,
            metadata=dict(value.get("metadata", {})),
        )
        for province_id, value in graph["provinces"].items()
    }
    state = CampaignState(
        campaign_name="Gates of CodeX: Europe",
        selected_faction=Faction.NATO,
        current_faction=Faction.NATO,
        map_id=graph["map_id"],
        map_metadata={
            **dict(graph.get("metadata", {})),
            "central_asia_status": "provisional PRC and North Korean deployment zone",
        },
        factions={
            Faction.NATO.value: FactionState(Faction.NATO, resources=1200, is_human_controlled=True),
            Faction.UKRAINE.value: FactionState(Faction.UKRAINE, resources=1000),
            Faction.RUSSIA.value: FactionState(Faction.RUSSIA, resources=1200),
            Faction.PRC.value: FactionState(Faction.PRC, resources=1000),
        },
        alliances=default_alliances(),
        formations=default_formations(),
        provinces=provinces,
        schema_version=3,
    )
    seed_formation_battalions(state)
    apply_modern_control_profile(state)
    state.validate()
    return state
