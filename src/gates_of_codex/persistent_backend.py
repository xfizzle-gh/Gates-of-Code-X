from __future__ import annotations

"""Persistent command backend for the #207 strategic responsiveness lane.

The authoritative campaign file remains the source of truth. The daemon keeps a
validated in-memory copy only while the on-disk file fingerprint remains exact.
Every mutating command still commits the canonical campaign before a response is
returned. Unsupported/self-committing operations fall back to the normal one-shot
backend and invalidate the daemon cache first.
"""

import copy
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

SESSION_FILE_NAME = ".goc-backend-session.json"
SESSION_SCHEMA = "gates-of-codex.persistent-backend"
SESSION_SCHEMA_VERSION = 1
SUPPORTED_OPS = frozenset(
    {"end_player_round", "issue_move_order", "cancel_move_order", "verify_result"}
)
IDLE_TIMEOUT_SECONDS = 900.0


def _session_path(campaign: Path) -> Path:
    return campaign.resolve(strict=False).with_name(SESSION_FILE_NAME)


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
    if str(payload.get("campaign_path", "")) != str(campaign.resolve(strict=False)):
        return None
    return payload


def _request(
    session: dict[str, Any],
    payload: dict[str, Any],
    *,
    timeout: float = 2.0,
) -> dict[str, Any] | None:
    try:
        port = int(session.get("port", 0))
        token = str(session.get("token", ""))
    except (TypeError, ValueError):
        return None
    if port <= 0 or not token:
        return None
    message = dict(payload)
    message["token"] = token
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


def try_forward_apply_frontend(argv: Sequence[str]) -> tuple[int, str] | None:
    """Forward an apply-frontend invocation to a healthy daemon when possible."""

    parsed = _apply_invocation(argv)
    if parsed is None:
        return None
    campaign, snapshot, commands = parsed
    session = _read_session(campaign)
    if session is None:
        return None
    response = _request(
        session,
        {
            "action": "apply",
            "campaign_path": str(campaign),
            "snapshot_path": str(snapshot) if snapshot is not None else "",
            "commands_path": str(commands) if commands is not None else "",
        },
        timeout=30.0,
    )
    if response is None:
        try:
            _session_path(campaign).unlink()
        except OSError:
            pass
        return None
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


def ensure_backend_session(campaign: Path, snapshot: Path) -> bool:
    """Start one daemon for the campaign if one is not already healthy.

    Failure is intentionally non-fatal: the existing one-shot backend remains the
    correctness fallback. Returning False means only that no performance daemon
    could be established.
    """

    campaign = campaign.expanduser().resolve(strict=False)
    snapshot = snapshot.expanduser().resolve(strict=False)
    if _ping(campaign):
        return True
    try:
        _session_path(campaign).unlink()
    except OSError:
        pass

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

    from . import command_cycle_perf as perf
    from . import frontend_commands as commands_module
    from .state_io import load_campaign

    cached_state = load_campaign(campaign)
    cached_fingerprint = _fingerprint(campaign)
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
                connection.settimeout(30.0)
                stream = connection.makefile("rwb")
                raw = stream.readline(4 * 1024 * 1024)
                response: dict[str, Any]
                try:
                    request = json.loads(raw.decode("utf-8")) if raw else {}
                except (UnicodeDecodeError, ValueError):
                    request = {}
                if not isinstance(request, dict) or request.get("token") != token:
                    response = {"handled": True, "exit_code": 2, "stdout": "", "ok": False}
                elif request.get("action") == "ping":
                    response = {"handled": True, "exit_code": 0, "stdout": "", "ok": True}
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
                            working_state = copy.deepcopy(cached_state)
                            captured_state: dict[str, Any] = {"value": None}
                            original_loader = commands_module.load_campaign
                            original_compact_save = perf._compact_save_campaign

                            def cached_loader(_path):
                                return copy.deepcopy(working_state)

                            def capturing_save(state, path, *, observation_context=None):
                                result = original_compact_save(
                                    state,
                                    path,
                                    observation_context=observation_context,
                                )
                                captured_state["value"] = copy.deepcopy(state)
                                return result

                            commands_module.load_campaign = cached_loader
                            perf._compact_save_campaign = capturing_save
                            try:
                                report = perf.measured_apply_frontend_commands(
                                    campaign,
                                    commands_path=commands_path,
                                    snapshot_path=(Path(request_snapshot) if request_snapshot else snapshot),
                                )
                            finally:
                                commands_module.load_campaign = original_loader
                                perf._compact_save_campaign = original_compact_save
                            if bool(report.get("ok", False)) and captured_state["value"] is not None:
                                cached_state = captured_state["value"]
                                cached_fingerprint = _fingerprint(campaign)
                            elif not bool(report.get("ok", False)):
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
