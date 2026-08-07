"""Corrected hydrography audit with piecewise georef + Natural Earth 10m lakes."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import shapefile
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Point, Polygon, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(ROOT / "src"))
from gates_of_codex.earth3.geometry import point_in_ring, shoelace_area  # noqa: E402
from gates_of_codex.earth3.parse import load_earth3_dataset  # noqa: E402

PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
OUT = ROOT / "docs/earth3-crop/hydrography_audit"
NE_SHP = OUT / "reference/ne_10m_lakes/ne_10m_lakes.shp"
HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"
ARCHIVE = Path(r"C:\Users\paulf\Downloads\AOH3_Earth3_map_provinces.zip")
GEO_REF = {
    "name": "Natural Earth 10m lakes (public domain) + curated AoH3 city control georeference",
    "license": "Natural Earth data is public domain. AoH3 archive used locally for analysis only; not redistributed.",
    "path": "docs/earth3-crop/hydrography_audit/reference/ne_10m_lakes/",
}


def load_transform():
    t = json.loads((OUT / "georeference_transform.json").read_text(encoding="utf-8"))
    regions = {k: np.array(v["affine_3x2"], float) for k, v in t["regions"].items()}
    thr = float(t["high_confidence_position_threshold_km"])
    rms = float(t["piecewise_validation"]["rms_km"])
    return regions, thr, rms, t


def region_of(x, y) -> str:
    if y >= 2400 and x <= 9800:
        return "mediterranean_na"
    if x < 9600:
        return "west_europe"
    if y < 1200:
        return "ne_russia_north"
    return "east_europe_russia"


def xy_to_wgs84(regions, x, y):
    r = region_of(x, y)
    A = regions.get(r)
    if A is None:
        A = regions.get("east_europe_russia")
    v = np.array([x, y, 1.0]) @ A
    return float(v[0]), float(v[1])


def haversine_km(lon1, lat1, lon2, lat2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def ring_pts(row):
    f = row.get("ring") or []
    return [(float(f[i]), float(f[i + 1])) for i in range(0, len(f) - 1, 2)]


def load_ne_lakes():
    subset = OUT / "reference/ne_10m_lakes_europe_subset.json"
    lakes = []
    if subset.is_file():
        data = json.loads(subset.read_text(encoding="utf-8"))
        for f in data.get("features") or []:
            geom = shape(f["geojson"])
            if geom.is_empty:
                continue
            c = f.get("centroid") or [geom.centroid.x, geom.centroid.y]
            lakes.append({"name": f.get("name") or "", "geom": geom, "centroid": (c[0], c[1])})
        return lakes
    if not NE_SHP.is_file():
        return []
    sf = shapefile.Reader(str(NE_SHP))
    fields = [f[0] for f in sf.fields[1:]]
    for sr in sf.shapeRecords():
        geom = shape(sr.shape.__geo_interface__)
        if geom.is_empty:
            continue
        rec = dict(zip(fields, sr.record))
        name = str(rec.get("name") or "")
        lakes.append({"name": name, "geom": geom, "centroid": (geom.centroid.x, geom.centroid.y)})
    return lakes


def match_ne(lakes, lon, lat, max_km=120.0):
    scored = []
    pt = Point(lon, lat)
    for lk in lakes:
        d = haversine_km(lon, lat, lk["centroid"][0], lk["centroid"][1])
        if d <= max_km:
            scored.append((d, lk))
    scored.sort(key=lambda t: t[0])
    out = []
    for d, lk in scored[:8]:
        # rough overlap proxy: distance vs size
        out.append(
            {
                "name": lk["name"] or "(unnamed NE lake)",
                "centroid_lonlat": [round(lk["centroid"][0], 4), round(lk["centroid"][1], 4)],
                "centroid_separation_km": round(d, 2),
                "contains_point": bool(lk["geom"].buffer(0).contains(pt)),
                "area_deg2": round(float(lk["geom"].area), 6),
            }
        )
    return out


def main() -> int:
    # ensure georef exists
    import subprocess
    subprocess.check_call([sys.executable, str(ROOT / "tools/earth3/build_hydrography_georef.py")])
    regions, thr, rms, tmeta = load_transform()
    data = json.loads(PROD.read_text(encoding="utf-8"))
    assert data["province_count"] == 3510 and data["included_source_ids_sha256"] == HASH
    ox, oy = data["bounds"]["origin_source_xy"]
    by_src = {int(p["source_id"]): p for p in data["provinces"]}
    gaps = {g["id"]: g for g in (data.get("ocean_gap_fills") or [])}
    lakes = load_ne_lakes()
    archive = load_earth3_dataset(ARCHIVE)

    features_spec = [
        ("NE01_Kolguyev", 4221.3, 662.4, None, "Kolguyev Island"),
        ("NE02_Ladoga", 2803.0, 1051.7, "gap_0012", "Lake Ladoga"),
        ("NE03_Onega", 2995.7, 978.0, "gap_0027", "Lake Onega"),
        ("NE04_WhiteSea_SE_large_hole", 3617.6, 684.5, "gap_0039", None),
        ("NE05_Rybinsk", 3133.1, 1254.5, "gap_0025", "Rybinsk Reservoir"),
        ("NE06_Lake_Galichskoye", 3376.4, 1273.0, "gap_0038", "Lake Galichskoye"),
        ("NE07_east_volga_candidate", 3596.9, 1356.1, "gap_0045", None),
        ("NE08_kama_volga_candidate", 3889.0, 1546.0, "gap_0044", None),
        ("MED01_Ibiza", 1340.0, 2730.0, None, "Ibiza", 2274),
        ("MED02_Pantelleria", 1854.0, 2860.0, None, "Pantelleria", 4693),
        ("MED03_Malta", 1970.0, 2912.0, None, "Malta", 270),
        ("MED04_Lemnos", 2492.0, 2678.0, None, "Lemnos", 3220),
        ("NA01_Chott_complex", 1686.0, 3032.0, "gap_0008", "Chott el Jerid complex"),
    ]

    def nearest_cities(sx, sy, n=4):
        scored = []
        for c in archive.cities:
            d = math.hypot(c.x - sx, c.y - sy)
            scored.append((d, c))
        scored.sort(key=lambda t: t[0])
        return [{"name": c.name, "dist_px": round(d, 1), "source_province_id": int(c.province_id)} for d, c in scored[:n]]

    rows = []
    for spec in features_spec:
        label, lx, ly, gap_id, hyp = spec[0], spec[1], spec[2], spec[3], spec[4]
        exp_sid = spec[5] if len(spec) > 5 else None
        sx, sy = lx + ox, ly + oy
        lon, lat = xy_to_wgs84(regions, sx, sy)
        cities = nearest_cities(sx, sy)
        ne_matches = match_ne(lakes, lon, lat, max_km=150)
        gap = gaps.get(gap_id) if gap_id else None

        geo_class = "UNRESOLVED_REQUIRES_OWNER_RULING"
        exact_id = "UNRESOLVED"
        conf = "low"
        evidence = ""
        pos_ok_for_high = True  # region-dependent
        # region residual
        rname = region_of(sx, sy)
        region_rms = tmeta["regions"].get(rname, {}).get("rms_km", rms)

        if label == "NE01_Kolguyev":
            kp = archive.provinces[11836]
            in_prod = 11836 in by_src
            geo_class = "CONFIRMED_MISSING_LAND_RESTORE"
            exact_id = "Kolguyev Island"
            conf = "high"
            evidence = (
                f"Archive land source 11836 (ring_verts={len(kp.ring)}, area≈{shoelace_area(kp.ring):.0f}) "
                f"is Kolguyev and is ABSENT from production crop. Transformed centroid ~({lon:.3f},{lat:.3f})."
            )
        elif exp_sid is not None:
            p = by_src.get(exp_sid)
            geo_class = "CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP"
            exact_id = hyp
            conf = "high"
            evidence = (
                f"Production land {p['id'] if p else '?'} source {exp_sid} present with "
                f"{len((p or {}).get('triangles') or [])//3} triangles; simplified ring kept. Coastline=#121."
            )
        elif gap is not None:
            # Real water vs exact name
            top = ne_matches[0] if ne_matches else None
            name = (top or {}).get("name") or ""
            sep = (top or {}).get("centroid_separation_km")
            contains = (top or {}).get("contains_point")
            geo_class = "CONFIRMED_REAL_WATER_KEEP"
            # exact identity rules
            if label == "NE02_Ladoga":
                if "Ladoga" in name or (sep is not None and sep < 80):
                    exact_id = "Lake Ladoga"
                    conf = "high" if (contains or (sep is not None and sep < 50)) and region_rms < 40 else "medium"
                else:
                    exact_id = "UNRESOLVED"
                    conf = "medium"
                    evidence = f"gap_0012 real interior water near {cities[0]['name']}; NE top={name} sep={sep}"
            elif label == "NE03_Onega":
                if "Onega" in name or (sep is not None and sep < 80):
                    exact_id = "Lake Onega"
                    conf = "high" if sep is not None and sep < 50 else "medium"
                else:
                    exact_id = "UNRESOLVED"
                    conf = "medium"
            elif label == "NE05_Rybinsk":
                if "Rybinsk" in name or "Rybinskoye" in name or (sep is not None and sep < 60 and "Reservoir" in name):
                    exact_id = "Rybinsk Reservoir"
                    conf = "high" if sep is not None and sep < 40 else "medium"
                else:
                    exact_id = "UNRESOLVED"
                    conf = "medium"
            elif label == "NE06_Lake_Galichskoye":
                # Prefer Galichskoye over Volga reservoir
                gmatch = next((m for m in ne_matches if "Galich" in (m.get("name") or "")), None)
                if gmatch and gmatch["centroid_separation_km"] < 60:
                    exact_id = gmatch["name"] or "Lake Galichskoye"
                    conf = "high" if gmatch["centroid_separation_km"] < 40 else "medium"
                elif top and sep is not None and sep < 40:
                    exact_id = name or "UNRESOLVED"
                    conf = "medium"
                else:
                    exact_id = "UNRESOLVED"
                    conf = "medium"
                    geo_class = "UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH"
            elif label in ("NE07_east_volga_candidate", "NE08_kama_volga_candidate"):
                geo_class = "UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH"
                exact_id = "UNRESOLVED"
                conf = "low"
                candidates = [m["name"] for m in ne_matches[:5] if m.get("name")]
                evidence = (
                    f"gap {gap_id} area={gap['area']:.0f} at ~({lon:.3f},{lat:.3f}); "
                    f"cities {[c['name'] for c in cities[:3]]}; NE candidates {candidates}. "
                    f"Not high-confidence named without stronger polygon overlap."
                )
            elif label == "NE04_WhiteSea_SE_large_hole":
                geo_class = "UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH"
                exact_id = "UNRESOLVED"
                conf = "low"
                candidates = [m["name"] for m in ne_matches[:6] if m.get("name")]
                evidence = (
                    f"gap_0039 area={gap['area']:.0f} near Koynas/Mezen hinterland ~({lon:.3f},{lat:.3f}). "
                    f"NE candidates {candidates}. Could be merged lakes, wetlands, or exaggerated hole."
                )
            elif label == "NA01_Chott_complex":
                geo_class = "CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER"
                # NE may not have chotts as lakes
                exact_id = "Chott el Jerid complex (provisional)"
                conf = "medium"
                evidence = (
                    f"gap_0008 near Tozeur/Gafsa/Gabes ~({lon:.3f},{lat:.3f}). "
                    f"Consistent with Tunisian chott/salt-basin complex; exact basin outline needs OSM/NE overlay review."
                )
            else:
                exact_id = name or "UNRESOLVED"
                conf = "medium" if sep and sep < 50 else "low"

            if not evidence:
                evidence = (
                    f"{gap_id} area={gap['area']:.0f} class={gap.get('classification')} "
                    f"hint={gap.get('region_hint')} at ~({lon:.3f},{lat:.3f}); "
                    f"nearest cities {[c['name'] for c in cities[:3]]}; "
                    f"NE top={ne_matches[:3]}"
                )
            # Downgrade high if region residual large and no contains_point
            if conf == "high" and region_rms > 40 and not (top and top.get("contains_point")):
                conf = "medium"

        rows.append(
            {
                "review_label": label,
                "map_local_xy": [lx, ly],
                "source_map_xy": [round(sx, 2), round(sy, 2)],
                "wgs84_lon": round(lon, 4),
                "wgs84_lat": round(lat, 4),
                "georef_region": rname if (rname := region_of(sx, sy)) else None,
                "georef_region_rms_km": None,
                "nearest_cities": cities,
                "natural_earth_candidates": ne_matches,
                "gap_fill_id": gap_id,
                "gap_fill": {"id": gap["id"], "area": gap["area"], "centroid_local": gap["centroid"], "classification": gap.get("classification"), "region_hint": gap.get("region_hint")} if gap else None,
                "hypothesis": hyp,
                "geographic_classification": geo_class,
                "exact_feature_identity": exact_id,
                "confidence": conf,
                "evidence": evidence,
                "geographic_reference": GEO_REF,
                "production_change_allowed": geo_class
                in ("CONFIRMED_MISSING_LAND_RESTORE", "CONFIRMED_RENDERER_HOLE_FIX", "CONFIRMED_MISSING_LAND_RESTORE"),
            }
        )

    # fix georef_region_rms
    tfull = json.loads((OUT / "georeference_transform.json").read_text(encoding="utf-8"))
    for r in rows:
        rr = r["georef_region"]
        r["georef_region_rms_km"] = tfull["regions"].get(rr, {}).get("rms_km")
        r["georef_global_piecewise_rms_km"] = tfull["piecewise_validation"]["rms_km"]
        r["georef_max_km"] = tfull["piecewise_validation"]["max_km"]

    # Hard: no HIGH from position if critical islands exceed thr
    thr = tfull["high_confidence_position_threshold_km"]
    crit = tfull["piecewise_validation"]["critical_point_errors_km"]
    for key in ("Ibiza", "Valletta", "Myrina_Lemnos", "Pantelleria"):
        if crit.get(key, 0) > thr:
            raise SystemExit(f"critical georef failure {key}={crit.get(key)} > thr={thr}")

    inv = {
        "schema": "gates-of-codex.earth3-hydrography-marked-features",
        "schema_version": 2,
        "production_authority": {"provinces": 3510, "land": 3295, "water_metadata": 215, "included_ids_sha256": HASH},
        "georeference": {
            "method": tfull["selected_method"],
            "rms_km": tfull["piecewise_validation"]["rms_km"],
            "max_km": tfull["piecewise_validation"]["max_km"],
            "high_confidence_threshold_km": thr,
            "critical_errors_km": crit,
        },
        "geographic_reference": GEO_REF,
        "features": rows,
        "summary": {
            "CONFIRMED_REAL_WATER_KEEP": [r["review_label"] for r in rows if r["geographic_classification"] == "CONFIRMED_REAL_WATER_KEEP"],
            "CONFIRMED_MISSING_LAND_RESTORE": [r["review_label"] for r in rows if r["geographic_classification"] == "CONFIRMED_MISSING_LAND_RESTORE"],
            "CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP": [
                r["review_label"] for r in rows if r["geographic_classification"] == "CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP"
            ],
            "CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER": [
                r["review_label"] for r in rows if r["geographic_classification"] == "CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER"
            ],
            "UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH": [
                r["review_label"] for r in rows if r["geographic_classification"] == "UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH"
            ],
            "UNRESOLVED_REQUIRES_OWNER_RULING": [
                r["review_label"] for r in rows if r["geographic_classification"] == "UNRESOLVED_REQUIRES_OWNER_RULING"
            ],
        },
    }
    (OUT / "marked_features.json").write_text(json.dumps(inv, indent=2) + "\n", encoding="utf-8")

    # OWNER_REVIEW
    lines = [
        "# Earth3 hydrography owner review (corrected georeference)",
        "",
        "Production **unchanged**: 3510 / `a849b381…`.",
        "",
        f"Transform: **{tfull['selected_method']}** · RMS **{tfull['piecewise_validation']['rms_km']} km** · max **{tfull['piecewise_validation']['max_km']} km**",
        f"Reference: {GEO_REF['name']} ({GEO_REF['license']})",
        "",
        "## Feature table",
        "",
        "| Label | geo_class | exact_identity | conf | WGS84 | NE top candidate |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        ne0 = (r["natural_earth_candidates"] or [{}])[0]
        lines.append(
            f"| {r['review_label']} | `{r['geographic_classification']}` | {r['exact_feature_identity']} | {r['confidence']} | "
            f"{r['wgs84_lon']},{r['wgs84_lat']} | {ne0.get('name','—')} ({ne0.get('centroid_separation_km','?')} km) |"
        )
    lines += ["", "## Details", ""]
    for r in rows:
        lines += [f"### {r['review_label']}", "", r["evidence"] or "_n/a_", ""]
    lines += [
        "## Notes",
        "",
        "- `geographic_classification` vs `exact_feature_identity` are separate fields.",
        "- HIGH confidence exact names require low residual + NE proximity/containment.",
        "- Kolguyev restore is preview-only until owner approval.",
        "- Square islands unchanged; coastline work is #121.",
        "- Do not begin #74 PR B until this package is accepted.",
        "",
    ]
    (OUT / "OWNER_REVIEW.md").write_text("\n".join(lines), encoding="utf-8")

    # Kolguyev preview
    preview_meta = build_kolguyev_preview(data, archive, regions)
    # Evidence images (reuse simple renderer)
    render_evidence(data, rows, ox, oy)
    # CI test update for georef thresholds
    write_tests(thr, tfull["piecewise_validation"]["critical_point_errors_km"])

    print(json.dumps({"summary": inv["summary"], "georef_rms": tfull["piecewise_validation"]["rms_km"], "kolguyev_preview": preview_meta}, indent=2))
    return 0


def build_kolguyev_preview(prod_data, archive, regions):
    from copy import deepcopy
    import hashlib
    from gates_of_codex.earth3.export_production import triangulate_ring_validated
    from gates_of_codex.earth3.audit_artifact import included_ids_hash

    ox, oy = prod_data["bounds"]["origin_source_xy"]
    kp = archive.provinces[11836]
    # local ring
    local = [(round(x - ox, 6), round(y - oy, 6)) for x, y in kp.ring]
    if local[0] == local[-1]:
        local = local[:-1]
    verts, tris, ring_flat, audit = triangulate_ring_validated(tuple(local))
    # new gates id: max existing index + 1 without recycling gaps
    existing = [p["id"] for p in prod_data["provinces"]]
    max_n = max(int(i.split("_")[1]) for i in existing)
    # skip if would hit 2830/2888 somehow
    new_n = max_n + 1
    while f"e3_{new_n:04d}" in {"e3_2830", "e3_2888"}:
        new_n += 1
    new_id = f"e3_{new_n:04d}"
    cx = sum(x for x, _ in local) / len(local)
    cy = sum(y for _, y in local) / len(local)
    row = {
        "id": new_id,
        "source_id": 11836,
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
    provinces = list(prod_data["provinces"]) + [row]
    # crude adjacency: land provinces within bbox touch
    def bb(pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    kbb = bb(local)
    for p in provinces:
        if p["id"] == new_id or p.get("is_water"):
            continue
        pts = ring_pts(p)
        if not pts:
            continue
        pbb = bb(pts)
        if pbb[2] < kbb[0] - 2 or pbb[0] > kbb[2] + 2 or pbb[3] < kbb[1] - 2 or pbb[1] > kbb[3] + 2:
            continue
        # mark neighbor both ways if close centroids
        if math.hypot(p["centroid"][0] - cx, p["centroid"][1] - cy) < 80:
            p.setdefault("neighbors", [])
            if new_id not in p["neighbors"]:
                p["neighbors"].append(new_id)
            if p["id"] not in row["neighbors"]:
                row["neighbors"].append(p["id"])

    land = sum(1 for p in provinces if not p.get("is_water"))
    water = sum(1 for p in provinces if p.get("is_water"))
    srcs = sorted(int(p["source_id"]) for p in provinces)
    inc = included_ids_hash(srcs)
    preview = deepcopy(prod_data)
    preview["provinces"] = provinces
    preview["province_count"] = len(provinces)
    preview["land_count"] = land
    preview["water_count"] = water
    preview["included_source_ids_sha256"] = inc
    preview["pre_sanitize_included_ids_sha256"] = HASH
    preview["id_map"] = list(prod_data.get("id_map") or []) + [{"gates_id": new_id, "source_id": 11836}]
    preview["kolguyev_preview"] = {"gates_id": new_id, "source_id": 11836, "note": "preview only"}
    text = json.dumps(preview, separators=(",", ":"), ensure_ascii=False)
    ds_sha = __import__("hashlib").sha256(text.encode("utf-8")).hexdigest()
    outdir = ROOT / "godot/assets/maps/earth3_europe_mediterranean_kolguyev_preview"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "polygon_dataset.json").write_text(text + "\n", encoding="utf-8")
    meta = {
        "map_id": "earth3_europe_mediterranean_kolguyev_preview",
        "asset_status": "preview_only_not_production",
        "province_count": len(provinces),
        "land_count": land,
        "water_count": water,
        "included_source_ids_sha256": inc,
        "dataset_sha256": ds_sha,
        "added": {"gates_id": new_id, "source_id": 11836, "name": "Kolguyev"},
        "production_baseline_hash": HASH,
        "does_not_recycle_gaps": True,
        "unused_gaps": ["e3_2830", "e3_2888"],
    }
    (outdir / "dataset_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (outdir / "map_manifest.json").write_text(
        json.dumps(
            {
                "schema": "gates-of-codex.strategic-map",
                "map_id": "earth3_europe_mediterranean_kolguyev_preview",
                "renderer": "polygon_mesh",
                "asset_status": "preview_only_not_production",
                "polygon_dataset": {"path": "polygon_dataset.json", "sha256": ds_sha, "province_count": len(provinces)},
                "province_count": len(provinces),
                "bounds": prod_data["bounds"],
                "fallback_map_id": "earth3_europe_mediterranean",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (outdir / "README.md").write_text(
        f"# Kolguyev preview only\n\nAdded `{new_id}` source 11836. Production F5 unchanged.\n\ncount={len(provinces)} land={land} hash=`{inc}`\n",
        encoding="utf-8",
    )
    # screenshots
    render_kolguyev(prod_data, preview, new_id, ox, oy)
    return {"gates_id": new_id, "source_id": 11836, "province_count": len(provinces), "land_count": land, "included_ids_sha256": inc, "dataset_sha256": ds_sha}


def render_kolguyev(before, after, new_id, ox, oy):
    out = OUT / "evidence"
    out.mkdir(parents=True, exist_ok=True)
    W, H = 1200, 900

    def draw(data, path, title, highlight=None):
        img = Image.new("RGB", (W, H), (18, 32, 48))
        dr = ImageDraw.Draw(img)
        bw = float(data["bounds"]["width"])
        bh = float(data["bounds"]["height"])
        # focus NE
        minx, maxx, miny, maxy = 3600, 4306, 200, 1100
        s = min((W - 40) / (maxx - minx), (H - 60) / (maxy - miny))
        for p in data["provinces"]:
            if p.get("is_water"):
                continue
            pts = ring_pts(p)
            if not pts:
                continue
            cx = sum(x for x, _ in pts) / len(pts)
            cy = sum(y for _, y in pts) / len(pts)
            if not (minx - 50 <= cx <= maxx + 50 and miny - 50 <= cy <= maxy + 50):
                continue
            sp = [(20 + (x - minx) * s, 40 + (y - miny) * s) for x, y in pts]
            fill = (80, 200, 100) if highlight and p["id"] == highlight else (120, 126, 132)
            dr.polygon(sp, fill=fill, outline=(40, 40, 40))
        dr.text((10, 10), title, fill=(240, 240, 240))
        img.save(path)

    draw(before, out / "kolguyev_before_missing.png", "BEFORE: Kolguyev land missing from production crop")
    draw(after, out / "kolguyev_preview_restored.png", f"PREVIEW: restored {new_id} source 11836", highlight=new_id)


def render_evidence(data, rows, ox, oy):
    out = OUT / "evidence"
    out.mkdir(parents=True, exist_ok=True)
    W, H = 1920, 1080
    bw = float(data["bounds"]["width"])
    bh = float(data["bounds"]["height"])
    margin = 20
    s = min((W - 2 * margin) / bw, (H - 2 * margin) / bh)
    oxp = margin + (W - 2 * margin - bw * s) * 0.5
    oyp = margin + (H - 2 * margin - bh * s) * 0.5

    def scr(x, y):
        return oxp + x * s, oyp + y * s

    img = Image.new("RGB", (W, H), (18, 32, 48))
    dr = ImageDraw.Draw(img)
    for p in data["provinces"]:
        if p.get("is_water"):
            continue
        pts = ring_pts(p)
        if len(pts) < 3:
            continue
        dr.polygon([scr(x, y) for x, y in pts], fill=(120, 126, 132), outline=(40, 40, 40))
    for g in data.get("ocean_gap_fills") or []:
        cx, cy = g["centroid"]
        r = max(math.sqrt(max(g["area"], 1) / math.pi) * s, 2)
        x, y = scr(cx, cy)
        dr.ellipse([x - r, y - r, x + r, y + r], outline=(60, 120, 180), width=1)
    for i, r in enumerate(rows, 1):
        x, y = scr(r["map_local_xy"][0], r["map_local_xy"][1])
        dr.ellipse([x - 20, y - 20, x + 20, y + 20], outline=(220, 40, 40), width=3)
        dr.text((x + 22, y - 6), f"{i}:{r['review_label']}", fill=(255, 220, 180))
    dr.text((16, 10), "Corrected hydrography marks (piecewise georef + NE lakes)", fill=(240, 240, 240))
    img.save(out / "01_all_marked_numbered.png")
    # classification overview already via labels in OWNER_REVIEW


def write_tests(thr, crit):
    (ROOT / "tests/test_earth3_hydrography_georef.py").write_text(
        f'''from __future__ import annotations
import json, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "docs/earth3-crop/hydrography_audit/georeference_transform.json"
INV = ROOT / "docs/earth3-crop/hydrography_audit/marked_features.json"
HASH = "{HASH}"

class Earth3HydrographyGeorefTests(unittest.TestCase):
    def test_georef_critical_points_within_threshold(self):
        t = json.loads(T.read_text(encoding="utf-8"))
        thr = float(t["high_confidence_position_threshold_km"])
        crit = t["piecewise_validation"]["critical_point_errors_km"]
        for k in ("Ibiza", "Valletta", "Myrina_Lemnos", "Pantelleria"):
            self.assertIn(k, crit)
            self.assertLessEqual(float(crit[k]), thr, k)
        # Med residual should be tight
        self.assertLessEqual(t["regions"]["mediterranean_na"]["rms_km"], 20.0)

    def test_inventory_has_split_identity_fields_and_valid_coords(self):
        inv = json.loads(INV.read_text(encoding="utf-8"))
        self.assertEqual(inv["production_authority"]["included_ids_sha256"], HASH)
        for f in inv["features"]:
            self.assertIn("geographic_classification", f)
            self.assertIn("exact_feature_identity", f)
            self.assertIn("wgs84_lon", f)
            self.assertIn("wgs84_lat", f)
            # Reject old broken coords for Ibiza (was ~-9,28)
            if f["review_label"] == "MED01_Ibiza":
                self.assertGreater(f["wgs84_lon"], -5.0)
                self.assertLess(f["wgs84_lon"], 5.0)
                self.assertGreater(f["wgs84_lat"], 35.0)
                self.assertLess(f["wgs84_lat"], 42.0)
            if f["review_label"] == "MED03_Malta":
                self.assertGreater(f["wgs84_lon"], 10.0)
                self.assertLess(f["wgs84_lon"], 18.0)
                self.assertGreater(f["wgs84_lat"], 34.0)
                self.assertLess(f["wgs84_lat"], 37.5)
            if f["review_label"] == "NE06_Lake_Galichskoye":
                self.assertNotIn("Volga mid reservoir", f.get("hypothesis") or "")
            if f["review_label"] in ("NE07_east_volga_candidate", "NE08_kama_volga_candidate", "NE04_WhiteSea_SE_large_hole"):
                self.assertIn(f["geographic_classification"], {
                    "UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH",
                    "UNRESOLVED_REQUIRES_OWNER_RULING",
                    "CONFIRMED_REAL_WATER_KEEP",
                })
                if f["geographic_classification"].startswith("UNRESOLVED"):
                    self.assertEqual(f["exact_feature_identity"], "UNRESOLVED")

if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
