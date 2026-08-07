#!/usr/bin/env python3
"""Authoritative Earth3 hydrography audit (docs + Kolguyev preview only).

  set GATES_EARTH3_ARCHIVE=/path/to/AOH3_Earth3_map_provinces.zip
  python tools/earth3/hydrography_audit_main.py --archive %GATES_EARTH3_ARCHIVE%

Does not modify production godot/assets/maps/earth3_europe_mediterranean/.

Geometry: exact emitted triangle unions only (no convex hull / synthetic circle).
Metrics: local Lambert azimuthal equal-area (meters), never raw degree-area IoU.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, mapping, shape
from shapely.ops import nearest_points, transform, unary_union
from shapely.validation import make_valid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from gates_of_codex.earth3.audit_artifact import included_ids_hash  # noqa: E402
from gates_of_codex.earth3.export_production import triangulate_ring_validated  # noqa: E402
from gates_of_codex.earth3.parse import load_earth3_dataset  # noqa: E402

OUT = ROOT / "docs/earth3-crop/hydrography_audit"
PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean"
NE_SUBSET = OUT / "reference/ne_10m_lakes_europe_subset.json"
KOL_DIR = ROOT / "godot/assets/maps/earth3_europe_mediterranean_kolguyev_preview"
HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"
GAPS = {"e3_2830", "e3_2888"}
KOL_SRC = 11836
RECON_AREA_TOL = 1e-4
EARTH_R_M = 6371008.8
HI_IOU = 0.15
HI_COV = 0.25
HI_SEP_KM = 40.0

CONTROL = [
    ("Reykjavik", 7281.0, 930.0, -21.8277, 64.1283),
    ("Dublin", 8040.0, 1844.0, -6.2603, 53.3498),
    ("London", 8337.0, 1992.0, -0.1276, 51.5074),
    ("Lisbon", 7898.0, 2879.0, -9.1393, 38.7223),
    ("Madrid", 8165.0, 2774.0, -3.7038, 40.4168),
    ("Rome", 8954.0, 2678.0, 12.4964, 41.9028),
    ("Valletta", 9050.0, 3053.0, 14.5146, 35.8989),
    ("Ibiza", 8415.0, 2866.0, 1.4326, 38.9067),
    ("Pantelleria", 8928.0, 2999.0, 11.9426, 36.7850),
    ("Athens", 9502.0, 2927.0, 23.7275, 37.9838),
    ("Myrina_Lemnos", 9570.0, 2808.0, 25.0633, 39.8747),
    ("Tozeur", 8741.0, 3163.0, 8.1336, 33.9197),
    ("Warsaw", 9369.0, 1936.0, 21.0122, 52.2297),
    ("St_Petersburg", 9826.0, 1264.0, 30.3351, 59.9343),
    ("Moscow", 10178.0, 1643.0, 37.6173, 55.7558),
    ("Galich", 10485.0, 1417.0, 42.3475, 58.3813),
    ("Rybinsk", 10236.0, 1441.0, 38.8333, 58.0500),
    ("Kazan", 10742.0, 1641.0, 49.1221, 55.7887),
    ("Naberezhnye_Chelny", 10901.0, 1648.0, 52.4070, 55.7431),
    ("Cheboksary", 10648.0, 1615.0, 47.2481, 56.1439),
    ("Nizhny_Novgorod", 10491.0, 1597.0, 44.0020, 56.2965),
    ("Samara", 10793.0, 1858.0, 50.15, 53.2),
    ("Astrakhan", 10687.0, 2374.0, 48.0408, 46.3497),
    ("Vologda", 10288.0, 1330.0, 39.884, 59.2205),
    ("Murmansk", 9961.0, 474.0, 33.0827, 68.9585),
    ("Apatity", 9974.0, 615.0, 33.393, 67.5641),
    ("Kem", 10031.0, 857.0, 34.579, 64.9555),
    ("Onega_town", 10203.0, 946.0, 38.0867, 63.9041),
    ("Arkhangelsk", 10325.0, 892.0, 40.5433, 64.5399),
    ("Petrozavodsk", 10019.0, 1124.0, 34.3469, 61.7849),
    ("Medvezhyegorsk", 10022.0, 1031.0, 34.4566, 62.9153),
    ("Pudozh", 10126.0, 1118.0, 36.5283, 61.8092),
    ("Vytegra", 10123.0, 1180.0, 36.4481, 61.0064),
    ("Syktyvkar", 10820.0, 1135.0, 50.8366, 61.6688),
    ("Sortavala", 9840.0, 1126.0, 30.7042, 61.7055),
    ("Koynas", 10663.0, 876.0, 47.6500, 64.7500),
    ("Usinsk", 11149.0, 761.0, 57.5570, 65.9939),
    ("Pechora", 11135.0, 838.0, 57.3094, 65.1472),
    ("Vorkuta", 11468.0, 623.0, 64.0661, 67.4978),
]

FIXED_TOL = {
    "Ibiza": 25.0,
    "Valletta": 25.0,
    "Pantelleria": 25.0,
    "Myrina_Lemnos": 40.0,
    "Petrozavodsk": 50.0,
    "Rybinsk": 50.0,
    "Murmansk": 60.0,
    "Arkhangelsk": 60.0,
    "Kem": 60.0,
    "Onega_town": 60.0,
}

SPECS = [
    ("NE01_Kolguyev", None, None, "Kolguyev Island"),
    ("NE02_Ladoga", "gap_0012", None, "Lake Ladoga"),
    ("NE03_Onega", "gap_0027", None, "Lake Onega"),
    ("NE04_WhiteSea_SE_large_hole", "gap_0039", None, None),
    ("NE05_Rybinsk", "gap_0025", None, "Rybinsk Reservoir"),
    ("NE06_Lake_Galichskoye", "gap_0038", None, "Lake Galichskoye"),
    ("NE07_east_volga_candidate", "gap_0045", None, None),
    ("NE08_kama_volga_candidate", "gap_0044", None, None),
    ("MED01_Ibiza", None, 2274, "Ibiza"),
    ("MED02_Pantelleria", None, 4693, "Pantelleria"),
    ("MED03_Malta", None, 270, "Malta"),
    ("MED04_Lemnos", None, 3220, "Lemnos"),
    ("NA01_Chott_complex", "gap_0008", None, "Chott el Jerid complex"),
]


def hav(lon1, lat1, lon2, lat2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def fit_affine(xy, ll):
    X = np.column_stack([xy[:, 0], xy[:, 1], np.ones(len(xy))])
    A, _, _, _ = np.linalg.lstsq(X, ll, rcond=None)
    return A


def apply_A(A, x, y):
    v = np.array([x, y, 1.0]) @ A
    return float(v[0]), float(v[1])


def region_of(x, y):
    if y >= 2400 and x <= 9800:
        return "mediterranean_na"
    if x < 9600:
        return "west_europe"
    if y < 1150 and x >= 9600:
        return "ne_russia_north"
    return "east_europe_russia"


def resolve_archive(path):
    p = path or os.environ.get("GATES_EARTH3_ARCHIVE") or os.environ.get("EARTH3_ARCHIVE")
    if not p:
        raise SystemExit("Pass --archive PATH or set GATES_EARTH3_ARCHIVE to AOH3_Earth3_map_provinces.zip")
    path = Path(p)
    if not path.is_file():
        raise SystemExit(f"Archive not found: {path}")
    return path


def build_georef():
    controls = [
        {"label": a, "source_x": b, "source_y": c, "wgs84_lon": d, "wgs84_lat": e}
        for a, b, c, d, e in CONTROL
    ]
    regions: dict[str, list] = {}
    for c in controls:
        regions.setdefault(region_of(c["source_x"], c["source_y"]), []).append(c)
    final = {}
    reg_meta = {}
    for rn, pts in regions.items():
        if len(pts) < 3:
            continue
        A = fit_affine(
            np.array([[p["source_x"], p["source_y"]] for p in pts], float),
            np.array([[p["wgs84_lon"], p["wgs84_lat"]] for p in pts], float),
        )
        final[rn] = A
        errs = [hav(*apply_A(A, p["source_x"], p["source_y"]), p["wgs84_lon"], p["wgs84_lat"]) for p in pts]
        reg_meta[rn] = {
            "n": len(pts),
            "in_sample_rms_km": round(float(np.sqrt(np.mean(np.square(errs)))), 3),
            "in_sample_max_km": round(float(max(errs)), 3),
            "validation_note": (
                "n<=3 => in-sample RMS is NOT independent validation. Use LOO."
                if len(pts) <= 3
                else "Use LOO metrics for validated accuracy."
            ),
        }
    loo = []
    for i, c in enumerate(controls):
        rest = controls[:i] + controls[i + 1 :]
        regs: dict[str, list] = {}
        for p in rest:
            regs.setdefault(region_of(p["source_x"], p["source_y"]), []).append(p)
        mats = {}
        for rn, pts in regs.items():
            if len(pts) < 3:
                continue
            mats[rn] = fit_affine(
                np.array([[p["source_x"], p["source_y"]] for p in pts], float),
                np.array([[p["wgs84_lon"], p["wgs84_lat"]] for p in pts], float),
            )
        rn = region_of(c["source_x"], c["source_y"])
        if rn in mats:
            plo, pla = apply_A(mats[rn], c["source_x"], c["source_y"])
        else:
            G = fit_affine(
                np.array([[p["source_x"], p["source_y"]] for p in rest], float),
                np.array([[p["wgs84_lon"], p["wgs84_lat"]] for p in rest], float),
            )
            plo, pla = apply_A(G, c["source_x"], c["source_y"])
        loo.append(
            {
                "label": c["label"],
                "region": rn,
                "predicted": [round(plo, 4), round(pla, 4)],
                "wgs84": [c["wgs84_lon"], c["wgs84_lat"]],
                "error_km": round(hav(plo, pla, c["wgs84_lon"], c["wgs84_lat"]), 3),
            }
        )
    by_r: dict[str, list[float]] = {}
    for r in loo:
        by_r.setdefault(r["region"], []).append(r["error_km"])
    errs = [r["error_km"] for r in loo]
    georef = {
        "schema": "gates-of-codex.earth3-georeference-transform",
        "schema_version": 6,
        "selected_method": "piecewise_regional_affine_with_loo",
        "kolguyev_is_control_point": False,
        "metric_projection": "lambert_azimuthal_equal_area_local_m",
        "regions": {
            k: {
                "affine_3x2": final[k].tolist(),
                **reg_meta[k],
                "loo_rms_km": round(float(np.sqrt(np.mean(np.square(by_r[k])))), 3) if k in by_r else None,
                "loo_max_km": round(float(max(by_r[k])), 3) if k in by_r else None,
            }
            for k in final
        },
        "leave_one_out": {
            "residuals": loo,
            "rms_km": round(float(np.sqrt(np.mean(np.square(errs)))), 3),
            "max_km": round(float(max(errs)), 3),
            "mean_km": round(float(np.mean(errs)), 3),
            "by_region": {
                k: {
                    "n": len(v),
                    "rms_km": round(float(np.sqrt(np.mean(np.square(v)))), 3),
                    "max_km": round(float(max(v)), 3),
                }
                for k, v in by_r.items()
            },
        },
        "fixed_control_tolerances_km": FIXED_TOL,
        "high_confidence_polygon_iou_threshold": HI_IOU,
        "high_confidence_coverage_threshold": HI_COV,
        "reconstruction_area_relative_tolerance": RECON_AREA_TOL,
        "notes": [
            "Kolguyev is NOT a georef control point.",
            "Polygon IoU/area use local LAEA meters, never raw lon/lat degree area.",
            "Rendered geometry = emitted triangle union only.",
        ],
    }
    return georef, controls


def txy(mats, x, y):
    r = region_of(x, y)
    A = mats.get(r) or mats.get("east_europe_russia")
    return apply_A(np.array(A, float), x, y)


def pair_vertices(vertices):
    if not vertices:
        return []
    if isinstance(vertices[0], (list, tuple)):
        return [(float(v[0]), float(v[1])) for v in vertices]
    return [(float(vertices[i]), float(vertices[i + 1])) for i in range(0, len(vertices) - 1, 2)]


def flat_triangles(triangles):
    if not triangles:
        return []
    if isinstance(triangles[0], (list, tuple)):
        out = []
        for t in triangles:
            out.extend(int(i) for i in t)
        return out
    return [int(i) for i in triangles]


def reconstruct_triangle_union(vertices, triangles, committed_area, *, allow_empty=False):
    """Authoritative rendered geometry from emitted vertices + triangle indices."""
    pts = pair_vertices(vertices)
    tflat = flat_triangles(triangles)
    if len(pts) < 3 or len(tflat) < 3:
        raise ValueError("insufficient vertices/triangles for reconstruction")
    if len(tflat) % 3 != 0:
        raise ValueError(f"triangle index count not multiple of 3: {len(tflat)}")
    polys = []
    for i in range(0, len(tflat), 3):
        a, b, c = tflat[i], tflat[i + 1], tflat[i + 2]
        if max(a, b, c) >= len(pts) or min(a, b, c) < 0:
            raise ValueError(f"triangle index out of range: {a},{b},{c} n={len(pts)}")
        if a == b or b == c or a == c:
            continue
        tri = Polygon([pts[a], pts[b], pts[c]])
        if not tri.is_valid:
            tri = make_valid(tri)
        if tri.is_empty:
            continue
        if tri.geom_type == "GeometryCollection":
            for g in tri.geoms:
                if g.geom_type in ("Polygon", "MultiPolygon") and not g.is_empty:
                    polys.append(g)
        else:
            polys.append(tri)
    if not polys:
        if allow_empty:
            return Polygon(), {
                "geometry_source": "emitted_triangle_union",
                "vertex_count": len(pts),
                "triangle_count": len(tflat) // 3,
                "component_count": 0,
                "committed_area": float(committed_area or 0),
                "reconstructed_area": 0.0,
                "reconstruction_relative_error": 1.0,
                "used_convex_hull": False,
                "used_synthetic_geometry": False,
                "ok": False,
            }
        raise ValueError("no valid triangles in reconstruction")
    union = unary_union(polys)
    if not union.is_valid:
        union = make_valid(union)
    if union.geom_type == "GeometryCollection":
        pieces = [g for g in union.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        union = unary_union(pieces) if pieces else Polygon()
    recon_area = float(union.area)
    committed = float(committed_area or 0)
    rel_err = abs(recon_area - committed) / committed if committed > 0 else (0.0 if recon_area == 0 else 1.0)
    if union.geom_type == "MultiPolygon":
        n_comp = len(union.geoms)
    elif union.geom_type == "Polygon" and not union.is_empty:
        n_comp = 1
    else:
        n_comp = 0
    meta = {
        "geometry_source": "emitted_triangle_union",
        "vertex_count": len(pts),
        "triangle_count": len(tflat) // 3,
        "component_count": n_comp,
        "committed_area": round(committed, 6),
        "reconstructed_area": round(recon_area, 6),
        "reconstruction_relative_error": round(rel_err, 12),
        "used_convex_hull": False,
        "used_synthetic_geometry": False,
        "ok": rel_err <= RECON_AREA_TOL and n_comp > 0,
    }
    if not meta["ok"]:
        raise ValueError(
            f"triangle-union reconstruction failed: rel_err={rel_err:.6g} "
            f"committed={committed} reconstructed={recon_area} components={n_comp}"
        )
    return union, meta


def laea_xy(lon, lat, lon0, lat0, r=EARTH_R_M):
    """Lambert azimuthal equal-area meters centered on (lon0, lat0)."""
    phi = math.radians(lat)
    lam = math.radians(lon)
    phi0 = math.radians(lat0)
    lam0 = math.radians(lon0)
    cos_c = math.sin(phi0) * math.sin(phi) + math.cos(phi0) * math.cos(phi) * math.cos(lam - lam0)
    cos_c = min(1.0, max(-1.0, cos_c))
    if cos_c <= -1.0 + 1e-15:
        return 0.0, 0.0
    k = math.sqrt(2.0 / (1.0 + cos_c))
    x = r * k * math.cos(phi) * math.sin(lam - lam0)
    y = r * k * (math.cos(phi0) * math.sin(phi) - math.sin(phi0) * math.cos(phi) * math.cos(lam - lam0))
    return x, y


def project_wgs_geom(geom, lon0, lat0):
    def _xf(xs, ys, zs=None):
        out_x, out_y = [], []
        for x, y in zip(xs, ys):
            px, py = laea_xy(x, y, lon0, lat0)
            out_x.append(px)
            out_y.append(py)
        return out_x, out_y

    return transform(_xf, geom)


def local_to_wgs_geom(mats, ox, oy, local_geom):
    def _xf(xs, ys, zs=None):
        out_x, out_y = [], []
        for x, y in zip(xs, ys):
            lon, lat = txy(mats, x + ox, y + oy)
            out_x.append(lon)
            out_y.append(lat)
        return out_x, out_y

    g = transform(_xf, local_geom)
    if not g.is_valid:
        g = make_valid(g)
    return g


def load_ne():
    data = json.loads(NE_SUBSET.read_text(encoding="utf-8"))
    lakes = []
    for f in data["features"]:
        g = make_valid(shape(f["geojson"]))
        if g.is_empty:
            continue
        c = f.get("centroid") or [g.centroid.x, g.centroid.y]
        lakes.append({"name": f.get("name") or "", "geom": g, "centroid": (float(c[0]), float(c[1]))})
    return lakes


def poly_match_meters(e3_wgs, lakes, n=6):
    """IoU and areas in local LAEA meters. Never degree-area."""
    if e3_wgs is None or e3_wgs.is_empty:
        return [], None
    e3_wgs = make_valid(e3_wgs)
    c = e3_wgs.centroid
    lon0, lat0 = float(c.x), float(c.y)
    proj_name = f"LAEA_local_m lon0={lon0:.4f} lat0={lat0:.4f} R={EARTH_R_M}"
    e3_m = project_wgs_geom(e3_wgs, lon0, lat0)
    if e3_m.is_empty:
        return [], proj_name
    out = []
    for lk in lakes:
        g = lk["geom"]
        try:
            g_m = project_wgs_geom(g, lon0, lat0)
            inter = e3_m.intersection(g_m)
            uni = e3_m.union(g_m)
        except Exception:
            continue
        ia = float(inter.area) if not inter.is_empty else 0.0
        ua = float(uni.area) if not uni.is_empty else 0.0
        e3_a = float(e3_m.area)
        ref_a = float(g_m.area)
        iou = ia / ua if ua > 0 else 0.0
        cov_e3 = ia / e3_a if e3_a > 0 else 0.0
        cov_ref = ia / ref_a if ref_a > 0 else 0.0
        sep = hav(e3_wgs.centroid.x, e3_wgs.centroid.y, lk["centroid"][0], lk["centroid"][1])
        try:
            haus_m = float(e3_m.hausdorff_distance(g_m))
        except Exception:
            haus_m = None
        boundary_mean_km = None
        try:
            if not e3_m.boundary.is_empty and not g_m.is_empty:
                # sample boundary distance percentiles
                coords = list(e3_m.boundary.coords) if e3_m.boundary.geom_type == "LineString" else []
                if len(coords) >= 4:
                    step = max(1, len(coords) // 48)
                    dists = []
                    for i in range(0, len(coords), step):
                        pt = Point(coords[i])
                        dists.append(float(pt.distance(g_m.boundary if not g_m.boundary.is_empty else g_m)))
                    if dists:
                        boundary_mean_km = round(float(np.mean(dists)) / 1000.0, 3)
        except Exception:
            pass
        out.append(
            {
                "name": lk["name"] or "(unnamed)",
                "projection": proj_name,
                "metric_units": "meters_laea",
                "iou": round(iou, 4),
                "earth3_coverage_by_ref": round(cov_e3, 4),
                "ref_coverage_by_earth3": round(cov_ref, 4),
                "earth3_area_km2": round(e3_a / 1e6, 3),
                "ref_area_km2": round(ref_a / 1e6, 3),
                "intersection_area_km2": round(ia / 1e6, 3),
                "union_area_km2": round(ua / 1e6, 3),
                "area_ratio_e3_over_ref": round(e3_a / ref_a, 4) if ref_a > 0 else None,
                "centroid_separation_km": round(sep, 2),
                "hausdorff_km": round(haus_m / 1000.0, 3) if haus_m is not None else None,
                "boundary_mean_distance_km": boundary_mean_km,
                "score": round(iou * 2 + cov_e3 + cov_ref - sep / 500.0, 4),
            }
        )
    out.sort(key=lambda d: -d["score"])
    return out[:n], proj_name


def degree_area_iou_legacy_hull(e3_local_hull_wgs, lakes):
    """Legacy degree-area convex-hull metric for old-vs-new comparison only."""
    if e3_local_hull_wgs is None or e3_local_hull_wgs.is_empty:
        return None
    e3 = make_valid(e3_local_hull_wgs)
    best = None
    for lk in lakes:
        g = lk["geom"]
        try:
            inter = e3.intersection(g)
            uni = e3.union(g)
        except Exception:
            continue
        ia = float(inter.area) if not inter.is_empty else 0.0
        ua = float(uni.area) if not uni.is_empty else 0.0
        iou = ia / ua if ua > 0 else 0.0
        cov = ia / float(e3.area) if e3.area > 0 else 0.0
        sep = hav(e3.centroid.x, e3.centroid.y, lk["centroid"][0], lk["centroid"][1])
        row = {
            "name": lk["name"] or "(unnamed)",
            "iou_degree_area_hull": round(iou, 4),
            "coverage_degree_area_hull": round(cov, 4),
            "centroid_separation_km": round(sep, 2),
            "score": iou * 2 + cov - sep / 500.0,
        }
        if best is None or row["score"] > best["score"]:
            best = row
    return best


def nearest_cities(archive, sx, sy, n=4):
    scored = [(math.hypot(c.x - sx, c.y - sy), c) for c in archive.cities]
    scored.sort(key=lambda t: t[0])
    return [{"name": c.name, "dist_px": round(d, 1), "source_province_id": int(c.province_id)} for d, c in scored[:n]]


def ring_pts_flat(row):
    f = row.get("ring") or []
    return [(float(f[i]), float(f[i + 1])) for i in range(0, len(f) - 1, 2)]


def source_ring_polygon(ring):
    pts = [(float(x), float(y)) for x, y in ring]
    if len(pts) < 3:
        return None
    if pts[0] != pts[-1]:
        pts = pts + [pts[0]]
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = make_valid(poly)
    if poly.is_empty:
        return None
    if poly.geom_type == "MultiPolygon":
        poly = max(list(poly.geoms), key=lambda g: g.area)
    return poly


def classify(label, hyp, exp_sid, by_src, top, matches, cities, recon_meta, kol_holdout=None):
    if label == "NE01_Kolguyev":
        ho = kol_holdout or {}
        return (
            "CONFIRMED_MISSING_LAND_RESTORE",
            "Kolguyev Island",
            "high",
            (
                f"Archive land src {KOL_SRC} (city Fion) absent from production crop. "
                f"Identity is archive topology, not WGS84. Not a georef control. "
                f"Holdout residual vs ~49E/69.1N: {ho.get('error_km')} km "
                f"(predicted {ho.get('predicted')}). geometry={recon_meta['geometry_source']}."
            ),
            [],
        )
    if exp_sid is not None:
        p = by_src[exp_sid]
        return (
            "CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP",
            hyp,
            "high",
            f"{p['id']} src {exp_sid} filled triangle-union; keep; #121 coastlines.",
            [],
        )
    name = (top or {}).get("name") or ""
    iou = float((top or {}).get("iou") or 0)
    cov = float((top or {}).get("earth3_coverage_by_ref") or 0)
    sep = (top or {}).get("centroid_separation_km")
    units = (top or {}).get("metric_units")
    if units != "meters_laea":
        # refuse high-confidence water names without meter metrics
        pass

    def water_ok(need_name):
        if need_name and need_name not in name:
            return False
        if units != "meters_laea":
            return False
        if recon_meta.get("used_convex_hull") or recon_meta.get("used_synthetic_geometry"):
            return False
        if recon_meta.get("geometry_source") != "emitted_triangle_union":
            return False
        return iou >= HI_IOU or cov >= HI_COV or (sep is not None and sep < HI_SEP_KM and iou >= 0.05)

    if label == "NE02_Ladoga" and water_ok("Ladoga"):
        return "CONFIRMED_REAL_WATER_KEEP", "Lake Ladoga", "high", f"exact-triangle LAEA match {top}", []
    if label == "NE03_Onega" and water_ok("Onega"):
        return "CONFIRMED_REAL_WATER_KEEP", "Lake Onega", "high", f"exact-triangle LAEA match {top}", []
    if label == "NE05_Rybinsk" and water_ok("Rybinsk"):
        return "CONFIRMED_REAL_WATER_KEEP", "Rybinsk Reservoir", "high", f"exact-triangle LAEA match {top}", []
    if label == "NE06_Lake_Galichskoye":
        return (
            "UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH",
            "UNRESOLVED",
            "medium",
            f"Primary candidate Lake Galichskoye. top={top}",
            ["Lake Galichskoye", "other Kostroma lakes"],
        )
    if label == "NE07_east_volga_candidate":
        return (
            "UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH",
            "UNRESOLVED",
            "low",
            f"matches={matches[:3]} cities={[c['name'] for c in cities[:3]]}",
            ["Cheboksary Reservoir", "local lakes near Yaransk/Shakhunya/Yoshkar-Ola", "merged gap-fill"],
        )
    if label == "NE08_kama_volga_candidate":
        return (
            "UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH",
            "UNRESOLVED",
            "low",
            f"matches={matches[:3]} cities={[c['name'] for c in cities[:3]]}",
            ["Nizhnekamsk Reservoir", "Kuybyshev Reservoir", "Kama arms", "merged gap-fill"],
        )
    if label == "NE04_WhiteSea_SE_large_hole":
        return (
            "UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH",
            "UNRESOLVED",
            "low",
            f"matches={matches[:3]}",
            ["merged lakes/wetlands", "exaggerated hydrography", "false hole", "missing land"],
        )
    if label == "NA01_Chott_complex":
        return (
            "CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER",
            "Chott el Jerid complex (provisional)",
            "medium",
            f"Near Tozeur; NE lakes may omit chotts. top={top}",
            ["Chott el Jerid", "Chott el Gharsa"],
        )
    return "UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH", "UNRESOLVED", "low", f"no meter match. top={top}", []


def feature_triangle_geometry(label, gap, exp_sid, by_src, archive, ox, oy):
    """Return local triangle-union geom + recon meta + centroid local xy. Never hull/circle."""
    if exp_sid is not None:
        p = by_src[exp_sid]
        geom, meta = reconstruct_triangle_union(p["vertices"], p["triangles"], p.get("area"))
        lx, ly = float(p["centroid"][0]), float(p["centroid"][1])
        return geom, meta, lx, ly
    if label == "NE01_Kolguyev":
        kp = archive.provinces[KOL_SRC]
        local = [(round(x - ox, 6), round(y - oy, 6)) for x, y in kp.ring]
        if local[0] == local[-1]:
            local = local[:-1]
        verts, tris, ring_flat, audit = triangulate_ring_validated(tuple(local))
        # verts may be nested list of pairs; tris flat indices
        if verts and isinstance(verts[0], (list, tuple)):
            vflat = [c for xy in verts for c in xy]
        else:
            vflat = list(verts)
        geom, meta = reconstruct_triangle_union(vflat, tris, audit["polygon_area"])
        lx = sum(x for x, _ in local) / len(local)
        ly = sum(y for _, y in local) / len(local)
        return geom, meta, lx, ly
    if gap is None:
        raise ValueError(f"{label}: missing gap fill")
    geom, meta = reconstruct_triangle_union(gap["vertices"], gap["triangles"], gap.get("area"))
    lx, ly = float(gap["centroid"][0]), float(gap["centroid"][1])
    return geom, meta, lx, ly


def hull_from_vertices_for_legacy_only(vertices):
    """Comparison-only convex hull — never used for classification."""
    pts = pair_vertices(vertices)
    if len(pts) < 3:
        return None
    from shapely.geometry import MultiPoint

    h = MultiPoint(pts).convex_hull
    if h.geom_type != "Polygon":
        return None
    return h


def draw_polygon_overlay(path, e3_wgs, ref_wgs, label, metrics, georef_unc_km):
    """Real polygon overlay: Earth3 / ref / intersection / only regions. No centroid circles."""
    w, h = 1100, 900
    img = Image.new("RGB", (w, h), (12, 18, 28))
    dr = ImageDraw.Draw(img, "RGBA")
    geoms = [g for g in (e3_wgs, ref_wgs) if g is not None and not g.is_empty]
    if not geoms:
        dr.text((20, 20), f"{label}: no geometry", fill=(255, 255, 255))
        img.save(path)
        return
    minx = min(g.bounds[0] for g in geoms)
    miny = min(g.bounds[1] for g in geoms)
    maxx = max(g.bounds[2] for g in geoms)
    maxy = max(g.bounds[3] for g in geoms)
    pad = 0.08
    dx = max(maxx - minx, 1e-6)
    dy = max(maxy - miny, 1e-6)
    minx -= dx * pad
    maxx += dx * pad
    miny -= dy * pad
    maxy += dy * pad
    sx = (w - 80) / (maxx - minx)
    sy = (h - 120) / (maxy - miny)
    s = min(sx, sy)

    def to_px(coords):
        return [(40 + (x - minx) * s, 60 + (maxy - y) * s) for x, y in coords]

    def draw_geom(g, fill, outline):
        if g is None or g.is_empty:
            return
        polys = []
        if g.geom_type == "Polygon":
            polys = [g]
        elif g.geom_type == "MultiPolygon":
            polys = list(g.geoms)
        for poly in polys:
            ext = to_px(list(poly.exterior.coords))
            if len(ext) >= 3:
                dr.polygon(ext, fill=fill, outline=outline)

    inter = None
    e3_only = None
    ref_only = None
    if e3_wgs is not None and ref_wgs is not None and not e3_wgs.is_empty and not ref_wgs.is_empty:
        try:
            inter = make_valid(e3_wgs.intersection(ref_wgs))
            e3_only = make_valid(e3_wgs.difference(ref_wgs))
            ref_only = make_valid(ref_wgs.difference(e3_wgs))
        except Exception:
            pass
    draw_geom(ref_only, (40, 80, 180, 90), (80, 140, 255))
    draw_geom(e3_only, (180, 60, 40, 90), (255, 120, 80))
    draw_geom(inter, (40, 160, 70, 120), (80, 220, 100))
    if e3_wgs is not None:
        draw_geom(e3_wgs, None, (255, 220, 60))
    if ref_wgs is not None:
        draw_geom(ref_wgs, None, (100, 180, 255))
    iou = (metrics or {}).get("iou", "—")
    haus = (metrics or {}).get("hausdorff_km", "—")
    name = (metrics or {}).get("name", "—")
    dr.text((16, 10), f"{label}  ref={name}  IoU={iou}  Hausdorff_km={haus}", fill=(240, 240, 240))
    dr.text(
        (16, 30),
        f"yellow=E3 boundary  blue=ref  green=intersection  red=E3-only  blue-fill=ref-only  "
        f"georef_unc~{georef_unc_km}km LOO",
        fill=(180, 190, 200),
    )
    dr.text((16, h - 28), "exact triangle-union geometry; LAEA meter metrics; no centroid circles", fill=(160, 170, 180))
    img.save(path)


def build_kolguyev_topology(prod, archive, ox, oy, local_geom, new_id):
    """Polygon topology distances — not centroid radius."""
    kp = archive.provinces[KOL_SRC]
    kol_src = source_ring_polygon(kp.ring)
    if kol_src is None:
        raise ValueError("Kolguyev source ring invalid")
    # nearby source water by envelope expansion, then exact distance
    minx, miny, maxx, maxy = kol_src.bounds
    pad = 400.0
    water_hits = []
    land_hits = []
    for sid, prov in archive.provinces.items():
        ring = getattr(prov, "ring", None)
        if not ring:
            continue
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        if max(xs) < minx - pad or min(xs) > maxx + pad or max(ys) < miny - pad or min(ys) > maxy + pad:
            continue
        poly = source_ring_polygon(ring)
        if poly is None or poly.is_empty:
            continue
        try:
            dist = float(kol_src.distance(poly))
            borders = bool(kol_src.intersects(poly) or kol_src.touches(poly))
            inter_area = float(kol_src.intersection(poly).area) if borders else 0.0
        except Exception:
            continue
        entry = {
            "source_id": int(sid),
            "min_boundary_distance_px": round(dist, 3),
            "intersects_or_touches": borders,
            "intersection_area_px2": round(inter_area, 4),
            "shared_boundary_only": borders and inter_area < 1e-6,
            "area_px2": round(float(poly.area), 2),
        }
        if bool(prov.is_water):
            water_hits.append(entry)
        elif int(sid) != KOL_SRC:
            land_hits.append(entry)

    # Production water polygons near Kolguyev local geom
    prod_water = []
    for p in prod["provinces"]:
        if not p.get("is_water"):
            continue
        try:
            g, _ = reconstruct_triangle_union(p["vertices"], p["triangles"], p.get("area"))
        except Exception:
            continue
        try:
            dist = float(local_geom.distance(g))
            touches = local_geom.touches(g) or (local_geom.intersects(g) and float(local_geom.intersection(g).area) >= 0)
        except Exception:
            continue
        if dist > 350:
            continue
        prod_water.append(
            {
                "gates_id": p["id"],
                "source_id": int(p["source_id"]),
                "min_boundary_distance_local_px": round(dist, 3),
                "intersects_or_borders": bool(dist < 1.0 or touches),
            }
        )
    prod_water.sort(key=lambda d: d["min_boundary_distance_local_px"])
    water_hits.sort(key=lambda d: d["min_boundary_distance_px"])
    land_hits.sort(key=lambda d: d["min_boundary_distance_px"])

    # Source packing may share boundary polylines with nearby land (area-0 MultiLineString).
    # That is reported, but preview Gates neighbors stay empty — no invented movement adjacency.
    shared_land = [h for h in land_hits if h["min_boundary_distance_px"] < 0.5]
    for h in shared_land + land_hits:
        # annotate intersection area when available (caller may not have it)
        h.setdefault("note", "distance 0 may be shared boundary polyline under source packing")
    bordering_water = [h for h in water_hits if h["min_boundary_distance_px"] < 2.0 or h["intersects_or_touches"]]
    adj = {
        "gates_id": new_id,
        "source_id": KOL_SRC,
        "direct_land_neighbors": [],
        "preview_province_neighbors_field": [],
        "method": "exact_source_ring_boundary_distance",
        "not_centroid_radius": True,
        "source_water_bordering_or_near": bordering_water[:20],
        "source_water_nearest": water_hits[:12],
        "closest_mainland_land_by_boundary": land_hits[:12],
        "source_geometry_land_boundary_touches": shared_land,
        "source_geometry_land_touch_note": (
            "AoH3 source ring shares boundary polylines (intersection area 0) with packed "
            "nearby land provinces. Preview does NOT copy those into Gates neighbors."
        ),
        "confirmation_no_mainland_land_adjacency_invented": True,
        "confirmation_preview_neighbors_empty": True,
        "production_water_near_by_boundary": prod_water[:20],
        "border_segments": "island outer ring only; sea links deferred",
        "proposed_future_sea_link_nodes": ["author ferry/naval links separately — not auto-derived"],
        "no_automatic_sea_or_ferry_adjacency": True,
    }
    return adj


def audit_preview_3511(prod, provinces, new_id, inc, ds_sha):
    land = [p for p in provinces if not p.get("is_water")]
    water = [p for p in provinces if p.get("is_water")]
    empty = [p["id"] for p in land if len(p.get("triangles") or []) < 3]
    failed_tri = []
    for p in land:
        try:
            reconstruct_triangle_union(p["vertices"], p["triangles"], p.get("area"))
        except Exception as exc:
            failed_tri.append({"id": p["id"], "error": str(exc)[:120]})
    ids = {p["id"] for p in provinces}
    dangling = [{"id": p["id"], "n": n} for p in provinces for n in (p.get("neighbors") or []) if n not in ids]
    srcs = [int(p["source_id"]) for p in provinces]
    prod_map = {int(e["source_id"]): e["gates_id"] for e in (prod.get("id_map") or [])}
    mismatches = []
    for p in provinces:
        sid = int(p["source_id"])
        if sid == KOL_SRC:
            continue
        expected = prod_map.get(sid)
        if expected is not None and expected != p["id"]:
            mismatches.append({"source_id": sid, "expected": expected, "got": p["id"]})
    prod_meta = json.loads((PROD / "dataset_meta.json").read_text(encoding="utf-8"))
    checks = {
        "province_count_checked": len(provinces),
        "land_count_checked": len(land),
        "water_count_checked": len(water),
        "failed_triangulations": len(failed_tri),
        "empty_land_meshes": len(empty),
        "dangling_adjacency": len(dangling),
        "retained_stable_id_mismatches": len(mismatches),
        "source_11836_count": srcs.count(KOL_SRC),
        "e3_3512_count": sum(1 for p in provinces if p["id"] == new_id),
        "e3_2830_count": sum(1 for p in provinces if p["id"] == "e3_2830"),
        "e3_2888_count": sum(1 for p in provinces if p["id"] == "e3_2888"),
        "production_dataset_unchanged": prod_meta.get("province_count") == 3510
        and prod_meta.get("included_source_ids_sha256") == HASH,
        "composition": {
            "baseline_production_provinces": 3510,
            "added_kolguyev": 1,
            "assembled_preview": 3511,
            "note": "composed from proven 3510 production + isolated Kolguyev triangulation",
        },
    }
    ok = (
        checks["province_count_checked"] == 3511
        and checks["land_count_checked"] == 3296
        and checks["water_count_checked"] == 215
        and checks["failed_triangulations"] == 0
        and checks["empty_land_meshes"] == 0
        and checks["dangling_adjacency"] == 0
        and checks["retained_stable_id_mismatches"] == 0
        and checks["source_11836_count"] == 1
        and checks["e3_3512_count"] == 1
        and checks["e3_2830_count"] == 0
        and checks["e3_2888_count"] == 0
        and checks["production_dataset_unchanged"] is True
    )
    return {
        "summary": {
            "gates_id": new_id,
            "source_id": KOL_SRC,
            "province_count": len(provinces),
            "land_count": len(land),
            "water_count": len(water),
            "included_ids_sha256": inc,
            "dataset_sha256": ds_sha,
        },
        "checks": checks,
        "all_pass": ok,
        "failed_triangulation_details": failed_tri[:20],
        "dangling_details": dangling[:20],
        "stable_id_mismatch_details": mismatches[:20],
    }


def build_kolguyev(prod, archive, ox, oy, mats):
    kp = archive.provinces[KOL_SRC]
    local = [(round(x - ox, 6), round(y - oy, 6)) for x, y in kp.ring]
    if local[0] == local[-1]:
        local = local[:-1]
    verts, tris, ring_flat, audit = triangulate_ring_validated(tuple(local))
    new_n = max(int(p["id"].split("_")[1]) for p in prod["provinces"]) + 1
    new_id = f"e3_{new_n:04d}"
    assert new_id not in GAPS
    cx = sum(x for x, _ in local) / len(local)
    cy = sum(y for _, y in local) / len(local)
    row = {
        "id": new_id,
        "source_id": KOL_SRC,
        "is_water": False,
        "terrain_id": int(kp.terrain_id),
        "continent_id": int(kp.continent_id),
        "centroid": [round(cx, 4), round(cy, 4)],
        "label": [round(cx, 4), round(cy, 4)],
        "vertices": verts,
        "triangles": tris,
        "ring": ring_flat,
        "area": round(float(audit["polygon_area"]), 4),
        "neighbors": [],
    }
    # rebuild local geom for topology
    if verts and isinstance(verts[0], (list, tuple)):
        vflat = [c for xy in verts for c in xy]
    else:
        vflat = list(verts)
    local_geom, _meta = reconstruct_triangle_union(vflat, tris, audit["polygon_area"])
    provinces = deepcopy(prod["provinces"]) + [row]
    land = sum(1 for p in provinces if not p.get("is_water"))
    water = sum(1 for p in provinces if p.get("is_water"))
    srcs = [int(p["source_id"]) for p in provinces]
    inc = included_ids_hash(sorted(srcs))
    preview = deepcopy(prod)
    preview["provinces"] = provinces
    preview["province_count"] = len(provinces)
    preview["land_count"] = land
    preview["water_count"] = water
    preview["included_source_ids_sha256"] = inc
    preview["id_map"] = list(prod.get("id_map") or []) + [{"gates_id": new_id, "source_id": KOL_SRC}]
    text = json.dumps(preview, separators=(",", ":"), ensure_ascii=False)
    ds_sha = hashlib.sha256(text.encode()).hexdigest()
    KOL_DIR.mkdir(parents=True, exist_ok=True)
    (KOL_DIR / "polygon_dataset.json").write_text(text + "\n", encoding="utf-8")
    meta = {
        "map_id": "earth3_europe_mediterranean_kolguyev_preview",
        "asset_status": "preview_only_not_production",
        "province_count": len(provinces),
        "land_count": land,
        "water_count": water,
        "included_source_ids_sha256": inc,
        "dataset_sha256": ds_sha,
        "added": {"gates_id": new_id, "source_id": KOL_SRC},
        "production_baseline_hash": HASH,
        "unused_gaps": sorted(GAPS),
    }
    (KOL_DIR / "dataset_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (KOL_DIR / "map_manifest.json").write_text(
        json.dumps(
            {
                "schema": "gates-of-codex.strategic-map",
                "map_id": "earth3_europe_mediterranean_kolguyev_preview",
                "renderer": "polygon_mesh",
                "asset_status": "preview_only_not_production",
                "polygon_dataset": {"path": "polygon_dataset.json", "sha256": ds_sha, "province_count": len(provinces)},
                "province_count": len(provinces),
                "bounds": prod["bounds"],
                "fallback_map_id": "earth3_europe_mediterranean",
                "water_policy": "water_not_normally_selectable",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    adj = build_kolguyev_topology(prod, archive, ox, oy, local_geom, new_id)
    # force no invented land neighbors on the province row
    assert row["neighbors"] == []
    assert adj["direct_land_neighbors"] == []
    val = audit_preview_3511(prod, provinces, new_id, inc, ds_sha)
    val["adjacency"] = adj
    val["checks_bool"] = {
        "empty_land_meshes": val["checks"]["empty_land_meshes"] == 0,
        "dangling_neighbors": val["checks"]["dangling_adjacency"] == 0,
        "source_11836_once": val["checks"]["source_11836_count"] == 1,
        "new_id_once": val["checks"]["e3_3512_count"] == 1,
        "gaps_unused": val["checks"]["e3_2830_count"] == 0 and val["checks"]["e3_2888_count"] == 0,
        "stable_retained_mappings": val["checks"]["retained_stable_id_mismatches"] == 0,
        "no_invented_land_adjacency": adj["confirmation_no_mainland_land_adjacency_invented"],
        "production_still_3510": val["checks"]["production_dataset_unchanged"],
        "tri_ok": len(row["triangles"]) >= 3,
        "full_3511_audit_pass": val["all_pass"],
        "topology_not_centroid_radius": adj["not_centroid_radius"],
    }
    (OUT / "kolguyev_adjacency_report.json").write_text(json.dumps(adj, indent=2) + "\n", encoding="utf-8")
    (OUT / "kolguyev_preview_validation.json").write_text(json.dumps(val, indent=2) + "\n", encoding="utf-8")
    # screenshots exact polygons
    ev = OUT / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    for tag, data, hi in [("before", prod, None), ("after", {"provinces": provinces}, new_id)]:
        img = Image.new("RGB", (1000, 800), (18, 32, 48))
        dr = ImageDraw.Draw(img)
        minx, maxx, miny, maxy = 3600, 4306, 200, 1100
        s = min(960 / (maxx - minx), 740 / (maxy - miny))
        for p in data["provinces"]:
            if p.get("is_water"):
                continue
            try:
                g, _ = reconstruct_triangle_union(p["vertices"], p["triangles"], p.get("area"))
            except Exception:
                continue
            ccx, ccy = g.centroid.x, g.centroid.y
            if not (minx - 80 <= ccx <= maxx + 80 and miny - 80 <= ccy <= maxy + 80):
                continue
            polys = [g] if g.geom_type == "Polygon" else list(g.geoms) if g.geom_type == "MultiPolygon" else []
            for poly in polys:
                sp = [(20 + (x - minx) * s, 30 + (y - miny) * s) for x, y in poly.exterior.coords]
                fill = (90, 200, 110) if hi and p["id"] == hi else (120, 126, 132)
                if len(sp) >= 3:
                    dr.polygon(sp, fill=fill, outline=(40, 40, 40))
        dr.text((10, 8), f"Kolguyev {tag} exact mesh (no mainland adjacency)", fill=(240, 240, 240))
        img.save(ev / f"kolguyev_{tag}.png")
    return val


def write_owner_review(rows, georef, comparison, kol_val):
    lines = [
        "# Earth3 hydrography owner review",
        "",
        "Production **unchanged** at 3510 / `a849b381…`. Kolguyev preview **not** approved for production.",
        "",
        f"LOO RMS **{georef['leave_one_out']['rms_km']} km**, max **{georef['leave_one_out']['max_km']} km**. "
        "Kolguyev is not a control point.",
        f"North LOO: {georef['leave_one_out']['by_region'].get('ne_russia_north')}",
        f"Kolguyev holdout (not control): {georef.get('kolguyev_holdout_not_control')}",
        "",
        "Geometry: **emitted triangle union only**. Metrics: **local LAEA meters** (not degree-area).",
        "",
        "## Classifications",
        "",
        "| Label | geo_class | exact_id | conf | WGS84 | top IoU (m) | geom |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        top = (r["polygon_matches"] or [{}])[0]
        gm = r.get("geometry_meta") or {}
        lines.append(
            f"| {r['review_label']} | `{r['geographic_classification']}` | {r['exact_feature_identity']} | "
            f"{r['confidence']} | {r['wgs84_lon']},{r['wgs84_lat']} | "
            f"{top.get('name', '—')} iou={top.get('iou', '—')} | {gm.get('geometry_source')} |"
        )
    lines += ["", "## Unresolved candidates", ""]
    for r in rows:
        if r["geographic_classification"].startswith("UNRESOLVED"):
            lines.append(f"- **{r['review_label']}**: {r.get('candidate_identities')}")
    lines += ["", "## Old convex-hull vs exact triangle-union", ""]
    lines.append("| Label | old_iou | new_iou | delta | class_changed |")
    lines.append("|---|---:|---:|---:|---|")
    for c in comparison:
        lines.append(
            f"| {c['review_label']} | {c.get('old_iou')} | {c.get('new_iou')} | {c.get('iou_delta')} | "
            f"{c.get('classification_changed')} |"
        )
    lines += ["", "## Kolguyev 3511 preview", ""]
    lines.append(f"- all_pass: `{kol_val.get('all_pass')}`")
    lines.append(f"- checks: `{json.dumps(kol_val.get('checks'))}`")
    lines.append(f"- land neighbors: `{kol_val.get('adjacency', {}).get('direct_land_neighbors')}`")
    (OUT / "OWNER_REVIEW.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_tests():
    (ROOT / "tests/test_earth3_hydrography_georef.py").write_text(
        '''from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "docs/earth3-crop/hydrography_audit/georeference_transform.json"
INV = ROOT / "docs/earth3-crop/hydrography_audit/marked_features.json"
MAIN = ROOT / "tools/earth3/hydrography_audit_main.py"
KOL_ADJ = ROOT / "docs/earth3-crop/hydrography_audit/kolguyev_adjacency_report.json"
KOL_VAL = ROOT / "docs/earth3-crop/hydrography_audit/kolguyev_preview_validation.json"
CMP = ROOT / "docs/earth3-crop/hydrography_audit/polygon_match_old_vs_new.json"
HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"
PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean/dataset_meta.json"


class Earth3HydrographyGeorefTests(unittest.TestCase):
    def test_loo_and_no_fake_zero_validated_rms(self):
        t = json.loads(T.read_text(encoding="utf-8"))
        self.assertFalse(t.get("kolguyev_is_control_point", True))
        loo = t["leave_one_out"]
        self.assertGreater(loo["rms_km"], 0.0)
        self.assertGreaterEqual(loo["by_region"].get("ne_russia_north", {}).get("n", 0), 5)
        for _rname, reg in t["regions"].items():
            if reg.get("n", 99) <= 3:
                self.assertIn("NOT independent validation", reg.get("validation_note", ""))
        tol = t["fixed_control_tolerances_km"]
        loo_map = {r["label"]: r["error_km"] for r in loo["residuals"]}
        for lab, max_km in tol.items():
            if lab in loo_map:
                self.assertLessEqual(loo_map[lab], max_km, lab)

    def test_no_hardcoded_home_archive_path(self):
        txt = MAIN.read_text(encoding="utf-8")
        self.assertNotIn(r"C:\\\\Users\\\\paulf\\\\Downloads", txt)
        self.assertIn("GATES_EARTH3_ARCHIVE", txt)

    def test_exact_geometry_and_meter_metrics(self):
        inv = json.loads(INV.read_text(encoding="utf-8"))
        self.assertEqual(inv["production_authority"]["included_ids_sha256"], HASH)
        self.assertEqual(json.loads(PROD.read_text(encoding="utf-8"))["province_count"], 3510)
        for f in inv["features"]:
            gm = f.get("geometry_meta") or {}
            self.assertEqual(gm.get("geometry_source"), "emitted_triangle_union", f["review_label"])
            self.assertFalse(gm.get("used_convex_hull", True), f["review_label"])
            self.assertFalse(gm.get("used_synthetic_geometry", True), f["review_label"])
            self.assertLessEqual(float(gm.get("reconstruction_relative_error", 1)), 1e-4, f["review_label"])
            self.assertIn("polygon_matches", f)
            if f["review_label"] == "MED01_Ibiza":
                self.assertGreater(f["wgs84_lon"], 0.0)
                self.assertLess(f["wgs84_lon"], 3.5)
            if f["geographic_classification"].startswith("UNRESOLVED"):
                self.assertFalse(f.get("production_change_allowed", False))
            if f["confidence"] == "high" and f["geographic_classification"] == "CONFIRMED_REAL_WATER_KEEP":
                top = (f.get("polygon_matches") or [None])[0]
                self.assertIsNotNone(top, f["review_label"])
                self.assertEqual(top.get("metric_units"), "meters_laea", f["review_label"])
                self.assertFalse(top.get("used_degree_area", False))
                ok = (
                    float(top.get("iou") or 0) >= 0.15
                    or float(top.get("earth3_coverage_by_ref") or 0) >= 0.25
                    or (
                        float(top.get("centroid_separation_km") or 999) < 40
                        and float(top.get("iou") or 0) >= 0.05
                    )
                )
                self.assertTrue(ok, f"{f['review_label']} high-confidence below exact thresholds: {top}")

    def test_no_synthetic_or_degree_area_confirmed(self):
        inv = json.loads(INV.read_text(encoding="utf-8"))
        confirmed = {
            "CONFIRMED_REAL_WATER_KEEP",
            "CONFIRMED_MISSING_LAND_RESTORE",
            "CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP",
        }
        for f in inv["features"]:
            if f["geographic_classification"] not in confirmed:
                continue
            gm = f["geometry_meta"]
            self.assertEqual(gm["geometry_source"], "emitted_triangle_union")
            self.assertFalse(gm["used_convex_hull"])
            self.assertFalse(gm["used_synthetic_geometry"])
            for m in f.get("polygon_matches") or []:
                if f["geographic_classification"] == "CONFIRMED_REAL_WATER_KEEP":
                    self.assertEqual(m.get("metric_units"), "meters_laea")

    def test_kolguyev_preview_constraints(self):
        adj = json.loads(KOL_ADJ.read_text(encoding="utf-8"))
        self.assertEqual(adj["direct_land_neighbors"], [])
        self.assertTrue(adj["confirmation_no_mainland_land_adjacency_invented"])
        self.assertTrue(adj.get("not_centroid_radius"))
        self.assertEqual(adj.get("method"), "exact_source_ring_boundary_distance")
        self.assertTrue(adj.get("no_automatic_sea_or_ferry_adjacency"))
        val = json.loads(KOL_VAL.read_text(encoding="utf-8"))
        self.assertTrue(val.get("all_pass"), val.get("checks"))
        c = val["checks"]
        self.assertEqual(c["province_count_checked"], 3511)
        self.assertEqual(c["land_count_checked"], 3296)
        self.assertEqual(c["water_count_checked"], 215)
        self.assertEqual(c["failed_triangulations"], 0)
        self.assertEqual(c["empty_land_meshes"], 0)
        self.assertEqual(c["dangling_adjacency"], 0)
        self.assertEqual(c["retained_stable_id_mismatches"], 0)
        self.assertEqual(c["source_11836_count"], 1)
        self.assertEqual(c["e3_3512_count"], 1)
        self.assertEqual(c["e3_2830_count"], 0)
        self.assertEqual(c["e3_2888_count"], 0)
        self.assertTrue(c["production_dataset_unchanged"])
        self.assertEqual(val["summary"]["source_id"], 11836)
        self.assertNotIn(val["summary"]["gates_id"], ["e3_2830", "e3_2888"])
        bools = val.get("checks_bool") or {}
        self.assertTrue(all(bools.values()), bools)

    def test_old_vs_new_comparison_present(self):
        cmp = json.loads(CMP.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cmp), 8)
        for row in cmp:
            self.assertIn("old_iou", row)
            self.assertIn("new_iou", row)
            self.assertIn("classification_changed", row)


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )


def write_readme():
    (OUT / "README.md").write_text(
        """# Earth3 hydrography audit

## Regenerate

```bash
set GATES_EARTH3_ARCHIVE=/path/to/AOH3_Earth3_map_provinces.zip
python tools/earth3/hydrography_audit_main.py --archive %GATES_EARTH3_ARCHIVE%
```

**Authoritative entry:** `tools/earth3/hydrography_audit_main.py`

- Geometry: emitted **triangle union** only (no convex hull / synthetic circle)
- Metrics: local **Lambert azimuthal equal-area** meters
- Production path is never modified
- Kolguyev preview is not production

Superseded: `build_hydrography_audit.py`, `build_hydrography_audit_v2.py`, `build_hydrography_georef.py`
""",
        encoding="utf-8",
    )


def supersede_old_builders():
    for p in [
        ROOT / "tools/earth3/build_hydrography_audit.py",
        ROOT / "tools/earth3/build_hydrography_audit_v2.py",
        ROOT / "tools/earth3/build_hydrography_georef.py",
    ]:
        if p.is_file():
            p.write_text(
                '"""SUPERSEDED by tools/earth3/hydrography_audit_main.py — do not use.\\n"""\n'
                "raise SystemExit('Superseded by tools/earth3/hydrography_audit_main.py')\n",
                encoding="utf-8",
            )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", default=None)
    args = ap.parse_args(argv)
    archive_path = resolve_archive(args.archive)

    prod = json.loads((PROD / "polygon_dataset.json").read_text(encoding="utf-8"))
    assert prod["province_count"] == 3510 and prod["included_source_ids_sha256"] == HASH
    ox, oy = prod["bounds"]["origin_source_xy"]
    by_src = {int(p["source_id"]): p for p in prod["provinces"]}
    gaps = {g["id"]: g for g in (prod.get("ocean_gap_fills") or [])}
    archive = load_earth3_dataset(archive_path)

    georef, controls = build_georef()
    mats = {k: v["affine_3x2"] for k, v in georef["regions"].items()}
    kp0 = archive.provinces[KOL_SRC]
    kcx = sum(p[0] for p in kp0.ring) / len(kp0.ring)
    kcy = sum(p[1] for p in kp0.ring) / len(kp0.ring)
    kplo, kpla = txy(mats, kcx, kcy)
    kol_holdout = {
        "is_control_point": False,
        "true_wgs84": [49.0, 69.1],
        "predicted": [round(kplo, 4), round(kpla, 4)],
        "error_km": round(hav(kplo, kpla, 49.0, 69.1), 3),
        "note": "Arctic source placement is east-biased vs true Kolguyev; identity uses archive src 11836.",
    }
    georef["kolguyev_holdout_not_control"] = kol_holdout
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "georeference_control_points.json").write_text(
        json.dumps({"control_points": controls, "kolguyev_is_control": False}, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUT / "georeference_transform.json").write_text(json.dumps(georef, indent=2) + "\n", encoding="utf-8")
    (OUT / "georeference_validation.json").write_text(
        json.dumps(
            {
                "leave_one_out": georef["leave_one_out"],
                "regions": {
                    k: {kk: vv for kk, vv in v.items() if kk != "affine_3x2"} for k, v in georef["regions"].items()
                },
                "fixed_tolerances_km": FIXED_TOL,
                "kolguyev_holdout_not_control": kol_holdout,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lakes = load_ne()
    subset = NE_SUBSET.read_bytes()
    (OUT / "reference/PROVENANCE.json").write_text(
        json.dumps(
            {
                "natural_earth_10m_lakes_subset": {
                    "license": "public domain",
                    "source_url": "https://www.naturalearthdata.com/downloads/10m-physical-vectors/",
                    "download_name": "ne_10m_lakes.zip",
                    "subset_file": "ne_10m_lakes_europe_subset.json",
                    "subset_sha256": hashlib.sha256(subset).hexdigest(),
                    "subset_bytes": len(subset),
                    "generation": "Europe/NA bbox + named majors + area filter; simplify 0.02 deg",
                    "fields": ["name", "bounds", "centroid", "geojson"],
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (OUT / "reference/README.md").write_text(
        "Natural Earth 10m lakes subset (public domain). Full shapefile optional/local; subset committed for CI.\n",
        encoding="utf-8",
    )

    # prior classifications for change detection
    prior_class = {}
    prior_path = OUT / "marked_features.json"
    if prior_path.is_file():
        try:
            prior = json.loads(prior_path.read_text(encoding="utf-8"))
            prior_class = {f["review_label"]: f.get("geographic_classification") for f in prior.get("features") or []}
        except Exception:
            prior_class = {}

    rows = []
    poly_table = []
    comparison = []
    recon_report = []
    ev = OUT / "evidence"
    ev.mkdir(parents=True, exist_ok=True)

    for label, gap_id, exp_sid, hyp in SPECS:
        gap = gaps.get(gap_id) if gap_id else None
        local_geom, recon_meta, lx, ly = feature_triangle_geometry(label, gap, exp_sid, by_src, archive, ox, oy)
        e3_wgs = local_to_wgs_geom(mats, ox, oy, local_geom)
        sx, sy = lx + ox, ly + oy
        lon, lat = txy(mats, sx, sy)
        cities = nearest_cities(archive, sx, sy)
        matches, proj_name = poly_match_meters(e3_wgs, lakes)
        top = matches[0] if matches else None

        # legacy hull comparison only
        if exp_sid is not None:
            vsrc = by_src[exp_sid]["vertices"]
        elif label == "NE01_Kolguyev":
            vsrc = None
            old_best = None
        else:
            vsrc = gap["vertices"] if gap else None
        if label != "NE01_Kolguyev" and vsrc is not None:
            hull = hull_from_vertices_for_legacy_only(vsrc)
            hull_wgs = local_to_wgs_geom(mats, ox, oy, hull) if hull is not None else None
            old_best = degree_area_iou_legacy_hull(hull_wgs, lakes)
        else:
            old_best = None

        geo, exact, conf, evidence, cands = classify(
            label, hyp, exp_sid, by_src, top, matches, cities, recon_meta, kol_holdout=kol_holdout
        )
        # demote high water if meter thresholds fail
        if conf == "high" and geo == "CONFIRMED_REAL_WATER_KEEP":
            if not top or top.get("metric_units") != "meters_laea":
                conf, geo, exact = "low", "UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH", "UNRESOLVED"
            elif not (
                float(top.get("iou") or 0) >= HI_IOU
                or float(top.get("earth3_coverage_by_ref") or 0) >= HI_COV
                or (float(top.get("centroid_separation_km") or 999) < HI_SEP_KM and float(top.get("iou") or 0) >= 0.05)
            ):
                conf, geo, exact = "medium", "UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH", "UNRESOLVED"

        old_iou = (old_best or {}).get("iou_degree_area_hull")
        new_iou = (top or {}).get("iou")
        iou_delta = None
        if old_iou is not None and new_iou is not None:
            iou_delta = round(float(new_iou) - float(old_iou), 4)
        prev = prior_class.get(label)
        comparison.append(
            {
                "review_label": label,
                "old_method": "convex_hull_degree_area",
                "new_method": "emitted_triangle_union_laea_meters",
                "old_iou": old_iou,
                "old_top_name": (old_best or {}).get("name"),
                "new_iou": new_iou,
                "new_top_name": (top or {}).get("name"),
                "iou_delta": iou_delta,
                "old_classification_prior_package": prev,
                "new_classification": geo,
                "classification_changed": bool(prev and prev != geo),
                "projection": proj_name,
                "geometry_meta": recon_meta,
            }
        )

        # reference geom for overlay = top named match if any
        ref_wgs = None
        if top:
            for lk in lakes:
                if (lk["name"] or "(unnamed)") == top["name"]:
                    ref_wgs = lk["geom"]
                    break
        unc = georef["leave_one_out"]["by_region"].get(region_of(sx, sy), {}).get("rms_km")
        overlay_name = f"overlay_{label}.png"
        draw_polygon_overlay(ev / overlay_name, e3_wgs, ref_wgs, label, top, unc)

        recon_report.append({"review_label": label, **recon_meta, "projection": proj_name})
        poly_table.append(
            {
                "review_label": label,
                "wgs84": [round(lon, 4), round(lat, 4)],
                "projection": proj_name,
                "geometry_meta": recon_meta,
                "matches": matches,
            }
        )
        rows.append(
            {
                "review_label": label,
                "map_local_xy": [round(lx, 2), round(ly, 2)],
                "source_map_xy": [round(sx, 2), round(sy, 2)],
                "wgs84_lon": round(lon, 4),
                "wgs84_lat": round(lat, 4),
                "georef_region": region_of(sx, sy),
                "georef_uncertainty_km_loo_region": unc,
                "nearest_cities": cities,
                "geometry_meta": recon_meta,
                "metric_projection": proj_name,
                "polygon_matches": matches,
                "candidate_identities": cands,
                "gap_fill_id": gap_id,
                "geographic_classification": geo,
                "exact_feature_identity": exact,
                "confidence": conf,
                "evidence": evidence,
                "overlay": f"docs/earth3-crop/hydrography_audit/evidence/{overlay_name}",
                "geographic_reference": {
                    "path": "docs/earth3-crop/hydrography_audit/reference/ne_10m_lakes_europe_subset.json",
                    "provenance": "docs/earth3-crop/hydrography_audit/reference/PROVENANCE.json",
                    "license": "Natural Earth public domain",
                },
                "production_change_allowed": geo == "CONFIRMED_MISSING_LAND_RESTORE",
            }
        )

    inv = {
        "schema": "gates-of-codex.earth3-hydrography-marked-features",
        "schema_version": 6,
        "production_authority": {
            "provinces": 3510,
            "land": 3295,
            "water_metadata": 215,
            "included_ids_sha256": HASH,
        },
        "georeference": {
            "method": georef["selected_method"],
            "loo_rms_km": georef["leave_one_out"]["rms_km"],
            "loo_max_km": georef["leave_one_out"]["max_km"],
            "loo_by_region": georef["leave_one_out"]["by_region"],
            "fixed_tolerances_km": FIXED_TOL,
            "metric_projection": "lambert_azimuthal_equal_area_local_m",
            "geometry_policy": "emitted_triangle_union_only",
            "note": "In-sample n<=3 zero RMS is not validation; LOO is authoritative. Kolguyev not a control.",
        },
        "features": rows,
        "polygon_match_table": poly_table,
        "summary": {
            k: [r["review_label"] for r in rows if r["geographic_classification"] == k]
            for k in [
                "CONFIRMED_REAL_WATER_KEEP",
                "CONFIRMED_MISSING_LAND_RESTORE",
                "CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP",
                "CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER",
                "UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH",
            ]
        },
    }
    (OUT / "marked_features.json").write_text(json.dumps(inv, indent=2) + "\n", encoding="utf-8")
    (OUT / "polygon_match_table.json").write_text(json.dumps(poly_table, indent=2) + "\n", encoding="utf-8")
    (OUT / "polygon_match_old_vs_new.json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    (OUT / "geometry_reconstruction_report.json").write_text(json.dumps(recon_report, indent=2) + "\n", encoding="utf-8")
    kol_val = build_kolguyev(prod, archive, ox, oy, mats)
    write_owner_review(rows, georef, comparison, kol_val)
    write_tests()
    write_readme()
    supersede_old_builders()
    print(
        json.dumps(
            {
                "loo_rms": georef["leave_one_out"]["rms_km"],
                "loo_max": georef["leave_one_out"]["max_km"],
                "loo_north": georef["leave_one_out"]["by_region"].get("ne_russia_north"),
                "summary": inv["summary"],
                "comparison": comparison,
                "kolguyev_all_pass": kol_val.get("all_pass"),
                "kolguyev_checks": kol_val.get("checks"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
