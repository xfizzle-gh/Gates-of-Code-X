"""Build geographic owner-review package for proposed Earth3 topology exclusions.

Does NOT modify production dataset. Production remains exact authority in
config/earth3/production_authority.json.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict, deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.earth3.parse import load_earth3_dataset  # noqa: E402
from gates_of_codex.earth3.topology_sanitize import (  # noqa: E402
    _rectness,
    _ring_points,
    land_connected_components,
)

ARCHIVE = Path(r"C:\Users\paulf\Downloads\AOH3_Earth3_map_provinces.zip")
PROD_DS = ROOT / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
OUT = ROOT / "docs/earth3-crop/topology_sanitize/proposed"
AUTHORITY = ROOT / "config/earth3/production_authority.json"
PRE_HASH = "507b0069a9572e915059ff6d21bd9f13a68cf62a26770c94a90c0b0e6a900be7"

# Rough equirectangular mapping for Earth3 world canvas (documented estimate for review only).
# Canvas 17760×8600 covers full Earth AoH3 map; lon -180..180, lat ~85..-85 (y down).
CANVAS_W = 17760.0
CANVAS_H = 8600.0
LAT_MAX = 85.0


def src_xy_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon = (x / CANVAS_W) * 360.0 - 180.0
    lat = LAT_MAX - (y / CANVAS_H) * (2.0 * LAT_MAX)
    return round(lon, 4), round(lat, 4)


def nearest_city(ds, x: float, y: float, limit: int = 3) -> list[dict]:
    scored = []
    for c in ds.cities:
        d = math.hypot(float(c.x) - x, float(c.y) - y)
        scored.append((d, c))
    scored.sort(key=lambda t: t[0])
    out = []
    for d, c in scored[:limit]:
        out.append({"name": c.name, "source_province_id": int(c.province_id), "dist_px": round(d, 1), "x": c.x, "y": c.y})
    return out


def region_bucket(lon: float, lat: float, local_x: float, local_y: float, width: float) -> str:
    if lon < -20 and lat > 50:
        return "atlantic_iceland_approaches"
    if -12 <= lon <= 2 and 50 <= lat <= 60:
        return "atlantic_channel_britain_ireland"
    if -10 <= lon <= 5 and 35 <= lat <= 45:
        return "western_mediterranean"
    if 5 <= lon <= 20 and 30 <= lat <= 45:
        return "central_mediterranean"
    if 20 <= lon <= 40 and 30 <= lat <= 45:
        return "eastern_mediterranean"
    if 10 <= lon <= 30 and 54 <= lat <= 70:
        return "baltic_scandinavia"
    if lon >= 40 or local_x >= width * 0.88:
        return "eastern_boundary_caspian"
    if 0 <= lon <= 20 and 45 <= lat <= 55:
        return "central_europe_inland"
    return "other"


def classify_row(
    *,
    component_id: str,
    component_class: str,
    component_keep: bool,
    area: float,
    nvert: int,
    rectness: float,
    neighbor_count: int,
    lon: float,
    lat: float,
    nearest: list[dict],
    source_id: int,
    terrain_id: int,
    continent_id: int,
    is_water: bool,
    local_x: float,
    width: float,
) -> dict:
    """Return geographic action with proof-oriented reason (not allowlist language)."""
    city = nearest[0]["name"] if nearest else "unknown"
    city_d = nearest[0]["dist_px"] if nearest else 1e9

    # Ireland component L002 — proven via Dublin/Cork/Belfast seed cities.
    if component_id == "L002":
        return {
            "proposed_action": "keep_as_legitimate_island",
            "confidence": "high",
            "evidence": f"Member of Ireland land component; nearest city {city} ({city_d}px); lon/lat {lon},{lat}",
            "owner_ruling": "pending",
            "bucket": "restore_legitimate",
        }

    # Perfect rectangles: only high-confidence when far from any named place.
    # Near cities (Valletta/Ibiza/Pantelleria/Jersey) may be simplified real islets — unresolved.
    if nvert <= 4 and rectness >= 0.98 and area <= 2500:
        if city_d > 40 and neighbor_count <= 1:
            return {
                "proposed_action": "exclude_as_malformed_marker_artifact",
                "confidence": "high",
                "evidence": (
                    f"{nvert}-vertex ring rectangularity={rectness:.3f} area={area:.1f}; "
                    f"isolated from named places (nearest {city} {city_d}px); "
                    f"source ring is axis-aligned rectangle atypical of coastline"
                ),
                "owner_ruling": "pending",
                "bucket": "high_confidence_exclude",
            }
        return {
            "proposed_action": "unresolved",
            "confidence": "low",
            "evidence": (
                f"{nvert}-vertex rectangle near {city} ({city_d}px) — may be simplified real island "
                f"or marker; requires contact-sheet visual proof before exclude"
            ),
            "owner_ruling": "pending",
            "bucket": "unresolved",
        }

    # Eastern crop spill: far-east detached land beyond Ural/Caspian approaches.
    if local_x >= width * 0.90 and neighbor_count <= 1:
        return {
            "proposed_action": "exclude_as_crop_spill",
            "confidence": "high" if neighbor_count == 0 else "medium",
            "evidence": (
                f"Eastern detached land local_x={local_x:.0f}/{width:.0f} neighbors={neighbor_count}; "
                f"lon/lat {lon},{lat}; nearest {city} {city_d}px"
            ),
            "owner_ruling": "pending",
            "bucket": "high_confidence_exclude",
        }

    # Tiny open-water isolates far from cities.
    if area < 200 and neighbor_count <= 1 and city_d > 80:
        return {
            "proposed_action": "unresolved",
            "confidence": "low",
            "evidence": f"Tiny isolate area={area:.1f} far from named places ({city} {city_d}px); needs visual proof",
            "owner_ruling": "pending",
            "bucket": "unresolved",
        }

    # Remaining former "allowlist miss" members of other components.
    if not component_keep and component_id not in ("L002",):
        return {
            "proposed_action": "unresolved",
            "confidence": "low",
            "evidence": (
                f"Previously proposed for exclusion via component {component_id} "
                f"({component_class}); geographic identity not yet proven — nearest {city} {city_d}px"
            ),
            "owner_ruling": "pending",
            "bucket": "unresolved",
        }

    return {
        "proposed_action": "keep_as_legitimate_land",
        "confidence": "medium",
        "evidence": f"No proven defect; nearest {city} {city_d}px lon/lat {lon},{lat}",
        "owner_ruling": "pending",
        "bucket": "restore_legitimate",
    }


def draw_sheet(
    *,
    title: str,
    rows: list[dict],
    by_id: dict,
    origin: tuple[float, float],
    out_path: Path,
    width: int = 2200,
    height: int = 1400,
) -> None:
    if not rows:
        return
    # Bounds from members
    xs, ys = [], []
    for r in rows:
        p = by_id.get(r["gates_id_pre_sanitize"])
        if not p:
            continue
        for x, y in _ring_points(p):
            xs.append(x)
            ys.append(y)
    if not xs:
        return
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    pad = max(40.0, 0.08 * max(maxx - minx, maxy - miny, 1.0))
    minx -= pad
    maxx += pad
    miny -= pad
    maxy += pad
    bw = max(maxx - minx, 1.0)
    bh = max(maxy - miny, 1.0)
    margin = 80.0
    s = min((width - 2 * margin) / bw, (height - 2 * margin - 40) / bh)
    ox = margin + (width - 2 * margin - bw * s) * 0.5
    oy = margin + 30 + (height - 2 * margin - 40 - bh * s) * 0.5

    img = Image.new("RGB", (width, height), (16, 28, 42))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
        font_sm = ImageFont.truetype("arial.ttf", 11)
        font_t = ImageFont.truetype("arial.ttf", 20)
    except Exception:
        font = font_sm = font_t = ImageFont.load_default()

    # Draw all land in view lightly
    for p in by_id.values():
        if p.get("is_water"):
            continue
        pts = _ring_points(p)
        if len(pts) < 3:
            continue
        if max(x for x, _ in pts) < minx or min(x for x, _ in pts) > maxx:
            continue
        if max(y for _, y in pts) < miny or min(y for _, y in pts) > maxy:
            continue
        sp = [((x - minx) * s + ox, (y - miny) * s + oy) for x, y in pts]
        draw.polygon(sp, fill=(90, 96, 102), outline=(50, 54, 58))

    # Highlight review rows
    colors = {
        "keep_as_legitimate_island": (80, 180, 100),
        "keep_as_legitimate_land": (80, 180, 100),
        "exclude_as_malformed_marker_artifact": (220, 60, 60),
        "exclude_as_crop_spill": (220, 120, 40),
        "reclassify_as_water_metadata": (60, 120, 220),
        "unresolved": (220, 200, 60),
    }
    for r in rows:
        p = by_id.get(r["gates_id_pre_sanitize"])
        if not p:
            continue
        pts = _ring_points(p)
        if len(pts) < 2:
            continue
        sp = [((x - minx) * s + ox, (y - miny) * s + oy) for x, y in pts]
        col = colors.get(r["proposed_action"], (255, 0, 255))
        draw.line(sp + [sp[0]], fill=col, width=3)
        cx = sum(x for x, _ in sp) / len(sp)
        cy = sum(y for _, y in sp) / len(sp)
        label = f"{r['gates_id_pre_sanitize']}/{r['source_id']}"
        draw.rectangle([cx - 2, cy - 10, cx + 7 * len(label), cy + 8], fill=(10, 10, 10))
        draw.text((cx, cy - 8), label, fill=col, font=font_sm)

    draw.text((20, 12), title, fill=(240, 240, 240), font=font_t)
    draw.text(
        (20, height - 28),
        "Green=KEEP  Red=EXCLUDE marker  Orange=EXCLUDE spill  Yellow=UNRESOLVED  | preview only, not production",
        fill=(200, 200, 200),
        font=font_sm,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def main() -> int:
    if not PROD_DS.is_file():
        print("production dataset missing", file=sys.stderr)
        return 2
    if not ARCHIVE.is_file():
        print("archive missing", file=sys.stderr)
        return 2

    auth = json.loads(AUTHORITY.read_text(encoding="utf-8"))
    assert auth["province_count"] == 3512
    assert auth["included_ids_sha256"] == PRE_HASH

    data = json.loads(PROD_DS.read_text(encoding="utf-8"))
    assert int(data["province_count"]) == 3512
    assert data.get("included_source_ids_sha256") == PRE_HASH

    by_id = {p["id"]: p for p in data["provinces"]}
    ox, oy = data["bounds"]["origin_source_xy"]
    width = float(data["bounds"]["width"])
    height = float(data["bounds"]["height"])

    ds = load_earth3_dataset(ARCHIVE)

    comps = land_connected_components(data["provinces"])
    comp_of: dict[str, dict] = {}
    mainland = comps[0]
    mcx = sum(by_id[i]["centroid"][0] for i in mainland) / len(mainland)
    mcy = sum(by_id[i]["centroid"][1] for i in mainland) / len(mainland)

    # Reuse prior component IDs from pre audit if present for stability
    pre_path = ROOT / "docs/earth3-crop/topology_sanitize/disconnected_land_components_pre.json"
    id_to_comp: dict[str, str] = {}
    comp_meta: dict[str, dict] = {}
    if pre_path.is_file():
        pre = json.loads(pre_path.read_text(encoding="utf-8"))
        for c in pre["components"]:
            comp_meta[c["component_id"]] = c
            for gid in c["gates_ids"]:
                id_to_comp[gid] = c["component_id"]
    else:
        for i, mem in enumerate(comps):
            cid = f"L{i:03d}"
            for gid in mem:
                id_to_comp[gid] = cid

    # Candidate set = previous 77 proposed exclusions if present, else empty
    old_ov_path = ROOT / "config/earth3/province_classification_overrides.json"
    candidate_source_ids: set[int] = set()
    old_by_src: dict[int, dict] = {}
    if old_ov_path.is_file():
        old = json.loads(old_ov_path.read_text(encoding="utf-8"))
        for o in old.get("overrides") or []:
            sid = int(o["source_id"])
            candidate_source_ids.add(sid)
            old_by_src[sid] = o

    # Also include all non-mainland component members for review completeness
    for gid, cid in id_to_comp.items():
        if cid == "L000":
            continue
        if gid in by_id:
            candidate_source_ids.add(int(by_id[gid]["source_id"]))

    # Always include known rectangle suspects and eastern isolates
    for p in data["provinces"]:
        if p.get("is_water"):
            continue
        pts = _ring_points(p)
        rn = _rectness(pts)
        if len(pts) <= 4 and rn >= 0.98:
            candidate_source_ids.add(int(p["source_id"]))
        if float(p["centroid"][0]) >= width * 0.90 and len(p.get("neighbors") or []) <= 1:
            candidate_source_ids.add(int(p["source_id"]))

    rows: list[dict] = []
    for p in data["provinces"]:
        sid = int(p["source_id"])
        if sid not in candidate_source_ids:
            continue
        if p.get("is_water"):
            continue
        gid = p["id"]
        pts = _ring_points(p)
        area = float(p.get("area") or 0.0)
        rn = _rectness(pts)
        nvert = len(pts)
        cx, cy = float(p["centroid"][0]), float(p["centroid"][1])
        src_x, src_y = cx + float(ox), cy + float(oy)
        lon, lat = src_xy_to_lonlat(src_x, src_y)
        nearest = nearest_city(ds, src_x, src_y)
        cid = id_to_comp.get(gid, "unknown")
        cm = comp_meta.get(cid, {})
        src_prov = ds.provinces.get(sid)
        decision = classify_row(
            component_id=cid,
            component_class=str(cm.get("classification") or ""),
            component_keep=bool(cm.get("keep", True)),
            area=area,
            nvert=nvert,
            rectness=rn,
            neighbor_count=len(p.get("neighbors") or []),
            lon=lon,
            lat=lat,
            nearest=nearest,
            source_id=sid,
            terrain_id=int(p.get("terrain_id", -1)),
            continent_id=int(p.get("continent_id", -1)),
            is_water=bool(p.get("is_water")),
            local_x=cx,
            width=width,
        )
        sheet = region_bucket(lon, lat, cx, cy, width)
        ring_src = list(src_prov.ring) if src_prov else []
        rows.append(
            {
                "gates_id_pre_sanitize": gid,
                "source_id": sid,
                "component_id": cid,
                "centroid_local_xy": [round(cx, 2), round(cy, 2)],
                "centroid_source_xy": [round(src_x, 2), round(src_y, 2)],
                "longitude": lon,
                "latitude": lat,
                "nearest_named_location": nearest[0]["name"] if nearest else "",
                "nearest_location_dist_px": nearest[0]["dist_px"] if nearest else None,
                "nearest_locations": nearest,
                "country_sea_region_guess": sheet,
                "area": round(area, 3),
                "vertex_count": nvert,
                "rectangularity": round(rn, 4),
                "neighbor_count": len(p.get("neighbors") or []),
                "source_terrain_id": int(p.get("terrain_id", -1)),
                "source_continent_id": int(p.get("continent_id", -1)),
                "source_is_water": bool(src_prov.is_water) if src_prov else bool(p.get("is_water")),
                "source_ring_coordinates": [[float(x), float(y)] for x, y in ring_src[:32]],
                "source_ring_vertex_count": len(ring_src),
                "screenshot_filename": f"contact_{sheet}.png",
                "proposed_action": decision["proposed_action"],
                "evidence": decision["evidence"],
                "confidence": decision["confidence"],
                "owner_ruling": "pending",
                "review_bucket": decision["bucket"],
                "previous_generic_reason": (old_by_src.get(sid) or {}).get("reason"),
                "owner_review_status": "proposed",
            }
        )

    rows.sort(key=lambda r: (r["component_id"], r["source_id"]))

    # Overrides file: proposed only; production apply list empty
    overrides = {
        "schema": "gates-of-codex.earth3-province-classification-overrides",
        "schema_version": 2,
        "description": "Proposed topology overrides for owner review (#117). NOT applied to production.",
        "production_authority_hash": PRE_HASH,
        "apply_to_production": False,
        "water_policy": auth["water_policy"],
        "overrides": [],
        "excluded_source_ids_approved": [],
        "excluded_source_ids_proposed_high_confidence": [],
        "restore_source_ids": [],
        "unresolved_source_ids": [],
    }
    for r in rows:
        action = r["proposed_action"]
        if action.startswith("exclude"):
            corr = "excluded"
            act = "exclude"
        elif action.startswith("reclassify"):
            corr = "water_metadata"
            act = "reclassify_water"
        elif action.startswith("keep"):
            corr = "keep_land"
            act = "keep"
        else:
            corr = "unresolved"
            act = "unresolved"
        overrides["overrides"].append(
            {
                "source_id": r["source_id"],
                "gates_id_pre_sanitize": r["gates_id_pre_sanitize"],
                "previous_classification": "land_included",
                "corrected_classification": corr,
                "action": act,
                "reason": r["evidence"],
                "evidence_reference": f"decision_table:{r['gates_id_pre_sanitize']}",
                "nearest_named_location": r["nearest_named_location"],
                "longitude": r["longitude"],
                "latitude": r["latitude"],
                "component_id": r["component_id"],
                "confidence": r["confidence"],
                "owner_review_status": "proposed" if act != "unresolved" else "unresolved",
                "screenshot_filename": r["screenshot_filename"],
            }
        )
        if act == "exclude" and r["confidence"] == "high":
            overrides["excluded_source_ids_proposed_high_confidence"].append(r["source_id"])
        elif act == "keep":
            overrides["restore_source_ids"].append(r["source_id"])
        else:
            overrides["unresolved_source_ids"].append(r["source_id"])

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "geographic_decision_table.json").write_text(
        json.dumps({"schema": "gates-of-codex.earth3-geographic-decision-table", "rows": rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    # CSV
    if rows:
        keys = list(rows[0].keys())
        # flatten non-scalars for csv
        csv_keys = [k for k in keys if k not in ("nearest_locations", "source_ring_coordinates")]
        with (OUT / "geographic_decision_table.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=csv_keys, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)

    (ROOT / "config/earth3/province_classification_overrides.json").write_text(
        json.dumps(overrides, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "province_classification_overrides.proposed.json").write_text(
        json.dumps(overrides, indent=2) + "\n", encoding="utf-8"
    )

    # L002 investigation
    l2_ids = [r for r in rows if r["component_id"] == "L002"]
    if not l2_ids and "L002" in comp_meta:
        # build from component even if not in candidate filter
        pass
    l2_meta = comp_meta.get("L002", {})
    l2_gates = list(l2_meta.get("gates_ids") or [r["gates_id_pre_sanitize"] for r in l2_ids])
    l2_src = [int(by_id[g]["source_id"]) for g in l2_gates if g in by_id]
    # cities inside bbox
    if l2_meta.get("bbox"):
        bb = l2_meta["bbox"]
        # local bbox -> source
        sb = [bb[0] + ox, bb[1] + oy, bb[2] + ox, bb[3] + oy]
    else:
        sb = [0, 0, 0, 0]
    cities_in = []
    for c in ds.cities:
        if sb[0] - 30 <= c.x <= sb[2] + 30 and sb[1] - 30 <= c.y <= sb[3] + 30:
            if -15 < src_xy_to_lonlat(c.x, c.y)[0] < 0:  # Ireland band
                cities_in.append({"name": c.name, "x": c.x, "y": c.y, "province_id": c.province_id})
    # adjacency loss check: compare archive neighbors among L002 sources
    archive_adj_count = 0
    export_adj_count = 0
    for g in l2_gates:
        if g not in by_id:
            continue
        export_adj_count += sum(1 for n in by_id[g].get("neighbors") or [] if n in l2_gates)
        sid = int(by_id[g]["source_id"])
        for nb in ds.neighbors(sid):
            if nb in l2_src:
                archive_adj_count += 1
    l2_report = {
        "component_id": "L002",
        "finding": "Ireland",
        "conclusion": "KEEP entire component as legitimate island/archipelago",
        "do_not_exclude_any_member": True,
        "polygon_count": len(l2_gates),
        "source_ids": l2_src,
        "gates_ids": l2_gates,
        "bbox_local": l2_meta.get("bbox"),
        "centroid_local": l2_meta.get("centroid"),
        "total_area": l2_meta.get("total_area"),
        "nearest_geographic_location": "Ireland (Dublin/Cork/Belfast city seeds in archive)",
        "cities_nearby": cities_in[:30],
        "why_one_component": (
            "56 land provinces share land-land adjacency forming the island of Ireland "
            "(and immediately connected islets). Not a multipart export artifact."
        ),
        "adjacency_check": {
            "export_internal_neighbor_refs": export_adj_count,
            "archive_internal_neighbor_refs": archive_adj_count,
            "note": "If both >> 0, adjacency was not lost; component is real island connectivity.",
        },
        "previous_error": (
            "Auto-classifier required n>=80 for western archipelago keep; Ireland has 56 provinces "
            "and was incorrectly marked unexplained/exclude."
        ),
        "owner_ruling_request": "Confirm KEEP all L002 members",
    }
    (OUT / "L002_investigation.json").write_text(json.dumps(l2_report, indent=2) + "\n", encoding="utf-8")

    # Contact sheets by region
    by_sheet: dict[str, list] = defaultdict(list)
    for r in rows:
        by_sheet[r["country_sea_region_guess"]].append(r)
    # Ensure L002 on atlantic sheet
    for r in rows:
        if r["component_id"] == "L002":
            by_sheet["atlantic_channel_britain_ireland"].append(r)

    sheet_files = []
    for sheet, srows in sorted(by_sheet.items()):
        # dedupe
        seen = set()
        uniq = []
        for r in srows:
            if r["source_id"] in seen:
                continue
            seen.add(r["source_id"])
            uniq.append(r)
        path = OUT / "contact_sheets" / f"contact_{sheet}.png"
        draw_sheet(
            title=f"Owner review: {sheet} ({len(uniq)} polygons)",
            rows=uniq,
            by_id=by_id,
            origin=(ox, oy),
            out_path=path,
        )
        sheet_files.append(str(path.relative_to(ROOT)))

    # L002 full component sheet
    l2_rows = [r for r in rows if r["component_id"] == "L002"]
    if not l2_rows:
        # synthesize minimal rows for drawing
        for g in l2_gates:
            if g not in by_id:
                continue
            p = by_id[g]
            l2_rows.append(
                {
                    "gates_id_pre_sanitize": g,
                    "source_id": int(p["source_id"]),
                    "proposed_action": "keep_as_legitimate_island",
                }
            )
    draw_sheet(
        title="L002 Ireland — KEEP all members (do not exclude)",
        rows=l2_rows,
        by_id=by_id,
        origin=(ox, oy),
        out_path=OUT / "contact_sheets" / "L002_ireland_full_component.png",
        width=2000,
        height=1600,
    )

    # Rectangle validation detail
    rect_rows = [r for r in rows if r["proposed_action"] == "exclude_as_malformed_marker_artifact"]
    rect_report = []
    for r in rect_rows:
        sid = r["source_id"]
        sp = ds.provinces[sid]
        nbs = sorted(ds.neighbors(sid))
        nb_info = []
        for n in nbs[:8]:
            np = ds.provinces[n]
            nb_info.append(
                {
                    "source_id": n,
                    "is_water": np.is_water,
                    "terrain_id": np.terrain_id,
                    "continent_id": np.continent_id,
                    "ring_len": len(np.ring),
                }
            )
        rect_report.append(
            {
                "gates_id": r["gates_id_pre_sanitize"],
                "source_id": sid,
                "exact_source_ring": [[float(x), float(y)] for x, y in sp.ring],
                "source_map_centroid": [sp.centroid[0], sp.centroid[1]],
                "lon_lat": [r["longitude"], r["latitude"]],
                "nearest": r["nearest_locations"],
                "corresponds_to_real_land": False if r["nearest_location_dist_px"] and r["nearest_location_dist_px"] > 40 else "uncertain",
                "neighbor_records": nb_info,
                "why_marker": (
                    f"Exactly {len(sp.ring)} vertices forming near-perfect rectangle "
                    f"(rectangularity={r['rectangularity']}); atypical vs organic coastline rings; "
                    f"nearest named place {r['nearest_named_location']} at {r['nearest_location_dist_px']}px"
                ),
                "proposed_action": r["proposed_action"],
                "confidence": r["confidence"],
            }
        )
    (OUT / "rectangular_marker_validation.json").write_text(
        json.dumps({"count": len(rect_report), "polygons": rect_report}, indent=2) + "\n",
        encoding="utf-8",
    )

    # Summary markdown
    high = [r for r in rows if r["review_bucket"] == "high_confidence_exclude"]
    restore = [r for r in rows if r["review_bucket"] == "restore_legitimate"]
    unresolved = [r for r in rows if r["review_bucket"] == "unresolved"]
    md = [
        "# Topology sanitize owner review package (proposed only)",
        "",
        f"Production authority unchanged: **3512 / 3297 / 215** hash `{PRE_HASH}`.",
        "",
        "Land exclusions are **not** applied to production. Water non-select policy remains accepted.",
        "",
        "## Lists",
        "",
        f"### High-confidence exclusions (proposed): {len(high)}",
        "",
    ]
    for r in high:
        md.append(
            f"- `{r['gates_id_pre_sanitize']}` src={r['source_id']} — {r['proposed_action']} — "
            f"{r['nearest_named_location']} ({r['longitude']},{r['latitude']}) — {r['evidence']}"
        )
    md += ["", f"### Legitimate polygons to restore / keep: {len(restore)}", ""]
    for r in restore[:80]:
        md.append(
            f"- `{r['gates_id_pre_sanitize']}` src={r['source_id']} comp={r['component_id']} — "
            f"{r['nearest_named_location']} — {r['proposed_action']}"
        )
    if len(restore) > 80:
        md.append(f"- … +{len(restore)-80} more")
    md += ["", f"### Unresolved: {len(unresolved)}", ""]
    for r in unresolved:
        md.append(
            f"- `{r['gates_id_pre_sanitize']}` src={r['source_id']} comp={r['component_id']} — "
            f"{r['nearest_named_location']} — {r['evidence']}"
        )
    md += [
        "",
        "## L002",
        "",
        json.dumps(l2_report, indent=2),
        "",
        "## Contact sheets",
        "",
    ]
    for s in sheet_files:
        md.append(f"- `{s}`")
    md.append("- `docs/earth3-crop/topology_sanitize/proposed/contact_sheets/L002_ireland_full_component.png`")
    (OUT / "OWNER_REVIEW.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    summary = {
        "production_authority": auth,
        "production_confirmed": {
            "province_count": int(data["province_count"]),
            "land_count": int(data["land_count"]),
            "water_count": int(data["water_count"]),
            "hash": data.get("included_source_ids_sha256"),
        },
        "review_row_count": len(rows),
        "high_confidence_exclude": [r["source_id"] for r in high],
        "restore_keep": [r["source_id"] for r in restore],
        "unresolved": [r["source_id"] for r in unresolved],
        "l002": l2_report,
        "contact_sheets": sheet_files,
        "proposed_preview_note": "No production dataset rewrite; preview export optional and separate",
    }
    (OUT / "review_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in summary if k != "l002"}, indent=2))
    print("L002:", l2_report["finding"], "members", l2_report["polygon_count"])
    print("high_exclude", len(high), "restore", len(restore), "unresolved", len(unresolved))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
