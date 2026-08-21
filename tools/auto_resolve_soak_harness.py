#!/usr/bin/env python3
"""P10 Auto-Resolve acceptance harness for roadmap #217.

Prove a production ``ww3_2028_core`` campaign can be played to a #75 terminal
result without opening Gates of Hell. The player path is New Campaign → faction
selection → move/commit → End Turn/AI → naturally produced contacts →
Auto-Resolve → treasury settlement → research/recruit/assign/repair →
query_supply → Forward Depot where useful → save/Continue → objectives /
Momentum → victory or defeat.

The S10 prepared-contact smoke is CI-safe only. It is not P10 exit evidence.
A naturally produced pending battle is required for the 2028 acceptance path.
Do not inject ``pending_battle`` and do not use the S10 prepared-contact seam
as the final proof.

Documented commands
-------------------

CI-safe 3-turn S10 smoke (not P10 exit):

    python tools/auto_resolve_soak_harness.py --turns 3 --fixture s10 \\
        --report artifacts/auto_resolve_soak_s10.json

P10 2028 acceptance (public ``p10_acceptance`` length preset):

    python tools/auto_resolve_soak_harness.py --fixture ww3_2028_core \\
        --faction ukr --length-preset p10_acceptance \\
        --report artifacts/auto_resolve_soak.json

This tool does not open Gates of Hell, does not add morale, and does not change
the persist gate:

    persist runtime snapshot only for live move batch
    (issue_move_order, commit_move_orders) OR command_ops == ["auto_resolve"]
    refresh is not a runtime/snapshot patch op
    runtime-patch schema stays v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DEFAULT_CI_TURNS = 3
DEFAULT_LONG_TURNS = 10
TURNS_ENV = "GOC_AUTO_RESOLVE_SOAK_TURNS"
WW3_2028_SCENARIO = "ww3_2028_core"
PRODUCTION_SCENARIO = "ww3_2028_core"
EARTH3_FIXTURE = "earth3_v1"
P10_ACCEPTANCE_PRESET = "p10_acceptance"
DEFAULT_FACTION = "ukr"
RUNTIME_PATCH_SCHEMA = "gates-of-codex.frontend-runtime-patch"
PLACEHOLDER_SNAPSHOT_SCHEMA = "gates-of-codex.soak-placeholder"
VICTORY_EVIDENCE_FIELDS = (
    "status",
    "grade",
    "selected_faction_result",
    "coalition_result",
    "national_result",
    "momentum",
    "reason",
)
TERMINAL_FACTION_RESULTS = frozenset({"victory", "defeat"})
TERMINAL_GRADES = frozenset(
    {"victory", "decisive_victory", "defeat", "decisive_defeat"}
)
REQUIRED_P10_CAPABILITIES = (
    "research",
    "recruit",
    "assign",
    "repair",
    "query_supply",
    "query_supply_foreign_reject",
    "repair_foreign_omitted_actor_reject",
    "upgrade_site",
    "issue_move_order_commit",
    "end_player_round",
    "natural_contact",
    "auto_resolve",
    "save_continue",
    "terminal_result",
)

AUTHORITY_MARKERS = (
    "authority",
    "fail-closed",
    "fail closed",
    "provenance",
    "stable id",
    "stable-id",
    "earth3authority",
    "earth3bootstrap",
    "packagingerror",
    "identity downgrade",
    "catalog signature",
)

HARD_FAIL_KINDS = (
    "crash",
    "authority_violation",
    "save_identity_break",
    "persist_seam_regression",
)


def _ensure_import_path() -> None:
    src = str(SRC)
    tests = str(ROOT / "tests")
    current = os.environ.get("PYTHONPATH", "")
    parts = [item for item in current.split(os.pathsep) if item]
    prefix = [src]
    if src not in parts:
        os.environ["PYTHONPATH"] = src + (os.pathsep + current if current else "")
    for path in (src, tests, str(ROOT)):
        if path not in sys.path:
            sys.path.insert(0, path)


def _default_turns() -> int:
    raw = str(os.environ.get(TURNS_ENV, "")).strip()
    if raw:
        return max(1, int(raw))
    return DEFAULT_LONG_TURNS


def persist_gate_contract() -> dict[str, Any]:
    """Return the frozen persist-gate contract, or raise on regression."""

    from gates_of_codex.command_cycle_perf import _should_persist_runtime_snapshot
    from gates_of_codex.frontend_runtime_patch import (
        RUNTIME_PATCH_SCHEMA as schema,
        RUNTIME_PATCH_SCHEMA_VERSION,
    )

    live_batch = [
        {"op": "issue_move_order"},
        {"op": "commit_move_orders"},
    ]
    expected = {
        "live_move_batch": True,
        "auto_resolve": True,
        "end_player_round": False,
        "refresh": False,
        "issue_move_order_alone": False,
        "query_supply": False,
        "research": False,
        "recruit": False,
        "assign": False,
        "repair": False,
        "upgrade_site": False,
        "actor_force_panel": False,
    }
    observed = {
        "live_move_batch": bool(_should_persist_runtime_snapshot(live_batch)),
        "auto_resolve": bool(
            _should_persist_runtime_snapshot([{"op": "auto_resolve"}])
        ),
        "end_player_round": bool(
            _should_persist_runtime_snapshot([{"op": "end_player_round"}])
        ),
        "refresh": bool(_should_persist_runtime_snapshot([{"op": "refresh"}])),
        "issue_move_order_alone": bool(
            _should_persist_runtime_snapshot([{"op": "issue_move_order"}])
        ),
        "query_supply": bool(_should_persist_runtime_snapshot([{"op": "query_supply"}])),
        "research": bool(_should_persist_runtime_snapshot([{"op": "research"}])),
        "recruit": bool(_should_persist_runtime_snapshot([{"op": "recruit"}])),
        "assign": bool(_should_persist_runtime_snapshot([{"op": "assign"}])),
        "repair": bool(_should_persist_runtime_snapshot([{"op": "repair"}])),
        "upgrade_site": bool(_should_persist_runtime_snapshot([{"op": "upgrade_site"}])),
        "actor_force_panel": bool(
            _should_persist_runtime_snapshot([{"op": "actor_force_panel"}])
        ),
    }
    if observed != expected:
        raise PersistSeamError(
            f"persist gate changed: expected {expected}, observed {observed}"
        )
    if schema != RUNTIME_PATCH_SCHEMA or int(RUNTIME_PATCH_SCHEMA_VERSION) != 1:
        raise PersistSeamError(
            "runtime-patch schema must remain "
            f"{RUNTIME_PATCH_SCHEMA} v1; observed {schema!r} v{RUNTIME_PATCH_SCHEMA_VERSION}"
        )
    return {
        "persist_runtime_snapshot_only_for": [
            "live_move_batch:issue_move_order+commit_move_orders",
            "command_ops==['auto_resolve']",
        ],
        "refresh_is_runtime_patch_op": False,
        "schema": schema,
        "schema_version": int(RUNTIME_PATCH_SCHEMA_VERSION),
        "observed": observed,
    }


class PersistSeamError(RuntimeError):
    """The persist gate or runtime-patch schema drifted."""


class SoakFatalError(RuntimeError):
    def __init__(self, kind: str, message: str) -> None:
        if kind not in HARD_FAIL_KINDS:
            kind = "crash"
        self.kind = kind
        super().__init__(message)


def _fingerprint(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def campaign_identity(state: Any) -> dict[str, Any]:
    metadata = state.map_metadata if isinstance(state.map_metadata, dict) else {}
    return {
        "campaign_name": str(state.campaign_name),
        "map_id": str(state.map_id),
        "schema_version": int(state.schema_version),
        "scenario_id": str(metadata.get("scenario_id") or ""),
        "selected_faction": str(state.selected_faction.value),
        "strategic_formation_ids": sorted(state.strategic_formations),
        "battalion_ids": sorted(state.battalions),
        "catalog_signature": str(getattr(state, "catalog_signature", "") or ""),
    }


def treasury_snapshot(state: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "factions": {
            faction_id: int(row.resources)
            for faction_id, row in sorted(state.factions.items())
        },
        "actors": {},
    }
    try:
        from gates_of_codex.strategic_actors import ensure_strategic_actor_runtime

        actors = ensure_strategic_actor_runtime(state)
        payload["actors"] = {
            actor_id: int(actor.resources)
            for actor_id, actor in sorted(actors.items())
        }
    except Exception:
        payload["actors"] = {}
    return payload


def _looks_like_authority_error(detail: str) -> bool:
    text = detail.lower()
    return any(marker in text for marker in AUTHORITY_MARKERS)


def _command_ops(commands: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("op", "")).strip().lower() for item in commands]


def expected_persist(commands: list[dict[str, Any]]) -> bool:
    from gates_of_codex.command_cycle_perf import _should_persist_runtime_snapshot

    persist = bool(_should_persist_runtime_snapshot(commands))
    ops = _command_ops(commands)
    independently = ops == ["issue_move_order", "commit_move_orders"] or ops == [
        "auto_resolve"
    ]
    if persist != independently:
        raise PersistSeamError(
            "persist gate disagrees with independent contract: "
            f"ops={ops} persist={persist} independent={independently}"
        )
    return persist


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in completed.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _stop_daemon(campaign: Path, pid: int | None) -> None:
    from gates_of_codex import persistent_backend

    session_path = persistent_backend._session_path(campaign)
    if pid is None and session_path.is_file():
        try:
            pid = int(json.loads(session_path.read_text(encoding="utf-8")).get("pid") or 0)
        except (OSError, ValueError):
            pid = None
    if pid:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F", "/T"],
                capture_output=True,
                check=False,
            )
        else:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.kill(pid, sig)
                except OSError:
                    break
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline:
                    if not _pid_alive(pid):
                        break
                    time.sleep(0.05)
                if not _pid_alive(pid):
                    break
    persistent_backend._drop_session_descriptor(campaign)


def _write_commands(path: Path, commands: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps({"commands": commands}, indent=2) + "\n", encoding="utf-8")


def _write_placeholder_snapshot(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": PLACEHOLDER_SNAPSHOT_SCHEMA,
                "note": "soak harness placeholder; not a full Earth3 snapshot",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _scenario_probe() -> dict[str, Any]:
    from gates_of_codex.scenario import DEFAULT_SCENARIO_ID, SCENARIO_REGISTRY, scenario_ids

    ids = list(scenario_ids())
    ww3 = WW3_2028_SCENARIO in SCENARIO_REGISTRY
    earth3 = EARTH3_FIXTURE in SCENARIO_REGISTRY
    return {
        "scenario_ids": ids,
        "default_scenario_id": DEFAULT_SCENARIO_ID,
        "earth3_v1": earth3,
        "ww3_2028_core": {
            "in_registry": ww3,
            "status": (
                SCENARIO_REGISTRY[WW3_2028_SCENARIO].status if ww3 else "absent"
            ),
        },
    }


def _outcome_fields(raw: Any) -> dict[str, Any]:
    """Preserve the authoritative #75 terminal fields for JSON evidence."""

    payload = {field: None for field in VICTORY_EVIDENCE_FIELDS}
    if raw is None:
        return payload
    getter = raw.get if isinstance(raw, dict) else lambda key, default=None: getattr(raw, key, default)
    for field in VICTORY_EVIDENCE_FIELDS:
        payload[field] = getter(field)
    return payload


def _victory_probe(state: Any | None = None) -> dict[str, Any]:
    from gates_of_codex.frontend import _control_block
    from gates_of_codex.strategic import evaluate_campaign_outcome

    ops = []
    if state is not None:
        try:
            ops = list(
                (_control_block(state, None, None).get("supported_ops") or [])
            )
        except Exception as exc:  # noqa: BLE001
            ops = [f"<probe_failed:{exc}>"]
    outcome = None
    if state is not None:
        evaluated = evaluate_campaign_outcome(state)
        outcome = _outcome_fields(evaluated)
        outcome["winner_coalition"] = evaluated.winner_coalition
        outcome["loser_coalition"] = evaluated.loser_coalition
    return {
        "evaluate_campaign_outcome_exists": True,
        "frontend_victory_op": any(
            op in {"continue_playing", "conclude_campaign", "declare_victory", "victory"}
            for op in ops
        ),
        "frontend_supported_ops": ops,
        "outcome": outcome,
    }


def _load_resolved_catalog(path: Path | None) -> dict[str, Any] | None:
    if path is not None:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise SoakFatalError("authority_violation", "resolved catalog is not an object")
        return payload
    try:
        from test_p2_earth3_campaign_bootstrap import _resolved_catalog

        return _resolved_catalog()
    except Exception:
        return None


def _build_earth3_state(resolved_catalog: dict[str, Any] | None) -> Any:
    from gates_of_codex.scenario import build_scenario

    if resolved_catalog is None:
        raise SoakFatalError(
            "authority_violation",
            "earth3_v1 requires a resolved catalog or active stack; none available",
        )
    return build_scenario(EARTH3_FIXTURE, resolved_catalog=resolved_catalog)


def _build_2028_campaign(
    work_dir: Path,
    *,
    faction: str,
    length_preset: str,
    resolved_catalog: dict[str, Any] | None,
) -> Any:
    from gates_of_codex.player_shell import create_new_campaign, resolve_campaign_paths

    if resolved_catalog is None:
        raise SoakFatalError(
            "authority_violation",
            "ww3_2028_core requires a resolved catalog or active stack; none available",
        )
    paths = resolve_campaign_paths(work_dir, scenario_id=WW3_2028_SCENARIO)
    return create_new_campaign(
        paths=paths,
        scenario_id=WW3_2028_SCENARIO,
        faction=faction,
        length_preset=length_preset,
        force=True,
        resolved_catalog=resolved_catalog,
    )


def _build_s10_state(root: Path) -> Any:
    from test_s10_frontend_presentation_contract import _state

    return _state(root)


class SoakSession:
    def __init__(
        self,
        work_dir: Path,
        *,
        use_daemon: bool,
        write_full_snapshot: bool,
    ) -> None:
        self.work_dir = work_dir
        self.campaign = work_dir / "campaign.json"
        self.snapshot = work_dir / "campaign_snapshot.json"
        self.commands_path = work_dir / "frontend_commands.json"
        self.use_daemon = use_daemon
        self.write_full_snapshot = write_full_snapshot
        self.daemon_pid: int | None = None
        self.daemon_used = False
        self.report_commands: list[dict[str, Any]] = []
        from gates_of_codex.turn_cycle import install_frontend_turn_cycle_op

        install_frontend_turn_cycle_op()

    def start_daemon(self) -> bool:
        if not self.use_daemon:
            return False
        from gates_of_codex import persistent_backend

        started = persistent_backend.ensure_backend_session(self.campaign, self.snapshot)
        if not started:
            return False
        session = persistent_backend._read_session(self.campaign)
        if session is None:
            return False
        self.daemon_pid = int(session["pid"])
        self.daemon_used = True
        return True

    def stop_daemon(self) -> None:
        if self.daemon_pid is None:
            from gates_of_codex import persistent_backend

            if not persistent_backend._session_path(self.campaign).is_file():
                return
        _stop_daemon(self.campaign, self.daemon_pid)
        self.daemon_pid = None

    def apply(
        self,
        commands: list[dict[str, Any]],
        *,
        expected_reject: bool = False,
    ) -> dict[str, Any]:
        from gates_of_codex import persistent_backend
        from gates_of_codex.command_cycle_perf import measured_apply_frontend_commands

        persist = expected_persist(commands)
        before_snapshot = _fingerprint(self.snapshot)
        _write_commands(self.commands_path, commands)
        forwarded = None
        via = "oneshot"
        if self.use_daemon:
            forwarded = persistent_backend.try_forward_apply_frontend(
                [
                    "apply-frontend",
                    str(self.campaign),
                    "--snapshot",
                    str(self.snapshot),
                    "--commands",
                    str(self.commands_path),
                ]
            )
        if forwarded is None:
            payload = measured_apply_frontend_commands(
                self.campaign,
                commands=commands,
                snapshot_path=self.snapshot,
            )
            via = "oneshot"
        else:
            exit_code, stdout = forwarded
            payload = json.loads(stdout)
            payload["_exit_code"] = exit_code
            via = "daemon"
            self.daemon_used = True
        after_snapshot = _fingerprint(self.snapshot)
        ops = _command_ops(commands)
        snapshot_changed = before_snapshot != after_snapshot and before_snapshot != ""
        if ops in (["end_player_round"], ["refresh"]) and snapshot_changed:
            raise PersistSeamError(
                f"{ops[0]} must not persist a runtime snapshot; "
                "snapshot digest changed"
            )
        row = {
            "ops": ops,
            "ok": bool(payload.get("ok", False)),
            "via": via,
            "persist_runtime_snapshot": persist,
            "snapshot_changed": snapshot_changed,
            "results": payload.get("results") or [],
            "detail": "",
        }
        if not row["ok"]:
            details = [
                str(item.get("detail") or "")
                for item in row["results"]
                if not item.get("ok", True)
            ]
            row["detail"] = "; ".join(details) or str(payload.get("detail") or "")
            if expected_reject:
                row["expected_reject"] = True
            elif _looks_like_authority_error(row["detail"]):
                raise SoakFatalError(
                    "authority_violation",
                    f"command {ops} failed closed on authority: {row['detail']}",
                )
        elif expected_reject:
            raise SoakFatalError(
                "authority_violation",
                f"command {ops} succeeded but the composed stack requires a reject",
            )
        self.report_commands.append(row)
        return payload


def _opposing_factions(state: Any) -> set[str]:
    selected = state.selected_faction.value
    alliances = state.alliances if isinstance(state.alliances, dict) else {}
    allied: set[str] = {selected}
    for row in alliances.values():
        members = getattr(row, "factions", None)
        if members is None:
            members = row
        values = {getattr(item, "value", str(item)) for item in members}
        if selected in values:
            allied.update(values)
    return {
        getattr(faction, "value", str(faction))
        for faction in state.factions
        if getattr(faction, "value", str(faction)) not in allied
    }


def _select_move(state: Any) -> dict[str, Any] | None:
    from gates_of_codex.operational_order_options import list_operational_move_options

    options = list_operational_move_options(state, state.current_faction)
    if not options:
        return None
    opposing = _opposing_factions(state)
    enemy_provinces = {
        str(force.province_id or "")
        for force in state.strategic_formations.values()
        if force.faction.value in opposing
    }
    hostile = []
    for row in options:
        province = state.provinces.get(str(row.get("target_province_id") or ""))
        owner = ""
        if province is not None:
            owner = getattr(getattr(province, "owner", None), "value", "") or ""
            if not owner:
                owner = getattr(getattr(province, "controller", None), "value", "") or ""
        if owner in opposing:
            hostile.append(row)
    pool = hostile or list(options)

    def _score(item: dict[str, Any]) -> tuple[int, int, str, str]:
        dest = str(item.get("target_province_id") or "")
        path_len = len(item.get("path_node_ids") or [])
        occupier = 0 if dest in enemy_provinces else 1
        return (occupier, path_len, str(item.get("formation_id") or ""), dest)

    row = min(pool, key=_score)
    return {
        "op": "issue_move_order",
        "formation": row["formation_id"],
        "path_node_ids": list(row["path_node_ids"]),
        "path_edge_ids": list(row["path_edge_ids"]),
        "target_province_id": str(row.get("target_province_id") or ""),
        "hostile_target": bool(hostile and row in hostile),
    }


def _player_actor_id(state: Any) -> str:
    metadata = state.map_metadata if isinstance(state.map_metadata, dict) else {}
    runtime = metadata.get("strategic_actor_runtime")
    if isinstance(runtime, dict) and runtime.get("selected_actor_id"):
        return str(runtime["selected_actor_id"])
    try:
        from gates_of_codex.scenario_selection import persisted_actor_id

        return str(persisted_actor_id(state) or "")
    except Exception:
        return ""


def _owned_formation_id(state: Any, actor_id: str) -> str:
    owned: list[str] = []
    for force_id, force in sorted(state.strategic_formations.items()):
        if actor_id and str(getattr(force, "actor_id", "") or "") == actor_id:
            owned.append(force_id)
        elif force.faction == state.selected_faction:
            owned.append(force_id)
    if not owned:
        return ""
    from gates_of_codex.site_upgrade import site_upgrade_blocked_reasons

    for force_id in owned:
        force = state.strategic_formations[force_id]
        province_id = str(getattr(getattr(force, "position", None), "province_id", "") or "")
        if not province_id:
            continue
        reasons = site_upgrade_blocked_reasons(
            state,
            province_id,
            faction=state.selected_faction,
            actor_id=actor_id or None,
        )
        if "province_not_owned" not in reasons and "province_not_owned_by_actor" not in reasons:
            return force_id
    return owned[0]


def _eligible_forward_depot_province(state: Any, actor_id: str) -> tuple[str, list[str]]:
    """Return a public-eligibility Forward Depot province and its block reasons."""

    from gates_of_codex.site_upgrade import site_upgrade_blocked_reasons

    affordable = ""
    pending_funds = ""
    pending_reasons: list[str] = []
    for province_id in sorted(state.provinces):
        reasons = site_upgrade_blocked_reasons(
            state,
            str(province_id),
            faction=state.selected_faction,
            actor_id=actor_id or None,
        )
        if not reasons:
            return str(province_id), []
        if reasons == ["insufficient_resources"] and not pending_funds:
            pending_funds = str(province_id)
            pending_reasons = list(reasons)
    return pending_funds, pending_reasons


def _enemy_formation_id(state: Any) -> str:
    opposing = _opposing_factions(state)
    for force_id, force in sorted(state.strategic_formations.items()):
        if force.faction.value in opposing:
            return force_id
    return ""


def _site_upgrade_fingerprint(state: Any) -> str:
    rows: list[tuple[str, str]] = []
    for province_id, province in sorted(state.provinces.items()):
        metadata = province.metadata if isinstance(province.metadata, dict) else {}
        rows.append((str(province_id), json.dumps(metadata.get("site_upgrades"), sort_keys=True)))
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _read_force_panel(
    session: SoakSession,
    state: Any,
    *,
    actor_id: str,
    formation_id: str,
    battalion_id: str,
) -> dict[str, Any]:
    upgrades_before = _site_upgrade_fingerprint(state)
    payload = session.apply(
        [
            {
                "op": "actor_force_panel",
                "actor": actor_id,
                "formation": formation_id,
                "battalion": battalion_id,
            }
        ]
    )
    from gates_of_codex.state_io import load_campaign

    after_panel = load_campaign(session.campaign)
    if _site_upgrade_fingerprint(after_panel) != upgrades_before:
        raise SoakFatalError(
            "authority_violation",
            "actor_force_panel / snapshot read mutated province site_upgrades",
        )
    if not payload.get("ok"):
        return {}
    results = payload.get("results") or []
    if not results:
        return {}
    data = results[0].get("data") or {}
    return data if isinstance(data, dict) else {}


def _exercise_player_loop(
    session: SoakSession,
    state: Any,
    gaps: list[dict[str, Any]],
    *,
    already: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Drive the composed P10 frontend commands using public campaign mechanics."""

    succeeded = dict(already or {})
    attempted: list[dict[str, Any]] = []
    actor_id = _player_actor_id(state)
    formation_id = _owned_formation_id(state, actor_id)
    battalion_id = ""
    if formation_id:
        force = state.strategic_formations[formation_id]
        battalion_id = next(iter(force.battalion_ids), "")

    panel = _read_force_panel(
        session,
        state,
        actor_id=actor_id,
        formation_id=formation_id,
        battalion_id=battalion_id,
    )
    attempted.append({"op": "actor_force_panel", "ok": bool(panel), "actor": actor_id})

    if actor_id and not succeeded.get("research"):
        research_rows = panel.get("available_research") or []
        research_key = ""
        for row in research_rows:
            key = str(row.get("key") or "")
            cost = int(row.get("cost") or 0)
            if key and 0 < cost <= 200:
                research_key = key
                break
        if not research_key and research_rows:
            research_key = str(research_rows[0].get("key") or "")
        if research_key:
            research = session.apply(
                [{"op": "research", "actor": actor_id, "key": research_key}]
            )
            ok = bool(research.get("ok"))
            attempted.append({"op": "research", "key": research_key, "ok": ok})
            succeeded["research"] = ok
            if ok:
                from gates_of_codex.state_io import load_campaign

                state = load_campaign(session.campaign)
                panel = _read_force_panel(
                    session,
                    state,
                    actor_id=actor_id,
                    formation_id=formation_id,
                    battalion_id=battalion_id,
                )

    if formation_id and not succeeded.get("recruit"):
        offers = [
            row
            for row in (panel.get("recruitment_offers") or [])
            if row.get("unlocked")
        ]
        if offers:
            unit = str(offers[0].get("unit_name") or "")
            recruit = session.apply(
                [
                    {
                        "op": "recruit",
                        "actor": actor_id,
                        "formation": formation_id,
                        "unit": unit,
                        "quantity": 1,
                    }
                ]
            )
            ok = bool(recruit.get("ok"))
            attempted.append({"op": "recruit", "unit": unit, "ok": ok})
            succeeded["recruit"] = ok
            if ok and not succeeded.get("assign"):
                assign = session.apply(
                    [
                        {
                            "op": "assign",
                            "actor": actor_id,
                            "formation": formation_id,
                            "battalion": battalion_id,
                            "unit": unit,
                            "quantity": 1,
                        }
                    ]
                )
                assign_ok = bool(assign.get("ok"))
                attempted.append({"op": "assign", "unit": unit, "ok": assign_ok})
                succeeded["assign"] = assign_ok

    if formation_id and not succeeded.get("repair"):
        repair = session.apply(
            [
                {
                    "op": "repair",
                    "actor": actor_id,
                    "formation": formation_id,
                    "battalion": battalion_id,
                    "points": 1,
                }
            ]
        )
        ok = bool(repair.get("ok"))
        attempted.append({"op": "repair", "ok": ok})
        succeeded["repair"] = ok
    if formation_id and not succeeded.get("query_supply"):
        supply = session.apply([{"op": "query_supply", "formation": formation_id}])
        ok = bool(supply.get("ok"))
        attempted.append({"op": "query_supply", "ok": ok})
        succeeded["query_supply"] = ok

    enemy_id = _enemy_formation_id(state)
    if enemy_id and not succeeded.get("query_supply_foreign_reject"):
        session.apply(
            [{"op": "query_supply", "formation": enemy_id}],
            expected_reject=True,
        )
        attempted.append(
            {
                "op": "query_supply_enemy",
                "ok": False,
                "expected_reject": True,
            }
        )
        succeeded["query_supply_foreign_reject"] = True
    if enemy_id and not succeeded.get("repair_foreign_omitted_actor_reject"):
        session.apply(
            [
                {
                    "op": "repair",
                    "formation": enemy_id,
                    "points": 1,
                }
            ],
            expected_reject=True,
        )
        attempted.append(
            {
                "op": "repair_omitted_actor_foreign",
                "ok": False,
                "expected_reject": True,
            }
        )
        succeeded["repair_foreign_omitted_actor_reject"] = True

    if not succeeded.get("upgrade_site"):
        province_id, reasons = _eligible_forward_depot_province(state, actor_id)
        if province_id and "insufficient_resources" not in reasons:
            upgrade = session.apply(
                [
                    {
                        "op": "upgrade_site",
                        "province": province_id,
                        "actor": actor_id,
                        "upgrade_id": "forward_depot",
                    }
                ]
            )
            ok = bool(upgrade.get("ok"))
            attempted.append(
                {
                    "op": "upgrade_site",
                    "ok": ok,
                    "province": province_id,
                }
            )
            succeeded["upgrade_site"] = ok
        elif province_id:
            attempted.append(
                {
                    "op": "upgrade_site",
                    "ok": False,
                    "province": province_id,
                    "waiting_for_treasury": True,
                }
            )
    return {
        "attempted": attempted,
        "actor_id": actor_id,
        "formation_id": formation_id,
        "succeeded": succeeded,
    }


def _campaign_outcome_payload(state: Any) -> dict[str, Any]:
    rules = state.map_metadata.get("campaign_rules") or {}
    locked = rules.get("locked_result") if isinstance(rules, dict) else {}
    outcome = state.map_metadata.get("campaign_outcome") or {}
    if isinstance(locked, dict) and locked:
        return _outcome_fields(locked)
    return _outcome_fields(outcome if isinstance(outcome, dict) else {})


def _terminal_result_ok(fields: dict[str, Any]) -> bool:
    return (
        str(fields.get("status") or "") == "complete"
        and str(fields.get("selected_faction_result") or "") in TERMINAL_FACTION_RESULTS
        and str(fields.get("grade") or "") in TERMINAL_GRADES
    )


def _required_capability_status(
    *,
    p10_exit: bool,
    succeeded: dict[str, bool],
    natural_battles: int,
    battles: int,
    save_reload: dict[str, Any],
    continue_identity: dict[str, Any],
    outcome: dict[str, Any],
    ops_used: list[str],
) -> dict[str, bool]:
    status = {key: bool(succeeded.get(key)) for key in REQUIRED_P10_CAPABILITIES}
    status["issue_move_order_commit"] = "issue_move_order" in ops_used and "commit_move_orders" in ops_used
    status["end_player_round"] = "end_player_round" in ops_used
    status["natural_contact"] = natural_battles >= 1
    status["auto_resolve"] = battles >= 1
    status["save_continue"] = bool(save_reload.get("performed")) and bool(
        continue_identity.get("performed")
    )
    status["terminal_result"] = _terminal_result_ok(outcome)
    if not p10_exit:
        return status
    return status


def _campaign_complete(state: Any) -> bool:
    payload = _campaign_outcome_payload(state)
    if str(payload.get("status") or "") == "complete":
        return True
    rules = state.map_metadata.get("campaign_rules") or {}
    return bool(rules.get("result_locked") or rules.get("concluded"))


def _static_gaps(scenario_probe: dict[str, Any], victory: dict[str, Any]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    ww3 = scenario_probe.get("ww3_2028_core") or {}
    if not ww3.get("in_registry"):
        gaps.append(
            {
                "id": "ww3_2028_core",
                "severity": "gap",
                "detail": "ww3_2028_core is not registered on this SHA",
            }
        )
    elif ww3.get("status") != "production":
        gaps.append(
            {
                "id": "ww3_2028_core_status",
                "severity": "gap",
                "detail": f"ww3_2028_core status is {ww3.get('status')!r}, expected production",
            }
        )
    if scenario_probe.get("default_scenario_id") != WW3_2028_SCENARIO:
        gaps.append(
            {
                "id": "production_default",
                "severity": "gap",
                "detail": (
                    "production New Campaign default is "
                    f"{scenario_probe.get('default_scenario_id')!r}, not ww3_2028_core"
                ),
            }
        )
    ops = set(victory.get("frontend_supported_ops") or [])
    for required in (
        "continue_playing",
        "conclude_campaign",
        "research",
        "recruit",
        "assign",
        "repair",
        "query_supply",
        "upgrade_site",
        "auto_resolve",
    ):
        if required not in ops and victory.get("frontend_supported_ops"):
            gaps.append(
                {
                    "id": f"missing_frontend_{required}",
                    "severity": "gap",
                    "detail": f"{required} is not a frontend command on this SHA",
                }
            )
    return gaps


def run_soak(
    *,
    turns: int,
    work_dir: Path,
    campaign_path: Path | None = None,
    fixture: str = "auto",
    faction: str = DEFAULT_FACTION,
    length_preset: str = P10_ACCEPTANCE_PRESET,
    resolved_catalog_path: Path | None = None,
    use_daemon: bool = True,
    write_full_snapshot: bool | None = None,
) -> dict[str, Any]:
    """Run the multi-turn Auto-Resolve soak and return the JSON report."""

    _ensure_import_path()
    persist = persist_gate_contract()
    scenario_probe = _scenario_probe()
    gaps = _static_gaps(scenario_probe, {"frontend_victory_op": False})
    fatal: dict[str, str] | None = None
    session: SoakSession | None = None
    turns_completed = 0
    battles = 0
    natural_battles = 0
    prepared_contact_used = False
    economy: dict[str, Any] = {"attempted": []}
    save_reload: dict[str, Any] = {"performed": False}
    continue_identity: dict[str, Any] = {"performed": False}
    scenario_id = ""
    scenario_status = ""
    selected_actor_id = ""
    treasury_start: dict[str, Any] = {}
    treasury_final: dict[str, Any] = {}
    victory: dict[str, Any] = {}
    authoritative: dict[str, Any] = _outcome_fields(None)
    p10_exit = False
    capability_state: dict[str, bool] = {}

    try:
        from gates_of_codex.frontend import write_frontend_snapshot
        from gates_of_codex.state_io import load_campaign, save_campaign

        work_dir.mkdir(parents=True, exist_ok=True)
        created = "loaded"
        if campaign_path is not None:
            from shutil import copy2

            copy2(campaign_path, work_dir / "campaign.json")
            state = load_campaign(work_dir / "campaign.json")
            scenario_id = str(state.map_metadata.get("scenario_id") or "loaded")
            scenario_status = str(state.map_metadata.get("scenario_status") or "loaded")
            if scenario_id == WW3_2028_SCENARIO:
                p10_exit = True
                created = "loaded"
        else:
            catalog = _load_resolved_catalog(resolved_catalog_path)
            state = None
            prefer_2028 = fixture in {"auto", WW3_2028_SCENARIO, PRODUCTION_SCENARIO}
            if prefer_2028:
                try:
                    state = _build_2028_campaign(
                        work_dir,
                        faction=faction,
                        length_preset=length_preset,
                        resolved_catalog=catalog,
                    )
                    scenario_id = WW3_2028_SCENARIO
                    scenario_status = "production"
                    created = "created"
                    p10_exit = True
                except Exception as exc:  # noqa: BLE001
                    if fixture in {WW3_2028_SCENARIO, PRODUCTION_SCENARIO}:
                        raise
                    gaps.append(
                        {
                            "id": "ww3_2028_core_create",
                            "severity": "skip",
                            "detail": f"ww3_2028_core did not load on this SHA: {exc}",
                        }
                    )
                    state = None
            if state is None and fixture == EARTH3_FIXTURE:
                state = _build_earth3_state(catalog)
                scenario_id = EARTH3_FIXTURE
                scenario_status = "debug_fixture"
                created = "created"
            if state is None:
                state = _build_s10_state(work_dir)
                scenario_id = "s10_soak_fixture"
                scenario_status = "debug_fixture"
                created = "created"
                p10_exit = False
                if write_full_snapshot is None:
                    write_full_snapshot = True
                gaps.append(
                    {
                        "id": "used_s10_fixture",
                        "severity": "skip",
                        "detail": (
                            "CI-safe S10 smoke only. This is not P10 exit evidence."
                        ),
                    }
                )
                try:
                    from test_s10_frontend_presentation_contract import (
                        _create_prepared_contact,
                    )

                    _create_prepared_contact(state)
                    prepared_contact_used = True
                except Exception as exc:  # noqa: BLE001
                    gaps.append(
                        {
                            "id": "s10_prepared_contact",
                            "severity": "skip",
                            "detail": f"could not seed an S10 prepared contact: {exc}",
                        }
                    )
            if not (work_dir / "campaign.json").is_file():
                save_campaign(state, work_dir / "campaign.json")
        if write_full_snapshot is None:
            write_full_snapshot = scenario_id == "s10_soak_fixture"

        session = SoakSession(
            work_dir,
            use_daemon=use_daemon,
            write_full_snapshot=write_full_snapshot,
        )
        if write_full_snapshot:
            write_frontend_snapshot(
                state, session.snapshot, campaign_path=session.campaign
            )
        else:
            _write_placeholder_snapshot(session.snapshot)
        _write_commands(session.commands_path, [])
        treasury_start = treasury_snapshot(state)
        selected_actor_id = _player_actor_id(state)
        if scenario_id == WW3_2028_SCENARIO and selected_actor_id in {"", "usa"}:
            raise SoakFatalError(
                "authority_violation",
                f"Core 2028 selected_actor_id leaked or missing: {selected_actor_id!r}",
            )
        victory = _victory_probe(state)
        gaps[:] = _static_gaps(scenario_probe, victory) + [
            gap
            for gap in gaps
            if gap["id"]
            in {"ww3_2028_core_create", "used_s10_fixture", "s10_prepared_contact"}
        ]
        if not session.start_daemon():
            gaps.append(
                {
                    "id": "persistent_backend_daemon",
                    "severity": "skip",
                    "detail": "warm daemon did not start; falling back to one-shot apply",
                }
            )
            session.use_daemon = False

        economy_done = False
        mid_turn = 1 if p10_exit else max(1, turns // 2)
        guard = 0
        max_steps = max(16, turns * 12)
        while turns_completed < turns and guard < max_steps:
            guard += 1
            state = load_campaign(session.campaign)
            if _campaign_complete(state):
                break
            if state.pending_battle is not None:
                payload = session.apply([{"op": "auto_resolve"}])
                if payload.get("ok"):
                    battles += 1
                    if not prepared_contact_used:
                        natural_battles += 1
                continue
            if state.current_faction == state.selected_faction:
                if p10_exit:
                    extra = _exercise_player_loop(
                        session,
                        state,
                        gaps,
                        already=capability_state,
                    )
                    capability_state = extra.get("succeeded") or capability_state
                    if not economy_done:
                        economy = extra
                        economy_done = True
                    else:
                        economy.setdefault("follow_up", [])
                        economy["follow_up"].extend(extra.get("attempted") or [])
                        economy["succeeded"] = capability_state
                move = _select_move(state)
                if move is not None:
                    issue = {
                        "op": "issue_move_order",
                        "formation": move["formation"],
                        "path_node_ids": move["path_node_ids"],
                        "path_edge_ids": move["path_edge_ids"],
                    }
                    session.apply(
                        [
                            issue,
                            {
                                "op": "commit_move_orders",
                                "faction": state.current_faction.value,
                                "locked_stance": "operational",
                            },
                        ]
                    )
                    state = load_campaign(session.campaign)
                    if state.pending_battle is not None:
                        continue
                payload = session.apply([{"op": "end_player_round"}])
                turns_completed += 1
                if not payload.get("ok"):
                    detail = str(payload.get("detail") or "")
                    if "already complete" not in detail.lower():
                        gaps.append(
                            {
                                "id": "end_player_round_failed",
                                "severity": "gap",
                                "detail": detail,
                            }
                        )
                    break
                if turns_completed == mid_turn:
                    session.stop_daemon()
                    from gates_of_codex.player_shell import (
                        continue_campaign,
                        resolve_campaign_paths,
                    )

                    paths = resolve_campaign_paths(session.campaign)
                    before_reload = campaign_identity(load_campaign(session.campaign))
                    continued = continue_campaign(paths=paths)
                    after_reload = campaign_identity(continued)
                    if after_reload != before_reload:
                        raise SoakFatalError(
                            "save_identity_break",
                            f"Continue identity changed: {before_reload} -> {after_reload}",
                        )
                    if scenario_id == WW3_2028_SCENARIO:
                        continued_actor = _player_actor_id(continued)
                        if continued_actor != selected_actor_id:
                            raise SoakFatalError(
                                "save_identity_break",
                                "Continue did not preserve selected actor "
                                f"{selected_actor_id!r} -> {continued_actor!r}",
                            )
                    save_reload = {
                        "performed": True,
                        "identity_ok": True,
                        "turn": turns_completed,
                        "identity": after_reload,
                    }
                    continue_identity = {
                        "performed": True,
                        "scenario_id": str(
                            continued.map_metadata.get("scenario_id") or ""
                        ),
                        "selected_actor_id": _player_actor_id(continued),
                    }
                    if session.use_daemon:
                        session.start_daemon()
            else:
                session.apply([{"op": "end_player_round"}])

        state = load_campaign(session.campaign)
        if state.pending_battle is not None:
            payload = session.apply([{"op": "auto_resolve"}])
            if payload.get("ok"):
                battles += 1
                if not prepared_contact_used:
                    natural_battles += 1
            state = load_campaign(session.campaign)
        outcome = _campaign_outcome_payload(state)
        if str(outcome.get("status") or "") == "complete":
            if str(outcome.get("grade") or "") in {"victory", "decisive_victory"}:
                session.apply([{"op": "continue_playing"}])
        treasury_final = treasury_snapshot(state)
        victory = _victory_probe(state)
        authoritative = _campaign_outcome_payload(state)
        probe_outcome = _outcome_fields((victory.get("outcome") or {}) if victory else {})
        if p10_exit and probe_outcome != authoritative:
            raise SoakFatalError(
                "authority_violation",
                "victory probe fields do not match authoritative campaign state: "
                f"probe={probe_outcome} state={authoritative}",
            )
        if p10_exit and natural_battles < 1:
            raise SoakFatalError(
                "crash",
                "2028 acceptance soak produced no natural Auto-Resolve battle",
            )
        if p10_exit and not _terminal_result_ok(authoritative):
            gaps.append(
                {
                    "id": "campaign_not_terminal",
                    "severity": "gap",
                    "detail": (
                        f"{turns_completed}-turn 2028 soak did not reach an accepted "
                        f"victory or defeat; observed {authoritative}"
                    ),
                }
            )
        if battles == 0:
            gaps.append(
                {
                    "id": "no_battles_auto_resolved",
                    "severity": "gap" if p10_exit else "skip",
                    "detail": (
                        "soak completed with no pending battles; "
                        "Auto-Resolve was ready but not exercised this run"
                    ),
                }
            )
        session.stop_daemon()
    except PersistSeamError as exc:
        fatal = {"kind": "persist_seam_regression", "detail": str(exc)}
    except SoakFatalError as exc:
        fatal = {"kind": exc.kind, "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001
        fatal = {"kind": "crash", "detail": f"{type(exc).__name__}: {exc}"}
    finally:
        if session is not None:
            session.stop_daemon()

    commands = session.report_commands if session is not None else []
    failed = [row for row in commands if not row.get("ok") and not row.get("expected_reject")]
    ops_used = sorted({op for row in commands for op in (row.get("ops") or [])})
    outcome = _outcome_fields((victory.get("outcome") or {}) if victory else {})
    if any(authoritative.get(field) is not None for field in VICTORY_EVIDENCE_FIELDS):
        outcome = dict(authoritative)
    required = _required_capability_status(
        p10_exit=p10_exit,
        succeeded=capability_state,
        natural_battles=natural_battles,
        battles=battles,
        save_reload=save_reload,
        continue_identity=continue_identity,
        outcome=outcome,
        ops_used=ops_used,
    )
    missing_required = [key for key, ok in required.items() if not ok]
    if p10_exit:
        for key in missing_required:
            if not any(gap.get("id") == f"required_{key}" for gap in gaps):
                gaps.append(
                    {
                        "id": f"required_{key}",
                        "severity": "gap",
                        "detail": f"required P10 capability {key} did not succeed",
                    }
                )
    p10_exit_evidence = (
        "2028 production path with at least one naturally produced Auto-Resolve battle"
        if p10_exit and natural_battles and fatal is None and not missing_required
        else (
            "CI-safe S10 prepared-contact smoke only — not P10 exit evidence"
            if not p10_exit
            else "2028 path did not produce P10 exit evidence"
        )
    )
    report = {
        "ok": fatal is None and (not p10_exit or not missing_required),
        "fatal": fatal,
        "base_sha": "b5320ce04bc006fc1cc936c582d126f0a560ba3e",
        "scenario_id": scenario_id,
        "scenario_status": scenario_status,
        "campaign_created": created if "created" in locals() else "",
        "length_preset": length_preset if p10_exit else "",
        "faction": faction if p10_exit else "",
        "selected_actor_id": selected_actor_id,
        "turns_requested": turns,
        "turns_completed": turns_completed,
        "battles_auto_resolved": battles,
        "natural_battles_resolved": natural_battles,
        "prepared_contact_used": prepared_contact_used,
        "commands_attempted": len(commands),
        "commands_failed": len(failed),
        "ops_used": ops_used,
        "commands": commands,
        "economy": economy,
        "required_capabilities": required,
        "missing_player_loop_capabilities": [
            gap for gap in gaps if gap.get("severity") == "gap"
        ],
        "gaps": gaps,
        "treasury_start": treasury_start,
        "treasury_final": treasury_final,
        "continue_identity": continue_identity,
        "campaign_outcome": {
            **outcome,
            "from_campaign_rules": True,
            "matches_authoritative_state": outcome == _outcome_fields(authoritative),
        },
        "victory_api": victory,
        "defeat_api": {
            "evaluate_campaign_outcome_exists": victory.get(
                "evaluate_campaign_outcome_exists", False
            ),
            "frontend_defeat_op": victory.get("frontend_victory_op", False),
            "selected_faction_result": outcome.get("selected_faction_result"),
        },
        "scenario_probe": scenario_probe,
        "persist_gate": persist,
        "save_reload": save_reload,
        "daemon": {
            "requested": use_daemon,
            "used": bool(session.daemon_used) if session is not None else False,
        },
        "goh_invoked": False,
        "goh_parked": {
            "issue_273": "parked",
            "issue_274": "parked HOLD — not in this stack",
            "morale_bridge": "not dragged",
        },
        "morale_changed": False,
        "runtime_patch_schema_v1": persist.get("schema_version") == 1,
        "p10_exit": p10_exit,
        "p10_exit_evidence": p10_exit_evidence,
        "documented_commands": {
            "ci_smoke": (
                "python tools/auto_resolve_soak_harness.py --turns 3 --fixture s10 "
                "--report artifacts/auto_resolve_soak_s10.json"
            ),
            "p10_2028_acceptance": (
                "python tools/auto_resolve_soak_harness.py --fixture ww3_2028_core "
                "--faction ukr --length-preset p10_acceptance "
                "--report artifacts/auto_resolve_soak.json"
            ),
            "report_path": "artifacts/auto_resolve_soak.json",
        },
    }
    return report


def write_report(report: dict[str, Any], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="auto_resolve_soak_harness",
        description="P10 Auto-Resolve multi-turn soak without Gates of Hell (#217).",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=_default_turns(),
        help=(
            f"Strategic player turns to complete (default {DEFAULT_LONG_TURNS} "
            f"or ${TURNS_ENV}; CI smoke uses {DEFAULT_CI_TURNS})"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("artifacts/auto_resolve_soak.json"),
        help="JSON report artifact path",
    )
    parser.add_argument(
        "--campaign",
        type=Path,
        help="Existing disposable campaign.json (copied; never the live owner save)",
    )
    parser.add_argument(
        "--fixture",
        choices=("auto", PRODUCTION_SCENARIO, "s10"),
        default="auto",
        help="Production ww3_2028_core by default; s10 is the fast CI smoke only",
    )
    parser.add_argument(
        "--faction",
        default=DEFAULT_FACTION,
        help="Core 2028 selected actor (nato, ukr, rusa, prc). Default ukr.",
    )
    parser.add_argument(
        "--length-preset",
        default=P10_ACCEPTANCE_PRESET,
        help="Public campaign-rules length_preset. Default p10_acceptance.",
    )
    parser.add_argument(
        "--resolved-catalog",
        type=Path,
        help="Resolved-factions JSON for 2028/Earth3 construction",
    )
    parser.add_argument(
        "--no-daemon",
        action="store_true",
        help="Disable persistent_backend warm daemon (not the default Earth3 path)",
    )
    parser.add_argument(
        "--write-full-snapshot",
        action="store_true",
        help="Write a full frontend snapshot (slow on Earth3; default for s10)",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="Disposable working directory (default: a temporary directory)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_import_path()
    args = build_parser().parse_args(argv)
    if args.turns < 1:
        print("turns must be >= 1", file=sys.stderr)
        return 2
    temporary = None
    work_dir = args.work_dir
    if work_dir is None:
        temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        work_dir = Path(temporary.name)
    try:
        report = run_soak(
            turns=args.turns,
            work_dir=work_dir,
            campaign_path=args.campaign,
            fixture=args.fixture,
            faction=args.faction,
            length_preset=args.length_preset,
            resolved_catalog_path=args.resolved_catalog,
            use_daemon=not args.no_daemon,
            write_full_snapshot=True if args.write_full_snapshot else None,
        )
        path = write_report(report, args.report)
        print(
            json.dumps(
                {
                    "report": str(path),
                    "ok": report["ok"],
                    "fatal": report["fatal"],
                    "scenario_id": report.get("scenario_id"),
                    "selected_actor_id": report.get("selected_actor_id"),
                    "natural_battles_resolved": report.get("natural_battles_resolved"),
                    "campaign_outcome": report.get("campaign_outcome"),
                    "p10_exit_evidence": report.get("p10_exit_evidence"),
                    "goh_invoked": report.get("goh_invoked"),
                },
                indent=2,
            )
        )
        return 0 if report["ok"] else 1
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
