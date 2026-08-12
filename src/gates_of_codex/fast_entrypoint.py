from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


def _install_fast_paths() -> None:
    from .frontend_fastpath import install_frontend_fast_path
    from .turn_cycle import install_frontend_turn_cycle_op

    install_frontend_fast_path()
    install_frontend_turn_cycle_op()


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
        from .player_shell import PlayerShellError

        raise PlayerShellError(
            f"Godot project import timed out after {timeout_seconds}s: {project_directory}"
        ) from exc

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
        from .player_shell import PlayerShellError

        detail = output[-2400:] if output else f"exit code {completed.returncode}"
        raise PlayerShellError(
            "Godot project import failed before player launch: " + detail
        )


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
            return original_launch(
                snapshot=snapshot,
                godot_executable=godot_executable,
                project_directory=project_directory,
            )

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
    _install_fast_paths()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if getattr(sys, "frozen", False) or (
        argv is None and arguments[:1] in (["play"], ["apply-frontend"])
    ):
        install_runtime_contracts()
    from .entrypoint import main as application_main

    return application_main(arguments)


def player_main(argv: Sequence[str] | None = None) -> int:
    """Run the packaged player shell while retaining backend CLI compatibility."""
    _install_fast_paths()
    if getattr(sys, "frozen", False) or argv is None:
        install_runtime_contracts()
    from .frozen_runtime import configure_frozen_earth3_authority
    from .player_shell import main as player_shell_main, read_last_campaign

    configure_frozen_earth3_authority()
    arguments = list(sys.argv[1:] if argv is None else argv)

    # The Godot write-back contract historically launches the recorded Python
    # runtime as `<exe> -m gates_of_codex <command>`. In a frozen package the
    # recorded runtime is an executable, not python.exe. Accept and normalize
    # that prefix so a packaged player can still serve as a fail-safe backend.
    if len(arguments) >= 2 and arguments[:2] == ["-m", "gates_of_codex"]:
        arguments = arguments[2:]

    if not arguments:
        arguments = ["--continue"] if read_last_campaign() is not None else ["--new"]

    # Explicit CLI subcommands belong to the general application entry point.
    # Player flags (`--new`, `--continue`, ...) remain direct player-shell input.
    if arguments and not arguments[0].startswith("-"):
        return main(arguments)
    return player_shell_main(arguments)
