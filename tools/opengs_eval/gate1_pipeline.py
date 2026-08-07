"""Gate 1 deterministic generation pipeline and output audits."""
from __future__ import annotations

import hashlib
import json
import platform
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np
from scipy.ndimage import label as ndlabel

from gate1_common import (
    AUTHORITATIVE_OUTPUTS, GENERATOR_VERSION, RUN_SCHEMA, RUN_SCHEMA_VERSION,
    UPSTREAM_COMMIT, Gate1Error, NumberSeries, SeedLedger, canonical_json_bytes,
    load_images, load_recipe, sha256_file, write_canonical_json,
    write_deterministic_rgb_png, extract_masks,
)
from gate1_regions import (
    DEFAULT_TERRAIN, combine_maps, create_region_map, largest_remainder,
    round_half_up, stable_color, terrain_name,
)

def generate(recipe_path: Path, output_dir: Path) -> dict[str, Any]:
    recipe, inputs = load_recipe(recipe_path)
    land_image, boundary_image, density, terrain = load_images(inputs)
    masks = extract_masks(land_image, boundary_image)
    options = recipe["options"]
    counts = recipe["counts"]
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
    territories = sorted(land_territories + ocean_territories, key=lambda item: int(item["_pmap_index"]))
    territory_rgb, territory_pmap = combine_maps(land_territory_map, ocean_territory_map, territories, masks["land_mask"], masks["sea_mask"])

    unique, pixel_counts_arr = np.unique(territory_pmap[territory_pmap >= 0], return_counts=True)
    pixel_counts = {int(k): int(v) for k, v in zip(unique, pixel_counts_arr)}
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
    ocean_alloc = largest_remainder(ocean_territories, counts["ocean_provinces"], ocean_weights) if ocean_territories else []

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
        center_x = float(xs.mean())
        center_y = float(ys.mean())
        territory_index = int(territory_pmap[round_half_up(center_y), round_half_up(center_x)])
        parent = territory_by_index.get(territory_index)
        r, g, b = stable_color(province_index, "lake", used_colors)
        item = {
            "province_id": province_series.get_id(), "province_type": "lake",
            "R": r, "G": g, "B": b, "x": center_x, "y": center_y,
            "territory_id": parent["territory_id"] if parent else "", "_pmap_index": province_index,
            "province_terrain": "lakes",
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
        pdensity = None if options["exclude_ocean_density"] and province_type == "ocean" else density
        pstrength = 1.0 if pdensity is None else float(options["density_strength"])
        pmap, metadata, next_province_index = create_region_map(
            fill, border, province_count, province_index, province_type, province_series,
            "province_id", "province_type", ledger, f"province.{province_type}.{territory_index:06d}",
            density=pdensity, density_strength=pstrength, lloyd_iterations=options["lloyd_iterations"],
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

    max_index = max((int(item["_pmap_index"]) for item in provinces), default=-1)
    lookup = np.zeros((max_index + 1, 3), dtype=np.uint8)
    for item in provinces:
        lookup[int(item["_pmap_index"])] = (item["R"], item["G"], item["B"])
    province_rgb = np.zeros((*province_map.shape, 3), dtype=np.uint8)
    valid = province_map >= 0
    province_rgb[valid] = lookup[province_map[valid]]

    output_dir.mkdir(parents=True, exist_ok=True)
    write_deterministic_rgb_png(output_dir / "territories.png", territory_rgb)
    write_deterministic_rgb_png(output_dir / "provinces.png", province_rgb)
    public_territories = [{k: v for k, v in item.items() if k != "_pmap_index"} for item in territories]
    public_provinces = [{k: v for k, v in item.items() if k != "_pmap_index"} for item in sorted(provinces, key=lambda p: int(p["_pmap_index"]))]
    write_canonical_json(output_dir / "territories.json", public_territories)
    write_canonical_json(output_dir / "provinces.json", public_provinces)

    output_checksums = {name: sha256_file(output_dir / name) for name in AUTHORITATIVE_OUTPUTS if name != "run_manifest.json"}
    manifest = {
        "schema": RUN_SCHEMA,
        "schema_version": RUN_SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "upstream_repository": "Thomas-Holtvedt/opengs-maptool",
        "upstream_commit": UPSTREAM_COMMIT,
        "recipe": {
            "path": recipe_path.name,
            "sha256": sha256_file(recipe_path),
            "recipe_id": recipe["recipe_id"],
            "root_seed": recipe["root_seed"],
        },
        "inputs": {key: {"path": spec.path.name, "sha256": spec.sha256} for key, spec in sorted(inputs.items())},
        "derived_seeds": ledger.manifest(),
        "counts": {
            "territories": len(public_territories),
            "provinces": len(public_provinces),
            "land_provinces": sum(1 for p in public_provinces if p["province_type"] == "land"),
            "ocean_provinces": sum(1 for p in public_provinces if p["province_type"] == "ocean"),
            "lake_provinces": sum(1 for p in public_provinces if p["province_type"] == "lake"),
        },
        "dimensions": {"width": int(masks["width"]), "height": int(masks["height"])},
        "outputs": output_checksums,
        "determinism": {
            "implicit_randomness": False,
            "json_canonical": True,
            "png_metadata": False,
            "stable_color_assignment": True,
            "stable_iteration_order": True,
        },
    }
    manifest["manifest_payload_sha256"] = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    write_canonical_json(output_dir / "run_manifest.json", manifest)
    return manifest


def inspect_output(output_dir: Path) -> dict[str, Any]:
    manifest_path = output_dir / "run_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Gate1Error(f"cannot read run manifest: {exc}") from exc
    if manifest.get("schema") != RUN_SCHEMA or manifest.get("schema_version") != RUN_SCHEMA_VERSION:
        raise Gate1Error("unsupported run manifest")
    failures = []
    payload = dict(manifest)
    expected_payload_hash = payload.pop("manifest_payload_sha256", None)
    actual_payload_hash = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    if expected_payload_hash != actual_payload_hash:
        failures.append(f"manifest payload checksum: expected {expected_payload_hash}, got {actual_payload_hash}")
    if set(manifest.get("outputs", {})) != {"territories.png", "provinces.png", "territories.json", "provinces.json"}:
        failures.append("manifest output set is incomplete or unexpected")
    for name, expected in sorted(manifest.get("outputs", {}).items()):
        path = output_dir / name
        if not path.is_file():
            failures.append(f"missing {name}")
        else:
            actual = sha256_file(path)
            if actual != expected:
                failures.append(f"checksum {name}: expected {expected}, got {actual}")
    result = {"ok": not failures, "output_dir": str(output_dir), "failures": failures, "manifest": manifest}
    if failures:
        raise Gate1Error("; ".join(failures))
    return result


def compare_runs(left: Path, right: Path) -> dict[str, Any]:
    inspect_output(left)
    inspect_output(right)
    differences = []
    for name in AUTHORITATIVE_OUTPUTS:
        lpath, rpath = left / name, right / name
        if not lpath.is_file() or not rpath.is_file():
            differences.append({"file": name, "reason": "missing"})
            continue
        lhash, rhash = sha256_file(lpath), sha256_file(rpath)
        if lhash != rhash or lpath.read_bytes() != rpath.read_bytes():
            differences.append({"file": name, "left_sha256": lhash, "right_sha256": rhash})
    return {"identical": not differences, "left": str(left), "right": str(right), "differences": differences}


def benchmark(recipe: Path, output: Path, repetitions: int) -> dict[str, Any]:
    if repetitions < 1:
        raise Gate1Error("repetitions must be positive")
    output.mkdir(parents=True, exist_ok=True)
    runs = []
    first_dir: Path | None = None
    for index in range(repetitions):
        run_dir = output / f"run-{index + 1:02d}"
        if run_dir.exists():
            shutil.rmtree(run_dir)
        start = time.perf_counter()
        manifest = generate(recipe, run_dir)
        elapsed = time.perf_counter() - start
        if first_dir is None:
            first_dir = run_dir
        comparison = compare_runs(first_dir, run_dir)
        runs.append({"run": index + 1, "wall_seconds": elapsed, "identical_to_first": comparison["identical"], "manifest_sha256": sha256_file(run_dir / "run_manifest.json"), "counts": manifest["counts"]})
    result = {
        "schema": "gates-of-codex.opengs-gate1-benchmark",
        "schema_version": 1,
        "recipe_sha256": sha256_file(recipe),
        "repetitions": repetitions,
        "all_identical": all(run["identical_to_first"] for run in runs),
        "environment": {"python": platform.python_version(), "platform": platform.platform(), "numpy": np.__version__},
        "runs": runs,
    }
    write_canonical_json(output / "benchmark.json", result)
    return result


