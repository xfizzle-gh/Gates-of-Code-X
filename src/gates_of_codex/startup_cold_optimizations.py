from __future__ import annotations

"""Fail-closed cold/full-path startup shortcuts for issue #221.

The warm unchanged-daemon fast path lives in ``fast_entrypoint``. This module
handles the complementary full path used when no reusable daemon is available:
it avoids rewriting unchanged authority, reuses only byte-identical derived
snapshots, and starts the performance daemon without blocking first paint.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Mapping


SNAPSHOT_CACHE_SCHEMA = "gates-of-codex.frontend-launch-cache"
SNAPSHOT_CACHE_VERSION = 2
SNAPSHOT_CACHE_DIRECTORY_NAME = "frontend_launch_cache"
SNAPSHOT_CACHE_FILE_NAME = ".goc-frontend-launch-cache.json"

_INSTALLED = False
_UNCHANGED_CONTINUE_BASELINES: dict[int, tuple[tuple[str, ...], str]] = {}
_BACKEND_STARTING: set[str] = set()
_LAUNCH_REQUESTED = False
_CACHE_WRITE_THREADS: list[threading.Thread] = []


def _emit(stage: str, *, duration_ms: float | None = None, **fields: Any) -> None:
    try:
        from . import fast_entrypoint

        fast_entrypoint._emit_startup_timing(
            stage,
            duration_ms=duration_ms,
            **fields,
        )
    except Exception:
        return


def _source_commit() -> str | None:
    from .packaging import PackagingError, resolve_source_commit

    try:
        return resolve_source_commit()
    except (PackagingError, OSError):
        return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_identity(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=False)
    metadata = resolved.stat()
    return {
        "path": str(resolved),
        "size": int(metadata.st_size),
        "sha256": _sha256_file(resolved),
    }


def _size_path_matches(path: Path, stored: object) -> bool:
    if not isinstance(stored, dict):
        return False
    try:
        current = path.expanduser().resolve(strict=False)
        metadata = current.stat()
    except OSError:
        return False
    return stored.get("path") == str(current) and stored.get("size") == int(
        metadata.st_size
    )


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
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


def _snapshot_cache_path(
    campaign: Path,
    snapshot: Path,
    *,
    environ: Mapping[str, str] | None,
) -> Path:
    from .player_shell import player_home

    campaign = campaign.expanduser().resolve(strict=False)
    snapshot = snapshot.expanduser().resolve(strict=False)
    identity = hashlib.sha256(
        f"{campaign}\0{snapshot}".encode("utf-8")
    ).hexdigest()
    return player_home(environ) / SNAPSHOT_CACHE_DIRECTORY_NAME / f"{identity}.json"


def _legacy_snapshot_cache_path(snapshot: Path) -> Path:
    return snapshot.resolve(strict=False).with_name(SNAPSHOT_CACHE_FILE_NAME)


def _forget_legacy_campaign_tree_cache(snapshot: Path) -> None:
    legacy = _legacy_snapshot_cache_path(snapshot)
    try:
        if legacy.is_file():
            legacy.unlink()
    except OSError:
        return


def _maintenance_signature(
    campaign: Path,
    *,
    environ: Mapping[str, str] | None,
) -> str:
    from . import frontend

    payload = frontend._maintenance_block(campaign, environ=environ)
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _snapshot_context(
    campaign: Path,
    snapshot: Path,
    *,
    environ: Mapping[str, str] | None,
    role: str | None = None,
) -> dict[str, Any] | None:
    commit = _source_commit()
    if commit is None:
        return None
    from .player_shell import player_home

    executable = Path(sys.executable).expanduser().resolve(strict=False)
    if not executable.is_file():
        return None
    try:
        started = time.perf_counter()
        runtime_identity = _file_identity(executable)
        if role is not None:
            _emit(
                "frontend_snapshot_executable_identity",
                duration_ms=(time.perf_counter() - started) * 1000.0,
                method="sha256",
                role=role,
            )
        started = time.perf_counter()
        maintenance = _maintenance_signature(campaign, environ=environ)
        if role is not None:
            _emit(
                "frontend_snapshot_maintenance_signature",
                duration_ms=(time.perf_counter() - started) * 1000.0,
                role=role,
            )
    except OSError:
        return None
    return {
        "schema": SNAPSHOT_CACHE_SCHEMA,
        "schema_version": SNAPSHOT_CACHE_VERSION,
        "source_commit": commit,
        "runtime_executable": runtime_identity,
        "managed_home": str(player_home(environ)),
        "campaign_path": str(campaign.resolve(strict=False)),
        "snapshot_path": str(snapshot.resolve(strict=False)),
        "maintenance_signature": maintenance,
    }


def _capture_published_pair_identities(
    campaign: Path,
    snapshot: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    campaign_identity = _file_identity(campaign)
    _emit(
        "frontend_snapshot_campaign_hash",
        duration_ms=(time.perf_counter() - started) * 1000.0,
        role="publish",
    )
    started = time.perf_counter()
    snapshot_identity = _file_identity(snapshot)
    _emit(
        "frontend_snapshot_snapshot_hash",
        duration_ms=(time.perf_counter() - started) * 1000.0,
        role="publish",
    )
    return campaign_identity, snapshot_identity


def _write_snapshot_cache(
    campaign: Path,
    snapshot: Path,
    *,
    environ: Mapping[str, str] | None,
    campaign_identity: Mapping[str, Any] | None = None,
    snapshot_identity: Mapping[str, Any] | None = None,
) -> bool:
    context = _snapshot_context(
        campaign,
        snapshot,
        environ=environ,
        role="publish",
    )
    if context is None or not campaign.is_file() or not snapshot.is_file():
        return False
    try:
        current_campaign, current_snapshot = _capture_published_pair_identities(
            campaign,
            snapshot,
        )
        if campaign_identity is None:
            campaign_identity = current_campaign
        if snapshot_identity is None:
            snapshot_identity = current_snapshot
        if (
            dict(campaign_identity) != current_campaign
            or dict(snapshot_identity) != current_snapshot
        ):
            _emit(
                "frontend_snapshot_cache_publish",
                published=False,
                reason="pair_mutated",
            )
            return False
        payload = dict(context)
        payload["campaign"] = dict(campaign_identity)
        payload["snapshot"] = dict(snapshot_identity)
        started = time.perf_counter()
        _atomic_json(
            _snapshot_cache_path(campaign, snapshot, environ=environ),
            payload,
        )
        _forget_legacy_campaign_tree_cache(snapshot)
        _emit(
            "frontend_snapshot_cache_publish",
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )
    except (OSError, ValueError, TypeError):
        return False
    return True


def _cheap_cache_metadata(
    campaign: Path,
    snapshot: Path,
    *,
    environ: Mapping[str, str] | None,
) -> dict[str, Any] | None:
    commit = _source_commit()
    if commit is None:
        return None
    from .player_shell import player_home

    return {
        "schema": SNAPSHOT_CACHE_SCHEMA,
        "schema_version": SNAPSHOT_CACHE_VERSION,
        "source_commit": commit,
        "managed_home": str(player_home(environ)),
        "campaign_path": str(campaign.resolve(strict=False)),
        "snapshot_path": str(snapshot.resolve(strict=False)),
    }


def _schedule_snapshot_cache_write(
    campaign: Path,
    snapshot: Path,
    *,
    environ: Mapping[str, str] | None,
    campaign_identity: Mapping[str, Any],
    snapshot_identity: Mapping[str, Any],
) -> None:
    campaign = campaign.expanduser().resolve(strict=False)
    snapshot = snapshot.expanduser().resolve(strict=False)
    frozen_campaign = dict(campaign_identity)
    frozen_snapshot = dict(snapshot_identity)

    def worker() -> None:
        try:
            _write_snapshot_cache(
                campaign,
                snapshot,
                environ=environ,
                campaign_identity=frozen_campaign,
                snapshot_identity=frozen_snapshot,
            )
        except Exception:
            return

    thread = threading.Thread(
        target=worker,
        name="goc-frontend-snapshot-cache",
        daemon=True,
    )
    _CACHE_WRITE_THREADS.append(thread)
    thread.start()


def _snapshot_cache_valid(
    campaign: Path,
    snapshot: Path,
    *,
    environ: Mapping[str, str] | None,
) -> bool:
    cache = _snapshot_cache_path(campaign, snapshot, environ=environ)
    if not campaign.is_file() or not snapshot.is_file() or not cache.is_file():
        return False
    try:
        payload = json.loads(cache.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            return False
        cheap = _cheap_cache_metadata(campaign, snapshot, environ=environ)
        if cheap is None:
            return False
        for key, expected in cheap.items():
            if payload.get(key) != expected:
                return False
        stored_campaign = payload.get("campaign")
        stored_snapshot = payload.get("snapshot")
        if not _size_path_matches(campaign, stored_campaign):
            return False
        if not _size_path_matches(snapshot, stored_snapshot):
            return False
        context = _snapshot_context(
            campaign,
            snapshot,
            environ=environ,
            role="validate",
        )
        if context is None:
            return False
        for key, expected in context.items():
            if payload.get(key) != expected:
                return False
        started = time.perf_counter()
        campaign_identity = _file_identity(campaign)
        _emit(
            "frontend_snapshot_campaign_hash",
            duration_ms=(time.perf_counter() - started) * 1000.0,
            role="validate",
        )
        if stored_campaign != campaign_identity:
            return False
        started = time.perf_counter()
        snapshot_identity = _file_identity(snapshot)
        _emit(
            "frontend_snapshot_snapshot_hash",
            duration_ms=(time.perf_counter() - started) * 1000.0,
            role="validate",
        )
        return stored_snapshot == snapshot_identity
    except (OSError, ValueError, TypeError):
        return False


def _begin_backend_session_nonblocking(
    persistent_backend,
    campaign: Path,
    snapshot: Path,
) -> bool:
    campaign = campaign.expanduser().resolve(strict=False)
    snapshot = snapshot.expanduser().resolve(strict=False)
    key = str(campaign)
    if persistent_backend._runtime_source_commit() is None:
        persistent_backend._drop_session_descriptor(campaign)
        _BACKEND_STARTING.discard(key)
        return False
    if persistent_backend._ping(campaign):
        _BACKEND_STARTING.discard(key)
        return True
    if key in _BACKEND_STARTING:
        return False

    persistent_backend._drop_session_descriptor(campaign)
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
    creationflags = (
        int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
    )
    started = time.perf_counter()
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
        _emit(
            "persistent_backend_spawn",
            duration_ms=(time.perf_counter() - started) * 1000.0,
            started=False,
        )
        return False
    _BACKEND_STARTING.add(key)
    _emit(
        "persistent_backend_spawn",
        duration_ms=(time.perf_counter() - started) * 1000.0,
        started=True,
    )
    return False


def _install_import_cache_guard(fast_entrypoint) -> None:
    current = fast_entrypoint._read_godot_import_stamp
    if getattr(current, "_goc_class_cache_guard", False):
        return

    def guarded_read_godot_import_stamp(project_directory: Path):
        class_cache = (
            project_directory.resolve(strict=False)
            / ".godot"
            / "global_script_class_cache.cfg"
        )
        if not class_cache.is_file():
            return None
        return current(project_directory)

    guarded_read_godot_import_stamp._goc_class_cache_guard = True
    fast_entrypoint._read_godot_import_stamp = guarded_read_godot_import_stamp


def _install_player_full_path_shortcuts(player_shell, persistent_backend) -> None:
    if getattr(player_shell.continue_campaign, "_goc_full_startup_shortcut", False):
        return

    original_save = player_shell.save_campaign
    original_continue = player_shell.continue_campaign
    original_publish = player_shell.publish_snapshot
    original_run_play = player_shell.run_play

    def optimized_continue_campaign(
        *,
        paths,
        faction=None,
        difficulty=None,
        fog_of_war=None,
        stack_config=None,
        game_directory=None,
        profile_directory=None,
        tactical_map=None,
        godot_executable=None,
        godot_project=None,
    ):
        if not paths.campaign.is_file():
            return original_continue(
                paths=paths,
                faction=faction,
                difficulty=difficulty,
                fog_of_war=fog_of_war,
                stack_config=stack_config,
                game_directory=game_directory,
                profile_directory=profile_directory,
                tactical_map=tactical_map,
                godot_executable=godot_executable,
                godot_project=godot_project,
            )

        state = player_shell.load_campaign(paths.campaign)
        scenario_id = (
            str(state.map_metadata.get("scenario_id", ""))
            or player_shell.DEFAULT_SCENARIO_ID
        )
        changed = False
        if faction and state.selected_faction.value != faction:
            player_shell._apply_faction(state, scenario_id, faction)
            changed = True
        if difficulty and state.difficulty != difficulty:
            state.difficulty = difficulty
            changed = True
        if fog_of_war:
            requested_fog = fog_of_war == "on"
            if state.fog_of_war_enabled != requested_fog:
                state.fog_of_war_enabled = requested_fog
                changed = True

        before_launch = player_shell.launch_settings(state)
        player_shell.persist_launch_settings(
            state,
            paths=paths,
            stack_config=stack_config,
            game_directory=game_directory,
            profile_directory=profile_directory,
            tactical_map=tactical_map,
            godot_executable=godot_executable,
            godot_project=godot_project,
        )
        if player_shell.launch_settings(state) != before_launch:
            changed = True

        if changed:
            original_save(state, paths.campaign)
            _emit("campaign_continue_save", saved=True)
        else:
            resource_stack = state.map_metadata.get("resource_stack")
            baseline_stack = (
                tuple(str(item) for item in resource_stack)
                if isinstance(resource_stack, list)
                else ()
            )
            _UNCHANGED_CONTINUE_BASELINES[id(state)] = (
                baseline_stack,
                str(state.code_x_directory or ""),
            )
            _emit("campaign_continue_save", saved=False)
        return state

    optimized_continue_campaign._goc_full_startup_shortcut = True
    player_shell.continue_campaign = optimized_continue_campaign

    def conditional_save(state, path):
        baseline = _UNCHANGED_CONTINUE_BASELINES.pop(id(state), None)
        if baseline is not None:
            resource_stack = state.map_metadata.get("resource_stack")
            current_stack = (
                tuple(str(item) for item in resource_stack)
                if isinstance(resource_stack, list)
                else ()
            )
            current_codex = str(state.code_x_directory or "")
            if (current_stack, current_codex) == baseline:
                _emit("campaign_redundant_stack_save", saved=False)
                return None
        return original_save(state, path)

    conditional_save._goc_full_startup_shortcut = True
    player_shell.save_campaign = conditional_save

    def cached_publish_snapshot(state, paths, *, environ=None):
        started = time.perf_counter()
        hit = _snapshot_cache_valid(
            paths.campaign,
            paths.snapshot,
            environ=environ,
        )
        if hit:
            from .frontend_commands import clear_commands

            clear_commands(paths.commands)
            written = paths.snapshot
        else:
            construct_started = time.perf_counter()
            written = original_publish(state, paths, environ=environ)
            _emit(
                "frontend_snapshot_construct_write",
                duration_ms=(time.perf_counter() - construct_started) * 1000.0,
            )
            campaign_identity, snapshot_identity = _capture_published_pair_identities(
                paths.campaign,
                paths.snapshot,
            )
            _forget_legacy_campaign_tree_cache(paths.snapshot)
            _schedule_snapshot_cache_write(
                paths.campaign,
                paths.snapshot,
                environ=environ,
                campaign_identity=campaign_identity,
                snapshot_identity=snapshot_identity,
            )
        _UNCHANGED_CONTINUE_BASELINES.pop(id(state), None)
        if _LAUNCH_REQUESTED:
            _begin_backend_session_nonblocking(
                persistent_backend,
                paths.campaign,
                paths.snapshot,
            )
        _emit(
            "frontend_snapshot_cache",
            duration_ms=(time.perf_counter() - started) * 1000.0,
            hit=hit,
        )
        return written

    cached_publish_snapshot._goc_full_startup_shortcut = True
    player_shell.publish_snapshot = cached_publish_snapshot

    def launch_context_run_play(args, *, environ=None, resolved_catalog=None):
        global _LAUNCH_REQUESTED
        previous = _LAUNCH_REQUESTED
        _LAUNCH_REQUESTED = not bool(args.no_launch)
        try:
            return original_run_play(
                args,
                environ=environ,
                resolved_catalog=resolved_catalog,
            )
        finally:
            _LAUNCH_REQUESTED = previous

    launch_context_run_play._goc_full_startup_shortcut = True
    player_shell.run_play = launch_context_run_play


def _install_nonblocking_backend_ensure(persistent_backend) -> None:
    current = persistent_backend.ensure_backend_session
    if getattr(current, "_goc_nonblocking_startup", False):
        return

    def nonblocking_ensure_backend_session(campaign: Path, snapshot: Path) -> bool:
        return _begin_backend_session_nonblocking(
            persistent_backend,
            campaign,
            snapshot,
        )

    nonblocking_ensure_backend_session._goc_nonblocking_startup = True
    persistent_backend.ensure_backend_session = nonblocking_ensure_backend_session


def install_packaged_full_startup_shortcuts() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    from . import fast_entrypoint, persistent_backend, player_shell

    _install_import_cache_guard(fast_entrypoint)
    _install_player_full_path_shortcuts(player_shell, persistent_backend)
    _install_nonblocking_backend_ensure(persistent_backend)
    _INSTALLED = True
