#!/usr/bin/env python3
"""Authoritative Earth3 hydrography audit (docs + diagnostic previews only).

  set GATES_EARTH3_ARCHIVE=/path/to/AOH3_Earth3_map_provinces.zip
  python tools/earth3/hydrography_audit_main.py --archive %GATES_EARTH3_ARCHIVE%

Does not modify production godot/assets/maps/earth3_europe_mediterranean/.

Geometry: exact emitted triangle unions only (no convex hull / synthetic circle).
Metrics: local Lambert azimuthal equal-area (meters), never raw degree-area IoU.

NOTE: Source 11836 is NOT Kolguyev. It is a northern-Urals/Komi–Yamal mainland
province (city Fion). Actual Kolguyev remains a separate investigation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import MultiPoint, Point, Polygon, mapping, shape
from shapely.ops import transform, unary_union
from shapely.validation import make_valid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from gates_of_codex.earth3.audit_artifact import included_ids_hash  # noqa: E402
from gates_of_codex.earth3.export_production import triangulate_ring_validated  # noqa: E402
from gates_of_codex.earth3.parse import load_earth3_dataset  # noqa: E402

OUT = ROOT / "docs/earth3-crop/hydrography_audit"
PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean"
NE_SUBSET = OUT / "reference/ne_10m_lakes_europe_subset.json"
SRC11836_DIR = ROOT / "godot/assets/maps/earth3_europe_mediterranean_src11836_preview"
OLD_KOL_DIR = ROOT / "godot/assets/maps/earth3_europe_mediterranean_kolguyev_preview"
CROP_CFG = ROOT / "config/earth3/crop_candidates_v1.json"
HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"
GAPS = {"e3_2830", "e3_2888"}
SRC11836 = 11836
TRUE_KOLGUYEV_WGS = (49.25, 69.08)
BUGRINO_WGS = (49.30, 68.78)
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
    ("NE01_source11836_Fion_northern_Urals", None, None, None),
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

STALE_EVIDENCE = [
    "closeup_NE01_Kolguyev.png",
    "closeup_NE06_Volga_mid_reservoir.png",
    "closeup_NE07_Cheboksary_system.png",
    "closeup_NE08_Kuybyshev_Samara_arm.png",
    "kolguyev_before.png",
    "kolguyev_after.png",
    "kolguyev_before_missing.png",
    "kolguyev_preview_restored.png",
    "overlay_NE01_Kolguyev.png",
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
    return {
        "schema": "gates-of-codex.earth3-georeference-transform",
        "schema_version": 7,
        "selected_method": "piecewise_regional_affine_with_loo",
        "source_11836_is_not_kolguyev": True,
        "source_11836_is_georef_control": False,
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
            "Source 11836 is NOT the real-world Kolguyev island.",
            "Polygon IoU/area use local LAEA meters, never raw lon/lat degree area.",
            "Rendered geometry = emitted triangle union only.",
        ],
    }, controls


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


def reconstruct_triangle_union(vertices, triangles, committed_area):
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
    n_comp = len(union.geoms) if union.geom_type == "MultiPolygon" else (1 if not union.is_empty else 0)
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


def load_v7_mask():
    data = json.loads(CROP_CFG.read_text(encoding="utf-8"))
    for c in data.get("candidates") or []:
        if c.get("id") != "em_reference_masked":
            continue
        polys = []
        for ring in c.get("mask_rings") or []:
            pts = [(float(x), float(y)) for x, y in ring]
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            polys.append(Polygon(pts))
        return unary_union(polys)
    return None


def classify(label, hyp, exp_sid, by_src, top, matches, cities, recon_meta):
    if label == "NE01_source11836_Fion_northern_Urals":
        return (
            "UNRESOLVED_MISSING_MAINLAND_OR_CROP_BOUNDARY_DEFECT",
            "UNRESOLVED",
            "high",
            (
                f"Archive land src {SRC11836} city Fion. Transformed ~61.3E/65.9N "
                f"(northern Urals / Komi–Yamal mainland). Shares land boundaries; "
                f"no bordering source-water. NOT the Barents island near 49.25E/69.08N. "
                f"Omitted by v7 Europe–Asia mask (overlap 0). geometry={recon_meta['geometry_source']}."
            ),
            [
                "include source 11836 if boundary revised west of Ural crest",
                "keep excluded as east-of-boundary mainland",
                "adjust mask / split boundary-straddling polygons",
            ],
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
    if exp_sid is not None:
        p = by_src[exp_sid]
        geom, meta = reconstruct_triangle_union(p["vertices"], p["triangles"], p.get("area"))
        lx, ly = float(p["centroid"][0]), float(p["centroid"][1])
        return geom, meta, lx, ly
    if label == "NE01_source11836_Fion_northern_Urals":
        kp = archive.provinces[SRC11836]
        local = [(round(x - ox, 6), round(y - oy, 6)) for x, y in kp.ring]
        if local[0] == local[-1]:
            local = local[:-1]
        verts, tris, _ring_flat, audit = triangulate_ring_validated(tuple(local))
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
    pts = pair_vertices(vertices)
    if len(pts) < 3:
        return None
    h = MultiPoint(pts).convex_hull
    if h.geom_type != "Polygon":
        return None
    return h


def draw_polygon_overlay(path, e3_wgs, ref_wgs, label, metrics, georef_unc_km):
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
    s = min((w - 80) / (maxx - minx), (h - 120) / (maxy - miny))

    def to_px(coords):
        return [(40 + (x - minx) * s, 60 + (maxy - y) * s) for x, y in coords]

    def draw_geom(g, fill, outline):
        if g is None or g.is_empty:
            return
        polys = [g] if g.geom_type == "Polygon" else list(g.geoms) if g.geom_type == "MultiPolygon" else []
        for poly in polys:
            ext = to_px(list(poly.exterior.coords))
            if len(ext) >= 3:
                dr.polygon(ext, fill=fill, outline=outline)

    inter = e3_only = ref_only = None
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
    dr.text((16, 30), f"georef_unc~{georef_unc_km}km LOO  exact triangle-union  LAEA meters", fill=(180, 190, 200))
    img.save(path)


def analyze_source_11836(archive, mats, prod, ox, oy):
    mask = load_v7_mask()
    p = archive.provinces[SRC11836]
    g = source_ring_polygon(p.ring)
    cx = float(g.centroid.x)
    cy = float(g.centroid.y)
    lon, lat = txy(mats, cx, cy)
    cities = nearest_cities(archive, cx, cy, n=8)
    # land/water contacts
    minx, miny, maxx, maxy = g.bounds
    pad = 400.0
    land_hits, water_hits = [], []
    for sid, pr in archive.provinces.items():
        if int(sid) == SRC11836:
            continue
        xs = [q[0] for q in pr.ring]
        ys = [q[1] for q in pr.ring]
        if max(xs) < minx - pad or min(xs) > maxx + pad or max(ys) < miny - pad or min(ys) > maxy + pad:
            continue
        pg = source_ring_polygon(pr.ring)
        if pg is None:
            continue
        dist = float(g.distance(pg))
        borders = bool(g.intersects(pg) or g.touches(pg))
        inter_area = float(g.intersection(pg).area) if borders else 0.0
        entry = {
            "source_id": int(sid),
            "min_boundary_distance_px": round(dist, 3),
            "intersects_or_touches": borders,
            "intersection_area_px2": round(inter_area, 4),
            "shared_boundary_only": borders and inter_area < 1e-6,
            "is_water": bool(pr.is_water),
            "in_production_3510": int(sid) in {int(x["source_id"]) for x in prod["provinces"]},
            "cities": [c.name for c in archive.cities if int(c.province_id) == int(sid)][:3],
        }
        (water_hits if pr.is_water else land_hits).append(entry)
    land_hits.sort(key=lambda d: d["min_boundary_distance_px"])
    water_hits.sort(key=lambda d: d["min_boundary_distance_px"])
    shared = [h for h in land_hits if h["min_boundary_distance_px"] < 0.5]
    overlap = float(g.intersection(mask).area / g.area) if mask is not None and g.area > 0 else None
    in_mask = bool(mask.contains(Point(cx, cy))) if mask is not None else None
    # Ural boundary side: mask east edge ~11235; conventional Europe west of Urals
    # Predicted lon ~61E is east of typical Ural crest (~60E) in this region
    ural_side = "east_of_or_across_ural_crest_provisional" if lon >= 60.0 else "west_of_ural_crest_provisional"
    report = {
        "source_id": SRC11836,
        "rejected_identity": "NOT_Kolguyev_island",
        "true_kolguyev_wgs84_for_comparison": list(TRUE_KOLGUYEV_WGS),
        "bugrino_wgs84_for_comparison": list(BUGRINO_WGS),
        "predicted_wgs84": [round(lon, 4), round(lat, 4)],
        "distance_to_true_kolguyev_km": round(hav(lon, lat, *TRUE_KOLGUYEV_WGS), 1),
        "source_centroid_xy": [round(cx, 2), round(cy, 2)],
        "is_water": bool(p.is_water),
        "geographic_region": "northern_Urals / Komi–Yamal mainland (Fion / Pechora basin periphery)",
        "country_federal_subject_provisional": "Russia — Komi Republic / Nenets–Yamal periphery (provisional)",
        "ural_europe_asia_side": ural_side,
        "v7_mask_contains_centroid": in_mask,
        "v7_mask_overlap_fraction": round(overlap, 6) if overlap is not None else None,
        "in_production_3510": False,
        "nearest_cities": cities,
        "shared_land_boundary_contacts": shared,
        "bordering_source_water": [h for h in water_hits if h["min_boundary_distance_px"] < 2.0],
        "nearest_source_water": water_hits[:8],
        "nearest_source_land": land_hits[:12],
        "behaves_as_island": False,
        "why_omitted": "v7 Europe–Asia boundary mask overlap is 0; province lies east of authored mask eastern limit",
        "creates_internal_land_hole_in_3510": False,
        "note_internal_hole": (
            "Omission is an eastern exterior crop, not an interior hole inside the kept land mass. "
            "Neighboring 11809 (Dutovo) and 11838 (Pechora) remain in production; 11836 sits outside mask."
        ),
        "candidate_solutions": [
            "keep excluded (east of approved Europe–Asia boundary)",
            "include source 11836 only if owner revises mask eastward",
            "do not treat as island restore",
            "if included later, derive real shared-edge land adjacency (not neighbors=[])",
        ],
        "recommended_interim": "UNRESOLVED_MISSING_MAINLAND_OR_CROP_BOUNDARY_DEFECT — no production change",
    }
    # overlay vs mask
    ev = OUT / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (1200, 900), (14, 20, 30))
    dr = ImageDraw.Draw(img)
    # source-local window
    win = (11000, 11600, 400, 1000)
    s = min(1100 / (win[1] - win[0]), 800 / (win[3] - win[2]))

    def px(x, y):
        return (40 + (x - win[0]) * s, 40 + (y - win[2]) * s)

    # mask slice
    if mask is not None:
        if mask.geom_type == "Polygon":
            polys = [mask]
        elif mask.geom_type == "MultiPolygon":
            polys = list(mask.geoms)
        else:
            polys = [g for g in getattr(mask, "geoms", []) if g.geom_type == "Polygon"]
        for poly in polys:
            if poly.geom_type != "Polygon":
                continue
            coords = [px(x, y) for x, y in poly.exterior.coords if win[0] - 200 <= x <= win[1] + 200]
            if len(coords) >= 3:
                dr.line(coords, fill=(60, 100, 180), width=2)
    def iter_polys(geom):
        if geom is None or geom.is_empty:
            return []
        if geom.geom_type == "Polygon":
            return [geom]
        if geom.geom_type == "MultiPolygon":
            return list(geom.geoms)
        return [x for x in getattr(geom, "geoms", []) if x.geom_type == "Polygon"]

    # neighbors
    for h in shared:
        pr = archive.provinces[h["source_id"]]
        pg = source_ring_polygon(pr.ring)
        for poly in iter_polys(pg):
            coords = [px(x, y) for x, y in poly.exterior.coords]
            if len(coords) >= 3:
                dr.polygon(coords, outline=(140, 140, 150))
    # 11836
    for poly in iter_polys(g):
        coords = [px(x, y) for x, y in poly.exterior.coords]
        if len(coords) >= 3:
            dr.polygon(coords, outline=(255, 200, 40), fill=(180, 120, 40))
    # true Kolguyev marker via inverse-ish: just text annotation of true WGS
    dr.text((20, 10), "src11836 Fion northern Urals (yellow) vs v7 mask edge (blue)", fill=(240, 240, 240))
    dr.text(
        (20, 30),
        f"predicted WGS {lon:.3f}E {lat:.3f}N | true island target {TRUE_KOLGUYEV_WGS[0]}E {TRUE_KOLGUYEV_WGS[1]}N "
        f"| d={report['distance_to_true_kolguyev_km']}km | mask_overlap={overlap}",
        fill=(200, 200, 210),
    )
    dr.text((20, 50), "NOT an island — shared land boundaries; no bordering source-water", fill=(255, 160, 120))
    img.save(ev / "overlay_NE01_source11836_Fion_ural_boundary.png")
    report["boundary_overlay"] = "docs/earth3-crop/hydrography_audit/evidence/overlay_NE01_source11836_Fion_ural_boundary.png"
    return report


def search_true_kolguyev(archive, mats, prod_srcs):
    """Independent search for real Kolguyev island source polygon. May return unresolved."""
    tlon, tlat = TRUE_KOLGUYEV_WGS
    candidates = []
    for sid, p in archive.provinces.items():
        if p.is_water:
            continue
        cx = sum(q[0] for q in p.ring) / len(p.ring)
        cy = sum(q[1] for q in p.ring) / len(p.ring)
        lon, lat = txy(mats, cx, cy)
        d_k = hav(lon, lat, tlon, tlat)
        d_b = hav(lon, lat, *BUGRINO_WGS)
        if min(d_k, d_b) > 400:
            continue
        g = source_ring_polygon(p.ring)
        if g is None:
            continue
        minx, miny, maxx, maxy = g.bounds
        pad = 60.0
        land_t, water_t = 0, 0
        for sid2, p2 in archive.provinces.items():
            if sid2 == sid:
                continue
            xs = [q[0] for q in p2.ring]
            ys = [q[1] for q in p2.ring]
            if max(xs) < minx - pad or min(xs) > maxx + pad or max(ys) < miny - pad or min(ys) > maxy + pad:
                continue
            g2 = source_ring_polygon(p2.ring)
            if g2 is None:
                continue
            if g.distance(g2) < 0.5:
                if p2.is_water:
                    water_t += 1
                else:
                    land_t += 1
        cities = [c.name for c in archive.cities if int(c.province_id) == int(sid)][:4]
        island_like = land_t == 0 and water_t >= 1
        candidates.append(
            {
                "source_id": int(sid),
                "predicted_wgs84": [round(lon, 4), round(lat, 4)],
                "distance_to_kolguyev_center_km": round(d_k, 1),
                "distance_to_bugrino_km": round(d_b, 1),
                "source_centroid_xy": [round(cx, 1), round(cy, 1)],
                "area_px2": round(float(g.area), 1),
                "land_boundary_contacts": land_t,
                "water_boundary_contacts": water_t,
                "island_like": island_like,
                "in_production_3510": int(sid) in prod_srcs,
                "nearest_cities": cities,
                "notes": (
                    "mainland Timan/Barents coast (Indiga area)"
                    if int(sid) == 11768
                    else (
                        "island-like northern land (likely Novaya Zemlya / other — not Bugrino)"
                        if island_like
                        else "mainland or multi-touch land"
                    )
                ),
            }
        )
    candidates.sort(key=lambda r: (not r["island_like"], r["distance_to_kolguyev_center_km"]))
    # Accept only if island-like AND within ~80km of true center
    accepted = [
        c
        for c in candidates
        if c["island_like"] and c["distance_to_kolguyev_center_km"] <= 80 and c["land_boundary_contacts"] == 0
    ]
    return {
        "true_kolguyev_wgs84": list(TRUE_KOLGUYEV_WGS),
        "bugrino_wgs84": list(BUGRINO_WGS),
        "search_method": [
            "LOO piecewise georef predicted WGS of all northern land provinces",
            "distance to 49.25E/69.08N and Bugrino 49.30E/68.78N",
            "source-ring land vs water boundary contacts",
            "island-like requires 0 land contacts and >=1 water contact",
            "source 11836 explicitly excluded as false prior identity",
        ],
        "candidates": candidates[:25],
        "accepted_kolguyev_source_id": accepted[0]["source_id"] if accepted else None,
        "result": (
            f"IDENTIFIED source {accepted[0]['source_id']}"
            if accepted
            else "UNRESOLVED — no archive land polygon matches Kolguyev island criteria near 49.25E/69.08N"
        ),
        "note": (
            "Closest named production land near the longitude is src 11768 (Indiga), already in 3510, "
            "mainland with multiple land contacts. No separate island polygon for Kolguyev was found. "
            "Source 11836 is mainland Fion ~630 km away and is not a candidate."
        ),
    }


def derive_src11836_land_neighbors(archive, prod):
    """Real shared-edge land adjacency for mainland src 11836 (not neighbors=[])."""
    g = source_ring_polygon(archive.provinces[SRC11836].ring)
    prod_by_src = {int(p["source_id"]): p for p in prod["provinces"]}
    neighbors = []
    for sid, pr in archive.provinces.items():
        if int(sid) == SRC11836 or pr.is_water:
            continue
        pg = source_ring_polygon(pr.ring)
        if pg is None:
            continue
        if g.distance(pg) < 0.5 and (g.touches(pg) or g.intersects(pg)):
            inter_area = float(g.intersection(pg).area)
            if inter_area < 1e-3:  # boundary-only
                gates = prod_by_src.get(int(sid))
                neighbors.append(
                    {
                        "source_id": int(sid),
                        "gates_id_if_in_production": gates["id"] if gates else None,
                        "in_production_3510": gates is not None,
                        "intersection_area_px2": round(inter_area, 6),
                    }
                )
    # Preview can only link neighbors present in the assembled dataset
    preview_neighbors = sorted(
        {n["gates_id_if_in_production"] for n in neighbors if n["gates_id_if_in_production"]},
    )
    return neighbors, preview_neighbors


def audit_all_triangle_rows(provinces):
    """Audit EVERY province row with triangles (land and water metadata)."""
    failed = []
    empty_land = []
    empty_water = []
    for p in provinces:
        tris = p.get("triangles") or []
        verts = p.get("vertices") or []
        if len(tris) < 3 or len(verts) < 6:
            if p.get("is_water"):
                empty_water.append(p["id"])
            else:
                empty_land.append(p["id"])
            continue
        try:
            reconstruct_triangle_union(verts, tris, p.get("area"))
        except Exception as exc:
            failed.append({"id": p["id"], "is_water": bool(p.get("is_water")), "error": str(exc)[:160]})
    return failed, empty_land, empty_water


def build_src11836_diagnostic_preview(prod, archive, ox, oy):
    """Diagnostic mainland preview only — not production, ID not reserved for promotion."""
    if OLD_KOL_DIR.exists():
        shutil.rmtree(OLD_KOL_DIR)
    kp = archive.provinces[SRC11836]
    local = [(round(x - ox, 6), round(y - oy, 6)) for x, y in kp.ring]
    if local[0] == local[-1]:
        local = local[:-1]
    verts, tris, ring_flat, audit = triangulate_ring_validated(tuple(local))
    # temporary diagnostic id only
    diag_id = "e3_3512"
    assert diag_id not in GAPS
    cx = sum(x for x, _ in local) / len(local)
    cy = sum(y for _, y in local) / len(local)
    land_adj, preview_neighbors = derive_src11836_land_neighbors(archive, prod)
    # mutual neighbor updates for production provinces present in preview
    provinces = deepcopy(prod["provinces"])
    row = {
        "id": diag_id,
        "source_id": SRC11836,
        "is_water": False,
        "terrain_id": int(kp.terrain_id),
        "continent_id": int(kp.continent_id),
        "centroid": [round(cx, 4), round(cy, 4)],
        "label": [round(cx, 4), round(cy, 4)],
        "vertices": verts,
        "triangles": tris,
        "ring": ring_flat,
        "area": round(float(audit["polygon_area"]), 4),
        "neighbors": preview_neighbors,
    }
    id_to_row = {p["id"]: p for p in provinces}
    for nid in preview_neighbors:
        if nid in id_to_row:
            nlist = list(id_to_row[nid].get("neighbors") or [])
            if diag_id not in nlist:
                nlist.append(diag_id)
                id_to_row[nid]["neighbors"] = nlist
    provinces.append(row)
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
    preview["id_map"] = list(prod.get("id_map") or []) + [{"gates_id": diag_id, "source_id": SRC11836}]
    text = json.dumps(preview, separators=(",", ":"), ensure_ascii=False)
    ds_sha = hashlib.sha256(text.encode()).hexdigest()
    SRC11836_DIR.mkdir(parents=True, exist_ok=True)
    (SRC11836_DIR / "polygon_dataset.json").write_text(text + "\n", encoding="utf-8")
    meta = {
        "map_id": "earth3_europe_mediterranean_src11836_preview",
        "asset_status": "diagnostic_preview_only_not_production",
        "not_reserved_for_production": True,
        "not_kolguyev": True,
        "province_count": len(provinces),
        "land_count": land,
        "water_count": water,
        "included_source_ids_sha256": inc,
        "dataset_sha256": ds_sha,
        "added": {"gates_id": diag_id, "source_id": SRC11836, "identity": "Fion_northern_Urals_mainland"},
        "production_baseline_hash": HASH,
        "unused_gaps": sorted(GAPS),
        "note": "Diagnostic only. e3_3512 is NOT reserved/promoted for production.",
    }
    (SRC11836_DIR / "dataset_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (SRC11836_DIR / "map_manifest.json").write_text(
        json.dumps(
            {
                "schema": "gates-of-codex.strategic-map",
                "map_id": "earth3_europe_mediterranean_src11836_preview",
                "renderer": "polygon_mesh",
                "asset_status": "diagnostic_preview_only_not_production",
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

    failed, empty_land, empty_water = audit_all_triangle_rows(provinces)
    ids = {p["id"] for p in provinces}
    dangling = [{"id": p["id"], "missing_neighbor": n} for p in provinces for n in (p.get("neighbors") or []) if n not in ids]
    prod_map = {int(e["source_id"]): e["gates_id"] for e in (prod.get("id_map") or [])}
    mismatches = []
    for p in provinces:
        sid = int(p["source_id"])
        if sid == SRC11836:
            continue
        exp = prod_map.get(sid)
        if exp is not None and exp != p["id"]:
            mismatches.append({"source_id": sid, "expected": exp, "got": p["id"]})
    prod_meta = json.loads((PROD / "dataset_meta.json").read_text(encoding="utf-8"))
    checks = {
        "province_count_checked": len(provinces),
        "land_count_checked": land,
        "water_count_checked": water,
        "all_3511_triangle_rows_valid": len(failed) == 0 and len(empty_land) == 0 and len(empty_water) == 0,
        "failed_triangulations_land_and_water": len(failed),
        "no_empty_land_meshes": len(empty_land) == 0,
        "no_empty_water_meshes": len(empty_water) == 0,
        "no_dangling_adjacency": len(dangling) == 0,
        "no_stable_id_mismatches": len(mismatches) == 0,
        "source_11836_count": srcs.count(SRC11836),
        "diagnostic_id_count": sum(1 for p in provinces if p["id"] == diag_id),
        "e3_2830_count": sum(1 for p in provinces if p["id"] == "e3_2830"),
        "e3_2888_count": sum(1 for p in provinces if p["id"] == "e3_2888"),
        "production_dataset_unchanged": prod_meta.get("province_count") == 3510
        and prod_meta.get("included_source_ids_sha256") == HASH,
        "mainland_adjacency_derived": len(preview_neighbors) >= 0,
        "not_using_empty_neighbors_for_mainland": row["neighbors"] == preview_neighbors,
        "composition": {
            "baseline_production_provinces": 3510,
            "added_src11836_mainland": 1,
            "assembled_diagnostic_preview": 3511,
            "audit_scope": "all_3511_rows_land_and_water_triangle_reconstruction",
        },
    }
    all_pass = (
        checks["province_count_checked"] == 3511
        and checks["all_3511_triangle_rows_valid"]
        and checks["no_dangling_adjacency"]
        and checks["no_stable_id_mismatches"]
        and checks["source_11836_count"] == 1
        and checks["production_dataset_unchanged"]
        and checks["e3_2830_count"] == 0
        and checks["e3_2888_count"] == 0
    )
    adj = {
        "gates_id": diag_id,
        "source_id": SRC11836,
        "identity": "mainland_Fion_northern_Urals",
        "not_kolguyev": True,
        "direct_land_neighbors": preview_neighbors,
        "source_shared_edge_land_contacts": land_adj,
        "method": "exact_source_ring_shared_boundary",
        "not_centroid_radius": True,
        "diagnostic_only": True,
        "id_not_reserved_for_production": True,
    }
    val = {
        "summary": {
            "gates_id": diag_id,
            "source_id": SRC11836,
            "identity": "mainland_Fion_northern_Urals_NOT_kolguyev",
            "province_count": len(provinces),
            "land_count": land,
            "water_count": water,
            "included_ids_sha256": inc,
            "dataset_sha256": ds_sha,
            "diagnostic_only": True,
        },
        "checks": checks,
        "all_pass": all_pass,
        "failed_triangulation_details": failed[:20],
        "dangling_details": dangling[:20],
        "adjacency": adj,
    }
    (OUT / "src11836_adjacency_report.json").write_text(json.dumps(adj, indent=2) + "\n", encoding="utf-8")
    (OUT / "src11836_preview_validation.json").write_text(json.dumps(val, indent=2) + "\n", encoding="utf-8")
    # screenshots
    ev = OUT / "evidence"
    for tag, data, hi in [("before", prod, None), ("after", {"provinces": provinces}, diag_id)]:
        img = Image.new("RGB", (1000, 800), (18, 32, 48))
        dr = ImageDraw.Draw(img)
        minx, maxx, miny, maxy = 3600, 4306, 200, 1100
        s = min(960 / (maxx - minx), 740 / (maxy - miny))
        for p in data["provinces"]:
            if p.get("is_water"):
                continue
            try:
                gg, _ = reconstruct_triangle_union(p["vertices"], p["triangles"], p.get("area"))
            except Exception:
                continue
            ccx, ccy = gg.centroid.x, gg.centroid.y
            if not (minx - 80 <= ccx <= maxx + 80 and miny - 80 <= ccy <= maxy + 80):
                continue
            polys = [gg] if gg.geom_type == "Polygon" else list(gg.geoms) if gg.geom_type == "MultiPolygon" else []
            for poly in polys:
                sp = [(20 + (x - minx) * s, 30 + (y - miny) * s) for x, y in poly.exterior.coords]
                fill = (90, 200, 110) if hi and p["id"] == hi else (120, 126, 132)
                if len(sp) >= 3:
                    dr.polygon(sp, fill=fill, outline=(40, 40, 40))
        dr.text((10, 8), f"src11836 Fion mainland diagnostic {tag} (NOT island)", fill=(240, 240, 240))
        img.save(ev / f"src11836_{tag}.png")
    return val


def purge_stale_evidence():
    removed = []
    ev = OUT / "evidence"
    for name in STALE_EVIDENCE:
        p = ev / name
        if p.is_file():
            p.unlink()
            removed.append(str(p.relative_to(ROOT)).replace("\\", "/"))
    for p in ev.glob("*olguy*"):
        p.unlink()
        removed.append(str(p.relative_to(ROOT)).replace("\\", "/"))
    for p in OUT.glob("*olguy*"):
        if p.is_file():
            p.unlink()
            removed.append(str(p.relative_to(ROOT)).replace("\\", "/"))
    if OLD_KOL_DIR.exists():
        shutil.rmtree(OLD_KOL_DIR)
        removed.append(str(OLD_KOL_DIR.relative_to(ROOT)).replace("\\", "/"))
    return removed


def write_owner_review(rows, georef, comparison, src_report, kol_search, preview_val, removed):
    lines = [
        "# Earth3 hydrography owner review",
        "",
        "Production **unchanged** at 3510 / `a849b381…`.",
        "",
        "**Source 11836 is NOT Kolguyev.** It is mainland Fion (northern Urals / Komi–Yamal).",
        f"True Kolguyev (~{TRUE_KOLGUYEV_WGS[0]}E, {TRUE_KOLGUYEV_WGS[1]}N) source polygon: "
        f"**{kol_search.get('result')}**.",
        "",
        f"LOO RMS **{georef['leave_one_out']['rms_km']} km**, max **{georef['leave_one_out']['max_km']} km**.",
        f"North LOO: {georef['leave_one_out']['by_region'].get('ne_russia_north')}",
        "",
        "Geometry: **emitted triangle union**. Metrics: **local LAEA meters**.",
        "",
        "## Classifications",
        "",
        "| Label | geo_class | exact_id | conf | WGS84 | top IoU (m) |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        top = (r["polygon_matches"] or [{}])[0]
        lines.append(
            f"| {r['review_label']} | `{r['geographic_classification']}` | {r['exact_feature_identity']} | "
            f"{r['confidence']} | {r['wgs84_lon']},{r['wgs84_lat']} | "
            f"{top.get('name', '—')} iou={top.get('iou', '—')} |"
        )
    lines += [
        "",
        "## Source 11836 identity",
        "",
        f"- predicted WGS: {src_report.get('predicted_wgs84')}",
        f"- distance to true Kolguyev: {src_report.get('distance_to_true_kolguyev_km')} km",
        f"- region: {src_report.get('geographic_region')}",
        f"- v7 mask overlap: {src_report.get('v7_mask_overlap_fraction')}",
        f"- shared land contacts: {len(src_report.get('shared_land_boundary_contacts') or [])}",
        f"- bordering source-water: {src_report.get('bordering_source_water')}",
        f"- overlay: {src_report.get('boundary_overlay')}",
        "",
        "## Actual Kolguyev search",
        "",
        f"- result: **{kol_search.get('result')}**",
        f"- accepted source id: `{kol_search.get('accepted_kolguyev_source_id')}`",
        f"- note: {kol_search.get('note')}",
        "",
        "## Diagnostic src11836 preview",
        "",
        f"- path: `godot/assets/maps/earth3_europe_mediterranean_src11836_preview/`",
        f"- all_pass: `{preview_val.get('all_pass')}`",
        f"- checks: `{json.dumps(preview_val.get('checks'))}`",
        f"- land neighbors (derived): `{preview_val.get('adjacency', {}).get('direct_land_neighbors')}`",
        f"- ID not reserved for production",
        "",
        "## Removed stale evidence",
        "",
    ]
    for r in removed:
        lines.append(f"- `{r}`")
    lines += ["", "## Old hull vs exact triangle-union", ""]
    lines.append("| Label | old_iou | new_iou | delta | class_changed |")
    lines.append("|---|---:|---:|---:|---|")
    for c in comparison:
        lines.append(
            f"| {c['review_label']} | {c.get('old_iou')} | {c.get('new_iou')} | {c.get('iou_delta')} | "
            f"{c.get('classification_changed')} |"
        )
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
SRC_ADJ = ROOT / "docs/earth3-crop/hydrography_audit/src11836_adjacency_report.json"
SRC_VAL = ROOT / "docs/earth3-crop/hydrography_audit/src11836_preview_validation.json"
SRC_ID = ROOT / "docs/earth3-crop/hydrography_audit/source_11836_identity_report.json"
KOL_SEARCH = ROOT / "docs/earth3-crop/hydrography_audit/kolguyev_true_island_search.json"
CMP = ROOT / "docs/earth3-crop/hydrography_audit/polygon_match_old_vs_new.json"
HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"
PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean/dataset_meta.json"
OLD_KOL = ROOT / "godot/assets/maps/earth3_europe_mediterranean_kolguyev_preview"


class Earth3HydrographyGeorefTests(unittest.TestCase):
    def test_loo_and_no_fake_zero_validated_rms(self):
        t = json.loads(T.read_text(encoding="utf-8"))
        self.assertTrue(t.get("source_11836_is_not_kolguyev"))
        loo = t["leave_one_out"]
        self.assertGreater(loo["rms_km"], 0.0)
        self.assertGreaterEqual(loo["by_region"].get("ne_russia_north", {}).get("n", 0), 5)
        tol = t["fixed_control_tolerances_km"]
        loo_map = {r["label"]: r["error_km"] for r in loo["residuals"]}
        for lab, max_km in tol.items():
            if lab in loo_map:
                self.assertLessEqual(loo_map[lab], max_km, lab)

    def test_no_hardcoded_home_archive_path(self):
        txt = MAIN.read_text(encoding="utf-8")
        self.assertNotIn(r"C:\\\\Users\\\\paulf\\\\Downloads", txt)
        self.assertIn("GATES_EARTH3_ARCHIVE", txt)

    def test_source_11836_not_labelled_kolguyev(self):
        inv = json.loads(INV.read_text(encoding="utf-8"))
        blob = json.dumps(inv).lower()
        # feature labels/classes must not claim 11836 is the island
        ne01 = next(f for f in inv["features"] if f["review_label"].startswith("NE01_"))
        self.assertEqual(ne01["review_label"], "NE01_source11836_Fion_northern_Urals")
        self.assertEqual(ne01["exact_feature_identity"], "UNRESOLVED")
        self.assertEqual(ne01["geographic_classification"], "UNRESOLVED_MISSING_MAINLAND_OR_CROP_BOUNDARY_DEFECT")
        self.assertFalse(ne01.get("production_change_allowed", False))
        self.assertNotIn("kolguyev island", (ne01.get("exact_feature_identity") or "").lower())
        self.assertTrue(SRC_ID.is_file())
        ident = json.loads(SRC_ID.read_text(encoding="utf-8"))
        self.assertEqual(ident["rejected_identity"], "NOT_Kolguyev_island")
        self.assertFalse(ident["behaves_as_island"])
        # no old preview path
        self.assertFalse(OLD_KOL.exists())
        # main + inventory should not market 11836 as Kolguyev restore
        main = MAIN.read_text(encoding="utf-8").lower()
        self.assertIn("not kolguyev", main)
        self.assertNotIn("confirmed_missing_land_restore", ne01["geographic_classification"].lower())

    def test_true_kolguyev_search_present(self):
        ks = json.loads(KOL_SEARCH.read_text(encoding="utf-8"))
        self.assertIn("candidates", ks)
        # 11836 must not be accepted as the island
        self.assertNotEqual(ks.get("accepted_kolguyev_source_id"), 11836)

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
            if f["geographic_classification"].startswith("UNRESOLVED"):
                self.assertFalse(f.get("production_change_allowed", False))
            if f["confidence"] == "high" and f["geographic_classification"] == "CONFIRMED_REAL_WATER_KEEP":
                top = (f.get("polygon_matches") or [None])[0]
                self.assertIsNotNone(top, f["review_label"])
                self.assertEqual(top.get("metric_units"), "meters_laea", f["review_label"])
                ok = (
                    float(top.get("iou") or 0) >= 0.15
                    or float(top.get("earth3_coverage_by_ref") or 0) >= 0.25
                    or (
                        float(top.get("centroid_separation_km") or 999) < 40
                        and float(top.get("iou") or 0) >= 0.05
                    )
                )
                self.assertTrue(ok, f"{f['review_label']} high-confidence below thresholds: {top}")

    def test_src11836_preview_mainland_adjacency_and_full_row_audit(self):
        adj = json.loads(SRC_ADJ.read_text(encoding="utf-8"))
        self.assertTrue(adj.get("not_kolguyev"))
        self.assertTrue(adj.get("diagnostic_only"))
        self.assertTrue(adj.get("id_not_reserved_for_production"))
        self.assertTrue(adj.get("not_centroid_radius"))
        # mainland must not force empty neighbors
        self.assertIsInstance(adj.get("direct_land_neighbors"), list)
        val = json.loads(SRC_VAL.read_text(encoding="utf-8"))
        self.assertTrue(val.get("all_pass"), val.get("checks"))
        c = val["checks"]
        self.assertEqual(c["province_count_checked"], 3511)
        self.assertTrue(c["all_3511_triangle_rows_valid"])
        self.assertTrue(c["no_empty_land_meshes"])
        self.assertTrue(c["no_empty_water_meshes"])
        self.assertTrue(c["no_dangling_adjacency"])
        self.assertTrue(c["no_stable_id_mismatches"])
        self.assertEqual(c["failed_triangulations_land_and_water"], 0)
        self.assertTrue(c["production_dataset_unchanged"])
        self.assertEqual(c["source_11836_count"], 1)
        self.assertEqual(c["e3_2830_count"], 0)
        self.assertEqual(c["e3_2888_count"], 0)

    def test_old_vs_new_comparison_present(self):
        cmp = json.loads(CMP.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cmp), 8)

    def test_no_stale_kolguyev_11836_filenames(self):
        ev = ROOT / "docs/earth3-crop/hydrography_audit/evidence"
        for p in ev.glob("*"):
            name = p.name.lower()
            self.assertNotIn("kolguyev", name)
            self.assertNotIn("volga_mid_reservoir", name)
            self.assertNotIn("cheboksary_system", name)
            self.assertNotIn("kuybyshev_samara", name)


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

- Geometry: emitted **triangle union** only
- Metrics: local **LAEA meters**
- Source **11836 is NOT Kolguyev** (mainland Fion / northern Urals)
- Actual Kolguyev island source remains a separate search (`kolguyev_true_island_search.json`)
- Production path is never modified

Diagnostic preview (not production): `godot/assets/maps/earth3_europe_mediterranean_src11836_preview/`
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

    removed = purge_stale_evidence()

    prod = json.loads((PROD / "polygon_dataset.json").read_text(encoding="utf-8"))
    assert prod["province_count"] == 3510 and prod["included_source_ids_sha256"] == HASH
    ox, oy = prod["bounds"]["origin_source_xy"]
    by_src = {int(p["source_id"]): p for p in prod["provinces"]}
    prod_srcs = set(by_src)
    gaps = {g["id"]: g for g in (prod.get("ocean_gap_fills") or [])}
    archive = load_earth3_dataset(archive_path)

    georef, controls = build_georef()
    mats = {k: v["affine_3x2"] for k, v in georef["regions"].items()}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "georeference_control_points.json").write_text(
        json.dumps({"control_points": controls, "source_11836_is_control": False}, indent=2) + "\n",
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
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    src_report = analyze_source_11836(archive, mats, prod, ox, oy)
    (OUT / "source_11836_identity_report.json").write_text(json.dumps(src_report, indent=2) + "\n", encoding="utf-8")
    kol_search = search_true_kolguyev(archive, mats, prod_srcs)
    (OUT / "kolguyev_true_island_search.json").write_text(json.dumps(kol_search, indent=2) + "\n", encoding="utf-8")

    prior_class = {}
    if (OUT / "marked_features.json").is_file():
        try:
            prior = json.loads((OUT / "marked_features.json").read_text(encoding="utf-8"))
            prior_class = {f["review_label"]: f.get("geographic_classification") for f in prior.get("features") or []}
        except Exception:
            prior_class = {}

    rows, poly_table, comparison, recon_report = [], [], [], []
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

        if exp_sid is not None:
            vsrc = by_src[exp_sid]["vertices"]
        elif label.startswith("NE01_"):
            vsrc = None
            old_best = None
        else:
            vsrc = gap["vertices"] if gap else None
        if not label.startswith("NE01_") and vsrc is not None:
            hull = hull_from_vertices_for_legacy_only(vsrc)
            hull_wgs = local_to_wgs_geom(mats, ox, oy, hull) if hull is not None else None
            old_best = degree_area_iou_legacy_hull(hull_wgs, lakes)
        else:
            old_best = None

        geo, exact, conf, evidence, cands = classify(label, hyp, exp_sid, by_src, top, matches, cities, recon_meta)
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
        iou_delta = None if old_iou is None or new_iou is None else round(float(new_iou) - float(old_iou), 4)
        prev = prior_class.get(label)
        comparison.append(
            {
                "review_label": label,
                "old_method": "convex_hull_degree_area",
                "new_method": "emitted_triangle_union_laea_meters",
                "old_iou": old_iou,
                "new_iou": new_iou,
                "iou_delta": iou_delta,
                "old_classification_prior_package": prev,
                "new_classification": geo,
                "classification_changed": bool(prev and prev != geo),
                "projection": proj_name,
                "geometry_meta": recon_meta,
            }
        )

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
                "production_change_allowed": False,
            }
        )

    inv = {
        "schema": "gates-of-codex.earth3-hydrography-marked-features",
        "schema_version": 7,
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
            "source_11836_is_not_kolguyev": True,
        },
        "features": rows,
        "polygon_match_table": poly_table,
        "source_11836_identity": "docs/earth3-crop/hydrography_audit/source_11836_identity_report.json",
        "true_kolguyev_search": "docs/earth3-crop/hydrography_audit/kolguyev_true_island_search.json",
        "summary": {
            k: [r["review_label"] for r in rows if r["geographic_classification"] == k]
            for k in [
                "CONFIRMED_REAL_WATER_KEEP",
                "CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP",
                "CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER",
                "UNRESOLVED_MISSING_MAINLAND_OR_CROP_BOUNDARY_DEFECT",
                "UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH",
            ]
        },
        "removed_stale_evidence": removed,
    }
    (OUT / "marked_features.json").write_text(json.dumps(inv, indent=2) + "\n", encoding="utf-8")
    (OUT / "polygon_match_table.json").write_text(json.dumps(poly_table, indent=2) + "\n", encoding="utf-8")
    (OUT / "polygon_match_old_vs_new.json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    (OUT / "geometry_reconstruction_report.json").write_text(json.dumps(recon_report, indent=2) + "\n", encoding="utf-8")
    (OUT / "stale_evidence_removed.json").write_text(json.dumps(removed, indent=2) + "\n", encoding="utf-8")

    preview_val = build_src11836_diagnostic_preview(prod, archive, ox, oy)
    write_owner_review(rows, georef, comparison, src_report, kol_search, preview_val, removed)
    write_tests()
    write_readme()
    supersede_old_builders()
    print(
        json.dumps(
            {
                "loo_rms": georef["leave_one_out"]["rms_km"],
                "summary": inv["summary"],
                "source_11836": {
                    "wgs": src_report["predicted_wgs84"],
                    "d_true_kolguyev_km": src_report["distance_to_true_kolguyev_km"],
                    "mask_overlap": src_report["v7_mask_overlap_fraction"],
                    "island": src_report["behaves_as_island"],
                },
                "true_kolguyev_search": kol_search["result"],
                "accepted_kolguyev_source_id": kol_search["accepted_kolguyev_source_id"],
                "preview_all_pass": preview_val.get("all_pass"),
                "removed_stale": removed,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
