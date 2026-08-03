from __future__ import annotations

from .codex.catalog import CodeXCatalog, UnitDefinition
from .models import BattalionRosterEntry, CampaignState, Faction


PREFERRED_CATEGORIES = ("infantry", "tank", "ifv", "vehicle", "artillery", "recon", "air_defense")


def _pick(units: list[UnitDefinition], category: str) -> UnitDefinition | None:
    candidates = [unit for unit in units if unit.category == category and not unit.doctrine]
    return sorted(candidates, key=lambda unit: (unit.doctrine_cost, unit.name))[0] if candidates else None


def populate_starter_rosters(state: CampaignState, catalog: CodeXCatalog) -> None:
    for battalion in state.battalions.values():
        units = catalog.by_faction(battalion.faction.value)
        if not units:
            raise ValueError(f"Code:X catalog contains no units for {battalion.faction.value}")
        formation = state.formations.get(battalion.formation_id)
        priorities = list(formation.preferred_categories) if formation else list(PREFERRED_CATEGORIES)
        for category in PREFERRED_CATEGORIES:
            if category not in priorities:
                priorities.append(category)
        infantry = _pick(units, "infantry") or units[0]
        support = None
        for category in priorities:
            if category == "infantry":
                continue
            support = _pick(units, category)
            if support is not None:
                break
        roster = [BattalionRosterEntry(infantry.name, quantity=3, category=infantry.category)]
        if support and support.name != infantry.name:
            roster.append(BattalionRosterEntry(support.name, quantity=1, category=support.category))
        battalion.roster = roster
        battalion.authorized_roster = [
            BattalionRosterEntry(
                entry.unit_name,
                quantity=entry.quantity,
                stage=entry.stage,
                category=entry.category,
                preserved_objects=list(entry.preserved_objects),
            )
            for entry in roster
        ]
        battalion.condition = 100


def set_player_faction(state: CampaignState, faction: Faction) -> None:
    state.selected_faction = faction
    state.current_faction = faction
    for faction_state in state.factions.values():
        faction_state.is_human_controlled = faction_state.faction == faction
    for battalion in state.battalions.values():
        battalion.is_player_controlled = battalion.faction == faction
