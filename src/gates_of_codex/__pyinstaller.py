from __future__ import annotations

from pathlib import Path


def get_hook_dirs() -> list[str]:
    """Expose the Gates-owned PyInstaller hook directory to every supported build."""
    return [str(Path(__file__).resolve().parent / "pyinstaller_hooks")]
