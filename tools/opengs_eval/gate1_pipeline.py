"""Gate 1 deterministic generation pipeline and output audits."""
from __future__ import annotations

import hashlib
import json
import math
import platform
import re
import shutil
from io import BytesIO
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import PIL
import scipy
from PIL import Image
from scipy.ndimage import label as ndlabel

from gate1_common import (
    AUTHORITATIVE_OUTPUTS, BOUNDARY_COLOR, DATA_OUTPUTS, GATE1_SOURCE_FILES,
    GENERATOR_VERSION, LAND_TERRAINS, LAKE_TERRAINS, NAVAL_TERRAINS,
    OCEAN_COLOR, LAKE_COLOR, PINNED_ENVIRONMENT, RUN_SCHEMA, RUN_SCHEMA_VERSION,
    UPSTREAM_COMMIT, UPSTREAM_REPOSITORY, Gate1Error, NumberSeries, SeedLedger,
    assert_inputs_unchanged, canonical_json_bytes, extract_masks, load_images,
    load_recipe, sha256_bytes, sha256_file, validate_manifest_shape,
    write_canonical_json, write_deterministic_rgb_png,
)
from gate1_regions import (
    DEFAULT_TERRAIN, combine_maps, create_region_map, largest_remainder,
    round_half_up, stable_color, terrain_name,
)

MODULE_DIR = Path(__file__).resolve().parent


def runtime_environment() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pillow": PIL.__version__,
        "scipy": scipy.__version__,
    }


def require_pinned_environment() -> None:
    current = runtime_environment()
    if current != PINNED_ENVIRONMENT:
        raise Gate1Error(
            "Gate 1 requires the pinned environment profile: "
            f"expected {PINNED_ENVIRONMENT}, got {current}"
        )



def _canonical_source_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return sha256_bytes(text.encode("utf-8"))


def generator_identity() -> dict[str, Any]:
    source_files = {name: _canonical_source_sha256(MODULE_DIR / name) for name in GATE1_SOURCE_FILES}
    return {
        "source_files": source_files,
        "source_tree_sha256": sha256_bytes(canonical_json_bytes(source_files)),
    }


def canonical_recipe_digest(recipe: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(recipe))


def preflight_counts(masks: dict[str, np.ndarray | int], counts: dict[str, int]) -> None:
    land_pixels = int(np.count_nonzero(masks["land_fill"]))
    ocean_pixels = int(np.count_nonzero(masks["sea_fill"]))
    checks = (
        ("land_territories", counts["land_territories"], land_pixels),
        ("ocean_territories", counts["ocean_territories"], ocean_pixels),
        ("land_provinces", counts["land_provinces"], land_pixels),
        ("ocean_provinces", counts["ocean_provinces"], ocean_pixels),
    )
    for name, requested, eligible in checks:
        if name == "ocean_territories" and eligible > 0 and requested == 0:
            raise Gate1Error("ocean_territories must be positive when the map contains eligible ocean pixels")
        if requested > eligible:
            raise Gate1Error(f"counts.{name} requests {requested} but only {eligible} eligible pixels exist")
        if requested > 0 and eligible == 0:
            raise Gate1Error(f"counts.{name} requests {requested} but the eligible mask is empty")
    if counts["land_provinces"] < counts["land_territories"]:
        raise Gate1Error("land_provinces must be at least land_territories")
    if counts["ocean_provinces"] < counts["ocean_territories"]:
        raise Gate1Error("ocean_provinces must be at least ocean_territories")


def _build_artifacts(recipe_path: Path, staging_dir: Path) -> dict[str, Any]:
    require_pinned_environment()
    recipe, inputs = load_recipe(recipe_path)
    land_image, boundary_image, density, terrain = load_images(inputs)
    masks = extract_masks(land_image, boundary_image)
    options = recipe["options"]
    counts = recipe["counts"]
    preflight_counts(masks, counts)
    ledger = SeedLedger(recipe["root_seed"], recipe["recipe_id"])
    used_colors: set[tuple[int, int, int]] = set()

    territory_series = NumberSeries("TRT")
    land_territory_map, land_territories, next_index = create_region_map(
        masks["land_fill"], masks["land_border"], counts["land_territories"], 0,
        "land", territory_series, "territory_id", "territory_type", ledger, "territory.land",
        density=density, density_strength=float(options["density_strength"]),
        lloyd_iterations=options["lloyd_iterations"], jagged=options["jagged_land"],
        amplitude=float(options["jagged_amplitude"]), used_colors=used_colors,
    )
    ocean_density = None if options["exclude_ocean_density"] else density
    ocean_strength = 1.0 if options["exclude_ocean_density"] else float(options["density_strength"])
    ocean_territory_map, ocean_territories, _ = create_region_map(
        masks["sea_fill"], masks["sea_border"], counts["ocean_territories"], next_index,
        "ocean", territory_series, "territory_id", "territory_type", ledger, "territory.ocean",
        density=ocean_density, density_strength=ocean_strength,
        lloyd_iterations=options["lloyd_iterations"], jagged=options["jagged_ocean"],
        amplitude=float(options["jagged_amplitude"]), used_colors=used_colors,
    )
    if len(land_territories) != counts["land_territories"] or len(ocean_territories) != counts["ocean_territories"]:
        raise Gate1Error("generated territory counts do not match the recipe")
    territories = sorted(land_territories + ocean_territories, key=lambda item: int(item["_pmap_index"]))
    territory_rgb, territory_pmap = combine_maps(
        land_territory_map, ocean_territory_map, territories,
        masks["land_mask"], masks["sea_mask"],
    )

    unique, pixel_counts_arr = np.unique(territory_pmap[territory_pmap >= 0], return_counts=True)
    pixel_counts = {int(k): int(v) for k, v in zip(unique, pixel_counts_arr)}
    if set(pixel_counts) != {int(item["_pmap_index"]) for item in territories}:
        raise Gate1Error("one or more territories have no pixels")
    density_weights: dict[int, float] = {}
    ocean_indices = {int(t["_pmap_index"]) for t in ocean_territories}
    for territory_index in sorted(pixel_counts):
        if options["exclude_ocean_density"] and territory_index in ocean_indices:
            density_weights[territory_index] = 1.0
        else:
            values = density[territory_pmap == territory_index].astype(np.float64)
            density_weights[territory_index] = float((256.0 - values.mean()) ** float(options["density_strength"]))
    land_weights = [pixel_counts[int(t["_pmap_index"])] * density_weights[int(t["_pmap_index"])] for t in land_territories]
    ocean_weights = [pixel_counts[int(t["_pmap_index"])] * density_weights[int(t["_pmap_index"])] for t in ocean_territories]
    land_alloc = largest_remainder(land_territories, counts["land_provinces"], land_weights)
    ocean_alloc = largest_remainder(ocean_territories, counts["ocean_provinces"], ocean_weights)

    province_series = NumberSeries("PRV")
    province_map = np.full(territory_pmap.shape, -1, dtype=np.int32)
    provinces: list[dict[str, Any]] = []
    province_index = 0
    boundary_mask = masks["boundary_mask"]
    lake_mask = masks["lake_mask"]
    territory_by_index = {int(item["_pmap_index"]): item for item in territories}
    labeled_lakes, lake_count = ndlabel(lake_mask)
    for component in range(1, lake_count + 1):
        component_mask = labeled_lakes == component
        ys, xs = np.where(component_mask)
        center_x, center_y = float(xs.mean()), float(ys.mean())
        territory_index = int(territory_pmap[round_half_up(center_y), round_half_up(center_x)])
        parent = territory_by_index.get(territory_index)
        r, g, b = stable_color(province_index, "lake", used_colors)
        item = {
            "province_id": province_series.get_id(), "province_type": "lake",
            "R": r, "G": g, "B": b, "x": center_x, "y": center_y,
            "territory_id": parent["territory_id"] if parent else "",
            "_pmap_index": province_index, "province_terrain": "lakes",
        }
        province_map[component_mask] = province_index
        provinces.append(item)
        if parent is not None:
            parent.setdefault("province_ids", []).append(item["province_id"])
        province_index += 1

    jobs: list[tuple[dict[str, Any], int]] = []
    jobs.extend((territory, land_alloc[i]) for i, territory in enumerate(land_territories))
    jobs.extend((territory, ocean_alloc[i]) for i, territory in enumerate(ocean_territories))
    for territory, province_count in jobs:
        territory_index = int(territory["_pmap_index"])
        province_type = str(territory["territory_type"])
        territory_mask = territory_pmap == territory_index
        fill = territory_mask & ~lake_mask & ~boundary_mask
        border = (territory_mask & boundary_mask) | (territory_mask & lake_mask)
        eligible = int(fill.sum())
        if province_count > eligible:
            raise Gate1Error(
                f"territory {territory['territory_id']} was allocated {province_count} provinces "
                f"but has only {eligible} eligible pixels"
            )
        pdensity = None if options["exclude_ocean_density"] and province_type == "ocean" else density
        pstrength = 1.0 if pdensity is None else float(options["density_strength"])
        pmap, metadata, next_province_index = create_region_map(
            fill, border, province_count, province_index, province_type, province_series,
            "province_id", "province_type", ledger, f"province.{province_type}.{territory_index:06d}",
            density=pdensity, density_strength=pstrength,
            lloyd_iterations=options["lloyd_iterations"],
            jagged=options["jagged_land"] if province_type == "land" else options["jagged_ocean"],
            amplitude=float(options["jagged_amplitude"]), used_colors=used_colors,
        )
        for item in metadata:
            item["territory_id"] = territory["territory_id"]
            if terrain is None:
                item["province_terrain"] = DEFAULT_TERRAIN[province_type]
            else:
                x = max(0, min(round_half_up(float(item["x"])), terrain.shape[1] - 1))
                y = max(0, min(round_half_up(float(item["y"])), terrain.shape[0] - 1))
                item["province_terrain"] = terrain_name(tuple(int(v) for v in terrain[y, x]), province_type)
        valid = (pmap >= 0) & (province_map < 0)
        province_map[valid] = pmap[valid]
        existing = list(territory.get("province_ids", []))
        territory["province_ids"] = existing + [item["province_id"] for item in metadata]
        provinces.extend(metadata)
        province_index = next_province_index

    actual_land = sum(1 for p in provinces if p["province_type"] == "land")
    actual_ocean = sum(1 for p in provinces if p["province_type"] == "ocean")
    if actual_land != counts["land_provinces"] or actual_ocean != counts["ocean_provinces"]:
        raise Gate1Error(
            "generated province counts do not match recipe: "
            f"land {actual_land}/{counts['land_provinces']}, "
            f"ocean {actual_ocean}/{counts['ocean_provinces']}"
        )

    max_index = max((int(item["_pmap_index"]) for item in provinces), default=-1)
    lookup = np.zeros((max_index + 1, 3), dtype=np.uint8)
    for item in provinces:
        lookup[int(item["_pmap_index"])] = (item["R"], item["G"], item["B"])
    province_rgb = np.zeros((*province_map.shape, 3), dtype=np.uint8)
    valid = province_map >= 0
    province_rgb[valid] = lookup[province_map[valid]]

    staging_dir.mkdir(parents=True, exist_ok=False)
    write_deterministic_rgb_png(staging_dir / "territories.png", territory_rgb)
    write_deterministic_rgb_png(staging_dir / "provinces.png", province_rgb)
    public_territories = [{k: v for k, v in item.items() if k != "_pmap_index"} for item in territories]
    public_provinces = [
        {k: v for k, v in item.items() if k != "_pmap_index"}
        for item in sorted(provinces, key=lambda p: int(p["_pmap_index"]))
    ]
    write_canonical_json(staging_dir / "territories.json", public_territories)
    write_canonical_json(staging_dir / "provinces.json", public_provinces)

    output_checksums = {name: sha256_file(staging_dir / name) for name in DATA_OUTPUTS}
    manifest = {
        "schema": RUN_SCHEMA,
        "schema_version": RUN_SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "generator_identity": generator_identity(),
        "upstream_repository": UPSTREAM_REPOSITORY,
        "upstream_commit": UPSTREAM_COMMIT,
        "recipe": {
            "recipe_id": recipe["recipe_id"],
            "root_seed": recipe["root_seed"],
            "canonical_sha256": canonical_recipe_digest(recipe),
        },
        "inputs": {
            key: None if recipe["inputs"][key] is None else {
                "path": recipe["inputs"][key]["path"],
                "sha256": recipe["inputs"][key]["sha256"],
            }
            for key in ("land", "boundary", "density", "terrain")
        },
        "derived_seeds": ledger.manifest(),
        "counts": {
            "requested": dict(counts),
            "actual": {
                "territories": len(public_territories),
                "land_territories": len(land_territories),
                "ocean_territories": len(ocean_territories),
                "provinces": len(public_provinces),
                "land_provinces": actual_land,
                "ocean_provinces": actual_ocean,
                "lake_provinces": sum(1 for p in public_provinces if p["province_type"] == "lake"),
            },
        },
        "dimensions": {"width": int(masks["width"]), "height": int(masks["height"])},
        "outputs": output_checksums,
        "determinism": {
            "implicit_randomness": False,
            "json_canonical": True,
            "png_metadata": False,
            "stable_color_assignment": True,
            "stable_iteration_order": True,
            "canonical_recipe_identity": True,
            "transactional_publish": True,
        },
        "environment": dict(PINNED_ENVIRONMENT),
    }
    manifest["manifest_payload_sha256"] = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    validate_manifest_shape(manifest)
    write_canonical_json(staging_dir / "run_manifest.json", manifest)
    inspect_output(staging_dir)
    assert_inputs_unchanged(inputs)
    return manifest


def generate(recipe_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise Gate1Error(f"output directory already exists: {output_dir}")
    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.gate1-", dir=parent))
    shutil.rmtree(staging)
    try:
        manifest = _build_artifacts(recipe_path.resolve(), staging)
        staging.replace(output_dir)
        return manifest
    except Exception as exc:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if isinstance(exc, Gate1Error):
            raise
        raise Gate1Error(f"generation failed before publish: {exc}") from exc


def _read_canonical_json(path: Path, label: str) -> Any:
    try:
        raw = path.read_bytes()
        parsed = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Gate1Error(f"cannot read {label}: {exc}") from exc
    if raw != canonical_json_bytes(parsed):
        raise Gate1Error(f"{label} is not canonical UTF-8/LF JSON")
    return parsed


def _record_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Gate1Error(f"{path} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise Gate1Error(f"{path} must be a finite number")
    return number


def _record_int(value: Any, path: str, *, minimum: int = 0, maximum: int = 255) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise Gate1Error(f"{path} must be an integer in [{minimum}, {maximum}]")
    return value


def _decode_rgb_png(path: Path, label: str, width: int, height: int) -> np.ndarray:
    try:
        raw = path.read_bytes()
        with Image.open(BytesIO(raw)) as image:
            image.load()
            if image.format != "PNG":
                raise Gate1Error(f"{label} must be PNG, got {image.format}")
            if image.mode != "RGB":
                raise Gate1Error(f"{label} must use RGB mode, got {image.mode}")
            if image.size != (width, height):
                raise Gate1Error(
                    f"{label} dimensions must be {(width, height)}, got {image.size}"
                )
            if image.info:
                raise Gate1Error(f"{label} contains unexpected PNG metadata: {sorted(image.info)}")
            pixels = np.asarray(image, dtype=np.uint8)
    except Gate1Error:
        raise
    except (OSError, ValueError) as exc:
        raise Gate1Error(f"cannot decode {label}: {exc}") from exc
    if pixels.shape != (height, width, 3):
        raise Gate1Error(f"{label} decoded shape is invalid: {pixels.shape}")
    return pixels


def _validate_seed_ledger(manifest: dict[str, Any], territories: list[dict[str, Any]]) -> None:
    seeds = manifest["derived_seeds"]
    expected_prefixes: set[str] = set()
    requested = manifest["counts"]["requested"]
    if requested["land_territories"]:
        expected_prefixes.add("territory.land")
    if requested["ocean_territories"]:
        expected_prefixes.add("territory.ocean")
    for index, territory in enumerate(territories):
        expected_prefixes.add(f"province.{territory['territory_type']}.{index:06d}")

    expected_names: set[str] = set()
    for prefix in sorted(expected_prefixes):
        expected_names.add(f"{prefix}.sample")
        expected_names.add(f"{prefix}.jagged")
        sample_pattern = re.compile(re.escape(prefix) + r"\.lloyd\.sample\.component_(\d{4})$")
        replacement_pattern = re.compile(
            re.escape(prefix) + r"\.lloyd\.empty_replacement\.component_(\d{4})$"
        )
        samples = sorted(
            int(match.group(1))
            for name in seeds
            if (match := sample_pattern.fullmatch(name)) is not None
        )
        replacements = sorted(
            int(match.group(1))
            for name in seeds
            if (match := replacement_pattern.fullmatch(name)) is not None
        )
        if not samples or samples != replacements or samples != list(range(1, max(samples) + 1)):
            raise Gate1Error(f"derived seed component ledger is incomplete for {prefix}")
        expected_names.update(
            f"{prefix}.lloyd.sample.component_{component:04d}" for component in samples
        )
        expected_names.update(
            f"{prefix}.lloyd.empty_replacement.component_{component:04d}"
            for component in replacements
        )
    actual_names = set(seeds)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise Gate1Error(f"derived seed ledger mismatch: missing={missing}, extra={extra}")


def _validate_artifact_semantics(output_dir: Path, manifest: dict[str, Any]) -> None:
    width = manifest["dimensions"]["width"]
    height = manifest["dimensions"]["height"]
    territories = _read_canonical_json(output_dir / "territories.json", "territories.json")
    provinces = _read_canonical_json(output_dir / "provinces.json", "provinces.json")
    if not isinstance(territories, list) or not isinstance(provinces, list):
        raise Gate1Error("territories.json and provinces.json must contain arrays")

    territory_keys = {"territory_id", "territory_type", "R", "G", "B", "x", "y", "province_ids"}
    province_keys = {"province_id", "province_type", "R", "G", "B", "x", "y", "territory_id", "province_terrain"}
    territory_ids: set[str] = set()
    province_ids: set[str] = set()
    territory_colors: set[tuple[int, int, int]] = set()
    province_colors: set[tuple[int, int, int]] = set()
    territory_by_id: dict[str, dict[str, Any]] = {}

    for index, item in enumerate(territories, start=1):
        path = f"territories[{index - 1}]"
        if not isinstance(item, dict) or set(item) != territory_keys:
            raise Gate1Error(f"{path} has an invalid record shape")
        expected_id = f"TRT{index:06d}"
        if item["territory_id"] != expected_id:
            raise Gate1Error(f"{path}.territory_id must be {expected_id}")
        if item["territory_type"] not in {"land", "ocean"}:
            raise Gate1Error(f"{path}.territory_type is invalid")
        color = tuple(_record_int(item[key], f"{path}.{key}") for key in ("R", "G", "B"))
        if color in territory_colors or color in {OCEAN_COLOR, LAKE_COLOR, BOUNDARY_COLOR}:
            raise Gate1Error(f"{path} has a duplicate or reserved color {color}")
        x = _record_number(item["x"], f"{path}.x")
        y = _record_number(item["y"], f"{path}.y")
        if not (0 <= x < width and 0 <= y < height):
            raise Gate1Error(f"{path} center is outside declared dimensions")
        if not isinstance(item["province_ids"], list) or not all(
            isinstance(value, str) for value in item["province_ids"]
        ):
            raise Gate1Error(f"{path}.province_ids must be an array of strings")
        if len(item["province_ids"]) != len(set(item["province_ids"])):
            raise Gate1Error(f"{path}.province_ids contains duplicates")
        territory_ids.add(item["territory_id"])
        territory_colors.add(color)
        territory_by_id[item["territory_id"]] = item

    expected_children: dict[str, list[str]] = {territory_id: [] for territory_id in territory_ids}
    terrain_by_type = {
        "land": set(LAND_TERRAINS),
        "ocean": set(NAVAL_TERRAINS),
        "lake": set(LAKE_TERRAINS),
    }
    for index, item in enumerate(provinces, start=1):
        path = f"provinces[{index - 1}]"
        if not isinstance(item, dict) or set(item) != province_keys:
            raise Gate1Error(f"{path} has an invalid record shape")
        expected_id = f"PRV{index:06d}"
        if item["province_id"] != expected_id:
            raise Gate1Error(f"{path}.province_id must be {expected_id}")
        province_type = item["province_type"]
        if province_type not in {"land", "ocean", "lake"}:
            raise Gate1Error(f"{path}.province_type is invalid")
        color = tuple(_record_int(item[key], f"{path}.{key}") for key in ("R", "G", "B"))
        if color in province_colors or color in territory_colors or color in {OCEAN_COLOR, LAKE_COLOR, BOUNDARY_COLOR}:
            raise Gate1Error(f"{path} has a duplicate or reserved color {color}")
        x = _record_number(item["x"], f"{path}.x")
        y = _record_number(item["y"], f"{path}.y")
        if not (0 <= x < width and 0 <= y < height):
            raise Gate1Error(f"{path} center is outside declared dimensions")
        parent_id = item["territory_id"]
        if parent_id not in territory_by_id:
            raise Gate1Error(f"{path}.territory_id references unknown territory {parent_id!r}")
        parent_type = territory_by_id[parent_id]["territory_type"]
        if province_type == "lake":
            if parent_type != "land":
                raise Gate1Error(f"{path} lake province must belong to a land territory")
        elif province_type != parent_type:
            raise Gate1Error(f"{path} type does not match parent territory")
        if item["province_terrain"] not in terrain_by_type[province_type]:
            raise Gate1Error(f"{path}.province_terrain is invalid for {province_type}")
        province_ids.add(item["province_id"])
        province_colors.add(color)
        expected_children[parent_id].append(item["province_id"])

    for territory_id, expected in expected_children.items():
        actual = territory_by_id[territory_id]["province_ids"]
        if actual != expected:
            raise Gate1Error(
                f"territory {territory_id} province_ids do not match province parent relationships"
            )

    actual = manifest["counts"]["actual"]
    land_territories = sum(item["territory_type"] == "land" for item in territories)
    ocean_territories = sum(item["territory_type"] == "ocean" for item in territories)
    land_provinces = sum(item["province_type"] == "land" for item in provinces)
    ocean_provinces = sum(item["province_type"] == "ocean" for item in provinces)
    lake_provinces = sum(item["province_type"] == "lake" for item in provinces)
    expected_counts = {
        "territories": len(territories),
        "land_territories": land_territories,
        "ocean_territories": ocean_territories,
        "provinces": len(provinces),
        "land_provinces": land_provinces,
        "ocean_provinces": ocean_provinces,
        "lake_provinces": lake_provinces,
    }
    if actual != expected_counts:
        raise Gate1Error(f"artifact records do not match manifest counts: {expected_counts}")

    territory_pixels = _decode_rgb_png(output_dir / "territories.png", "territories.png", width, height)
    province_pixels = _decode_rgb_png(output_dir / "provinces.png", "provinces.png", width, height)
    territory_png_colors = {tuple(int(v) for v in row) for row in np.unique(territory_pixels.reshape(-1, 3), axis=0)}
    province_png_colors = {tuple(int(v) for v in row) for row in np.unique(province_pixels.reshape(-1, 3), axis=0)}
    if territory_png_colors != territory_colors:
        raise Gate1Error(
            f"territories.png colors do not match territories.json: "
            f"missing={sorted(territory_colors - territory_png_colors)}, "
            f"extra={sorted(territory_png_colors - territory_colors)}"
        )
    if province_png_colors != province_colors:
        raise Gate1Error(
            f"provinces.png colors do not match provinces.json: "
            f"missing={sorted(province_colors - province_png_colors)}, "
            f"extra={sorted(province_png_colors - province_colors)}"
        )
    _validate_seed_ledger(manifest, territories)


def inspect_output(output_dir: Path) -> dict[str, Any]:
    require_pinned_environment()
    expected_names = set(AUTHORITATIVE_OUTPUTS)
    try:
        entries = list(output_dir.iterdir())
    except OSError as exc:
        raise Gate1Error(f"cannot inspect output directory: {exc}") from exc
    actual_names = {entry.name for entry in entries}
    if actual_names != expected_names:
        raise Gate1Error(
            f"output entries do not match authoritative set: "
            f"missing={sorted(expected_names - actual_names)}, "
            f"unexpected={sorted(actual_names - expected_names)}"
        )
    invalid_entries = sorted(
        entry.name for entry in entries if not entry.is_file() or entry.is_symlink()
    )
    if invalid_entries:
        raise Gate1Error("authoritative output entries must be regular files: " + ", ".join(invalid_entries))

    manifest_path = output_dir / "run_manifest.json"
    manifest = _read_canonical_json(manifest_path, "run_manifest.json")
    validate_manifest_shape(manifest)
    failures: list[str] = []
    payload = dict(manifest)
    expected_payload_hash = payload.pop("manifest_payload_sha256")
    actual_payload_hash = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    if expected_payload_hash != actual_payload_hash:
        failures.append(f"manifest payload checksum: expected {expected_payload_hash}, got {actual_payload_hash}")
    current_identity = generator_identity()
    if manifest["generator_identity"] != current_identity:
        failures.append("generator source identity does not match the inspecting implementation")
    if manifest["environment"] != runtime_environment():
        failures.append("manifest environment does not match the inspecting runtime")
    for name, expected in sorted(manifest["outputs"].items()):
        path = output_dir / name
        actual = sha256_file(path)
        if actual != expected:
            failures.append(f"checksum {name}: expected {expected}, got {actual}")
    if failures:
        raise Gate1Error("; ".join(failures))
    _validate_artifact_semantics(output_dir, manifest)
    return {"ok": True, "output_dir": str(output_dir), "failures": [], "manifest": manifest}


def compare_runs(left: Path, right: Path) -> dict[str, Any]:
    inspect_output(left)
    inspect_output(right)
    differences = []
    for name in AUTHORITATIVE_OUTPUTS:
        lpath, rpath = left / name, right / name
        lhash, rhash = sha256_file(lpath), sha256_file(rpath)
        if lhash != rhash or lpath.read_bytes() != rpath.read_bytes():
            differences.append({"file": name, "left_sha256": lhash, "right_sha256": rhash})
    return {"identical": not differences, "left": str(left), "right": str(right), "differences": differences}


def benchmark(recipe: Path, output: Path, repetitions: int) -> dict[str, Any]:
    if repetitions < 1:
        raise Gate1Error("repetitions must be positive")
    if output.exists():
        raise Gate1Error(f"benchmark output directory already exists: {output}")
    output.mkdir(parents=True)
    runs = []
    first_dir: Path | None = None
    for index in range(repetitions):
        run_dir = output / f"run-{index + 1:02d}"
        start = time.perf_counter()
        manifest = generate(recipe, run_dir)
        elapsed = time.perf_counter() - start
        if first_dir is None:
            first_dir = run_dir
        comparison = compare_runs(first_dir, run_dir)
        runs.append({
            "run": index + 1,
            "wall_seconds": elapsed,
            "identical_to_first": comparison["identical"],
            "manifest_sha256": sha256_file(run_dir / "run_manifest.json"),
            "counts": manifest["counts"],
        })
    result = {
        "schema": "gates-of-codex.opengs-gate1-benchmark",
        "schema_version": 1,
        "recipe_canonical_sha256": canonical_recipe_digest(load_recipe(recipe)[0]),
        "repetitions": repetitions,
        "all_identical": all(run["identical_to_first"] for run in runs),
        "environment": dict(PINNED_ENVIRONMENT),
        "runs": runs,
    }
    write_canonical_json(output / "benchmark.json", result)
    return result
