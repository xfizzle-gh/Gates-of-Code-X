import os
import sys
import time
from pathlib import Path


STARTUP_LOG_ENV = "GATES_OF_CODEX_STARTUP_LOG"


def _default_startup_log() -> Path:
    explicit = str(os.environ.get(STARTUP_LOG_ENV, "")).strip()
    if explicit:
        return Path(explicit).expanduser()

    configured_home = str(os.environ.get("GATES_OF_CODEX_HOME", "")).strip()
    if configured_home:
        home = Path(configured_home).expanduser()
    elif os.name == "nt":
        local = str(os.environ.get("LOCALAPPDATA", "")).strip()
        home = Path(local) / "GatesOfCodeX" if local else Path.home() / "AppData" / "Local" / "GatesOfCodeX"
    else:
        xdg = str(os.environ.get("XDG_DATA_HOME", "")).strip()
        home = Path(xdg) / "gates-of-codex" if xdg else Path.home() / ".local" / "share" / "gates-of-codex"
    return home / "startup_telemetry.jsonl"


def _install_windowed_output() -> None:
    """Give the windowed packaged player a durable stdout/stderr sink.

    PyInstaller's windowed executable has no console streams. Startup telemetry
    must never crash the player merely because stdout/stderr are unavailable.
    """

    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        destination = _default_startup_log()
        destination.parent.mkdir(parents=True, exist_ok=True)
        stream = destination.open("a", encoding="utf-8", buffering=1)
    except OSError:
        return
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


os.environ.setdefault("GATES_OF_CODEX_STARTUP_TELEMETRY", "1")
os.environ.setdefault(
    "GATES_OF_CODEX_STARTUP_EPOCH_MS",
    f"{time.time() * 1000.0:.3f}",
)
_install_windowed_output()

from gates_of_codex.fast_entrypoint import player_main
from gates_of_codex.startup_cold_optimizations import install_packaged_full_startup_shortcuts


install_packaged_full_startup_shortcuts()


if __name__ == "__main__":
    raise SystemExit(player_main())
