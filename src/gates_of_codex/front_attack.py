"""Open a Europe 4X front battle and export a live Conquest save."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .campaign import CampaignEngine
from .models import CampaignState, Faction
from .play_context import default_install_save_path, list_front_options, tactical_map_for_province
from .service import GatesOfCodeXService, goh_conquest_save_filename
from .state_io import load_campaign, save_campaign
from .strategic_ai import StrategicAI


DEFAULT_VISIBLE_NAME = "GatesOfCodeX"
DEFAULT_MODS = (
    "mod_2897299509:0",
    "mod_3261086933:0",
    "mod_3636883799:0",
)


def pick_front_option(
    state: CampaignState,
    *,
    battalion_id: str | None = None,
    target: str | None = None,
    kind: str | None = "battle",
) -> dict[str, Any]:
    options = list_front_options(state)
    if battalion_id and target:
        for row in options:
            if row["battalion_id"] == battalion_id and row["target"] == target:
                return row
        raise ValueError(f"No legal front option {battalion_id} -> {target}")
    if kind:
        matching = [row for row in options if row.get("kind") == kind]
    else:
        matching = list(options)
    if not matching:
        label = kind or "action"
        raise RuntimeError(f"No front-line {label} is available for {state.current_faction.value}")
    return matching[0]


def resolve_attack_save_path(state: CampaignState, save_path: str | Path | None = None) -> Path:
    if save_path:
        return Path(save_path).expanduser().resolve()
    install = str(state.map_metadata.get("install_directory") or "").strip()
    if install:
        return default_install_save_path(install, DEFAULT_VISIBLE_NAME)
    if state.profile_directory:
        campaign_dir = Path(state.profile_directory).expanduser().resolve() / "campaign"
        return default_install_save_path(campaign_dir, DEFAULT_VISIBLE_NAME)
    return Path("live") / goh_conquest_save_filename(DEFAULT_VISIBLE_NAME)


def attack_front(
    campaign_path: str | Path,
    *,
    battalion_id: str | None = None,
    target: str | None = None,
    kind: str = "battle",
    code_x_directory: str | Path | None = None,
    save_path: str | Path | None = None,
    map_name: str | None = None,
    export: bool = True,
) -> dict[str, Any]:
    campaign = Path(campaign_path).resolve()
    state = load_campaign(campaign)
    option: dict[str, Any] | None = None
    pending_created = False
    if state.pending_battle is None:
        from .forces import ensure_faction_forces

        ensure_faction_forces(state)
        try:
            option = pick_front_option(
                state,
                battalion_id=battalion_id,
                target=target,
                kind=kind or None,
            )
        except (RuntimeError, ValueError):
            option = None
            for try_kind in ("battle", "capture", "neutral", "move"):
                try:
                    option = pick_front_option(state, kind=try_kind)
                    break
                except RuntimeError:
                    continue
            if option is None:
                save_campaign(state, campaign)
                return {
                    "moved": False,
                    "pending_created": False,
                    "pending_battle": None,
                    "option": None,
                    "status": "ready",
                }
        result = CampaignEngine(state).move_or_attack(option["battalion_id"], option["target"])
        pending_created = result.pending_battle is not None
        save_campaign(state, campaign)
        if result.pending_battle is None:
            return {
                "moved": True,
                "pending_created": False,
                "pending_battle": None,
                "option": option,
                "status": "ready",
            }

    payload: dict[str, Any] = {
        "moved": False,
        "pending_created": pending_created,
        "pending_battle": state.pending_battle.battle_id if state.pending_battle else None,
        "option": option,
        "attacker": state.pending_battle.attacker_faction.value if state.pending_battle else None,
        "defender": state.pending_battle.defender_faction.value if state.pending_battle else None,
        "origin": state.pending_battle.origin_province_id if state.pending_battle else None,
        "target": state.pending_battle.target_province_id if state.pending_battle else None,
        "origin_name": (
            state.provinces[state.pending_battle.origin_province_id].display_name
            if state.pending_battle
            else None
        ),
        "target_name": (
            state.provinces[state.pending_battle.target_province_id].display_name
            if state.pending_battle
            else None
        ),
        "visible_name": DEFAULT_VISIBLE_NAME,
    }
    if not export or state.pending_battle is None:
        return payload

    chosen_map = _choose_export_map(state, map_name)
    destination = resolve_attack_save_path(state, save_path)
    manifest = GatesOfCodeXService().export_battle(
        campaign,
        code_x_directory=code_x_directory or state.code_x_directory,
        save_path=destination,
        map_name=chosen_map,
        allow_overwrite=True,
        campaign_name=DEFAULT_VISIBLE_NAME,
        mods=list(DEFAULT_MODS),
    )
    payload["manifest"] = asdict(manifest)
    payload["save"] = manifest.save_path
    payload["map"] = chosen_map
    payload["load_instruction"] = f"Load this exact Conquest entry: {DEFAULT_VISIBLE_NAME}"
    state = load_campaign(campaign)
    history = [str(value) for value in state.map_metadata.get("used_tactical_maps", []) if value]
    history.append(chosen_map)
    state.map_metadata["used_tactical_maps"] = history[-12:]
    save_campaign(state, campaign)
    return payload


def _choose_export_map(state: CampaignState, explicit: str | None) -> str:
    from .europe import CODEX_MAPS
    from .play_context import select_tactical_map, tactical_map_for_province

    pending = state.pending_battle
    if pending is None:
        raise RuntimeError("No pending battle to choose a map for")
    province_map = tactical_map_for_province(state, pending.target_province_id, None)
    used = [str(value) for value in state.map_metadata.get("used_tactical_maps", []) if value]
    return select_tactical_map(
        CODEX_MAPS,
        preferred=province_map,
        used=used,
        battle_id=pending.battle_id,
        explicit=explicit,
    )


def advance_to_player(campaign_path: str | Path, *, seed: int = 0) -> dict[str, Any]:
    """Run AI factions until the human player is current, auto-resolving AI battles."""

    campaign = Path(campaign_path).resolve()
    state = load_campaign(campaign)
    engine = CampaignEngine(state)
    actions: list[dict[str, Any]] = []
    guard = 0
    while guard < 12:
        guard += 1
        if state.pending_battle is not None:
            break
        from .strategic import evaluate_campaign_outcome

        outcome = evaluate_campaign_outcome(state)
        if str(outcome.status) == "complete":
            break
        if all(
            not faction_state.is_human_controlled or faction_state.is_eliminated
            for faction_state in state.factions.values()
        ):
            break
        faction = state.current_faction
        faction_state = state.factions.get(faction.value)
        if faction_state is None or faction_state.is_human_controlled:
            break
        taken = StrategicAI(state, random_seed=seed + guard).take_turn(faction)
        actions.extend(asdict(item) | {"faction": faction.value} for item in taken)
        if state.pending_battle is not None:
            break
        outcome = evaluate_campaign_outcome(state)
        if str(outcome.status) == "complete":
            break
        previous = state.current_faction
        engine.end_turn()
        if state.current_faction == previous:
            break
    save_campaign(state, campaign)
    return {
        "turn_number": state.turn_number,
        "current_faction": state.current_faction.value,
        "pending_battle": state.pending_battle.battle_id if state.pending_battle else None,
        "actions": actions,
    }
