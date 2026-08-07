"""Export approved Earth3 crop as production polygon dataset for Godot."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from shapely import make_valid
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import triangulate as shapely_triangulate

from .audit_artifact import included_ids_hash, sha256_file, sha256_text_file
from .crop import apply_crop, load_crop_candidates
from .parse import load_earth3_dataset

# Pending owner visual approval of mask v6 (Africa–Levant corridor + full Scandinavia).
APPROVED_INCLUDED_IDS_SHA256 = "4fe9d98bbf40d2588286d3d4ec5513ffa3a8f0b7b2ae5689373217b4cb569a1b"
APPROVED_PROVINCE_COUNT = 3345
DATASET_SCHEMA = "gates-of-codex.earth3-polygon-dataset"
DATASET_SCHEMA_VERSION = 2
AREA_REL_TOL = 1e-3


class TriangulationError(ValueError):
    pass


def _extract_polygons(geom) -> list[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom] if geom.area > 0 else []
    if isinstance(geom, (MultiPolygon, GeometryCollection)):
        out: list[Polygon] = []
        for g in geom.geoms:
            out.extend(_extract_polygons(g))
        return out
    return []


def _normalize_polygon(ring: tuple[tuple[float, float], ...]) -> Polygon:
    coords = list(ring)
    if len(coords) < 3:
        raise TriangulationError("ring too small")
    if coords[0] != coords[-1]:
        coords = coords + [coords[0]]
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = make_valid(poly)
    polys = _extract_polygons(poly)
    if not polys:
        raise TriangulationError("empty/invalid polygon after make_valid")
    # Strategic fill uses largest exterior shell only (no holes).
    poly = max(polys, key=lambda g: g.area)
    if poly.interiors:
        poly = Polygon(list(poly.exterior.coords))
        if not poly.is_valid:
            poly = max(_extract_polygons(make_valid(poly)), key=lambda g: g.area)
    if poly.area <= 0:
        raise TriangulationError("non-positive area")
    return poly


def _triangle_coords_from_piece(piece: Polygon) -> list[list[tuple[float, float]]]:
    """Return list of 3-point triangles covering a polygon piece fully inside source."""
    coords = list(piece.exterior.coords)[:-1]
    if len(coords) < 3:
        return []
    if len(coords) == 3:
        return [coords]
    out: list[list[tuple[float, float]]] = []
    for t in shapely_triangulate(piece):
        inter = piece.intersection(t)
        for g in _extract_polygons(inter):
            if g.area <= 1e-12:
                continue
            # Accept only if intersection is essentially the full delaunay triangle
            # or a polygonal piece we can fan.
            cc = list(g.exterior.coords)[:-1]
            if len(cc) == 3:
                out.append(cc)
            elif len(cc) > 3:
                # Convex fan is safe for intersection pieces of triangles.
                for i in range(1, len(cc) - 1):
                    out.append([cc[0], cc[i], cc[i + 1]])
    return out


def triangulate_ring_validated(
    ring: tuple[tuple[float, float], ...],
) -> tuple[list[float], list[int], list[float], dict]:
    """Return (fill_verts_flat, fill_tri_indices, ring_flat, audit).

    Uses Shapely Delaunay triangles clipped to the polygon (no fan fallback on
    the original concave ring).
    """
    poly = _normalize_polygon(ring)
    poly_area = float(poly.area)

    tris_coords: list[list[tuple[float, float]]] = []
    for t in shapely_triangulate(poly):
        if t.is_empty or t.area <= 0:
            continue
        inter = poly.intersection(t)
        for piece in _extract_polygons(inter):
            if piece.area <= 1e-12:
                continue
            tris_coords.extend(_triangle_coords_from_piece(piece))

    if not tris_coords:
        raise TriangulationError("no interior triangles retained")

    tri_area = 0.0
    for tc in tris_coords:
        tri_area += float(Polygon(tc + [tc[0]]).area)
    rel_err = abs(tri_area - poly_area) / poly_area
    if rel_err > AREA_REL_TOL:
        raise TriangulationError(
            f"triangle area mismatch rel_err={rel_err:.6f} poly={poly_area} tris={tri_area}"
        )

    vert_index: dict[tuple[float, float], int] = {}
    vertices: list[list[float]] = []
    indices: list[int] = []

    def vid(x: float, y: float) -> int:
        key = (round(float(x), 6), round(float(y), 6))
        if key not in vert_index:
            vert_index[key] = len(vertices)
            vertices.append([key[0], key[1]])
        return vert_index[key]

    for tc in tris_coords:
        if len(tc) < 3:
            continue
        i0 = vid(tc[0][0], tc[0][1])
        i1 = vid(tc[1][0], tc[1][1])
        i2 = vid(tc[2][0], tc[2][1])
        if i0 == i1 or i1 == i2 or i0 == i2:
            continue
        x0, y0 = vertices[i0]
        x1, y1 = vertices[i1]
        x2, y2 = vertices[i2]
        cross = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
        if cross < 0:
            i1, i2 = i2, i1
        indices.extend((i0, i1, i2))

    if len(indices) < 3:
        raise TriangulationError("no index triples after winding filter")

    for t in range(0, len(indices), 3):
        a, b, c = indices[t], indices[t + 1], indices[t + 2]
        if a == b or b == c or a == c:
            raise TriangulationError("degenerate triangle indices")
        n = len(vertices)
        if a < 0 or b < 0 or c < 0 or a >= n or b >= n or c >= n:
            raise TriangulationError("triangle index out of range")

    verts_flat: list[float] = []
    for x, y in vertices:
        verts_flat.extend((float(x), float(y)))

    ring_flat: list[float] = []
    for x, y in ring:
        ring_flat.extend((float(x), float(y)))

    audit = {
        "polygon_area": poly_area,
        "triangle_area": tri_area,
        "rel_err": rel_err,
        "triangle_count": len(indices) // 3,
        "vertex_count": len(vertices),
    }
    return verts_flat, indices, ring_flat, audit


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
    source_ids = sorted(crop.included_ids)
    gates_by_source: dict[int, str] = {}
    provinces_out: list[dict] = []
    total_tris = 0
    total_verts = 0
    poly_area_sum = 0.0
    tri_area_sum = 0.0
    max_rel_err = 0.0
    failed: list[dict] = []
    border_segments: set[tuple[tuple[float, float], tuple[float, float]]] = set()

    for index, source_id in enumerate(source_ids):
        province = dataset.provinces[source_id]
        gates_id = f"e3_{index:04d}"
        gates_by_source[source_id] = gates_id
        ring_src = province.ring
        if len(ring_src) >= 2 and ring_src[0] == ring_src[-1]:
            ring_src = ring_src[:-1]
        local_ring = tuple(
            (round(x - origin_x, 6), round(y - origin_y, 6)) for x, y in ring_src
        )
        try:
            verts_flat, tris_flat, ring_flat, audit = triangulate_ring_validated(local_ring)
        except Exception as exc:  # noqa: BLE001
            failed.append({"source_id": source_id, "gates_id": gates_id, "error": str(exc)})
            continue

        n = len(local_ring)
        for i in range(n):
            a = local_ring[i]
            b = local_ring[(i + 1) % n]
            if a == b:
                continue
            edge = (a, b) if a < b else (b, a)
            border_segments.add(edge)

        total_tris += len(tris_flat) // 3
        total_verts += len(verts_flat) // 2
        poly_area_sum += float(audit["polygon_area"])
        tri_area_sum += float(audit["triangle_area"])
        max_rel_err = max(max_rel_err, float(audit["rel_err"]))

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
                "ring": ring_flat,
                "neighbors_source": neighbors_src,
                "area": round(float(audit["polygon_area"]), 4),
            }
        )

    tri_audit = {
        "ok": len(failed) == 0,
        "province_count_checked": len(source_ids),
        "failed_count": len(failed),
        "failed_province_ids": failed,
        "max_area_error": max_rel_err,
        "total_polygon_area": poly_area_sum,
        "total_triangle_area": tri_area_sum,
        "triangulator": "shapely_delaunay_clipped_interior",
        "area_rel_tol": AREA_REL_TOL,
        "no_fan_fallback": True,
    }
    (output_dir / "triangulation_audit.json").write_text(
        json.dumps(tri_audit, indent=2) + "\n", encoding="utf-8"
    )
    if failed:
        raise TriangulationError(
            f"triangulation failed for {len(failed)} provinces; see triangulation_audit.json"
        )

    for row in provinces_out:
        row["neighbors"] = [
            gates_by_source[sid]
            for sid in row.pop("neighbors_source")
            if sid in gates_by_source
        ]

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

    borders_flat: list[float] = []
    for a, b in sorted(border_segments):
        borders_flat.extend((a[0], a[1], b[0], b[1]))

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
        "border_segment_count": len(border_segments),
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
        },
        "triangulation_audit": tri_audit,
        "provinces": provinces_out,
        "edges": edges,
        "border_segments": borders_flat,
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
            "ownership_update": "immutable_geometry_shader_lookup",
        },
        "approved_included_ids_sha256": APPROVED_INCLUDED_IDS_SHA256,
        "export": {
            "archive_sha256": sha256_file(archive_path) if archive_path.is_file() else "",
            "crop_config_sha256": sha256_text_file(crop_config_path),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "triangulation_ok": True,
            "max_tri_area_error": max_rel_err,
        },
    }
    (output_dir / "map_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    meta = {
        "map_id": map_id,
        "province_count": len(provinces_out),
        "land_count": payload["land_count"],
        "water_count": payload["water_count"],
        "vertex_count": total_verts,
        "triangle_count": total_tris,
        "edge_count": len(edges),
        "border_segment_count": len(border_segments),
        "approved_included_ids_sha256": APPROVED_INCLUDED_IDS_SHA256,
        "included_source_ids_sha256": id_hash,
        "dataset_sha256": dataset_sha,
        "bounds": payload["bounds"],
        "triangulation_audit": tri_audit,
        "sample_province_ids": [p["id"] for p in provinces_out[:5]],
        "sample_source_ids": [p["source_id"] for p in provinces_out[:5]],
    }
    (output_dir / "dataset_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )

    return {
        "ok": True,
        "map_id": map_id,
        "output_dir": str(output_dir),
        "dataset_path": str(dataset_path),
        "manifest_path": str(output_dir / "map_manifest.json"),
        "meta_path": str(output_dir / "dataset_meta.json"),
        "province_count": len(provinces_out),
        "dataset_sha256": dataset_sha,
        "elapsed_ms": manifest["export"]["elapsed_ms"],
        "triangulation_audit": tri_audit,
        "meta": meta,
    }
