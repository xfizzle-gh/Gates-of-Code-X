"""Render Earth3 crop candidate preview images and audit reports."""

from __future__ import annotations

import json
from pathlib import Path

from .crop import CropCandidate, CropRect, CropResult
from .locations import validate_required_locations
from .model import Earth3Dataset

try:
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Pillow is required for Earth3 crop previews") from exc


# Shared camera for overview comparison (Earth3 pixels).
DEFAULT_COMPARISON_VIEW = (6700.0, 500.0, 11800.0, 4300.0)

CLOSEUPS = {
    "scandinavia_north_russia": (8200.0, 700.0, 11200.0, 1800.0),
    "ukraine_donbas_caucasus": (9600.0, 1700.0, 11450.0, 3100.0),
    "north_africa_east_med": (7800.0, 2800.0, 10800.0, 3900.0),
}

KEY_LABELS = {
    "Iceland": (7300, 900),
    "Britain": (7800, 1400),
    "Ireland": (7600, 1550),
    "Iberia": (7600, 2500),
    "France": (8200, 1900),
    "Germany": (9000, 1600),
    "Italy": (9200, 2400),
    "Balkans": (9800, 2300),
    "Greece": (9700, 2700),
    "Ukraine": (10000, 1900),
    "Crimea": (10020, 2470),
    "Kherson": (9935, 2345),
    "Zaporizhzhia": (10075, 2255),
    "Donetsk": (10195, 2260),
    "Luhansk": (10265, 2225),
    "Rostov": (10280, 2300),
    "Turkey": (10050, 2850),
    "Caucasus": (10600, 2650),
    "N.Africa coast": (9000, 3400),
    "Levant edge": (10200, 3200),
    "Murmansk": (9999, 474),
    "Arkhangelsk": (10325, 927),
}


def render_crop_preview(
    dataset: Earth3Dataset,
    result: CropResult,
    output_path: str | Path,
    *,
    width: int = 1600,
    height: int = 1000,
    view: tuple[float, float, float, float] | None = None,
    reference_outline: list[list[float]] | None = None,
    title_suffix: str = "",
    highlight_boundary: bool = True,
) -> Path:
    """Draw included polygons, muted outside geography, mask/rect, and key labels."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if view is None:
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
    excluded_boundary = set(result.excluded_boundary_ids)
    review = set(result.threshold_review_ids)

    # Muted outside provinces that intersect the view.
    for pid, province in dataset.provinces.items():
        if pid in included:
            continue
        b = province.bounds
        if b[2] < view[0] or b[0] > view[2] or b[3] < view[1] or b[1] > view[3]:
            continue
        pts = [tx(x, y) for x, y in province.ring]
        if len(pts) < 3:
            continue
        if highlight_boundary and pid in excluded_boundary:
            color = (120, 55, 55, 160)
        elif highlight_boundary and pid in review:
            color = (140, 110, 40, 140)
        else:
            color = (40, 48, 58, 110) if province.is_water else (55, 52, 48, 120)
        draw.polygon(pts, fill=color)

    # Included provinces.
    for pid in result.included_ids:
        province = dataset.provinces[pid]
        pts = [tx(x, y) for x, y in province.ring]
        if len(pts) < 3:
            continue
        reason = result.inclusion_reason.get(pid, "")
        if province.is_water:
            fill = (40, 85, 120, 200)
            outline = (90, 150, 190, 220)
        elif reason == "required_include":
            fill = (150, 140, 90, 220)
            outline = (40, 40, 20, 200)
        elif reason.startswith("mask_overlap") and reason != "mask_overlap_full":
            fill = (130, 135, 100, 210)
            outline = (200, 160, 40, 220)
        else:
            fill = (120, 125, 105, 210)
            outline = (30, 30, 30, 180)
        draw.polygon(pts, fill=fill, outline=outline)

    # Authored mask rings (magenta) and query rect (gold).
    cand = result.candidate
    for ring in cand.mask_rings:
        pts = [tx(x, y) for x, y in ring]
        if len(pts) >= 2:
            draw.line(pts + [pts[0]], fill=(220, 80, 200, 255), width=2)
    rect = cand.rect
    c0 = tx(rect.min_x, rect.min_y)
    c1 = tx(rect.max_x, rect.max_y)
    draw.rectangle([c0, c1], outline=(255, 210, 80, 200), width=2)

    if result.export_rect is not None:
        er = result.export_rect
        draw.rectangle(
            [tx(er.min_x, er.min_y), tx(er.max_x, er.max_y)],
            outline=(120, 220, 255, 220),
            width=2,
        )

    if reference_outline and len(reference_outline) >= 3:
        pts = [tx(float(p[0]), float(p[1])) for p in reference_outline]
        draw.line(pts + [pts[0]], fill=(80, 220, 140, 255), width=2)

    for text, (x, y) in KEY_LABELS.items():
        if not (view[0] <= x <= view[2] and view[1] <= y <= view[3]):
            continue
        px, py = tx(x, y)
        color = (255, 120, 120, 255) if text in {"Murmansk", "Arkhangelsk"} else (240, 240, 230, 255)
        draw.text((px + 1, py + 1), text, fill=(0, 0, 0, 200))
        draw.text((px, py), text, fill=color)

    hud = [
        f"{result.candidate.id}: {result.candidate.title}{title_suffix}",
        f"mode={result.candidate.selection_mode} thr={result.candidate.inclusion_threshold}",
        f"provinces={result.province_count} land={result.land_count} water={result.water_count}",
        f"vertices={result.vertex_count} edges={result.adjacency_edges} "
        f"components={result.disconnected_land_components}",
        f"threshold_review={len(result.threshold_review_ids)} "
        f"excl_boundary={len(result.excluded_boundary_ids)}",
    ]
    y = 10
    for line in hud:
        draw.text((11, y + 1), line, fill=(0, 0, 0, 220))
        draw.text((10, y), line, fill=(255, 255, 255, 255))
        y += 16

    # Legend
    legend_y = height - 70
    draw.text((10, legend_y), "gold=query rect  magenta=mask  green=reference outline  cyan=export bounds", fill=(200, 200, 200, 255))
    draw.text((10, legend_y + 16), "red muted=excluded boundary  olive=required include  Murmansk/Arkhangelsk labels forced", fill=(200, 200, 200, 255))

    image = image.convert("RGB")
    image.save(out, optimize=True)
    return out


def write_audit_report(
    dataset: Earth3Dataset,
    results: list[CropResult],
    output_path: str | Path,
    *,
    recommended_id: str | None = None,
    config_payload: dict | None = None,
) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "schema": "gates-of-codex.earth3-crop-audit",
        "schema_version": 2,
        "source_provinces": len(dataset.provinces),
        "canvas_size": list(dataset.canvas_size),
        "adjacency_source": {
            "directed_edge_count": dataset.source_directed_edge_count,
            "undirected_edge_count_after_symmetrize": dataset.undirected_edge_count,
            "one_way_source_pair_count": len(dataset.one_way_source_pairs),
            "mutual_source_pair_count": len(dataset.mutual_source_pairs),
            "one_way_storage_is_expected": True,
            "notes": (
                "Earth3 stores undirected neighbors mostly as single directed "
                "pid->wp records. Importer symmetrizes for gameplay adjacency."
            ),
        },
        "city_count": len(dataset.cities),
        "permission": {
            "status": "OWNER_ASSERTED_GRANT",
            "asserted_by": "repository owner (issue #92 / agent brief)",
            "scope_claimed": [
                "use applicable Earth3 province geometry",
                "convert and modify geometry/adjacency for Gates of Code:X",
                "redistribute converted province geometry and adjacency in this project",
            ],
            "not_present_in_repo": [
                "signed license instrument",
                "rights-holder email/PDF attachment",
            ],
            "excluded_from_grant_as_understood": [
                "original 81MB archive commit",
                "AoH3 background tiles/art",
                "AoH3 scenarios, owners, diplomacy, wonders, formables",
            ],
            "product_shape": "APPROVED_EXACT_IMPORT_CROPPED_THEATRE",
        },
        "recommended_candidate_id": recommended_id,
        "recommendation_status": (
            "no_production_recommendation_until_owner_reviews_masked_candidate"
        ),
        "status": "awaiting_owner_crop_approval",
        "candidates": [],
    }
    if config_payload:
        payload["mask_defaults"] = config_payload.get("mask_defaults")
        payload["rules"] = config_payload.get("rules")

    by_id = {r.candidate.id: r for r in results}
    tight = by_id.get("em_ref_tight")

    for result in results:
        est_geom_bytes = result.vertex_count * 16 + result.province_count * 64
        est_snapshot_bytes = result.province_count * 450 + result.adjacency_edges * 24
        region_fail = sorted(
            name for name, row in result.region_coverage.items() if not row.get("ok")
        )
        entry: dict = {
            "id": result.candidate.id,
            "title": result.candidate.title,
            "description": result.candidate.description,
            "selection_mode": result.candidate.selection_mode,
            "inclusion_threshold": result.candidate.inclusion_threshold,
            "review_band": [
                result.candidate.review_band_low,
                result.candidate.review_band_high,
            ],
            "province_count": result.province_count,
            "land_province_count": result.land_count,
            "water_or_ocean_continent_count": result.water_count,
            "polygon_count": result.province_count,
            "total_vertices": result.vertex_count,
            "adjacency_edge_count": result.adjacency_edges,
            "source_bounds": list(result.source_bounds),
            "query_rect": {
                "min_x": result.candidate.rect.min_x,
                "min_y": result.candidate.rect.min_y,
                "max_x": result.candidate.rect.max_x,
                "max_y": result.candidate.rect.max_y,
            },
            "export_rect": (
                {
                    "min_x": result.export_rect.min_x,
                    "min_y": result.export_rect.min_y,
                    "max_x": result.export_rect.max_x,
                    "max_y": result.export_rect.max_y,
                }
                if result.export_rect
                else None
            ),
            "mask_ring_count": len(result.candidate.mask_rings),
            "estimated_runtime_geometry_bytes": est_geom_bytes,
            "estimated_frontend_snapshot_bytes": est_snapshot_bytes,
            "disconnected_land_components": result.disconnected_land_components,
            "missing_required_ids": result.missing_required_ids,
            "required_include_ids": list(result.candidate.required_include_ids),
            "explicit_exclude_ids": list(result.candidate.explicit_exclude_ids),
            "threshold_review_count": len(result.threshold_review_ids),
            "threshold_review_ids": result.threshold_review_ids[:80],
            "label_outside_polygon_count": len(result.label_outside_polygon),
            "label_outside_polygon_sample": result.label_outside_polygon[:25],
            "excluded_boundary_touch_count": len(result.excluded_boundary_ids),
            "excluded_boundary_sample": result.excluded_boundary_ids[:40],
            "far_north_excluded_sample": result.far_north_excluded_sample,
            "region_coverage": result.region_coverage,
            "region_coverage_failures": region_fail,
            "notes": result.candidate.notes,
        }
        if tight is not None and result.candidate.id != tight.candidate.id:
            a = set(result.included_ids)
            b = set(tight.included_ids)
            only_this = sorted(a - b)
            only_tight = sorted(b - a)
            entry["diff_vs_em_ref_tight"] = {
                "added_count": len(only_this),
                "removed_count": len(only_tight),
                "added_sample": only_this[:50],
                "removed_sample": only_tight[:50],
            }
        # Explicit city status for Murmansk / Arkhangelsk
        entry["forced_far_north_city_status"] = _city_status(
            dataset, result, ("Murmansk", "Arkhangelsk")
        )
        entry["exact_required_locations"] = validate_required_locations(
            dataset, set(result.included_ids)
        )
        payload["candidates"].append(entry)

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
        "em_reference_masked uses authored multi-ring mask + overlap ratio threshold.",
        "Rectangle candidates retained for comparison; rect is broad query only on masked mode.",
        "Murmansk and Arkhangelsk must be excluded on the masked candidate.",
        "No production Earth3 subset is committed until owner approves a candidate.",
        "No production recommendation is made in this audit package.",
        "AoH3 background art/scenarios are not used.",
    ]
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def _city_status(
    dataset: Earth3Dataset, result: CropResult, names: tuple[str, ...]
) -> list[dict[str, object]]:
    included = set(result.included_ids)
    out: list[dict[str, object]] = []
    for needle in names:
        needle_l = needle.casefold()
        for city in dataset.cities:
            if needle_l not in city.name.casefold():
                continue
            out.append(
                {
                    "city": city.name,
                    "source_province_id": city.province_id,
                    "included": city.province_id in included,
                    "x": city.x,
                    "y": city.y,
                    "overlap_ratio": result.overlap_ratios.get(city.province_id),
                }
            )
    return out


def load_shared_view(config_path: str | Path) -> tuple[float, float, float, float]:
    payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    view = payload.get("shared_comparison_view")
    if not view:
        return DEFAULT_COMPARISON_VIEW
    return (
        float(view["min_x"]),
        float(view["min_y"]),
        float(view["max_x"]),
        float(view["max_y"]),
    )


def load_reference_outline(config_path: str | Path) -> list[list[float]]:
    payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    raw = payload.get("reference_extent_outline") or []
    return [[float(p[0]), float(p[1])] for p in raw]
