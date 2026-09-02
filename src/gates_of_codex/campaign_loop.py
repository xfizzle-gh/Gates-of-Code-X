"""Run the Europe 4X loop: import GoH result, AI turns, export the next fight."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .bridge.result import BattleImportResult
from .campaign import CampaignEngine
from .front_attack import (
    DEFAULT_VISIBLE_NAME,
    advance_to_player,
    attack_front,
    resolve_attack_save_path,
)
from .service import GatesOfCodeXService
from .state_io import load_campaign, save_campaign
from .strategic import evaluate_campaign_outcome


def continue_campaign(
    campaign_path: str | Path,
    *,
    save_path: str | Path | None = None,
    code_x_directory: str | Path | None = None,
    map_name: str | None = None,
    simulate: bool = False,
    turns: int = 1,
    seed: int = 0,
    export: bool = True,
    snapshot_path: str | Path | None = None,
) -> dict[str, Any]:
    """Advance the campaign as far as possible without a live GoH fight.

    Live: import a completed Conquest save if GoH rewrote it, run AI, export the
    next NATO attack into gatesofcodex.sav. If the pending fight is still
    unplayed, re-export and wait.

    ``simulate=True`` auto-resolves the player's pending battle so the 4X loop
    can run unattended.
    """

    if turns < 1:
        raise ValueError("turns must be at least 1")
    reports: list[dict[str, Any]] = []
    last: dict[str, Any] = {}
    for index in range(turns):
        last = _continue_once(
            campaign_path,
            save_path=save_path,
            code_x_directory=code_x_directory,
            map_name=map_name,
            simulate=simulate,
            seed=seed + index,
            export=export,
        )
        reports.append(last)
        if last.get("status") == "waiting_for_conquest" and not simulate:
            break
        if last.get("status") == "complete":
            break
    payload = {
        "turns_run": len(reports),
        "status": last.get("status"),
        "turn_number": last.get("turn_number"),
        "current_faction": last.get("current_faction"),
        "pending_battle": last.get("pending_battle"),
        "save": last.get("save"),
        "visible_name": last.get("visible_name", DEFAULT_VISIBLE_NAME),
        "load_instruction": last.get("load_instruction"),
        "owners": last.get("owners"),
        "steps": last.get("steps"),
        "reports": reports,
    }
    if snapshot_path:
        from .frontend import write_frontend_snapshot
        from .state_io import load_campaign as _load

        state = _load(campaign_path)
        payload["snapshot"] = str(
            write_frontend_snapshot(state, snapshot_path, campaign_path=campaign_path).resolve()
        )
    return payload


def overmap_turn(campaign_path: str | Path, *, seed: int = 0) -> dict[str, Any]:
    """One strategic 4X turn on the overmap. Battles auto-resolve. No Conquest export."""

    from .forces import ensure_faction_forces
    from .play_context import list_front_options

    campaign = Path(campaign_path).resolve()
    state = load_campaign(campaign)
    ensure_faction_forces(state)
    save_campaign(state, campaign)
    steps: list[dict[str, Any]] = []
    if state.pending_battle is not None:
        winner = CampaignEngine(state).auto_resolve_pending_battle()
        save_campaign(state, campaign)
        steps.append({"op": "resolve", "winner": winner.value})

    state = load_campaign(campaign)
    faction_state = state.factions.get(state.current_faction.value)
    human_turn = faction_state is not None and faction_state.is_human_controlled
    if human_turn:
        fought: set[str] = set()
        for _ in range(16):
            state = load_campaign(campaign)
            combat = [
                row
                for row in list_front_options(state)
                if row.get("kind") in {"battle", "capture"}
                and str(row.get("battalion_id")) not in fought
            ]
            if not combat:
                break
            pick = combat[0]
            fought.add(str(pick["battalion_id"]))
            action = attack_front(
                campaign,
                battalion_id=str(pick["battalion_id"]),
                target=str(pick["target"]),
                kind=str(pick["kind"]),
                export=False,
            )
            steps.append({"op": "action", "option": action.get("option"), "moved": action.get("moved")})
            state = load_campaign(campaign)
            if state.pending_battle is not None:
                winner = CampaignEngine(state).auto_resolve_pending_battle()
                save_campaign(state, campaign)
                steps.append({"op": "resolve", "winner": winner.value})
                ensure_faction_forces(state)
                save_campaign(state, campaign)
            if not action.get("moved") and not action.get("pending_created") and not action.get("pending_battle"):
                break

    from .strategic_ai import StrategicAI

    state = load_campaign(campaign)
    faction_state = state.factions.get(state.current_faction.value)
    human_turn = faction_state is not None and faction_state.is_human_controlled
    if not human_turn:
        state = load_campaign(campaign)
        return _finish_player_then_ai(campaign, state, steps, seed=seed)

    for battalion_id in sorted(
        battalion.battalion_id
        for battalion in state.battalions.values()
        if battalion.faction == state.current_faction
    ):
        state = load_campaign(campaign)
        battalion = state.battalions.get(battalion_id)
        if battalion is None or battalion.movement_remaining <= 0 or battalion.condition <= 20:
            continue
        step = StrategicAI(state, random_seed=seed)._next_step_to_front(battalion)
        if not step:
            continue
        options = [
            row
            for row in list_front_options(state)
            if row["battalion_id"] == battalion_id and row["target"] == step
        ]
        if not options:
            continue
        pick = options[0]
        action = attack_front(
            campaign,
            battalion_id=battalion_id,
            target=step,
            kind=str(pick["kind"]),
            export=False,
        )
        steps.append({"op": "march", "option": action.get("option"), "moved": action.get("moved")})
        state = load_campaign(campaign)
        if state.pending_battle is not None:
            winner = CampaignEngine(state).auto_resolve_pending_battle()
            save_campaign(state, campaign)
            steps.append({"op": "resolve", "winner": winner.value})
            ensure_faction_forces(state)
            save_campaign(state, campaign)

    state = load_campaign(campaign)
    return _finish_player_then_ai(campaign, state, steps, seed=seed)


def finish_player_overmap_turn(
    campaign_path: str | Path,
    *,
    seed: int = 0,
    auto_resolve: bool = True,
) -> dict[str, Any]:
    """Interactive 4X: keep the player's moves, then run AI until NATO is current."""

    from .forces import ensure_faction_forces

    campaign = Path(campaign_path).resolve()
    state = load_campaign(campaign)
    ensure_faction_forces(state)
    save_campaign(state, campaign)
    steps: list[dict[str, Any]] = []
    if state.pending_battle is not None:
        if not auto_resolve:
            waiting = _summary(campaign)
            waiting.update({"status": "waiting_for_conquest", "steps": steps})
            return waiting
        winner = CampaignEngine(state).auto_resolve_pending_battle()
        save_campaign(state, campaign)
        steps.append({"op": "resolve", "winner": winner.value})
        state = load_campaign(campaign)
    return _finish_player_then_ai(campaign, state, steps, seed=seed)


def _finish_player_then_ai(
    campaign: Path,
    state,
    steps: list[dict[str, Any]],
    *,
    seed: int,
) -> dict[str, Any]:
    from .forces import ensure_faction_forces

    faction_state = state.factions.get(state.current_faction.value)
    if faction_state is not None and faction_state.is_human_controlled and state.pending_battle is None:
        nxt = CampaignEngine(state).end_turn()
        save_campaign(state, campaign)
        steps.append({"op": "end_player_turn", "next": nxt.value})
    advanced = advance_to_player(campaign, seed=seed)
    steps.append({"op": "advance", "turn_number": advanced.get("turn_number")})
    state = load_campaign(campaign)
    ensure_faction_forces(state)
    save_campaign(state, campaign)
    outcome = evaluate_campaign_outcome(state)
    summary = _summary(campaign)
    summary.update(
        {
            "status": "complete" if str(outcome.status) == "complete" else "ready",
            "steps": steps,
            "outcome": asdict(outcome),
        }
    )
    return summary


def overmap_campaign(
    campaign_path: str | Path,
    *,
    turns: int = 1,
    seed: int = 0,
    snapshot_path: str | Path | None = None,
) -> dict[str, Any]:
    if turns < 1:
        raise ValueError("turns must be at least 1")
    reports = []
    last: dict[str, Any] = {}
    for index in range(turns):
        last = overmap_turn(campaign_path, seed=seed + index)
        reports.append(last)
        if last.get("status") == "complete":
            break
    payload = {
        "turns_run": len(reports),
        "status": last.get("status"),
        "turn_number": last.get("turn_number"),
        "current_faction": last.get("current_faction"),
        "pending_battle": last.get("pending_battle"),
        "owners": last.get("owners"),
        "reports": reports,
    }
    if snapshot_path:
        from .frontend import write_frontend_snapshot

        state = load_campaign(campaign_path)
        payload["snapshot"] = str(
            write_frontend_snapshot(state, snapshot_path, campaign_path=campaign_path).resolve()
        )
    return payload


def watch_campaign(
    campaign_path: str | Path,
    *,
    save_path: str | Path | None = None,
    code_x_directory: str | Path | None = None,
    interval_seconds: float = 20.0,
    snapshot_path: str | Path | None = None,
) -> dict[str, Any]:
    """Keep importing finished fights and exporting the next one until the campaign ends."""

    import time

    last: dict[str, Any] = {}
    while True:
        payload = continue_campaign(
            campaign_path,
            save_path=save_path,
            code_x_directory=code_x_directory,
            snapshot_path=snapshot_path,
        )
        last = payload
        if payload.get("status") == "complete":
            return payload
        time.sleep(max(5.0, float(interval_seconds)))


def play_campaign(
    campaign_path: str | Path,
    *,
    code_x_directory: str | Path | None = None,
    save_path: str | Path | None = None,
    launch: bool = True,
    watch: bool = False,
    interval_seconds: float = 15.0,
    snapshot_path: str | Path | None = "godot/campaign_snapshot.json",
) -> dict[str, Any]:
    """Export the current fight, optionally launch GoH, and optionally watch for results."""

    from .launcher import launch_game

    campaign = Path(campaign_path).resolve()
    payload = continue_campaign(
        campaign,
        save_path=save_path,
        code_x_directory=code_x_directory,
        snapshot_path=snapshot_path,
    )
    launched = False
    state = load_campaign(campaign)
    if launch and state.game_directory:
        launch_game(state.game_directory)
        launched = True
    payload["launched"] = launched
    payload["load_instruction"] = payload.get("load_instruction") or "Load this exact Conquest entry: GatesOfCodeX"
    if watch:
        watched = watch_campaign(
            campaign,
            save_path=save_path,
            code_x_directory=code_x_directory,
            interval_seconds=interval_seconds,
            snapshot_path=snapshot_path,
        )
        watched["launched"] = launched
        return watched
    return payload


def _continue_once(
    campaign_path: str | Path,
    *,
    save_path: str | Path | None,
    code_x_directory: str | Path | None,
    map_name: str | None,
    simulate: bool,
    seed: int,
    export: bool,
) -> dict[str, Any]:
    campaign = Path(campaign_path).resolve()
    state = load_campaign(campaign)
    steps: list[dict[str, Any]] = []
    hint = resolve_attack_save_path(state, save_path)

    if state.pending_battle is not None:
        imported = _try_import(campaign, hint)
        if imported is not None:
            steps.append(
                {
                    "op": "import",
                    "winner": imported.winner.value,
                    "player_won": imported.player_won,
                    "survivors": imported.survivor_counts,
                }
            )
        elif simulate:
            winner = CampaignEngine(state).auto_resolve_pending_battle()
            save_campaign(state, campaign)
            steps.append({"op": "simulate", "winner": winner.value})
        else:
            already = ""
            if state.pending_battle is not None:
                already = str(state.pending_battle.exported_save_path or "")
            if already and Path(already).is_file():
                waiting = {
                    "status": "waiting_for_conquest",
                    "save": already,
                    "load_instruction": f"Load this exact Conquest entry: {DEFAULT_VISIBLE_NAME}",
                    "steps": steps + [{"op": "wait", "save": already}],
                    "moved": False,
                    "pending_created": False,
                    "pending_battle": state.pending_battle.battle_id,
                    "visible_name": DEFAULT_VISIBLE_NAME,
                    "attacker": state.pending_battle.attacker_faction.value,
                    "defender": state.pending_battle.defender_faction.value,
                    "origin": state.pending_battle.origin_province_id,
                    "target": state.pending_battle.target_province_id,
                }
                waiting.update(_summary(campaign))
                return waiting
            attack = attack_front(
                campaign,
                code_x_directory=code_x_directory or state.code_x_directory,
                save_path=hint,
                map_name=map_name,
                export=export,
            )
            attack["status"] = "waiting_for_conquest"
            attack["steps"] = steps + [{"op": "wait", "save": attack.get("save")}]
            attack.update(_summary(campaign))
            return attack

    state = load_campaign(campaign)
    outcome = evaluate_campaign_outcome(state)
    if str(outcome.status) == "complete" or state.map_metadata.get("campaign_outcome", {}).get("status") == "complete":
        save_campaign(state, campaign)
        return {
            "status": "complete",
            "steps": steps,
            "outcome": asdict(outcome),
            **_summary(campaign),
        }

    if state.pending_battle is None:
        resolved = any(step.get("op") in {"import", "simulate"} for step in steps)
        faction_state = state.factions.get(state.current_faction.value)
        if resolved and faction_state is not None and faction_state.is_human_controlled:
            CampaignEngine(state).end_turn()
            save_campaign(state, campaign)
            steps.append(
                {
                    "op": "end_player_turn",
                    "current_faction": state.current_faction.value,
                    "turn_number": state.turn_number,
                }
            )
        advanced = advance_to_player(campaign, seed=seed)
        steps.append({"op": "advance", **{key: value for key, value in advanced.items() if key != "actions"}})
        if advanced.get("actions"):
            steps[-1]["action_count"] = len(advanced["actions"])
            steps[-1]["actions"] = advanced["actions"]

    state = load_campaign(campaign)
    outcome = evaluate_campaign_outcome(state)
    if str(outcome.status) == "complete" or state.map_metadata.get("campaign_outcome", {}).get("status") == "complete":
        save_campaign(state, campaign)
        return {
            "status": "complete",
            "steps": steps,
            "outcome": asdict(outcome),
            **_summary(campaign),
        }

    try:
        attack = attack_front(
            campaign,
            code_x_directory=code_x_directory or state.code_x_directory,
            save_path=hint,
            map_name=map_name,
            export=export,
        )
    except RuntimeError as exc:
        return {
            "status": "ready",
            "error": str(exc),
            "steps": steps + [{"op": "attack", "error": str(exc)}],
            **_summary(campaign),
        }
    attack["status"] = "waiting_for_conquest" if export and attack.get("save") else "ready"
    if simulate and not export:
        attack["status"] = "ready"
    attack["steps"] = steps + [{"op": "attack", "pending_battle": attack.get("pending_battle")}]
    attack.update(_summary(campaign))
    return attack


def _try_import(campaign: Path, hint: Path) -> BattleImportResult | None:
    if not hint.exists() and not hint.parent.is_dir():
        return None
    target = hint if hint.exists() else hint.parent
    try:
        return GatesOfCodeXService().import_battle(campaign, save_path=target)
    except FileNotFoundError:
        return None
    except ValueError as exc:
        message = str(exc)
        if "does not show a newly completed battle" in message:
            return None
        if "no pending battle" in message.lower():
            return None
        if "does not match" in message or "different campaign" in message:
            return None
        raise


def _summary(campaign: Path) -> dict[str, Any]:
    state = load_campaign(campaign)
    owners: dict[str, int] = {}
    for province in state.provinces.values():
        owners[province.owner.value] = owners.get(province.owner.value, 0) + 1
    return {
        "turn_number": state.turn_number,
        "current_faction": state.current_faction.value,
        "pending_battle": state.pending_battle.battle_id if state.pending_battle else None,
        "owners": owners,
        "visible_name": DEFAULT_VISIBLE_NAME,
    }
