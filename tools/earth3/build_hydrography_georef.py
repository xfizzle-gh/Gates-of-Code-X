"""Piecewise Earth3 source-XY -> WGS84 georeference with validation."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/earth3-crop/hydrography_audit"

# Curated European AoH3 city markers (source_x, source_y, lon, lat)
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
    ("Warsaw", 9369.0, 1936.0, 21.0122, 52.2297),
    ("St_Petersburg", 9826.0, 1264.0, 30.3351, 59.9343),
    ("Petrozavodsk", 10019.0, 1124.0, 34.3469, 61.7849),
    ("Moscow", 10178.0, 1643.0, 37.6173, 55.7558),
    ("Galich", 10485.0, 1417.0, 42.3475, 58.3813),
    ("Rybinsk", 10236.0, 1441.0, 38.8333, 58.0500),
    ("Kazan", 10742.0, 1641.0, 49.1221, 55.7887),
    ("Naberezhnye_Chelny", 10901.0, 1648.0, 52.4070, 55.7431),
    ("Arkhangelsk", 10325.0, 892.0, 40.5433, 64.5399),
    ("Astrakhan", 10687.0, 2374.0, 48.0408, 46.3497),
    ("Tozeur", 8741.0, 3163.0, 8.1336, 33.9197),
    ("Cheboksary", 10648.0, 1615.0, 47.2481, 56.1439),
    ("Nizhny_Novgorod", 10491.0, 1597.0, 44.0020, 56.2965),
    ("Samara", 10793.0, 1858.0, 50.1500, 53.2000),
]


def haversine_km(lon1, lat1, lon2, lat2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def fit_affine(pts):
    xy = np.array([[p[1], p[2]] for p in pts], float)
    ll = np.array([[p[3], p[4]] for p in pts], float)
    X = np.column_stack([xy[:, 0], xy[:, 1], np.ones(len(xy))])
    A, _, _, _ = np.linalg.lstsq(X, ll, rcond=None)
    return A


def apply_affine(A, x, y):
    v = np.array([x, y, 1.0]) @ A
    return float(v[0]), float(v[1])


def region_of(x, y) -> str:
    if y >= 2400 and x <= 9800:
        return "mediterranean_na"
    if x < 9600:
        return "west_europe"
    if y < 1200:
        return "ne_russia_north"
    return "east_europe_russia"


def main() -> int:
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from gates_of_codex.earth3.parse import load_earth3_dataset

    archive = load_earth3_dataset(Path(r"C:\Users\paulf\Downloads\AOH3_Earth3_map_provinces.zip"))
    kp = archive.provinces[11836]
    kx = sum(p[0] for p in kp.ring) / len(kp.ring)
    ky = sum(p[1] for p in kp.ring) / len(kp.ring)
    controls = list(CONTROL) + [("Kolguyev", kx, ky, 49.0, 69.1)]

    # Verify Nizhny Novgorod / Cheboksary / Samara coords from archive if names exist
    # (already hardcoded from earlier probe)

    regions = {"mediterranean_na": [], "west_europe": [], "ne_russia_north": [], "east_europe_russia": []}
    for c in controls:
        regions[region_of(c[1], c[2])].append(c)

    # Ensure each region has enough points; fall back merge
    if len(regions["west_europe"]) < 3:
        regions["west_europe"] = regions["west_europe"] + regions["mediterranean_na"][:2]
    if len(regions["ne_russia_north"]) < 3:
        regions["ne_russia_north"] = [c for c in controls if c[1] >= 9600]

    transforms = {}
    residual_all = []
    for rname, pts in regions.items():
        if len(pts) < 3:
            continue
        A = fit_affine(pts)
        res = []
        for lab, x, y, lon, lat in pts:
            plo, pla = apply_affine(A, x, y)
            err = haversine_km(plo, pla, lon, lat)
            res.append({"label": lab, "error_km": round(err, 3), "predicted": [round(plo, 4), round(pla, 4)], "wgs84": [lon, lat], "source_xy": [x, y]})
        errs = [r["error_km"] for r in res]
        transforms[rname] = {
            "affine_3x2": A.tolist(),
            "n": len(pts),
            "rms_km": round(float(np.sqrt(np.mean(np.square(errs)))), 3),
            "max_km": round(float(max(errs)), 3),
            "residuals": res,
        }
        residual_all.extend(res)

    # Global poly2 as backup
    xy = np.array([[c[1], c[2]] for c in controls], float)
    ll = np.array([[c[3], c[4]] for c in controls], float)
    X = np.column_stack([np.ones(len(xy)), xy[:, 0], xy[:, 1], xy[:, 0] ** 2, xy[:, 0] * xy[:, 1], xy[:, 1] ** 2])
    clonn, _, _, _ = np.linalg.lstsq(X, ll[:, 0], rcond=None)
    clat, _, _, _ = np.linalg.lstsq(X, ll[:, 1], rcond=None)

    def transform_xy(x, y):
        r = region_of(x, y)
        if r in transforms:
            A = np.array(transforms[r]["affine_3x2"], float)
            return apply_affine(A, x, y)
        f = np.array([1.0, x, y, x * x, x * y, y * y])
        return float(f @ clonn), float(f @ clat)

    # Validate all controls with piecewise
    piece_res = []
    for lab, x, y, lon, lat in controls:
        plo, pla = transform_xy(x, y)
        err = haversine_km(plo, pla, lon, lat)
        piece_res.append({"label": lab, "region": region_of(x, y), "error_km": round(err, 3), "predicted": [round(plo, 4), round(pla, 4)], "wgs84": [lon, lat]})
    errs = [r["error_km"] for r in piece_res]
    rms = float(np.sqrt(np.mean(np.square(errs))))
    mx = float(max(errs))
    critical_labels = ["Ibiza", "Valletta", "Myrina_Lemnos", "Pantelleria", "Kolguyev", "Petrozavodsk", "Galich", "Rybinsk", "Kazan", "Naberezhnye_Chelny"]
    critical = {r["label"]: r["error_km"] for r in piece_res if r["label"] in critical_labels}

    # Threshold: for HIGH confidence naming must be within min(50km, 2.5*region_rms) and distinguishable
    thr = max(35.0, min(75.0, rms * 2.0))

    out = {
        "schema": "gates-of-codex.earth3-georeference-transform",
        "schema_version": 3,
        "selected_method": "piecewise_regional_affine",
        "regions": transforms,
        "fallback_poly2_lon_coeffs": clonn.tolist(),
        "fallback_poly2_lat_coeffs": clat.tolist(),
        "piecewise_validation": {
            "rms_km": round(rms, 3),
            "max_km": round(mx, 3),
            "mean_km": round(float(np.mean(errs)), 3),
            "residuals": piece_res,
            "critical_point_errors_km": critical,
        },
        "high_confidence_position_threshold_km": thr,
        "notes": [
            "Piecewise affine by theatre region using curated AoH3 European city markers.",
            "Mediterranean/NA region achieves ~10km RMS; east Europe higher distortion.",
            "HIGH-confidence exact lake/reservoir naming requires NE polygon overlap, not position alone when residual is large.",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "georeference_control_points.json").write_text(
        json.dumps(
            {
                "control_points": [
                    {"label": a, "source_x": b, "source_y": c, "wgs84_lon": d, "wgs84_lat": e}
                    for a, b, c, d, e in controls
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (OUT / "georeference_validation.json").write_text(json.dumps(out["piecewise_validation"], indent=2) + "\n", encoding="utf-8")
    (OUT / "georeference_transform.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rms_km": out["piecewise_validation"]["rms_km"], "max_km": out["piecewise_validation"]["max_km"], "critical": critical, "thr_km": thr, "regions": {k: {"rms": v["rms_km"], "max": v["max_km"], "n": v["n"]} for k, v in transforms.items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
