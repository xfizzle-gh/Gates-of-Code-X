#!/usr/bin/env python3
"""P10 Auto-Resolve multi-turn soak harness for roadmap #217.

Prove the current-main player loop can run multiple strategic turns without
opening Gates of Hell. Missing 2028 New Campaign, victory UI, and Godot
force-management work are recorded as structured gaps — they do not fail the
harness. Crashes, authority violations, save-identity breaks, and persist-seam
regressions do fail.

Documented commands
-------------------

CI-safe 3-turn smoke (S10 operational fixture; default unittest):

    python tools/auto_resolve_soak_harness.py --turns 3 --fixture s10 \\
        --report artifacts/auto_resolve_soak.json

Optional longer Earth3 soak (target 12 turns; not default CI):

    GOC_AUTO_RESOLVE_SOAK_TURNS=12 python tools/auto_resolve_soak_harness.py \\
        --fixture earth3_v1 --report artifacts/auto_resolve_soak.json

Prefer an existing disposable campaign (never the live owner save):

    python tools/auto_resolve_soak_harness.py --campaign /path/to/campaign.json \\
        --turns 12 --report artifacts/auto_resolve_soak.json

JSON report path is ``--report`` (created directories as needed). Default CI
uses three turns; set ``GOC_AUTO_RESOLVE_SOAK_TURNS`` for the long harness.

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
DEFAULT_LONG_TURNS = 12
TURNS_ENV = "GOC_AUTO_RESOLVE_SOAK_TURNS"
WW3_2028_SCENARIO = "ww3_2028_core"
PRODUCTION_SCENARIO = "earth3_v1"
RUNTIME_PATCH_SCHEMA = "gates-of-codex.frontend-runtime-patch"
PLACEHOLDER_SNAPSHOT_SCHEMA = "gates-of-codex.soak-placeholder"

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
    return {
        "scenario_ids": ids,
        "default_scenario_id": DEFAULT_SCENARIO_ID,
        "earth3_v1": PRODUCTION_SCENARIO in SCENARIO_REGISTRY,
        "ww3_2028_core": {
            "in_registry": ww3,
            "status": (
                SCENARIO_REGISTRY[WW3_2028_SCENARIO].status if ww3 else "absent"
            ),
        },
    }


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
        outcome = evaluate_campaign_outcome(state)
        outcome = {
            "status": outcome.status,
            "winner_coalition": outcome.winner_coalition,
            "loser_coalition": outcome.loser_coalition,
            "reason": outcome.reason,
            "selected_faction_result": outcome.selected_faction_result,
        }
    return {
        "evaluate_campaign_outcome_exists": True,
        "frontend_victory_op": any(
            op in {"declare_victory", "victory", "campaign_status"} for op in ops
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
    return build_scenario(PRODUCTION_SCENARIO, resolved_catalog=resolved_catalog)


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

    def apply(self, commands: list[dict[str, Any]]) -> dict[str, Any]:
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
            if _looks_like_authority_error(row["detail"]):
                raise SoakFatalError(
                    "authority_violation",
                    f"command {ops} failed closed on authority: {row['detail']}",
                )
        self.report_commands.append(row)
        return payload


def _select_move(state: Any) -> dict[str, Any] | None:
    from gates_of_codex.operational_order_options import list_operational_move_options

    options = list_operational_move_options(state, state.current_faction)
    if not options:
        return None
    row = options[0]
    return {
        "op": "issue_move_order",
        "formation": row["formation_id"],
        "path_node_ids": list(row["path_node_ids"]),
        "path_edge_ids": list(row["path_edge_ids"]),
    }


def _player_actor_id(state: Any) -> str:
    metadata = state.map_metadata if isinstance(state.map_metadata, dict) else {}
    for key in (
        "earth3_bootstrap",
        "earth3_v1_campaign_bootstrap",
        "bootstrap",
    ):
        bootstrap = metadata.get(key)
        if isinstance(bootstrap, dict) and bootstrap.get("selected_actor_id"):
            return str(bootstrap["selected_actor_id"])
    try:
        from gates_of_codex.strategic_actors import ensure_strategic_actor_runtime

        actors = ensure_strategic_actor_runtime(state)
        for actor_id, actor in actors.items():
            if getattr(actor, "is_human_controlled", False):
                return actor_id
            if actor_id == "usa":
                return actor_id
    except Exception:
        pass
    return ""


def _exercise_economy(state: Any, gaps: list[dict[str, Any]]) -> dict[str, Any]:
    """Spend treasury via existing #149 / CLI APIs when present.

    Recruit and research are not frontend ops on this SHA. Repair is a frontend
    op but is not on the persistent-backend allowlist. The probe uses the Python
    APIs that already exist so missing UI/2028 work stays a gap, not a crash.
    """

    attempted: list[dict[str, Any]] = []
    from gates_of_codex.actor_economy import ACTOR_CONTENT_KEY
    from gates_of_codex.frontend import _control_block

    frontend_ops = set(_control_block(state, None, None).get("supported_ops") or [])
    if "recruit" not in frontend_ops:
        gaps.append(
            {
                "id": "frontend_recruit_op",
                "severity": "gap",
                "detail": "recruit exists as CLI/Python (#149) but is not a frontend op",
            }
        )
    if "research" not in frontend_ops:
        gaps.append(
            {
                "id": "frontend_research_op",
                "severity": "gap",
                "detail": "research exists as CLI/Python (#149) but is not a frontend op",
            }
        )
    if "repair" in frontend_ops:
        from gates_of_codex.persistent_backend import SUPPORTED_OPS

        if "repair" not in SUPPORTED_OPS:
            gaps.append(
                {
                    "id": "daemon_repair_op",
                    "severity": "gap",
                    "detail": "repair is a frontend op but is not a persistent_backend warm op",
                }
            )

    actor_content = state.map_metadata.get(ACTOR_CONTENT_KEY)
    if isinstance(actor_content, dict):
        from gates_of_codex.actor_economy import (
            actor_recruitment_offers,
            available_actor_research,
            purchase_actor_reinforcements,
            purchase_actor_research,
            repair_actor_formation,
        )

        actor_id = _player_actor_id(state)
        if actor_id:
            research = available_actor_research(state, actor_id)
            affordable = [item for item in research if item.cost <= 50 or item.cost == 0]
            target = next((item for item in affordable if item.cost > 0), None)
            if target is None and research:
                target = research[0]
            if target is not None:
                try:
                    bought = purchase_actor_research(state, actor_id, target.key)
                    attempted.append(
                        {
                            "op": "purchase_actor_research",
                            "ok": True,
                            "key": bought.key,
                            "cost": bought.cost,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    attempted.append(
                        {
                            "op": "purchase_actor_research",
                            "ok": False,
                            "detail": str(exc),
                        }
                    )
                    if _looks_like_authority_error(str(exc)):
                        raise SoakFatalError("authority_violation", str(exc)) from exc
            else:
                gaps.append(
                    {
                        "id": "actor_research_offer",
                        "severity": "skip",
                        "detail": f"no purchasable research for actor {actor_id}",
                    }
                )
        formation_id = ""
        for force_id, force in sorted(state.strategic_formations.items()):
            if actor_id and getattr(force, "actor_id", "") == actor_id:
                formation_id = force_id
                break
            if force.faction == state.selected_faction and not formation_id:
                formation_id = force_id
        if formation_id:
            offers = [
                item
                for item in actor_recruitment_offers(state, formation_id)
                if item.unlocked
            ]
            if offers:
                offer = offers[0]
                try:
                    bought = purchase_actor_reinforcements(
                        state, formation_id, offer.unit_name, 1
                    )
                    attempted.append(
                        {
                            "op": "purchase_actor_reinforcements",
                            "ok": True,
                            "unit": offer.unit_name,
                            "cost": bought.total_cost
                            if hasattr(bought, "total_cost")
                            else offer.purchase_cost,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    attempted.append(
                        {
                            "op": "purchase_actor_reinforcements",
                            "ok": False,
                            "detail": str(exc),
                        }
                    )
                    if _looks_like_authority_error(str(exc)):
                        raise SoakFatalError("authority_violation", str(exc)) from exc
            else:
                gaps.append(
                    {
                        "id": "actor_recruit_offer",
                        "severity": "skip",
                        "detail": f"no unlocked recruitment offer for {formation_id}",
                    }
                )
            try:
                repaired = repair_actor_formation(state, formation_id, 1)
                attempted.append(
                    {
                        "op": "repair_actor_formation",
                        "ok": True,
                        "points": repaired.points_repaired
                        if hasattr(repaired, "points_repaired")
                        else 0,
                        "cost": repaired.cost if hasattr(repaired, "cost") else 0,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                attempted.append(
                    {
                        "op": "repair_actor_formation",
                        "ok": False,
                        "detail": str(exc),
                    }
                )
                if _looks_like_authority_error(str(exc)):
                    raise SoakFatalError("authority_violation", str(exc)) from exc
    else:
        from gates_of_codex.economy import (
            available_research,
            formation_recruitment_offers,
            purchase_reinforcements,
            purchase_research,
            repair_formation,
        )

        gaps.append(
            {
                "id": "actor_content_runtime",
                "severity": "skip",
                "detail": "campaign has no #149 actor_content_runtime; using legacy economy APIs",
            }
        )
        faction = state.selected_faction
        try:
            nodes = available_research(state, faction)
        except Exception as exc:  # noqa: BLE001
            nodes = []
            attempted.append({"op": "available_research", "ok": False, "detail": str(exc)})
        if nodes:
            node = nodes[0]
            try:
                purchase_research(state, faction, node.key)
                attempted.append({"op": "purchase_research", "ok": True, "key": node.key})
            except Exception as exc:  # noqa: BLE001
                attempted.append(
                    {"op": "purchase_research", "ok": False, "detail": str(exc)}
                )
                if _looks_like_authority_error(str(exc)):
                    raise SoakFatalError("authority_violation", str(exc)) from exc
        formation_id = next(iter(sorted(state.strategic_formations)), "")
        if formation_id:
            try:
                offers = formation_recruitment_offers(state, formation_id)
            except Exception as exc:  # noqa: BLE001
                offers = []
                attempted.append(
                    {"op": "formation_recruitment_offers", "ok": False, "detail": str(exc)}
                )
            if offers:
                offer = offers[0]
                unit = getattr(offer, "unit_name", None) or offer.get("unit_name")
                try:
                    purchase_reinforcements(state, formation_id, str(unit), 1)
                    attempted.append(
                        {"op": "purchase_reinforcements", "ok": True, "unit": unit}
                    )
                except Exception as exc:  # noqa: BLE001
                    attempted.append(
                        {
                            "op": "purchase_reinforcements",
                            "ok": False,
                            "detail": str(exc),
                        }
                    )
                    if _looks_like_authority_error(str(exc)):
                        raise SoakFatalError("authority_violation", str(exc)) from exc
            try:
                repair_formation(state, formation_id, 1)
                attempted.append({"op": "repair_formation", "ok": True})
            except Exception as exc:  # noqa: BLE001
                attempted.append(
                    {"op": "repair_formation", "ok": False, "detail": str(exc)}
                )
                if _looks_like_authority_error(str(exc)):
                    raise SoakFatalError("authority_violation", str(exc)) from exc
    return {"attempted": attempted}


def _static_gaps(scenario_probe: dict[str, Any], victory: dict[str, Any]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    if not scenario_probe["ww3_2028_core"]["in_registry"]:
        gaps.append(
            {
                "id": "ww3_2028_core",
                "severity": "gap",
                "detail": (
                    "ww3_2028_core is not a scenario on this SHA; "
                    f"production default is {scenario_probe['default_scenario_id']}. "
                    "2028 New Campaign (#254–#260) is landing in parallel."
                ),
            }
        )
    if not victory.get("frontend_victory_op"):
        gaps.append(
            {
                "id": "frontend_victory_defeat",
                "severity": "gap",
                "detail": (
                    "evaluate_campaign_outcome exists in Python (#75 surface) but "
                    "there is no frontend victory/defeat command on this SHA"
                ),
            }
        )
    gaps.append(
        {
            "id": "auto_resolve_default_ui",
            "severity": "gap",
            "detail": "Auto-Resolve default UI (#265) is out of scope for this harness",
        }
    )
    gaps.append(
        {
            "id": "godot_force_management",
            "severity": "gap",
            "detail": "Godot force-management UI is out of scope for this harness",
        }
    )
    gaps.append(
        {
            "id": "site_upgrade",
            "severity": "gap",
            "detail": "Minimal site-upgrade is out of scope for this harness",
        }
    )
    return gaps


def run_soak(
    *,
    turns: int,
    work_dir: Path,
    campaign_path: Path | None = None,
    fixture: str = "auto",
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
    economy: dict[str, Any] = {"attempted": []}
    save_reload: dict[str, Any] = {"performed": False}
    scenario_id = ""
    scenario_status = ""
    treasury_start: dict[str, Any] = {}
    treasury_final: dict[str, Any] = {}
    victory: dict[str, Any] = {}

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
        else:
            catalog = _load_resolved_catalog(resolved_catalog_path)
            prefer_earth3 = fixture in {"auto", PRODUCTION_SCENARIO}
            state = None
            if prefer_earth3:
                try:
                    state = _build_earth3_state(catalog)
                    scenario_id = PRODUCTION_SCENARIO
                    scenario_status = "production"
                    created = "created"
                except Exception as exc:  # noqa: BLE001
                    if fixture == PRODUCTION_SCENARIO:
                        raise
                    gaps.append(
                        {
                            "id": "earth3_v1_create",
                            "severity": "skip",
                            "detail": f"earth3_v1 did not load on this SHA: {exc}",
                        }
                    )
                    state = None
            if state is None:
                state = _build_s10_state(work_dir)
                scenario_id = "s10_soak_fixture"
                scenario_status = "debug_fixture"
                created = "created"
                if write_full_snapshot is None:
                    write_full_snapshot = True
                gaps.append(
                    {
                        "id": "used_s10_fixture",
                        "severity": "skip",
                        "detail": (
                            "soak used the existing S10 operational fixture because "
                            "earth3_v1 was not selected or did not load"
                        ),
                    }
                )
                try:
                    from test_s10_frontend_presentation_contract import (
                        _create_prepared_contact,
                    )

                    _create_prepared_contact(state)
                except Exception as exc:  # noqa: BLE001
                    gaps.append(
                        {
                            "id": "s10_prepared_contact",
                            "severity": "skip",
                            "detail": f"could not seed an S10 prepared contact: {exc}",
                        }
                    )
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
        victory = _victory_probe(state)
        gaps[:] = _static_gaps(scenario_probe, victory) + [
            gap
            for gap in gaps
            if gap["id"] in {"earth3_v1_create", "used_s10_fixture"}
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
        mid_turn = max(1, turns // 2)
        guard = 0
        max_steps = max(8, turns * 8)
        while turns_completed < turns and guard < max_steps:
            guard += 1
            state = load_campaign(session.campaign)
            if state.pending_battle is not None:
                payload = session.apply([{"op": "auto_resolve"}])
                if payload.get("ok"):
                    battles += 1
                continue
            if state.current_faction == state.selected_faction:
                if not economy_done:
                    economy = _exercise_economy(state, gaps)
                    from gates_of_codex.state_io import save_campaign as _save

                    session.stop_daemon()
                    _save(state, session.campaign)
                    if session.use_daemon:
                        session.start_daemon()
                    economy_done = True
                    continue
                move = _select_move(state)
                if move is not None:
                    session.apply(
                        [
                            move,
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
                session.apply([{"op": "end_player_round"}])
                turns_completed += 1
                if turns_completed == mid_turn:
                    session.stop_daemon()
                    reloaded = load_campaign(session.campaign)
                    before_reload = campaign_identity(reloaded)
                    save_campaign(reloaded, session.campaign)
                    again = load_campaign(session.campaign)
                    after_reload = campaign_identity(again)
                    if after_reload != before_reload:
                        raise SoakFatalError(
                            "save_identity_break",
                            f"save/reload identity changed: {before_reload} -> {after_reload}",
                        )
                    save_reload = {
                        "performed": True,
                        "identity_ok": True,
                        "turn": turns_completed,
                        "identity": after_reload,
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
            state = load_campaign(session.campaign)
        treasury_final = treasury_snapshot(state)
        victory = _victory_probe(state)
        if victory.get("outcome") and victory["outcome"]["status"] == "active":
            gaps.append(
                {
                    "id": "campaign_not_won",
                    "severity": "gap",
                    "detail": (
                        f"{turns_completed}-turn soak did not reach victory/defeat; "
                        "#75 campaign-end work is landing in parallel"
                    ),
                }
            )
        if battles == 0:
            gaps.append(
                {
                    "id": "no_battles_auto_resolved",
                    "severity": "skip",
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
    failed = [row for row in commands if not row.get("ok")]
    report = {
        "ok": fatal is None,
        "fatal": fatal,
        "base_sha": "b5320ce04bc006fc1cc936c582d126f0a560ba3e",
        "scenario_id": scenario_id,
        "scenario_status": scenario_status,
        "campaign_created": created if "created" in locals() else "",
        "turns_requested": turns,
        "turns_completed": turns_completed,
        "battles_auto_resolved": battles,
        "commands_attempted": len(commands),
        "commands_failed": len(failed),
        "commands": commands,
        "economy": economy,
        "missing_player_loop_capabilities": [
            gap for gap in gaps if gap.get("severity") == "gap"
        ],
        "gaps": gaps,
        "treasury_start": treasury_start,
        "treasury_final": treasury_final,
        "victory_api": victory,
        "defeat_api": {
            "evaluate_campaign_outcome_exists": victory.get(
                "evaluate_campaign_outcome_exists", False
            ),
            "frontend_defeat_op": victory.get("frontend_victory_op", False),
            "selected_faction_result": (victory.get("outcome") or {}).get(
                "selected_faction_result"
            ),
        },
        "scenario_probe": scenario_probe,
        "persist_gate": persist,
        "save_reload": save_reload,
        "daemon": {
            "requested": use_daemon,
            "used": bool(session.daemon_used) if session is not None else False,
        },
        "goh_invoked": False,
        "morale_changed": False,
        "runtime_patch_schema_v1": persist.get("schema_version") == 1,
        "documented_commands": {
            "ci_smoke": (
                "python tools/auto_resolve_soak_harness.py --turns 3 --fixture s10 "
                "--report artifacts/auto_resolve_soak.json"
            ),
            "long_earth3": (
                "GOC_AUTO_RESOLVE_SOAK_TURNS=12 python tools/auto_resolve_soak_harness.py "
                "--fixture earth3_v1 --report artifacts/auto_resolve_soak.json"
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
        help="Create earth3_v1 when possible; s10 is the fast CI fixture",
    )
    parser.add_argument(
        "--resolved-catalog",
        type=Path,
        help="Resolved-factions JSON for earth3_v1 construction",
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
            resolved_catalog_path=args.resolved_catalog,
            use_daemon=not args.no_daemon,
            write_full_snapshot=True if args.write_full_snapshot else None,
        )
        path = write_report(report, args.report)
        print(json.dumps({"report": str(path), "ok": report["ok"], "fatal": report["fatal"]}, indent=2))
        return 0 if report["ok"] else 1
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
