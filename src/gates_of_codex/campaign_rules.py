from __future__ import annotations

"""P9/#75 campaign calendar, war-aim hold, Momentum, and victory rules.

Python is the authority. Godot may only present the projected fields and issue
``continue_playing`` / ``conclude_campaign`` commands. Earth3 ``objectives.json``
remains frozen; war-aim metadata is overlaid from ``data/campaign_rules/v1.json``.
"""

import copy
import json
from collections import deque
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .models import CampaignState, Faction
from .supply import reachable_supply_provinces


CAMPAIGN_RULES_KEY = "campaign_rules"
CAMPAIGN_RULES_SCHEMA_VERSION = 1
CONTRACT_PATH = Path(__file__).resolve().parent / "data" / "campaign_rules" / "v1.json"
LENGTH_PRESETS = ("short", "medium", "long")
VICTORY_MODEL_P9 = "p9_v1"
VICTORY_MODEL_LEGACY = "legacy_compat"
DEFAULT_HOLD_WEEKS = 4
DEFAULT_START_YEAR = 2028
DEFAULT_TURNS_PER_YEAR = 52

GRADE_DECISIVE_VICTORY = "decisive_victory"
GRADE_VICTORY = "victory"
GRADE_NEGOTIATED = "negotiated_advantage"
GRADE_STALEMATE = "stalemate"
GRADE_DEFEAT = "defeat"
GRADE_DECISIVE_DEFEAT = "decisive_defeat"
VICTORY_GRADES = frozenset({GRADE_DECISIVE_VICTORY, GRADE_VICTORY})


class CampaignRulesError(ValueError):
    """Raised when a campaign-rules command or setting is illegal."""


@lru_cache(maxsize=1)
def load_campaign_rules_contract() -> dict[str, Any]:
    raw = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or int(raw.get("schema_version", 0)) != 1:
        raise CampaignRulesError("campaign_rules contract schema_version must be 1")
    presets = raw.get("presets")
    if not isinstance(presets, dict) or set(presets) != set(LENGTH_PRESETS):
        raise CampaignRulesError("campaign_rules contract must define short, medium, and long presets")
    for name in LENGTH_PRESETS:
        row = presets[name]
        expected_cap = {"short": 52, "medium": 104, "long": 156}[name]
        if int(row.get("turn_cap", 0)) != expected_cap:
            raise CampaignRulesError(f"{name} preset turn_cap must be {expected_cap}")
    return raw


def length_preset_ids() -> tuple[str, ...]:
    return LENGTH_PRESETS


def normalize_length_preset(value: str | None) -> str:
    contract = load_campaign_rules_contract()
    default = str(contract["calendar"]["default_length_preset"])
    text = str(value or default).strip().lower()
    if text not in LENGTH_PRESETS:
        raise CampaignRulesError(
            f"Unknown campaign length preset {value!r}; expected {', '.join(LENGTH_PRESETS)}"
        )
    return text


def calendar_from_turn(
    turn_number: int,
    *,
    start_year: int = DEFAULT_START_YEAR,
    turns_per_year: int = DEFAULT_TURNS_PER_YEAR,
) -> dict[str, Any]:
    turn = max(1, int(turn_number))
    year = int(start_year) + (turn - 1) // int(turns_per_year)
    week = ((turn - 1) % int(turns_per_year)) + 1
    return {
        "start_year": int(start_year),
        "turns_per_year": int(turns_per_year),
        "year": year,
        "week": week,
        "label": f"{year}-W{week:02d}",
    }


def campaign_rules(state: CampaignState) -> dict[str, Any]:
    metadata = getattr(state, "map_metadata", None)
    if not isinstance(metadata, dict):
        return {}
    raw = metadata.get(CAMPAIGN_RULES_KEY)
    return raw if isinstance(raw, dict) else {}


def campaign_play_blocked(state: CampaignState) -> bool:
    rules = campaign_rules(state)
    if bool(rules.get("concluded")):
        return True
    if bool(rules.get("continue_playing")):
        return False
    metadata = getattr(state, "map_metadata", None)
    if not isinstance(metadata, dict):
        return False
    outcome = metadata.get("campaign_outcome", {})
    return isinstance(outcome, dict) and outcome.get("status") == "complete"


def ensure_campaign_rules(
    state: CampaignState,
    *,
    length_preset: str | None = None,
    victory_model: str | None = None,
) -> dict[str, Any]:
    contract = load_campaign_rules_contract()
    existing = campaign_rules(state)
    preset_id = normalize_length_preset(
        length_preset if length_preset is not None else existing.get("length_preset")
    )
    preset = contract["presets"][preset_id]
    calendar_spec = contract["calendar"]
    model = str(
        victory_model
        or existing.get("victory_model")
        or VICTORY_MODEL_LEGACY
    )
    if model not in {VICTORY_MODEL_P9, VICTORY_MODEL_LEGACY}:
        raise CampaignRulesError(f"Unknown victory model {model!r}")

    rules = existing if existing else {}
    rules["schema_version"] = CAMPAIGN_RULES_SCHEMA_VERSION
    rules["victory_model"] = model
    rules["start_year"] = int(rules.get("start_year") or calendar_spec["start_year"])
    rules["turns_per_year"] = int(rules.get("turns_per_year") or calendar_spec["turns_per_year"])
    rules["hold_weeks"] = int(rules.get("hold_weeks") or calendar_spec["default_hold_weeks"])
    rules["length_preset"] = preset_id
    rules["turn_cap"] = int(preset["turn_cap"])
    rules["required_war_aims"] = int(preset["required_war_aims"])
    rules["required_national"] = int(preset["required_national"])
    rules["require_all_primary_war_aims"] = bool(preset["require_all_primary_war_aims"])
    if length_preset is not None or "thresholds" not in rules:
        rules["thresholds"] = copy.deepcopy(preset["thresholds"])
    rules.setdefault("momentum_sources", copy.deepcopy(contract["momentum_sources"]))
    rules.setdefault("continue_playing", False)
    rules.setdefault("concluded", False)
    rules.setdefault("result_locked", False)
    rules.setdefault("locked_result", {})
    rules.setdefault("momentum", {"score": 0, "by_faction": {}, "by_actor": {}})
    rules.setdefault("events", {"major_auto_resolve_wins": {}, "formation_losses": {}})
    rules.setdefault("actor_hub_loss", {})
    rules.setdefault("opening_owners", {})
    rules.setdefault("opening_formations", {})
    rules.setdefault("actor_hubs", copy.deepcopy(contract.get("actor_hubs", {})))
    rules["calendar"] = calendar_from_turn(
        state.turn_number,
        start_year=int(rules["start_year"]),
        turns_per_year=int(rules["turns_per_year"]),
    )
    if not rules["opening_owners"]:
        rules["opening_owners"] = {
            province_id: province.owner.value
            for province_id, province in state.provinces.items()
        }
    if not rules["opening_formations"]:
        rules["opening_formations"] = _living_formation_counts(state)
    state.map_metadata[CAMPAIGN_RULES_KEY] = rules
    _apply_objective_contract(state, contract)
    return rules


def _apply_objective_contract(state: CampaignState, contract: Mapping[str, Any]) -> None:
    objectives = state.map_metadata.get("operational_objectives")
    if not isinstance(objectives, list):
        return
    overlay = {
        str(row["id"]): row
        for row in contract.get("objective_overlay", [])
        if isinstance(row, dict) and row.get("id")
    }
    for objective in objectives:
        if not isinstance(objective, dict):
            continue
        extra = overlay.get(str(objective.get("id", "")))
        if extra is None:
            continue
        for key, value in extra.items():
            if key == "id":
                continue
            objective.setdefault(key, copy.deepcopy(value))
        objective.setdefault("target_hold_weeks", {})
    existing_ids = {
        str(row.get("id", ""))
        for row in objectives
        if isinstance(row, dict)
    }
    if str(campaign_rules(state).get("victory_model")) != VICTORY_MODEL_P9:
        return
    for row in contract.get("national_objectives", []):
        if not isinstance(row, dict):
            continue
        identity = str(row.get("id", ""))
        if not identity or identity in existing_ids:
            continue
        targets = [str(item) for item in row.get("targets", [])]
        if not targets or any(target not in state.provinces for target in targets):
            continue
        objectives.append(
            {
                **copy.deepcopy(row),
                "progress": 0,
                "completed": False,
                "completed_turn": 0,
                "rewarded": False,
                "target_hold_weeks": {},
            }
        )
        existing_ids.add(identity)


def resolve_objective_factions(state: CampaignState, objective: Mapping[str, Any]) -> set[Faction] | None:
    contract = load_campaign_rules_contract()
    owner_type = str(objective.get("owner_type") or "alliance")
    if owner_type == "actor":
        actor_id = str(objective.get("owner_id") or "")
        faction_id = contract["actor_faction"].get(actor_id)
        if faction_id and faction_id in state.factions:
            return {Faction(faction_id)}
        return None
    alliance_id = str(objective.get("coalition") or "")
    alliance = state.alliances.get(alliance_id)
    if alliance is not None:
        return set(alliance.factions)
    aliases = contract.get("coalition_aliases", {}).get(alliance_id, [])
    factions = {
        Faction(item)
        for item in aliases
        if item in state.factions
    }
    return factions or None


def hold_connected_provinces(state: CampaignState, faction: Faction) -> set[str]:
    """Provinces that count as supply-connected for war-aim hold.

    Prefer the strategic supply graph. Earth3 P2 currently records
    ``supply_connectivity_authority: none_until_p3`` and that graph is empty, so
    this v1 rule falls back to a documented BFS from authored hubs and static
    supply sources through friendly owners. That keeps the hold rule real
    without inventing a second economy/supply system.
    """

    from .p2_integrity import earth3_p2_supply_disabled

    if not earth3_p2_supply_disabled(state):
        return reachable_supply_provinces(state, faction)
    return _hub_connected_provinces(state, faction)


def _hub_connected_provinces(state: CampaignState, faction: Faction) -> set[str]:
    from .diplomacy import allied_factions

    friendly = allied_factions(state, faction)
    sources: set[str] = set()
    contract = load_campaign_rules_contract()
    actor_id = player_actor_id_for_faction(state, faction)
    for hub in contract.get("actor_hubs", {}).get(actor_id, []):
        if hub in state.provinces:
            sources.add(str(hub))
    for capital in state.map_metadata.get("earth3_p2_capitals", []):
        if not isinstance(capital, dict):
            continue
        province_id = str(capital.get("province_id") or "")
        if province_id:
            sources.add(province_id)
    for province_id, province in state.provinces.items():
        owners = set(province.metadata.get("static_supply_source_for", []))
        owners.update(province.metadata.get("supply_source_for", []))
        if faction.value in owners:
            sources.add(province_id)
    reachable: set[str] = set()
    queue: deque[str] = deque()
    for province_id in sorted(sources):
        province = state.provinces.get(province_id)
        if province is None or province.owner not in friendly:
            continue
        reachable.add(province_id)
        queue.append(province_id)
    while queue:
        current = queue.popleft()
        for neighbor_id in sorted(state.provinces[current].neighbors):
            if neighbor_id in reachable:
                continue
            neighbor = state.provinces.get(neighbor_id)
            if neighbor is None or neighbor.owner not in friendly:
                continue
            reachable.add(neighbor_id)
            queue.append(neighbor_id)
    return reachable


def player_actor_id_for_faction(state: CampaignState, faction: Faction) -> str:
    contract = load_campaign_rules_contract()
    mapped = str(contract["player_actor_by_faction"].get(faction.value, "") or "")
    if mapped:
        return mapped
    runtime = state.map_metadata.get("actor_content_runtime")
    if isinstance(runtime, dict):
        actors = runtime.get("actors")
        if isinstance(actors, dict):
            for actor_id, row in actors.items():
                if isinstance(row, dict) and str(row.get("tactical_side") or "") == faction.value:
                    return str(actor_id)
    return faction.value


def player_actor_id(state: CampaignState) -> str:
    return player_actor_id_for_faction(state, state.selected_faction)


def control_objective_progress(
    state: CampaignState,
    objective: Mapping[str, Any],
    coalition_factions: set[Faction],
) -> int:
    hold_weeks = int(objective.get("hold_weeks") or 0)
    if hold_weeks <= 0:
        return sum(
            1
            for province_id in objective.get("targets", [])
            if province_id in state.provinces
            and state.provinces[province_id].owner in coalition_factions
        )
    holds = objective.get("target_hold_weeks", {})
    if not isinstance(holds, dict):
        holds = {}
    return sum(
        1
        for province_id in objective.get("targets", [])
        if int(holds.get(str(province_id), 0) or 0) >= hold_weeks
    )


def advance_objective_holds(state: CampaignState) -> None:
    objectives = state.map_metadata.get("operational_objectives", [])
    if not isinstance(objectives, list):
        return
    connected_cache: dict[str, set[str]] = {}
    for objective in objectives:
        if not isinstance(objective, dict) or objective.get("kind") != "control":
            continue
        hold_weeks = int(objective.get("hold_weeks") or 0)
        if hold_weeks <= 0:
            continue
        factions = resolve_objective_factions(state, objective)
        if not factions:
            continue
        holds = objective.get("target_hold_weeks")
        if not isinstance(holds, dict):
            holds = {}
        next_holds: dict[str, int] = {}
        for province_id in objective.get("targets", []):
            identity = str(province_id)
            province = state.provinces.get(identity)
            owner_ok = province is not None and province.owner in factions
            connected = False
            if owner_ok and province is not None:
                cache_key = province.owner.value
                if cache_key not in connected_cache:
                    connected_cache[cache_key] = hold_connected_provinces(state, province.owner)
                connected = identity in connected_cache[cache_key]
            current = int(holds.get(identity, 0) or 0)
            next_holds[identity] = current + 1 if owner_ok and connected else 0
        objective["target_hold_weeks"] = next_holds
        objective["supply_connected_held"] = [
            province_id
            for province_id, weeks in next_holds.items()
            if weeks > 0
        ]


def advance_actor_hub_loss(state: CampaignState) -> None:
    rules = campaign_rules(state)
    hold_weeks = int(rules.get("hold_weeks") or DEFAULT_HOLD_WEEKS)
    loss = rules.setdefault("actor_hub_loss", {})
    contract = load_campaign_rules_contract()
    hubs_table = rules.get("actor_hubs") or contract.get("actor_hubs", {})
    for actor_id, hubs in hubs_table.items():
        faction_id = contract["actor_faction"].get(actor_id)
        if not faction_id or faction_id not in state.factions:
            continue
        faction = Faction(faction_id)
        present = [str(hub) for hub in hubs if str(hub) in state.provinces]
        if not present:
            continue
        from .diplomacy import allied_factions

        friendly = allied_factions(state, faction)
        held = False
        for hub in present:
            province = state.provinces.get(hub)
            if province is not None and province.owner in friendly:
                held = True
                break
        row = loss.get(actor_id) if isinstance(loss.get(actor_id), dict) else {}
        if held:
            weeks_lost = 0
            defeated = bool(row.get("defeated"))
        else:
            weeks_lost = int(row.get("weeks_lost", 0) or 0) + 1
            defeated = weeks_lost >= hold_weeks
        loss[actor_id] = {
            "weeks_lost": weeks_lost,
            "defeated": defeated,
            "hubs": list(hubs),
        }
    state.map_metadata[CAMPAIGN_RULES_KEY] = rules


def record_auto_resolve_result(state: CampaignState, winner: Faction, pending: Any) -> None:
    """Count an attacker auto-resolve win as a major victory for Momentum."""

    ensure_campaign_rules(state)
    rules = campaign_rules(state)
    events = rules.setdefault("events", {})
    wins = events.setdefault("major_auto_resolve_wins", {})
    attacker = getattr(pending, "attacker_faction", None)
    if attacker is not None and winner == attacker:
        key = winner.value
        wins[key] = int(wins.get(key, 0) or 0) + 1
    state.map_metadata[CAMPAIGN_RULES_KEY] = rules


def refresh_campaign_calendar(state: CampaignState) -> dict[str, Any]:
    rules = ensure_campaign_rules(state)
    rules["calendar"] = calendar_from_turn(
        state.turn_number,
        start_year=int(rules["start_year"]),
        turns_per_year=int(rules["turns_per_year"]),
    )
    state.map_metadata[CAMPAIGN_RULES_KEY] = rules
    return rules["calendar"]


def update_momentum(state: CampaignState) -> dict[str, Any]:
    rules = ensure_campaign_rules(state)
    sources = rules.get("momentum_sources") or load_campaign_rules_contract()["momentum_sources"]
    by_faction: dict[str, int] = {}
    by_actor: dict[str, int] = {}
    for faction_id in state.factions:
        faction = Faction(faction_id)
        score = _momentum_for_faction(state, faction, sources)
        by_faction[faction_id] = score
        by_actor[player_actor_id_for_faction(state, faction)] = score
    selected = by_faction.get(state.selected_faction.value, 0)
    rules["momentum"] = {
        "score": int(selected),
        "by_faction": by_faction,
        "by_actor": by_actor,
    }
    state.map_metadata[CAMPAIGN_RULES_KEY] = rules
    return rules["momentum"]


def _momentum_for_faction(
    state: CampaignState,
    faction: Faction,
    sources: Mapping[str, Any],
) -> int:
    from .diplomacy import allied_factions

    friendly = allied_factions(state, faction)
    objectives = state.map_metadata.get("operational_objectives", [])
    war_aims = 0
    if isinstance(objectives, list):
        for objective in objectives:
            if not isinstance(objective, dict):
                continue
            if str(objective.get("layer") or "") != "coalition_war_aim":
                continue
            owners = resolve_objective_factions(state, objective)
            if owners and faction in owners and objective.get("completed"):
                war_aims += 1
    held_sites = 0
    lost_capitals = 0
    contract = load_campaign_rules_contract()
    actor_id = player_actor_id_for_faction(state, faction)
    hubs_table = campaign_rules(state).get("actor_hubs") or contract.get("actor_hubs", {})
    for hub in hubs_table.get(actor_id, []):
        province = state.provinces.get(str(hub))
        if province is None:
            continue
        if province.owner in friendly:
            held_sites += 1
        else:
            lost_capitals += 1
    for capital in state.map_metadata.get("earth3_p2_capitals", []):
        if not isinstance(capital, dict):
            continue
        province = state.provinces.get(str(capital.get("province_id") or ""))
        if province is None:
            continue
        if province.owner in friendly:
            held_sites += 1
        elif str(capital.get("owner_id") or "") in {actor_id, faction.value}:
            lost_capitals += 1
    connected = hold_connected_provinces(state, faction)
    opening = campaign_rules(state).get("opening_owners", {})
    gains = 0
    for province_id, province in state.provinces.items():
        if province.owner not in friendly:
            continue
        if province_id not in connected:
            continue
        opened = str(opening.get(province_id, ""))
        if opened and opened != province.owner.value and Faction(opened) not in friendly:
            gains += 1
    wins = int(
        campaign_rules(state)
        .get("events", {})
        .get("major_auto_resolve_wins", {})
        .get(faction.value, 0)
        or 0
    )
    opening_formations = int(
        campaign_rules(state).get("opening_formations", {}).get(faction.value, 0) or 0
    )
    current_formations = _living_formation_counts(state).get(faction.value, 0)
    losses = max(0, opening_formations - current_formations)
    return (
        war_aims * int(sources.get("war_aim_completed", 0))
        + held_sites * int(sources.get("held_strategic_site", 0))
        + gains * int(sources.get("supply_connected_gain", 0))
        + wins * int(sources.get("major_auto_resolve_victory", 0))
        + losses * int(sources.get("formation_loss", 0))
        + lost_capitals * int(sources.get("lost_capital", 0))
    )


def _living_formation_counts(state: CampaignState) -> dict[str, int]:
    counts: dict[str, int] = {faction_id: 0 for faction_id in state.factions}
    for force in state.strategic_formations.values():
        living = any(
            battalion.faction == force.faction and battalion.unit_count > 0
            for battalion in state.battalions.values()
            if battalion.strategic_formation_id == force.strategic_formation_id
            or battalion.formation_id == force.template_formation_id
        )
        if living:
            counts[force.faction.value] = counts.get(force.faction.value, 0) + 1
    if state.strategic_formations:
        return counts
    for battalion in state.battalions.values():
        if battalion.unit_count > 0:
            counts[battalion.faction.value] = counts.get(battalion.faction.value, 0) + 1
    return counts


def evaluate_p9_outcome(state: CampaignState) -> Any | None:
    """Return a terminal P9 outcome, or None so legacy victory may still run."""

    from .strategic import CampaignOutcome, coalition_for_faction

    rules = ensure_campaign_rules(state)
    refresh_campaign_calendar(state)
    update_momentum(state)
    if bool(rules.get("concluded")) or (
        bool(rules.get("result_locked")) and not bool(rules.get("continue_playing"))
    ):
        locked = rules.get("locked_result")
        if isinstance(locked, dict) and locked.get("status"):
            return _outcome_from_dict(locked)

    selected = state.selected_faction
    selected_alliance = coalition_for_faction(state, selected)
    player_actor = player_actor_id(state)
    hub_loss = rules.get("actor_hub_loss", {})
    player_defeated = bool(hub_loss.get(player_actor, {}).get("defeated"))
    player_score = int(rules.get("momentum", {}).get("by_faction", {}).get(selected.value, 0))
    thresholds = rules.get("thresholds", {})
    collapse = int(thresholds.get("momentum_collapse", -30))
    if str(rules.get("victory_model")) != VICTORY_MODEL_P9:
        return None
    if bool(rules.get("continue_playing")) and bool(rules.get("result_locked")):
        locked = dict(rules.get("locked_result") or {})
        locked["continue_playing"] = True
        locked["momentum"] = player_score
        return _outcome_from_dict(locked)
    if player_defeated or player_score <= collapse:
        grade = GRADE_DECISIVE_DEFEAT if player_defeated and player_score <= collapse else GRADE_DEFEAT
        reason = (
            "player actor capital or control hub lost and not recovered"
            if player_defeated
            else "victory momentum collapsed"
        )
        return _lock_outcome(
            state,
            CampaignOutcome(
                status="complete",
                winner_coalition="",
                loser_coalition=selected_alliance,
                reason=reason,
                selected_faction_result="defeat",
                victory_hold_rounds=int(rules.get("hold_weeks") or 0),
                grade=grade,
                coalition_result="defeat",
                national_result="defeat",
                continue_playing=False,
                concluded=False,
                momentum=player_score,
            ),
        )

    contenders = _victory_contenders(state)
    for owner_key, owner_factions, lead_faction in contenders:
        # Coalition war aims are coalition-wide. An allied actor's national
        # contribution must not end the selected player's campaign or become a
        # defeat. Player victory uses the selected actor only; defeat from this
        # path requires an opposing coalition's accepted victory contract.
        if selected in owner_factions and lead_faction != selected:
            continue
        report = _owner_victory_report(state, owner_key, owner_factions, lead_faction)
        if report is None:
            continue
        winner_is_player = selected == lead_faction
        selected_result = "victory" if winner_is_player else "defeat"
        if winner_is_player:
            grade = str(report["grade"])
            coalition_result = str(report["coalition_result"])
            national_result = str(report["national_result"])
            reason = str(report["reason"])
            momentum = int(report["momentum"])
        else:
            # Player-facing fields stay selected-player semantics. Winner
            # coalition is recorded separately; do not copy the opposing
            # owner report's victory grade / layer results onto the loser.
            grade = GRADE_DEFEAT
            coalition_result = _layer_result(state, selected, "coalition_war_aim")
            national_result = _layer_result(state, selected, "national_contribution")
            reason = "opposing coalition completed its accepted victory contract"
            momentum = player_score
        return _lock_outcome(
            state,
            CampaignOutcome(
                status="complete",
                winner_coalition=str(report["coalition"]),
                loser_coalition="" if winner_is_player else selected_alliance,
                reason=reason,
                selected_faction_result=selected_result,
                victory_hold_rounds=int(rules.get("hold_weeks") or 0),
                grade=grade,
                coalition_result=coalition_result,
                national_result=national_result,
                continue_playing=False,
                concluded=False,
                momentum=momentum,
            ),
        )

    turn_cap = int(rules.get("turn_cap") or 0)
    if (
        turn_cap
        and int(state.turn_number) > turn_cap
        and not bool(rules.get("continue_playing"))
    ):
        grade = _time_limit_grade(state, selected, thresholds)
        selected_result = (
            "victory"
            if grade in VICTORY_GRADES
            else ("active" if grade in {GRADE_NEGOTIATED, GRADE_STALEMATE} else "defeat")
        )
        return _lock_outcome(
            state,
            CampaignOutcome(
                status="complete",
                winner_coalition=selected_alliance if grade in VICTORY_GRADES else "",
                loser_coalition=selected_alliance if grade in {GRADE_DEFEAT, GRADE_DECISIVE_DEFEAT} else "",
                reason="time-limit grading at the campaign turn cap",
                selected_faction_result=selected_result,
                victory_hold_rounds=int(rules.get("hold_weeks") or 0),
                grade=grade,
                coalition_result=_layer_result(state, selected, "coalition_war_aim"),
                national_result=_layer_result(state, selected, "national_contribution"),
                continue_playing=False,
                concluded=False,
                momentum=player_score,
            ),
        )
    return None


def _victory_contenders(state: CampaignState) -> list[tuple[str, set[Faction], Faction]]:
    seen: dict[str, set[Faction]] = {}
    for objective in state.map_metadata.get("operational_objectives", []) or []:
        if not isinstance(objective, dict):
            continue
        if str(objective.get("layer") or "") != "coalition_war_aim":
            continue
        factions = resolve_objective_factions(state, objective)
        if not factions:
            continue
        key = str(objective.get("coalition") or objective.get("owner_id") or sorted(f.value for f in factions)[0])
        seen.setdefault(key, set()).update(factions)
    rows: list[tuple[str, set[Faction], Faction]] = []
    for key in sorted(seen):
        for faction in sorted(seen[key], key=lambda item: item.value):
            rows.append((key, seen[key], faction))
    return rows


def _required_count(rules: Mapping[str, Any], key: str, *, default: int = 1) -> int:
    """Read a required-count field. An explicit 0 must stay 0; ``or 1`` would raise it."""

    if key not in rules or rules[key] is None:
        return default
    return int(rules[key])


def _owner_victory_report(
    state: CampaignState,
    owner_key: str,
    owner_factions: set[Faction],
    lead_faction: Faction,
) -> dict[str, Any] | None:
    rules = campaign_rules(state)
    objectives = [
        row
        for row in state.map_metadata.get("operational_objectives", []) or []
        if isinstance(row, dict)
    ]
    war_aims = []
    national = []
    for row in objectives:
        owners = resolve_objective_factions(state, row)
        if not owners:
            continue
        layer = str(row.get("layer") or "")
        owner_id = str(row.get("coalition") or row.get("owner_id") or "")
        if layer == "coalition_war_aim" and owner_id == owner_key and owners <= owner_factions:
            war_aims.append(row)
        elif layer == "national_contribution" and lead_faction in owners:
            national.append(row)
    completed_aims = [row for row in war_aims if row.get("completed")]
    completed_national = [row for row in national if row.get("completed")]
    primary_aims = [row for row in war_aims if row.get("primary")]
    required_aims = _required_count(rules, "required_war_aims")
    required_national = _required_count(rules, "required_national")
    aims_ok = len(completed_aims) >= required_aims
    if bool(rules.get("require_all_primary_war_aims")) and primary_aims:
        aims_ok = aims_ok and all(row.get("completed") for row in primary_aims)
    national_ok = len(completed_national) >= required_national if national else required_national <= 0
    if not aims_ok or not national_ok:
        return None
    score = int(rules.get("momentum", {}).get("by_faction", {}).get(lead_faction.value, 0) or 0)
    thresholds = rules.get("thresholds", {})
    if score >= int(thresholds.get("decisive_victory", 80)) and (
        not primary_aims or all(row.get("completed") for row in primary_aims)
    ):
        grade = GRADE_DECISIVE_VICTORY
        reason = "decisive victory: war aims held, national contribution met, decisive Momentum"
    elif score >= int(thresholds.get("victory", 50)):
        grade = GRADE_VICTORY
        reason = "campaign victory: required war aims and national contribution before the turn cap"
    else:
        return None
    if int(state.turn_number) > int(rules.get("turn_cap") or 0) and not rules.get("continue_playing"):
        return None
    return {
        "coalition": owner_key,
        "grade": grade,
        "reason": reason,
        "coalition_result": "victory",
        "national_result": "victory",
        "momentum": score,
    }


def _time_limit_grade(
    state: CampaignState,
    faction: Faction,
    thresholds: Mapping[str, Any],
) -> str:
    rules = campaign_rules(state)
    score = int(rules.get("momentum", {}).get("by_faction", {}).get(faction.value, 0) or 0)
    actor = player_actor_id_for_faction(state, faction)
    defeated = bool(rules.get("actor_hub_loss", {}).get(actor, {}).get("defeated"))
    coalition = _layer_result(state, faction, "coalition_war_aim")
    national = _layer_result(state, faction, "national_contribution")
    if defeated and score <= int(thresholds.get("decisive_defeat", -40)):
        return GRADE_DECISIVE_DEFEAT
    if score >= int(thresholds.get("decisive_victory", 80)) and coalition == "victory" and national == "victory":
        return GRADE_DECISIVE_VICTORY
    if score >= int(thresholds.get("victory", 50)) and coalition == "victory" and national == "victory":
        return GRADE_VICTORY
    if score >= int(thresholds.get("negotiated_advantage", 25)) and (coalition == "victory" or national == "victory"):
        return GRADE_NEGOTIATED
    if score <= int(thresholds.get("decisive_defeat", -40)) or defeated:
        return GRADE_DECISIVE_DEFEAT if defeated else GRADE_DEFEAT
    if score <= int(thresholds.get("defeat", -25)):
        return GRADE_DEFEAT
    return GRADE_STALEMATE


def _layer_result(state: CampaignState, faction: Faction, layer: str) -> str:
    rows = [
        row
        for row in state.map_metadata.get("operational_objectives", []) or []
        if isinstance(row, dict)
        and str(row.get("layer") or "") == layer
        and resolve_objective_factions(state, row)
        and faction in resolve_objective_factions(state, row)
    ]
    if not rows:
        return "none"
    completed = sum(1 for row in rows if row.get("completed"))
    key = "required_national" if layer == "national_contribution" else "required_war_aims"
    required = _required_count(campaign_rules(state), key)
    return "victory" if completed >= required else "incomplete"


def _lock_outcome(state: CampaignState, outcome: Any) -> Any:
    rules = campaign_rules(state)
    payload = _outcome_to_dict(outcome)
    payload["continue_playing"] = bool(rules.get("continue_playing"))
    payload["concluded"] = bool(rules.get("concluded"))
    rules["result_locked"] = True
    rules["locked_result"] = payload
    state.map_metadata[CAMPAIGN_RULES_KEY] = rules
    return _outcome_from_dict(payload)


def _outcome_to_dict(outcome: Any) -> dict[str, Any]:
    if hasattr(outcome, "__dataclass_fields__"):
        return asdict(outcome)
    return dict(outcome)


def _outcome_from_dict(payload: Mapping[str, Any]) -> Any:
    from .strategic import CampaignOutcome

    fields = {
        "status": str(payload.get("status") or "active"),
        "winner_coalition": str(payload.get("winner_coalition") or ""),
        "loser_coalition": str(payload.get("loser_coalition") or ""),
        "reason": str(payload.get("reason") or ""),
        "selected_faction_result": str(payload.get("selected_faction_result") or "active"),
        "victory_hold_rounds": int(payload.get("victory_hold_rounds") or 0),
        "grade": str(payload.get("grade") or ""),
        "coalition_result": str(payload.get("coalition_result") or ""),
        "national_result": str(payload.get("national_result") or ""),
        "continue_playing": bool(payload.get("continue_playing")),
        "concluded": bool(payload.get("concluded")),
        "momentum": int(payload.get("momentum") or 0),
    }
    return CampaignOutcome(**fields)


def continue_playing(state: CampaignState) -> dict[str, Any]:
    ensure_campaign_rules(state)
    rules = campaign_rules(state)
    outcome = state.map_metadata.get("campaign_outcome", {})
    locked = rules.get("locked_result") if isinstance(rules.get("locked_result"), dict) else {}
    grade = str((outcome or {}).get("grade") or locked.get("grade") or "")
    selected_result = str(
        (outcome or {}).get("selected_faction_result") or locked.get("selected_faction_result") or ""
    )
    if str((outcome or {}).get("status") or "") != "complete" and not rules.get("result_locked"):
        raise CampaignRulesError("Continue Playing is only available after a campaign result")
    if grade not in VICTORY_GRADES or selected_result == "defeat":
        raise CampaignRulesError("Continue Playing is only available after victory")
    if rules.get("concluded"):
        raise CampaignRulesError("Campaign is already concluded")
    rules["continue_playing"] = True
    rules["concluded"] = False
    locked = dict(rules.get("locked_result") or outcome or {})
    locked["continue_playing"] = True
    locked["concluded"] = False
    locked["status"] = "complete"
    rules["locked_result"] = locked
    rules["result_locked"] = True
    state.map_metadata[CAMPAIGN_RULES_KEY] = rules
    state.map_metadata["campaign_outcome"] = locked
    return copy.deepcopy(locked)


def conclude_campaign(state: CampaignState) -> dict[str, Any]:
    ensure_campaign_rules(state)
    rules = campaign_rules(state)
    outcome = state.map_metadata.get("campaign_outcome", {})
    if str((outcome or {}).get("status") or "") != "complete" and not rules.get("result_locked"):
        raise CampaignRulesError("Conclude Campaign is only available after a campaign result")
    rules["concluded"] = True
    rules["continue_playing"] = False
    locked = dict(rules.get("locked_result") or outcome or {})
    locked["concluded"] = True
    locked["continue_playing"] = False
    locked["status"] = "complete"
    rules["locked_result"] = locked
    rules["result_locked"] = True
    state.map_metadata[CAMPAIGN_RULES_KEY] = rules
    state.map_metadata["campaign_outcome"] = locked
    return copy.deepcopy(locked)


def _presentation_rules(state: CampaignState) -> dict[str, Any]:
    """Read-only overlay. Runtime-patch projection must not mutate retained state."""
    existing = campaign_rules(state)
    if existing:
        return existing
    contract = load_campaign_rules_contract()
    preset_id = str(contract["calendar"]["default_length_preset"])
    preset = contract["presets"][preset_id]
    return {
        "length_preset": preset_id,
        "turn_cap": int(preset["turn_cap"]),
        "hold_weeks": int(contract["calendar"]["default_hold_weeks"]),
        "calendar": calendar_from_turn(state.turn_number),
        "continue_playing": False,
        "concluded": False,
        "momentum": {"score": 0, "by_faction": {}, "by_actor": {}},
        "victory_model": VICTORY_MODEL_LEGACY,
        "thresholds": copy.deepcopy(preset["thresholds"]),
    }


def campaign_presentation(state: CampaignState) -> dict[str, Any]:
    rules = _presentation_rules(state)
    calendar = rules.get("calendar") or calendar_from_turn(state.turn_number)
    momentum = rules.get("momentum") or {"score": 0, "by_faction": {}, "by_actor": {}}
    return {
        "calendar": copy.deepcopy(calendar),
        "length_preset": str(rules.get("length_preset") or "medium"),
        "turn_cap": int(rules.get("turn_cap") or 0),
        "hold_weeks": int(rules.get("hold_weeks") or DEFAULT_HOLD_WEEKS),
        "continue_playing": bool(rules.get("continue_playing")),
        "concluded": bool(rules.get("concluded")),
        "momentum": copy.deepcopy(momentum),
        "victory_model": str(rules.get("victory_model") or VICTORY_MODEL_LEGACY),
        "thresholds": copy.deepcopy(rules.get("thresholds") or {}),
    }
