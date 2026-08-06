"""Render Earth3 crop candidate preview images and audit reports."""

from __future__ import annotations

import json
from pathlib import Path

from .crop import CropCandidate, CropResult, apply_crop
from .model import Earth3Dataset

try:
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Pillow is required for Earth3 crop previews") from exc


def render_crop_preview(
    dataset: Earth3Dataset,
    result: CropResult,
    output_path: str | Path,
    *,
    width: int = 1600,
    height: int = 1000,
) -> Path:
    """Draw included polygons, muted outside geography, crop rect, and key labels."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Focus camera on candidate rect with padding.
    rect = result.candidate.rect
    pad_x = (rect.max_x - rect.min_x) * 0.04
    pad_y = (rect.max_y - rect.min_y) * 0.04
    view = (
        rect.min_x - pad_x,
        rect.min_y - pad_y,
        rect.max_x + pad_x,
        rect.max_y + pad_y,
    )
    scale = min(width / (view[2] - view[0]), height / (view[3] - view[1]))

    def tx(x: float, y: float) -> tuple[float, float]:
        return (x - view[0]) * scale, (y - view[1]) * scale

    image = Image.new("RGB", (width, height), (18, 28, 38))
    draw = ImageDraw.Draw(image, "RGBA")
    included = set(result.included_ids)

    # Muted outside provinces that intersect the view.
    for pid, province in dataset.provinces.items():
        if pid in included:
            continue
        b = province.bounds
        if b[2] < view[0] or b[0] > view[2] or b[3] < view[1] or b[1] > view[3]:
            continue
        pts = [tx(x, y) for x, y in province.ring]
        if len(pts) >= 3:
            color = (40, 48, 58, 110) if province.is_water else (55, 52, 48, 120)
            draw.polygon(pts, fill=color)

    # Included provinces.
    for pid in result.included_ids:
        province = dataset.provinces[pid]
        pts = [tx(x, y) for x, y in province.ring]
        if len(pts) < 3:
            continue
        if province.is_water:
            fill = (40, 85, 120, 200)
            outline = (90, 150, 190, 220)
        else:
            fill = (120, 125, 105, 210)
            outline = (30, 30, 30, 180)
        draw.polygon(pts, fill=fill, outline=outline)

    # Crop rectangle.
    c0 = tx(rect.min_x, rect.min_y)
    c1 = tx(rect.max_x, rect.max_y)
    draw.rectangle([c0, c1], outline=(255, 210, 80, 255), width=3)

    # Orientation labels (approximate anchors in map space).
    labels = {
        "Iceland": (7300, 820),
        "Britain": (7800, 1400),
        "Iberia": (7600, 2500),
        "France": (8200, 1900),
        "Germany": (9000, 1600),
        "Italy": (9200, 2400),
        "Balkans": (9800, 2300),
        "Ukraine": (10400, 1700),
        "Crimea": (10650, 2100),
        "Donbas": (10850, 1850),
        "Turkey": (10500, 2600),
        "Caucasus": (11200, 2300),
        "N.Africa": (9000, 3400),
        "Scandi cut": (9600, rect.min_y + 40),
    }
    for text, (x, y) in labels.items():
        if not (view[0] <= x <= view[2] and view[1] <= y <= view[3]):
            continue
        px, py = tx(x, y)
        draw.text((px + 1, py + 1), text, fill=(0, 0, 0, 200))
        draw.text((px, py), text, fill=(240, 240, 230, 255))

    # HUD
    hud = [
        f"{result.candidate.id}: {result.candidate.title}",
        f"provinces={result.province_count} land={result.land_count} water={result.water_count}",
        f"vertices={result.vertex_count} edges={result.adjacency_edges}",
        f"land_components={result.disconnected_land_components}",
        f"rect=({rect.min_x:.0f},{rect.min_y:.0f})-({rect.max_x:.0f},{rect.max_y:.0f})",
    ]
    y = 10
    for line in hud:
        draw.text((11, y + 1), line, fill=(0, 0, 0, 220))
        draw.text((10, y), line, fill=(255, 255, 255, 255))
        y += 16

    image = image.convert("RGB")
    image.save(out, optimize=True)
    return out


def write_audit_report(
    dataset: Earth3Dataset,
    results: list[CropResult],
    output_path: str | Path,
    *,
    recommended_id: str,
) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "gates-of-codex.earth3-crop-audit",
        "schema_version": 1,
        "source_provinces": len(dataset.provinces),
        "canvas_size": list(dataset.canvas_size),
        "recommended_candidate_id": recommended_id,
        "recommendation_rationale": (
            "em_ref_tight best matches the supplied Europe-Mediterranean reference: "
            "keeps Iceland, cuts far-northern Scandinavia via min_y, and frames "
            "Crimea/Donbas/Turkey/N.Africa without silent continent==Europe selection."
        ),
        "status": "awaiting_owner_crop_approval",
        "candidates": [],
    }
    for result in results:
        est_geom_bytes = result.vertex_count * 16 + result.province_count * 64
        est_snapshot_bytes = result.province_count * 450 + result.adjacency_edges * 24
        payload["candidates"].append(
            {
                "id": result.candidate.id,
                "title": result.candidate.title,
                "description": result.candidate.description,
                "province_count": result.province_count,
                "land_province_count": result.land_count,
                "water_or_ocean_continent_count": result.water_count,
                "polygon_count": result.province_count,
                "total_vertices": result.vertex_count,
                "adjacency_edge_count": result.adjacency_edges,
                "source_bounds": list(result.source_bounds),
                "crop_rect": {
                    "min_x": result.candidate.rect.min_x,
                    "min_y": result.candidate.rect.min_y,
                    "max_x": result.candidate.rect.max_x,
                    "max_y": result.candidate.rect.max_y,
                },
                "estimated_runtime_geometry_bytes": est_geom_bytes,
                "estimated_frontend_snapshot_bytes": est_snapshot_bytes,
                "disconnected_land_components": result.disconnected_land_components,
                "missing_required_ids": result.missing_required_ids,
                "label_outside_polygon_count": len(result.label_outside_polygon),
                "label_outside_polygon_sample": result.label_outside_polygon[:25],
                "excluded_boundary_touch_count": len(result.excluded_boundary_ids),
                "excluded_boundary_sample": result.excluded_boundary_ids[:25],
                "notes": result.candidate.notes,
            }
        )

    # Boundary diffs between candidates.
    sets = {r.candidate.id: set(r.included_ids) for r in results}
    diffs = {}
    ids = list(sets)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            only_a = sorted(sets[a] - sets[b])
            only_b = sorted(sets[b] - sets[a])
            diffs[f"{a}_vs_{b}"] = {
                "only_in_first_count": len(only_a),
                "only_in_second_count": len(only_b),
                "only_in_first_sample": only_a[:40],
                "only_in_second_sample": only_b[:40],
            }
    payload["boundary_province_diffs"] = diffs
    payload["assumptions"] = [
        "Whole-polygon inclusion only; no clipped slivers.",
        "Crop is authored rect + centroid spill rule; not continent==Europe.",
        "Far-northern Scandinavia excluded by min_y; Iceland retained.",
        "No production Earth3 subset is committed until owner approves a candidate.",
        "AoH3 background art/scenarios are not used.",
    ]
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out
