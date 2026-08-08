from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .campaign import CampaignEngine
from .models import Faction
from .state_io import load_campaign, save_campaign
from .strategic import build_infrastructure
from .strategic_ai import StrategicAI


@dataclass(slots=True)
class CommandResult:
    op: str
    ok: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class _FrontendReportingCampaignEngine(CampaignEngine):
    """Capture existing finalization output for transient frontend presentation."""

    def __init__(self, state) -> None:
        super().__init__(state)
        self.last_battle_finalization = None

    def apply_battle_result(self, winner: Faction):
        report = super().apply_battle_result(winner)
        self.last_battle_finalization = report
        return report


def default_commands_path(snapshot_path: str | Path) -> Path:
    path = Path(snapshot_path)
    return path.with_name("frontend_commands.json")


def read_commands(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.is_file():
        return []
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        commands = payload.get("commands", [])
        return [item for item in commands if isinstance(item, dict)]
    return []


def write_commands(path: str | Path, commands: list[dict[str, Any]]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"commands": commands}, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
        delete=False,
    ) as temporary:
        temporary.write(body)
        temporary_path = Path(temporary.name)
    temporary_path.replace(destination)
    return destination


def clear_commands(path: str | Path) -> None:
    write_commands(path, [])


def apply_frontend_commands(
    campaign_path: str | Path,
    *,
    commands: list[dict[str, Any]] | None = None,
    commands_path: str | Path | None = None,
    snapshot_path: str | Path | None = None,
) -> dict[str, Any]:
    campaign = Path(campaign_path).resolve()
    command_file = Path(commands_path).resolve() if commands_path else None
    pending = list(commands) if commands is not None else read_commands(command_file) if command_file else []
    state = load_campaign(campaign)
    results: list[CommandResult] = []

    for raw in pending:
        op = str(raw.get("op", "")).strip().lower()
        before_presentations = _formation_presentation_rows(state)
        try:
            if op == "handoff":
                result = _apply_handoff(campaign, state, raw)
                state = load_campaign(campaign)
            elif op == "import_battle":
                result = _apply_import_battle(campaign, state, raw)
                state = load_campaign(campaign)
            else:
                result = _apply_one(state, op, raw)
        except Exception as exc:  # noqa: BLE001 - surface operator errors in result list
            result = CommandResult(op=op or "unknown", ok=False, detail=str(exc))
        if result.ok:
            presentation = {
                "movements": _movement_presentation_delta(
                    before_presentations,
                    _formation_presentation_rows(state),
                )
            }
            battle_finalization = result.data.pop(
                "_battle_finalization_presentation", None
            )
            if battle_finalization is not None:
                presentation["battle_finalization"] = battle_finalization
            result.data["operational_presentation"] = presentation
        results.append(result)
        if not result.ok:
            break

    save_campaign(state, campaign)
    snapshot = ""
    if snapshot_path:
        from .frontend import write_frontend_snapshot

        snapshot = str(
            write_frontend_snapshot(
                state,
                snapshot_path,
                campaign_path=campaign,
            ).resolve()
        )
    if command_file is not None:
        clear_commands(command_file)

    return {
        "ok": all(item.ok for item in results) if results else True,
        "campaign_path": str(campaign),
        "snapshot_path": snapshot,
        "commands_applied": len([item for item in results if item.ok]),
        "results": [asdict(item) for item in results],
        "pending_battle": state.pending_battle.battle_id if state.pending_battle else None,
        "current_faction": state.current_faction.value,
        "turn_number": state.turn_number,
    }


def _formation_presentation_rows(state) -> dict[str, dict[str, Any]]:
    from .operational_movement import move_order_to_dict
    from .operational_position import position_to_dict, resolve_display_pixel

    rows: dict[str, dict[str, Any]] = {}
    for force in sorted(
        state.strategic_formations.values(),
        key=lambda value: value.strategic_formation_id,
    ):
        order = move_order_to_dict(force.move_order) or {}
        rows[force.strategic_formation_id] = {
            "position": position_to_dict(force.position),
            "pixel": resolve_display_pixel(state, force),
            "path_node_ids": list(order.get("path_node_ids") or []),
            "path_edge_ids": list(order.get("path_edge_ids") or []),
        }
    return rows


def _movement_presentation_delta(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    movements: list[dict[str, Any]] = []
    for formation_id in sorted(set(before) & set(after)):
        start = before[formation_id]
        end = after[formation_id]
        if (
            start.get("position") == end.get("position")
            and start.get("pixel") == end.get("pixel")
        ):
            continue
        path_node_ids = list(
            start.get("path_node_ids") or end.get("path_node_ids") or []
        )
        path_edge_ids = list(
            start.get("path_edge_ids") or end.get("path_edge_ids") or []
        )
        movements.append(
            {
                "formation_id": formation_id,
                "start_position": start.get("position"),
                "end_position": end.get("position"),
                "start_pixel": start.get("pixel"),
                "end_pixel": end.get("pixel"),
                "path_node_ids": path_node_ids,
                "path_edge_ids": path_edge_ids,
            }
        )
    return movements


def _battle_finalization_presentation(state, winner: Faction, report) -> dict[str, Any]:
    from .operational_position import resolve_display_pixel

    outcomes: list[dict[str, Any]] = []
    for outcome in tuple(getattr(report, "retreat_outcomes", ()) or ()):
        force = state.strategic_formations.get(outcome.formation_id)
        destination_pixel = (
            resolve_display_pixel(state, force)
            if force is not None and outcome.destination_node_id
            else None
        )
        outcomes.append(
            {
                "formation_id": outcome.formation_id,
                "destination_node_id": outcome.destination_node_id,
                "destination_province_id": outcome.destination_province_id,
                "destination_pixel": destination_pixel,
                "reason": outcome.reason,
            }
        )
    return {
        "winner": winner.value,
        "retreat_outcomes": outcomes,
    }


def _apply_handoff(campaign: Path, state, raw: dict[str, Any]) -> CommandResult:
    from .stack_acceptance import prepare_stack_handoff

    if state.pending_battle is None:
        raise ValueError("No pending battle to hand off")
    root = campaign.parent
    work_root = Path(str(raw.get("work_root", root / "live")))
    if not work_root.is_absolute():
        work_root = (root / work_root).resolve()
    backup_root = Path(str(raw.get("backup_root", root / "backups")))
    if not backup_root.is_absolute():
        backup_root = (root / backup_root).resolve()
    result = prepare_stack_handoff(
        campaign,
        map_name=str(raw["map"]) if raw.get("map") else None,
        work_root=work_root,
        backup_root=backup_root,
        launch=bool(raw.get("launch", False)),
    )
    visible = result.visible_campaign_name or result.manifest.visible_campaign_name
    return CommandResult(
        op="handoff",
        ok=True,
        detail=f"installed {visible}",
        data={
            "visible_campaign_name": visible,
            "installed_save_path": str(result.installed_save_path or ""),
            "verify_command": result.verify_command or "",
            "import_command": result.import_command or "",
            "battle_id": state.pending_battle.battle_id if state.pending_battle else "",
        },
    )


def _apply_import_battle(
    campaign: Path,
    state,
    raw: dict[str, Any],
) -> CommandResult:
    from .acceptance import verify_tactical_result
    from .service import GatesOfCodeXService
    from .stack_acceptance import verify_stack_result

    pending = state.pending_battle
    if pending is None:
        raise ValueError("No pending battle to import")
    save_path = str(raw.get("save_path") or pending.exported_save_path or "").strip()
    if not save_path:
        raise ValueError("Pending battle has no handed-off GoH save path")

    service = GatesOfCodeXService()
    manifest = service.load_manifest(service.manifest_path(save_path))
    resource_stack = (
        state.map_metadata.get("resource_stack", []) or manifest.resource_stack
    )
    stack_config = state.map_metadata.get("stack_config")
    if resource_stack or state.code_x_directory:
        verification = verify_stack_result(
            campaign,
            save_path=save_path,
            code_x_directory=state.code_x_directory or None,
            resource_stack=resource_stack or None,
            stack_config=stack_config or None,
        )
    else:
        verification = verify_tactical_result(
            campaign,
            save_path=save_path,
            code_x_directory=None,
        )
    if not verification.ok:
        detail = "; ".join(verification.errors) or "unknown verification failure"
        raise ValueError(f"GoH result verification failed: {detail}")

    imported = service.import_battle(campaign, save_path=save_path)
    finalized_state = load_campaign(campaign)
    return CommandResult(
        op="import_battle",
        ok=True,
        detail=f"winner {imported.winner.value}",
        data={
            "winner": imported.winner.value,
            "survivors": imported.survivor_counts,
            "_battle_finalization_presentation": _battle_finalization_presentation(
                finalized_state,
                imported.winner,
                imported.finalization_report,
            ),
        },
    )


def _apply_one(state, op: str, raw: dict[str, Any]) -> CommandResult:
    if op in {"", "refresh", "noop"}:
        return CommandResult(op=op or "refresh", ok=True, detail="snapshot refresh only")
    if op == "move":
        battalion = str(raw.get("battalion") or raw.get("battalion_id") or "")
        province = str(raw.get("province") or raw.get("target") or raw.get("province_id") or "")
        if not battalion or not province:
            raise ValueError("move requires battalion and province")
        result = CampaignEngine(state).move_or_attack(battalion, province)
        detail = "battle created" if result.pending_battle else "moved"
        return CommandResult(
            op=op,
            ok=True,
            detail=detail,
            data={
                "battalion": battalion,
                "province": province,
                "pending_battle": result.pending_battle.battle_id if result.pending_battle else "",
            },
        )
    if op == "auto_resolve":
        engine = _FrontendReportingCampaignEngine(state)
        winner = engine.auto_resolve_pending_battle()
        return CommandResult(
            op=op,
            ok=True,
            detail=f"winner {winner.value}",
            data={
                "winner": winner.value,
                "_battle_finalization_presentation": _battle_finalization_presentation(
                    state,
                    winner,
                    engine.last_battle_finalization,
                ),
            },
        )
    if op == "issue_move_order":
        from .operational_movement import issue_move_order, move_order_to_dict

        formation_id = str(
            raw.get("formation")
            or raw.get("formation_id")
            or raw.get("strategic_formation_id")
            or ""
        )
        path_nodes = [str(item) for item in raw.get("path_node_ids") or raw.get("nodes") or []]
        path_edges = [str(item) for item in raw.get("path_edge_ids") or raw.get("edges") or []]
        if not formation_id or not path_nodes:
            raise ValueError("issue_move_order requires formation and path_node_ids")
        order = issue_move_order(
            state,
            formation_id,
            path_node_ids=path_nodes,
            path_edge_ids=path_edges,
            destination_site_id=(
                None
                if raw.get("destination_site_id") in (None, "")
                else str(raw.get("destination_site_id"))
            ),
            order_id=None if raw.get("order_id") in (None, "") else str(raw.get("order_id")),
        )
        return CommandResult(
            op=op,
            ok=True,
            detail=f"draft {order.order_id}",
            data={"move_order": move_order_to_dict(order)},
        )
    if op == "cancel_move_order":
        from .operational_movement import cancel_move_order, move_order_to_dict

        formation_id = str(
            raw.get("formation")
            or raw.get("formation_id")
            or raw.get("strategic_formation_id")
            or ""
        )
        if not formation_id:
            raise ValueError("cancel_move_order requires formation")
        order = cancel_move_order(state, formation_id)
        return CommandResult(
            op=op,
            ok=True,
            detail="cancelled" if order else "none",
            data={"move_order": move_order_to_dict(order)},
        )
    if op == "commit_move_orders":
        from .operational_movement import commit_move_orders

        faction = raw.get("faction")
        stance = str(raw.get("locked_stance") or raw.get("stance") or "operational")
        ids = commit_move_orders(
            state,
            faction=None if faction in (None, "") else str(faction),
            locked_stance=stance,
        )
        return CommandResult(
            op=op,
            ok=True,
            detail=f"committed {len(ids)}",
            data={"formation_ids": ids},
        )
    if op == "advance_operational_tick":
        from .operational_movement import advance_operational_tick, advance_operational_ticks

        count = raw.get("count")
        if count is None:
            report = advance_operational_tick(state)
        else:
            report = advance_operational_ticks(state, int(count))
        return CommandResult(op=op, ok=True, detail="advanced", data=report)
    if op == "end_turn":
        nxt = CampaignEngine(state).end_turn()
        return CommandResult(op=op, ok=True, detail=f"next {nxt.value}", data={"next_faction": nxt.value})
    if op == "run_ai":
        faction = Faction(str(raw.get("faction", state.current_faction.value)))
        seed = int(raw.get("seed", 0))
        actions = StrategicAI(state, random_seed=seed).take_turn(faction)
        advanced = ""
        if raw.get("advance_turn"):
            advanced = CampaignEngine(state).end_turn().value
        return CommandResult(
            op=op,
            ok=True,
            detail=f"ai {faction.value}",
            data={"faction": faction.value, "actions": len(actions), "next_faction": advanced},
        )
    if op == "construct":
        province = str(raw.get("province") or raw.get("province_id") or "")
        building = str(raw.get("building") or "")
        faction = Faction(str(raw.get("faction", state.selected_faction.value)))
        if not province or not building:
            raise ValueError("construct requires province and building")
        built = build_infrastructure(state, faction, province, building)
        return CommandResult(op=op, ok=True, detail=f"built {building}", data=asdict(built))
    if op == "repair":
        from .economy import repair_formation

        formation = str(raw.get("formation") or raw.get("formation_id") or "")
        points = raw.get("points")
        repaired = repair_formation(state, formation, None if points is None else int(points))
        return CommandResult(op=op, ok=True, detail=f"repaired {formation}", data=asdict(repaired))
    if op == "handoff":
        raise ValueError("handoff is handled at the campaign-path layer")
    raise ValueError(f"Unsupported frontend command: {op}")
