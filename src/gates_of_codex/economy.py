from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass

from .codex.catalog import CodeXCatalog, UnitDefinition
from .models import (
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    ReinforcementPoolEntry,
    ResearchNode,
    UnitEconomy,
)


CATEGORY_COSTS = {
    "infantry": 0,
    "unknown": 0,
    "recon": 140,
    "vehicle": 160,
    "ifv": 240,
    "tank": 320,
    "artillery": 220,
    "air_defense": 220,
}
CATEGORY_PREREQUISITES = {
    "infantry": None,
    "unknown": None,
    "recon": "infantry",
    "vehicle": "infantry",
    "ifv": "vehicle",
    "tank": "ifv",
    "artillery": "infantry",
    "air_defense": "infantry",
}
CATEGORY_PURCHASE_BASE = {
    "infantry": 70,
    "unknown": 90,
    "recon": 120,
    "vehicle": 190,
    "ifv": 260,
    "tank": 360,
    "artillery": 280,
    "air_defense": 260,
}


@dataclass(frozen=True, slots=True)
class RecruitmentOffer:
    formation_id: str
    unit_name: str
    category: str
    purchase_cost: int
    maintenance_cost: int
    research_keys: tuple[str, ...]
    missing_research: tuple[str, ...]
    unlocked: bool
    preferred: bool
    doctrine: str = ""
    infrastructure_discount: float = 0.0


@dataclass(frozen=True, slots=True)
class ResearchPurchase:
    faction: str
    key: str
    cost: int
    resources_remaining: int


@dataclass(frozen=True, slots=True)
class ReinforcementTransfer:
    formation_id: str
    unit_name: str
    quantity: int
    replacements: int
    expansion: int
    pool_remaining: int


@dataclass(frozen=True, slots=True)
class RepairResult:
    formation_id: str
    points_repaired: int
    cost: int
    condition: int
    resources_remaining: int


@dataclass(frozen=True, slots=True)
class RoundEconomyReport:
    faction: str
    income: int
    maintenance_due: int
    maintenance_paid: int
    shortfall: int
    resources_remaining: int


def initialize_economy(state: CampaignState, catalog: CodeXCatalog) -> None:
    state.catalog_signature = catalog.signature
    state.research_nodes = build_research_nodes(catalog)
    state.unit_economy = build_unit_economy(catalog)
    for faction_id, faction_state in state.factions.items():
        core_key = category_research_key(Faction(faction_id), "infantry")
        if core_key not in faction_state.researched_keys:
            faction_state.researched_keys.append(core_key)
    for battalion in state.battalions.values():
        if not battalion.authorized_roster:
            battalion.authorized_roster = [_copy_roster_entry(entry) for entry in battalion.roster]
        faction_state = state.factions[battalion.faction.value]
        for entry in battalion.roster:
            economy = state.unit_economy.get(entry.unit_name)
            if economy is None:
                continue
            for key in economy.research_keys:
                _grant_with_prerequisites(state, faction_state.researched_keys, key)
    for faction_state in state.factions.values():
        faction_state.researched_keys = sorted(set(faction_state.researched_keys))
    state.schema_version = max(state.schema_version, 4)
    state.validate()


def build_research_nodes(catalog: CodeXCatalog) -> dict[str, ResearchNode]:
    nodes: dict[str, ResearchNode] = {}
    factions = sorted({unit.side for unit in catalog.units.values() if unit.side in {"nato", "ukr", "rusa", "prc"}})
    for faction_id in factions:
        faction = Faction(faction_id)
        for category, cost in CATEGORY_COSTS.items():
            key = category_research_key(faction, category)
            prerequisite_category = CATEGORY_PREREQUISITES[category]
            prerequisites = [category_research_key(faction, prerequisite_category)] if prerequisite_category else []
            display = "Core Forces" if category in {"infantry", "unknown"} else category.replace("_", " ").title()
            nodes[key] = ResearchNode(
                key=key,
                faction=faction,
                display_name=display,
                cost=cost,
                prerequisites=prerequisites,
                unlock_categories=[category],
                source="Code:X catalog category",
            )
        doctrines = sorted({unit.doctrine for unit in catalog.by_faction(faction_id) if unit.doctrine})
        for doctrine in doctrines:
            matching = [unit for unit in catalog.by_faction(faction_id) if unit.doctrine == doctrine]
            key = doctrine_research_key(faction, doctrine)
            doctrine_cost = max((unit.doctrine_cost for unit in matching), default=0)
            nodes[key] = ResearchNode(
                key=key,
                faction=faction,
                display_name=_display_doctrine(doctrine),
                cost=max(140, 140 + doctrine_cost * 35),
                prerequisites=[category_research_key(faction, "infantry")],
                unlock_doctrines=[doctrine],
                unlock_units=sorted(unit.name for unit in matching),
                source="Code:X Lua doctrine metadata",
            )
    return nodes


def build_unit_economy(catalog: CodeXCatalog) -> dict[str, UnitEconomy]:
    values: dict[str, UnitEconomy] = {}
    for unit in catalog.units.values():
        if unit.side not in {"nato", "ukr", "rusa", "prc"}:
            continue
        faction = Faction(unit.side)
        category = unit.category if unit.category in CATEGORY_PURCHASE_BASE else "unknown"
        purchase = (
            CATEGORY_PURCHASE_BASE[category]
            + unit.manpower_estimate * 18
            + len(unit.vehicles) * 55
            + unit.doctrine_cost * 30
        )
        purchase = max(50, int(math.ceil(purchase / 5.0) * 5))
        keys = [category_research_key(faction, category)]
        if unit.doctrine:
            keys.append(doctrine_research_key(faction, unit.doctrine))
        values[unit.name] = UnitEconomy(
            unit_name=unit.name,
            faction=faction,
            category=category,
            purchase_cost=purchase,
            maintenance_cost=max(2, math.ceil(purchase * 0.035)),
            repair_cost_per_point=max(1, math.ceil(purchase * 0.0025)),
            research_keys=keys,
            doctrine=unit.doctrine,
            manpower_estimate=unit.manpower_estimate,
        )
    return values


def category_research_key(faction: Faction, category: str) -> str:
    normalized = "infantry" if category == "unknown" else category
    return f"codex:{faction.value}:category:{normalized}"


def doctrine_research_key(faction: Faction, doctrine: str) -> str:
    return f"codex:{faction.value}:doctrine:{_slug(doctrine)}"


def available_research(state: CampaignState, faction: Faction) -> list[ResearchNode]:
    faction_state = state.factions[faction.value]
    researched = set(faction_state.researched_keys)
    return sorted(
        (
            node
            for node in state.research_nodes.values()
            if node.faction == faction
            and node.key not in researched
            and set(node.prerequisites).issubset(researched)
        ),
        key=lambda node: (node.cost, node.key),
    )


def purchase_research(state: CampaignState, faction: Faction, key: str) -> ResearchPurchase:
    node = state.research_nodes.get(key)
    if node is None:
        raise KeyError(f"Unknown research key: {key}")
    if node.faction != faction:
        raise ValueError(f"Research {key} belongs to {node.faction.value}, not {faction.value}")
    faction_state = state.factions[faction.value]
    if key in faction_state.researched_keys:
        raise ValueError(f"Research already completed: {key}")
    missing = sorted(set(node.prerequisites) - set(faction_state.researched_keys))
    if missing:
        raise ValueError(f"Research prerequisites not met for {key}: {', '.join(missing)}")
    if faction_state.resources < node.cost:
        raise ValueError(f"Insufficient resources for {key}: need {node.cost}")
    faction_state.resources -= node.cost
    faction_state.researched_keys.append(key)
    faction_state.researched_keys = sorted(set(faction_state.researched_keys))
    state.validate()
    return ResearchPurchase(faction.value, key, node.cost, faction_state.resources)


def formation_recruitment_offers(state: CampaignState, formation_id: str) -> list[RecruitmentOffer]:
    formation = state.formations.get(formation_id)
    if formation is None:
        raise KeyError(f"Unknown formation: {formation_id}")
    faction_state = state.factions[formation.faction.value]
    researched = set(faction_state.researched_keys)
    allowed_categories = set(formation.preferred_categories) | {"infantry", "unknown"}
    candidates = [
        economy
        for economy in state.unit_economy.values()
        if economy.faction == formation.faction and economy.category in allowed_categories
    ]
    if not candidates:
        candidates = [economy for economy in state.unit_economy.values() if economy.faction == formation.faction]
    from .strategic import recruitment_discount_for_formation

    discount = recruitment_discount_for_formation(state, formation_id)
    offers = []
    for economy in candidates:
        missing = tuple(sorted(set(economy.research_keys) - researched))
        discounted_cost = max(1, int(math.ceil(economy.purchase_cost * (1.0 - discount) / 5.0) * 5))
        offers.append(
            RecruitmentOffer(
                formation_id=formation_id,
                unit_name=economy.unit_name,
                category=economy.category,
                purchase_cost=discounted_cost,
                maintenance_cost=economy.maintenance_cost,
                research_keys=tuple(economy.research_keys),
                missing_research=missing,
                unlocked=not missing,
                preferred=economy.category in formation.preferred_categories,
                doctrine=economy.doctrine,
                infrastructure_discount=discount,
            )
        )
    return sorted(offers, key=lambda offer: (not offer.unlocked, not offer.preferred, offer.purchase_cost, offer.unit_name))


def purchase_reinforcements(
    state: CampaignState,
    formation_id: str,
    unit_name: str,
    quantity: int = 1,
) -> ReinforcementPoolEntry:
    if quantity < 1:
        raise ValueError("Reinforcement quantity must be positive")
    formation = state.formations.get(formation_id)
    if formation is None:
        raise KeyError(f"Unknown formation: {formation_id}")
    offer = next((value for value in formation_recruitment_offers(state, formation_id) if value.unit_name == unit_name), None)
    if offer is None:
        raise ValueError(f"Unit {unit_name} is outside formation {formation_id}'s recruitment pool")
    if not offer.unlocked:
        raise ValueError(f"Unit {unit_name} requires research: {', '.join(offer.missing_research)}")
    faction_state = state.factions[formation.faction.value]
    total_cost = offer.purchase_cost * quantity
    if faction_state.resources < total_cost:
        raise ValueError(f"Insufficient resources: need {total_cost}")
    faction_state.resources -= total_cost
    existing = next(
        (
            entry
            for entry in faction_state.reinforcement_pool
            if entry.formation_id == formation_id and entry.unit_name == unit_name
        ),
        None,
    )
    if existing is None:
        existing = ReinforcementPoolEntry(
            unit_name=unit_name,
            quantity=quantity,
            category=offer.category,
            formation_id=formation_id,
            unit_cost=offer.purchase_cost,
        )
        faction_state.reinforcement_pool.append(existing)
    else:
        existing.quantity += quantity
    state.validate()
    return existing


def assign_reinforcements(
    state: CampaignState,
    formation_id: str,
    unit_name: str,
    quantity: int = 1,
) -> ReinforcementTransfer:
    if quantity < 1:
        raise ValueError("Transfer quantity must be positive")
    formation = state.formations.get(formation_id)
    if formation is None:
        raise KeyError(f"Unknown formation: {formation_id}")
    battalion = _formation_battalion(state, formation_id)
    faction_state = state.factions[formation.faction.value]
    pool_entry = next(
        (
            entry
            for entry in faction_state.reinforcement_pool
            if entry.formation_id == formation_id and entry.unit_name == unit_name
        ),
        None,
    )
    if pool_entry is None or pool_entry.quantity < quantity:
        available = pool_entry.quantity if pool_entry else 0
        raise ValueError(f"Only {available} {unit_name} reinforcement(s) available")
    current = _entry_quantity(battalion.roster, unit_name)
    authorized = _entry_quantity(battalion.authorized_roster, unit_name)
    replacements = min(quantity, max(0, authorized - current))
    expansion = quantity - replacements
    _add_roster_quantity(battalion.roster, unit_name, pool_entry.category, quantity)
    if expansion:
        _add_roster_quantity(battalion.authorized_roster, unit_name, pool_entry.category, expansion)
    pool_entry.quantity -= quantity
    if pool_entry.quantity == 0:
        faction_state.reinforcement_pool.remove(pool_entry)
    state.validate()
    return ReinforcementTransfer(
        formation_id=formation_id,
        unit_name=unit_name,
        quantity=quantity,
        replacements=replacements,
        expansion=expansion,
        pool_remaining=pool_entry.quantity,
    )


def repair_formation(state: CampaignState, formation_id: str, points: int | None = None) -> RepairResult:
    battalion = _formation_battalion(state, formation_id)
    if battalion.condition >= 100:
        return RepairResult(formation_id, 0, 0, 100, state.factions[battalion.faction.value].resources)
    if battalion.supply < 50 or battalion.encircled_turns > 0:
        raise ValueError(f"Formation {formation_id} must be supplied to repair")
    faction_state = state.factions[battalion.faction.value]
    cost_per_point = max(
        1,
        sum(
            state.unit_economy.get(entry.unit_name, UnitEconomy(entry.unit_name, battalion.faction, entry.category, 0, 0, 1)).repair_cost_per_point
            * entry.quantity
            for entry in battalion.roster
        ),
    )
    from .site_upgrade import apply_forward_depot_repair_cost

    cost_per_point = apply_forward_depot_repair_cost(state, battalion.province_id, cost_per_point)
    missing = 100 - battalion.condition
    requested = missing if points is None else min(missing, max(0, points))
    if requested == 0:
        return RepairResult(formation_id, 0, 0, battalion.condition, faction_state.resources)
    affordable = faction_state.resources // cost_per_point
    repaired = min(requested, affordable)
    if points is not None and repaired < requested:
        raise ValueError(f"Insufficient resources to repair {requested} points")
    if repaired <= 0:
        raise ValueError("Insufficient resources to repair formation")
    cost = repaired * cost_per_point
    faction_state.resources -= cost
    battalion.condition += repaired
    state.validate()
    return RepairResult(formation_id, repaired, cost, battalion.condition, faction_state.resources)


def settle_round_economy(state: CampaignState) -> list[RoundEconomyReport]:
    if "actor_content_runtime" in state.map_metadata:
        from .actor_economy import settle_actor_round_economy

        return settle_actor_round_economy(state)  # type: ignore[return-value]

    reports: list[RoundEconomyReport] = []
    for faction_id, faction_state in sorted(state.factions.items()):
        faction = Faction(faction_id)
        income = sum(province.resource_yield for province in state.provinces.values() if province.owner == faction)
        maintenance = 0
        faction_battalions = [battalion for battalion in state.battalions.values() if battalion.faction == faction]
        for battalion in faction_battalions:
            for entry in battalion.roster:
                economy = state.unit_economy.get(entry.unit_name)
                maintenance += (economy.maintenance_cost if economy else 2) * entry.quantity
        faction_state.resources += income
        paid = min(faction_state.resources, maintenance)
        faction_state.resources -= paid
        shortfall = maintenance - paid
        faction_state.income_last_round = income
        faction_state.maintenance_last_round = paid
        if shortfall:
            for battalion in faction_battalions:
                battalion.condition = max(25, battalion.condition - 5)
        reports.append(
            RoundEconomyReport(
                faction=faction_id,
                income=income,
                maintenance_due=maintenance,
                maintenance_paid=paid,
                shortfall=shortfall,
                resources_remaining=faction_state.resources,
            )
        )
    state.map_metadata["last_round_economy"] = [asdict(report) for report in reports]
    state.validate()
    return reports


def run_ai_economy(state: CampaignState, faction: Faction) -> list[dict]:
    if "actor_content_runtime" in state.map_metadata:
        from .actor_ai_economy import run_actor_ai_economy

        return run_actor_ai_economy(state, faction)

    actions: list[dict] = []
    faction_state = state.factions[faction.value]
    research = available_research(state, faction)
    if research:
        candidate = min(research, key=lambda node: (node.cost, node.key))
        if candidate.cost <= max(0, faction_state.resources // 2):
            result = purchase_research(state, faction, candidate.key)
            actions.append({"action": "research", **asdict(result)})
    battalions = sorted(
        (battalion for battalion in state.battalions.values() if battalion.faction == faction),
        key=lambda battalion: (battalion.condition, battalion.unit_count, battalion.battalion_id),
    )
    if battalions and battalions[0].condition < 85:
        try:
            result = repair_formation(state, battalions[0].formation_id)
            if result.points_repaired:
                actions.append({"action": "repair", **asdict(result)})
        except ValueError:
            pass
    if battalions:
        target = min(battalions, key=lambda battalion: (battalion.unit_count, battalion.battalion_id))
        offers = [offer for offer in formation_recruitment_offers(state, target.formation_id) if offer.unlocked]
        offers.sort(key=lambda offer: (not offer.preferred, offer.purchase_cost, offer.unit_name))
        if offers and offers[0].purchase_cost <= faction_state.resources:
            pool = purchase_reinforcements(state, target.formation_id, offers[0].unit_name, 1)
            transfer = assign_reinforcements(state, target.formation_id, offers[0].unit_name, 1)
            actions.append(
                {
                    "action": "recruit",
                    "formation_id": target.formation_id,
                    "unit_name": offers[0].unit_name,
                    "cost": pool.unit_cost,
                    "resources_remaining": faction_state.resources,
                    "transfer": asdict(transfer),
                }
            )
    return actions


def _grant_with_prerequisites(state: CampaignState, researched: list[str], key: str) -> None:
    node = state.research_nodes.get(key)
    if node is None:
        return
    for prerequisite in node.prerequisites:
        _grant_with_prerequisites(state, researched, prerequisite)
    researched.append(key)


def _formation_battalion(state: CampaignState, formation_id: str) -> Battalion:
    battalion = next(
        (value for value in state.battalions.values() if value.formation_id == formation_id),
        None,
    )
    if battalion is None:
        raise ValueError(f"Formation {formation_id} has no active battalion")
    return battalion


def _entry_quantity(roster: list[BattalionRosterEntry], unit_name: str) -> int:
    return sum(entry.quantity for entry in roster if entry.unit_name == unit_name)


def _add_roster_quantity(
    roster: list[BattalionRosterEntry],
    unit_name: str,
    category: str,
    quantity: int,
) -> None:
    entry = next((value for value in roster if value.unit_name == unit_name), None)
    if entry is None:
        roster.append(BattalionRosterEntry(unit_name, quantity=quantity, category=category))
    else:
        entry.quantity += quantity


def _copy_roster_entry(entry: BattalionRosterEntry) -> BattalionRosterEntry:
    return BattalionRosterEntry(
        entry.unit_name,
        quantity=entry.quantity,
        stage=entry.stage,
        category=entry.category,
        preserved_objects=list(entry.preserved_objects),
    )


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "doctrine"


def _display_doctrine(value: str) -> str:
    return re.sub(r"[_\-.]+", " ", value).strip().title() or "Doctrine"
