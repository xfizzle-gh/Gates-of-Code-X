"""Bounded P10 military site-upgrade: one Forward Depot family.

This is not the #65 city-builder. It adds one player-facing infrastructure
verb that matters to the Auto-Resolve loop: a Forward Depot bought from the
acting actor treasury, limited to one slot per province, completed after two
weekly turns, and lost when the province changes owner.

Documented v1 contract
----------------------
upgrade_id: ``forward_depot``
display name: Forward Depot
treasury cost: 400 from the acting actor (#149), or the owning faction when
    no actor runtime is installed
slot cap: 1 per province
build time: 2 weekly turns (advanced when ``CampaignState.turn_number``
    increments at the end of a full faction cycle)
effect when complete:
    - repair cost in that province is halved (integer, minimum 1)
    - weekly supply restore in that province gains +10
ownership: fail-closed; the acting actor must own the province
supply: owned province must be supply-connected, except Earth3 P2 while
    supply connectivity is disabled, which requires the P2 footprint instead
capture: records are destroyed on owner change (no transfer)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .models import CampaignState, Faction, Province
from .strategic_actors import ACTOR_RUNTIME_KEY, ensure_strategic_actor_runtime
from .supply import reachable_supply_provinces


FORWARD_DEPOT_ID = "forward_depot"
FORWARD_DEPOT_DISPLAY_NAME = "Forward Depot"
FORWARD_DEPOT_COST = 400
FORWARD_DEPOT_BUILD_TURNS = 2
FORWARD_DEPOT_SLOT_CAP = 1
FORWARD_DEPOT_REPAIR_COST_NUMERATOR = 1
FORWARD_DEPOT_REPAIR_COST_DENOMINATOR = 2
FORWARD_DEPOT_SUPPLY_BONUS = 10
FORWARD_DEPOT_EFFECT_ID = "repair_cost_half_and_supply_restore_plus_10"

SITE_UPGRADE_KEY = "site_upgrades"
SITE_UPGRADE_RECORD_KEYS = (
    "upgrade_id",
    "status",
    "turns_remaining",
    "owner_actor_id",
    "owner_faction",
    "started_turn",
)
SITE_UPGRADE_STATUSES = frozenset({"building", "complete"})
KNOWN_UPGRADE_IDS = frozenset({FORWARD_DEPOT_ID})


@dataclass(frozen=True, slots=True)
class SiteUpgradeResult:
    province_id: str
    upgrade_id: str
    status: str
    turns_remaining: int
    cost: int
    actor_id: str
    faction: str
    resources_remaining: int


def province_site_upgrades(province: Province) -> list[dict[str, Any]]:
    """Return canonical upgrade records, or raise on malformed authority."""

    raw = province.metadata.get(SITE_UPGRADE_KEY)
    if raw is None:
        return []
    return [_canonical_record(item, province_id=province.province_id) for item in _require_record_list(raw, province.province_id)]


def province_has_completed_forward_depot(state: CampaignState, province_id: str) -> bool:
    """Read-only effect query. Never mutates ``province.metadata.site_upgrades``."""

    province = state.provinces.get(province_id)
    if province is None:
        return False
    return any(
        record["upgrade_id"] == FORWARD_DEPOT_ID
        and record["status"] == "complete"
        and _upgrade_matches_province_owner(province, record)
        for record in province_site_upgrades(province)
    )


def apply_forward_depot_repair_cost(state: CampaignState, province_id: str, cost_per_point: int) -> int:
    if cost_per_point < 1 or not province_has_completed_forward_depot(state, province_id):
        return cost_per_point
    return max(
        1,
        (cost_per_point * FORWARD_DEPOT_REPAIR_COST_NUMERATOR)
        // FORWARD_DEPOT_REPAIR_COST_DENOMINATOR,
    )


def forward_depot_supply_restore_bonus(state: CampaignState, province_id: str) -> int:
    if not province_has_completed_forward_depot(state, province_id):
        return 0
    return FORWARD_DEPOT_SUPPLY_BONUS


def site_upgrade_blocked_reasons(
    state: CampaignState,
    province_id: str,
    *,
    faction: Faction,
    actor_id: str | None = None,
    upgrade_id: str = FORWARD_DEPOT_ID,
    reachable: set[str] | None = None,
) -> list[str]:
    reasons: list[str] = []
    province = state.provinces.get(province_id)
    if province is None:
        return ["unknown_province"]
    if upgrade_id not in KNOWN_UPGRADE_IDS:
        reasons.append("unknown_upgrade")
        return reasons
    from .earth3_bootstrap import earth3_p2_footprint, is_earth3_p2_campaign

    if is_earth3_p2_campaign(state) and province_id not in earth3_p2_footprint(state):
        reasons.append("outside_scenario_footprint")
    if province.owner != faction:
        reasons.append("province_not_owned")
    actor_runtime = _actor_runtime_installed(state)
    if actor_runtime:
        requested = _requested_actor_id(state, actor_id)
        owner_actor = str(province.metadata.get("owner_actor_id") or "")
        if not requested:
            reasons.append("acting_actor_required")
        elif owner_actor != requested:
            reasons.append("province_not_owned_by_actor")
    supplied = _province_is_supply_eligible(state, province_id, faction, reachable=reachable)
    if not supplied:
        reasons.append("province_not_supplied")
    records = province_site_upgrades(province)
    if len(records) >= FORWARD_DEPOT_SLOT_CAP:
        reasons.append("slot_full")
    if any(record["upgrade_id"] == upgrade_id for record in records):
        reasons.append("upgrade_already_present")
    available = _available_resources(state, faction=faction, actor_id=actor_id)
    if available < FORWARD_DEPOT_COST:
        reasons.append("insufficient_resources")
    return reasons


def hidden_site_upgrade_projection() -> dict[str, Any]:
    """Fog-safe presentation: no status, no availability, no owner details."""

    return _hidden_projection()


def project_site_upgrade(
    state: CampaignState,
    province: Province,
    faction: Faction,
    *,
    actor_id: str | None = None,
    reachable: set[str] | None = None,
    reveal: bool = True,
) -> dict[str, Any]:
    """Presentation projection. Never mutates campaign authority."""

    if not reveal:
        return _hidden_projection()
    records = [
        item
        for item in province_site_upgrades(province)
        if _upgrade_matches_province_owner(province, item)
    ]
    record = next((item for item in records if item["upgrade_id"] == FORWARD_DEPOT_ID), None)
    reasons = site_upgrade_blocked_reasons(
        state,
        province.province_id,
        faction=faction,
        actor_id=actor_id,
        reachable=reachable,
    )
    status = "none" if record is None else str(record["status"])
    return {
        "upgrade_id": FORWARD_DEPOT_ID,
        "display_name": FORWARD_DEPOT_DISPLAY_NAME,
        "status": status,
        "turns_remaining": 0 if record is None else int(record["turns_remaining"]),
        "slot_cap": FORWARD_DEPOT_SLOT_CAP,
        "slot_used": len(records),
        "cost": FORWARD_DEPOT_COST,
        "build_time_turns": FORWARD_DEPOT_BUILD_TURNS,
        "available": not reasons,
        "effect": FORWARD_DEPOT_EFFECT_ID,
    }


def start_site_upgrade(
    state: CampaignState,
    province_id: str,
    *,
    upgrade_id: str = FORWARD_DEPOT_ID,
    faction: Faction | None = None,
    actor_id: str | None = None,
) -> SiteUpgradeResult:
    acting_faction = faction or state.selected_faction
    if upgrade_id not in KNOWN_UPGRADE_IDS:
        raise ValueError(f"Unknown site upgrade: {upgrade_id}")
    province = state.provinces.get(province_id)
    if province is None:
        raise KeyError(f"Unknown province: {province_id}")
    from .earth3_bootstrap import require_earth3_p2_actionable

    require_earth3_p2_actionable(state, province_id, action="site_upgrade")
    acting_actor = _require_acting_owner(state, province, acting_faction, actor_id)
    if not _province_is_supply_eligible(state, province_id, acting_faction):
        raise ValueError(f"Province {province_id} is not supplied")
    records = province_site_upgrades(province)
    if len(records) >= FORWARD_DEPOT_SLOT_CAP:
        raise ValueError(f"Province {province_id} has no free site-upgrade slots")
    if any(record["upgrade_id"] == upgrade_id for record in records):
        raise ValueError(f"{upgrade_id} is already present on {province_id}")
    remaining = _debit_treasury(state, actor_id=acting_actor, faction=acting_faction, cost=FORWARD_DEPOT_COST)
    record = {
        "upgrade_id": upgrade_id,
        "status": "building",
        "turns_remaining": FORWARD_DEPOT_BUILD_TURNS,
        "owner_actor_id": acting_actor,
        "owner_faction": acting_faction.value,
        "started_turn": int(state.turn_number),
    }
    _write_records(province, [*records, record])
    state.validate()
    return SiteUpgradeResult(
        province_id=province_id,
        upgrade_id=upgrade_id,
        status="building",
        turns_remaining=FORWARD_DEPOT_BUILD_TURNS,
        cost=FORWARD_DEPOT_COST,
        actor_id=acting_actor,
        faction=acting_faction.value,
        resources_remaining=remaining,
    )


def advance_site_upgrades(state: CampaignState) -> list[dict[str, Any]]:
    """Advance every building project by one weekly turn. Completes at zero."""

    completed: list[dict[str, Any]] = []
    for province in sorted(state.provinces.values(), key=lambda value: value.province_id):
        raw = province.metadata.get(SITE_UPGRADE_KEY)
        if raw is None:
            continue
        records = province_site_upgrades(province)
        changed = False
        next_records: list[dict[str, Any]] = []
        for record in records:
            if not _upgrade_matches_province_owner(province, record):
                next_records.append(record)
                continue
            if record["status"] != "building":
                next_records.append(record)
                continue
            remaining = int(record["turns_remaining"]) - 1
            if remaining > 0:
                updated = dict(record)
                updated["turns_remaining"] = remaining
                next_records.append(updated)
                changed = True
                continue
            updated = dict(record)
            updated["status"] = "complete"
            updated["turns_remaining"] = 0
            next_records.append(updated)
            changed = True
            completed.append(
                {
                    "province_id": province.province_id,
                    "upgrade_id": updated["upgrade_id"],
                    "status": "complete",
                }
            )
        if changed:
            _write_records(province, next_records)
    return completed


def sync_site_upgrades_on_owner_change(province: Province) -> None:
    """Fail-closed: upgrades are lost when the province owner changes."""

    _drop_upgrades_if_owner_changed(province)


def run_ai_site_upgrade(state: CampaignState, faction: Faction) -> dict[str, Any] | None:
    """Issue the same ``start_site_upgrade`` command the player uses."""

    owned = [
        province
        for province in state.provinces.values()
        if province.owner == faction
    ]
    if not owned:
        return None
    reachable = reachable_supply_provinces(state, faction)
    if _actor_runtime_installed(state):
        actors = ensure_strategic_actor_runtime(state)
        actor_ids = sorted(
            actor.actor_id
            for actor in actors.values()
            if actor.tactical_side.campaign_faction() == faction and not actor.is_eliminated
        )
        for actor_id in actor_ids:
            actor = actors[actor_id]
            if actor.resources < FORWARD_DEPOT_COST or FORWARD_DEPOT_COST > actor.resources // 2:
                continue
            candidates = [
                province
                for province in owned
                if str(province.metadata.get("owner_actor_id") or "") == actor_id
            ]
            chosen = _choose_ai_province(state, faction, candidates, reachable)
            if chosen is None:
                continue
            result = start_site_upgrade(
                state,
                chosen.province_id,
                faction=faction,
                actor_id=actor_id,
            )
            return {"action": "upgrade_site", **asdict(result)}
        return None
    if state.factions[faction.value].resources < FORWARD_DEPOT_COST:
        return None
    if FORWARD_DEPOT_COST > state.factions[faction.value].resources // 2:
        return None
    chosen = _choose_ai_province(state, faction, owned, reachable)
    if chosen is None:
        return None
    result = start_site_upgrade(state, chosen.province_id, faction=faction)
    return {"action": "upgrade_site", **asdict(result)}


def validate_province_site_upgrades(province: Province) -> None:
    raw = province.metadata.get(SITE_UPGRADE_KEY)
    if raw is None:
        return
    records = [_canonical_record(item, province_id=province.province_id) for item in _require_record_list(raw, province.province_id)]
    if len(records) > FORWARD_DEPOT_SLOT_CAP:
        raise ValueError(f"Province {province.province_id} exceeds site-upgrade slot cap {FORWARD_DEPOT_SLOT_CAP}")
    seen: set[str] = set()
    for record in records:
        if record["upgrade_id"] in seen:
            raise ValueError(f"Province {province.province_id} has a duplicate {record['upgrade_id']}")
        seen.add(record["upgrade_id"])
    _write_records(province, records)


def _hidden_projection() -> dict[str, Any]:
    return {
        "upgrade_id": FORWARD_DEPOT_ID,
        "display_name": FORWARD_DEPOT_DISPLAY_NAME,
        "status": "none",
        "turns_remaining": 0,
        "slot_cap": FORWARD_DEPOT_SLOT_CAP,
        "slot_used": 0,
        "cost": FORWARD_DEPOT_COST,
        "build_time_turns": FORWARD_DEPOT_BUILD_TURNS,
        "available": False,
        "effect": FORWARD_DEPOT_EFFECT_ID,
    }


def _choose_ai_province(
    state: CampaignState,
    faction: Faction,
    candidates: Iterable[Province],
    reachable: set[str],
) -> Province | None:
    eligible: list[Province] = []
    for province in candidates:
        reasons = site_upgrade_blocked_reasons(
            state,
            province.province_id,
            faction=faction,
            actor_id=str(province.metadata.get("owner_actor_id") or "") or None,
            reachable=reachable,
        )
        if reasons:
            continue
        eligible.append(province)
    if not eligible:
        return None

    damaged = {
        battalion.province_id
        for battalion in state.battalions.values()
        if battalion.faction == faction and battalion.condition < 100
    }
    from .diplomacy import allied_factions

    friends = allied_factions(state, faction)
    front = {
        province.province_id
        for province in eligible
        if any(
            state.provinces[neighbor].owner not in friends
            for neighbor in province.neighbors
            if neighbor in state.provinces
        )
    }
    return min(
        eligible,
        key=lambda province: (
            0 if province.province_id in damaged else 1,
            0 if province.province_id in front else 1,
            province.province_id,
        ),
    )


def _province_is_supply_eligible(
    state: CampaignState,
    province_id: str,
    faction: Faction,
    *,
    reachable: set[str] | None = None,
) -> bool:
    from .p2_integrity import earth3_p2_supply_disabled

    if earth3_p2_supply_disabled(state):
        from .earth3_bootstrap import earth3_p2_footprint, is_earth3_p2_campaign

        return (not is_earth3_p2_campaign(state)) or province_id in earth3_p2_footprint(state)
    supplied = reachable if reachable is not None else reachable_supply_provinces(state, faction)
    return province_id in supplied


def _actor_runtime_installed(state: CampaignState) -> bool:
    return isinstance(state.map_metadata.get(ACTOR_RUNTIME_KEY), dict)


def _requested_actor_id(state: CampaignState, actor_id: str | None) -> str:
    requested = str(actor_id or "").strip()
    if requested:
        return requested
    runtime = state.map_metadata.get(ACTOR_RUNTIME_KEY)
    if isinstance(runtime, dict):
        return str(runtime.get("selected_actor_id") or "").strip()
    return ""


def _require_acting_owner(
    state: CampaignState,
    province: Province,
    faction: Faction,
    actor_id: str | None,
) -> str:
    if province.owner != faction:
        raise ValueError(f"Faction {faction.value} does not own {province.province_id}")
    if not _actor_runtime_installed(state):
        if actor_id:
            raise ValueError("Acting actor was provided but actor runtime is not installed")
        return ""
    requested = _requested_actor_id(state, actor_id)
    if not requested:
        raise ValueError("Acting actor is required")
    actors = ensure_strategic_actor_runtime(state)
    actor = actors.get(requested)
    if actor is None:
        raise KeyError(f"Unknown strategic actor: {requested}")
    if actor.tactical_side.campaign_faction() != faction:
        raise ValueError(f"Actor {requested} does not act as {faction.value}")
    owner_actor = str(province.metadata.get("owner_actor_id") or "")
    if owner_actor != requested:
        raise ValueError(f"Actor {requested} does not own {province.province_id}")
    return requested


def _available_resources(
    state: CampaignState,
    *,
    faction: Faction,
    actor_id: str | None,
) -> int:
    if _actor_runtime_installed(state):
        requested = _requested_actor_id(state, actor_id)
        if not requested:
            return 0
        actors = ensure_strategic_actor_runtime(state)
        actor = actors.get(requested)
        return 0 if actor is None else int(actor.resources)
    return int(state.factions[faction.value].resources)


def _debit_treasury(
    state: CampaignState,
    *,
    actor_id: str,
    faction: Faction,
    cost: int,
) -> int:
    if actor_id:
        actors = ensure_strategic_actor_runtime(state)
        actor = actors[actor_id]
        if actor.resources < cost:
            raise ValueError(f"Insufficient resources: need {cost}")
        actor.resources -= cost
        runtime = state.map_metadata[ACTOR_RUNTIME_KEY]
        runtime["actors"] = {key: actors[key].to_dict() for key in sorted(actors)}
        return int(actor.resources)
    faction_state = state.factions[faction.value]
    if faction_state.resources < cost:
        raise ValueError(f"Insufficient resources: need {cost}")
    faction_state.resources -= cost
    return int(faction_state.resources)


def _upgrade_matches_province_owner(province: Province, record: dict[str, Any]) -> bool:
    """True when a stored record still belongs to the current province owner."""

    return (
        province.owner != Faction.NEUTRAL
        and record["owner_faction"] == province.owner.value
    )


def _drop_upgrades_if_owner_changed(province: Province) -> None:
    raw = province.metadata.get(SITE_UPGRADE_KEY)
    if raw is None:
        return
    records = [
        _canonical_record(item, province_id=province.province_id)
        for item in _require_record_list(raw, province.province_id)
    ]
    if province.owner == Faction.NEUTRAL:
        province.metadata.pop(SITE_UPGRADE_KEY, None)
        return
    if any(not _upgrade_matches_province_owner(province, record) for record in records):
        province.metadata.pop(SITE_UPGRADE_KEY, None)


def _write_records(province: Province, records: list[dict[str, Any]]) -> None:
    if not records:
        province.metadata.pop(SITE_UPGRADE_KEY, None)
        return
    province.metadata[SITE_UPGRADE_KEY] = [
        {key: record[key] for key in SITE_UPGRADE_RECORD_KEYS}
        for record in sorted(records, key=lambda item: item["upgrade_id"])
    ]


def _require_record_list(raw: Any, province_id: str) -> list[Any]:
    if not isinstance(raw, list):
        raise ValueError(f"Province {province_id} site_upgrades must be a list")
    return raw


def _canonical_record(raw: Any, *, province_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"Province {province_id} site upgrade must be an object")
    extra = set(raw) - set(SITE_UPGRADE_RECORD_KEYS)
    if extra:
        raise ValueError(
            f"Province {province_id} site upgrade has unknown fields: {sorted(extra)}"
        )
    missing = [key for key in SITE_UPGRADE_RECORD_KEYS if key not in raw]
    if missing:
        raise ValueError(
            f"Province {province_id} site upgrade is missing fields: {missing}"
        )
    upgrade_id = str(raw["upgrade_id"])
    if upgrade_id not in KNOWN_UPGRADE_IDS:
        raise ValueError(f"Province {province_id} has unknown site upgrade {upgrade_id}")
    status = str(raw["status"])
    if status not in SITE_UPGRADE_STATUSES:
        raise ValueError(f"Province {province_id} has unknown site-upgrade status {status}")
    turns_remaining = raw["turns_remaining"]
    if isinstance(turns_remaining, bool) or not isinstance(turns_remaining, int):
        raise ValueError(f"Province {province_id} site-upgrade turns_remaining must be an int")
    if turns_remaining < 0:
        raise ValueError(f"Province {province_id} site-upgrade turns_remaining is negative")
    if status == "complete" and turns_remaining != 0:
        raise ValueError(f"Province {province_id} completed site upgrade still has remaining turns")
    if status == "building" and turns_remaining < 1:
        raise ValueError(f"Province {province_id} building site upgrade has no remaining turns")
    owner_actor_id = raw["owner_actor_id"]
    if not isinstance(owner_actor_id, str):
        raise ValueError(f"Province {province_id} site-upgrade owner_actor_id must be a string")
    owner_faction = str(raw["owner_faction"])
    try:
        Faction(owner_faction)
    except ValueError as exc:
        raise ValueError(f"Province {province_id} site-upgrade owner_faction is invalid") from exc
    started_turn = raw["started_turn"]
    if isinstance(started_turn, bool) or not isinstance(started_turn, int) or started_turn < 1:
        raise ValueError(f"Province {province_id} site-upgrade started_turn must be a positive int")
    return {
        "upgrade_id": upgrade_id,
        "status": status,
        "turns_remaining": turns_remaining,
        "owner_actor_id": owner_actor_id,
        "owner_faction": owner_faction,
        "started_turn": started_turn,
    }
