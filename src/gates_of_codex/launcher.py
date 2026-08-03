from __future__ import annotations

import subprocess
from pathlib import Path


EXECUTABLE_CANDIDATES = (
    "call_to_arms.exe",
    "call_to_arms_x64.exe",
    "gates_of_hell.exe",
)


def find_game_executable(game_directory: str | Path) -> Path:
    root = Path(game_directory)
    for relative in (Path("binaries/x64"), Path("binaries"), Path("")):
        directory = root / relative
        for name in EXECUTABLE_CANDIDATES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(f"Could not locate Gates of Hell executable under {root}")


def launch_game(game_directory: str | Path, extra_args: list[str] | None = None) -> subprocess.Popen:
    executable = find_game_executable(game_directory)
    return subprocess.Popen([str(executable), *(extra_args or [])], cwd=executable.parent)
