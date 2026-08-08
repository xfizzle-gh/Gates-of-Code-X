"""Gate 1 deterministic generation pipeline and output audits."""
from __future__ import annotations

import hashlib
import json
import platform
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import PIL
import scipy
from scipy.ndimage import label as ndlabel

from gate1_common import (
    AUTHORITATIVE_OUTPUTS, DATA_OUTPUTS, GATE1_SOURCE_FILES, GENERATOR_VERSION,
    RUN_SCHEMA, RUN_SCHEMA_VERSION, UPSTREAM_COMMIT, UPSTREAM_REPOSITORY,
    Gate1Error, NumberSeries, SeedLedger, canonical_json_bytes, extract_masks,
    load_images, load_recipe, sha256_bytes, sha256_file, validate_manifest_shape,
    write_canonical_json, write_deterministic_rgb_png,
)
from gate1_regions import (
    DEFAULT_TERRAIN, combine_maps, create_region_map, largest_remainder,
    round_half_up, stable_color, terrain_name,
)

MODULE_DIR = Path(__file__).resolve().parent


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
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pillow": PIL.__version__,
            "scipy": scipy.__version__,
        },
    }
    manifest["manifest_payload_sha256"] = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    validate_manifest_shape(manifest)
    write_canonical_json(staging_dir / "run_manifest.json", manifest)
    inspect_output(staging_dir)
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


def inspect_output(output_dir: Path) -> dict[str, Any]:
    manifest_path = output_dir / "run_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Gate1Error(f"cannot read run manifest: {exc}") from exc
    validate_manifest_shape(manifest)
    failures: list[str] = []
    if manifest_path.read_bytes() != canonical_json_bytes(manifest):
        failures.append("run_manifest.json is not canonical UTF-8/LF JSON")
    payload = dict(manifest)
    expected_payload_hash = payload.pop("manifest_payload_sha256")
    actual_payload_hash = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    if expected_payload_hash != actual_payload_hash:
        failures.append(f"manifest payload checksum: expected {expected_payload_hash}, got {actual_payload_hash}")
    current_identity = generator_identity()
    if manifest["generator_identity"] != current_identity:
        failures.append("generator source identity does not match the inspecting implementation")
    for name, expected in sorted(manifest["outputs"].items()):
        path = output_dir / name
        if not path.is_file():
            failures.append(f"missing {name}")
        else:
            actual = sha256_file(path)
            if actual != expected:
                failures.append(f"checksum {name}: expected {expected}, got {actual}")
            if name.endswith(".json"):
                try:
                    parsed = json.loads(path.read_bytes().decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    failures.append(f"invalid JSON {name}: {exc}")
                else:
                    if path.read_bytes() != canonical_json_bytes(parsed):
                        failures.append(f"{name} is not canonical UTF-8/LF JSON")
    unexpected = sorted(path.name for path in output_dir.iterdir() if path.is_file() and path.name not in AUTHORITATIVE_OUTPUTS)
    if unexpected:
        failures.append("unexpected output files: " + ", ".join(unexpected))
    if failures:
        raise Gate1Error("; ".join(failures))
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
        "environment": {
            "python": platform.python_version(), "numpy": np.__version__,
            "pillow": PIL.__version__, "scipy": scipy.__version__,
        },
        "runs": runs,
    }
    write_canonical_json(output / "benchmark.json", result)
    return result
