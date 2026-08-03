from __future__ import annotations

from .codex.catalog import CodeXCatalog, UnitDefinition
from .models import BattalionRosterEntry, CampaignState, Faction


PREFERRED_CATEGORIES = ("infantry", "tank", "ifv", "vehicle", "artillery", "recon")


def _pick(units: list[UnitDefinition], category: str) -> UnitDefinition | None:
    candidates = [unit for unit in units if unit.category == category and not unit.doctrine]
    return sorted(candidates, key=lambda unit: (unit.doctrine_cost, unit.name))[0] if candidates else None


def populate_starter_rosters(state: CampaignState, catalog: CodeXCatalog) -> None:
    for battalion in state.battalions.values():
        units = catalog.by_faction(battalion.faction.value)
        if not units:
            raise ValueError(f"Code:X catalog contains no units for {battalion.faction.value}")
        infantry = _pick(units, "infantry") or units[0]
        support = None
        for category in PREFERRED_CATEGORIES[1:]:
            support = _pick(units, category)
            if support:
                break
        roster = [BattalionRosterEntry(infantry.name, quantity=3, category=infantry.category)]
        if support and support.name != infantry.name:
            roster.append(BattalionRosterEntry(support.name, quantity=1, category=support.category))
        battalion.roster = roster


def set_player_faction(state: CampaignState, faction: Faction) -> None:
    state.selected_faction = faction
    state.current_faction = faction
    for faction_state in state.factions.values():
        faction_state.is_human_controlled = faction_state.faction == faction
    for battalion in state.battalions.values():
        battalion.is_player_controlled = battalion.faction == faction
