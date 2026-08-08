#!/usr/bin/env python3
"""Shared contracts for the isolated OpenGS Gate 3 prototype."""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

MODULE_DIR = Path(__file__).resolve().parent
ROOT = MODULE_DIR.parents[1]

CONFIG_SCHEMA = "gates-of-codex.opengs-gate3-config"
CONFIG_SCHEMA_VERSION = 1
INPUT_SCHEMA = "gates-of-codex.opengs-gate3-input-manifest"
INPUT_SCHEMA_VERSION = 2
PACKAGE_SCHEMA = "gates-of-codex.opengs-gate3-package"
PACKAGE_SCHEMA_VERSION = 2
REPORT_SCHEMA_VERSION = 2
CANDIDATE_ID = "opengs_gate3_europe_mediterranean_3514_candidate"
STARTING_COMMIT = "62063d70d2bb94f41b4d997578c02556003e9a72"
NATURAL_EARTH_REPOSITORY = "nvkelso/natural-earth-vector"
NATURAL_EARTH_REF = "v5.1.2"
NATURAL_EARTH_COMMIT = "f1890d9f152c896d250a77557a5751a93d494776"
PROJECTION = "+proj=laea +lat_0=45 +lon_0=20 +datum=WGS84 +units=m +no_defs"
LOCKED_CONFIG_CANONICAL_SHA256 = "4646af6a193374127e1c6c1570d74eb3e70b52748b1724f1e17879dff416ca85"
SOURCE_ROLES = (
    "land",
    "lakes",
    "national_boundaries",
    "populated_places",
    "rivers",
)
GATE1_OUTPUTS = (
    "territories.png",
    "provinces.png",
    "territories.json",
    "provinces.json",
    "run_manifest.json",
)
GATE2_OUTPUTS = (
    "polygon_dataset.json",
    "map_manifest.json",
    "dataset_meta.json",
    "topology_audit.json",
    "adapter_manifest.json",
)
INPUT_FILES = (
    "land.png",
    "boundary.png",
    "density.png",
    "terrain.png",
    "theatre_mask.png",
    "gate1_recipe.json",
    "gate2_config.json",
    "gate3_input_manifest.json",
    "gate3_config.json",
)
REPORT_FILES = (
    "provenance_manifest.json",
    "count_report.json",
    "topology_report.json",
    "adjacency_report.json",
    "terrain_report.json",
    "water_policy_report.json",
    "geography_report.json",
    "density_report.json",
    "performance_report.json",
    "debug_map_manifest.json",
)
OCEAN_COLOR = (5, 20, 18)
LAND_COLOR = (220, 220, 220)
LAKE_COLOR = (0, 255, 0)
BOUNDARY_COLOR = (0, 0, 0)
BOUNDARY_BACKGROUND = (255, 255, 255)
OUTSIDE_COLOR = (255, 0, 255)
TERRAIN_COLORS = {
    "plains": (255, 129, 66),
    "deep_ocean": (2, 38, 150),
    "lakes": (58, 91, 255),
}


class Gate3Error(RuntimeError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_hex(value: Any, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and set(value) <= set("0123456789abcdef")


def _require_dict(value: Any, path: str, required: set[str], allowed: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Gate3Error(f"{path} must be an object")
    allowed = required if allowed is None else allowed
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    if missing:
        raise Gate3Error(f"{path} missing fields: {', '.join(missing)}")
    if extra:
        raise Gate3Error(f"{path} has unexpected fields: {', '.join(extra)}")
    return value


def _require_int(value: Any, path: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Gate3Error(f"{path} must be an integer")
    if minimum is not None and value < minimum:
        raise Gate3Error(f"{path} must be >= {minimum}")
    return value


def _require_number(value: Any, path: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Gate3Error(f"{path} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise Gate3Error(f"{path} must be finite")
    if minimum is not None and number < minimum:
        raise Gate3Error(f"{path} must be >= {minimum}")
    return number


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise Gate3Error(f"{path} must be boolean")
    return value


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise Gate3Error(f"{path} must be a non-empty string")
    return value


def _load_json_bytes(data: bytes, path: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Gate3Error(f"cannot parse {path}: {exc}") from exc


def _read_regular_file(path: Path, label: str) -> bytes:
    try:
        path_before = path.lstat()
    except OSError as exc:
        raise Gate3Error(f"cannot inspect {label} {path}: {exc}") from exc
    if stat.S_ISLNK(path_before.st_mode) or not stat.S_ISREG(path_before.st_mode):
        raise Gate3Error(f"{label} must be a regular non-symlink file: {path}")
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise Gate3Error(f"cannot capture {label} {path}: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise Gate3Error(f"{label} must be a regular file: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if identity_before != identity_after:
            raise Gate3Error(f"{label} changed while being captured: {path}")
        try:
            path_after = path.lstat()
        except OSError as exc:
            raise Gate3Error(f"cannot recapture {label} {path}: {exc}") from exc
        if stat.S_ISLNK(path_after.st_mode) or not stat.S_ISREG(path_after.st_mode):
            raise Gate3Error(f"{label} path changed to a nonregular entry: {path}")
        final_identity = (path_after.st_dev, path_after.st_ino, path_after.st_size, path_after.st_mtime_ns)
        if final_identity != identity_before:
            raise Gate3Error(f"{label} path changed while being captured: {path}")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def load_config(path: Path) -> tuple[dict[str, Any], str, bytes]:
    raw = _read_regular_file(path.resolve(), "Gate 3 config")
    config = _load_json_bytes(raw, str(path))
    top_keys = {
        "schema", "schema_version", "candidate_id", "status", "starting_commit",
        "source", "projection", "theatre", "raster", "counts", "generator",
        "density", "terrain", "gate2", "water_policy", "isolation",
    }
    top = _require_dict(config, "config", top_keys)
    if top["schema"] != CONFIG_SCHEMA or top["schema_version"] != CONFIG_SCHEMA_VERSION:
        raise Gate3Error("Gate 3 config schema mismatch")
    if top["candidate_id"] != CANDIDATE_ID:
        raise Gate3Error("Gate 3 candidate ID is not locked")
    if top["status"] != "experimental_debug_only":
        raise Gate3Error("Gate 3 status must remain experimental_debug_only")
    if top["starting_commit"] != STARTING_COMMIT:
        raise Gate3Error("Gate 3 starting commit changed")
    source = _require_dict(top["source"], "config.source", {"repository", "ref", "commit", "license", "terms_url", "files"})
    if source["repository"] != NATURAL_EARTH_REPOSITORY or source["ref"] != NATURAL_EARTH_REF or source["commit"] != NATURAL_EARTH_COMMIT:
        raise Gate3Error("Natural Earth source is not exactly pinned")
    if source["license"] != "public_domain":
        raise Gate3Error("Gate 3 source license must remain public_domain")
    _require_string(source["terms_url"], "config.source.terms_url")
    if not isinstance(source["files"], list) or len(source["files"]) != len(SOURCE_ROLES):
        raise Gate3Error("config.source.files must contain exactly five records")
    roles: set[str] = set()
    for index, row_value in enumerate(source["files"]):
        row = _require_dict(row_value, f"config.source.files[{index}]", {"role", "path", "git_blob_sha1", "sha256"})
        role = _require_string(row["role"], f"config.source.files[{index}].role")
        if role not in SOURCE_ROLES or role in roles:
            raise Gate3Error(f"invalid or duplicate source role: {role}")
        roles.add(role)
        relative = Path(_require_string(row["path"], f"source.{role}.path"))
        if relative.is_absolute() or ".." in relative.parts:
            raise Gate3Error(f"source path must be contained: {relative}")
        if not _is_hex(row["git_blob_sha1"], 40) or not _is_hex(row["sha256"], 64):
            raise Gate3Error(f"source authority hashes are invalid for {role}")
    if roles != set(SOURCE_ROLES):
        raise Gate3Error("Gate 3 source role set changed")
    projection = _require_dict(top["projection"], "config.projection", {"source_crs", "name", "proj"})
    if projection != {"source_crs": "EPSG:4326", "name": "Lambert Azimuthal Equal Area", "proj": PROJECTION}:
        raise Gate3Error("Gate 3 projection changed")
    theatre = _require_dict(top["theatre"], "config.theatre", {"lon_lat_bounds", "policy", "anchors"})
    bounds = theatre["lon_lat_bounds"]
    if not isinstance(bounds, list) or len(bounds) != 4:
        raise Gate3Error("config.theatre.lon_lat_bounds must contain four values")
    lon_min, lat_min, lon_max, lat_max = [_require_number(value, f"config.theatre.lon_lat_bounds[{index}]") for index, value in enumerate(bounds)]
    if not (lon_min < lon_max and lat_min < lat_max):
        raise Gate3Error("Gate 3 theatre bounds are invalid")
    _require_string(theatre["policy"], "config.theatre.policy")
    anchors = theatre["anchors"]
    if not isinstance(anchors, list) or not anchors:
        raise Gate3Error("config.theatre.anchors must be a non-empty list")
    anchor_names: set[str] = set()
    for index, anchor_value in enumerate(anchors):
        anchor = _require_dict(anchor_value, f"config.theatre.anchors[{index}]", {"name", "longitude", "latitude", "expected"})
        name = _require_string(anchor["name"], f"config.theatre.anchors[{index}].name")
        if name in anchor_names:
            raise Gate3Error(f"duplicate geography anchor: {name}")
        anchor_names.add(name)
        longitude = _require_number(anchor["longitude"], f"config.theatre.anchors[{index}].longitude")
        latitude = _require_number(anchor["latitude"], f"config.theatre.anchors[{index}].latitude")
        if not (lon_min <= longitude <= lon_max and lat_min <= latitude <= lat_max):
            raise Gate3Error(f"geography anchor is outside the theatre: {name}")
        if anchor["expected"] not in {"land", "ocean", "lake"}:
            raise Gate3Error(f"invalid expected geography class for {name}")
    raster = _require_dict(top["raster"], "config.raster", {"width", "height"})
    if raster != {"width": 2048, "height": 1536}:
        raise Gate3Error("Gate 3 raster dimensions changed")
    counts = _require_dict(top["counts"], "config.counts", {"land_territories", "ocean_territories", "land_provinces", "ocean_provinces", "comparison_target_total"})
    for key in counts:
        _require_int(counts[key], f"config.counts.{key}", 0)
    if counts["land_provinces"] != 3299 or counts["ocean_provinces"] != 215 or counts["comparison_target_total"] != 3514:
        raise Gate3Error("Gate 3 direct comparison province target changed")
    if counts["land_provinces"] + counts["ocean_provinces"] != 3514:
        raise Gate3Error("Gate 3 comparison target is inconsistent")
    generator = _require_dict(top["generator"], "config.generator", {"root_seed", "lloyd_iterations", "density_strength", "exclude_ocean_density", "jagged_land", "jagged_ocean", "jagged_amplitude"})
    _require_int(generator["root_seed"], "config.generator.root_seed", 0)
    _require_int(generator["lloyd_iterations"], "config.generator.lloyd_iterations", 0)
    _require_number(generator["density_strength"], "config.generator.density_strength", 0)
    _require_bool(generator["exclude_ocean_density"], "config.generator.exclude_ocean_density")
    _require_bool(generator["jagged_land"], "config.generator.jagged_land")
    _require_bool(generator["jagged_ocean"], "config.generator.jagged_ocean")
    _require_number(generator["jagged_amplitude"], "config.generator.jagged_amplitude", 0)
    density = _require_dict(top["density"], "config.density", {"baseline", "city_radius_min", "city_radius_max", "city_depth_min", "city_depth_max", "boundary_sigma", "boundary_depth", "river_sigma", "river_depth", "coast_sigma", "coast_depth", "combination"})
    for key in ("baseline", "city_radius_min", "city_radius_max", "city_depth_min", "city_depth_max"):
        _require_int(density[key], f"config.density.{key}", 0)
    for key in ("boundary_sigma", "boundary_depth", "river_sigma", "river_depth", "coast_sigma", "coast_depth"):
        _require_number(density[key], f"config.density.{key}", 0)
    if density["combination"] != "minimum":
        raise Gate3Error("Gate 3 density combination must remain minimum")
    terrain = _require_dict(top["terrain"], "config.terrain", {"policy", "land", "ocean", "lake", "production_authority"})
    if terrain != {"policy": "natural_earth_three_class_baseline", "land": "plains", "ocean": "deep_ocean", "lake": "lakes", "production_authority": False}:
        raise Gate3Error("Gate 3 terrain policy changed")
    gate2 = _require_dict(top["gate2"], "config.gate2", {"id_prefix", "minimum_shared_edge_pixels", "authored_boundary_pairs", "suppressed_segments"})
    if gate2["id_prefix"] != "og2_":
        raise Gate3Error("Gate 2 accepted namespace changed")
    _require_int(gate2["minimum_shared_edge_pixels"], "config.gate2.minimum_shared_edge_pixels", 1)
    if gate2["authored_boundary_pairs"] != [] or gate2["suppressed_segments"] != []:
        raise Gate3Error("Gate 3 cannot silently add authored Gate 2 overrides")
    water = _require_dict(top["water_policy"], "config.water_policy", {"selectable", "operational_sea_generated", "lake_filtering", "count_policy"})
    if water != {"selectable": False, "operational_sea_generated": False, "lake_filtering": "none", "count_policy": "requested_ocean_plus_all_natural_earth_lake_components"}:
        raise Gate3Error("Gate 3 water policy changed")
    isolation = _require_dict(top["isolation"], "config.isolation", {"debug_only", "default_map", "production_registration", "earth3_authority_changed", "campaign_authority_generated"})
    if isolation != {"debug_only": True, "default_map": False, "production_registration": False, "earth3_authority_changed": False, "campaign_authority_generated": False}:
        raise Gate3Error("Gate 3 isolation contract changed")
    canonical = canonical_json_bytes(top)
    digest = sha256_bytes(canonical)
    if digest != LOCKED_CONFIG_CANONICAL_SHA256:
        raise Gate3Error(
            "Gate 3 config differs from the exact owner-approved canonical configuration: "
            f"expected {LOCKED_CONFIG_CANONICAL_SHA256}, got {digest}"
        )
    return top, digest, raw


def _run(command: Sequence[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(list(command), cwd=cwd, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise Gate3Error(f"command failed ({completed.returncode}): {' '.join(command)}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")
    return completed.stdout.strip()


def _run_bytes(command: Sequence[str], *, cwd: Path | None = None) -> bytes:
    completed = subprocess.run(list(command), cwd=cwd, check=False, capture_output=True)
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")
        raise Gate3Error(f"command failed ({completed.returncode}): {' '.join(command)}\nstderr:\n{stderr}")
    return completed.stdout


def _git_head(root: Path) -> str:
    return _run(["git", "-C", str(root), "rev-parse", "HEAD"])


def capture_sources(config: Mapping[str, Any], natural_earth_root: Path) -> dict[str, dict[str, Any]]:
    root = natural_earth_root.resolve()
    commit = str(config["source"]["commit"])
    if _git_head(root) != commit:
        raise Gate3Error("Natural Earth checkout head does not match the locked commit")
    captured: dict[str, dict[str, Any]] = {}
    for row in config["source"]["files"]:
        role = str(row["role"])
        relative = Path(str(row["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise Gate3Error(f"source path escaped checkout: {relative}")
        object_name = f"{commit}:{relative.as_posix()}"
        actual_blob = _run(["git", "-C", str(root), "rev-parse", object_name])
        if actual_blob != row["git_blob_sha1"]:
            raise Gate3Error(f"Natural Earth {role} Git blob mismatch: expected {row['git_blob_sha1']}, got {actual_blob}")
        data = _run_bytes(["git", "-C", str(root), "cat-file", "blob", object_name])
        actual_sha = sha256_bytes(data)
        if actual_sha != row["sha256"]:
            raise Gate3Error(f"Natural Earth {role} SHA-256 mismatch: expected {row['sha256']}, got {actual_sha}")
        captured[role] = {
            "path": root / relative,
            "data": data,
            "sha256": actual_sha,
            "git_blob_sha1": actual_blob,
            "size_bytes": len(data),
            "relative_path": relative.as_posix(),
            "authority": "git_blob_bytes",
        }
    return captured


def verify_source_paths(config: Mapping[str, Any], natural_earth_root: Path, expected: Mapping[str, Any]) -> None:
    current = capture_sources(config, natural_earth_root)
    for role in SOURCE_ROLES:
        row = expected[role]
        if current[role]["sha256"] != row["sha256"] or current[role]["git_blob_sha1"] != row["git_blob_sha1"]:
            raise Gate3Error(f"Natural Earth {role} changed before publication")


__all__ = [name for name in globals() if not name.startswith("__")]
