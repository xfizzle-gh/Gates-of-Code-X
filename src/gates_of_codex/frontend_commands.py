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


#: Commands that commit to the campaign file through their own service-level
#: transaction instead of the in-memory batch. They may never share a batch with
#: other operations because the batch rollback cannot undo them.
SELF_COMMITTING_OPS = frozenset(
    {"handoff", "import_battle", "restore_backup", "reset_test_campaign"}
)

#: Read-only actions. They mutate nothing, so they are never recorded in the
#: exactly-once ledger: a player must be able to re-verify a result after
#: replaying a battle and get a fresh verdict rather than a "duplicate" reply.
#: ``actor_force_panel`` is the bounded #149 recruit/research/repair query.
#: ``query_supply`` is the bounded #140 owned-formation supply/readiness query.
READ_ONLY_OPS = frozenset({"verify_result", "actor_force_panel", "query_supply"})

#: Campaign-metadata key holding the exactly-once command ledger.
COMMAND_LEDGER_KEY = "frontend_command_ledger"

#: Persisted binding between the current strategic pending battle and the exact
#: GoH-profile save that the game rewrites. ``pending_battle.exported_save_path``
#: is the isolated source/export archive, not the installed acceptance target.
PENDING_HANDOFF_BINDING_KEY = "pending_battle_handoff"

#: Retained ledger entries. Bounded so the campaign file cannot grow without
#: limit; replay protection therefore covers the most recent applications.
COMMAND_LEDGER_LIMIT = 512


@dataclass(slots=True)
class CommandResult:
    op: str
    ok: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def read_command_ledger(state) -> dict[str, Any]:
    """Return the normalized exactly-once ledger carried by the campaign."""
    raw = state.map_metadata.get(COMMAND_LEDGER_KEY)
    entries: list[dict[str, Any]] = []
    sequence = 0
    if isinstance(raw, dict):
        sequence = int(raw.get("sequence", 0) or 0)
        for item in raw.get("entries", []) or []:
            if not isinstance(item, dict):
                continue
            command_id = str(item.get("command_id", "")).strip()
            if not command_id:
                continue
            entries.append(
                {
                    "command_id": command_id,
                    "op": str(item.get("op", "")),
                    "sequence": int(item.get("sequence", 0) or 0),
                }
            )
    return {"sequence": sequence, "entries": entries}


def ledger_contains(ledger: dict[str, Any], command_id: str) -> bool:
    identity = str(command_id).strip()
    if not identity:
        return False
    return any(entry["command_id"] == identity for entry in ledger["entries"])


def _ledger_record(ledger: dict[str, Any], command_id: str, op: str) -> None:
    identity = str(command_id).strip()
    if not identity or ledger_contains(ledger, identity):
        return
    ledger["sequence"] = int(ledger["sequence"]) + 1
    ledger["entries"].append(
        {"command_id": identity, "op": str(op), "sequence": ledger["sequence"]}
    )
    if len(ledger["entries"]) > COMMAND_LEDGER_LIMIT:
        del ledger["entries"][: len(ledger["entries"]) - COMMAND_LEDGER_LIMIT]


def _store_command_ledger(state, ledger: dict[str, Any]) -> None:
    if not ledger["entries"]:
        return
    state.map_metadata[COMMAND_LEDGER_KEY] = {
        "sequence": int(ledger["sequence"]),
        "entries": [dict(entry) for entry in ledger["entries"]],
    }


def _command_identity(raw: dict[str, Any]) -> str:
    return str(raw.get("command_id") or raw.get("id") or "").strip()


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
    ledger = read_command_ledger(state)
    results: list[CommandResult] = []
    from .observation import (
        ObservationMutationContext,
        merge_observation_mutation_contexts,
    )
    observation_context = ObservationMutationContext()

    batch_error = _batch_rejection(pending)
    if batch_error:
        if command_file is not None:
            clear_commands(command_file)
        return _apply_report(
            state,
            campaign,
            ok=False,
            snapshot="",
            results=[CommandResult(op="batch", ok=False, detail=batch_error)],
        )

    for raw in pending:
        op = str(raw.get("op", "")).strip().lower()
        command_id = _command_identity(raw)
        if command_id and op not in READ_ONLY_OPS and ledger_contains(ledger, command_id):
            results.append(
                CommandResult(
                    op=op or "unknown",
                    ok=True,
                    detail=f"duplicate command_id {command_id} ignored",
                    data={"command_id": command_id, "duplicate": True},
                )
            )
            continue
        before_presentations = _formation_presentation_rows(state)
        try:
            if op == "handoff":
                result = _apply_handoff(campaign, state, raw)
                state = load_campaign(campaign)
            elif op == "verify_result":
                result = _apply_verify_result(campaign, state, raw)
            elif op == "import_battle":
                result = _apply_import_battle(campaign, state, raw)
                state = load_campaign(campaign)
            elif op == "restore_backup":
                result = _apply_restore_backup(campaign, state, raw)
                state = load_campaign(campaign)
                ledger = read_command_ledger(state)
                observation_context = ObservationMutationContext()
                before_presentations = _formation_presentation_rows(state)
            elif op == "reset_test_campaign":
                result = _apply_reset_test_campaign(campaign, state, raw)
            else:
                result = _apply_one(state, op, raw)
        except Exception as exc:  # noqa: BLE001 - surface operator errors in result list
            result = CommandResult(op=op or "unknown", ok=False, detail=str(exc))
        if result.ok:
            operation_context = result.data.pop("_observation_context", None)
            observation_context = merge_observation_mutation_contexts(
                observation_context, operation_context
            )
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
            if command_id and op not in READ_ONLY_OPS:
                _ledger_record(ledger, command_id, op)
                result.data["command_id"] = command_id
        results.append(result)
        if not result.ok:
            break

    if command_file is not None:
        clear_commands(command_file)

    if any(not item.ok for item in results):
        if campaign.is_file():
            return _apply_report(
                load_campaign(campaign),
                campaign,
                ok=False,
                snapshot="",
                results=results,
            )
        return {
            "ok": False,
            "campaign_path": str(campaign),
            "snapshot_path": "",
            "commands_applied": 0,
            "results": [asdict(item) for item in results],
        }

    if any(item.op == "reset_test_campaign" for item in results):
        return {
            "ok": True,
            "campaign_path": str(campaign),
            "snapshot_path": "",
            "commands_applied": len(results),
            "results": [asdict(item) for item in results],
        }

    query_only = bool(results) and all(item.op in READ_ONLY_OPS for item in results)
    if query_only:
        return _apply_report(
            state,
            campaign,
            ok=True,
            snapshot=str(Path(snapshot_path).resolve()) if snapshot_path else "",
            results=results,
        )

    _store_command_ledger(state, ledger)
    save_campaign(
        state,
        campaign,
        observation_context=observation_context,
    )
    snapshot = ""
    if snapshot_path:
        from .frontend import write_frontend_snapshot

        try:
            snapshot = str(
                write_frontend_snapshot(
                    state,
                    snapshot_path,
                    campaign_path=campaign,
                ).resolve()
            )
        except Exception as exc:  # noqa: BLE001 - authoritative state is already committed
            report = _apply_report(
                state,
                campaign,
                ok=False,
                snapshot="",
                results=results,
            )
            report["snapshot_publish_failed"] = str(exc)
            return report

    return _apply_report(state, campaign, ok=True, snapshot=snapshot, results=results)


def _batch_rejection(pending: list[dict[str, Any]]) -> str:
    ops = [str(raw.get("op", "")).strip().lower() for raw in pending]
    self_committing = sorted({op for op in ops if op in SELF_COMMITTING_OPS})
    if self_committing and len(ops) > 1:
        return (
            f"{', '.join(self_committing)} must be submitted alone; "
            f"batched with {len(ops) - 1} other command(s)"
        )
    identities = [_command_identity(raw) for raw in pending]
    seen = {value for value in identities if value}
    if len(seen) != len([value for value in identities if value]):
        return "batch contains duplicate command_id values"
    return ""


def _apply_report(
    state,
    campaign: Path,
    *,
    ok: bool,
    snapshot: str,
    results: list[CommandResult],
) -> dict[str, Any]:
    return {
        "ok": ok,
        "campaign_path": str(campaign),
        "snapshot_path": snapshot,
        "commands_applied": len(
            [
                item
                for item in results
                if item.ok and not bool(item.data.get("duplicate"))
            ]
        )
        if ok
        else 0,
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
    template_raw = str(
        raw.get("template_save")
        or raw.get("status_template_path")
        or state.map_metadata.get("status_template_path")
        or ""
    ).strip()
    result = prepare_stack_handoff(
        campaign,
        map_name=str(raw["map"]) if raw.get("map") else None,
        work_root=work_root,
        backup_root=backup_root,
        launch=bool(raw.get("launch", False)),
        status_template_path=template_raw or None,
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


def _session_installed_save_path(pending) -> str:
    """Recover an installed GoH save from the authenticated handoff session.

    P6 heads before the persisted binding fix stored only the isolated export path
    on ``PendingBattle``. The handoff session still records the profile-installed
    save. Recovery is deliberately fail-closed: the installed sidecar must exist
    and bind its own save path and battle id before it can be selected. Campaign
    identity is checked immediately afterwards by ``_verify_result``.
    """
    raw_export = str(getattr(pending, "exported_save_path", "") or "").strip()
    if not raw_export:
        return ""
    from .service import GatesOfCodeXService

    service = GatesOfCodeXService()
    export_save = Path(raw_export).expanduser().resolve()
    session_path = service.manifest_path(export_save).with_suffix(".session.json")
    if not session_path.is_file():
        return ""
    try:
        payload = json.loads(session_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return ""
    installed_raw = str(payload.get("installed_save_path") or "").strip()
    if not installed_raw:
        return ""
    installed = Path(installed_raw).expanduser().resolve()
    manifest_path = service.manifest_path(installed)
    if not manifest_path.is_file():
        return ""
    try:
        manifest = service.load_manifest(manifest_path)
    except (OSError, ValueError, TypeError):
        return ""
    if str(getattr(manifest, "battle_id", "") or "") != str(
        getattr(pending, "battle_id", "") or ""
    ):
        return ""
    manifest_save = str(getattr(manifest, "save_path", "") or "").strip()
    if not manifest_save or Path(manifest_save).expanduser().resolve() != installed:
        return ""
    return str(installed)


def _resolve_result_save_path(state, raw: dict[str, Any]) -> str:
    pending = state.pending_battle
    if pending is None:
        raise ValueError("No pending battle to verify")

    explicit = str(raw.get("save_path") or "").strip()
    if explicit:
        return explicit

    metadata = getattr(state, "map_metadata", {}) or {}
    binding = metadata.get(PENDING_HANDOFF_BINDING_KEY, {})
    if isinstance(binding, dict):
        bound_battle = str(binding.get("battle_id") or "").strip()
        installed = str(binding.get("installed_save_path") or "").strip()
        if bound_battle == str(pending.battle_id) and installed:
            return installed

    recovered = _session_installed_save_path(pending)
    if recovered:
        return recovered

    save_path = str(getattr(pending, "exported_save_path", "") or "").strip()
    if not save_path:
        raise ValueError("Pending battle has no handed-off GoH save path")
    return save_path


def _assert_manifest_binds_result(
    manifest,
    *,
    campaign: Path,
    save_file: Path,
    state,
) -> None:
    raw_battle = str(getattr(manifest, "battle_id", "") or "")
    raw_campaign = str(getattr(manifest, "campaign_path", "") or "")
    raw_save = str(getattr(manifest, "save_path", "") or "")
    campaign_file = Path(campaign).resolve()

    if not raw_campaign.strip():
        raise ValueError("Handoff manifest does not name a campaign")
    if Path(raw_campaign).resolve() != campaign_file:
        raise ValueError(
            f"Handoff manifest belongs to campaign {raw_campaign!r}, "
            f"not {str(campaign_file)!r}"
        )

    if not raw_save.strip():
        raise ValueError("Handoff manifest does not name a tactical save")
    if Path(raw_save).resolve() != save_file:
        raise ValueError(
            f"Handoff manifest belongs to tactical save {raw_save!r}, "
            f"not {str(save_file)!r}"
        )

    pending = state.pending_battle
    if pending is None:
        raise ValueError("No pending battle to verify this result against")
    if not raw_battle.strip():
        raise ValueError("Handoff manifest does not name a battle")
    if raw_battle != pending.battle_id:
        raise ValueError(
            f"Handoff manifest belongs to battle {raw_battle!r}, "
            f"but the pending battle is {pending.battle_id!r}"
        )


def _verify_result(campaign: Path, state, save_path: str):
    from .acceptance import verify_tactical_result
    from .service import GatesOfCodeXService
    from .stack_acceptance import verify_stack_result

    service = GatesOfCodeXService()
    save_file = Path(save_path).resolve()
    manifest = service.load_manifest(service.manifest_path(save_file))
    _assert_manifest_binds_result(manifest, campaign=campaign, save_file=save_file, state=state)
    resource_stack = (
        state.map_metadata.get("resource_stack", []) or manifest.resource_stack
    )
    stack_config = state.map_metadata.get("stack_config")
    if resource_stack or state.code_x_directory:
        return verify_stack_result(
            campaign,
            save_path=save_path,
            code_x_directory=state.code_x_directory or None,
            resource_stack=resource_stack or None,
            stack_config=stack_config or None,
        )
    return verify_tactical_result(campaign, save_path=save_path, code_x_directory=None)


def _apply_verify_result(campaign: Path, state, raw: dict[str, Any]) -> CommandResult:
    save_path = _resolve_result_save_path(state, raw)
    verification = _verify_result(campaign, state, save_path)
    errors = list(getattr(verification, "errors", []) or [])
    return CommandResult(
        op="verify_result",
        ok=True,
        detail="verified" if verification.ok else "verification failed",
        data={
            "verified": bool(verification.ok),
            "save_path": save_path,
            "battle_id": state.pending_battle.battle_id if state.pending_battle else "",
            "errors": errors,
        },
    )


def _apply_import_battle(
    campaign: Path,
    state,
    raw: dict[str, Any],
) -> CommandResult:
    from .service import GatesOfCodeXService

    save_path = _resolve_result_save_path(state, raw)
    service = GatesOfCodeXService()
    verification = _verify_result(campaign, state, save_path)
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


def _apply_restore_backup(campaign: Path, state, raw: dict[str, Any]) -> CommandResult:
    from .packaging import (
        PackagingError,
        latest_managed_backup,
        restore_managed_backup,
    )

    backup = str(raw.get("backup") or raw.get("backup_directory") or "").strip()
    if not backup:
        descriptor = latest_managed_backup(campaign)
        if descriptor is None:
            raise ValueError("No authenticated backup exists for this campaign")
        backup = descriptor["backup_directory"]
    else:
        descriptor = {
            "backup_directory": str(Path(backup).expanduser().resolve(strict=False)),
            "campaign_path": str(campaign.resolve(strict=False)),
        }
    try:
        restored = restore_managed_backup(backup, expected_campaign=campaign)
    except PackagingError as exc:
        raise ValueError(str(exc)) from exc
    return CommandResult(
        op="restore_backup",
        ok=True,
        detail=f"restored {len(restored)} file(s)",
        data={
            "backup_directory": descriptor["backup_directory"],
            "backup": descriptor,
            "restored": [str(path) for path in restored],
        },
    )


def _apply_reset_test_campaign(campaign: Path, state, raw: dict[str, Any]) -> CommandResult:
    from .packaging import PackagingError, reset_test_campaign

    create_backup = bool(raw.get("create_backup", True))
    scenario_id = str(
        raw.get("scenario_id") or state.map_metadata.get("scenario_id") or "earth3_v1"
    )
    try:
        report = reset_test_campaign(
            campaign,
            scenario_id=scenario_id,
            create_backup=create_backup,
        )
    except PackagingError as exc:
        raise ValueError(str(exc)) from exc
    return CommandResult(
        op="reset_test_campaign",
        ok=True,
        detail="test campaign reset",
        data=report,
    )


def _apply_one(state, op: str, raw: dict[str, Any]) -> CommandResult:
    if op in {"", "refresh", "noop"}:
        return CommandResult(op=op or "refresh", ok=True, detail="snapshot refresh only")
    if op == "query_supply":
        from .supply import query_supply_status

        formation_id = str(
            raw.get("formation")
            or raw.get("formation_id")
            or raw.get("strategic_formation_id")
            or ""
        ).strip()
        province = str(raw.get("province") or raw.get("province_id") or "").strip()
        # IDs are forwarded as requested; query_supply_status fail-closes on
        # ownership. The player frontend cannot spoof observer/faction here.
        payload = query_supply_status(
            state,
            strategic_formation_id=formation_id or None,
            province_id=province or None,
        )
        target = formation_id or province
        return CommandResult(
            op=op,
            ok=True,
            detail=f"supply {target}",
            data=payload,
        )
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
                "_observation_context": engine.observation_context,
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
        ai = StrategicAI(state, random_seed=seed)
        actions = ai.take_turn(faction)
        advanced = ""
        if raw.get("advance_turn"):
            advanced = CampaignEngine(state).end_turn().value
        return CommandResult(
            op=op,
            ok=True,
            detail=f"ai {faction.value}",
            data={
                "faction": faction.value,
                "actions": len(actions),
                "next_faction": advanced,
                "_observation_context": ai.observation_context,
            },
        )
    if op == "construct":
        province = str(raw.get("province") or raw.get("province_id") or "")
        building = str(raw.get("building") or "")
        faction = Faction(str(raw.get("faction", state.selected_faction.value)))
        if not province or not building:
            raise ValueError("construct requires province and building")
        built = build_infrastructure(state, faction, province, building)
        return CommandResult(op=op, ok=True, detail=f"built {building}", data=asdict(built))
    if op == "upgrade_site":
        from .site_upgrade import FORWARD_DEPOT_ID, start_site_upgrade

        province = str(raw.get("province") or raw.get("province_id") or "")
        upgrade_id = str(raw.get("upgrade_id") or raw.get("upgrade") or FORWARD_DEPOT_ID)
        from .core_player_economy import is_core_2028_campaign

        actor_id = raw.get("actor_id") or raw.get("actor")
        faction = Faction(str(raw.get("faction", state.selected_faction.value)))
        if not province:
            raise ValueError("upgrade_site requires province")
        upgraded = start_site_upgrade(
            state,
            province,
            upgrade_id=upgrade_id,
            faction=faction,
            actor_id=None
            if is_core_2028_campaign(state) or actor_id in (None, "")
            else str(actor_id),
        )
        return CommandResult(op=op, ok=True, detail=f"upgrading {upgrade_id}", data=asdict(upgraded))
    if op == "repair":
        from .frontend_actor_force import apply_repair_command

        repaired = apply_repair_command(state, raw)
        return CommandResult(
            op=op,
            ok=True,
            detail=f"repaired {repaired.get('strategic_formation_id') or repaired.get('formation_id') or ''}",
            data=repaired,
        )
    if op == "research":
        from .frontend_actor_force import apply_research_command

        purchased = apply_research_command(state, raw)
        return CommandResult(
            op=op,
            ok=True,
            detail=f"researched {purchased.get('key', '')}",
            data=purchased,
        )
    if op == "recruit":
        from .frontend_actor_force import apply_recruit_command

        purchased = apply_recruit_command(state, raw)
        return CommandResult(
            op=op,
            ok=True,
            detail=f"recruited {purchased.get('quantity', 0)} {purchased.get('unit_name', '')}",
            data=purchased,
        )
    if op == "assign":
        from .frontend_actor_force import apply_assign_command

        transferred = apply_assign_command(state, raw)
        return CommandResult(
            op=op,
            ok=True,
            detail=f"assigned {transferred.get('quantity', 0)} {transferred.get('unit_name', '')}",
            data=transferred,
        )
    if op == "actor_force_panel":
        from .frontend_actor_force import build_actor_force_panel

        panel = build_actor_force_panel(state, raw)
        return CommandResult(
            op=op,
            ok=True,
            detail=f"force panel {panel.get('actor_id', '')}",
            data=panel,
        )
    if op == "continue_playing":
        from .campaign_rules import continue_playing

        payload = continue_playing(state)
        return CommandResult(op=op, ok=True, detail="continue playing", data=payload)
    if op == "conclude_campaign":
        from .campaign_rules import conclude_campaign

        payload = conclude_campaign(state)
        return CommandResult(op=op, ok=True, detail="campaign concluded", data=payload)
    if op == "handoff":
        raise ValueError("handoff is handled at the campaign-path layer")
    raise ValueError(f"Unsupported frontend command: {op}")
