"""Keep a faction on the map while it still owns land."""

from __future__ import annotations

from collections import deque

from .models import Battalion, BattalionRosterEntry, BattalionType, CampaignState, Faction


def ensure_faction_forces(state: CampaignState) -> list[str]:
    spawned: list[str] = []
    for faction_id, faction_state in state.factions.items():
        if faction_state.is_eliminated:
            continue
        faction = Faction(faction_id)
        for home in _ungarrisoned_homes(state, faction):
            spawned.append(_spawn_remnant(state, faction, home))
    if spawned:
        from .force_migration import ensure_strategic_formations

        ensure_strategic_formations(state)
    return spawned


def _ungarrisoned_homes(state: CampaignState, faction: Faction) -> list[str]:
    """One remnant per owned land component that has no friendly battalion."""

    owned_ids = {
        province.province_id for province in state.provinces.values() if province.owner == faction
    }
    if not owned_ids:
        return []
    occupied = {
        battalion.province_id for battalion in state.battalions.values() if battalion.faction == faction
    }
    anyone = {battalion.province_id for battalion in state.battalions.values()}
    seen: set[str] = set()
    homes: list[str] = []
    for start in sorted(owned_ids):
        if start in seen:
            continue
        component: list[str] = []
        queue: deque[str] = deque([start])
        seen.add(start)
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor_id in state.provinces[current].neighbors:
                if neighbor_id in owned_ids and neighbor_id not in seen:
                    seen.add(neighbor_id)
                    queue.append(neighbor_id)
        if any(province_id in occupied for province_id in component):
            continue
        empty = [province_id for province_id in component if province_id not in anyone]
        if not empty:
            continue
        best = max(
            empty,
            key=lambda province_id: (
                state.provinces[province_id].resource_yield,
                state.provinces[province_id].display_name,
            ),
        )
        homes.append(best)
    return homes


def _home_province(state: CampaignState, faction: Faction) -> str | None:
    homes = _ungarrisoned_homes(state, faction)
    return homes[0] if homes else None


def _spawn_remnant(state: CampaignState, faction: Faction, province_id: str) -> str:
    serial = 1
    battalion_id = f"{faction.value}-remnant-{serial}"
    while battalion_id in state.battalions:
        serial += 1
        battalion_id = f"{faction.value}-remnant-{serial}"
    roster = _remnant_roster(state, faction)
    formation_id = next(
        (formation.formation_id for formation in state.formations.values() if formation.faction == faction),
        "",
    )
    state.battalions[battalion_id] = Battalion(
        battalion_id=battalion_id,
        faction=faction,
        province_id=province_id,
        battalion_type=BattalionType.INFANTRY,
        formation_id=formation_id,
        roster=roster,
        authorized_roster=[
            BattalionRosterEntry(entry.unit_name, entry.quantity, category=entry.category)
            for entry in roster
        ],
        is_player_controlled=faction == state.selected_faction,
        movement_remaining=1,
        combat_actions_remaining=1,
        condition=70,
        supply=80,
    )
    return battalion_id


def _remnant_roster(state: CampaignState, faction: Faction) -> list[BattalionRosterEntry]:
    for battalion in state.battalions.values():
        if battalion.faction == faction and battalion.roster:
            entry = battalion.roster[0]
            return [BattalionRosterEntry(entry.unit_name, max(1, entry.quantity), category=entry.category)]
    infantry = [
        economy
        for economy in state.unit_economy.values()
        if economy.faction == faction and economy.category == "infantry"
    ]
    if infantry:
        pick = sorted(infantry, key=lambda item: (item.purchase_cost, item.unit_name))[0]
        return [BattalionRosterEntry(pick.unit_name, 1, category="infantry")]
    return [BattalionRosterEntry(f"placeholder({faction.value})", 1, category="infantry")]
