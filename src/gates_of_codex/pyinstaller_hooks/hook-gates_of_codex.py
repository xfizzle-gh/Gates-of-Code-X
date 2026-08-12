from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

# Package-owned Earth3 bootstrap JSON is always collected. The eight files below
# live outside the Python package but are authenticated runtime authority and must
# be present in both supported Windows executables. Keeping this in the package's
# PyInstaller hook makes CI, release, and installer builds share one minimum
# packaging contract even when an individual build command does not spell out
# --collect-data/--add-data itself.
datas = collect_data_files("gates_of_codex")

_PRODUCT_ENTRYPOINTS = {"run_gates_of_codex.py", "run_gates_of_codex_live.py"}
_EXTERNAL_AUTHORITY = (
    ("config/earth3/production_authority.json", "config/earth3"),
    ("config/earth3/p3_operational_authority.json", "config/earth3"),
    (
        "godot/assets/maps/earth3_europe_mediterranean/map_manifest.json",
        "godot/assets/maps/earth3_europe_mediterranean",
    ),
    (
        "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json",
        "godot/assets/maps/earth3_europe_mediterranean",
    ),
    (
        "godot/assets/maps/earth3_europe_mediterranean/dataset_meta.json",
        "godot/assets/maps/earth3_europe_mediterranean",
    ),
    (
        "godot/assets/maps/earth3_europe_mediterranean/p3_authority/"
        "p3_operational_graph.json",
        "godot/assets/maps/earth3_europe_mediterranean/p3_authority",
    ),
    ("docs/audits/p3-first-corridor-route-inventory.json", "docs/audits"),
    ("src/gates_of_codex/data/earth3_v1/sites.json", "src/gates_of_codex/data/earth3_v1"),
)


def _is_product_executable_build() -> bool:
    return any(Path(argument).name in _PRODUCT_ENTRYPOINTS for argument in sys.argv[1:])


def _project_root() -> Path:
    candidates = [Path.cwd()]
    for argument in sys.argv[1:]:
        candidate = Path(argument)
        if candidate.suffix.lower() == ".py":
            candidates.append(candidate.absolute().parent)
    for candidate in candidates:
        for root in (candidate, *candidate.parents):
            if (
                (root / "pyproject.toml").is_file()
                and (root / "config/earth3/production_authority.json").is_file()
            ):
                return root.resolve()
    raise RuntimeError("Gates of CodeX PyInstaller build cannot resolve the project root")


if _is_product_executable_build():
    root = _project_root()
    for relative, destination in _EXTERNAL_AUTHORITY:
        source = root / relative
        if not source.is_file():
            raise RuntimeError(f"Required Earth3 runtime authority is missing: {source}")
        datas.append((str(source), destination))
