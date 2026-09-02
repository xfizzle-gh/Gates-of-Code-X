from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .diplomacy import allied_factions
from .models import CampaignState, Faction, Province
from .supply import reachable_supply_provinces


BUILDING_RULES: dict[str, dict[str, int]] = {
    "fortification": {"base_cost": 140, "max_level": 5},
    "supply_hub": {"base_cost": 240, "max_level": 2},
    "recruitment_center": {"base_cost": 220, "max_level": 2},
    "command_post": {"base_cost": 260, "max_level": 2},
}

DEFAULT_CAPITALS: dict[str, list[str]] = {
    "western-coalition": ["Sussex", "Warszawa", "Lwow"],
    "eastern-coalition": ["Minsk", "Leningrad", "province_0501"],
}

DEFAULT_OBJECTIVES: tuple[dict[str, Any], ...] = (
    {
        "id": "western-breakthrough",
        "coalition": "western-coalition",
        "display_name": "Break the Eastern Line",
        "kind": "control",
        "targets": ["Minsk", "Leningrad", "Mozyr"],
        "required": 2,
        "reward_each": 300,
        "primary": True,
    },
    {
        "id": "eastern-breakthrough",
        "coalition": "eastern-coalition",
        "display_name": "Break the Western Line",
        "kind": "control",
        "targets": ["Warszawa", "Brandenburg", "Lwow"],
        "required": 2,
        "reward_each": 300,
        "primary": True,
    },
    {
        "id": "western-logistics",
        "coalition": "western-coalition",
        "display_name": "Establish Forward Logistics",
        "kind": "infrastructure",
        "building": "supply_hub",
        "required": 2,
        "reward_each": 180,
        "primary": False,
    },
    {
        "id": "eastern-logistics",
        "coalition": "eastern-coalition",
        "display_name": "Establish Forward Logistics",
        "kind": "infrastructure",
        "building": "supply_hub",
        "required": 2,
        "reward_each": 180,
        "primary": False,
    },
    {
        "id": "western-command-network",
        "coalition": "western-coalition",
        "display_name": "Build a Command Network",
        "kind": "infrastructure",
        "building": "command_post",
        "required": 3,
        "reward_each": 200,
        "primary": False,
    },
    {
        "id": "eastern-command-network",
        "coalition": "eastern-coalition",
        "display_name": "Build a Command Network",
        "kind": "infrastructure",
        "building": "command_post",
        "required": 3,
        "reward_each": 200,
        "primary": False,
    },
)


@dataclass(frozen=True, slots=True)
class ConstructionResult:
    faction: str
    province_id: str
    building: str
    level: int
    cost: int
    resources_remaining: int


@dataclass(frozen=True, slots=True)
class CampaignOutcome:
    status: str
    winner_coalition: str = ""
    loser_coalition: str = ""
    reason: str = ""
    selected_faction_result: str = "active"
    victory_hold_rounds: int = 0


def ensure_strategic_layer(state: CampaignState) -> None:
    if "operational_objectives" not in state.map_metadata:
        state.map_metadata["operational_objectives"] = [
            {
                **objective,
                "progress": 0,
                "completed": False,
                "completed_turn": 0,
                "rewarded": False,
            }
            for objective in DEFAULT_OBJECTIVES
            if objective["coalition"] in state.alliances
        ]
    state.map_metadata.setdefault("coalition_capitals", DEFAULT_CAPITALS)
    state.map_metadata.setdefault("victory_hold_rounds", {})
    state.map_metadata.setdefault("campaign_outcome", asdict(CampaignOutcome(status="active")))
    for province in state.provinces.values():
        infrastructure_levels(province)
        sync_province_infrastructure_owner(province)
    state.schema_version = max(state.schema_version, 5)
    from .force_migration import ensure_strategic_formations

    ensure_strategic_formations(state)


def infrastructure_levels(province: Province) -> dict[str, int]:
    raw = province.metadata.setdefault("infrastructure", {})
    levels = {
        building: max(0, min(int(raw.get(building, 0)), rules["max_level"]))
        for building, rules in BUILDING_RULES.items()
    }
    province.metadata["infrastructure"] = levels
    if levels["fortification"] > province.fortification:
        province.fortification = levels["fortification"]
    return levels


def construction_cost(province: Province, building: str) -> int:
    if building not in BUILDING_RULES:
        raise KeyError(f"Unknown building: {building}")
    level = infrastructure_levels(province)[building]
    return BUILDING_RULES[building]["base_cost"] * (level + 1)


def construction_options(state: CampaignState, faction: Faction, province_id: str) -> list[dict[str, Any]]:
    ensure_strategic_layer(state)
    province = _province(state, province_id)
    reachable = reachable_supply_provinces(state, faction)
    levels = infrastructure_levels(province)
    options = []
    for building, rules in BUILDING_RULES.items():
        cost = construction_cost(province, building)
        reasons: list[str] = []
        if province.owner != faction:
            reasons.append("province_not_owned")
        if province_id not in reachable:
            reasons.append("province_not_supplied")
        if levels[building] >= rules["max_level"]:
            reasons.append("maximum_level")
        if state.factions[faction.value].resources < cost:
            reasons.append("insufficient_resources")
        options.append(
            {
                "building": building,
                "level": levels[building],
                "next_level": min(levels[building] + 1, rules["max_level"]),
                "max_level": rules["max_level"],
                "cost": cost,
                "available": not reasons,
                "blocked_reasons": reasons,
            }
        )
    return options


def build_infrastructure(
    state: CampaignState,
    faction: Faction,
    province_id: str,
    building: str,
) -> ConstructionResult:
    ensure_strategic_layer(state)
    province = _province(state, province_id)
    if building not in BUILDING_RULES:
        raise KeyError(f"Unknown building: {building}")
    if province.owner != faction:
        raise ValueError(f"Faction {faction.value} does not own {province_id}")
    if province_id not in reachable_supply_provinces(state, faction):
        raise ValueError(f"Province {province_id} is not supplied")
    levels = infrastructure_levels(province)
    rules = BUILDING_RULES[building]
    if levels[building] >= rules["max_level"]:
        raise ValueError(f"{building} is already at maximum level")
    cost = construction_cost(province, building)
    faction_state = state.factions[faction.value]
    if faction_state.resources < cost:
        raise ValueError(f"Insufficient resources: need {cost}")
    faction_state.resources -= cost
    levels[building] += 1
    province.metadata["infrastructure"] = levels
    if building == "fortification":
        province.fortification = levels[building]
    elif building == "command_post":
        base_yield = int(province.metadata.setdefault("base_resource_yield", province.resource_yield))
        province.resource_yield = base_yield + levels[building] * 5
    sync_province_infrastructure_owner(province)
    update_operational_objectives(state)
    state.validate()
    return ConstructionResult(
        faction=faction.value,
        province_id=province_id,
        building=building,
        level=levels[building],
        cost=cost,
        resources_remaining=faction_state.resources,
    )


def recruitment_discount_for_formation(state: CampaignState, formation_id: str) -> float:
    battalion = next(
        (value for value in state.battalions.values() if value.formation_id == formation_id),
        None,
    )
    if battalion is None:
        return 0.0
    province = state.provinces[battalion.province_id]
    if province.owner != battalion.faction:
        return 0.0
    level = infrastructure_levels(province)["recruitment_center"]
    return min(0.16, level * 0.08)


def sync_province_infrastructure_owner(province: Province) -> None:
    levels = infrastructure_levels(province)
    sources = {
        value
        for value in province.metadata.get("supply_source_for", [])
        if value not in {Faction.NATO.value, Faction.UKRAINE.value, Faction.RUSSIA.value, Faction.PRC.value}
    }
    if levels["supply_hub"] > 0 and province.owner != Faction.NEUTRAL:
        sources.add(province.owner.value)
    province.metadata["supply_source_for"] = sorted(sources)


def update_operational_objectives(state: CampaignState) -> list[dict[str, Any]]:
    ensure_strategic_layer(state)
    objectives = state.map_metadata["operational_objectives"]
    for objective in objectives:
        coalition = state.alliances.get(objective["coalition"])
        if coalition is None:
            continue
        coalition_factions = set(coalition.factions)
        if objective["kind"] == "control":
            progress = sum(
                1
                for province_id in objective.get("targets", [])
                if province_id in state.provinces and state.provinces[province_id].owner in coalition_factions
            )
        else:
            building = objective.get("building", "")
            progress = sum(
                infrastructure_levels(province).get(building, 0)
                for province in state.provinces.values()
                if province.owner in coalition_factions
            )
        objective["progress"] = progress
        if not objective.get("completed") and progress >= int(objective["required"]):
            objective["completed"] = True
            objective["completed_turn"] = state.turn_number
        if objective.get("completed") and not objective.get("rewarded"):
            reward = int(objective.get("reward_each", 0))
            for faction in coalition.factions:
                faction_state = state.factions.get(faction.value)
                if faction_state is not None and not faction_state.is_eliminated:
                    faction_state.resources += reward
            objective["rewarded"] = True
    return objectives


def evaluate_campaign_outcome(state: CampaignState, *, advance_hold: bool = False) -> CampaignOutcome:
    ensure_strategic_layer(state)
    update_operational_objectives(state)
    _update_eliminations(state)
    alliance_ids = sorted(state.alliances)
    winner = ""
    loser = ""
    reason = ""
    hold_rounds = 0

    for alliance_id in alliance_ids:
        opponents = [value for value in alliance_ids if value != alliance_id]
        if not opponents:
            continue
        opposing_id = opponents[0]
        opposing = state.alliances[opposing_id]
        if all(state.factions[faction.value].is_eliminated for faction in opposing.factions):
            winner, loser, reason = alliance_id, opposing_id, "opposing coalition eliminated"
            break

    living = [
        faction_id
        for faction_id, faction_state in state.factions.items()
        if not faction_state.is_eliminated
    ]
    if not winner and len(living) <= 1:
        winner, loser, reason = (living[0] if living else ""), "", "last faction standing"

    if not winner and len(alliance_ids) >= 2:
        holds = state.map_metadata.setdefault("victory_hold_rounds", {})
        capitals = state.map_metadata.get("coalition_capitals", DEFAULT_CAPITALS)
        objectives = state.map_metadata["operational_objectives"]
        for alliance_id in alliance_ids:
            opposing_id = next(value for value in alliance_ids if value != alliance_id)
            alliance_factions = set(state.alliances[alliance_id].factions)
            targets = [value for value in capitals.get(opposing_id, []) if value in state.provinces]
            controlled = sum(state.provinces[target].owner in alliance_factions for target in targets)
            primary_complete = any(
                objective.get("coalition") == alliance_id
                and objective.get("primary")
                and objective.get("completed")
                for objective in objectives
            )
            threshold = max(1, min(2, len(targets)))
            qualifies = primary_complete and controlled >= threshold
            current = int(holds.get(alliance_id, 0))
            if advance_hold:
                current = current + 1 if qualifies else 0
                holds[alliance_id] = current
            elif not qualifies:
                current = 0
            if qualifies and current >= 2:
                winner, loser = alliance_id, opposing_id
                reason = "held enemy strategic capitals after completing the primary operation"
                hold_rounds = current
                break
            hold_rounds = max(hold_rounds, current)

    status = "complete" if winner else "active"
    selected_alliance = coalition_for_faction(state, state.selected_faction)
    selected_result = "active"
    if winner:
        selected_result = "victory" if selected_alliance == winner else "defeat"
    outcome = CampaignOutcome(
        status=status,
        winner_coalition=winner,
        loser_coalition=loser,
        reason=reason,
        selected_faction_result=selected_result,
        victory_hold_rounds=hold_rounds,
    )
    state.map_metadata["campaign_outcome"] = asdict(outcome)
    return outcome


def coalition_for_faction(state: CampaignState, faction: Faction) -> str:
    for alliance_id, alliance in state.alliances.items():
        if faction in alliance.factions:
            return alliance_id
    return ""


def run_ai_construction(state: CampaignState, faction: Faction) -> dict[str, Any] | None:
    ensure_strategic_layer(state)
    owned = [province for province in state.provinces.values() if province.owner == faction]
    supplied = reachable_supply_provinces(state, faction)
    candidates = [province for province in owned if province.province_id in supplied]
    if not candidates:
        return None

    front = [
        province
        for province in candidates
        if any(state.provinces[neighbor].owner not in allied_factions(state, faction) for neighbor in province.neighbors)
    ]
    priorities: list[tuple[str, Province]] = []
    if front:
        priorities.append(("fortification", min(front, key=lambda value: (value.fortification, value.province_id))))
    formation_provinces = [
        state.provinces[battalion.province_id]
        for battalion in state.battalions.values()
        if battalion.faction == faction and battalion.province_id in supplied
    ]
    if formation_provinces:
        priorities.append(
            (
                "recruitment_center",
                min(
                    formation_provinces,
                    key=lambda value: (infrastructure_levels(value)["recruitment_center"], value.province_id),
                ),
            )
        )
    priorities.append(
        (
            "supply_hub",
            min(candidates, key=lambda value: (infrastructure_levels(value)["supply_hub"], -len(value.neighbors), value.province_id)),
        )
    )
    priorities.append(
        (
            "command_post",
            max(candidates, key=lambda value: (value.resource_yield, -infrastructure_levels(value)["command_post"], value.province_id)),
        )
    )

    for building, province in priorities:
        option = next(value for value in construction_options(state, faction, province.province_id) if value["building"] == building)
        if not option["available"]:
            continue
        if option["cost"] > state.factions[faction.value].resources // 2:
            continue
        result = build_infrastructure(state, faction, province.province_id, building)
        return {"action": "construct", **asdict(result)}
    return None


def _update_eliminations(state: CampaignState) -> None:
    for faction_id, faction_state in state.factions.items():
        faction = Faction(faction_id)
        has_battalion = any(value.faction == faction for value in state.battalions.values())
        has_territory = any(value.owner == faction for value in state.provinces.values())
        faction_state.is_eliminated = not has_battalion and not has_territory


def _province(state: CampaignState, province_id: str) -> Province:
    province = state.provinces.get(province_id)
    if province is None:
        raise KeyError(f"Unknown province: {province_id}")
    return province
