from __future__ import annotations

"""Persistent command backend for the #207 strategic responsiveness lane.

The authoritative campaign file remains the source of truth. The daemon keeps a
validated in-memory copy only while the on-disk file fingerprint remains exact.
Every mutating command still commits the canonical campaign before a response is
returned. Unsupported/self-committing operations fall back to the normal one-shot
backend and invalidate the daemon cache first.
"""

import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

from .packaging import PackagingError, resolve_source_commit


SESSION_FILE_NAME = ".goc-backend-session.json"
SESSION_SCHEMA = "gates-of-codex.persistent-backend"
SESSION_SCHEMA_VERSION = 2
SUPPORTED_OPS = frozenset(
    {"end_player_round", "issue_move_order", "cancel_move_order", "verify_result"}
)
IDLE_TIMEOUT_SECONDS = 900.0
APPLY_RESPONSE_TIMEOUT_SECONDS = 600.0


def _session_path(campaign: Path) -> Path:
    return campaign.resolve(strict=False).with_name(SESSION_FILE_NAME)


def _runtime_source_commit() -> str | None:
    """Return this process's immutable package provenance, or fail closed."""

    try:
        return resolve_source_commit()
    except (PackagingError, OSError):
        return None


def _drop_session_descriptor(campaign: Path) -> None:
    try:
        _session_path(campaign).unlink()
    except OSError:
        pass


def _fingerprint(path: Path) -> tuple[int, int, str]:
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return int(stat.st_size), int(stat.st_mtime_ns), digest


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary.write(body)
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


def _read_session(campaign: Path) -> dict[str, Any] | None:
    source_commit = _runtime_source_commit()
    if source_commit is None:
        return None
    source = _session_path(campaign)
    if not source.is_file():
        return None
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema") != SESSION_SCHEMA:
        return None
    if int(payload.get("schema_version", 0) or 0) != SESSION_SCHEMA_VERSION:
        return None
    if str(payload.get("source_commit", "")).strip().lower() != source_commit:
        return None
    if str(payload.get("campaign_path", "")) != str(campaign.resolve(strict=False)):
        return None
    return payload


def _request(
    session: dict[str, Any],
    payload: dict[str, Any],
    *,
    timeout: float = 2.0,
) -> dict[str, Any] | None:
    source_commit = _runtime_source_commit()
    if source_commit is None:
        return None
    try:
        port = int(session.get("port", 0))
        token = str(session.get("token", ""))
    except (TypeError, ValueError):
        return None
    if port <= 0 or not token:
        return None
    message = dict(payload)
    message["token"] = token
    message["source_commit"] = source_commit
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as connection:
            connection.settimeout(timeout)
            stream = connection.makefile("rwb")
            stream.write((json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8"))
            stream.flush()
            raw = stream.readline(64 * 1024 * 1024)
    except (OSError, TimeoutError):
        return None
    if not raw:
        return None
    try:
        response = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return response if isinstance(response, dict) else None


def _apply_invocation(argv: Sequence[str]) -> tuple[Path, Path | None, Path | None] | None:
    arguments = list(argv)
    if not arguments or arguments[0] != "apply-frontend" or len(arguments) < 2:
        return None
    campaign = Path(arguments[1]).expanduser().resolve(strict=False)
    snapshot: Path | None = None
    commands: Path | None = None
    index = 2
    while index < len(arguments):
        token = arguments[index]
        if token == "--snapshot" and index + 1 < len(arguments):
            snapshot = Path(arguments[index + 1]).expanduser().resolve(strict=False)
            index += 2
            continue
        if token == "--commands" and index + 1 < len(arguments):
            commands = Path(arguments[index + 1]).expanduser().resolve(strict=False)
            index += 2
            continue
        index += 1
    return campaign, snapshot, commands


def _ambiguous_daemon_payload() -> str:
    return json.dumps(
        {
            "ok": False,
            "campaign_path": "",
            "snapshot_path": "",
            "commands_applied": 0,
            "results": [
                {
                    "op": "persistent_backend",
                    "ok": False,
                    "detail": (
                        "Persistent backend response was lost after dispatch; "
                        "command outcome is ambiguous. Reload campaign state before retrying."
                    ),
                    "data": {},
                }
            ],
        },
        separators=(",", ":"),
    )


def try_forward_apply_frontend(argv: Sequence[str]) -> tuple[int, str] | None:
    """Forward an apply-frontend invocation to a healthy daemon when possible.

    A stale/unreachable session falls back before dispatch. Once an apply request
    has been sent, response loss never triggers automatic one-shot replay because
    that could race a command which actually committed but lost its reply.
    """

    parsed = _apply_invocation(argv)
    if parsed is None:
        return None
    campaign, snapshot, commands = parsed
    session = _read_session(campaign)
    if session is None:
        if _session_path(campaign).is_file():
            _drop_session_descriptor(campaign)
        return None

    ping = _request(session, {"action": "ping"}, timeout=0.4)
    if not ping or ping.get("ok") is not True:
        _drop_session_descriptor(campaign)
        return None

    response = _request(
        session,
        {
            "action": "apply",
            "campaign_path": str(campaign),
            "snapshot_path": str(snapshot) if snapshot is not None else "",
            "commands_path": str(commands) if commands is not None else "",
        },
        timeout=APPLY_RESPONSE_TIMEOUT_SECONDS,
    )
    if response is None:
        _drop_session_descriptor(campaign)
        return 0, _ambiguous_daemon_payload()
    if not bool(response.get("handled", False)):
        _request(session, {"action": "invalidate"}, timeout=1.0)
        return None
    return int(response.get("exit_code", 1)), str(response.get("stdout", ""))


def _ping(campaign: Path) -> bool:
    session = _read_session(campaign)
    if session is None:
        return False
    response = _request(session, {"action": "ping"}, timeout=0.4)
    return bool(response and response.get("ok") is True)


def _startup_state_summary(state) -> dict[str, Any]:
    metadata = state.map_metadata if isinstance(state.map_metadata, dict) else {}
    launch = metadata.get("player_launch", {})
    launch_record = dict(launch) if isinstance(launch, dict) else {}
    resource_stack = metadata.get("resource_stack", [])
    return {
        "scenario_id": str(metadata.get("scenario_id", "")),
        "map_id": str(state.map_id),
        "selected_faction": str(state.selected_faction.value),
        "difficulty": str(state.difficulty),
        "fog_of_war": "on" if bool(state.fog_of_war_enabled) else "off",
        "turn_number": int(state.turn_number),
        "stack_config": str(metadata.get("stack_config", "") or ""),
        "tactical_map": str(metadata.get("preferred_map", "") or ""),
        "game_directory": str(state.game_directory or ""),
        "profile_directory": str(state.profile_directory or ""),
        "code_x_directory": str(state.code_x_directory or ""),
        "resource_stack": list(resource_stack) if isinstance(resource_stack, list) else [],
        "player_launch": launch_record,
    }


def _startup_reuse_response(
    *,
    cached_state,
    cached_fingerprint: tuple[int, int, str] | None,
    startup_campaign_fingerprint: tuple[int, int, str] | None,
    startup_snapshot_fingerprint: tuple[int, int, str] | None,
    campaign: Path,
    snapshot: Path | None,
) -> dict[str, Any]:
    """Prove that the daemon's launch-time validated campaign/snapshot are intact."""

    if (
        cached_state is None
        or cached_fingerprint is None
        or startup_campaign_fingerprint is None
        or startup_snapshot_fingerprint is None
        or snapshot is None
    ):
        return {
            "handled": True,
            "exit_code": 0,
            "ok": False,
            "reason": "startup_baseline_unavailable",
        }
    try:
        current_campaign_fingerprint = _fingerprint(campaign)
        current_snapshot_fingerprint = _fingerprint(snapshot)
    except OSError:
        return {
            "handled": True,
            "exit_code": 0,
            "ok": False,
            "reason": "startup_files_unavailable",
        }
    if current_campaign_fingerprint != startup_campaign_fingerprint:
        return {
            "handled": True,
            "exit_code": 0,
            "ok": False,
            "reason": "campaign_changed_since_startup",
        }
    if cached_fingerprint != startup_campaign_fingerprint:
        return {
            "handled": True,
            "exit_code": 0,
            "ok": False,
            "reason": "daemon_state_advanced_since_startup",
        }
    if current_snapshot_fingerprint != startup_snapshot_fingerprint:
        return {
            "handled": True,
            "exit_code": 0,
            "ok": False,
            "reason": "snapshot_changed_since_startup",
        }
    return {
        "handled": True,
        "exit_code": 0,
        "ok": True,
        "state": _startup_state_summary(cached_state),
    }


def probe_startup_reuse(campaign: Path, snapshot: Path) -> dict[str, Any] | None:
    """Return daemon-proven validated state only for an untouched launch baseline."""

    campaign = campaign.expanduser().resolve(strict=False)
    snapshot = snapshot.expanduser().resolve(strict=False)
    session = _read_session(campaign)
    if session is None:
        if _session_path(campaign).is_file():
            _drop_session_descriptor(campaign)
        return None
    response = _request(
        session,
        {
            "action": "startup_reuse",
            "campaign_path": str(campaign),
            "snapshot_path": str(snapshot),
        },
        timeout=0.8,
    )
    if response is None:
        _drop_session_descriptor(campaign)
        return None
    if response.get("ok") is not True:
        return None
    state = response.get("state")
    return dict(state) if isinstance(state, dict) else None


def ensure_backend_session(campaign: Path, snapshot: Path) -> bool:
    """Start one daemon for the campaign if one is not already healthy.

    Failure is intentionally non-fatal: the existing one-shot backend remains the
    correctness fallback. Returning False means only that no performance daemon
    could be established.
    """

    campaign = campaign.expanduser().resolve(strict=False)
    snapshot = snapshot.expanduser().resolve(strict=False)
    if _runtime_source_commit() is None:
        _drop_session_descriptor(campaign)
        return False
    if _ping(campaign):
        return True
    _drop_session_descriptor(campaign)

    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve().with_name("GatesOfCodeXLive.exe")
        command = [
            str(executable),
            "session-backend",
            str(campaign),
            "--snapshot",
            str(snapshot),
        ]
    else:
        command = [
            sys.executable,
            "-m",
            "gates_of_codex",
            "session-backend",
            str(campaign),
            "--snapshot",
            str(snapshot),
        ]
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
    try:
        subprocess.Popen(
            command,
            cwd=str(campaign.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    except OSError:
        return False
    deadline = time.monotonic() + 12.0
    while time.monotonic() < deadline:
        if _ping(campaign):
            return True
        time.sleep(0.05)
    return False


def _command_ops(commands_path: Path | None) -> list[str]:
    if commands_path is None or not commands_path.is_file():
        return []
    from .frontend_commands import read_commands

    return [str(row.get("op", "")).strip().lower() for row in read_commands(commands_path)]


def _direct_cache_loader(cached_state, original_loader):
    """Lease the validated daemon state to exactly one command load.

    The first load receives the cached object itself, avoiding a full campaign
    clone on every command. A second load in the same command is the command
    engine's rollback/reporting path after failure, so it must reload canonical
    disk state instead of exposing the possibly mutated leased object.
    """

    load_count = 0

    def load(path):
        nonlocal load_count
        load_count += 1
        if load_count == 1:
            return cached_state
        return original_loader(path)

    return load


def _cache_can_survive_report(
    report: dict[str, Any],
    ops: Sequence[str],
    *,
    persisted: bool,
) -> bool:
    """Retain daemon state only when its canonical relationship is proven."""

    if not bool(report.get("ok", False)):
        return False
    read_only = bool(ops) and all(op == "verify_result" for op in ops)
    return read_only or persisted


def run_session_backend(argv: Sequence[str]) -> int:
    """Serve bounded frontend commands while retaining a validated campaign copy."""

    arguments = list(argv)
    if not arguments:
        return 2
    campaign = Path(arguments[0]).expanduser().resolve(strict=False)
    snapshot: Path | None = None
    if "--snapshot" in arguments:
        index = arguments.index("--snapshot")
        if index + 1 < len(arguments):
            snapshot = Path(arguments[index + 1]).expanduser().resolve(strict=False)
    if not campaign.is_file():
        return 2
    source_commit = _runtime_source_commit()
    if source_commit is None:
        return 2

    from . import command_cycle_perf as perf
    from . import frontend_commands as commands_module
    from .state_io import load_campaign

    cached_state = load_campaign(campaign)
    cached_fingerprint = _fingerprint(campaign)
    startup_campaign_fingerprint = cached_fingerprint
    startup_snapshot_fingerprint = (
        _fingerprint(snapshot) if snapshot is not None and snapshot.is_file() else None
    )
    token = secrets.token_urlsafe(32)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    server.settimeout(1.0)
    port = int(server.getsockname()[1])
    descriptor = {
        "schema": SESSION_SCHEMA,
        "schema_version": SESSION_SCHEMA_VERSION,
        "source_commit": source_commit,
        "campaign_path": str(campaign),
        "snapshot_path": str(snapshot) if snapshot is not None else "",
        "port": port,
        "token": token,
        "pid": os.getpid(),
    }
    _atomic_json(_session_path(campaign), descriptor)
    last_activity = time.monotonic()

    try:
        while time.monotonic() - last_activity < IDLE_TIMEOUT_SECONDS:
            try:
                connection, _address = server.accept()
            except socket.timeout:
                continue
            last_activity = time.monotonic()
            with connection:
                connection.settimeout(APPLY_RESPONSE_TIMEOUT_SECONDS)
                stream = connection.makefile("rwb")
                raw = stream.readline(4 * 1024 * 1024)
                response: dict[str, Any]
                try:
                    request = json.loads(raw.decode("utf-8")) if raw else {}
                except (UnicodeDecodeError, ValueError):
                    request = {}
                if not isinstance(request, dict) or request.get("token") != token:
                    response = {"handled": True, "exit_code": 2, "stdout": "", "ok": False}
                elif request.get("source_commit") != source_commit:
                    response = {
                        "handled": False,
                        "reason": "source_commit_mismatch",
                        "exit_code": 2,
                        "stdout": "",
                        "ok": False,
                    }
                elif request.get("action") == "ping":
                    response = {"handled": True, "exit_code": 0, "stdout": "", "ok": True}
                elif request.get("action") == "startup_reuse":
                    request_campaign = Path(
                        str(request.get("campaign_path", ""))
                    ).resolve(strict=False)
                    request_snapshot_text = str(request.get("snapshot_path", "")).strip()
                    request_snapshot = (
                        Path(request_snapshot_text).resolve(strict=False)
                        if request_snapshot_text
                        else None
                    )
                    if request_campaign != campaign or request_snapshot != snapshot:
                        response = {
                            "handled": True,
                            "exit_code": 0,
                            "ok": False,
                            "reason": "startup_path_mismatch",
                        }
                    else:
                        response = _startup_reuse_response(
                            cached_state=cached_state,
                            cached_fingerprint=cached_fingerprint,
                            startup_campaign_fingerprint=startup_campaign_fingerprint,
                            startup_snapshot_fingerprint=startup_snapshot_fingerprint,
                            campaign=campaign,
                            snapshot=snapshot,
                        )
                elif request.get("action") == "invalidate":
                    cached_state = None
                    cached_fingerprint = None
                    response = {"handled": True, "exit_code": 0, "stdout": "", "ok": True}
                elif request.get("action") == "apply":
                    request_campaign = Path(str(request.get("campaign_path", ""))).resolve(strict=False)
                    request_snapshot = str(request.get("snapshot_path", "")).strip()
                    request_commands = str(request.get("commands_path", "")).strip()
                    commands_path = Path(request_commands).resolve(strict=False) if request_commands else None
                    if request_campaign != campaign:
                        response = {"handled": False, "reason": "campaign_mismatch"}
                    else:
                        ops = _command_ops(commands_path)
                        if not ops or any(op not in SUPPORTED_OPS for op in ops):
                            cached_state = None
                            cached_fingerprint = None
                            response = {"handled": False, "reason": "unsupported_op"}
                        else:
                            current_fingerprint = _fingerprint(campaign)
                            if cached_state is None or cached_fingerprint != current_fingerprint:
                                cached_state = load_campaign(campaign)
                                cached_fingerprint = current_fingerprint

                            persisted = False
                            original_loader = commands_module.load_campaign
                            original_compact_save = perf._compact_save_campaign

                            def capturing_save(
                                state,
                                path,
                                *,
                                observation_context=None,
                                subphase_seconds=None,
                            ):
                                nonlocal persisted
                                result = original_compact_save(
                                    state,
                                    path,
                                    observation_context=observation_context,
                                    subphase_seconds=subphase_seconds,
                                )
                                persisted = True
                                return result

                            commands_module.load_campaign = _direct_cache_loader(
                                cached_state,
                                original_loader,
                            )
                            perf._compact_save_campaign = capturing_save
                            try:
                                report = perf.measured_apply_frontend_commands(
                                    campaign,
                                    commands_path=commands_path,
                                    snapshot_path=(Path(request_snapshot) if request_snapshot else snapshot),
                                )
                            except Exception:
                                # The leased object may have been mutated before the
                                # command raised, including after a canonical save but
                                # before runtime-patch publication completed. Never
                                # retain that object or its old fingerprint. Re-raise
                                # so the daemon closes and the client reports the
                                # post-dispatch outcome as ambiguous rather than
                                # replaying a possibly committed mutation.
                                cached_state = None
                                cached_fingerprint = None
                                raise
                            finally:
                                commands_module.load_campaign = original_loader
                                perf._compact_save_campaign = original_compact_save

                            if _cache_can_survive_report(report, ops, persisted=persisted):
                                # The leased object is the same state normalized by
                                # the authoritative save. No second full-state clone
                                # is required. Re-fingerprint the canonical file so
                                # the next request still detects external mutation.
                                cached_fingerprint = _fingerprint(campaign)
                            else:
                                # A failed or unexpectedly unpersisted mutating
                                # command may have touched the leased object. Never
                                # reuse it. The next supported request reloads the
                                # canonical file through the normal validated path.
                                cached_state = None
                                cached_fingerprint = None

                            response = {
                                "handled": True,
                                "exit_code": 0,
                                "stdout": json.dumps(report, separators=(",", ":")),
                                "ok": bool(report.get("ok", False)),
                            }
                else:
                    response = {"handled": True, "exit_code": 2, "stdout": "", "ok": False}
                stream.write((json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8"))
                stream.flush()
    finally:
        server.close()
        try:
            session = _read_session(campaign)
            if session and int(session.get("pid", -1)) == os.getpid():
                _session_path(campaign).unlink()
        except OSError:
            pass
    return 0
