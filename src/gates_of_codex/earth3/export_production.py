"""Export approved Earth3 crop as production polygon dataset for Godot."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .audit_artifact import included_ids_hash, sha256_file, sha256_text_file
from .crop import apply_crop, load_crop_candidates
from .geometry import ear_clip_triangles, shoelace_area
from .parse import load_earth3_dataset

APPROVED_INCLUDED_IDS_SHA256 = "7effdffbccbcce33ecba364dc8d161ded5053266db2df0deee605a98c36620dc"
APPROVED_PROVINCE_COUNT = 3038
DATASET_SCHEMA = "gates-of-codex.earth3-polygon-dataset"
DATASET_SCHEMA_VERSION = 1


def _triangulate(ring: tuple[tuple[float, float], ...]) -> list[tuple[int, int, int]]:
    """Return triangle indices into ring vertex list (fan indices into original ring)."""
    if len(ring) < 3:
        return []
    # ear_clip returns actual points; map back to indices via position match.
    tris = ear_clip_triangles(ring)
    # Build index lookup with rounded keys for float stability.
    index_of: dict[tuple[float, float], int] = {}
    for i, (x, y) in enumerate(ring):
        index_of[(round(x, 6), round(y, 6))] = i
    out: list[tuple[int, int, int]] = []
    for a, b, c in tris:
        ia = index_of.get((round(a[0], 6), round(a[1], 6)))
        ib = index_of.get((round(b[0], 6), round(b[1], 6)))
        ic = index_of.get((round(c[0], 6), round(c[1], 6)))
        if ia is None or ib is None or ic is None:
            # Fallback: skip malformed ear (should be rare).
            continue
        if ia == ib or ib == ic or ia == ic:
            continue
        out.append((ia, ib, ic))
    if not out and len(ring) >= 3:
        # Last-resort fan triangulation from vertex 0.
        for i in range(1, len(ring) - 1):
            out.append((0, i, i + 1))
    return out


def export_production_dataset(
    *,
    archive_path: str | Path,
    crop_config_path: str | Path,
    output_dir: str | Path,
    candidate_id: str = "em_reference_masked",
    map_id: str = "earth3_europe_mediterranean",
) -> dict:
    t0 = time.perf_counter()
    archive_path = Path(archive_path)
    crop_config_path = Path(crop_config_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset = load_earth3_dataset(archive_path)
    candidates = load_crop_candidates(crop_config_path)
    candidate = next(c for c in candidates if c.id == candidate_id)
    crop = apply_crop(dataset, candidate)

    if crop.province_count != APPROVED_PROVINCE_COUNT:
        raise ValueError(
            f"province_count {crop.province_count} != approved {APPROVED_PROVINCE_COUNT}"
        )
    id_hash = included_ids_hash(crop.included_ids)
    if id_hash != APPROVED_INCLUDED_IDS_SHA256:
        raise ValueError(
            f"included_ids_sha256 {id_hash} != approved {APPROVED_INCLUDED_IDS_SHA256}"
        )

    # Bounds from included geometry (source Earth3 pixels).
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for pid in crop.included_ids:
        b = dataset.provinces[pid].bounds
        min_x = min(min_x, b[0])
        min_y = min(min_y, b[1])
        max_x = max(max_x, b[2])
        max_y = max(max_y, b[3])
    pad = 8.0
    origin_x = min_x - pad
    origin_y = min_y - pad
    width = (max_x + pad) - origin_x
    height = (max_y + pad) - origin_y

    included_set = set(crop.included_ids)
    # Stable Gates IDs: sorted by source id for determinism.
    source_ids = sorted(crop.included_ids)
    gates_by_source: dict[int, str] = {}
    provinces_out: list[dict] = []
    total_tris = 0
    total_verts = 0

    for index, source_id in enumerate(source_ids):
        province = dataset.provinces[source_id]
        gates_id = f"e3_{index:04d}"
        gates_by_source[source_id] = gates_id
        ring_src = province.ring
        # Drop closing duplicate if present.
        if len(ring_src) >= 2 and ring_src[0] == ring_src[-1]:
            ring_src = ring_src[:-1]
        local_ring = [
            [round(x - origin_x, 4), round(y - origin_y, 4)] for x, y in ring_src
        ]
        # Flat vertices [x0,y0,x1,y1,...]
        verts_flat: list[float] = []
        for x, y in local_ring:
            verts_flat.append(float(x))
            verts_flat.append(float(y))
        ring_tuples = tuple((float(p[0]), float(p[1])) for p in local_ring)
        tri_idx = _triangulate(ring_tuples)
        tris_flat: list[int] = []
        for a, b, c in tri_idx:
            tris_flat.extend((a, b, c))
        total_tris += len(tri_idx)
        total_verts += len(local_ring)

        cx = float(province.centroid[0] - origin_x)
        cy = float(province.centroid[1] - origin_y)
        lx = float(province.label_x - origin_x)
        ly = float(province.label_y - origin_y)

        neighbors_src = sorted(
            nb for nb in dataset.neighbors(source_id) if nb in included_set
        )
        provinces_out.append(
            {
                "id": gates_id,
                "source_id": source_id,
                "is_water": bool(province.is_water),
                "terrain_id": int(province.terrain_id),
                "continent_id": int(province.continent_id),
                "centroid": [round(cx, 4), round(cy, 4)],
                "label": [round(lx, 4), round(ly, 4)],
                "vertices": verts_flat,
                "triangles": tris_flat,
                "neighbors_source": neighbors_src,
                "area": round(shoelace_area(ring_tuples), 4),
            }
        )

    # Resolve neighbor Gates IDs after full table exists.
    for row in provinces_out:
        row["neighbors"] = [
            gates_by_source[sid]
            for sid in row.pop("neighbors_source")
            if sid in gates_by_source
        ]

    # Adjacency undirected edges for validation.
    edges: list[list[str]] = []
    seen_e: set[tuple[str, str]] = set()
    for row in provinces_out:
        a = row["id"]
        for b in row["neighbors"]:
            key = (a, b) if a < b else (b, a)
            if key in seen_e:
                continue
            seen_e.add(key)
            edges.append([key[0], key[1]])

    payload = {
        "schema": DATASET_SCHEMA,
        "schema_version": DATASET_SCHEMA_VERSION,
        "map_id": map_id,
        "candidate_id": candidate_id,
        "province_count": len(provinces_out),
        "land_count": sum(1 for p in provinces_out if not p["is_water"]),
        "water_count": sum(1 for p in provinces_out if p["is_water"]),
        "vertex_count": total_verts,
        "triangle_count": total_tris,
        "edge_count": len(edges),
        "approved_included_ids_sha256": APPROVED_INCLUDED_IDS_SHA256,
        "included_source_ids_sha256": id_hash,
        "bounds": {
            "origin_source_xy": [origin_x, origin_y],
            "width": width,
            "height": height,
            "source_min_xy": [min_x, min_y],
            "source_max_xy": [max_x, max_y],
        },
        "coordinate_space": {
            "unit": "earth3_pixels_translated",
            "y_axis": "downward_positive",
            "notes": "Local coords = source Earth3 pixels minus origin_source_xy.",
        },
        "provinces": provinces_out,
        "edges": edges,
        "id_map": [
            {"gates_id": gates_by_source[sid], "source_id": sid} for sid in source_ids
        ],
    }

    dataset_path = output_dir / "polygon_dataset.json"
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    dataset_path.write_text(text + "\n", encoding="utf-8")
    dataset_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

    manifest = {
        "schema": "gates-of-codex.strategic-map",
        "schema_version": 1,
        "map_id": map_id,
        "renderer": "polygon_mesh",
        "provenance": "earth3_em_reference_masked_approved",
        "asset_status": "production_theatre",
        "polygon_dataset": {
            "path": "polygon_dataset.json",
            "sha256": dataset_sha,
            "province_count": len(provinces_out),
        },
        "province_count": len(provinces_out),
        "bounds": payload["bounds"],
        "fallback_map_id": "europe_mediterranean_from_goe",
        "runtime_contract": {
            "gameplay_key": "province_id",
            "hit_test": "point_in_polygon_spatial_index",
            "ownership_update": "event_driven_recolor",
        },
        "approved_included_ids_sha256": APPROVED_INCLUDED_IDS_SHA256,
        "export": {
            "archive_sha256": sha256_file(archive_path) if archive_path.is_file() else "",
            "crop_config_sha256": sha256_text_file(crop_config_path),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        },
    }
    manifest_path = output_dir / "map_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    # Compact meta for tests without loading full geometry.
    meta = {
        "map_id": map_id,
        "province_count": len(provinces_out),
        "land_count": payload["land_count"],
        "water_count": payload["water_count"],
        "vertex_count": total_verts,
        "triangle_count": total_tris,
        "edge_count": len(edges),
        "approved_included_ids_sha256": APPROVED_INCLUDED_IDS_SHA256,
        "included_source_ids_sha256": id_hash,
        "dataset_sha256": dataset_sha,
        "bounds": payload["bounds"],
        "sample_province_ids": [p["id"] for p in provinces_out[:5]],
        "sample_source_ids": [p["source_id"] for p in provinces_out[:5]],
    }
    meta_path = output_dir / "dataset_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "map_id": map_id,
        "output_dir": str(output_dir),
        "dataset_path": str(dataset_path),
        "manifest_path": str(manifest_path),
        "meta_path": str(meta_path),
        "province_count": len(provinces_out),
        "dataset_sha256": dataset_sha,
        "elapsed_ms": manifest["export"]["elapsed_ms"],
        "meta": meta,
    }
