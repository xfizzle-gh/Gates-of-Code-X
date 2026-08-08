from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .goh_source import scan_source_entries
from .expanded_nations_models import (
    ACTIVATION_SCHEMA,
    ACTIVATION_VERSION,
    BROAD_ROSTER_INCLUDES,
    ExpandedNationsError,
    GENERATED_MARKER,
    MANIFEST_RELATIVE,
    RESEARCH_RELATIVE,
    ROSTER_RELATIVE,
    UNITS_RELATIVE,
    all_managed_candidates,
    managed_relatives_for_side,
    safe_target,
    sha256_bytes,
)


def install_projection(root: Path, outputs: Mapping[Path, bytes], manifest_bytes: bytes) -> None:
    manifest_path = root / MANIFEST_RELATIVE
    previous_manifest_bytes: bytes | None = None
    previous_files: dict[Path, bytes] = {}
    if manifest_path.is_file():
        previous_manifest_bytes = manifest_path.read_bytes()
        previous_manifest = load_manifest(manifest_path)
        verify_manifest_files(root, previous_manifest)
        for row in previous_manifest["files"]:
            relative = Path(str(row["relative_path"]))
            previous_files[relative] = (root / relative).read_bytes()
    else:
        occupied = [path for path in all_managed_candidates(root) if path.is_file()]
        if occupied:
            raise ExpandedNationsError(
                "Expanded Nations activation refuses to overwrite unmanaged final-layer files: "
                + ", ".join(str(path) for path in occupied)
            )

    staged: dict[Path, Path] = {}
    manifest_stage: Path | None = None
    try:
        for relative, data in outputs.items():
            target = safe_target(root, relative.as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            stage = target.with_name(target.name + ".goc-stage")
            stage.write_bytes(data)
            staged[target] = stage
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_stage = manifest_path.with_name(manifest_path.name + ".goc-stage")
        manifest_stage.write_bytes(manifest_bytes)

        old_paths = set(previous_files)
        new_paths = set(outputs)
        for target, stage in staged.items():
            os.replace(stage, target)
        for stale in sorted(old_paths - new_paths, key=lambda path: path.as_posix()):
            (root / stale).unlink()
        os.replace(manifest_stage, manifest_path)
    except Exception:
        for stage in staged.values():
            if stage.exists():
                stage.unlink()
        if manifest_stage and manifest_stage.exists():
            manifest_stage.unlink()
        for relative in outputs:
            target = root / relative
            if relative not in previous_files and target.is_file():
                target.unlink()
        for relative, data in previous_files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if previous_manifest_bytes is None:
            if manifest_path.exists():
                manifest_path.unlink()
        else:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_bytes(previous_manifest_bytes)
        raise


def deactivate_actor_projection(gates_root: str | Path) -> bool:
    root = Path(gates_root).expanduser().resolve()
    manifest_path = root / MANIFEST_RELATIVE
    if not manifest_path.is_file():
        unexpected = [
            path for path in all_managed_candidates(root)
            if path.is_file() and GENERATED_MARKER in path.read_text(encoding="utf-8-sig", errors="replace")
        ]
        if unexpected:
            raise ExpandedNationsError(
                "Managed-looking Expanded Nations files exist without an activation manifest: "
                + ", ".join(str(path) for path in unexpected)
            )
        return False

    manifest = load_manifest(manifest_path)
    verify_manifest_files(root, manifest)
    relatives = [Path(str(row["relative_path"])) for row in manifest["files"]]
    for relative in relatives:
        safe_target(root, relative.as_posix()).unlink()
    manifest_path.unlink()
    _prune_empty_directories(root, relatives)
    return True


def verify_actor_projection(gates_root: str | Path) -> dict[str, Any]:
    root = Path(gates_root).expanduser().resolve()
    manifest_path = root / MANIFEST_RELATIVE
    if not manifest_path.is_file():
        raise ExpandedNationsError(f"Expanded Nations activation manifest is missing: {manifest_path}")
    manifest = load_manifest(manifest_path)
    verify_manifest_files(root, manifest)

    roster = (root / ROSTER_RELATIVE).read_text(encoding="utf-8-sig")
    units = (root / UNITS_RELATIVE).read_text(encoding="utf-8-sig")
    research = (root / RESEARCH_RELATIVE[str(manifest["tactical_side"])]).read_text(encoding="utf-8-sig")
    if any(GENERATED_MARKER not in value for value in (roster, units, research)):
        raise ExpandedNationsError("One or more active projection files lack the managed marker")
    if '(include "conquest/goc_active_actor_units.set")' not in roster:
        raise ExpandedNationsError("Active roster does not include the actor unit projection")
    for forbidden in BROAD_ROSTER_INCLUDES:
        if f'(include "{forbidden}")' in roster:
            raise ExpandedNationsError(f"Active actor roster leaks broad tactical roster {forbidden}")

    scan = scan_source_entries(units, str(root / UNITS_RELATIVE))
    if scan.diagnostics:
        raise ExpandedNationsError(
            "Generated actor unit file is malformed: " + "; ".join(item.message for item in scan.diagnostics)
        )
    if len(scan.entries) != int(manifest["unit_count"]):
        raise ExpandedNationsError(
            f"Generated unit count {len(scan.entries)} does not match manifest {manifest['unit_count']}"
        )
    expected_side = str(manifest["tactical_side"])
    for entry in scan.entries:
        side_calls = [call.value for call in entry.calls if call.family == "side"]
        if side_calls != [expected_side]:
            raise ExpandedNationsError(
                f"Generated unit {entry.name} has tactical sides {side_calls}, expected {expected_side}"
            )
    return manifest


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("schema") != ACTIVATION_SCHEMA or payload.get("schema_version") != ACTIVATION_VERSION:
        raise ExpandedNationsError(f"Unsupported activation manifest: {path}")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ExpandedNationsError(f"Activation manifest has no managed files: {path}")
    return payload


def verify_manifest_files(root: Path, manifest: Mapping[str, Any]) -> None:
    allowed = {item.as_posix() for item in managed_relatives_for_side(str(manifest["tactical_side"]))}
    rows = manifest.get("files", [])
    actual = {str(row.get("relative_path", "")) for row in rows}
    if actual != allowed:
        raise ExpandedNationsError(
            f"Activation manifest managed-file set is invalid: expected {sorted(allowed)}, got {sorted(actual)}"
        )
    for row in rows:
        target = safe_target(root, str(row["relative_path"]))
        if not target.is_file():
            raise ExpandedNationsError(f"Managed projection file is missing: {target}")
        data = target.read_bytes()
        if sha256_bytes(data) != row.get("sha256") or len(data) != int(row.get("byte_count", -1)):
            raise ExpandedNationsError(f"Managed projection file was modified: {target}")


def _prune_empty_directories(root: Path, relatives: Sequence[Path]) -> None:
    stop = root.resolve()
    for relative in relatives:
        current = (root / relative).parent
        while current != stop and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
