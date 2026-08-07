"""Earth3 topology sanitization: land components, suspicious polygons, overrides."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from shapely import make_valid
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box
from shapely.ops import unary_union

from .geometry import shoelace_area


SCHEMA_OVERRIDES = "gates-of-codex.earth3-province-classification-overrides"
SCHEMA_VERSION = 1

# Image-space heuristics on the v7 Europe–Asia crop (4306×3449 local).
MAINLAND_MIN_COMPONENT_PROVINCES = 500
# Perfect or near-perfect rectangles with few vertices are marker artifacts.
RECT_VERTEX_MAX = 6
RECT_AREA_MAX = 2500.0
RECTNESS_MIN = 0.92
TINY_ISOLATED_AREA_MAX = 900.0
# Eastern crop-spill band: far-right detached land beyond Caspian approaches.
EAST_SPILL_X_FRAC = 0.90


@dataclass(frozen=True)
class ComponentInfo:
    component_id: str
    gates_ids: tuple[str, ...]
    source_ids: tuple[int, ...]
    polygon_count: int
    centroid: tuple[float, float]
    total_area: float
    bbox: tuple[float, float, float, float]
    terrain_ids: tuple[int, ...]
    continent_ids: tuple[int, ...]
    source_is_water_values: tuple[bool, ...]
    classification: str
    keep: bool
    reason: str


def _ring_points(row: dict) -> list[tuple[float, float]]:
    flat = row.get("ring") or []
    pts: list[tuple[float, float]] = []
    for i in range(0, len(flat) - 1, 2):
        pts.append((float(flat[i]), float(flat[i + 1])))
    return pts


def _rectness(pts: list[tuple[float, float]]) -> float:
    if len(pts) < 3:
        return 0.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    w = max(xs) - min(xs)
    h = max(ys) - min(ys)
    if w <= 1e-9 or h <= 1e-9:
        return 0.0
    return shoelace_area(pts) / (w * h)


def _bbox(pts: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def land_connected_components(provinces: list[dict]) -> list[list[str]]:
    by_id = {str(p["id"]): p for p in provinces}
    land_ids = {pid for pid, p in by_id.items() if not bool(p.get("is_water"))}
    adj: dict[str, set[str]] = defaultdict(set)
    for pid in land_ids:
        for nb in by_id[pid].get("neighbors") or []:
            nbs = str(nb)
            if nbs in land_ids:
                adj[pid].add(nbs)
                adj[nbs].add(pid)
    seen: set[str] = set()
    comps: list[list[str]] = []
    for pid in sorted(land_ids):
        if pid in seen:
            continue
        q: deque[str] = deque([pid])
        seen.add(pid)
        mem: list[str] = []
        while q:
            u = q.popleft()
            mem.append(u)
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    q.append(v)
        comps.append(mem)
    comps.sort(key=lambda c: (-len(c), c[0]))
    return comps


def _classify_component(
    *,
    index: int,
    members: list[str],
    by_id: dict[str, dict],
    image_width: float,
    mainland_centroid: tuple[float, float],
) -> ComponentInfo:
    rows = [by_id[m] for m in members]
    total_area = float(sum(float(r.get("area") or 0.0) for r in rows))
    cx = sum(float(r["centroid"][0]) for r in rows) / len(rows)
    cy = sum(float(r["centroid"][1]) for r in rows) / len(rows)
    all_pts: list[tuple[float, float]] = []
    for r in rows:
        all_pts.extend(_ring_points(r))
    bb = _bbox(all_pts) if all_pts else (cx, cy, cx, cy)
    source_ids = tuple(int(r["source_id"]) for r in rows)
    terrain_ids = tuple(sorted({int(r.get("terrain_id", -1)) for r in rows}))
    continent_ids = tuple(sorted({int(r.get("continent_id", -1)) for r in rows}))
    water_vals = tuple(bool(r.get("is_water")) for r in rows)
    cid = f"L{index:03d}"
    n = len(members)
    east_x = image_width * EAST_SPILL_X_FRAC
    nearest_mainland = _dist((cx, cy), mainland_centroid)

    # Allowlist legitimate islands / archipelagos by size + geography.
    if n >= MAINLAND_MIN_COMPONENT_PROVINCES:
        classification = "legitimate_mainland"
        keep = True
        reason = "largest connected land mass(es)"
    elif n >= 80 and 200 < cx < 1200 and cy < 2200:
        # Great Britain / Ireland scale western islands.
        classification = "legitimate_real_archipelago"
        keep = True
        reason = "large western island/archipelago component"
    elif n >= 15 and cx < 700 and cy < 1400:
        classification = "legitimate_real_island"
        keep = True
        reason = "Iceland-scale north-west island component"
    elif n >= 8 and 1400 < cx < 2800 and 2200 < cy < 3200:
        # Mediterranean islands cluster (Sardinia/Sicily/Crete scale groups).
        classification = "legitimate_real_archipelago"
        keep = True
        reason = "Mediterranean island/archipelago component"
    elif n >= 5 and 2400 < cx < 3200 and 2400 < cy < 3200:
        classification = "legitimate_real_island"
        keep = True
        reason = "eastern Med / Cyprus-scale island component"
    elif n >= 3 and 1600 < cx < 2300 and 1000 < cy < 1700:
        classification = "legitimate_real_island"
        keep = True
        reason = "Baltic / Scandinavian island component"
    elif cx >= east_x and n <= 30:
        classification = "crop_spill_beyond_approved_boundary"
        keep = False
        reason = "detached land in eastern spill band beyond Ural/Caspian approaches"
    elif n <= 3 and total_area < TINY_ISOLATED_AREA_MAX and nearest_mainland > 80:
        # Further classified at polygon level; mark component suspicious.
        classification = "malformed_source_or_marker_polygon"
        keep = False
        reason = "tiny isolated land component not matching island allowlist"
    elif n == 1:
        row = rows[0]
        pts = _ring_points(row)
        rn = _rectness(pts)
        if len(pts) <= RECT_VERTEX_MAX and rn >= RECTNESS_MIN:
            classification = "malformed_source_or_marker_polygon"
            keep = False
            reason = "single rectangular marker polygon"
        else:
            classification = "unexplained"
            keep = False
            reason = "single-province land component outside island allowlist"
    else:
        classification = "unexplained"
        keep = False
        reason = "disconnected land component outside island allowlist"

    return ComponentInfo(
        component_id=cid,
        gates_ids=tuple(members),
        source_ids=source_ids,
        polygon_count=n,
        centroid=(round(cx, 2), round(cy, 2)),
        total_area=round(total_area, 2),
        bbox=(round(bb[0], 2), round(bb[1], 2), round(bb[2], 2), round(bb[3], 2)),
        terrain_ids=terrain_ids,
        continent_ids=continent_ids,
        source_is_water_values=water_vals,
        classification=classification,
        keep=keep,
        reason=reason,
    )


def audit_land_components(dataset: dict) -> dict[str, Any]:
    provinces = list(dataset.get("provinces") or [])
    by_id = {str(p["id"]): p for p in provinces}
    width = float((dataset.get("bounds") or {}).get("width") or 1.0)
    comps = land_connected_components(provinces)
    # Mainland = largest component centroid.
    mainland_ids = comps[0] if comps else []
    if mainland_ids:
        mcx = sum(float(by_id[i]["centroid"][0]) for i in mainland_ids) / len(mainland_ids)
        mcy = sum(float(by_id[i]["centroid"][1]) for i in mainland_ids) / len(mainland_ids)
        mainland_centroid = (mcx, mcy)
    else:
        mainland_centroid = (0.0, 0.0)

    infos: list[ComponentInfo] = []
    for i, mem in enumerate(comps):
        infos.append(
            _classify_component(
                index=i,
                members=mem,
                by_id=by_id,
                image_width=width,
                mainland_centroid=mainland_centroid,
            )
        )

    # Distance to nearest kept component coastline centroid for each rejected.
    kept_centroids = [c.centroid for c in infos if c.keep]
    rows_out: list[dict] = []
    for info in infos:
        nearest = None
        if kept_centroids:
            nearest = min(_dist(info.centroid, k) for k in kept_centroids)
        rows_out.append(
            {
                "component_id": info.component_id,
                "gates_ids": list(info.gates_ids),
                "source_ids": list(info.source_ids),
                "polygon_count": info.polygon_count,
                "centroid": list(info.centroid),
                "total_area": info.total_area,
                "bbox": list(info.bbox),
                "nearest_legitimate_land_centroid_dist": None
                if nearest is None
                else round(nearest, 2),
                "terrain_ids": list(info.terrain_ids),
                "continent_ids": list(info.continent_ids),
                "source_is_water_values": list(info.source_is_water_values),
                "classification": info.classification,
                "keep": info.keep,
                "reason": info.reason,
                "screenshot_label": info.component_id,
            }
        )

    non_allowlisted = [
        r
        for r in rows_out
        if not r["keep"] and r["classification"] in ("unexplained", "malformed_source_or_marker_polygon", "crop_spill_beyond_approved_boundary", "water_misclassified_as_land", "disconnected_polygon_export_normalization")
    ]
    return {
        "schema": "gates-of-codex.earth3-land-component-audit",
        "schema_version": 1,
        "component_count": len(rows_out),
        "kept_component_count": sum(1 for r in rows_out if r["keep"]),
        "rejected_component_count": sum(1 for r in rows_out if not r["keep"]),
        "non_allowlisted_unexplained_or_bad": len(
            [r for r in rows_out if not r["keep"]]
        ),
        "mainland_centroid": [round(mainland_centroid[0], 2), round(mainland_centroid[1], 2)],
        "components": rows_out,
        "hard_requirement": {
            "non_allowlisted_unexplained_land_components_must_be_zero_after_sanitize": True,
            "pre_sanitize_rejected_count": sum(1 for r in rows_out if not r["keep"]),
        },
    }


def audit_suspicious_polygons(dataset: dict, component_audit: dict) -> dict[str, Any]:
    provinces = list(dataset.get("provinces") or [])
    by_id = {str(p["id"]): p for p in provinces}
    width = float((dataset.get("bounds") or {}).get("width") or 1.0)
    rejected_ids: set[str] = set()
    for c in component_audit.get("components") or []:
        if not c.get("keep"):
            rejected_ids.update(str(x) for x in c.get("gates_ids") or [])

    rows: list[dict] = []
    for p in provinces:
        if bool(p.get("is_water")):
            continue
        pid = str(p["id"])
        pts = _ring_points(p)
        area = float(p.get("area") or shoelace_area(pts))
        rn = _rectness(pts)
        nvert = len(pts)
        cx, cy = float(p["centroid"][0]), float(p["centroid"][1])
        isolated = len(p.get("neighbors") or []) == 0
        flags: list[str] = []
        if nvert <= RECT_VERTEX_MAX and rn >= RECTNESS_MIN and area <= RECT_AREA_MAX:
            flags.append("high_rectangularity")
        if area < 100.0:
            flags.append("tiny_area")
        if isolated and area < 12000.0:
            flags.append("isolated_open_water_candidate")
        if cx >= width * EAST_SPILL_X_FRAC and len(p.get("neighbors") or []) <= 1:
            flags.append("eastern_edge_detached")
        if pid in rejected_ids:
            flags.append("in_rejected_component")
        if not flags:
            continue

        if "high_rectangularity" in flags:
            classification = "malformed_source_or_marker_polygon"
            decision = "exclude"
            reason = "near-rectangular few-vertex land marker in open water or isolated"
        elif "eastern_edge_detached" in flags:
            classification = "crop_spill_beyond_approved_boundary"
            decision = "exclude"
            reason = "detached eastern land beyond approved Europe–Urals extent"
        elif "in_rejected_component" in flags:
            classification = "malformed_source_or_marker_polygon"
            decision = "exclude"
            reason = "member of non-allowlisted disconnected land component"
        elif "tiny_area" in flags and "isolated_open_water_candidate" in flags:
            classification = "malformed_source_or_marker_polygon"
            decision = "exclude"
            reason = "tiny isolated land polygon"
        else:
            classification = "unexplained"
            decision = "exclude"
            reason = "suspicious land polygon requiring exclusion pending island proof"

        rows.append(
            {
                "gates_id": pid,
                "source_id": int(p["source_id"]),
                "area": round(area, 3),
                "vertex_count": nvert,
                "rectangularity": round(rn, 4),
                "centroid": [round(cx, 2), round(cy, 2)],
                "bbox": list(_bbox(pts)) if pts else None,
                "neighbor_count": len(p.get("neighbors") or []),
                "terrain_id": int(p.get("terrain_id", -1)),
                "continent_id": int(p.get("continent_id", -1)),
                "is_water": bool(p.get("is_water")),
                "flags": flags,
                "classification": classification,
                "decision": decision,
                "reason": reason,
                "owner_review_status": "proposed",
                "ring_sample": pts[:12],
            }
        )

    rows.sort(key=lambda r: (r["area"], r["gates_id"]))
    unexplained = [r for r in rows if r["classification"] == "unexplained"]
    return {
        "schema": "gates-of-codex.earth3-suspicious-polygon-audit",
        "schema_version": 1,
        "suspicious_count": len(rows),
        "exclude_count": sum(1 for r in rows if r["decision"] == "exclude"),
        "unexplained_count": len(unexplained),
        "polygons": rows,
        "hard_requirement": {
            "unexplained_suspicious_rectangular_land_must_be_zero_after_sanitize": True,
            "pre_sanitize_unexplained": len(unexplained),
        },
    }


def build_overrides(
    *,
    component_audit: dict,
    suspicious_audit: dict,
    previous_included_hash: str,
) -> dict[str, Any]:
    overrides: list[dict] = []
    seen_source: set[int] = set()

    def add(source_id: int, gates_id: str | None, prev: str, corrected: str, reason: str, evidence: str) -> None:
        if source_id in seen_source:
            return
        seen_source.add(source_id)
        overrides.append(
            {
                "source_id": int(source_id),
                "gates_id_pre_sanitize": gates_id,
                "previous_classification": prev,
                "corrected_classification": corrected,
                "action": "exclude" if corrected == "excluded" else corrected,
                "reason": reason,
                "evidence_reference": evidence,
                "owner_review_status": "proposed",
            }
        )

    for c in component_audit.get("components") or []:
        if c.get("keep"):
            continue
        for sid, gid in zip(c.get("source_ids") or [], c.get("gates_ids") or []):
            add(
                int(sid),
                str(gid),
                "land_included",
                "excluded",
                str(c.get("reason") or c.get("classification")),
                f"component:{c.get('component_id')}",
            )

    for p in suspicious_audit.get("polygons") or []:
        if p.get("decision") != "exclude":
            continue
        add(
            int(p["source_id"]),
            str(p.get("gates_id")),
            "land_included",
            "excluded",
            str(p.get("reason")),
            f"suspicious:{p.get('gates_id')}",
        )

    overrides.sort(key=lambda o: int(o["source_id"]))
    payload = {
        "schema": SCHEMA_OVERRIDES,
        "schema_version": SCHEMA_VERSION,
        "description": "Project-owned Earth3 province classification overrides for topology sanitization (#117).",
        "pre_sanitize_included_ids_sha256": previous_included_hash,
        "water_policy": {
            "v1": "water_not_normally_selectable",
            "normal_click_returns": "no_province",
            "source_water_ids": "import_metadata_only",
            "sea_movement": "authored_operational_nodes_edges",
        },
        "overrides": overrides,
        "override_count": len(overrides),
        "excluded_source_ids": [int(o["source_id"]) for o in overrides if o.get("action") == "exclude"],
    }
    # Validate required fields.
    for o in overrides:
        if not o.get("reason") or not o.get("evidence_reference"):
            raise ValueError(f"override missing reason/evidence: {o}")
    return payload


def extract_polygons(geom) -> list[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom] if geom.area > 0 else []
    if isinstance(geom, (MultiPolygon, GeometryCollection)):
        out: list[Polygon] = []
        for g in geom.geoms:
            out.extend(extract_polygons(g))
        return out
    return []


def normalize_province_geometry(
    ring: tuple[tuple[float, float], ...],
    *,
    keep_all_parts: bool = True,
    min_part_area_ratio: float = 0.02,
    min_part_area_abs: float = 25.0,
) -> tuple[list[Polygon], dict[str, Any]]:
    """Normalize ring geometry without silently dropping legitimate multipart pieces.

    Returns retained exterior shells (holes stripped for strategic fill) and an audit dict.
    """
    coords = list(ring)
    if len(coords) < 3:
        raise ValueError("ring too small")
    if coords[0] != coords[-1]:
        coords = coords + [coords[0]]
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = make_valid(poly)
    parts = extract_polygons(poly)
    if not parts:
        raise ValueError("empty/invalid after make_valid")
    parts = sorted(parts, key=lambda g: g.area, reverse=True)
    largest = parts[0].area
    retained: list[Polygon] = []
    dropped: list[dict] = []
    for i, g in enumerate(parts):
        area = float(g.area)
        ratio = area / largest if largest > 0 else 0.0
        # Strip interiors for strategic fill.
        shell = Polygon(list(g.exterior.coords))
        if not shell.is_valid:
            shell_parts = extract_polygons(make_valid(shell))
            shell = max(shell_parts, key=lambda x: x.area) if shell_parts else shell
        if i == 0:
            retained.append(shell)
            continue
        if keep_all_parts and (ratio >= min_part_area_ratio or area >= min_part_area_abs):
            retained.append(shell)
        else:
            dropped.append({"part_index": i, "area": area, "ratio_of_largest": ratio, "reason": "below_multipart_threshold"})
    audit = {
        "input_part_count": len(parts),
        "retained_part_count": len(retained),
        "dropped_parts": dropped,
        "largest_area": float(largest),
        "retained_areas": [float(g.area) for g in retained],
    }
    return retained, audit


def apply_exclusions_to_source_ids(
    included_source_ids: Iterable[int],
    overrides: dict,
) -> list[int]:
    excluded = {int(x) for x in overrides.get("excluded_source_ids") or []}
    for o in overrides.get("overrides") or []:
        if o.get("action") == "exclude":
            excluded.add(int(o["source_id"]))
    return sorted(sid for sid in included_source_ids if int(sid) not in excluded)


def sha256_json(data: dict) -> str:
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
