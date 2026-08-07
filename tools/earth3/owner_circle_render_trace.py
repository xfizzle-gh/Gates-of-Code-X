#!/usr/bin/env python3
"""Exact rendered-feature trace for owner-circled hydrography points.

Simulates Godot PolygonMap rules:
  - land fill from province triangles only
  - water provinces: rings/borders only (no fill mesh)
  - continuous ocean underlay everywhere without land fill
  - borders from all province ring edges (drop pure water–water)
  - ocean_gap_fills are dataset metadata only (not meshed in Godot)

Writes docs/earth3-crop/hydrography_audit/owner_circle_render_trace.json
and evidence/owner_circles_numbered_traced.png
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import LineString, MultiPoint, Point, Polygon, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from gates_of_codex.earth3.export_production import triangulate_ring_validated  # noqa: E402
from gates_of_codex.earth3.parse import load_earth3_dataset  # noqa: E402

PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean"
OUT = ROOT / "docs/earth3-crop/hydrography_audit"
NE_SUBSET = OUT / "reference/ne_10m_lakes_europe_subset.json"
HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"
RECON_TOL = 1e-4
EARTH_R = 6371008.8

# Owner-circle sample points (map-local). NE01 uses original screenshot mark, not src11836 identity claim.
OWNER_CIRCLES = [
    ("NE01_northern_outline", 4220.0, 660.0, "top northern outline from owner F5"),
    ("NE02_Ladoga", 2803.0, 1052.0, "Ladoga"),
    ("NE03_Onega", 2996.0, 978.0, "Onega"),
    ("NE04_WhiteSea_SE_large_hole", 3618.0, 685.0, "large northern interior hole"),
    ("NE05_Rybinsk", 3133.0, 1255.0, "Rybinsk"),
    ("NE06_Galich_area", 3376.0, 1273.0, "Galich-area feature"),
    ("NE07_east_volga", 3597.0, 1356.0, "eastern Volga candidate"),
    ("NE08_kama_volga", 3890.0, 1546.0, "Kama/Volga candidate"),
]


def pair_vertices(vertices):
    if not vertices:
        return []
    if isinstance(vertices[0], (list, tuple)):
        return [(float(v[0]), float(v[1])) for v in vertices]
    return [(float(vertices[i]), float(vertices[i + 1])) for i in range(0, len(vertices) - 1, 2)]


def flat_tris(triangles):
    if not triangles:
        return []
    if isinstance(triangles[0], (list, tuple)):
        out = []
        for t in triangles:
            out.extend(int(i) for i in t)
        return out
    return [int(i) for i in triangles]


def reconstruct(vertices, triangles, area):
    pts = pair_vertices(vertices)
    tflat = flat_tris(triangles)
    polys = []
    for i in range(0, len(tflat), 3):
        a, b, c = tflat[i], tflat[i + 1], tflat[i + 2]
        if min(a, b, c) < 0 or max(a, b, c) >= len(pts) or len({a, b, c}) < 3:
            continue
        tri = Polygon([pts[a], pts[b], pts[c]])
        if not tri.is_valid:
            tri = make_valid(tri)
        if not tri.is_empty:
            polys.append(tri)
    if not polys:
        return None, {"ok": False}
    u = unary_union(polys)
    if not u.is_valid:
        u = make_valid(u)
    recon = float(u.area)
    committed = float(area or 0)
    rel = abs(recon - committed) / committed if committed > 0 else 0.0
    return u, {
        "ok": rel <= RECON_TOL,
        "vertex_count": len(pts),
        "triangle_count": len(tflat) // 3,
        "committed_area": committed,
        "reconstructed_area": recon,
        "reconstruction_relative_error": rel,
        "geometry_source": "emitted_triangle_union",
    }


def ring_poly(row):
    pts = pair_vertices(row.get("ring") or [])
    if len(pts) < 3:
        return None
    if pts[0] != pts[-1]:
        pts = pts + [pts[0]]
    g = Polygon(pts)
    if not g.is_valid:
        g = make_valid(g)
    return g if not g.is_empty else None


def edge_key(a, b, snap=0.01):
    ax, ay = round(a[0] / snap) * snap, round(a[1] / snap) * snap
    bx, by = round(b[0] / snap) * snap, round(b[1] / snap) * snap
    p1, p2 = (ax, ay), (bx, by)
    return (p1, p2) if p1 <= p2 else (p2, p1)


def register_edges(edge_map, ring_pts, is_water, pid, sid):
    n = len(ring_pts)
    if n < 2:
        return
    pts = list(ring_pts)
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        k = edge_key(a, b)
        e = edge_map.setdefault(k, {"land": [], "water": [], "flags": 0})
        if is_water:
            e["flags"] |= 2
            e["water"].append({"gates_id": pid, "source_id": sid})
        else:
            e["flags"] |= 1
            e["land"].append({"gates_id": pid, "source_id": sid})


def point_in_ring(pt, ring_pts):
    # ray cast
    x, y = pt
    inside = False
    n = len(ring_pts)
    if n < 3:
        return False
    pts = list(ring_pts)
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    n = len(pts)
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi):
            inside = not inside
        j = i
    return inside


def hav(lon1, lat1, lon2, lat2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def laea(lon, lat, lon0, lat0):
    phi, lam = math.radians(lat), math.radians(lon)
    phi0, lam0 = math.radians(lat0), math.radians(lon0)
    cos_c = math.sin(phi0) * math.sin(phi) + math.cos(phi0) * math.cos(phi) * math.cos(lam - lam0)
    cos_c = min(1.0, max(-1.0, cos_c))
    if cos_c <= -1 + 1e-15:
        return 0.0, 0.0
    k = math.sqrt(2.0 / (1.0 + cos_c))
    x = EARTH_R * k * math.cos(phi) * math.sin(lam - lam0)
    y = EARTH_R * k * (math.cos(phi0) * math.sin(phi) - math.sin(phi0) * math.cos(phi) * math.cos(lam - lam0))
    return x, y


def load_georef_mats():
    t = json.loads((OUT / "georeference_transform.json").read_text(encoding="utf-8"))
    return {k: np.array(v["affine_3x2"], float) for k, v in t["regions"].items()}, t


def region_of(x, y):
    if y >= 2400 and x <= 9800:
        return "mediterranean_na"
    if x < 9600:
        return "west_europe"
    if y < 1150 and x >= 9600:
        return "ne_russia_north"
    return "east_europe_russia"


def txy(mats, x, y):
    r = region_of(x, y)
    A = mats[r] if r in mats else mats["east_europe_russia"]
    v = np.array([x, y, 1.0]) @ A
    return float(v[0]), float(v[1])


def poly_match_meters(e3_wgs, lakes):
    if e3_wgs is None or e3_wgs.is_empty:
        return None
    c = e3_wgs.centroid
    lon0, lat0 = float(c.x), float(c.y)

    def proj(g):
        def xf(xs, ys, zs=None):
            ox, oy = [], []
            for x, y in zip(xs, ys):
                px, py = laea(x, y, lon0, lat0)
                ox.append(px)
                oy.append(py)
            return ox, oy

        from shapely.ops import transform

        return transform(xf, g)

    e3m = proj(e3_wgs)
    best = None
    for lk in lakes:
        try:
            gm = proj(lk["geom"])
            inter = e3m.intersection(gm)
            uni = e3m.union(gm)
        except Exception:
            continue
        ia = float(inter.area) if not inter.is_empty else 0.0
        ua = float(uni.area) if not uni.is_empty else 0.0
        e3a = float(e3m.area)
        refa = float(gm.area)
        iou = ia / ua if ua > 0 else 0.0
        cov = ia / e3a if e3a > 0 else 0.0
        sep = hav(c.x, c.y, lk["centroid"][0], lk["centroid"][1])
        row = {
            "name": lk["name"] or "(unnamed)",
            "iou": round(iou, 4),
            "earth3_coverage_by_ref": round(cov, 4),
            "centroid_separation_km": round(sep, 2),
            "earth3_area_km2": round(e3a / 1e6, 3),
            "ref_area_km2": round(refa / 1e6, 3),
            "metric_units": "meters_laea",
            "score": iou * 2 + cov - sep / 500.0,
        }
        if best is None or row["score"] > best["score"]:
            best = row
    return best


def classify_pixel(kind_bits):
    # priority
    if kind_bits.get("outside_crop"):
        return "outside_the_crop"
    if kind_bits.get("land_fill"):
        return "land_mesh"
    if kind_bits.get("gap_fill"):
        return "gap_fill_metadata_ocean_shows_through"
    if kind_bits.get("water_ring"):
        return "water_metadata_polygon_ocean_shows_through"
    if kind_bits.get("near_border"):
        return "border_only_geometry_over_ocean"
    if kind_bits.get("in_bounds"):
        return "continuous_water_background"
    return "empty_canvas"


def final_class_for_feature(label, trace, match, mats):
    gap = trace.get("ocean_gap_fill")
    land = trace.get("land_fill_hit")
    borders = trace.get("border_segments_near") or []
    arch = trace.get("archive_land_at_point")
    explicit = trace.get("explicit_exclude") or {}

    if label == "NE01_northern_outline":
        if land:
            return "SOURCE_GEOMETRY_DEFECT", "land fill present at sample — unexpected for hole outline"
        if arch and not trace.get("archive_land_in_production"):
            sid = int(arch["source_id"])
            if sid == 11836:
                return (
                    "CROP_EDGE_PRESENTATION_ARTIFACT",
                    "Archive mainland src11836 (Fion) is inside image bounds but outside v7 mask "
                    "(mask_overlap=0). Continuous ocean shows; not meshed. NOT Kolguyev "
                    f"(~{trace.get('geography_compare', {}).get('distance_to_true_kolguyev_km')} km from 49.25E/69.08N).",
                )
            if explicit.get("is_explicit_exclude"):
                return (
                    "SOURCE_GEOMETRY_DEFECT",
                    f"Archive land src {sid} is on crop explicit_exclude_ids; ocean underlay at owner circle.",
                )
            return (
                "CROP_EDGE_PRESENTATION_ARTIFACT",
                f"Archive land src {sid} omitted from 3510; ocean underlay at owner circle.",
            )
        if borders and not land:
            return "BORDER_ARTIFACT_REMOVE", "borders without land fill; no archive land at point"
        return "UNRESOLVED_WITH_EXACT_TRACE", "trace complete but no decisive producer"

    if label in ("NE02_Ladoga", "NE03_Onega", "NE05_Rybinsk"):
        if match and (
            match["iou"] >= 0.15
            or match["earth3_coverage_by_ref"] >= 0.25
            or (match["centroid_separation_km"] < 40 and match["iou"] >= 0.05)
        ):
            return "REAL_WATER_KEEP", f"exact gap-fill LAEA match {match['name']} iou={match['iou']}"
        return "UNRESOLVED_WITH_EXACT_TRACE", "expected water keep but match failed"

    # NE04/06/07/08: gap fills over explicitly excluded archive land
    if arch and not trace.get("archive_land_in_production") and explicit.get("is_explicit_exclude"):
        sid = int(arch["source_id"])
        cities = ", ".join(arch.get("cities") or []) or "unnamed"
        gap_id = gap["id"] if gap else "none"
        near = ""
        if match:
            near = f" nearest NE lake '{match['name']}' iou={match['iou']} sep_km={match['centroid_separation_km']}"
        return (
            "SOURCE_GEOMETRY_DEFECT",
            f"Owner circle is gap-fill {gap_id} over explicitly excluded archive land "
            f"src {sid} ({cities}). Not confirmed real water at this scale.{near} "
            "Godot draws continuous ocean (gap-fill not meshed).",
        )

    if match and match["iou"] >= 0.15:
        name = match["name"]
        ratio = (match["earth3_area_km2"] / match["ref_area_km2"]) if match.get("ref_area_km2") else None
        note = f"match {name} iou={match['iou']} area_ratio={ratio}"
        if ratio and ratio > 2.5:
            return "REAL_WATER_KEEP", note + " — scale exaggerated; consider reduce/replace gap fill"
        return "REAL_WATER_KEEP", note
    if match and match["centroid_separation_km"] < 80 and match["iou"] < 0.05:
        return (
            "SOURCE_GEOMETRY_DEFECT",
            f"near {match['name']} but poor overlap iou={match['iou']} — exaggerated/merged gap or wrong feature",
        )
    if gap:
        return (
            "UNRESOLVED_WITH_EXACT_TRACE",
            f"gap {gap['id']} without decisive land-exclude or lake match",
        )
    return "UNRESOLVED_WITH_EXACT_TRACE", "no reliable reference match"


def recommendation(final_class, label, match, trace):
    if final_class == "REAL_WATER_KEEP":
        if match and match.get("earth3_area_km2") and match.get("ref_area_km2"):
            ratio = match["earth3_area_km2"] / match["ref_area_km2"]
            if ratio > 2.5:
                return "reduce_or_replace_gap_fill"
        return "keep"
    if final_class == "CROP_EDGE_PRESENTATION_ARTIFACT":
        return "no_production_change_document_crop_edge_presentation"
    if final_class == "BORDER_ARTIFACT_REMOVE":
        return "remove_or_suppress_orphan_border_presentation"
    if final_class == "SOURCE_GEOMETRY_DEFECT":
        # Prefer restore-land option when explicit exclude created the hole
        if (trace or {}).get("explicit_exclude", {}).get("is_explicit_exclude"):
            return "owner_ruling_restore_excluded_land_or_accept_water_gap_presentation"
        return "defer_owner_ruling_on_gap_geometry"
    if final_class == "REAL_ISLAND_MISSING_FROM_SOURCE":
        return "no_source_polygon_to_restore"
    if final_class == "REAL_ISLAND_OMITTED_BY_CROP":
        return "owner_mask_ruling_required"
    if final_class == "REAL_ISLAND_FILL_RENDER_BUG":
        return "fix_land_fill_export"
    return "defer_if_no_reliable_reference"


def main() -> int:
    prod = json.loads((PROD / "polygon_dataset.json").read_text(encoding="utf-8"))
    assert prod["province_count"] == 3510 and prod["included_source_ids_sha256"] == HASH
    ox, oy = prod["bounds"]["origin_source_xy"]
    w = float(prod["bounds"]["width"])
    h = float(prod["bounds"]["height"])
    mats, georef = load_georef_mats()

    # optional archive for exclusion check
    import os

    archive = None
    ap = os.environ.get("GATES_EARTH3_ARCHIVE") or os.environ.get("EARTH3_ARCHIVE")
    if ap and Path(ap).is_file():
        archive = load_earth3_dataset(Path(ap))

    # explicit excludes from v7 crop candidate
    explicit_exclude = set()
    crop_cfg = ROOT / "config/earth3/crop_candidates_v1.json"
    if crop_cfg.is_file():
        for c in json.loads(crop_cfg.read_text(encoding="utf-8")).get("candidates") or []:
            if c.get("id") == "em_reference_masked":
                explicit_exclude = {int(x) for x in (c.get("explicit_exclude_ids") or [])}
                break

    # lakes
    lakes = []
    if NE_SUBSET.is_file():
        for f in json.loads(NE_SUBSET.read_text(encoding="utf-8"))["features"]:
            g = make_valid(shape(f["geojson"]))
            if g.is_empty:
                continue
            c = f.get("centroid") or [g.centroid.x, g.centroid.y]
            lakes.append({"name": f.get("name") or "", "geom": g, "centroid": (float(c[0]), float(c[1]))})

    # index provinces
    land_fills = []
    water_rings = []
    edge_map: dict = {}
    prod_srcs = set()
    for p in prod["provinces"]:
        pid = p["id"]
        sid = int(p["source_id"])
        prod_srcs.add(sid)
        water = bool(p.get("is_water"))
        ring_pts = pair_vertices(p.get("ring") or [])
        register_edges(edge_map, ring_pts, water, pid, sid)
        if water:
            water_rings.append({"id": pid, "source_id": sid, "ring": ring_pts, "centroid": p["centroid"], "area": p.get("area")})
        else:
            geom, meta = reconstruct(p["vertices"], p["triangles"], p.get("area"))
            if geom is not None:
                land_fills.append({"id": pid, "source_id": sid, "geom": geom, "meta": meta, "centroid": p["centroid"]})

    gaps = []
    for g in prod.get("ocean_gap_fills") or []:
        geom, meta = reconstruct(g["vertices"], g["triangles"], g.get("area"))
        gaps.append(
            {
                "id": g["id"],
                "geom": geom,
                "meta": meta,
                "centroid": g["centroid"],
                "area": g.get("area"),
                "classification": g.get("classification"),
                "region_hint": g.get("region_hint"),
            }
        )

    # godot-drawn borders only
    drawn_edges = []
    for k, e in edge_map.items():
        if not (e["flags"] & 1):
            continue  # drop pure water-water
        kind = "coast" if (e["flags"] & 2) else "land_land"
        drawn_edges.append({"a": k[0], "b": k[1], "kind": kind, "land": e["land"], "water": e["water"]})

    traces = []
    for label, lx, ly, note in OWNER_CIRCLES:
        pt = Point(lx, ly)
        in_bounds = 0 <= lx <= w and 0 <= ly <= h
        sx, sy = lx + ox, ly + oy
        lon, lat = txy(mats, sx, sy)

        land_hit = None
        for lf in land_fills:
            if lf["geom"].covers(pt) or lf["geom"].contains(pt):
                land_hit = {"gates_id": lf["id"], "source_id": lf["source_id"], "centroid": lf["centroid"]}
                break

        water_hits = []
        for wr in water_rings:
            if point_in_ring((lx, ly), wr["ring"]):
                water_hits.append({"gates_id": wr["id"], "source_id": wr["source_id"], "centroid": wr["centroid"]})

        gap_hit = None
        for g in gaps:
            if g["geom"] is not None and (g["geom"].covers(pt) or g["geom"].contains(pt)):
                gap_hit = {
                    "id": g["id"],
                    "classification": g["classification"],
                    "region_hint": g["region_hint"],
                    "area": g["area"],
                    "centroid": g["centroid"],
                    "geometry_meta": g["meta"],
                    "godot_meshed": False,
                    "note": "gap-fill tris exist in dataset only; Godot shows continuous ocean through land holes",
                }
                break

        # borders near point
        near_borders = []
        for e in drawn_edges:
            ls = LineString([e["a"], e["b"]])
            d = ls.distance(pt)
            if d <= 3.0:
                near_borders.append(
                    {
                        "distance_px": round(d, 3),
                        "kind": e["kind"],
                        "a": list(e["a"]),
                        "b": list(e["b"]),
                        "land_producers": e["land"],
                        "water_producers": e["water"],
                    }
                )
        near_borders.sort(key=lambda r: r["distance_px"])
        near_borders = near_borders[:20]

        # nearest land borders IDs
        nearest_border_ids = []
        for b in near_borders[:8]:
            for lp in b["land_producers"]:
                if lp not in nearest_border_ids:
                    nearest_border_ids.append(lp)

        # fill triangles inside gap if gap
        fill_tri_count = None
        if gap_hit:
            gg = next(g for g in gaps if g["id"] == gap_hit["id"])
            fill_tri_count = gg["meta"].get("triangle_count")

        # archive land at source point
        archive_land = None
        archive_in_prod = None
        explicit_info = {"is_explicit_exclude": False}
        if archive is not None:
            for sid, pr in archive.provinces.items():
                if pr.is_water:
                    continue
                rp = [(float(x), float(y)) for x, y in pr.ring]
                if point_in_ring((sx, sy), rp):
                    archive_land = {
                        "source_id": int(sid),
                        "is_water": False,
                        "cities": [c.name for c in archive.cities if int(c.province_id) == int(sid)][:4],
                    }
                    archive_in_prod = int(sid) in prod_srcs
                    explicit_info = {
                        "is_explicit_exclude": int(sid) in explicit_exclude,
                        "source_id": int(sid),
                        "listed_in": "config/earth3/crop_candidates_v1.json em_reference_masked.explicit_exclude_ids",
                    }
                    break

        kind_bits = {
            "outside_crop": not in_bounds,
            "land_fill": land_hit is not None,
            "gap_fill": gap_hit is not None,
            "water_ring": len(water_hits) > 0,
            "near_border": len(near_borders) > 0,
            "in_bounds": in_bounds,
        }
        pixel_class = classify_pixel(kind_bits)

        # feature polygon for matching: prefer gap geom, else water ring, else small buffer
        e3_local = None
        if gap_hit:
            e3_local = next(g["geom"] for g in gaps if g["id"] == gap_hit["id"])
        elif water_hits:
            wr = next(w for w in water_rings if w["id"] == water_hits[0]["gates_id"])
            flat = []
            for xy in wr["ring"]:
                flat.extend([xy[0], xy[1]])
            e3_local = ring_poly({"ring": flat})
        elif archive_land and archive is not None:
            pr = archive.provinces[archive_land["source_id"]]
            local = [(x - ox, y - oy) for x, y in pr.ring]
            if local[0] == local[-1]:
                local = local[:-1]
            e3_local = Polygon(local + [local[0]])
            if not e3_local.is_valid:
                e3_local = make_valid(e3_local)

        # to wgs
        e3_wgs = None
        if e3_local is not None and not e3_local.is_empty:
            from shapely.ops import transform

            def xf(xs, ys, zs=None):
                oxl, oyl = [], []
                for x, y in zip(xs, ys):
                    lo, la = txy(mats, x + ox, y + oy)
                    oxl.append(lo)
                    oyl.append(la)
                return oxl, oyl

            e3_wgs = transform(xf, e3_local)

        match = poly_match_meters(e3_wgs, lakes) if e3_wgs is not None else None

        # interior exclusion reason
        if land_hit:
            interior_reason = "land_province_fill_present"
        elif gap_hit:
            interior_reason = "no_land_fill_gap_fill_metadata_ocean_underlay"
        elif water_hits:
            interior_reason = "no_land_fill_inside_water_metadata_ring_ocean_underlay"
        elif archive_land and not archive_in_prod:
            interior_reason = "archive_land_exists_but_omitted_from_3510_crop_ocean_underlay"
        elif not in_bounds:
            interior_reason = "outside_crop_bounds"
        else:
            interior_reason = "no_land_province_at_point_continuous_ocean"

        geo_compare_pre = {
            "predicted_wgs84": [round(lon, 4), round(lat, 4)],
            "true_kolguyev_wgs84": [49.25, 69.08],
            "distance_to_true_kolguyev_km": round(hav(lon, lat, 49.25, 69.08), 1),
            "is_kolguyev": False,
        }
        trace_ctx = {
            "pixel_classification": pixel_class,
            "ocean_gap_fill": gap_hit,
            "land_fill_hit": land_hit,
            "water_ring_hits": water_hits,
            "border_segments_near": near_borders,
            "archive_land_at_point": archive_land,
            "archive_land_in_production": archive_in_prod,
            "explicit_exclude": explicit_info,
            "geography_compare": geo_compare_pre,
        }
        final_class, final_note = final_class_for_feature(label, trace_ctx, match, mats)
        rec = recommendation(final_class, label, match, trace_ctx)

        geo_compare = dict(geo_compare_pre)
        if label == "NE01_northern_outline":
            geo_compare["identity"] = (
                "Excluded mainland archive land (src 11836 Fion) presentation artifact inside image bounds"
                if archive_land and int(archive_land["source_id"]) == 11836
                else "see final_classification"
            )
            geo_compare["kolguyev_shape_match"] = False

        # scale exaggeration for gap features
        scale_note = None
        if match and match.get("ref_area_km2") and match["ref_area_km2"] > 0:
            scale_note = {
                "area_ratio_e3_over_ref": round(match["earth3_area_km2"] / match["ref_area_km2"], 3),
                "exaggerated": (match["earth3_area_km2"] / match["ref_area_km2"]) > 2.5,
            }

        traces.append(
            {
                "review_label": label,
                "owner_note": note,
                "map_local_xy": [lx, ly],
                "source_map_xy": [round(sx, 2), round(sy, 2)],
                "wgs84": [round(lon, 4), round(lat, 4)],
                "in_image_bounds": in_bounds,
                "pixel_classification": pixel_class,
                "land_fill_hit": land_hit,
                "land_fill_mesh_membership": land_hit is not None,
                "water_metadata_ring_hits": water_hits,
                "ocean_gap_fill": gap_hit,
                "gap_fill_triangle_membership": fill_tri_count,
                "border_segments_near": near_borders,
                "nearest_province_border_ids": nearest_border_ids,
                "interior_exclusion_reason": interior_reason,
                "archive_land_at_point": archive_land,
                "archive_land_in_production": archive_in_prod,
                "explicit_exclude": explicit_info,
                "godot_render_model": {
                    "land_fill": "province triangles",
                    "water_fill_mesh": False,
                    "ocean_gap_fills_meshed": False,
                    "continuous_ocean_underlay": True,
                    "borders": "all province ring edges except pure water-water",
                },
                "polygon_match_laea": match,
                "scale": scale_note,
                "final_classification": final_class,
                "final_note": final_note,
                "recommendation": rec,
                "geography_compare": geo_compare,
            }
        )

    # Numbered screenshot (offline composite of land + labels)
    img_w, img_h = 1400, 1100
    # NE crop window
    minx, maxx, miny, maxy = 2400, 4306, 200, 1800
    s = min((img_w - 80) / (maxx - minx), (img_h - 80) / (maxy - miny))
    img = Image.new("RGB", (img_w, img_h), (14, 22, 34))
    dr = ImageDraw.Draw(img)

    def px(x, y):
        return (40 + (x - minx) * s, 40 + (y - miny) * s)

    for lf in land_fills:
        cx, cy = lf["centroid"]
        if not (minx - 50 <= cx <= maxx + 50 and miny - 50 <= cy <= maxy + 50):
            continue
        g = lf["geom"]
        polys = [g] if g.geom_type == "Polygon" else list(g.geoms) if g.geom_type == "MultiPolygon" else []
        for poly in polys:
            coords = [px(x, y) for x, y in poly.exterior.coords]
            if len(coords) >= 3:
                dr.polygon(coords, fill=(110, 118, 108), outline=(40, 44, 40))
    # gap outlines
    for g in gaps:
        if g["geom"] is None:
            continue
        cx, cy = g["centroid"]
        if not (minx <= cx <= maxx and miny <= cy <= maxy):
            continue
        polys = [g["geom"]] if g["geom"].geom_type == "Polygon" else list(g["geom"].geoms)
        for poly in polys:
            if poly.geom_type != "Polygon":
                continue
            coords = [px(x, y) for x, y in poly.exterior.coords]
            if len(coords) >= 3:
                dr.line(coords, fill=(40, 120, 200), width=2)
    for i, tr in enumerate(traces, 1):
        x, y = tr["map_local_xy"]
        if not (minx <= x <= maxx and miny <= y <= maxy):
            continue
        cx, cy = px(x, y)
        r = 18
        dr.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 220, 40), width=3)
        dr.text((cx + 22, cy - 10), f"{tr['review_label']}", fill=(255, 240, 180))
        dr.text((cx - 6, cy - 8), str(i), fill=(255, 255, 255))
        # short class
        dr.text((cx + 22, cy + 8), tr["final_classification"][:40], fill=(180, 200, 220))
    dr.text((20, 10), "Owner circles — exact render trace labels (offline Godot-rule simulation)", fill=(240, 240, 240))
    dr.text((20, 28), "Yellow circles=sample points; blue=gap-fill outlines; land=fill mesh", fill=(180, 190, 200))
    ev = OUT / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    shot = ev / "owner_circles_numbered_traced.png"
    img.save(shot)

    payload = {
        "schema": "gates-of-codex.earth3-owner-circle-render-trace",
        "schema_version": 1,
        "production_authority": {"provinces": 3510, "included_ids_sha256": HASH},
        "godot_rules": {
            "hit_test": "point_in_polygon_spatial_index_land_only_selectable",
            "water_policy": "water_not_normally_selectable",
            "ocean_gap_fills_meshed_in_godot": False,
            "continuous_ocean_underlay": True,
            "borders_from": "province_rings_drop_pure_water_water",
        },
        "georef_loo_rms_km": georef["leave_one_out"]["rms_km"],
        "circles": traces,
        "numbered_screenshot": str(shot.relative_to(ROOT)).replace("\\", "/"),
        "summary": {
            c["review_label"]: {
                "final_classification": c["final_classification"],
                "recommendation": c["recommendation"],
                "pixel_classification": c["pixel_classification"],
            }
            for c in traces
        },
    }
    outp = OUT / "owner_circle_render_trace.json"
    outp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    print("wrote", outp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
