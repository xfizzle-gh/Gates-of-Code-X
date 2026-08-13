from __future__ import annotations

import functools
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path


STARTUP_TELEMETRY_ENV = "GATES_OF_CODEX_STARTUP_TELEMETRY"
STARTUP_EPOCH_ENV = "GATES_OF_CODEX_STARTUP_EPOCH_MS"
STARTUP_LOG_ENV = "GATES_OF_CODEX_STARTUP_LOG"
STARTUP_LOG_PREFIX = "GOC_STARTUP"
GODOT_IMPORT_STAMP_SCHEMA = "gates-of-codex.godot-import-cache"
GODOT_IMPORT_STAMP_VERSION = 2
GODOT_IMPORT_STAMP_NAME = "gates_of_codex_import_cache.json"
GODOT_FINGERPRINT_SKIP_DIRECTORIES = frozenset({".godot", ".import"})
GODOT_FINGERPRINT_SKIP_SUFFIXES = (".import", ".uid")
GODOT_FINGERPRINT_SKIP_NAMES = frozenset(
    {
        "campaign_snapshot.json",
        "frontend_commands.json",
        "commands.json",
        "screenshot_log.txt",
    }
)


def _startup_telemetry_enabled() -> bool:
    return str(os.environ.get(STARTUP_TELEMETRY_ENV, "")).strip() == "1"


def _startup_epoch_ms() -> float:
    raw = str(os.environ.get(STARTUP_EPOCH_ENV, "")).strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    value = time.time() * 1000.0
    os.environ[STARTUP_EPOCH_ENV] = f"{value:.3f}"
    return value


def _emit_startup_timing(
    stage: str,
    *,
    duration_ms: float | None = None,
    **fields,
) -> None:
    if not _startup_telemetry_enabled():
        return
    payload = {
        "stage": str(stage),
        "since_process_entry_ms": round(
            max(0.0, (time.time() * 1000.0) - _startup_epoch_ms()),
            3,
        ),
    }
    if duration_ms is not None:
        payload["duration_ms"] = round(max(0.0, float(duration_ms)), 3)
    payload.update(fields)
    print(
        f"{STARTUP_LOG_PREFIX} "
        + json.dumps(payload, sort_keys=True, separators=(",", ":")),
        flush=True,
    )


def _install_player_startup_timing(player_shell) -> None:
    """Instrument stable player-shell phase boundaries without changing authority."""

    stage_by_name = {
        "read_last_campaign": "campaign_discovery",
        "resolve_campaign_paths": "campaign_path_resolution",
        "validate_stack": "stack_validation",
        "find_godot_executable": "godot_executable_resolution",
        "godot_project_directory": "godot_project_resolution",
        "create_new_campaign": "campaign_create_validate_persist",
        "continue_campaign": "campaign_load_validate_persist",
        "publish_snapshot": "frontend_snapshot_build_write",
        "write_last_campaign": "campaign_pointer_write",
    }
    for name, stage in stage_by_name.items():
        current = getattr(player_shell, name)
        if getattr(current, "_goc_startup_timed", False):
            continue

        @functools.wraps(current)
        def timed(*args, __original=current, __stage=stage, **kwargs):
            started = time.perf_counter()
            try:
                return __original(*args, **kwargs)
            finally:
                _emit_startup_timing(
                    __stage,
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                )

        timed._goc_startup_timed = True  # type: ignore[attr-defined]
        setattr(player_shell, name, timed)


def _install_fast_paths() -> None:
    from .command_cycle_perf import install_command_cycle_perf_path
    from .command_scoped_p2_auth import install_command_scoped_p2_auth
    from .frontend_fastpath import install_frontend_fast_path
    from .turn_cycle import install_frontend_turn_cycle_op

    install_frontend_fast_path()
    install_frontend_turn_cycle_op()
    install_command_cycle_perf_path()
    install_command_scoped_p2_auth()


def _hash_regular_file(digest, path: Path) -> None:
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                return
            digest.update(chunk)


def _skip_godot_fingerprint_file(name: str) -> bool:
    if name.endswith(GODOT_FINGERPRINT_SKIP_SUFFIXES):
        return True
    if name in GODOT_FINGERPRINT_SKIP_NAMES:
        return True
    return name.startswith("home_") and name.endswith(".png")


def _godot_project_fingerprint(project_directory: Path) -> str | None:
    """Hash authored project sources, excluding generated Godot/runtime files."""

    project = project_directory.resolve(strict=False)
    if not (project / "project.godot").is_file():
        return None
    digest = hashlib.sha256()
    try:
        for root, directories, files in os.walk(project, followlinks=False):
            root_path = Path(root)
            kept_directories: list[str] = []
            for name in sorted(directories):
                candidate = root_path / name
                if name in GODOT_FINGERPRINT_SKIP_DIRECTORIES:
                    continue
                if candidate.is_symlink():
                    return None
                kept_directories.append(name)
            directories[:] = kept_directories
            for name in sorted(files):
                if _skip_godot_fingerprint_file(name):
                    continue
                candidate = root_path / name
                if candidate.is_symlink() or not candidate.is_file():
                    return None
                relative = candidate.relative_to(project).as_posix()
                digest.update(relative.encode("utf-8"))
                digest.update(b"\0")
                digest.update(str(candidate.stat().st_size).encode("ascii"))
                digest.update(b"\0")
                _hash_regular_file(digest, candidate)
                digest.update(b"\0")
    except OSError:
        return None
    return digest.hexdigest()


def _godot_executable_identity(godot_executable: Path) -> dict[str, object] | None:
    try:
        resolved = godot_executable.resolve(strict=True)
        metadata = resolved.stat()
    except OSError:
        return None
    return {
        "path": str(resolved),
        "size": int(metadata.st_size),
        "mtime_ns": int(metadata.st_mtime_ns),
    }


def _godot_import_stamp_path(project_directory: Path) -> Path:
    return project_directory.resolve(strict=False) / ".godot" / GODOT_IMPORT_STAMP_NAME


def _read_godot_import_stamp(project_directory: Path) -> dict[str, object] | None:
    source = _godot_import_stamp_path(project_directory)
    if not source.is_file():
        return None
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema") != GODOT_IMPORT_STAMP_SCHEMA:
        return None
    if int(payload.get("schema_version", 0) or 0) != GODOT_IMPORT_STAMP_VERSION:
        return None
    return payload


def _write_godot_import_stamp(
    project_directory: Path,
    *,
    source_commit: str,
    project_fingerprint: str,
    godot_identity: dict[str, object],
) -> None:
    destination = _godot_import_stamp_path(project_directory)
    destination.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        {
            "schema": GODOT_IMPORT_STAMP_SCHEMA,
            "schema_version": GODOT_IMPORT_STAMP_VERSION,
            "source_commit": source_commit,
            "project_fingerprint": project_fingerprint,
            "godot_identity": godot_identity,
        },
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
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


def _prepare_godot_project(
    godot_executable: Path,
    project_directory: Path,
    *,
    timeout_seconds: int = 180,
) -> None:
    """Import only when exact source/project/runtime identity changed.

    P6 proved that a clean project needs one synchronous import before the
    interactive launch. #221 keeps that correctness guard but avoids repeating
    the import for an unchanged project by hashing every source file and binding
    the derived cache to the immutable packaged source commit and Godot binary.
    Any missing/malformed identity falls back to the full import.
    """

    fingerprint_started = time.perf_counter()
    source_commit: str | None = None
    try:
        from .packaging import PackagingError, resolve_source_commit

        source_commit = resolve_source_commit()
    except (PackagingError, OSError):
        source_commit = None
    project_fingerprint = _godot_project_fingerprint(project_directory)
    godot_identity = _godot_executable_identity(godot_executable)
    fingerprint_ms = (time.perf_counter() - fingerprint_started) * 1000.0

    if source_commit and project_fingerprint and godot_identity:
        stamp = _read_godot_import_stamp(project_directory)
        if (
            stamp is not None
            and str(stamp.get("source_commit", "")) == source_commit
            and str(stamp.get("project_fingerprint", "")) == project_fingerprint
            and stamp.get("godot_identity") == godot_identity
        ):
            _emit_startup_timing(
                "godot_project_import",
                duration_ms=fingerprint_ms,
                ok=True,
                cached=True,
            )
            return

    arguments = [
        str(godot_executable),
        "--headless",
        "--path",
        str(project_directory),
        "--import",
        "--quit-after",
        "1",
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            arguments,
            cwd=str(project_directory),
            capture_output=True,
            text=True,
            check=False,
            timeout=max(1, timeout_seconds),
        )
    except subprocess.TimeoutExpired as exc:
        _emit_startup_timing(
            "godot_project_import",
            duration_ms=(time.perf_counter() - started) * 1000.0 + fingerprint_ms,
            ok=False,
            cached=False,
            reason="timeout",
        )
        from .player_shell import PlayerShellError

        raise PlayerShellError(
            f"Godot project import timed out after {timeout_seconds}s: {project_directory}"
        ) from exc

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    output = "\n".join(
        part.strip()
        for part in (completed.stdout or "", completed.stderr or "")
        if part and part.strip()
    )
    script_failure = (
        "SCRIPT ERROR:" in output
        or "Failed to load script" in output
        or "Parse Error:" in output
    )
    if completed.returncode != 0 or script_failure:
        _emit_startup_timing(
            "godot_project_import",
            duration_ms=elapsed_ms + fingerprint_ms,
            ok=False,
            cached=False,
            returncode=int(completed.returncode),
        )
        from .player_shell import PlayerShellError

        detail = output[-2400:] if output else f"exit code {completed.returncode}"
        raise PlayerShellError(
            "Godot project import failed before player launch: " + detail
        )
    if source_commit and project_fingerprint and godot_identity:
        try:
            _write_godot_import_stamp(
                project_directory,
                source_commit=source_commit,
                project_fingerprint=project_fingerprint,
                godot_identity=godot_identity,
            )
        except OSError:
            # Cache publication is performance-only. A later launch simply pays
            # for the canonical import again if the stamp cannot be persisted.
            pass
    _emit_startup_timing(
        "godot_project_import",
        duration_ms=elapsed_ms + fingerprint_ms,
        ok=True,
        cached=False,
    )


def _fast_continue_state_compatible(
    player_shell,
    args,
    state: dict[str, object],
    *,
    paths,
    stack_layers: list[str],
    stack_config: str,
    game_directory: str,
    profile_directory: str,
    godot_executable: str,
    godot_project: str,
) -> bool:
    if args.faction and str(args.faction) != str(state.get("selected_faction", "")):
        return False
    if args.difficulty and str(args.difficulty) != str(state.get("difficulty", "")):
        return False
    if args.fog_of_war and str(args.fog_of_war) != str(state.get("fog_of_war", "")):
        return False
    if game_directory and game_directory != str(state.get("game_directory", "")):
        return False
    if profile_directory and profile_directory != str(state.get("profile_directory", "")):
        return False
    tactical_override = str(args.tactical_map or "").strip()
    if tactical_override and tactical_override != str(state.get("tactical_map", "")):
        return False
    if stack_config != str(state.get("stack_config", "")):
        return False
    if list(state.get("resource_stack", []) or []) != list(stack_layers):
        return False
    if stack_layers:
        codex_layer = player_shell._codex_layer_from_stack(stack_layers)
        if codex_layer != str(state.get("code_x_directory", "")):
            return False
    launch = state.get("player_launch", {})
    if not isinstance(launch, dict):
        return False
    if str(launch.get("campaign_path", "")) != str(paths.campaign):
        return False
    if str(launch.get("snapshot_path", "")) != str(paths.snapshot):
        return False
    if str(launch.get("commands_path", "")) != str(paths.commands):
        return False
    if str(launch.get("godot_executable", "")) != godot_executable:
        return False
    if str(launch.get("godot_project", "")) != godot_project:
        return False
    return True


def _install_unchanged_continue_fast_path(player_shell) -> None:
    """Reuse an unchanged validated campaign/snapshot proven by the live daemon."""

    current = player_shell.run_play
    if getattr(current, "_goc_unchanged_continue_fast_path", False):
        return
    original_run_play = current

    @functools.wraps(original_run_play)
    def fast_run_play(args, *, environ=None, resolved_catalog=None):
        started = time.perf_counter()
        if bool(args.new) or bool(args.no_launch) or resolved_catalog is not None:
            return original_run_play(
                args,
                environ=environ,
                resolved_catalog=resolved_catalog,
            )

        scenario_id = str(args.scenario or player_shell.DEFAULT_SCENARIO_ID)
        campaign_argument = args.campaign
        if not campaign_argument:
            remembered = player_shell.read_last_campaign(environ)
            if remembered is None:
                return original_run_play(
                    args,
                    environ=environ,
                    resolved_catalog=resolved_catalog,
                )
            campaign_argument = str(remembered)
        paths = player_shell.resolve_campaign_paths(
            campaign_argument,
            scenario_id=scenario_id,
            environ=environ,
        )

        try:
            from .persistent_backend import diagnose_startup_reuse

            state, reuse_reason = diagnose_startup_reuse(paths.campaign, paths.snapshot)
        except Exception:  # noqa: BLE001 - full validated path is the fallback
            state = None
            reuse_reason = "probe_exception"
        if not isinstance(state, dict):
            _emit_startup_timing(
                "unchanged_continue_reuse",
                duration_ms=(time.perf_counter() - started) * 1000.0,
                reused=False,
                reason=str(reuse_reason or "daemon_or_fingerprint_miss"),
            )
            return original_run_play(
                args,
                environ=environ,
                resolved_catalog=resolved_catalog,
            )

        game_directory = player_shell._require_directory(args.game, label="--game")
        profile_directory = player_shell._require_directory(args.profile, label="--profile")
        persisted_stack = str(state.get("stack_config", "") or "")
        stack_config_argument = str(args.stack_config or "").strip() or persisted_stack
        stack_layers = player_shell.validate_stack(
            stack_config_argument or None,
            game_directory=game_directory or None,
            profile_directory=profile_directory or None,
            required=False,
        )
        stack_config = (
            str(Path(stack_config_argument).expanduser().resolve())
            if stack_config_argument
            else ""
        )
        godot_executable = str(
            player_shell.find_godot_executable(args.godot, environ=environ)
        )
        godot_project = str(player_shell.godot_project_directory(args.godot_project))

        if not _fast_continue_state_compatible(
            player_shell,
            args,
            state,
            paths=paths,
            stack_layers=list(stack_layers),
            stack_config=stack_config,
            game_directory=game_directory,
            profile_directory=profile_directory,
            godot_executable=godot_executable,
            godot_project=godot_project,
        ):
            _emit_startup_timing(
                "unchanged_continue_reuse",
                duration_ms=(time.perf_counter() - started) * 1000.0,
                reused=False,
                reason="launch_settings_changed",
            )
            return original_run_play(
                args,
                environ=environ,
                resolved_catalog=resolved_catalog,
            )

        from .frontend_commands import clear_commands

        clear_commands(paths.commands)
        player_shell.write_last_campaign(paths.campaign, environ=environ)
        result = player_shell.PlayResult(
            mode="continue",
            campaign_path=str(paths.campaign),
            snapshot_path=str(paths.snapshot),
            commands_path=str(paths.commands),
            scenario_id=str(state.get("scenario_id", scenario_id)),
            map_id=str(state.get("map_id", "")),
            selected_faction=str(state.get("selected_faction", "")),
            difficulty=str(state.get("difficulty", "")),
            fog_of_war=str(state.get("fog_of_war", "off")),
            turn_number=int(state.get("turn_number", 0) or 0),
            godot_executable=godot_executable,
            godot_project=godot_project,
            stack_layers=list(stack_layers),
        )
        player_shell.launch_strategic_application(
            snapshot=paths.snapshot,
            godot_executable=Path(godot_executable),
            project_directory=Path(godot_project),
        )
        result.launched = True
        _emit_startup_timing(
            "unchanged_continue_reuse",
            duration_ms=(time.perf_counter() - started) * 1000.0,
            reused=True,
        )
        return result

    fast_run_play._goc_unchanged_continue_fast_path = True  # type: ignore[attr-defined]
    player_shell.run_play = fast_run_play


def _write_forwarded_result(result: tuple[int, str] | None) -> int | None:
    if result is None:
        return None
    exit_code, output = result
    if output:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
    return int(exit_code)


def _require_frozen_console_backend() -> Path:
    backend = Path(sys.executable).resolve().with_name("GatesOfCodeXLive.exe")
    if not backend.is_file():
        raise RuntimeError(
            "Packaged Gates of CodeX write-back requires the sibling "
            f"GatesOfCodeXLive.exe console backend: {backend}"
        )
    return backend


def install_runtime_contracts() -> None:
    """Install player/package runtime seams that cannot be inferred by Godot.

    This layer is intentionally idempotent. Source `gates-of-codex play` uses the
    first-run Godot import guard and the explicit tactical-template/handoff
    contract. Frozen builds additionally publish a stable Godot `res://` map path
    and route write-back through the sibling console executable so command JSON
    remains observable to the Godot command runner.
    """
    from . import player_shell
    from .p6_handoff_runtime import install_p6_handoff_runtime_contracts

    install_p6_handoff_runtime_contracts()
    _install_player_startup_timing(player_shell)

    current_launch = player_shell.launch_strategic_application
    if not getattr(current_launch, "_goc_preimport_guard", False):
        original_launch = current_launch

        def launch_after_import(
            *,
            snapshot: Path,
            godot_executable: Path,
            project_directory: Path,
        ):
            _prepare_godot_project(godot_executable, project_directory)
            # Performance-only session. Failure falls back to the existing
            # one-shot authoritative backend without blocking player launch.
            backend_started = time.perf_counter()
            backend_ready = False
            try:
                from .persistent_backend import ensure_backend_session

                backend_ready = bool(
                    ensure_backend_session(snapshot.with_name("campaign.json"), snapshot)
                )
            except Exception:  # noqa: BLE001 - correctness fallback remains available
                backend_ready = False
            _emit_startup_timing(
                "persistent_backend_start_health",
                duration_ms=(time.perf_counter() - backend_started) * 1000.0,
                established=backend_ready,
            )
            launch_started = time.perf_counter()
            process = original_launch(
                snapshot=snapshot,
                godot_executable=godot_executable,
                project_directory=project_directory,
            )
            _emit_startup_timing(
                "godot_process_launch",
                duration_ms=(time.perf_counter() - launch_started) * 1000.0,
                pid=int(process.pid),
            )
            return process

        launch_after_import._goc_preimport_guard = True  # type: ignore[attr-defined]
        player_shell.launch_strategic_application = launch_after_import

    _install_unchanged_continue_fast_path(player_shell)

    if not getattr(sys, "frozen", False):
        return

    from . import frontend
    from .earth3_campaign import CAMPAIGN_MANIFEST_IDENTIFIER

    current_control = frontend._control_block
    if not getattr(current_control, "_goc_frozen_backend", False):
        original_control = current_control

        def frozen_control(*args, **kwargs):
            block = original_control(*args, **kwargs)
            backend = _require_frozen_console_backend()
            from .packaging import package_identity

            identity = package_identity()
            block["python_executable"] = str(backend)
            # Existing Godot write-back passes `-m <module>` before the command.
            # GatesOfCodeXLive accepts and strips this compatibility prefix.
            block["python_module"] = "gates_of_codex"
            block["backend_executable"] = str(backend)
            block["backend_kind"] = "frozen_console"
            block["backend_source_commit"] = identity.source_commit
            return block

        frozen_control._goc_frozen_backend = True  # type: ignore[attr-defined]
        frontend._control_block = frozen_control

    current_map = frontend._earth3_strategic_map_block
    if not getattr(current_map, "_goc_stable_res_path", False):
        original_map = current_map

        def frozen_earth3_map(state):
            block = original_map(state)
            # Never persist the transient PyInstaller _MEIPASS path into the
            # campaign snapshot. The separately deployed Godot project owns the
            # presentation copy of this already-authenticated Earth3 manifest.
            block["manifest_path"] = f"res://{CAMPAIGN_MANIFEST_IDENTIFIER}"
            return block

        frozen_earth3_map._goc_stable_res_path = True  # type: ignore[attr-defined]
        frontend._earth3_strategic_map_block = frozen_earth3_map


def main(argv: Sequence[str] | None = None) -> int:
    """Runtime CLI wrapper for the post-P5 responsiveness layer (#207)."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    from .packaging import PackagingError, enforce_packaged_backend_identity

    try:
        invocation = enforce_packaged_backend_identity(arguments)
    except PackagingError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    return dispatch_authenticated_packaged_invocation(invocation, process_argv=argv)


def dispatch_authenticated_packaged_invocation(
    invocation: object,
    *,
    process_argv: Sequence[str] | None = None,
) -> int:
    """Continue after the process identity boundary has already authenticated argv."""
    from .packaging import AuthenticatedPackagedInvocation

    if not isinstance(invocation, AuthenticatedPackagedInvocation):
        raise TypeError(
            "packaged dispatch requires AuthenticatedPackagedInvocation from "
            "enforce_packaged_backend_identity"
        )
    arguments = list(invocation.arguments)

    if arguments[:1] == ["apply-frontend"]:
        from .persistent_backend import try_forward_apply_frontend

        forwarded = _write_forwarded_result(try_forward_apply_frontend(arguments))
        if forwarded is not None:
            return forwarded

    if arguments[:1] == ["session-backend"]:
        _install_fast_paths()
        install_runtime_contracts()
        from .frozen_runtime import configure_frozen_earth3_authority
        from .persistent_backend import run_session_backend

        configure_frozen_earth3_authority()
        return run_session_backend(arguments[1:])

    _install_fast_paths()
    if getattr(sys, "frozen", False) or (
        process_argv is None and arguments[:1] in (["play"], ["apply-frontend"])
    ):
        install_runtime_contracts()
    from .entrypoint import main as application_main

    return application_main(arguments)


def player_main(argv: Sequence[str] | None = None) -> int:
    """Run the packaged player shell while retaining backend CLI compatibility."""
    _startup_epoch_ms()
    _emit_startup_timing("player_main_enter")
    arguments = list(sys.argv[1:] if argv is None else argv)

    # The Godot write-back contract historically launches the recorded Python
    # runtime as `<exe> -m gates_of_codex <command>`. In a frozen package the
    # recorded runtime is an executable, not python.exe. Accept and normalize
    # that prefix so a packaged player can still serve as a fail-safe backend.
    if len(arguments) >= 2 and arguments[:2] == ["-m", "gates_of_codex"]:
        arguments = arguments[2:]

    from .packaging import PackagingError, enforce_packaged_backend_identity

    try:
        invocation = enforce_packaged_backend_identity(arguments)
    except PackagingError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    arguments = list(invocation.arguments)

    if arguments[:1] == ["apply-frontend"]:
        from .persistent_backend import try_forward_apply_frontend

        forwarded = _write_forwarded_result(try_forward_apply_frontend(arguments))
        if forwarded is not None:
            return forwarded

    _install_fast_paths()
    if getattr(sys, "frozen", False) or argv is None:
        install_runtime_contracts()
    from .frozen_runtime import configure_frozen_earth3_authority
    from .player_shell import main as player_shell_main, read_last_campaign

    authority_started = time.perf_counter()
    configure_frozen_earth3_authority()
    _emit_startup_timing(
        "frozen_authority_configuration",
        duration_ms=(time.perf_counter() - authority_started) * 1000.0,
    )

    if not arguments:
        arguments = ["--continue"] if read_last_campaign() is not None else ["--new"]

    # Explicit CLI subcommands belong to the general application entry point.
    # Player flags (`--new`, `--continue`, ...) remain direct player-shell input.
    if arguments and not arguments[0].startswith("-"):
        return dispatch_authenticated_packaged_invocation(
            invocation, process_argv=arguments
        )
    _emit_startup_timing("player_shell_dispatch", mode=str(arguments[0] if arguments else ""))
    return player_shell_main(arguments)
