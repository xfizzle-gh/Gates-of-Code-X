from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from .codex.locator import CodeXLocator


PROFILE_NAMES = {"profiles", "profile"}
SAVE_NAMES = {"save", "saves", "campaign", "campaigns", "dynamic_conquest"}
SKIP_DIRECTORIES = {
    ".git",
    ".venv",
    "node_modules",
    "windows",
    "program files",
    "program files (x86)",
    "$recycle.bin",
}


@dataclass(frozen=True, slots=True)
class ProfileCandidate:
    path: str
    source: str
    save_directories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def default_search_roots() -> list[Path]:
    roots: list[Path] = []
    values = [
        Path.home() / "Documents",
        Path.home() / "OneDrive" / "Documents",
    ]
    for variable in ("OneDrive", "OneDriveConsumer"):
        value = os.environ.get(variable)
        if value:
            values.append(Path(value) / "Documents")
    for variable in ("APPDATA", "LOCALAPPDATA"):
        value = os.environ.get(variable)
        if value:
            values.append(Path(value))
    for value in values:
        _append_directory(roots, value)
    return roots


def discover_profile_locations(
    search_roots: Iterable[str | Path] | None = None,
    *,
    max_depth: int = 6,
) -> list[ProfileCandidate]:
    found: dict[str, ProfileCandidate] = {}

    for path in CodeXLocator().find_profiles():
        candidate = _profile_candidate(path, "known-location")
        found[candidate.path.lower()] = candidate

    roots = list(search_roots or default_search_roots())
    for raw_root in roots:
        root = Path(raw_root).expanduser()
        try:
            root = root.resolve()
        except OSError:
            pass
        if not root.is_dir():
            continue
        for path in _walk_directories(root, max_depth=max_depth):
            name = path.name.lower()
            text = str(path).lower()
            if name not in PROFILE_NAMES:
                continue
            if "gates of hell" not in text and "call to arms" not in text and "400750" not in text:
                continue
            candidate = _profile_candidate(path, f"search:{root}")
            found[candidate.path.lower()] = candidate

    return sorted(found.values(), key=lambda value: value.path.lower())


def _profile_candidate(path: Path, source: str) -> ProfileCandidate:
    resolved = path.resolve()
    saves: list[str] = []
    for candidate in _walk_directories(resolved, max_depth=4, include_root=False):
        if candidate.name.lower() in SAVE_NAMES:
            value = str(candidate.resolve())
            if value not in saves:
                saves.append(value)
    return ProfileCandidate(str(resolved), source, sorted(saves, key=str.lower))


def _walk_directories(root: Path, *, max_depth: int, include_root: bool = True):
    root_depth = len(root.parts)
    if include_root:
        yield root
    for current, directories, _files in os.walk(root):
        current_path = Path(current)
        depth = len(current_path.parts) - root_depth
        directories[:] = [
            name
            for name in directories
            if name.lower() not in SKIP_DIRECTORIES and not name.startswith(".")
        ]
        if depth >= max_depth:
            directories[:] = []
            continue
        for name in directories:
            yield current_path / name


def _append_directory(values: list[Path], candidate: Path) -> None:
    try:
        candidate = candidate.resolve()
    except OSError:
        pass
    if candidate.is_dir() and candidate not in values:
        values.append(candidate)
