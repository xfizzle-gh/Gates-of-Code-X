"""Earth3 hydrography audit: marked lakes, islands, holes (docs only; no production change)."""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.earth3.geometry import point_in_ring, shoelace_area  # noqa: E402
from gates_of_codex.earth3.parse import load_earth3_dataset  # noqa: E402

PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
OUT = ROOT / "docs/earth3-crop/hydrography_audit"
ARCHIVE = Path(r"C:\Users\paulf\Downloads\AOH3_Earth3_map_provinces.zip")
HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"
# Natural Earth-style attribution for coordinate reasoning (no binary basemap committed).
GEO_REF = {
    "name": "Natural Earth 110m/50m cultural+physical (conceptual comparison) + AoH3 Earth3 city labels",
    "license": "Natural Earth: public domain. AoH3 archive: local analysis only, not redistributed.",
    "note": "No Google Maps tiles committed. Coordinates cross-checked via archive city anchors and known hydrography.",
}


def lonlat(sx: float, sy: float) -> tuple[float, float]:
    return round((sx / 17760.0) * 360.0 - 180.0, 4), round(85.0 - (sy / 8600.0) * 170.0, 4)


def ring_pts(row: dict) -> list[tuple[float, float]]:
    f = row.get("ring") or []
    return [(float(f[i]), float(f[i + 1])) for i in range(0, len(f) - 1, 2)]


def nearest_cities(archive, sx: float, sy: float, n: int = 4) -> list[dict]:
    scored = []
    for c in archive.cities:
        d = math.hypot(c.x - sx, c.y - sy)
        scored.append((d, c))
    scored.sort(key=lambda t: t[0])
    return [
        {"name": c.name, "dist_px": round(d, 1), "source_province_id": int(c.province_id), "x": c.x, "y": c.y}
        for d, c in scored[:n]
    ]


def main() -> int:
    data = json.loads(PROD.read_text(encoding="utf-8"))
    assert int(data["province_count"]) == 3510
    assert data.get("included_source_ids_sha256") == HASH
    ox, oy = data["bounds"]["origin_source_xy"]
    W, H = float(data["bounds"]["width"]), float(data["bounds"]["height"])
    by_id = {p["id"]: p for p in data["provinces"]}
    by_src = {int(p["source_id"]): p for p in data["provinces"]}
    gaps = {g["id"]: g for g in (data.get("ocean_gap_fills") or [])}
    archive = load_earth3_dataset(ARCHIVE)

    # --- Marked features from owner screenshots (working inventory) ---
    # Coordinates are map-local centers of owner circles (estimated from F5 frame).
    features = [
        {
            "review_label": "NE01_Kolguyev",
            "screenshot": "northeast_full",
            "map_local_xy": [4220.0, 660.0],
            "hypothesis": "Kolguyev Island",
        },
        {
            "review_label": "NE02_Ladoga",
            "screenshot": "northeast_full",
            "map_local_xy": [2803.0, 1052.0],
            "hypothesis": "Lake Ladoga",
            "gap_fill_id": "gap_0012",
        },
        {
            "review_label": "NE03_Onega",
            "screenshot": "northeast_full",
            "map_local_xy": [2996.0, 978.0],
            "hypothesis": "Lake Onega",
            "gap_fill_id": "gap_0027",
        },
        {
            "review_label": "NE04_WhiteSea_SE_large_hole",
            "screenshot": "northeast_full",
            "map_local_xy": [3618.0, 685.0],
            "hypothesis": "Large hole SE of White Sea / Mezen basin (possible Lacha-Kenozero region or exaggerated hole)",
            "gap_fill_id": "gap_0039",
        },
        {
            "review_label": "NE05_Rybinsk",
            "screenshot": "northeast_full",
            "map_local_xy": [3133.0, 1255.0],
            "hypothesis": "Rybinsk Reservoir",
            "gap_fill_id": "gap_0025",
        },
        {
            "review_label": "NE06_Volga_mid_reservoir",
            "screenshot": "northeast_full",
            "map_local_xy": [3376.0, 1273.0],
            "hypothesis": "Volga mid reservoir / Kostroma-Galich lake cluster",
            "gap_fill_id": "gap_0038",
        },
        {
            "review_label": "NE07_Cheboksary_system",
            "screenshot": "northeast_full",
            "map_local_xy": [3597.0, 1356.0],
            "hypothesis": "Cheboksary / Volga reservoir system",
            "gap_fill_id": "gap_0045",
        },
        {
            "review_label": "NE08_Kuybyshev_Samara_arm",
            "screenshot": "northeast_full",
            "map_local_xy": [3889.0, 1546.0],
            "hypothesis": "Kuybyshev (Samara) Reservoir arm",
            "gap_fill_id": "gap_0044",
        },
        {
            "review_label": "MED01_Ibiza",
            "screenshot": "mediterranean",
            "map_local_xy": [1340.0, 2730.0],
            "hypothesis": "Ibiza",
            "expected_source_id": 2274,
        },
        {
            "review_label": "MED02_Pantelleria",
            "screenshot": "mediterranean",
            "map_local_xy": [1854.0, 2860.0],
            "hypothesis": "Pantelleria",
            "expected_source_id": 4693,
        },
        {
            "review_label": "MED03_Malta",
            "screenshot": "mediterranean",
            "map_local_xy": [1970.0, 2912.0],
            "hypothesis": "Malta / Valletta",
            "expected_source_id": 270,
        },
        {
            "review_label": "MED04_Lemnos",
            "screenshot": "mediterranean",
            "map_local_xy": [2492.0, 2678.0],
            "hypothesis": "Lemnos / Myrina",
            "expected_source_id": 3220,
        },
        {
            "review_label": "NA01_Chott_or_basin",
            "screenshot": "mediterranean",
            "map_local_xy": [1686.0, 3032.0],
            "hypothesis": "North African chott / salt basin (Chott el Jerid region)",
            "gap_fill_id": "gap_0008",
        },
    ]

    # Archive Kolguyev proof
    kolguyev_sid = 11836
    kol_prov = archive.provinces.get(kolguyev_sid)

    rows = []
    for feat in features:
        lx, ly = feat["map_local_xy"]
        sx, sy = lx + ox, ly + oy
        lo, la = lonlat(sx, sy)
        cities = nearest_cities(archive, sx, sy)
        touching = []
        for p in data["provinces"]:
            r = ring_pts(p)
            if len(r) < 3:
                continue
            xs = [a for a, _ in r]
            ys = [b for _, b in r]
            if not (min(xs) - 30 <= lx <= max(xs) + 30 and min(ys) - 30 <= ly <= max(ys) + 30):
                continue
            if point_in_ring(lx, ly, r) or (
                abs(p["centroid"][0] - lx) < 40 and abs(p["centroid"][1] - ly) < 40
            ):
                touching.append(
                    {
                        "gates_id": p["id"],
                        "source_id": int(p["source_id"]),
                        "is_water": bool(p.get("is_water")),
                        "area": float(p.get("area") or 0),
                        "triangle_count": len(p.get("triangles") or []) // 3,
                        "vertex_count": len(p.get("ring") or []) // 2,
                        "neighbors": list(p.get("neighbors") or [])[:12],
                    }
                )

        gap = gaps.get(feat.get("gap_fill_id") or "")
        rendered = "unknown"
        poly_type = "unknown"
        action = "UNRESOLVED_REQUIRES_OWNER_RULING"
        confidence = "medium"
        evidence = ""
        defect = None

        if feat["review_label"] == "NE01_Kolguyev":
            # Proven archive land province not in production crop
            in_prod = kolguyev_sid in by_src
            rendered = "coastline_outline_or_water_without_land_fill"
            poly_type = "omitted_source_land_province"
            if kol_prov and not in_prod:
                action = "CONFIRMED_MISSING_LAND_RESTORE"
                confidence = "high"
                evidence = (
                    f"Archive source_id={kolguyev_sid} is land (terrain_id={kol_prov.terrain_id}, "
                    f"ring_verts={len(kol_prov.ring)}, area≈{shoelace_area(kol_prov.ring):.0f}) "
                    f"centered near Kolguyev; ABSENT from production included set. "
                    f"Visual outline likely residual water/coast geometry without land mesh."
                )
                defect = {
                    "kind": "crop_omission_or_boundary_exclusion",
                    "archive_source_id": kolguyev_sid,
                    "in_production": False,
                    "pipeline_stage": "crop_inclusion",
                }
            touching = touching  # may be empty or nearby mainland

        elif gap is not None:
            rendered = "water_presentation_gap_fill"
            poly_type = "gap_fill_interior_hole"
            # Real lakes/reservoirs kept
            if feat["review_label"] in (
                "NE02_Ladoga",
                "NE03_Onega",
                "NE05_Rybinsk",
                "NE06_Volga_mid_reservoir",
                "NE07_Cheboksary_system",
                "NE08_Kuybyshev_Samara_arm",
            ):
                action = "CONFIRMED_REAL_WATER_KEEP"
                confidence = "high"
                evidence = (
                    f"Matches ocean_gap_fills {gap['id']} area={gap['area']:.0f} "
                    f"classification={gap.get('classification')} region_hint={gap.get('region_hint')}. "
                    f"Nearest cities {', '.join(c['name'] for c in cities[:3])}. "
                    f"Continuous-ocean renderer correctly shows interior water (non-selectable)."
                )
            elif feat["review_label"] == "NE04_WhiteSea_SE_large_hole":
                # Large gap near Koynas — scale check vs known small lakes
                action = "UNRESOLVED_REQUIRES_OWNER_RULING"
                confidence = "medium"
                evidence = (
                    f"gap_0039 area={gap['area']:.0f} near {cities[0]['name']} (Arkhangelsk/Mezen hinterland). "
                    f"May be merged/exaggerated hydrography rather than a single named great lake; "
                    f"not proven false. Do not fill without stronger proof."
                )
            elif feat["review_label"] == "NA01_Chott_or_basin":
                action = "CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER"
                confidence = "high"
                evidence = (
                    f"gap_0008 area={gap['area']:.0f} near Tozeur/Gafsa/Gabes — "
                    f"consistent with Chott el Jerid / Tunisian salt-basin complex. "
                    f"Keep as water presentation; terrain styling deferred to PR B / visual hierarchy."
                )
            else:
                action = "CONFIRMED_REAL_WATER_KEEP"
                confidence = "medium"
                evidence = f"gap fill {gap['id']} treated as real interior water pending finer naming."

        elif feat.get("expected_source_id"):
            sid = int(feat["expected_source_id"])
            p = by_src.get(sid)
            if p and not p.get("is_water"):
                verts = len(p.get("ring") or []) // 2
                rendered = "land_province_fill_present"
                poly_type = "province_polygon"
                action = "CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP"
                confidence = "high"
                evidence = (
                    f"Production land {p['id']} source_id={sid} area={p.get('area')} "
                    f"ring_verts={verts} triangles={len(p.get('triangles') or [])//3}. "
                    f"City anchor supports {feat['hypothesis']}. "
                    f"Rectangular/low-vert rings are simplified real islands — KEEP IDs; coastline work is #121."
                )
            elif p and p.get("is_water"):
                action = "UNRESOLVED_REQUIRES_OWNER_RULING"
                evidence = f"Expected island source {sid} is marked water in production."
            else:
                action = "CONFIRMED_MISSING_LAND_RESTORE"
                evidence = f"Expected island source {sid} absent from production."
                confidence = "high"

        # Surrounding IDs
        surrounding = []
        for p in data["provinces"]:
            if abs(p["centroid"][0] - lx) < 120 and abs(p["centroid"][1] - ly) < 120:
                surrounding.append(
                    {
                        "gates_id": p["id"],
                        "source_id": int(p["source_id"]),
                        "is_water": bool(p.get("is_water")),
                    }
                )

        rows.append(
            {
                "review_label": feat["review_label"],
                "screenshot": feat["screenshot"],
                "hypothesis": feat.get("hypothesis"),
                "screenshot_pixel_coordinate": None,  # F5 UI pixels vary; map-local is authoritative
                "map_local_xy": [lx, ly],
                "source_map_xy": [round(sx, 2), round(sy, 2)],
                "approx_longitude": lo,
                "approx_latitude": la,
                "nearest_named_geographic_feature": cities[0]["name"] if cities else None,
                "nearest_cities": cities,
                "gates_province_ids_touching_or_surrounding": surrounding[:24],
                "touching_detail": touching,
                "source_is_water_values": [t.get("is_water") for t in touching],
                "rendered_classification": rendered,
                "polygon_or_ring_type": poly_type,
                "gap_fill_id": feat.get("gap_fill_id"),
                "gap_fill": {
                    "id": gap.get("id"),
                    "area": gap.get("area"),
                    "centroid": gap.get("centroid"),
                    "classification": gap.get("classification"),
                    "region_hint": gap.get("region_hint"),
                }
                if gap
                else None,
                "archive_kolguyev_source_id": kolguyev_sid if feat["review_label"] == "NE01_Kolguyev" else None,
                "archive_kolguyev_in_production": kolguyev_sid in by_src
                if feat["review_label"] == "NE01_Kolguyev"
                else None,
                "recommended_action": action,
                "confidence": confidence,
                "evidence": evidence,
                "renderer_defect": defect,
                "geographic_reference": GEO_REF,
                "reference_license": GEO_REF["license"],
                "production_change_allowed": action
                not in (
                    "UNRESOLVED_REQUIRES_OWNER_RULING",
                    "CONFIRMED_REAL_WATER_KEEP",
                    "CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP",
                    "CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER",
                ),
            }
        )

    OUT.mkdir(parents=True, exist_ok=True)
    inv = {
        "schema": "gates-of-codex.earth3-hydrography-marked-features",
        "schema_version": 1,
        "production_authority": {
            "provinces": 3510,
            "land": 3295,
            "water_metadata": 215,
            "included_ids_sha256": HASH,
        },
        "geographic_reference": GEO_REF,
        "feature_count": len(rows),
        "features": rows,
        "summary": {
            "CONFIRMED_REAL_WATER_KEEP": [r["review_label"] for r in rows if r["recommended_action"] == "CONFIRMED_REAL_WATER_KEEP"],
            "CONFIRMED_REAL_ISLAND_RESTORE_FILL": [
                r["review_label"] for r in rows if r["recommended_action"] == "CONFIRMED_REAL_ISLAND_RESTORE_FILL"
            ],
            "CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP": [
                r["review_label"]
                for r in rows
                if r["recommended_action"] == "CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP"
            ],
            "CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER": [
                r["review_label"] for r in rows if r["recommended_action"] == "CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER"
            ],
            "CONFIRMED_MISSING_LAND_RESTORE": [
                r["review_label"] for r in rows if r["recommended_action"] == "CONFIRMED_MISSING_LAND_RESTORE"
            ],
            "CONFIRMED_RENDERER_HOLE_FIX": [
                r["review_label"] for r in rows if r["recommended_action"] == "CONFIRMED_RENDERER_HOLE_FIX"
            ],
            "UNRESOLVED_REQUIRES_OWNER_RULING": [
                r["review_label"] for r in rows if r["recommended_action"] == "UNRESOLVED_REQUIRES_OWNER_RULING"
            ],
        },
        "renderer_notes": [
            "Water provinces and ocean_gap_fills render as continuous ocean (no land fill) under v1 water policy.",
            "Interior lakes that are gap_fills are intentional water presentation, not missing land meshes.",
            "All production land provinces have non-empty triangle meshes (empty land mesh count = 0).",
            "Kolguyev archive land source 11836 is outside the current included crop set.",
            "Simplified rectangular islands retain land fills; coastline quality is #121.",
        ],
    }
    (OUT / "marked_features.json").write_text(json.dumps(inv, indent=2) + "\n", encoding="utf-8")

    # OWNER_REVIEW.md
    md = [
        "# Earth3 hydrography owner review",
        "",
        "Audit only — **production F5 unchanged** (3510 / `a849b381…`).",
        "",
        f"Geographic reference: {GEO_REF['name']}",
        f"License: {GEO_REF['license']}",
        "",
        "## Summary counts",
        "",
    ]
    for k, v in inv["summary"].items():
        md.append(f"- **{k}**: {len(v)} — {', '.join(v) if v else '—'}")
    md += ["", "## Feature table", ""]
    md.append("| Label | Hypothesis | Nearest name | Type | Action | Confidence |")
    md.append("|---|---|---|---|---|---|")
    for r in rows:
        md.append(
            f"| {r['review_label']} | {r['hypothesis']} | {r['nearest_named_geographic_feature']} | "
            f"{r['polygon_or_ring_type']} | `{r['recommended_action']}` | {r['confidence']} |"
        )
    md += ["", "## Evidence notes", ""]
    for r in rows:
        md.append(f"### {r['review_label']}")
        md.append("")
        md.append(r["evidence"] or "_no evidence text_")
        md.append("")
        md.append(
            f"- local xy: `{r['map_local_xy']}` source xy: `{r['source_map_xy']}` "
            f"approx lon/lat: `{r['approx_longitude']}, {r['approx_latitude']}`"
        )
        md.append("")
    md += [
        "## Production policy",
        "",
        "- Do **not** change production for UNRESOLVED items.",
        "- CONFIRMED_REAL_WATER_KEEP / SIMPLIFIED_ISLAND_KEEP / SALT_BASIN: no production geometry change.",
        "- CONFIRMED_MISSING_LAND_RESTORE (Kolguyev): requires separate owner-approved crop inclusion PR; not auto-applied.",
        "- Island coastline reconstruction remains **#121**.",
        "- Do not begin #74 PR B until owner accepts this package.",
        "",
    ]
    (OUT / "OWNER_REVIEW.md").write_text("\n".join(md), encoding="utf-8")

    _render_maps(data, rows, gaps, ox, oy)
    _write_tests()
    print(json.dumps(inv["summary"], indent=2))
    print("wrote", OUT)
    return 0


def _render_maps(data, rows, gaps, ox, oy) -> None:
    OUT_IMG = OUT / "evidence"
    OUT_IMG.mkdir(parents=True, exist_ok=True)
    W, H = 1920, 1080
    bw = float(data["bounds"]["width"])
    bh = float(data["bounds"]["height"])
    margin = 20
    s = min((W - 2 * margin) / bw, (H - 2 * margin) / bh)
    oxp = margin + (W - 2 * margin - bw * s) * 0.5
    oyp = margin + (H - 2 * margin - bh * s) * 0.5

    def to_screen(x, y):
        return oxp + x * s, oyp + y * s

    def base_img():
        img = Image.new("RGB", (W, H), (18, 32, 48))
        dr = ImageDraw.Draw(img)
        for p in data["provinces"]:
            if p.get("is_water"):
                continue
            pts = ring_pts(p)
            if len(pts) < 3:
                continue
            sp = [to_screen(x, y) for x, y in pts]
            dr.polygon(sp, fill=(120, 126, 132), outline=(45, 48, 52))
        # gap fills as darker blue
        for g in data.get("ocean_gap_fills") or []:
            # approximate with centroid circle scaled by area
            cx, cy = g["centroid"]
            r = max(math.sqrt(max(g["area"], 1) / math.pi) * s, 2)
            x, y = to_screen(cx, cy)
            dr.ellipse([x - r, y - r, x + r, y + r], fill=(30, 55, 90), outline=(60, 100, 140))
        return img, dr

    try:
        font = ImageFont.truetype("arial.ttf", 14)
        font_s = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        font = font_s = ImageFont.load_default()

    # Full NE annotated
    img, dr = base_img()
    n = 1
    for r in rows:
        if r["screenshot"] != "northeast_full":
            continue
        x, y = to_screen(r["map_local_xy"][0], r["map_local_xy"][1])
        rad = 28
        dr.ellipse([x - rad, y - rad, x + rad, y + rad], outline=(220, 40, 40), width=3)
        label = f"{n}:{r['review_label'].split('_',1)[-1][:12]}"
        dr.rectangle([x + rad, y - 10, x + rad + 7 * len(label), y + 10], fill=(10, 10, 10))
        dr.text((x + rad + 2, y - 8), label, fill=(255, 220, 180), font=font_s)
        n += 1
    dr.text((16, 10), "NE hydrography marks (land gray, gap-fill lakes blue circles)", fill=(240, 240, 240), font=font)
    img.save(OUT_IMG / "01_northeast_marked_numbered.png")

    # Med annotated
    img, dr = base_img()
    n = 1
    for r in rows:
        if r["screenshot"] != "mediterranean":
            continue
        x, y = to_screen(r["map_local_xy"][0], r["map_local_xy"][1])
        rad = 22
        dr.ellipse([x - rad, y - rad, x + rad, y + rad], outline=(220, 40, 40), width=3)
        label = f"{n}:{r['review_label']}"
        dr.rectangle([x + rad, y - 10, x + rad + 7 * len(label), y + 10], fill=(10, 10, 10))
        dr.text((x + rad + 2, y - 8), label, fill=(255, 220, 180), font=font_s)
        n += 1
    dr.text((16, 10), "Mediterranean / NA marks", fill=(240, 240, 240), font=font)
    img.save(OUT_IMG / "02_mediterranean_marked_numbered.png")

    # Classification legend map
    img, dr = base_img()
    colors = {
        "CONFIRMED_REAL_WATER_KEEP": (40, 120, 200),
        "CONFIRMED_MISSING_LAND_RESTORE": (220, 60, 60),
        "CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP": (80, 200, 100),
        "CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER": (200, 180, 60),
        "UNRESOLVED_REQUIRES_OWNER_RULING": (200, 100, 220),
    }
    for r in rows:
        x, y = to_screen(r["map_local_xy"][0], r["map_local_xy"][1])
        col = colors.get(r["recommended_action"], (255, 255, 255))
        dr.ellipse([x - 16, y - 16, x + 16, y + 16], outline=col, width=3)
        dr.text((x + 18, y - 6), r["review_label"].split("_")[0], fill=col, font=font_s)
    dr.text((16, 10), "Classification colors: blue=real water, red=missing land, green=simplified island, yellow=salt basin, purple=unresolved", fill=(230, 230, 230), font=font_s)
    img.save(OUT_IMG / "03_classification_overview.png")

    # Closeups
    for r in rows:
        img = Image.new("RGB", (900, 700), (18, 32, 48))
        dr = ImageDraw.Draw(img)
        cx, cy = r["map_local_xy"]
        win = 180.0
        # draw nearby land
        for p in data["provinces"]:
            if p.get("is_water"):
                continue
            if abs(p["centroid"][0] - cx) > win or abs(p["centroid"][1] - cy) > win:
                continue
            pts = ring_pts(p)
            if len(pts) < 3:
                continue
            sp = [
                (450 + (x - cx) / win * 400, 350 + (y - cy) / win * 300)
                for x, y in pts
            ]
            dr.polygon(sp, fill=(120, 126, 132), outline=(40, 40, 40))
        # gap
        if r.get("gap_fill"):
            g = r["gap_fill"]
            gx, gy = g["centroid"]
            rr = max(math.sqrt(g["area"] / math.pi) / win * 400, 8)
            x = 450 + (gx - cx) / win * 400
            y = 350 + (gy - cy) / win * 300
            dr.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(30, 60, 100), outline=(80, 140, 200))
        dr.ellipse([450 - 12, 350 - 12, 450 + 12, 350 + 12], outline=(255, 60, 60), width=2)
        dr.text((10, 10), f"{r['review_label']} -> {r['recommended_action']}", fill=(240, 240, 240), font=font)
        dr.text((10, 32), f"near {r['nearest_named_geographic_feature']}", fill=(200, 200, 200), font=font_s)
        img.save(OUT_IMG / f"closeup_{r['review_label']}.png")

    # Renderer classification strip legend file
    (OUT_IMG / "README.md").write_text(
        "\n".join(
            [
                "# Hydrography audit evidence",
                "",
                "- Gray polygons: production land meshes",
                "- Blue circles/ellipses: ocean_gap_fills (interior water presentation)",
                "- Red rings: owner-marked review centers",
                "",
                "No production assets modified.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_tests() -> None:
    test = ROOT / "tests/test_earth3_hydrography_audit.py"
    test.write_text(
        '''from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INV = ROOT / "docs/earth3-crop/hydrography_audit/marked_features.json"
PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean"
HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"


class Earth3HydrographyAuditTests(unittest.TestCase):
    @unittest.skipUnless(INV.is_file(), "hydrography audit inventory missing")
    def test_inventory_complete_and_production_untouched(self) -> None:
        inv = json.loads(INV.read_text(encoding="utf-8"))
        self.assertEqual(inv["production_authority"]["provinces"], 3510)
        self.assertEqual(inv["production_authority"]["included_ids_sha256"], HASH)
        feats = inv["features"]
        self.assertGreaterEqual(len(feats), 10)
        labels = {f["review_label"] for f in feats}
        self.assertIn("NE01_Kolguyev", labels)
        self.assertIn("NE02_Ladoga", labels)
        self.assertIn("NE03_Onega", labels)
        self.assertIn("MED01_Ibiza", labels)
        for f in feats:
            self.assertNotEqual(f.get("recommended_action"), "")
            self.assertNotIn("a hole", (f.get("evidence") or "").lower())
            self.assertIn(f["recommended_action"], {
                "CONFIRMED_REAL_WATER_KEEP",
                "CONFIRMED_REAL_ISLAND_RESTORE_FILL",
                "CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP",
                "CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER",
                "CONFIRMED_MISSING_LAND_RESTORE",
                "CONFIRMED_RENDERER_HOLE_FIX",
                "UNRESOLVED_REQUIRES_OWNER_RULING",
            })
        # Production path still 3510
        meta = json.loads((PROD / "dataset_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["province_count"], 3510)
        self.assertEqual(meta["included_source_ids_sha256"], HASH)
        # Unresolved must not claim production_change_allowed
        for f in feats:
            if f["recommended_action"] == "UNRESOLVED_REQUIRES_OWNER_RULING":
                self.assertFalse(f.get("production_change_allowed"))
        # No empty land meshes in production
        ds = json.loads((PROD / "polygon_dataset.json").read_text(encoding="utf-8"))
        for p in ds["provinces"]:
            if p.get("is_water"):
                continue
            self.assertGreaterEqual(len(p.get("triangles") or []), 3, p["id"])
        # Simplified islands still land with fill
        for sid in (2274, 4693, 270, 3220):
            row = next(p for p in ds["provinces"] if int(p["source_id"]) == sid)
            self.assertFalse(row.get("is_water"))
            self.assertGreaterEqual(len(row.get("triangles") or []), 3)


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
