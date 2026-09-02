from __future__ import annotations

from .codex.catalog import CodeXCatalog, UnitDefinition
from .models import BattalionRosterEntry, CampaignState, Faction


PREFERRED_CATEGORIES = ("infantry", "tank", "ifv", "vehicle", "artillery", "recon", "air_defense")
PREFERRED_SQUADS = {
    "nato": (
        "squad_inf2_rifle(nato)",
        "squad_usmc_rifle(nato)",
        "squad_usmc_eng(nato)",
    ),
    "rusa": (
        "rus90_inf_rifle(rusa)",
        "rus90_inf_assault(rusa)",
        "rus90_inf_mg(rusa)",
    ),
    "ukr": (
        "47th_inf_rifle(ukr)",
        "ter_22_1(ukr)",
    ),
    "prc": (
        "squad_pla112_rifle(prc)",
    ),
}
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
        infantry = _preferred_squad(catalog, battalion.faction.value) or _pick(units, "infantry") or units[0]
        roster = [BattalionRosterEntry(infantry.name, quantity=1, category=infantry.category)]
        _apply_roster(battalion, roster)


def populate_acceptance_combat_rosters(state: CampaignState, catalog: CodeXCatalog) -> None:
    """Build fightable NATO/Russia acceptance rosters from Code:X squad_* entries."""

    for battalion in state.battalions.values():
        if battalion.faction not in {Faction.NATO, Faction.RUSSIA}:
            continue
        preferred = _preferred_squad(catalog, battalion.faction.value)
        picks = [preferred] if preferred is not None else _acceptance_combat_units(catalog, battalion.faction.value)
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
            BattalionRosterEntry(picks[0].name, quantity=1, category=picks[0].category),
        ]
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


def _preferred_squad(catalog: CodeXCatalog, faction: str) -> UnitDefinition | None:
    for name in PREFERRED_SQUADS.get(faction, ()):
        unit = catalog.units.get(name)
        if unit is not None and unit.materializable and unit.members:
            return unit
    return None


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
