from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .models import CampaignState, Faction


FORCE_PANEL_OP = "actor_force_panel"
RESEARCH_OP = "research"
RECRUIT_OP = "recruit"
ASSIGN_OP = "assign"


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def actor_content_installed(state: CampaignState) -> bool:
    return isinstance(state.map_metadata.get("actor_content_runtime"), dict)


def requested_actor_id(state: CampaignState, raw: dict[str, Any]) -> str:
    """Return the selected player. Command payloads cannot spoof this identity.

    Explicit ``actor`` / ``actor_id`` is presentation-only. Economy identity
    always comes from the formation's ``actor_id``.
    """

    del raw
    return selected_command_actor_id(state)


def selected_command_actor_id(state: CampaignState) -> str:
    runtime = state.map_metadata.get("strategic_actor_runtime")
    if isinstance(runtime, dict):
        selected = str(runtime.get("selected_actor_id") or "").strip()
        if selected:
            return selected
    raise ValueError("Actor identity is required for force-management commands")


def is_core_2028_campaign(state: CampaignState) -> bool:
    profile = state.map_metadata.get("scenario_profile")
    if isinstance(profile, dict):
        scenario_id = str(profile.get("scenario_id") or "").strip()
        if scenario_id:
            return scenario_id == "ww3_2028_core"
    return str(state.map_metadata.get("scenario_id") or "").strip() == "ww3_2028_core"


def formation_economy_actor_id(state: CampaignState, formation_id: str) -> str:
    force = state.strategic_formations.get(formation_id)
    if force is None:
        raise KeyError(f"Unknown strategic formation: {formation_id}")
    owner = str(force.actor_id or "").strip()
    if not owner:
        raise ValueError(f"Formation {formation_id} has no economy actor")
    return owner


def player_may_command_formation(state: CampaignState, formation_id: str) -> bool:
    force = state.strategic_formations.get(formation_id)
    if force is None:
        return False
    economy_id = str(force.actor_id or "").strip()
    if not economy_id:
        return False
    command_id = selected_command_actor_id(state)
    if command_id == economy_id:
        return True
    if not is_core_2028_campaign(state):
        return False
    from .strategic_actors import ensure_strategic_actor_runtime

    actors = ensure_strategic_actor_runtime(state)
    command = actors.get(command_id)
    economy = actors.get(economy_id)
    if command is None or economy is None:
        return False
    command_coalition = str(command.coalition_id or "").strip()
    economy_coalition = str(economy.coalition_id or "").strip()
    if not command_coalition or command_coalition != economy_coalition:
        return False
    return (
        command.tactical_side.campaign_faction() == force.faction
        and economy.tactical_side.campaign_faction() == force.faction
    )


def require_player_may_command_formation(state: CampaignState, formation_id: str) -> None:
    if not formation_id:
        raise ValueError("formation required")
    if state.strategic_formations.get(formation_id) is None:
        raise KeyError(f"Unknown strategic formation: {formation_id}")
    if player_may_command_formation(state, formation_id):
        return
    command_id = selected_command_actor_id(state)
    economy_id = str(state.strategic_formations[formation_id].actor_id or "nobody")
    raise ValueError(
        f"Formation {formation_id} is not under {command_id} command authority "
        f"(economy actor {economy_id})"
    )


def require_formation_owned_by_actor(
    state: CampaignState,
    formation_id: str,
    actor_id: str,
) -> None:
    del actor_id
    require_player_may_command_formation(state, formation_id)


def build_acting_actor_presentation(state: CampaignState) -> dict[str, Any] | None:
    """Treasury/budget row for the selected actor. No roster payload."""

    runtime = state.map_metadata.get("strategic_actor_runtime")
    if not isinstance(runtime, dict):
        return None
    actor_id = str(runtime.get("selected_actor_id") or "").strip()
    actors = runtime.get("actors")
    if not actor_id or not isinstance(actors, dict):
        return None
    actor = actors.get(actor_id)
    if not isinstance(actor, dict):
        return None
    last_round: dict[str, Any] = {}
    content = state.map_metadata.get("actor_content_runtime")
    if isinstance(content, dict):
        for report in content.get("last_round_economy") or []:
            if isinstance(report, dict) and str(report.get("actor_id") or "") == actor_id:
                last_round = report
                break
    researched = actor.get("researched_keys") or []
    tactical_side = actor.get("tactical_side") or actor.get("campaign_faction") or ""
    return {
        "actor_id": actor_id,
        "display_name": str(actor.get("display_name") or actor_id),
        "short_name": str(actor.get("short_name") or actor.get("display_name") or actor_id),
        "tactical_side": str(tactical_side),
        "resources": int(actor.get("resources") or 0),
        "income_last_round": int(last_round.get("income") or 0),
        "maintenance_last_round": int(last_round.get("maintenance_due") or 0),
        "researched_count": len(researched),
        "content_installed": isinstance(content, dict),
    }


def build_actor_force_panel(state: CampaignState, raw: dict[str, Any]) -> dict[str, Any]:
    """Bounded acting-actor recruit/research/repair presentation.

    Returns only the requested actor's treasury, research, offers, and pool.
    Foreign formation ownership never leaks another actor's roster.
    """

    if actor_content_installed(state):
        return _jsonable(_actor_content_panel(state, raw))
    return _jsonable(_legacy_faction_panel(state, raw))


def apply_research_command(state: CampaignState, raw: dict[str, Any]) -> dict[str, Any]:
    key = str(raw.get("key") or raw.get("research_key") or "").strip()
    if not key:
        raise ValueError("research requires key")
    if actor_content_installed(state):
        from .actor_economy import purchase_actor_research

        formation = _formation_id(raw)
        if formation:
            require_player_may_command_formation(state, formation)
            actor_id = formation_economy_actor_id(state, formation)
        else:
            actor_id = selected_command_actor_id(state)
        if not key.startswith(f"actor:{actor_id}:"):
            raise ValueError(f"Research key is not scoped to actor {actor_id}: {key}")
        return _jsonable(asdict(purchase_actor_research(state, actor_id, key)))
    from .economy import purchase_research

    faction = Faction(str(raw.get("faction") or state.selected_faction.value))
    return _jsonable(asdict(purchase_research(state, faction, key)))


def apply_recruit_command(state: CampaignState, raw: dict[str, Any]) -> dict[str, Any]:
    formation = _formation_id(raw)
    unit_name = str(raw.get("unit") or raw.get("unit_name") or "").strip()
    quantity = int(raw.get("quantity") or 1)
    if not formation or not unit_name:
        raise ValueError("recruit requires formation and unit")
    if actor_content_installed(state):
        from .actor_economy import purchase_actor_reinforcements

        require_player_may_command_formation(state, formation)
        return _jsonable(asdict(purchase_actor_reinforcements(state, formation, unit_name, quantity)))
    from .economy import purchase_reinforcements

    return _jsonable(asdict(purchase_reinforcements(state, formation, unit_name, quantity)))


def apply_assign_command(state: CampaignState, raw: dict[str, Any]) -> dict[str, Any]:
    formation = _formation_id(raw)
    unit_name = str(raw.get("unit") or raw.get("unit_name") or "").strip()
    quantity = int(raw.get("quantity") or 1)
    battalion_id = raw.get("battalion") or raw.get("battalion_id")
    if not formation or not unit_name:
        raise ValueError("assign requires formation and unit")
    if actor_content_installed(state):
        from .actor_economy import assign_actor_reinforcements

        require_player_may_command_formation(state, formation)
        return _jsonable(
            asdict(
                assign_actor_reinforcements(
                    state,
                    formation,
                    unit_name,
                    quantity,
                    battalion_id=None if battalion_id in (None, "") else str(battalion_id),
                )
            )
        )
    from .economy import assign_reinforcements

    return _jsonable(asdict(assign_reinforcements(state, formation, unit_name, quantity)))


def apply_repair_command(state: CampaignState, raw: dict[str, Any]) -> dict[str, Any]:
    formation = _formation_id(raw)
    points = raw.get("points")
    requested_points = None if points is None else int(points)
    battalion_id = raw.get("battalion") or raw.get("battalion_id")
    if actor_content_installed(state):
        from .actor_economy import repair_actor_formation

        require_player_may_command_formation(state, formation)
        return _jsonable(
            asdict(
                repair_actor_formation(
                    state,
                    formation,
                    requested_points,
                    battalion_id=None if battalion_id in (None, "") else str(battalion_id),
                )
            )
        )
    from .economy import repair_formation

    return _jsonable(asdict(repair_formation(state, formation, requested_points)))


def _formation_id(raw: dict[str, Any]) -> str:
    return str(
        raw.get("formation")
        or raw.get("formation_id")
        or raw.get("strategic_formation_id")
        or ""
    ).strip()


def _actor_content_panel(state: CampaignState, raw: dict[str, Any]) -> dict[str, Any]:
    from .actor_economy import actor_recruitment_offers, available_actor_research
    from .strategic_actors import ensure_strategic_actor_runtime

    command_id = selected_command_actor_id(state)
    actors = ensure_strategic_actor_runtime(state)
    command = actors.get(command_id)
    if command is None:
        raise KeyError(f"Unknown strategic actor: {command_id}")
    formation_id = _formation_id(raw)
    battalion_id = raw.get("battalion") or raw.get("battalion_id")
    battalion_id = "" if battalion_id in (None, "") else str(battalion_id)
    force = state.strategic_formations.get(formation_id) if formation_id else None
    formation_actor_id = str(force.actor_id or "") if force is not None else ""
    can_manage = bool(formation_id and player_may_command_formation(state, formation_id))
    blocked: list[str] = []
    if not formation_id:
        blocked.append("Select a strategic formation.")
    elif force is None:
        blocked.append(f"Unknown strategic formation: {formation_id}")
    elif not can_manage:
        blocked.append(
            f"Formation is not under {command_id} command authority "
            f"(economy actor {formation_actor_id or 'nobody'})"
        )

    present_id = formation_actor_id if can_manage else command_id
    present = actors.get(present_id)
    if present is None:
        raise KeyError(f"Unknown strategic actor: {present_id}")

    offers: list[dict[str, Any]] = []
    pool: list[dict[str, Any]] = []
    repair: dict[str, Any] = {
        "can_repair": False,
        "blocked_reasons": list(blocked),
        "battalion_id": battalion_id,
        "condition": 0,
        "supply": 0,
        "encircled_turns": 0,
        "points_needed": 0,
        "cost_per_point": 0,
        "affordable_points": 0,
        "total_cost": 0,
    }
    if can_manage and force is not None:
        offers = [asdict(item) for item in actor_recruitment_offers(state, formation_id)]
        runtime = state.map_metadata["actor_content_runtime"]
        pool = [
            dict(entry)
            for entry in runtime.get("reinforcement_pool") or []
            if entry.get("actor_id") == present_id
            and entry.get("strategic_formation_id") == formation_id
        ]
        repair = _actor_repair_quote(
            state,
            formation_id,
            battalion_id=battalion_id or None,
            actor_id=present_id,
        )

    last_round: dict[str, Any] = {}
    for report in state.map_metadata["actor_content_runtime"].get("last_round_economy") or []:
        if isinstance(report, dict) and str(report.get("actor_id") or "") == present_id:
            last_round = report
            break

    return {
        "actor_id": present_id,
        "display_name": present.display_name,
        "short_name": present.short_name,
        "tactical_side": present.tactical_side.value,
        "resources": present.resources,
        "income_last_round": int(last_round.get("income") or 0),
        "maintenance_last_round": int(last_round.get("maintenance_due") or 0),
        "researched_keys": list(present.researched_keys),
        "available_research": [
            asdict(item) for item in available_actor_research(state, present_id)
        ]
        if can_manage
        else [],
        "command_actor_id": command_id,
        "command_display_name": command.display_name,
        "formation_id": formation_id,
        "formation_actor_id": formation_actor_id,
        "battalion_id": battalion_id,
        "can_manage_formation": can_manage,
        "blocked_reasons": blocked,
        "recruitment_offers": offers,
        "reinforcement_pool": pool,
        "repair": repair,
        "content_installed": True,
    }


def _actor_repair_quote(
    state: CampaignState,
    formation_id: str,
    *,
    battalion_id: str | None,
    actor_id: str,
) -> dict[str, Any]:
    from .actor_economy import _force_battalion, _runtime

    force = state.strategic_formations[formation_id]
    blocked: list[str] = []
    try:
        target = _force_battalion(state, force.battalion_ids, battalion_id)
    except ValueError as exc:
        return {
            "can_repair": False,
            "blocked_reasons": [str(exc)],
            "battalion_id": battalion_id or "",
            "condition": 0,
            "supply": 0,
            "encircled_turns": 0,
            "points_needed": 0,
            "cost_per_point": 0,
            "affordable_points": 0,
            "total_cost": 0,
        }
    runtime = _runtime(state)
    units = runtime["actors"][actor_id]["units"]
    cost_per_point = max(
        1,
        sum(
            units.get(entry.unit_name, {"repair_cost_per_point": 1})["repair_cost_per_point"]
            * entry.quantity
            for entry in target.roster
        ),
    )
    points_needed = max(0, 100 - target.condition)
    actors = state.map_metadata["strategic_actor_runtime"]["actors"]
    resources = int(actors[actor_id]["resources"])
    affordable = 0 if cost_per_point <= 0 else resources // cost_per_point
    if target.condition >= 100:
        blocked.append("Formation is already at full condition.")
    if target.supply < 50:
        blocked.append("Formation must be supplied to repair.")
    if target.encircled_turns > 0:
        blocked.append("Encircled formations cannot repair.")
    if points_needed > 0 and affordable <= 0:
        blocked.append("Insufficient actor treasury to repair.")
    return {
        "can_repair": not blocked and points_needed > 0,
        "blocked_reasons": blocked,
        "battalion_id": target.battalion_id,
        "condition": target.condition,
        "supply": target.supply,
        "encircled_turns": target.encircled_turns,
        "points_needed": points_needed,
        "cost_per_point": cost_per_point,
        "affordable_points": min(points_needed, affordable),
        "total_cost": min(points_needed, affordable) * cost_per_point,
    }


def _legacy_faction_panel(state: CampaignState, raw: dict[str, Any]) -> dict[str, Any]:
    from .economy import available_research, formation_recruitment_offers

    faction = Faction(str(raw.get("faction") or state.selected_faction.value))
    faction_state = state.factions[faction.value]
    formation_id = _formation_id(raw)
    battalion_id = raw.get("battalion") or raw.get("battalion_id")
    battalion_id = "" if battalion_id in (None, "") else str(battalion_id)
    force = state.strategic_formations.get(formation_id) if formation_id else None
    template_id = force.template_formation_id if force is not None else formation_id
    can_manage = bool(force is not None and force.faction == faction)
    blocked: list[str] = []
    if not formation_id:
        blocked.append("Select a strategic formation.")
    elif force is None:
        blocked.append(f"Unknown strategic formation: {formation_id}")
    elif not can_manage:
        blocked.append(f"Formation belongs to {force.faction.value}, not {faction.value}")

    offers: list[dict[str, Any]] = []
    pool: list[dict[str, Any]] = []
    repair = {
        "can_repair": False,
        "blocked_reasons": list(blocked),
        "battalion_id": battalion_id,
        "condition": 0,
        "supply": 0,
        "encircled_turns": 0,
        "points_needed": 0,
        "cost_per_point": 0,
        "affordable_points": 0,
        "total_cost": 0,
    }
    if can_manage and force is not None and state.unit_economy:
        try:
            offers = [
                asdict(item) for item in formation_recruitment_offers(state, template_id)
            ]
        except KeyError:
            offers = []
        pool = [
            asdict(entry)
            for entry in faction_state.reinforcement_pool
            if entry.formation_id == template_id
        ]
        members = [item for item in force.battalion_ids if item in state.battalions]
        target_id = battalion_id if battalion_id in members else (members[0] if len(members) == 1 else "")
        if target_id:
            repair = _legacy_repair_quote(state, target_id, faction_state.resources)
        elif not members:
            repair["blocked_reasons"] = ["Formation has no battalion."]
        else:
            repair["blocked_reasons"] = ["Specify battalion_id when a formation has multiple battalions."]

    return {
        "actor_id": faction.value,
        "display_name": faction.value.upper(),
        "short_name": faction.value.upper(),
        "tactical_side": faction.value,
        "resources": faction_state.resources,
        "income_last_round": faction_state.income_last_round,
        "maintenance_last_round": faction_state.maintenance_last_round,
        "researched_keys": list(faction_state.researched_keys),
        "available_research": [
            asdict(item) for item in available_research(state, faction)
        ]
        if state.research_nodes
        else [],
        "command_actor_id": faction.value,
        "command_display_name": faction.value.upper(),
        "formation_id": formation_id,
        "formation_actor_id": force.actor_id if force is not None else "",
        "battalion_id": battalion_id,
        "can_manage_formation": can_manage,
        "blocked_reasons": blocked,
        "recruitment_offers": offers,
        "reinforcement_pool": pool,
        "repair": repair,
        "content_installed": False,
    }


def _legacy_repair_quote(
    state: CampaignState,
    battalion_id: str,
    resources: int,
) -> dict[str, Any]:
    from .models import UnitEconomy

    target = state.battalions[battalion_id]
    cost_per_point = max(
        1,
        sum(
            state.unit_economy.get(
                entry.unit_name,
                UnitEconomy(entry.unit_name, target.faction, entry.category, 0, 0, 1),
            ).repair_cost_per_point
            * entry.quantity
            for entry in target.roster
        ),
    )
    points_needed = max(0, 100 - target.condition)
    affordable = 0 if cost_per_point <= 0 else resources // cost_per_point
    blocked: list[str] = []
    if target.condition >= 100:
        blocked.append("Formation is already at full condition.")
    if target.supply < 50:
        blocked.append("Formation must be supplied to repair.")
    if target.encircled_turns > 0:
        blocked.append("Encircled formations cannot repair.")
    if points_needed > 0 and affordable <= 0:
        blocked.append("Insufficient treasury to repair.")
    return {
        "can_repair": not blocked and points_needed > 0,
        "blocked_reasons": blocked,
        "battalion_id": target.battalion_id,
        "condition": target.condition,
        "supply": target.supply,
        "encircled_turns": target.encircled_turns,
        "points_needed": points_needed,
        "cost_per_point": cost_per_point,
        "affordable_points": min(points_needed, affordable),
        "total_cost": min(points_needed, affordable) * cost_per_point,
    }
