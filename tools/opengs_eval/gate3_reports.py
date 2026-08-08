#!/usr/bin/env python3
"""Build authoritative reports for isolated OpenGS Gate 3 candidates."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from gate3_core import *
from gate3_inputs import *


def _json(path: Path) -> Any:
    return _load_json_bytes(_read_regular_file(path, "JSON file"), str(path))


def _copy_exact(source: Path, destination: Path) -> None:
    data = _read_regular_file(source, "package input")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def _validate_candidate_dataset(dataset: Mapping[str, Any], candidate_id: str) -> dict[str, Any]:
    if dataset.get("map_id") != candidate_id:
        raise Gate3Error("candidate dataset map_id mismatch")
    provinces = dataset.get("provinces")
    if not isinstance(provinces, list) or not provinces:
        raise Gate3Error("candidate dataset has no provinces")
    by_id: dict[str, Mapping[str, Any]] = {}
    for province in provinces:
        if not isinstance(province, dict):
            raise Gate3Error("candidate province is not an object")
        pid = province.get("id")
        if not isinstance(pid, str) or not pid.startswith("og2_") or pid in by_id:
            raise Gate3Error(f"invalid candidate province ID: {pid!r}")
        by_id[pid] = province
        is_water = province.get("is_water") is True
        selectable = province.get("selectable") is True
        if is_water and selectable:
            raise Gate3Error(f"water province is selectable: {pid}")
        if not is_water and not selectable:
            raise Gate3Error(f"land province is not selectable: {pid}")
    neighbor_pairs: set[tuple[str, str]] = set()
    for pid, province in by_id.items():
        neighbors = province.get("neighbors")
        if not isinstance(neighbors, list) or neighbors != sorted(set(neighbors)):
            raise Gate3Error(f"neighbors are not sorted and unique for {pid}")
        for neighbor in neighbors:
            if neighbor not in by_id:
                raise Gate3Error(f"unknown neighbor {neighbor} for {pid}")
            if pid not in by_id[neighbor].get("neighbors", []):
                raise Gate3Error(f"nonreciprocal adjacency: {pid} -> {neighbor}")
            neighbor_pairs.add(tuple(sorted((pid, neighbor))))
    edges = dataset.get("edges")
    if not isinstance(edges, list):
        raise Gate3Error("candidate edges must be a list")
    edge_pairs = {tuple(sorted((edge[0], edge[1]))) for edge in edges if isinstance(edge, list) and len(edge) == 2}
    if edge_pairs != neighbor_pairs or len(edge_pairs) != len(edges):
        raise Gate3Error("candidate edge list disagrees with reciprocal neighbors")
    water = [p for p in provinces if p.get("is_water") is True]
    land = [p for p in provinces if p.get("is_water") is not True]
    return {
        "province_count": len(provinces),
        "land_count": len(land),
        "water_count": len(water),
        "edge_count": len(edge_pairs),
        "water_type_counts": dict(sorted(Counter(p.get("province_type") for p in water).items())),
    }


def _report(schema: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": schema, "schema_version": REPORT_SCHEMA_VERSION, **payload}


def build_package(config_path: Path, inputs: Path, gate1: Path, gate2: Path, output: Path) -> dict[str, Any]:
    config, config_sha, _raw = load_config(config_path)
    if output.exists():
        raise Gate3Error(f"Gate 3 package output already exists: {output}")
    output.mkdir(parents=True)
    for name in INPUT_FILES:
        source = config_path if name == "gate3_config.json" else inputs / name
        _copy_exact(source, output / "inputs" / name)
    for name in GATE1_OUTPUTS:
        _copy_exact(gate1 / name, output / "gate1" / name)
    for name in GATE2_OUTPUTS:
        _copy_exact(gate2 / name, output / "candidate" / name)

    input_manifest = _json(output / "inputs" / "gate3_input_manifest.json")
    gate1_manifest = _json(output / "gate1" / "run_manifest.json")
    dataset = _json(output / "candidate" / "polygon_dataset.json")
    dataset_meta = _json(output / "candidate" / "dataset_meta.json")
    map_manifest = _json(output / "candidate" / "map_manifest.json")
    topology = _json(output / "candidate" / "topology_audit.json")
    candidate_summary = _validate_candidate_dataset(dataset, config["candidate_id"])
    requested = gate1_manifest["counts"]["requested"]
    actual = gate1_manifest["counts"]["actual"]
    if actual["provinces"] != candidate_summary["province_count"]:
        raise Gate3Error("Gate 1 and Gate 2 province totals disagree")
    if actual["land_provinces"] != candidate_summary["land_count"]:
        raise Gate3Error("Gate 1 and Gate 2 land counts disagree")
    if actual["ocean_provinces"] + actual["lake_provinces"] != candidate_summary["water_count"]:
        raise Gate3Error("Gate 1 and Gate 2 water counts disagree")
    if dataset_meta["province_count"] != candidate_summary["province_count"]:
        raise Gate3Error("dataset metadata province count mismatch")

    provenance = _report("gates-of-codex.opengs-gate3-provenance", {
        "candidate_id": config["candidate_id"], "status": config["status"], "starting_commit": config["starting_commit"], "gate3_config_sha256": config_sha,
        "source": input_manifest["source"], "projection": input_manifest["projection"], "lon_lat_bounds": input_manifest["lon_lat_bounds"], "projected_bounds": input_manifest["projected_bounds"], "dimensions": input_manifest["dimensions"],
        "gate1_manifest_sha256": sha256_file(output / "gate1" / "run_manifest.json"), "gate2_adapter_manifest_sha256": sha256_file(output / "candidate" / "adapter_manifest.json"),
        "production_authority_changed": False, "campaign_authority_generated": False,
    })
    count_report = _report("gates-of-codex.opengs-gate3-count-report", {
        "candidate_id": config["candidate_id"], "comparison_target_total": config["counts"]["comparison_target_total"], "requested": requested, "actual": actual, "gate2": candidate_summary,
        "delta_from_comparison_target": actual["provinces"] - config["counts"]["comparison_target_total"], "lake_overage_policy": "reported_not_silently_filtered",
    })
    topology_report = _report("gates-of-codex.opengs-gate3-topology-report", {
        "candidate_id": config["candidate_id"], "ok": topology.get("ok") is True, "province_count": topology.get("province_count"), "component_count": topology.get("component_count"), "hole_count": topology.get("hole_count"),
        "adjacency_edge_count": topology.get("adjacency_edge_count"), "border_class_counts": topology.get("border_class_counts"), "max_triangle_area_relative_error": topology.get("max_triangle_area_relative_error"),
        "minimum_shared_edge_pixels": topology.get("minimum_shared_edge_pixels"), "topology_audit_sha256": sha256_file(output / "candidate" / "topology_audit.json"),
    })
    adjacency_report = _report("gates-of-codex.opengs-gate3-adjacency-report", {
        "candidate_id": config["candidate_id"], "edge_count": candidate_summary["edge_count"], "reciprocal": True, "corner_or_diagonal_only_edges": 0,
        "minimum_shared_edge_pixels": config["gate2"]["minimum_shared_edge_pixels"], "edge_pairs_sha256": sha256_bytes(canonical_json_bytes(dataset["edges"])),
    })
    dominant: Counter[str] = Counter()
    coverage_pixels: Counter[str] = Counter()
    for province in dataset["provinces"]:
        dominant[str(province["terrain_id"])] += 1
        for terrain_id, count in province["terrain_coverage_pixels"].items():
            coverage_pixels[str(terrain_id)] += int(count)
    terrain_report = _report("gates-of-codex.opengs-gate3-terrain-report", {
        "candidate_id": config["candidate_id"], "policy": config["terrain"], "dominant_terrain_province_counts": dict(sorted(dominant.items())), "terrain_pixel_counts": dict(sorted(coverage_pixels.items())),
        "terrain_raster_sha256": sha256_file(output / "inputs" / "terrain.png"), "limitation": "three-class physical baseline only; not production terrain authority",
    })
    water_provinces = [p for p in dataset["provinces"] if p["is_water"]]
    water_report = _report("gates-of-codex.opengs-gate3-water-policy-report", {
        "candidate_id": config["candidate_id"], "policy": config["water_policy"], "water_count": len(water_provinces), "water_type_counts": candidate_summary["water_type_counts"],
        "selectable_water_count": sum(bool(p["selectable"]) for p in water_provinces), "operational_sea_nodes_generated": False, "operational_sea_edges_generated": False,
    })
    geography_report = _report("gates-of-codex.opengs-gate3-geography-report", {
        "candidate_id": config["candidate_id"], "theatre_policy": config["theatre"]["policy"], "lon_lat_bounds": input_manifest["lon_lat_bounds"], "projected_bounds": input_manifest["projected_bounds"],
        "projection": input_manifest["projection"], "dimensions": input_manifest["dimensions"], "feature_counts": input_manifest["feature_counts"], "geography_anchors": input_manifest["geography_anchors"],
        "pixel_counts": input_manifest["pixel_counts"], "manual_geometry_edits": 0, "islands_and_lakes_source": "pinned Natural Earth v5.1.2",
    })
    density_report = _report("gates-of-codex.opengs-gate3-density-report", {
        "candidate_id": config["candidate_id"], "policy": input_manifest["density"]["policy"], "statistics": {key: input_manifest["density"][key] for key in ("minimum", "maximum", "mean")},
        "density_raster_sha256": sha256_file(output / "inputs" / "density.png"), "source_feature_counts": {key: input_manifest["feature_counts"][key] for key in ("populated_places", "boundary_line_parts", "river_line_parts")},
    })
    performance_report = _report("gates-of-codex.opengs-gate3-performance-report", {
        "candidate_id": config["candidate_id"], "dimensions": input_manifest["dimensions"], "province_count": candidate_summary["province_count"], "vertex_count": dataset_meta["vertex_count"],
        "triangle_count": dataset_meta["triangle_count"], "border_segment_count": dataset_meta["border_segment_count"],
        "gate0_reference": {"workflow_run_id": 31224683315, "width": 2048, "height": 1536, "non_jagged_wall_seconds_range": [50.23387, 51.530111], "peak_rss_bytes_max": 417296384},
        "measurement_policy": "exact-head wall time and memory remain CI observations, not deterministic package authority",
    })
    debug_manifest = _report("gates-of-codex.opengs-gate3-debug-map", {
        "candidate_id": config["candidate_id"], "map_id": map_manifest["map_id"], "candidate_manifest_path": "candidate/map_manifest.json", "candidate_manifest_sha256": sha256_file(output / "candidate" / "map_manifest.json"),
        "debug_only": True, "default_map": False, "production_registration": False, "earth3_fallback_unchanged": True, "campaign_authority_generated": False,
    })
    reports = {
        "provenance_manifest.json": provenance, "count_report.json": count_report, "topology_report.json": topology_report, "adjacency_report.json": adjacency_report,
        "terrain_report.json": terrain_report, "water_policy_report.json": water_report, "geography_report.json": geography_report, "density_report.json": density_report,
        "performance_report.json": performance_report, "debug_map_manifest.json": debug_manifest,
    }
    for name, value in reports.items():
        _write_json(output / "reports" / name, value)
    payload_files = [path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()]
    payload_hashes = {relative: sha256_file(output / relative) for relative in sorted(payload_files)}
    _write_json(output / "checksums.json", _report("gates-of-codex.opengs-gate3-checksums", {"candidate_id": config["candidate_id"], "files": payload_hashes}))
    final_files = sorted(payload_files + ["checksums.json"])
    final_hashes = {relative: sha256_file(output / relative) for relative in final_files}
    package_manifest = {
        "schema": PACKAGE_SCHEMA, "schema_version": PACKAGE_SCHEMA_VERSION, "candidate_id": config["candidate_id"], "status": "experimental_debug_only", "starting_commit": config["starting_commit"],
        "gate3_config_sha256": config_sha, "source_commit": config["source"]["commit"], "map_id": map_manifest["map_id"], "province_count": candidate_summary["province_count"],
        "land_count": candidate_summary["land_count"], "water_count": candidate_summary["water_count"], "files": final_hashes, "production_authority_changed": False, "gate4_started": False,
    }
    _write_json(output / "package_manifest.json", package_manifest)
    return package_manifest


__all__ = [name for name in globals() if not name.startswith('__')]
