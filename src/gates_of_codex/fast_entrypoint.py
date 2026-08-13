from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path


STARTUP_TELEMETRY_ENV = "GATES_OF_CODEX_STARTUP_TELEMETRY"
STARTUP_EPOCH_ENV = "GATES_OF_CODEX_STARTUP_EPOCH_MS"
STARTUP_LOG_PREFIX = "GOC_STARTUP"


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


def _prepare_godot_project(
    godot_executable: Path,
    project_directory: Path,
    *,
    timeout_seconds: int = 180,
) -> None:
    """Synchronously import a clean Godot project before the interactive launch.

    Owner-native P6 acceptance proved that launching a freshly deployed project
    directly can race Godot's first filesystem/class scan and leave the main scene
    black with unresolved GDScript inheritance. The same project renders normally
    once the canonical headless import finishes. Treat that import as a required
    player-launch phase rather than asking the player to repair the cache manually.
    """
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
            duration_ms=(time.perf_counter() - started) * 1000.0,
            ok=False,
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
            duration_ms=elapsed_ms,
            ok=False,
            returncode=int(completed.returncode),
        )
        from .player_shell import PlayerShellError

        detail = output[-2400:] if output else f"exit code {completed.returncode}"
        raise PlayerShellError(
            "Godot project import failed before player launch: " + detail
        )
    _emit_startup_timing(
        "godot_project_import",
        duration_ms=elapsed_ms,
        ok=True,
    )


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

    if not getattr(sys, "frozen", False):
        return

    from . import frontend
    from .earth3_campaign import CAMPAIGN_MANIFEST_IDENTIFIER

    current_control = frontend._control_block
    if not getattr(current_control, "_goc_frozen_backend", False):
        original_control = current_control

        def frozen_control(*args, **kwargs):
            block = original_control(*args, **kwargs)
            backend = Path(sys.executable).resolve().with_name("GatesOfCodeXLive.exe")
            block["python_executable"] = str(backend)
            # Existing Godot write-back passes `-m <module>` before the command.
            # GatesOfCodeXLive accepts and strips this compatibility prefix.
            block["python_module"] = "gates_of_codex"
            block["backend_executable"] = str(backend)
            block["backend_kind"] = "frozen_console"
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
        argv is None and arguments[:1] in (["play"], ["apply-frontend"])
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
        return main(arguments)
    _emit_startup_timing("player_shell_dispatch", mode=str(arguments[0] if arguments else ""))
    return player_shell_main(arguments)
