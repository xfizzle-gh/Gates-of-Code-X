from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MapCandidate:
    identifier: str
    source: str
    path: str


def discover_maps(*roots: str | Path) -> list[MapCandidate]:
    """Discover playable map roots using GoH overlay priority.

    A playable map is represented by a file literally named ``map`` or
    ``map.mi``. Other ``.mi`` files under a map directory are mission scripts,
    ammunition definitions, triggers, or mode overlays and are not standalone
    map identifiers. Roots are supplied from lowest to highest load priority;
    later layers replace earlier definitions for the same identifier.
    """

    values: dict[str, MapCandidate] = {}
    for raw_root in roots:
        root = Path(raw_root).expanduser()
        try:
            root = root.resolve()
        except OSError:
            pass
        if not root.is_dir():
            continue
        for relative_root in (Path("resource/map"), Path("resource/maps")):
            map_root = root / relative_root
            if not map_root.is_dir():
                continue
            for path in map_root.rglob("*"):
                if not path.is_file() or path.name.lower() not in {"map", "map.mi"}:
                    continue
                identifier_path = path.parent.relative_to(map_root)
                identifier = identifier_path.as_posix().strip("/")
                if not identifier or identifier == ".":
                    continue
                values[identifier.lower()] = MapCandidate(
                    identifier=identifier,
                    source=str(root),
                    path=str(path.resolve()),
                )
    return sorted(values.values(), key=lambda value: value.identifier.lower())
