from __future__ import annotations

from .codex.catalog import CodeXCatalog, UnitDefinition
from .models import BattalionRosterEntry, CampaignState, Faction


PREFERRED_CATEGORIES = ("infantry", "tank", "ifv", "vehicle", "artillery", "recon", "air_defense")
_ACCEPTANCE_SKIP_TOKENS = (
    "_ai",
    "crew",
    "drone",
    "a-10",
    "heli",
    "uh-60",
    "uh60",
    "c130",
    "il-76",
    "v22",
    "mortar",
    "m119",
    "d-30",
    "msta",
    "howitzer",
    "para",
)


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
        _apply_roster(battalion, roster)


def populate_acceptance_combat_rosters(state: CampaignState, catalog: CodeXCatalog) -> None:
    """Build fightable NATO/Russia acceptance rosters from Code:X squad_* entries."""

    for battalion in state.battalions.values():
        if battalion.faction not in {Faction.NATO, Faction.RUSSIA}:
            continue
        picks = _acceptance_combat_units(catalog, battalion.faction.value)
        if not picks:
            # Fixture catalogs may only expose simple rifle units.
            fallback = [
                unit
                for unit in catalog.by_faction(battalion.faction.value)
                if unit.materializable and "crew" not in unit.name.lower()
            ]
            picks = sorted(fallback, key=lambda unit: (-sum(unit.members.values()), unit.name))
        if not picks:
            raise ValueError(f"No fightable acceptance units found for {battalion.faction.value}")
        roster = [
            BattalionRosterEntry(picks[0].name, quantity=2, category=picks[0].category),
        ]
        for unit in picks[1:4]:
            roster.append(BattalionRosterEntry(unit.name, quantity=1, category=unit.category))
        _apply_roster(battalion, roster)


def set_player_faction(state: CampaignState, faction: Faction) -> None:
    state.selected_faction = faction
    state.current_faction = faction
    for faction_state in state.factions.values():
        faction_state.is_human_controlled = faction_state.faction == faction
    for battalion in state.battalions.values():
        battalion.is_player_controlled = battalion.faction == faction


def _apply_roster(battalion, roster: list[BattalionRosterEntry]) -> None:
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


def _acceptance_combat_units(catalog: CodeXCatalog, faction: str) -> list[UnitDefinition]:
    candidates: list[UnitDefinition] = []
    for unit in catalog.by_faction(faction):
        name = unit.name.lower()
        if not name.startswith("squad_"):
            continue
        if any(token in name for token in _ACCEPTANCE_SKIP_TOKENS):
            continue
        if not unit.materializable:
            continue
        if sum(unit.members.values()) < 4 and not unit.vehicles:
            continue
        candidates.append(unit)

    def score(unit: UnitDefinition) -> tuple:
        name = unit.name.lower()
        points = 0
        if "rifle" in name:
            points += 12
        if "mech" in name:
            points += 10
        if any(token in name for token in ("bmp", "btr", "ampv", "aavp", "m2", "bradley")):
            points += 8
        if "tank" in name or "t72" in name or "t80" in name or "t90" in name or "m1" in name:
            points += 6
        if "fireteam" in name:
            points += 4
        points += min(sum(unit.members.values()), 20)
        return (-points, unit.doctrine_cost, unit.name)

    return sorted(candidates, key=score)
