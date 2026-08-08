#!/usr/bin/env python3
"""Inspect, compare, and atomically publish OpenGS Gate 3 packages."""
from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from gate3_core import *
from gate3_inputs import *
from gate3_reports import *


@dataclass(frozen=True)
class TreeSnapshot:
    files: Mapping[str, bytes]
    sha256: Mapping[str, str]
    directories: frozenset[str]


def _scan_tree(root: Path, *, capture: bool) -> tuple[dict[str, bytes], set[str], dict[str, tuple[int, int, int, int]]]:
    if not root.is_dir() or root.is_symlink():
        raise Gate3Error(f"snapshot root must be a regular directory: {root}")
    files: dict[str, bytes] = {}
    directories: set[str] = set()
    identities: dict[str, tuple[int, int, int, int]] = {}
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name)
        except OSError as exc:
            raise Gate3Error(f"cannot scan snapshot directory {current}: {exc}") from exc
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise Gate3Error(f"cannot inspect snapshot entry {relative}: {exc}") from exc
            if stat.S_ISLNK(info.st_mode):
                raise Gate3Error(f"snapshot contains symlink: {relative}")
            identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            identities[relative] = identity
            if stat.S_ISDIR(info.st_mode):
                directories.add(relative)
                stack.append(path)
            elif stat.S_ISREG(info.st_mode):
                if capture:
                    files[relative] = _read_regular_file(path, f"snapshot file {relative}")
            else:
                raise Gate3Error(f"snapshot contains nonregular entry: {relative}")
    return files, directories, identities


def capture_tree(root: Path) -> TreeSnapshot:
    files, directories, before = _scan_tree(root, capture=True)
    _ignored, final_directories, after = _scan_tree(root, capture=False)
    if directories != final_directories or before != after:
        raise Gate3Error("snapshot tree changed during capture")
    return TreeSnapshot(
        files=MappingProxyType(dict(files)),
        sha256=MappingProxyType({name: sha256_bytes(data) for name, data in files.items()}),
        directories=frozenset(directories),
    )


def capture_flat(root: Path, expected: Sequence[str], label: str) -> TreeSnapshot:
    snapshot = capture_tree(root)
    expected_set = set(expected)
    if set(snapshot.files) != expected_set or snapshot.directories:
        raise Gate3Error(
            f"{label} set mismatch: missing={sorted(expected_set - set(snapshot.files))} "
            f"extra={sorted(set(snapshot.files) - expected_set)} dirs={sorted(snapshot.directories)}"
        )
    return snapshot


def write_tree(root: Path, snapshot: TreeSnapshot) -> None:
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    for directory in sorted(snapshot.directories, key=lambda value: (value.count("/"), value)):
        (root / directory).mkdir(mode=0o700, parents=False, exist_ok=False)
    for relative in sorted(snapshot.files):
        path = root / relative
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(path, flags, 0o600)
        try:
            data = snapshot.files[relative]
            offset = 0
            while offset < len(data):
                offset += os.write(fd, data[offset:])
            os.fsync(fd)
        finally:
            os.close(fd)


def _config_from_bytes(data: bytes) -> tuple[dict[str, Any], str]:
    with tempfile.TemporaryDirectory(prefix=".gate3-config-") as temp:
        path = Path(temp) / "gate3_config.json"
        path.write_bytes(data)
        config, digest, raw = load_config(path)
        if raw != data:
            raise Gate3Error("Gate 3 config bytes changed during validation")
        return config, digest


def _decode_png(data: bytes, mode: str, label: str) -> Any:
    import numpy as np
    from PIL import Image
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            if image.format != "PNG":
                raise Gate3Error(f"{label} must be PNG")
            return np.asarray(image.convert(mode), dtype=np.uint8).copy()
    except Gate3Error:
        raise
    except Exception as exc:
        raise Gate3Error(f"cannot decode {label}: {exc}") from exc


def _masked_extract_masks(land: Any, boundary: Any) -> dict[str, Any]:
    import numpy as np
    outside = np.all(boundary == np.asarray(OUTSIDE_COLOR, dtype=np.uint8), axis=2)
    sea = np.all(land == np.asarray(OCEAN_COLOR, dtype=np.uint8), axis=2) & ~outside
    lake = np.all(land == np.asarray(LAKE_COLOR, dtype=np.uint8), axis=2) & ~outside
    land_mask = ~sea & ~outside
    boundary_mask = np.all(boundary == np.asarray(BOUNDARY_COLOR, dtype=np.uint8), axis=2) & ~outside
    return {
        "boundary_mask": boundary_mask,
        "land_mask": land_mask,
        "sea_mask": sea,
        "lake_mask": lake,
        "land_fill": land_mask & ~boundary_mask,
        "land_border": boundary_mask | sea | outside,
        "sea_fill": sea & ~boundary_mask,
        "sea_border": boundary_mask | land_mask | outside,
        "height": int(land.shape[0]),
        "width": int(land.shape[1]),
    }


@contextmanager
def gate3_masked_gate1_contract() -> Iterator[None]:
    import gate1_pipeline
    original_extract = gate1_pipeline.extract_masks
    original_inspect = gate1_pipeline.inspect_output
    original_unique = gate1_pipeline.np.unique

    def inspect_allowing_black_background(output_dir: Path) -> dict[str, Any]:
        def unique_without_background(value: Any, *args: Any, **kwargs: Any) -> Any:
            result = original_unique(value, *args, **kwargs)
            axis = kwargs.get("axis")
            if axis is None and len(args) >= 2:
                axis = args[1]
            if axis == 0 and getattr(result, "ndim", 0) == 2 and result.shape[1] == 3:
                import numpy as np
                result = result[~np.all(result == 0, axis=1)]
            return result
        gate1_pipeline.np.unique = unique_without_background
        try:
            return original_inspect(output_dir)
        finally:
            gate1_pipeline.np.unique = original_unique

    gate1_pipeline.extract_masks = _masked_extract_masks
    gate1_pipeline.inspect_output = inspect_allowing_black_background
    try:
        yield
    finally:
        gate1_pipeline.extract_masks = original_extract
        gate1_pipeline.inspect_output = original_inspect
        gate1_pipeline.np.unique = original_unique


def _verify_mask_contract(snapshot: TreeSnapshot) -> dict[str, int]:
    import numpy as np
    required = {
        "inputs/theatre_mask.png",
        "inputs/boundary.png",
        "gate1/territories.png",
        "gate1/provinces.png",
    }
    if not required <= set(snapshot.files):
        raise Gate3Error("Gate 3 package is missing theatre-mask contract files")
    mask = _decode_png(snapshot.files["inputs/theatre_mask.png"], "L", "theatre_mask.png") == 255
    boundary = _decode_png(snapshot.files["inputs/boundary.png"], "RGB", "boundary.png")
    territories = _decode_png(snapshot.files["gate1/territories.png"], "RGB", "territories.png")
    provinces = _decode_png(snapshot.files["gate1/provinces.png"], "RGB", "provinces.png")
    outside = ~mask
    boundary_outside = np.all(boundary == np.asarray(OUTSIDE_COLOR, dtype=np.uint8), axis=2)
    if not np.array_equal(boundary_outside, outside):
        raise Gate3Error("authenticated boundary outside-color pixels do not exactly match theatre_mask.png")
    territory_background = np.all(territories == 0, axis=2)
    province_background = np.all(provinces == 0, axis=2)
    if not np.array_equal(territory_background, outside):
        raise Gate3Error("Gate 1 territory no-data pixels do not exactly match the projected theatre mask")
    if not np.array_equal(province_background, outside):
        raise Gate3Error("Gate 1 province no-data pixels do not exactly match the projected theatre mask")
    if not bool(mask.any()) or not bool(outside.any()):
        raise Gate3Error("projected theatre mask must contain inside and outside pixels")
    return {"inside_pixels": int(mask.sum()), "outside_pixels": int(outside.sum())}


def _parse_authority(snapshot: TreeSnapshot) -> dict[str, Any]:
    config, config_sha = _config_from_bytes(snapshot.files["inputs/gate3_config.json"])
    input_manifest = _json_bytes(snapshot.files["inputs/gate3_input_manifest.json"], "gate3_input_manifest.json")
    recipe = _json_bytes(snapshot.files["inputs/gate1_recipe.json"], "gate1_recipe.json")
    gate1_manifest = _json_bytes(snapshot.files["gate1/run_manifest.json"], "run_manifest.json")
    gate2_manifest = _json_bytes(snapshot.files["candidate/adapter_manifest.json"], "adapter_manifest.json")
    dataset = _json_bytes(snapshot.files["candidate/polygon_dataset.json"], "polygon_dataset.json")
    dataset_meta = _json_bytes(snapshot.files["candidate/dataset_meta.json"], "dataset_meta.json")
    map_manifest = _json_bytes(snapshot.files["candidate/map_manifest.json"], "map_manifest.json")
    topology = _json_bytes(snapshot.files["candidate/topology_audit.json"], "topology_audit.json")

    if input_manifest.get("schema") != INPUT_SCHEMA or input_manifest.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise Gate3Error("Gate 3 input manifest schema mismatch")
    if input_manifest.get("gate3_config_sha256") != config_sha:
        raise Gate3Error("input manifest config digest does not match packaged config")
    for name, row in input_manifest.get("outputs", {}).items():
        relative = f"inputs/{name}"
        if relative not in snapshot.sha256 or row.get("sha256") != snapshot.sha256[relative]:
            raise Gate3Error(f"Gate 3 input manifest output mismatch: {name}")
    if input_manifest.get("theatre_mask", {}).get("sha256") != snapshot.sha256["inputs/theatre_mask.png"]:
        raise Gate3Error("theatre mask digest is not authenticated by the input manifest")

    recipe_sha = sha256_bytes(canonical_json_bytes(recipe))
    if gate1_manifest.get("recipe", {}).get("canonical_sha256") != recipe_sha:
        raise Gate3Error("packaged Gate 1 recipe does not match the Gate 1 manifest canonical digest")
    for key in ("land", "boundary", "density", "terrain"):
        ref = recipe["inputs"][key]
        if gate1_manifest.get("inputs", {}).get(key) != ref:
            raise Gate3Error(f"Gate 1 manifest input authority disagrees with packaged recipe: {key}")
        relative = f"inputs/{ref['path']}"
        if snapshot.sha256.get(relative) != ref["sha256"]:
            raise Gate3Error(f"packaged Gate 1 input bytes disagree with recipe: {key}")
    if gate2_manifest.get("gate1", {}).get("run_manifest_sha256") != snapshot.sha256["gate1/run_manifest.json"]:
        raise Gate3Error("Gate 2 manifest does not authenticate the packaged Gate 1 manifest")
    if gate2_manifest.get("gate1", {}).get("recipe") != gate1_manifest.get("recipe"):
        raise Gate3Error("Gate 2 manifest recipe authority disagrees with Gate 1")
    if gate2_manifest.get("terrain_sha256") != snapshot.sha256["inputs/terrain.png"]:
        raise Gate3Error("Gate 2 manifest terrain authority disagrees with packaged terrain")
    return {
        "config": config,
        "config_sha": config_sha,
        "input_manifest": input_manifest,
        "recipe": recipe,
        "gate1_manifest": gate1_manifest,
        "gate2_manifest": gate2_manifest,
        "dataset": dataset,
        "dataset_meta": dataset_meta,
        "map_manifest": map_manifest,
        "topology": topology,
    }


def _expected_package_directories() -> frozenset[str]:
    return frozenset({"inputs", "gate1", "candidate", "reports"})


def _expected_payload_paths() -> set[str]:
    return (
        {f"inputs/{name}" for name in INPUT_FILES}
        | {f"gate1/{name}" for name in GATE1_OUTPUTS}
        | {f"candidate/{name}" for name in GATE2_OUTPUTS}
        | {f"reports/{name}" for name in REPORT_FILES}
    )


def _verify_report_derivation(snapshot: TreeSnapshot, authority: Mapping[str, Any]) -> None:
    expected_reports = derive_reports(
        authority["config"],
        authority["config_sha"],
        authority["input_manifest"],
        authority["gate1_manifest"],
        authority["dataset"],
        authority["dataset_meta"],
        authority["map_manifest"],
        authority["topology"],
        snapshot.sha256,
    )
    for name, report in expected_reports.items():
        relative = f"reports/{name}"
        if relative not in snapshot.files or snapshot.files[relative] != canonical_json_bytes(report):
            raise Gate3Error(
                f"Gate 3 report is not derivable from authenticated package authority: {name}"
            )


def inspect_snapshot(snapshot: TreeSnapshot) -> dict[str, Any]:
    if snapshot.directories != _expected_package_directories():
        raise Gate3Error(f"Gate 3 package directory set mismatch: {sorted(snapshot.directories)}")
    if "package_manifest.json" not in snapshot.files or "checksums.json" not in snapshot.files:
        raise Gate3Error("Gate 3 package is missing root manifests")
    manifest = _json_bytes(snapshot.files["package_manifest.json"], "package_manifest.json")
    if manifest.get("schema") != PACKAGE_SCHEMA or manifest.get("schema_version") != PACKAGE_SCHEMA_VERSION:
        raise Gate3Error("Gate 3 package manifest schema mismatch")
    if manifest.get("candidate_id") != CANDIDATE_ID or manifest.get("status") != "experimental_debug_only":
        raise Gate3Error("Gate 3 package identity mismatch")
    files_ledger = manifest.get("files")
    if not isinstance(files_ledger, dict):
        raise Gate3Error("Gate 3 package files ledger is invalid")
    expected_paths = _expected_payload_paths() | {"checksums.json", "package_manifest.json"}
    if set(snapshot.files) != expected_paths:
        raise Gate3Error(
            f"Gate 3 package file set mismatch: missing={sorted(expected_paths - set(snapshot.files))} "
            f"extra={sorted(set(snapshot.files) - expected_paths)}"
        )
    if set(files_ledger) != expected_paths - {"package_manifest.json"}:
        raise Gate3Error("Gate 3 package manifest file ledger set mismatch")
    for relative, digest in files_ledger.items():
        if not _is_hex(digest, 64) or snapshot.sha256[relative] != digest:
            raise Gate3Error(f"Gate 3 package hash mismatch: {relative}")

    authority = _parse_authority(snapshot)
    mask_counts = _verify_mask_contract(snapshot)
    config = authority["config"]
    config_sha = authority["config_sha"]
    if manifest.get("gate3_config_sha256") != config_sha:
        raise Gate3Error("Gate 3 package config digest mismatch")

    with tempfile.TemporaryDirectory(prefix=".gate3-sealed-") as temp:
        sealed = Path(temp) / "package"
        write_tree(sealed, snapshot)
        import gate1_pipeline
        import gate1_to_gate2_adapter
        with gate3_masked_gate1_contract():
            gate1_pipeline.inspect_output(sealed / "gate1")
            gate1_to_gate2_adapter.inspect_output(
                sealed / "candidate",
                sealed / "gate1",
                sealed / "inputs" / "terrain.png",
                sealed / "inputs" / "gate2_config.json",
            )
        recaptured = capture_tree(sealed)
        if dict(recaptured.files) != dict(snapshot.files) or recaptured.directories != snapshot.directories:
            raise Gate3Error("sealed Gate 3 snapshot changed during nested inspection")

    _verify_report_derivation(snapshot, authority)

    payload_paths = sorted(_expected_payload_paths())
    expected_checksums = _report("gates-of-codex.opengs-gate3-checksums", {
        "candidate_id": CANDIDATE_ID,
        "files": {name: snapshot.sha256[name] for name in payload_paths},
    })
    if snapshot.files["checksums.json"] != canonical_json_bytes(expected_checksums):
        raise Gate3Error("checksums.json is not derivable from the authenticated package snapshot")

    summary = _validate_candidate_dataset(authority["dataset"], CANDIDATE_ID)
    expected_manifest = {
        "schema": PACKAGE_SCHEMA,
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "candidate_id": CANDIDATE_ID,
        "status": "experimental_debug_only",
        "starting_commit": config["starting_commit"],
        "gate3_config_sha256": config_sha,
        "source_commit": config["source"]["commit"],
        "map_id": authority["map_manifest"]["map_id"],
        "province_count": summary["province_count"],
        "land_count": summary["land_count"],
        "water_count": summary["water_count"],
        "theatre_inside_pixels": mask_counts["inside_pixels"],
        "theatre_outside_pixels": mask_counts["outside_pixels"],
        "files": {name: snapshot.sha256[name] for name in sorted(expected_paths - {"package_manifest.json"})},
        "production_authority_changed": False,
        "gate4_started": False,
    }
    if snapshot.files["package_manifest.json"] != canonical_json_bytes(expected_manifest):
        raise Gate3Error("package_manifest.json is not derivable from authenticated package authority")
    return {
        "ok": True,
        "candidate_id": CANDIDATE_ID,
        "province_count": summary["province_count"],
        "land_count": summary["land_count"],
        "water_count": summary["water_count"],
        "file_count": len(snapshot.files),
        "gate1_manifest_sha256": snapshot.sha256["gate1/run_manifest.json"],
        "gate2_manifest_sha256": snapshot.sha256["candidate/adapter_manifest.json"],
        "package_manifest_sha256": snapshot.sha256["package_manifest.json"],
    }


def inspect_package(output: Path) -> dict[str, Any]:
    return inspect_snapshot(capture_tree(output))


def compare_snapshots(left: TreeSnapshot, right: TreeSnapshot) -> dict[str, Any]:
    left_result = inspect_snapshot(left)
    right_result = inspect_snapshot(right)
    differences = sorted(
        set(left.files) ^ set(right.files)
        | {name for name in set(left.files) & set(right.files) if left.files[name] != right.files[name]}
    )
    if left.directories != right.directories:
        differences.append("<directories>")
    if differences:
        raise Gate3Error(f"Gate 3 packages differ: {', '.join(differences)}")
    return {
        "identical": True,
        "file_count": len(left.files),
        "package_manifest_sha256": left_result["package_manifest_sha256"],
        "province_count": left_result["province_count"],
        "right_province_count": right_result["province_count"],
    }


def compare_packages(left: Path, right: Path) -> dict[str, Any]:
    return compare_snapshots(capture_tree(left), capture_tree(right))


def build_package(inputs: Path, gate1: Path, gate2: Path, output: Path) -> TreeSnapshot:
    if output.exists():
        raise Gate3Error(f"Gate 3 package output already exists: {output}")
    input_snapshot = capture_flat(inputs, INPUT_FILES, "Gate 3 inputs")
    gate1_snapshot = capture_flat(gate1, GATE1_OUTPUTS, "Gate 1 output")
    gate2_snapshot = capture_flat(gate2, GATE2_OUTPUTS, "Gate 2 output")
    files: dict[str, bytes] = {}
    for name, data in input_snapshot.files.items():
        files[f"inputs/{name}"] = data
    for name, data in gate1_snapshot.files.items():
        files[f"gate1/{name}"] = data
    for name, data in gate2_snapshot.files.items():
        files[f"candidate/{name}"] = data
    base_snapshot = TreeSnapshot(
        files=MappingProxyType(files),
        sha256=MappingProxyType({name: sha256_bytes(data) for name, data in files.items()}),
        directories=frozenset({"inputs", "gate1", "candidate", "reports"}),
    )
    authority = _parse_authority(base_snapshot)
    mask_counts = _verify_mask_contract(base_snapshot)
    reports = derive_reports(
        authority["config"],
        authority["config_sha"],
        authority["input_manifest"],
        authority["gate1_manifest"],
        authority["dataset"],
        authority["dataset_meta"],
        authority["map_manifest"],
        authority["topology"],
        base_snapshot.sha256,
    )
    for name, report in reports.items():
        files[f"reports/{name}"] = canonical_json_bytes(report)
    payload_paths = sorted(_expected_payload_paths())
    payload_sha = {name: sha256_bytes(files[name]) for name in payload_paths}
    checksums = _report("gates-of-codex.opengs-gate3-checksums", {"candidate_id": CANDIDATE_ID, "files": payload_sha})
    files["checksums.json"] = canonical_json_bytes(checksums)
    all_without_manifest_sha = {name: sha256_bytes(data) for name, data in files.items()}
    summary = _validate_candidate_dataset(authority["dataset"], CANDIDATE_ID)
    package_manifest = {
        "schema": PACKAGE_SCHEMA,
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "candidate_id": CANDIDATE_ID,
        "status": "experimental_debug_only",
        "starting_commit": authority["config"]["starting_commit"],
        "gate3_config_sha256": authority["config_sha"],
        "source_commit": authority["config"]["source"]["commit"],
        "map_id": authority["map_manifest"]["map_id"],
        "province_count": summary["province_count"],
        "land_count": summary["land_count"],
        "water_count": summary["water_count"],
        "theatre_inside_pixels": mask_counts["inside_pixels"],
        "theatre_outside_pixels": mask_counts["outside_pixels"],
        "files": {name: all_without_manifest_sha[name] for name in sorted(all_without_manifest_sha)},
        "production_authority_changed": False,
        "gate4_started": False,
    }
    files["package_manifest.json"] = canonical_json_bytes(package_manifest)
    snapshot = TreeSnapshot(
        files=MappingProxyType(dict(files)),
        sha256=MappingProxyType({name: sha256_bytes(data) for name, data in files.items()}),
        directories=_expected_package_directories(),
    )
    write_tree(output, snapshot)
    captured = capture_tree(output)
    if dict(captured.files) != dict(snapshot.files) or captured.directories != snapshot.directories:
        raise Gate3Error("generated Gate 3 package differs from its immutable build snapshot")
    inspect_snapshot(snapshot)
    return snapshot


def publish_snapshot(snapshot: TreeSnapshot, output: Path) -> None:
    publication = Path(tempfile.mkdtemp(prefix=f".{output.name}.gate3-publish-", dir=output.parent))
    shutil.rmtree(publication)
    try:
        write_tree(publication, snapshot)
        recaptured = capture_tree(publication)
        if dict(recaptured.files) != dict(snapshot.files) or recaptured.directories != snapshot.directories:
            raise Gate3Error("Gate 3 publication bytes differ from the inspected immutable snapshot")
        publication.replace(output)
    except Exception:
        if publication.exists():
            shutil.rmtree(publication, ignore_errors=True)
        raise


def run_pipeline(config_path: Path, natural_earth_root: Path, output: Path) -> dict[str, Any]:
    config, _config_sha, _raw = load_config(config_path)
    if output.exists():
        raise Gate3Error(f"Gate 3 output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{output.name}.gate3-build-", dir=output.parent))
    started = time.perf_counter()
    try:
        inputs = work / "inputs"
        build_inputs(config_path, natural_earth_root, inputs)
        initial_inputs = capture_flat(inputs, INPUT_FILES, "Gate 3 inputs")
        recipe = inputs / "gate1_recipe.json"
        terrain = inputs / "terrain.png"
        gate2_config = inputs / "gate2_config.json"
        gate1_a, gate1_b = work / "gate1-a", work / "gate1-b"
        gate2_a, gate2_b = work / "gate2-a", work / "gate2-b"
        package_a, package_b = work / "package-a", work / "package-b"
        import gate1_common
        import gate1_pipeline
        import gate1_to_gate2_adapter
        gate1_common.load_recipe(recipe)
        with gate3_masked_gate1_contract():
            for destination in (gate1_a, gate1_b):
                gate1_pipeline.generate(recipe, destination)
                gate1_pipeline.inspect_output(destination)
            comparison = gate1_pipeline.compare_runs(gate1_a, gate1_b)
            if not comparison.get("identical"):
                raise Gate3Error("Gate 1 repeated outputs differ")
            for gate1_output, gate2_output in ((gate1_a, gate2_a), (gate1_b, gate2_b)):
                gate1_to_gate2_adapter.convert(gate1_output, terrain, gate2_config, gate2_output)
                gate1_to_gate2_adapter.inspect_output(gate2_output, gate1_output, terrain, gate2_config)
            gate1_to_gate2_adapter.compare_runs(gate2_a, gate2_b, gate1_a, terrain, gate2_config)
        final_inputs = capture_flat(inputs, INPUT_FILES, "Gate 3 inputs")
        if dict(final_inputs.files) != dict(initial_inputs.files):
            raise Gate3Error("Gate 3 inputs changed before publication")
        input_manifest = _json_bytes(initial_inputs.files["gate3_input_manifest.json"], "gate3_input_manifest.json")
        verify_source_paths(config, natural_earth_root, input_manifest["source"]["files"])
        snapshot_a = build_package(inputs, gate1_a, gate2_a, package_a)
        snapshot_b = build_package(inputs, gate1_b, gate2_b, package_b)
        compare_snapshots(snapshot_a, snapshot_b)
        inspect_snapshot(snapshot_a)
        publish_snapshot(snapshot_a, output)
        published = capture_tree(output)
        if dict(published.files) != dict(snapshot_a.files) or published.directories != snapshot_a.directories:
            raise Gate3Error("published Gate 3 package differs from inspected snapshot")
        summary = inspect_snapshot(snapshot_a)
        return {
            **summary,
            "elapsed_seconds_observation": round(time.perf_counter() - started, 6),
            "source_commit": config["source"]["commit"],
            "output": str(output),
        }
    except Exception as exc:
        if isinstance(exc, Gate3Error):
            raise
        raise Gate3Error(f"Gate 3 pipeline failed before publish: {exc}") from exc
    finally:
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)


__all__ = [name for name in globals() if not name.startswith("__")]
