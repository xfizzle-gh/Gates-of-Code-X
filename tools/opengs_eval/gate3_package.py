#!/usr/bin/env python3
"""Inspect, compare, and publish OpenGS Gate 3 candidate packages."""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from gate3_core import *
from gate3_inputs import *
from gate3_reports import *


def inspect_package(output: Path) -> dict[str, Any]:
    if not output.is_dir() or output.is_symlink():
        raise Gate3Error("Gate 3 package must be a regular directory")
    manifest_path = output / "package_manifest.json"
    manifest = _json(manifest_path)
    if manifest.get("schema") != PACKAGE_SCHEMA or manifest.get("schema_version") != PACKAGE_SCHEMA_VERSION:
        raise Gate3Error("Gate 3 package manifest schema mismatch")
    if manifest.get("candidate_id") != CANDIDATE_ID:
        raise Gate3Error("Gate 3 package candidate ID mismatch")
    if manifest.get("status") != "experimental_debug_only":
        raise Gate3Error("Gate 3 package is not debug-only")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise Gate3Error("Gate 3 package files ledger is invalid")
    actual_entries: set[str] = set()
    for path in output.rglob("*"):
        relative = path.relative_to(output).as_posix()
        if path.is_symlink() or not path.is_file():
            if path.is_dir() and not path.is_symlink():
                continue
            raise Gate3Error(f"Gate 3 package contains nonregular entry: {relative}")
        actual_entries.add(relative)
    expected_entries = set(files) | {"package_manifest.json"}
    if actual_entries != expected_entries:
        missing = sorted(expected_entries - actual_entries)
        extra = sorted(actual_entries - expected_entries)
        raise Gate3Error(f"Gate 3 package file set mismatch: missing={missing} extra={extra}")
    for relative, expected_sha in sorted(files.items()):
        if not _is_hex(expected_sha, 64):
            raise Gate3Error(f"invalid package hash for {relative}")
        actual_sha = sha256_file(output / relative)
        if actual_sha != expected_sha:
            raise Gate3Error(f"Gate 3 package hash mismatch for {relative}: expected {expected_sha}, got {actual_sha}")

    config_path = output / "inputs" / "gate3_config.json"
    config, config_sha, _raw = load_config(config_path)
    if config_sha != manifest.get("gate3_config_sha256"):
        raise Gate3Error("Gate 3 package config digest mismatch")
    input_manifest = _json(output / "inputs" / "gate3_input_manifest.json")
    for name, row in input_manifest["outputs"].items():
        if sha256_file(output / "inputs" / name) != row["sha256"]:
            raise Gate3Error(f"Gate 3 input hash mismatch: {name}")

    import gate1_pipeline
    import gate1_to_gate2_adapter
    gate1_manifest = gate1_pipeline.inspect_output(output / "gate1")
    gate2_manifest = gate1_to_gate2_adapter.inspect_output(
        output / "candidate", output / "gate1", output / "inputs" / "terrain.png", output / "inputs" / "gate2_config.json"
    )
    dataset = _json(output / "candidate" / "polygon_dataset.json")
    summary = _validate_candidate_dataset(dataset, config["candidate_id"])
    count_report = _json(output / "reports" / "count_report.json")
    if count_report["actual"] != gate1_manifest["counts"]["actual"]:
        raise Gate3Error("Gate 3 count report disagrees with Gate 1")
    if count_report["gate2"]["province_count"] != summary["province_count"]:
        raise Gate3Error("Gate 3 count report disagrees with Gate 2")
    water_report = _json(output / "reports" / "water_policy_report.json")
    if water_report["selectable_water_count"] != 0:
        raise Gate3Error("Gate 3 water policy report permits selectable water")
    debug_manifest = _json(output / "reports" / "debug_map_manifest.json")
    if debug_manifest["debug_only"] is not True or debug_manifest["default_map"] is not False or debug_manifest["production_registration"] is not False:
        raise Gate3Error("Gate 3 debug isolation report is invalid")
    if manifest.get("production_authority_changed") is not False:
        raise Gate3Error("Gate 3 package claims a production authority change")
    return {
        "ok": True, "candidate_id": config["candidate_id"], "province_count": summary["province_count"], "land_count": summary["land_count"], "water_count": summary["water_count"],
        "file_count": len(actual_entries), "gate1_manifest_sha256": sha256_file(output / "gate1" / "run_manifest.json"),
        "gate2_manifest_sha256": sha256_file(output / "candidate" / "adapter_manifest.json"), "package_manifest_sha256": sha256_file(manifest_path), "gate2_schema": gate2_manifest["schema"],
    }


def compare_packages(left: Path, right: Path) -> dict[str, Any]:
    left_result = inspect_package(left)
    right_result = inspect_package(right)
    left_files = {path.relative_to(left).as_posix(): _read_regular_file(path, "left package file") for path in left.rglob("*") if path.is_file()}
    right_files = {path.relative_to(right).as_posix(): _read_regular_file(path, "right package file") for path in right.rglob("*") if path.is_file()}
    differences = sorted(set(left_files) ^ set(right_files) | {name for name in set(left_files) & set(right_files) if left_files[name] != right_files[name]})
    if differences:
        raise Gate3Error(f"Gate 3 packages differ: {', '.join(differences)}")
    return {"identical": True, "file_count": len(left_files), "package_manifest_sha256": left_result["package_manifest_sha256"], "province_count": left_result["province_count"], "right_province_count": right_result["province_count"]}


def _assert_inputs_unchanged(inputs: Path) -> None:
    manifest = _json(inputs / "gate3_input_manifest.json")
    for name, row in manifest["outputs"].items():
        if sha256_file(inputs / name) != row["sha256"]:
            raise Gate3Error(f"Gate 3 input changed before publication: {name}")


def run_pipeline(config_path: Path, natural_earth_root: Path, output: Path) -> dict[str, Any]:
    config, _config_sha, _raw = load_config(config_path)
    if output.exists():
        raise Gate3Error(f"Gate 3 output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{output.name}.gate3-build-", dir=output.parent))
    published = False
    started = time.perf_counter()
    try:
        inputs = work / "inputs"
        build_inputs(config_path, natural_earth_root, inputs)
        recipe, terrain, gate2_config = inputs / "gate1_recipe.json", inputs / "terrain.png", inputs / "gate2_config.json"
        gate1_a, gate1_b = work / "gate1-a", work / "gate1-b"
        gate2_a, gate2_b = work / "gate2-a", work / "gate2-b"
        package_a, package_b = work / "package-a", work / "package-b"
        _run([sys.executable, str(MODULE_DIR / "gate1_generator.py"), "validate-recipe", str(recipe)])
        for destination in (gate1_a, gate1_b):
            _run([sys.executable, str(MODULE_DIR / "gate1_generator.py"), "generate", str(recipe), "--output", str(destination)])
            _run([sys.executable, str(MODULE_DIR / "gate1_generator.py"), "inspect-output", str(destination)])
        _run([sys.executable, str(MODULE_DIR / "gate1_generator.py"), "compare-runs", str(gate1_a), str(gate1_b)])
        for gate1_output, gate2_output in ((gate1_a, gate2_a), (gate1_b, gate2_b)):
            _run([sys.executable, str(MODULE_DIR / "gate1_to_gate2_adapter.py"), "convert", str(gate1_output), "--terrain", str(terrain), "--config", str(gate2_config), "--output", str(gate2_output)])
            _run([sys.executable, str(MODULE_DIR / "gate1_to_gate2_adapter.py"), "inspect-output", str(gate2_output), "--gate1-output", str(gate1_output), "--terrain", str(terrain), "--config", str(gate2_config)])
        _run([sys.executable, str(MODULE_DIR / "gate1_to_gate2_adapter.py"), "compare-runs", str(gate2_a), str(gate2_b), "--gate1-output", str(gate1_a), "--terrain", str(terrain), "--config", str(gate2_config)])
        _assert_inputs_unchanged(inputs)
        input_manifest = _json(inputs / "gate3_input_manifest.json")
        verify_source_paths(config, natural_earth_root, input_manifest["source"]["files"])
        build_package(config_path, inputs, gate1_a, gate2_a, package_a)
        build_package(config_path, inputs, gate1_b, gate2_b, package_b)
        compare_packages(package_a, package_b)
        summary = inspect_package(package_a)
        package_a.replace(output)
        published = True
        return {**summary, "elapsed_seconds_observation": round(time.perf_counter() - started, 6), "source_commit": config["source"]["commit"], "output": str(output)}
    finally:
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)


__all__ = [name for name in globals() if not name.startswith('__')]
