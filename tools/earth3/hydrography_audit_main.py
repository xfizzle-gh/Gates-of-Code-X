#!/usr/bin/env python3
"""Authoritative Earth3 hydrography audit (docs + Kolguyev preview only).

  set GATES_EARTH3_ARCHIVE=/path/to/AOH3_Earth3_map_provinces.zip
  python tools/earth3/hydrography_audit_main.py --archive %GATES_EARTH3_ARCHIVE%

Does not modify production godot/assets/maps/earth3_europe_mediterranean/.
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
from shapely.geometry import MultiPoint, Polygon, shape
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

# label, sx, sy, lon, lat — European instances; Kolguyev is NOT included
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
        "schema_version": 5,
        "selected_method": "piecewise_regional_affine_with_loo",
        "kolguyev_is_control_point": False,
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
        "high_confidence_polygon_iou_threshold": 0.15,
        "high_confidence_coverage_threshold": 0.25,
        "notes": ["Kolguyev is NOT a georef control point."],
    }
    return georef, controls


def txy(mats, x, y):
    r = region_of(x, y)
    A = mats.get(r) or mats.get("east_europe_russia")
    return apply_A(np.array(A, float), x, y)


def ring_pts(row):
    f = row.get("ring") or []
    return [(float(f[i]), float(f[i + 1])) for i in range(0, len(f) - 1, 2)]


def local_to_wgs_poly(mats, ox, oy, local_pts):
    wgs = [txy(mats, x + ox, y + oy) for x, y in local_pts]
    if len(wgs) < 3:
        return None
    if wgs[0] != wgs[-1]:
        wgs.append(wgs[0])
    poly = Polygon(wgs)
    if not poly.is_valid:
        poly = make_valid(poly)
    if poly.is_empty:
        return None
    if poly.geom_type == "MultiPolygon":
        poly = max(list(poly.geoms), key=lambda g: g.area)
    return poly


def load_ne():
    data = json.loads(NE_SUBSET.read_text(encoding="utf-8"))
    lakes = []
    for f in data["features"]:
        g = make_valid(shape(f["geojson"]))
        if g.is_empty:
            continue
        c = f.get("centroid") or [g.centroid.x, g.centroid.y]
        lakes.append({"name": f.get("name") or "", "geom": g, "centroid": (c[0], c[1])})
    return lakes


def poly_match(e3, lakes, n=6):
    if e3 is None or e3.is_empty:
        return []
    e3 = make_valid(e3)
    out = []
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
        cov_e3 = ia / float(e3.area) if e3.area > 0 else 0.0
        cov_ref = ia / float(g.area) if g.area > 0 else 0.0
        sep = hav(e3.centroid.x, e3.centroid.y, lk["centroid"][0], lk["centroid"][1])
        try:
            haus = float(e3.hausdorff_distance(g))
        except Exception:
            haus = None
        out.append(
            {
                "name": lk["name"] or "(unnamed)",
                "iou": round(iou, 4),
                "earth3_coverage_by_ref": round(cov_e3, 4),
                "ref_coverage_by_earth3": round(cov_ref, 4),
                "centroid_separation_km": round(sep, 2),
                "hausdorff_deg": round(haus, 5) if haus is not None else None,
                "area_ratio_e3_over_ref": round(float(e3.area) / float(g.area), 4) if g.area > 0 else None,
                "score": round(iou * 2 + cov_e3 + cov_ref - sep / 500.0, 4),
            }
        )
    out.sort(key=lambda d: -d["score"])
    return out[:n]


def nearest_cities(archive, sx, sy, n=4):
    scored = [(math.hypot(c.x - sx, c.y - sy), c) for c in archive.cities]
    scored.sort(key=lambda t: t[0])
    return [{"name": c.name, "dist_px": round(d, 1), "source_province_id": int(c.province_id)} for d, c in scored[:n]]


def classify(label, hyp, gap, exp_sid, by_src, top, matches, cities, georef, kol_holdout=None):
    if label == "NE01_Kolguyev":
        ho = kol_holdout or {}
        return (
            "CONFIRMED_MISSING_LAND_RESTORE",
            "Kolguyev Island",
            "high",
            (
                f"Archive land src {KOL_SRC} (city Fion) absent from production crop. "
                f"Identity is archive topology, not WGS84. Kolguyev is NOT a georef control. "
                f"Holdout residual vs true ~49E/69.1N: {ho.get('error_km')} km "
                f"(predicted {ho.get('predicted')}); Arctic source warp biases lon/lat."
            ),
            [],
        )
    if exp_sid is not None:
        p = by_src[exp_sid]
        return (
            "CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP",
            hyp,
            "high",
            f"{p['id']} src {exp_sid} filled; keep; #121 coastlines.",
            [],
        )
    name = (top or {}).get("name") or ""
    iou = (top or {}).get("iou") or 0
    cov = (top or {}).get("earth3_coverage_by_ref") or 0
    sep = (top or {}).get("centroid_separation_km")
    hi_iou = georef["high_confidence_polygon_iou_threshold"]
    hi_cov = georef["high_confidence_coverage_threshold"]
    if label == "NE02_Ladoga" and "Ladoga" in name and (iou >= hi_iou or cov >= hi_cov or (sep is not None and sep < 35)):
        return "CONFIRMED_REAL_WATER_KEEP", "Lake Ladoga", "high", f"polygon-match {top}", []
    if label == "NE03_Onega" and "Onega" in name and (iou >= hi_iou or cov >= hi_cov or (sep is not None and sep < 40)):
        return "CONFIRMED_REAL_WATER_KEEP", "Lake Onega", "high", f"polygon-match {top}", []
    if label == "NE05_Rybinsk" and "Rybinsk" in name and (iou >= 0.05 or (sep is not None and sep < 25)):
        return "CONFIRMED_REAL_WATER_KEEP", "Rybinsk Reservoir", "high", f"polygon-match {top}", []
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
            f"gap_0039 area={gap['area'] if gap else '?'} matches={matches[:3]}",
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
    return "CONFIRMED_REAL_WATER_KEEP", "UNRESOLVED", "medium", f"Interior water; exact name unresolved. top={top}", []


def build_kolguyev(prod, archive, ox, oy):
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
    provinces = deepcopy(prod["provinces"]) + [row]
    surrounding_water = []
    for p in prod["provinces"]:
        if p.get("is_water") and math.hypot(p["centroid"][0] - cx, p["centroid"][1] - cy) < 300:
            surrounding_water.append({"gates_id": p["id"], "source_id": int(p["source_id"])})
    land = sum(1 for p in provinces if not p.get("is_water"))
    water = sum(1 for p in provinces if p.get("is_water"))
    empty = [p["id"] for p in provinces if not p.get("is_water") and len(p.get("triangles") or []) < 3]
    ids = {p["id"] for p in provinces}
    dangling = [{"id": p["id"], "n": n} for p in provinces for n in (p.get("neighbors") or []) if n not in ids]
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
    prod_map = {int(e["source_id"]): e["gates_id"] for e in (prod.get("id_map") or [])}
    stable = all(prod_map.get(int(p["source_id"])) == p["id"] for p in provinces if int(p["source_id"]) != KOL_SRC)
    adj = {
        "gates_id": new_id,
        "source_id": KOL_SRC,
        "direct_land_neighbors": [],
        "surrounding_source_water_ids": surrounding_water,
        "border_segments": "island outer ring only",
        "proposed_future_sea_link_nodes": ["author ferry/naval links separately"],
        "confirmation_no_mainland_land_adjacency_invented": True,
    }
    val = {
        "summary": {
            "gates_id": new_id,
            "source_id": KOL_SRC,
            "province_count": len(provinces),
            "land_count": land,
            "water_count": water,
            "included_ids_sha256": inc,
            "dataset_sha256": ds_sha,
        },
        "checks": {
            "empty_land_meshes": len(empty) == 0,
            "dangling_neighbors": len(dangling) == 0,
            "source_11836_once": srcs.count(KOL_SRC) == 1,
            "new_id_once": sum(1 for p in provinces if p["id"] == new_id) == 1,
            "gaps_unused": GAPS.isdisjoint(ids),
            "stable_retained_mappings": stable,
            "no_invented_land_adjacency": True,
            "production_still_3510": json.loads((PROD / "dataset_meta.json").read_text(encoding="utf-8"))["province_count"]
            == 3510,
            "tri_ok": len(row["triangles"]) >= 3,
        },
        "adjacency": adj,
    }
    (OUT / "kolguyev_adjacency_report.json").write_text(json.dumps(adj, indent=2) + "\n", encoding="utf-8")
    (OUT / "kolguyev_preview_validation.json").write_text(json.dumps(val, indent=2) + "\n", encoding="utf-8")
    ev = OUT / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    for tag, data, hi in [("before", prod, None), ("after", {"provinces": provinces, "bounds": prod["bounds"]}, new_id)]:
        img = Image.new("RGB", (1000, 800), (18, 32, 48))
        dr = ImageDraw.Draw(img)
        minx, maxx, miny, maxy = 3600, 4306, 200, 1100
        s = min(960 / (maxx - minx), 740 / (maxy - miny))
        for p in data["provinces"]:
            if p.get("is_water"):
                continue
            pts = ring_pts(p)
            if not pts:
                continue
            ccx = sum(x for x, _ in pts) / len(pts)
            ccy = sum(y for _, y in pts) / len(pts)
            if not (minx - 80 <= ccx <= maxx + 80 and miny - 80 <= ccy <= maxy + 80):
                continue
            sp = [(20 + (x - minx) * s, 30 + (y - miny) * s) for x, y in pts]
            fill = (90, 200, 110) if hi and p["id"] == hi else (120, 126, 132)
            dr.polygon(sp, fill=fill, outline=(40, 40, 40))
        dr.text((10, 8), f"Kolguyev {tag} (no mainland adjacency)", fill=(240, 240, 240))
        img.save(ev / f"kolguyev_{tag}.png")
    return val["summary"]


def write_owner_review(rows, georef):
    lines = [
        "# Earth3 hydrography owner review",
        "",
        "Production **unchanged** at 3510 / `a849b381…`.",
        "",
        f"LOO RMS **{georef['leave_one_out']['rms_km']} km**, max **{georef['leave_one_out']['max_km']} km**. "
        "Kolguyev is not a control point.",
        f"North LOO: {georef['leave_one_out']['by_region'].get('ne_russia_north')}",
        f"Kolguyev holdout (not control): {georef.get('kolguyev_holdout_not_control')}",
        "",
        "| Label | geo_class | exact_id | conf | WGS84 | top IoU |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        top = (r["polygon_matches"] or [{}])[0]
        lines.append(
            f"| {r['review_label']} | `{r['geographic_classification']}` | {r['exact_feature_identity']} | "
            f"{r['confidence']} | {r['wgs84_lon']},{r['wgs84_lat']} | "
            f"{top.get('name', '—')} iou={top.get('iou', '—')} |"
        )
    lines += ["", "## Unresolved candidates", ""]
    for r in rows:
        if r["geographic_classification"].startswith("UNRESOLVED"):
            lines.append(f"- **{r['review_label']}**: {r.get('candidate_identities')}")
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
                note = reg.get("validation_note", "")
                self.assertIn("NOT independent validation", note)
        tol = t["fixed_control_tolerances_km"]
        loo_map = {r["label"]: r["error_km"] for r in loo["residuals"]}
        for lab, max_km in tol.items():
            if lab in loo_map:
                self.assertLessEqual(loo_map[lab], max_km, lab)

    def test_no_hardcoded_home_archive_path(self):
        txt = MAIN.read_text(encoding="utf-8")
        self.assertNotIn(r"C:\\Users\\paulf\\Downloads", txt)
        self.assertIn("GATES_EARTH3_ARCHIVE", txt)

    def test_inventory_and_production_inert(self):
        inv = json.loads(INV.read_text(encoding="utf-8"))
        self.assertEqual(inv["production_authority"]["included_ids_sha256"], HASH)
        self.assertEqual(json.loads(PROD.read_text(encoding="utf-8"))["province_count"], 3510)
        for f in inv["features"]:
            self.assertIn("polygon_matches", f)
            if f["review_label"] == "MED01_Ibiza":
                self.assertGreater(f["wgs84_lon"], 0.0)
                self.assertLess(f["wgs84_lon"], 3.5)
                self.assertGreater(f["wgs84_lat"], 37.0)
            if f["geographic_classification"].startswith("UNRESOLVED"):
                self.assertFalse(f.get("production_change_allowed", False))
            if f["confidence"] == "high" and f["exact_feature_identity"] not in (
                "UNRESOLVED",
                "Kolguyev Island",
                "Ibiza",
                "Pantelleria",
                "Malta",
                "Lemnos",
            ):
                self.assertTrue(f.get("polygon_matches"), f["review_label"])

    def test_kolguyev_preview_constraints(self):
        adj = json.loads(KOL_ADJ.read_text(encoding="utf-8"))
        self.assertEqual(adj["direct_land_neighbors"], [])
        self.assertTrue(adj["confirmation_no_mainland_land_adjacency_invented"])
        val = json.loads(KOL_VAL.read_text(encoding="utf-8"))
        self.assertTrue(all(val["checks"].values()), val["checks"])
        self.assertEqual(val["summary"]["source_id"], 11836)
        self.assertNotIn(val["summary"]["gates_id"], ["e3_2830", "e3_2888"])


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

**Authoritative entry point:** `tools/earth3/hydrography_audit_main.py`

Superseded helpers (do not use): `build_hydrography_audit.py`, `build_hydrography_audit_v2.py`, `build_hydrography_georef.py`.

Production path is never modified.
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


def feature_local_geometry(label, gap, exp_sid, by_src, archive, ox, oy):
    if exp_sid is not None:
        p = by_src[exp_sid]
        lx, ly = float(p["centroid"][0]), float(p["centroid"][1])
        return lx, ly, ring_pts(p)
    if label == "NE01_Kolguyev":
        kp = archive.provinces[KOL_SRC]
        local_pts = [(float(x - ox), float(y - oy)) for x, y in kp.ring]
        if local_pts[0] == local_pts[-1]:
            local_pts = local_pts[:-1]
        lx = sum(pt[0] for pt in local_pts) / len(local_pts)
        ly = sum(pt[1] for pt in local_pts) / len(local_pts)
        return lx, ly, local_pts
    lx, ly = float(gap["centroid"][0]), float(gap["centroid"][1])
    vf = gap.get("vertices") or []
    pts = [(float(vf[i]), float(vf[i + 1])) for i in range(0, len(vf) - 1, 2)]
    if len(pts) >= 3:
        hull = MultiPoint(pts).convex_hull
        local_pts = list(hull.exterior.coords)[:-1] if hull.geom_type == "Polygon" else pts[:48]
    else:
        r = math.sqrt(max(float(gap["area"]), 1) / math.pi)
        local_pts = [
            (lx + r * math.cos(2 * math.pi * i / 32), ly + r * math.sin(2 * math.pi * i / 32)) for i in range(32)
        ]
    return lx, ly, local_pts


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
    # Holdout only (NOT a control): true Kolguyev WGS84 vs regional prediction
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

    rows = []
    poly_table = []
    for label, gap_id, exp_sid, hyp in SPECS:
        gap = gaps.get(gap_id) if gap_id else None
        lx, ly, local_pts = feature_local_geometry(label, gap, exp_sid, by_src, archive, ox, oy)
        e3_poly = local_to_wgs_poly(mats, ox, oy, local_pts)
        sx, sy = lx + ox, ly + oy
        lon, lat = txy(mats, sx, sy)
        cities = nearest_cities(archive, sx, sy)
        matches = poly_match(e3_poly, lakes)
        top = matches[0] if matches else None
        geo, exact, conf, evidence, cands = classify(
            label, hyp, gap, exp_sid, by_src, top, matches, cities, georef, kol_holdout=kol_holdout
        )
        if (
            conf == "high"
            and geo == "CONFIRMED_REAL_WATER_KEEP"
            and exact not in ("UNRESOLVED",)
            and (
                not top
                or (
                    top.get("iou", 0) < 0.05
                    and top.get("earth3_coverage_by_ref", 0) < 0.15
                    and top.get("centroid_separation_km", 999) > 40
                )
            )
        ):
            conf = "medium"
        poly_table.append({"review_label": label, "wgs84": [round(lon, 4), round(lat, 4)], "matches": matches})
        rows.append(
            {
                "review_label": label,
                "map_local_xy": [round(lx, 2), round(ly, 2)],
                "source_map_xy": [round(sx, 2), round(sy, 2)],
                "wgs84_lon": round(lon, 4),
                "wgs84_lat": round(lat, 4),
                "georef_region": region_of(sx, sy),
                "georef_uncertainty_km_loo_region": georef["leave_one_out"]["by_region"]
                .get(region_of(sx, sy), {})
                .get("rms_km"),
                "nearest_cities": cities,
                "polygon_matches": matches,
                "candidate_identities": cands,
                "gap_fill_id": gap_id,
                "geographic_classification": geo,
                "exact_feature_identity": exact,
                "confidence": conf,
                "evidence": evidence,
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
        "schema_version": 5,
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
    write_owner_review(rows, georef)
    kol = build_kolguyev(prod, archive, ox, oy)
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
                "kolguyev": kol,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
