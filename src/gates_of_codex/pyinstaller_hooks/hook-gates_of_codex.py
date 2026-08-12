from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

# Package-owned Earth3 bootstrap JSON is always collected. The eight files below
# live outside the Python package but are authenticated runtime authority and must
# be present in every frozen Gates of CodeX runtime that imports the package.
#
# Do not gate this contract on sys.argv or the apparent entrypoint. PyInstaller
# executes hooks from its analysis process, where the original product script is
# not guaranteed to remain visible in sys.argv. Windows run #990 proved that such
# detection can silently skip the external authority while still processing this
# hook. Requiring the repository root whenever the hook runs makes every supported
# CI/release/installer build share one fail-closed packaging contract.
datas = collect_data_files("gates_of_codex")

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
        "godot/assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json",
        "godot/assets/maps/earth3_europe_mediterranean/p3_authority",
    ),
    ("docs/audits/p3-first-corridor-route-inventory.json", "docs/audits"),
    ("src/gates_of_codex/data/earth3_v1/sites.json", "src/gates_of_codex/data/earth3_v1"),
)


def _project_root() -> Path:
    # Every supported product packaging surface invokes PyInstaller from the
    # repository (or a child directory). Resolve only that explicit filesystem
    # relationship instead of inferring intent from PyInstaller process argv.
    candidate = Path.cwd().resolve()
    for root in (candidate, *candidate.parents):
        if (
            (root / "pyproject.toml").is_file()
            and (root / "config/earth3/production_authority.json").is_file()
        ):
            return root
    raise RuntimeError(
        "Gates of CodeX PyInstaller build cannot resolve the repository root "
        "required for authenticated Earth3 runtime authority"
    )


root = _project_root()
for relative, destination in _EXTERNAL_AUTHORITY:
    source = root / relative
    if not source.is_file():
        raise RuntimeError(f"Required Earth3 runtime authority is missing: {source}")
    datas.append((str(source), destination))
