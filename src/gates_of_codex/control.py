from __future__ import annotations

from collections import Counter, deque

from .formations import FORMATION_DEPLOYMENTS
from .models import Alliance, CampaignState, Faction


CONTROL_PROFILE_ID = "modern_europe_v1"
PRC_EXPANSION_RADIUS = 4

CONTROL_SEEDS: dict[Faction, tuple[str, ...]] = {
    Faction.NATO: (
        "Sussex",
        "Wester Ems",
        "Hannover",
        "Brandenburg",
        "Warszawa",
        "Krakow",
        "Gdynia",
        "Oberbayern",
        "Niederosterreich",
    ),
    Faction.UKRAINE: (
        "Stanislawow",
        "Lwow",
        "Proskuriv",
        "Zhytomyr",
        "Wolyn",
    ),
    Faction.RUSSIA: (
        "Mozyr",
        "Bobryusk",
        "Minsk",
        "Vitebsk",
        "Nevel",
        "Pskov",
        "Luga",
        "Leningrad",
    ),
    Faction.PRC: (
        "province_0501",
        "province_0508",
    ),
}


def default_alliances() -> dict[str, Alliance]:
    values = (
        Alliance(
            alliance_id="western-coalition",
            display_name="Western Coalition",
            factions=[Faction.NATO, Faction.UKRAINE],
            notes="Strategic allies with separate formations, resources, research, and turn ownership.",
        ),
        Alliance(
            alliance_id="eastern-coalition",
            display_name="Eastern Coalition",
            factions=[Faction.RUSSIA, Faction.PRC],
            notes="Strategic allies with separate formations, resources, research, and turn ownership.",
        ),
    )
    return {alliance.alliance_id: alliance for alliance in values}


def apply_modern_control_profile(state: CampaignState) -> None:
    """Assign every province to the nearest strategic seed on the recovered graph.

    This is a deterministic development profile, not a claim that the recovered alpha
    supplied modern political ownership. PRC expansion is intentionally capped around
    its provisional Central Asian anchors.
    """

    seeds = _resolved_seeds(state)
    claimed: dict[str, Faction] = {}
    roots: dict[str, str] = {}
    distances: dict[str, int] = {}
    queue: deque[tuple[str, Faction, str, int]] = deque()

    faction_order = (Faction.NATO, Faction.UKRAINE, Faction.RUSSIA, Faction.PRC)
    for faction in faction_order:
        for province_id in sorted(seeds[faction]):
            if province_id in claimed:
                continue
            claimed[province_id] = faction
            roots[province_id] = province_id
            distances[province_id] = 0
            queue.append((province_id, faction, province_id, 0))

    while queue:
        province_id, faction, root, distance = queue.popleft()
        if faction == Faction.PRC and distance >= PRC_EXPANSION_RADIUS:
            continue
        for neighbor_id in sorted(state.provinces[province_id].neighbors):
            if neighbor_id in claimed:
                continue
            claimed[neighbor_id] = faction
            roots[neighbor_id] = root
            distances[neighbor_id] = distance + 1
            queue.append((neighbor_id, faction, root, distance + 1))

    # Disconnected or isolated nodes use the nearest seed in development-layout space.
    for province_id, province in state.provinces.items():
        if province_id in claimed:
            continue
        faction, root = min(
            (
                (
                    faction,
                    seed_id,
                    (province.x - state.provinces[seed_id].x) ** 2
                    + (province.y - state.provinces[seed_id].y) ** 2,
                )
                for faction in faction_order[:-1]
                for seed_id in seeds[faction]
            ),
            key=lambda value: (value[2], value[0].value, value[1]),
        )[:2]
        claimed[province_id] = faction
        roots[province_id] = root
        distances[province_id] = -1

    for province_id, province in state.provinces.items():
        province.owner = claimed[province_id]
        province.metadata["control_profile"] = CONTROL_PROFILE_ID
        province.metadata["control_seed"] = roots[province_id]
        province.metadata["control_distance"] = distances[province_id]

    # Formation locations are authoritative deployment anchors.
    for formation_id, province_id in FORMATION_DEPLOYMENTS.items():
        battalion = next(
            (value for value in state.battalions.values() if value.formation_id == formation_id),
            None,
        )
        if battalion is None:
            continue
        state.provinces[province_id].owner = battalion.faction
        state.provinces[province_id].metadata["formation_anchor"] = formation_id

    counts = Counter(province.owner.value for province in state.provinces.values())
    state.map_metadata.update(
        {
            "modern_ownership_status": "deterministic development profile",
            "modern_control_profile": CONTROL_PROFILE_ID,
            "modern_control_counts": dict(sorted(counts.items())),
            "source_ownership_preserved_in_province_metadata": True,
            "central_asia_status": "provisional PRC and Russia-aligned North Korean deployments",
        }
    )
    state.validate()


def _resolved_seeds(state: CampaignState) -> dict[Faction, set[str]]:
    seeds = {faction: set(values) for faction, values in CONTROL_SEEDS.items()}
    for formation_id, province_id in FORMATION_DEPLOYMENTS.items():
        formation = state.formations.get(formation_id)
        if formation is not None:
            seeds.setdefault(formation.faction, set()).add(province_id)
    for faction, province_ids in seeds.items():
        missing = sorted(province_id for province_id in province_ids if province_id not in state.provinces)
        if missing:
            raise ValueError(f"Control seeds for {faction.value} reference missing provinces: {missing}")
    return seeds
