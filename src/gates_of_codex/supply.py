from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .diplomacy import allied_factions, is_friendly_owner
from .models import Battalion, CampaignState, Faction
from .operational_position import load_operational_graph_for_state


DEFAULT_SUPPLY_SOURCES: dict[Faction, tuple[str, ...]] = {
    Faction.NATO: ("Sussex", "Wester Ems", "Warszawa"),
    Faction.UKRAINE: ("Lwow", "Zhytomyr"),
    Faction.RUSSIA: ("Minsk", "Leningrad"),
    Faction.PRC: ("province_0501",),
}

SUPPLY_RESTORE = 20
SUPPLY_DRAIN = 25
ATTRITION_START_TURN = 3


@dataclass(frozen=True, slots=True)
class SupplyReport:
    faction: Faction
    sources: tuple[str, ...]
    reachable_provinces: int
    supplied_battalions: tuple[str, ...]
    isolated_battalions: tuple[str, ...]
    destroyed_battalions: tuple[str, ...]


def mark_default_supply_sources(state: CampaignState) -> None:
    for faction, province_ids in DEFAULT_SUPPLY_SOURCES.items():
        for province_id in province_ids:
            province = state.provinces.get(province_id)
            if province is None:
                raise ValueError(f"Supply source for {faction.value} references missing province {province_id}")
            values = set(province.metadata.get("supply_source_for", []))
            values.add(faction.value)
            province.metadata["supply_source_for"] = sorted(values)
            static_values = set(province.metadata.get("static_supply_source_for", []))
            static_values.add(faction.value)
            province.metadata["static_supply_source_for"] = sorted(static_values)


def reachable_supply_provinces(state: CampaignState, faction: Faction) -> set[str]:
    friendly = allied_factions(state, faction)
    sources = _eligible_sources(state, faction)
    reachable: set[str] = set()
    queue: deque[str] = deque()
    for province_id in sources:
        province = state.provinces[province_id]
        if province.owner in friendly:
            reachable.add(province_id)
            queue.append(province_id)
    while queue:
        province_id = queue.popleft()
        for neighbor_id in sorted(state.provinces[province_id].neighbors):
            if neighbor_id in reachable:
                continue
            neighbor = state.provinces[neighbor_id]
            if neighbor.owner not in friendly:
                continue
            reachable.add(neighbor_id)
            queue.append(neighbor_id)
    return reachable


def refresh_supply_for_faction(state: CampaignState, faction: Faction) -> SupplyReport:
    reachable = reachable_supply_provinces(state, faction)
    supplied: list[str] = []
    isolated: list[str] = []
    destroyed: list[str] = []

    for battalion in sorted(
        (value for value in state.battalions.values() if value.faction == faction),
        key=lambda value: value.battalion_id,
    ):
        operational_supplied = formation_supplied_for_battalion(
            state, battalion
        )
        is_supplied = (
            battalion.province_id in reachable
            if operational_supplied is None
            else operational_supplied
        )
        if is_supplied:
            battalion.supply = min(100, battalion.supply + SUPPLY_RESTORE)
            battalion.encircled_turns = 0
            supplied.append(battalion.battalion_id)
            continue

        battalion.supply = max(0, battalion.supply - SUPPLY_DRAIN)
        battalion.encircled_turns += 1
        isolated.append(battalion.battalion_id)
        if battalion.encircled_turns >= ATTRITION_START_TURN and battalion.supply <= 25:
            _apply_encirclement_attrition(battalion)
        if battalion.is_destroyed:
            destroyed.append(battalion.battalion_id)
        if battalion.supply == 0:
            battalion.movement_remaining = 0
            battalion.combat_actions_remaining = 0

    for battalion_id in destroyed:
        state.battalions.pop(battalion_id, None)

    report = SupplyReport(
        faction=faction,
        sources=tuple(_eligible_sources(state, faction)),
        reachable_provinces=len(reachable),
        supplied_battalions=tuple(supplied),
        isolated_battalions=tuple(isolated),
        destroyed_battalions=tuple(destroyed),
    )
    state.validate()
    return report


def refresh_all_supply(state: CampaignState) -> list[SupplyReport]:
    return [
        refresh_supply_for_faction(state, faction)
        for faction in (Faction.NATO, Faction.UKRAINE, Faction.RUSSIA, Faction.PRC)
        if faction.value in state.factions and not state.factions[faction.value].is_eliminated
    ]


def formation_supplied_for_battalion(
    state: CampaignState, battalion: Battalion
) -> bool | None:
    """Return S8 formation authority, or None for legacy no-graph campaigns."""
    if load_operational_graph_for_state(state) is None:
        return None
    force = state.strategic_formations.get(
        battalion.strategic_formation_id
    )
    if force is None:
        force = next(
            (
                item
                for item in sorted(
                    state.strategic_formations.values(),
                    key=lambda value: value.strategic_formation_id,
                )
                if battalion.battalion_id in item.battalion_ids
            ),
            None,
        )
    return False if force is None else force.supplied


def _eligible_sources(state: CampaignState, faction: Faction) -> list[str]:
    friendly = {value.value for value in allied_factions(state, faction)}
    sources = {
        province.province_id
        for province in state.provinces.values()
        if friendly.intersection(
            set(province.metadata.get("supply_source_for", []))
            | set(province.metadata.get("static_supply_source_for", []))
        )
        and is_friendly_owner(state, faction, province.owner)
    }
    for allied in allied_factions(state, faction):
        for province_id in DEFAULT_SUPPLY_SOURCES.get(allied, ()):
            province = state.provinces.get(province_id)
            if province is not None and is_friendly_owner(state, faction, province.owner):
                sources.add(province_id)
    return sorted(sources)


def _apply_encirclement_attrition(battalion: Battalion) -> None:
    if not battalion.roster:
        return
    largest = max(battalion.roster, key=lambda value: (value.quantity, value.unit_name))
    largest.quantity = max(0, largest.quantity - 1)
    battalion.roster = [value for value in battalion.roster if value.quantity > 0]
