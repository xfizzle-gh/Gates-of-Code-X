from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .europe import build_goe_europe_campaign
from .models import CampaignState, Faction, Province
from .strategic import ensure_strategic_layer
from .strategic_map import decode_png_rgb, import_strategic_map, write_png_rgb


MAP_ID = "europe_mediterranean_from_goe"
DEFAULT_OUTPUT_DIR = "godot/assets/maps/europe_mediterranean/from_goe"
INTERIM_DIR = Path("godot/assets/maps/europe/interim_goe")

# GoE marker-space theatre (not lon/lat). Initial rectangular selection only.
MARKER_THEATRE = {
    "x_min": -4.2,
    "x_max": 3.2,
    "y_min": -2.2,
    "y_max": 5.0,
}

# Whole-province overrides after marker bounds (never slice geometry).
FORCE_INCLUDE_PROVINCE_IDS: frozenset[str] = frozenset(
    {
        "province_0101",  # Casablanca
        "province_0111",  # Spanish Africa / northern Morocco belt
        "province_0114",  # Algiers
        "province_0117",  # Constantine
        "province_0112",  # Tunis
        "province_0095",  # Gabes
        "province_0097",  # Tripoli
        "province_0089",  # Tripolitania
        "province_0098",  # Benghasi
        "province_0091",  # Cyrenaica
        "province_0099",  # Derna
        "province_0094",  # Alexandria
        "province_0079",  # Cairo
        "province_0086",  # Suez
        "province_0078",  # Sinai
        "province_0090",  # Palestine
        "province_0107",  # Lebanon
        "province_0102",  # Syria
        "province_0110",  # Aleppo
        "province_0113",  # Cyprus
    }
)

# Deep interior only. Coastal Libyan/Egyptian approaches are CLIPPED, not deleted,
# so the Mediterranean silhouette stays intact.
FORCE_EXCLUDE_PROVINCE_IDS: frozenset[str] = frozenset(
    {
        "province_0066",  # Western Desert
        "province_0081",  # Fezzan
        "province_0103",  # Algerian Desert
        "province_0080",  # Marrakech
        "province_0062",  # deep south generic
        "province_0072",  # deep south/east generic
        "province_0083",  # Jordan interior
    }
)

# Marker-space clip mask (tighter south than selection). Edge provinces intersecting
# this rect are reshaped; pixels outside become sea. Whole provinces are not deleted
# merely for straddling the boundary.
CLIP_THEATRE = {
    "x_min": -4.2,
    "x_max": 3.2,
    # Marker y increases north. Keep Nile Delta (~-1.56) and Maghreb coast;
    # clip only deeper Sahara south of that belt.
    "y_min": -1.72,
    "y_max": 5.0,
}

MIN_CLIPPED_PIXELS = 12
MIN_CLIP_RATIO_TO_DROP = 0.08

EXCLUDES = [
    "deep Central Asia / far Russia east of theatre",
    "deep Sahara / interior North Africa",
    "far Atlantic / Americas filler",
    "extreme arctic filler provinces outside Scandinavia framing",
]


def _load_interim() -> tuple[dict, object]:
    manifest_path = INTERIM_DIR / "map_manifest.json"
    texture_path = INTERIM_DIR / "province_id_map.png"
    if not manifest_path.is_file() or not texture_path.is_file():
        raise FileNotFoundError(
            f"Interim GoE assets missing under {INTERIM_DIR}. "
            "Import the working GoE color-ID map first."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    image = decode_png_rgb(texture_path)
    return manifest, image


def select_theatre_provinces(province_table: list[dict]) -> tuple[list[dict], dict]:
    """Select whole provinces: marker bounds → force include → force exclude."""

    by_id = {str(row["province_id"]): row for row in province_table}
    selected: dict[str, dict] = {}
    marker_bound_count = 0
    for row in province_table:
        pid = str(row["province_id"])
        anchor = row.get("marker_anchor") or [0.0, 0.0]
        x, y = float(anchor[0]), float(anchor[1])
        if (
            MARKER_THEATRE["x_min"] <= x <= MARKER_THEATRE["x_max"]
            and MARKER_THEATRE["y_min"] <= y <= MARKER_THEATRE["y_max"]
        ):
            selected[pid] = row
            marker_bound_count += 1

    forced_in = []
    for pid in sorted(FORCE_INCLUDE_PROVINCE_IDS):
        row = by_id.get(pid)
        if row is None:
            continue
        if pid not in selected:
            forced_in.append(
                {
                    "province_id": pid,
                    "display_name": str(row.get("display_name", pid)),
                    "reason": "force_include_mediterranean_coastal",
                }
            )
        selected[pid] = row

    forced_out = []
    for pid in sorted(FORCE_EXCLUDE_PROVINCE_IDS):
        row = selected.pop(pid, None)
        if row is None:
            continue
        forced_out.append(
            {
                "province_id": pid,
                "display_name": str(row.get("display_name", pid)),
                "reason": "force_exclude_deep_africa_or_interior",
            }
        )

    kept = list(selected.values())
    if len(kept) < 80:
        raise RuntimeError(f"Theatre selection too small: {len(kept)} provinces")
    report = {
        "marker_bound_count": marker_bound_count,
        "force_included": forced_in,
        "force_excluded": forced_out,
        "final_count": len(kept),
        "force_include_ids": sorted(FORCE_INCLUDE_PROVINCE_IDS),
        "force_exclude_ids": sorted(FORCE_EXCLUDE_PROVINCE_IDS),
    }
    return kept, report


def _province_pixel_stats(image) -> dict[tuple[int, int, int], dict]:
    """Per-color pixel count and centroid on the full ID map."""

    stats: dict[tuple[int, int, int], dict] = {}
    for y in range(image.height):
        for x in range(image.width):
            color = image.color_at(x, y)
            if color == (0, 0, 0) or color == (255, 255, 255):
                continue
            row = stats.get(color)
            if row is None:
                row = {"count": 0, "sx": 0.0, "sy": 0.0, "min_x": x, "max_x": x, "min_y": y, "max_y": y}
                stats[color] = row
            row["count"] += 1
            row["sx"] += x
            row["sy"] += y
            row["min_x"] = min(row["min_x"], x)
            row["max_x"] = max(row["max_x"], x)
            row["min_y"] = min(row["min_y"], y)
            row["max_y"] = max(row["max_y"], y)
    for row in stats.values():
        n = max(row["count"], 1)
        row["cx"] = row["sx"] / n
        row["cy"] = row["sy"] / n
    return stats


def _fit_marker_to_pixel(
    province_table: list[dict],
    color_stats: dict[tuple[int, int, int], dict],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Linear map marker (mx,my) -> pixel (px,py) using province anchors/centroids."""

    pairs: list[tuple[float, float, float, float]] = []
    for row in province_table:
        color = tuple(int(c) for c in row.get("rgb", []))
        stat = color_stats.get(color)
        if stat is None or stat["count"] < 8:
            continue
        anchor = row.get("marker_anchor") or [0.0, 0.0]
        pairs.append((float(anchor[0]), float(anchor[1]), float(stat["cx"]), float(stat["cy"])))
    if len(pairs) < 8:
        raise RuntimeError("Not enough provinces to fit marker→pixel map")

    def fit_axis(src_a: list[float], src_b: list[float], dst: list[float]) -> tuple[float, float, float]:
        # dst ~= p*src_a + q*src_b + r
        n = float(len(dst))
        sa = sum(src_a)
        sb = sum(src_b)
        sd = sum(dst)
        saa = sum(a * a for a in src_a)
        sbb = sum(b * b for b in src_b)
        sab = sum(a * b for a, b in zip(src_a, src_b))
        sad = sum(a * d for a, d in zip(src_a, dst))
        sbd = sum(b * d for b, d in zip(src_b, dst))
        # Solve 3x3 normal equations.
        m = [
            [saa, sab, sa, sad],
            [sab, sbb, sb, sbd],
            [sa, sb, n, sd],
        ]
        for col in range(3):
            pivot = max(range(col, 3), key=lambda r: abs(m[r][col]))
            m[col], m[pivot] = m[pivot], m[col]
            div = m[col][col] or 1e-12
            for j in range(col, 4):
                m[col][j] /= div
            for row_i in range(3):
                if row_i == col:
                    continue
                factor = m[row_i][col]
                for j in range(col, 4):
                    m[row_i][j] -= factor * m[col][j]
        return m[0][3], m[1][3], m[2][3]

    mxs = [p[0] for p in pairs]
    mys = [p[1] for p in pairs]
    pxs = [p[2] for p in pairs]
    pys = [p[3] for p in pairs]
    return fit_axis(mxs, mys, pxs), fit_axis(mxs, mys, pys)


def _marker_to_pixel(
    mx: float,
    my: float,
    x_map: tuple[float, float, float],
    y_map: tuple[float, float, float],
) -> tuple[float, float]:
    p, q, r = x_map
    s, t, u = y_map
    return p * mx + q * my + r, s * mx + t * my + u


def generate_europe_mediterranean_from_goe(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    pad_px: int = 12,
) -> dict:
    """Crop/clip the working interim GoE color-ID map to a Europe–Mediterranean theatre."""

    manifest, image = _load_interim()
    source_table = list(manifest.get("province_table", []))
    color_stats = _province_pixel_stats(image)
    x_map, y_map = _fit_marker_to_pixel(source_table, color_stats)

    # Pixel-space clip rectangle from CLIP_THEATRE corners.
    corners = [
        (CLIP_THEATRE["x_min"], CLIP_THEATRE["y_min"]),
        (CLIP_THEATRE["x_min"], CLIP_THEATRE["y_max"]),
        (CLIP_THEATRE["x_max"], CLIP_THEATRE["y_min"]),
        (CLIP_THEATRE["x_max"], CLIP_THEATRE["y_max"]),
    ]
    pix = [_marker_to_pixel(mx, my, x_map, y_map) for mx, my in corners]
    clip_min_x = max(0, int(min(p[0] for p in pix)) - pad_px)
    clip_max_x = min(image.width - 1, int(max(p[0] for p in pix)) + pad_px)
    clip_min_y = max(0, int(min(p[1] for p in pix)) - pad_px)
    clip_max_y = min(image.height - 1, int(max(p[1] for p in pix)) + pad_px)

    selected_rows, selection_report = select_theatre_provinces(source_table)
    selected_ids = {str(row["province_id"]) for row in selected_rows}
    color_to_row = {tuple(int(c) for c in row["rgb"]): row for row in source_table}

    # Also keep any non-excluded province that has pixels inside the clip rect
    # (preserves edge landmasses whose anchors sit just outside marker bounds).
    intersecting_ids: set[str] = set()
    for color, stat in color_stats.items():
        row = color_to_row.get(color)
        if row is None:
            continue
        pid = str(row["province_id"])
        if pid in FORCE_EXCLUDE_PROVINCE_IDS:
            continue
        if (
            stat["max_x"] < clip_min_x
            or stat["min_x"] > clip_max_x
            or stat["max_y"] < clip_min_y
            or stat["min_y"] > clip_max_y
        ):
            continue
        intersecting_ids.add(pid)
        if pid not in selected_ids:
            selected_rows.append(row)
            selected_ids.add(pid)

    kept_colors = {
        tuple(int(c) for c in row["rgb"])
        for row in selected_rows
        if str(row["province_id"]) not in FORCE_EXCLUDE_PROVINCE_IDS
    }
    kept_by_color = {
        tuple(int(c) for c in row["rgb"]): row
        for row in selected_rows
        if str(row["province_id"]) not in FORCE_EXCLUDE_PROVINCE_IDS
    }

    # Output crop tightly around clip rect.
    min_x, min_y, max_x, max_y = clip_min_x, clip_min_y, clip_max_x, clip_max_y
    crop_w = max_x - min_x + 1
    crop_h = max_y - min_y + 1

    sea = (0, 0, 0)
    cropped = bytearray(crop_w * crop_h * 3)
    pixel_counts: dict[str, int] = defaultdict(int)
    full_counts: dict[str, int] = {
        str(kept_by_color[c]["province_id"]): int(color_stats.get(c, {}).get("count", 0))
        for c in kept_colors
    }
    for y in range(crop_h):
        for x in range(crop_w):
            sx, sy = min_x + x, min_y + y
            color = image.color_at(sx, sy)
            if color not in kept_colors:
                color = sea
            else:
                pid = str(kept_by_color[color]["province_id"])
                pixel_counts[pid] += 1
            i = (y * crop_w + x) * 3
            cropped[i : i + 3] = bytes(color)

    # Classify clipped vs intact; drop tiny remnants from gameplay.
    clipped_ids: list[dict] = []
    dropped_tiny: list[dict] = []
    active_rows: list[dict] = []
    for color, row in kept_by_color.items():
        pid = str(row["province_id"])
        kept_px = pixel_counts.get(pid, 0)
        full_px = max(full_counts.get(pid, 0), 1)
        ratio = kept_px / full_px
        # Drop only near-empty clipped remnants, not naturally small intact provinces.
        if kept_px < MIN_CLIPPED_PIXELS or (
            ratio < MIN_CLIP_RATIO_TO_DROP and kept_px < full_px
        ):
            dropped_tiny.append(
                {
                    "province_id": pid,
                    "display_name": str(row.get("display_name", pid)),
                    "pixels_kept": kept_px,
                    "pixels_full": full_px,
                    "kept_ratio": round(ratio, 3),
                }
            )
            continue
        entry = dict(row)
        if ratio < 0.97:
            clipped_ids.append(
                {
                    "province_id": pid,
                    "display_name": str(row.get("display_name", pid)),
                    "pixels_kept": kept_px,
                    "pixels_full": full_px,
                    "kept_ratio": round(ratio, 3),
                    "role": "gameplay_clipped",
                }
            )
            entry["mapping_method"] = "goe_theatre_edge_clip"
        active_rows.append(entry)

    active_ids = {str(row["province_id"]) for row in active_rows}
    active_colors = {tuple(int(c) for c in row["rgb"]) for row in active_rows}

    # Second pass: erase non-active colors (tiny remnants).
    if dropped_tiny:
        drop_colors = {
            tuple(int(c) for c in row["rgb"])
            for row in source_table
            if str(row["province_id"]) in {d["province_id"] for d in dropped_tiny}
        }
        for y in range(crop_h):
            for x in range(crop_w):
                i = (y * crop_w + x) * 3
                color = (cropped[i], cropped[i + 1], cropped[i + 2])
                if color in drop_colors:
                    cropped[i : i + 3] = bytes(sea)

    color_to_pid = {
        tuple(int(c) for c in row["rgb"]): str(row["province_id"]) for row in active_rows
    }
    owners_grid = [-1] * (crop_w * crop_h)
    pid_index = {pid: i for i, pid in enumerate(sorted(active_ids))}
    index_pid = {i: pid for pid, i in pid_index.items()}
    sums: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    pixels_by_pid: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for y in range(crop_h):
        for x in range(crop_w):
            i = (y * crop_w + x) * 3
            color = (cropped[i], cropped[i + 1], cropped[i + 2])
            pid = color_to_pid.get(color)
            if pid is None:
                continue
            owners_grid[y * crop_w + x] = pid_index[pid]
            sums[pid][0] += x
            sums[pid][1] += y
            sums[pid][2] += 1
            pixels_by_pid[pid].append((x, y))

    # Ordinary land adjacency from final clipped raster.
    # GoE ID maps separate provinces with white/black border pixels, so scan through
    # a small ignored gap (same idea as strategic_map.extract_color_adjacency).
    max_gap = 6
    land_edges: set[tuple[str, str]] = set()
    for y in range(crop_h):
        for x in range(crop_w):
            a = owners_grid[y * crop_w + x]
            if a < 0:
                continue
            for dx, dy in ((1, 0), (0, 1)):
                cx, cy = x + dx, y + dy
                gap = 0
                while 0 <= cx < crop_w and 0 <= cy < crop_h:
                    b = owners_grid[cy * crop_w + cx]
                    if b >= 0:
                        if b != a:
                            left, right = sorted((index_pid[a], index_pid[b]))
                            land_edges.add((left, right))
                        break
                    gap += 1
                    if gap > max_gap:
                        break
                    cx += dx
                    cy += dy
    land_neighbors: dict[str, list[str]] = defaultdict(list)
    for left, right in sorted(land_edges):
        land_neighbors[left].append(right)
        land_neighbors[right].append(left)

    # Optional authored non-land edges from source, only if both endpoints remain.
    authored_edges: list[dict] = []
    # GoE interim table has no typed strait/ferry today; reserved for future.
    authored_neighbors: dict[str, list[str]] = defaultdict(list)

    def _snap_anchor(pid: str, cx: float, cy: float) -> tuple[float, float, bool]:
        """Ensure anchor lies on a pixel of this province; snap if needed."""
        ix, iy = int(round(cx)), int(round(cy))
        if 0 <= ix < crop_w and 0 <= iy < crop_h and owners_grid[iy * crop_w + ix] == pid_index[pid]:
            return float(ix), float(iy), False
        best = None
        best_d = 10**18
        for px, py in pixels_by_pid[pid]:
            d = (px - cx) * (px - cx) + (py - cy) * (py - cy)
            if d < best_d:
                best_d = d
                best = (px, py)
        if best is None:
            raise RuntimeError(f"No pixels for province {pid}")
        return float(best[0]), float(best[1]), True

    table = []
    anchors_snapped = 0
    for row in sorted(active_rows, key=lambda item: str(item["province_id"])):
        pid = str(row["province_id"])
        count = max(int(sums[pid][2]), 1)
        cx = sums[pid][0] / count
        cy = sums[pid][1] / count
        ax, ay, snapped = _snap_anchor(pid, cx, cy)
        if snapped:
            anchors_snapped += 1
        land = sorted(set(land_neighbors.get(pid, [])))
        authored = sorted(set(authored_neighbors.get(pid, [])))
        all_neighbors = sorted(set(land) | set(authored))
        table.append(
            {
                "province_id": pid,
                "display_name": row.get("display_name", pid),
                "name_is_human_readable": bool(row.get("name_is_human_readable", True)),
                "rgb": list(row["rgb"]),
                "marker_anchor": [float(ax), float(crop_h - 1 - ay)],
                "source_neighbors": all_neighbors,
                "land_neighbors": land,
                "edge_types": {
                    **{n: "land" for n in land},
                    **{n: "ferry_or_sea_lane" for n in authored if n not in land},
                },
                "source_province_id": row.get("source_province_id", pid),
                "mapping_method": row.get("mapping_method", "goe_theatre_crop"),
                "provenance": {
                    "generator": "europe_mediterranean_from_goe_v3_raster_adj",
                    "source_map_id": manifest.get("map_id", "goe_europe"),
                    "marker_theatre": dict(MARKER_THEATRE),
                    "clip_theatre": dict(CLIP_THEATRE),
                    "crop_px": [min_x, min_y, max_x, max_y],
                    "pixels": int(sums[pid][2]),
                    "anchor_snapped": snapped,
                },
            }
        )

    # Validate every anchor samples its own color.
    for row in table:
        ax = int(round(row["marker_anchor"][0]))
        ay = crop_h - 1 - int(round(row["marker_anchor"][1]))
        i = (ay * crop_w + ax) * 3
        color = (cropped[i], cropped[i + 1], cropped[i + 2])
        if color_to_pid.get(color) != row["province_id"]:
            raise RuntimeError(f"Anchor outside province {row['province_id']}")

    selection_report["land_adjacency_edges"] = len(land_edges)
    selection_report["authored_non_land_edges"] = len(authored_edges)
    selection_report["anchors_snapped"] = anchors_snapped

    selection_report["intersecting_edge_added"] = sorted(intersecting_ids - set(selection_report.get("force_include_ids", [])))
    selection_report["clipped_provinces"] = clipped_ids
    selection_report["clipped_count"] = len(clipped_ids)
    selection_report["dropped_tiny_after_clip"] = dropped_tiny
    selection_report["final_count"] = len(table)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    id_png = out / "province_id_map.png"
    write_png_rgb(id_png, crop_w, crop_h, bytes(cropped))

    # Procedural presentation background from land silhouette of the crop.
    bg = bytearray(crop_w * crop_h * 3)
    for y in range(crop_h):
        for x in range(crop_w):
            i = (y * crop_w + x) * 3
            color = (cropped[i], cropped[i + 1], cropped[i + 2])
            if color == sea:
                bg[i : i + 3] = bytes((236, 240, 244))  # light neutral sea/panel
            else:
                # soft parchment land under tint
                bg[i : i + 3] = bytes((228, 222, 208))
    bg_path = out / "background_procedural.png"
    write_png_rgb(bg_path, crop_w, crop_h, bytes(bg))

    result = import_strategic_map(
        id_png,
        table,
        out / "map_manifest.json",
        map_id=MAP_ID,
        provenance="derived_from_interim_goe_europe_theatre_crop",
        ignored_colors=(sea, (255, 255, 255)),
        texture_output=id_png,
    )
    result["asset_status"] = "derived_project_theatre"
    result["theatre"] = {
        "name": "Europe-Mediterranean from GoE",
        "marker_bounds": dict(MARKER_THEATRE),
        "crop_px": {
            "x0": min_x,
            "y0": min_y,
            "x1": max_x,
            "y1": max_y,
            "width": crop_w,
            "height": crop_h,
        },
        "source_texture": "godot/assets/maps/europe/interim_goe/province_id_map.png",
        "source_province_count": len(source_table),
        "theatre_province_count": len(table),
        "selection": selection_report,
        "excludes": EXCLUDES,
    }
    result["visual_background_policy"] = {
        "repo_stores_pack_artwork": False,
        "default_background": "background_procedural.png",
        "role": "presentation_underlay_only",
        "gameplay_authority": "color_id_province_map",
        "status_label": "project_procedural",
    }
    result["visual_background"] = {
        "path": "background_procedural.png",
        "width": crop_w,
        "height": crop_h,
        "asset_status": "project_procedural",
        "layer_role": "presentation_underlay_only",
    }
    result["provenance_table"] = {
        "province_geometry": "interim_goe_color_id_crop_with_edge_clip",
        "province_ids": "preserved_from_goe_graph_where_in_theatre",
        "edge_handling": "intersecting_provinces_clipped_to_theatre_mask",
        "adjacency": "recomputed_land_touch_from_final_clipped_raster",
        "visual_background": "procedural_light_neutral_from_crop_silhouette",
        "pack_artwork": "not_used",
    }
    (out / "map_manifest.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out / "README.md").write_text(
        "\n".join(
            [
                "# Europe–Mediterranean theatre (from GoE)",
                "",
                f"- map_id: `{MAP_ID}`",
                f"- provinces: {len(table)} (from interim GoE 517)",
                f"- texture: {crop_w}×{crop_h} crop of interim GoE color-ID",
                "- gameplay authority: color-ID layer",
                "- background: project-owned procedural underlay only",
                "- pack artwork: not used",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return result


def build_europe_mediterranean_from_goe_campaign(
    *,
    manifest_path: str | Path | None = None,
    selected_faction: Faction = Faction.NATO,
) -> CampaignState:
    """Build campaign by filtering the working GoE Europe scenario to the theatre crop."""

    path = Path(manifest_path) if manifest_path else Path(DEFAULT_OUTPUT_DIR) / "map_manifest.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"Theatre manifest missing: {path}. Run generate-europe-mediterranean-from-goe first."
        )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if str(manifest.get("map_id")) != MAP_ID:
        raise ValueError(f"Expected map_id {MAP_ID}, got {manifest.get('map_id')}")

    state = build_goe_europe_campaign()
    kept_ids = {str(row["province_id"]) for row in manifest.get("province_table", [])}
    anchors = {
        str(row["province_id"]): row.get("marker_anchor") or [0.0, 0.0]
        for row in manifest.get("province_table", [])
    }
    neighbors_map = {
        str(row["province_id"]): [
            str(n)
            for n in (
                row.get("land_neighbors")
                if row.get("land_neighbors") is not None
                else row.get("source_neighbors", [])
            )
        ]
        for row in manifest.get("province_table", [])
    }

    state.provinces = {
        pid: province for pid, province in state.provinces.items() if pid in kept_ids
    }
    for pid, province in state.provinces.items():
        anchor = anchors.get(pid, [province.x, province.y])
        province.x = float(anchor[0])
        province.y = float(anchor[1])
        province.neighbors = neighbors_map.get(pid, [])
        province.map_region = "europe_mediterranean"
        province.metadata["europe_mediterranean_from_goe"] = True

    state.battalions = {
        bid: battalion
        for bid, battalion in state.battalions.items()
        if battalion.province_id in state.provinces
    }
    live_formation_ids = {
        battalion.formation_id
        for battalion in state.battalions.values()
        if battalion.formation_id
    }
    state.formations = {
        fid: formation
        for fid, formation in state.formations.items()
        if fid in live_formation_ids or not live_formation_ids
    }

    state.campaign_name = "Gates of CodeX: Europe-Mediterranean (GoE theatre)"
    state.selected_faction = selected_faction
    state.current_faction = selected_faction
    state.map_id = MAP_ID
    state.map_metadata = {
        **dict(state.map_metadata),
        "strategic_map_id": MAP_ID,
        "strategic_map_manifest": "assets/maps/europe_mediterranean/from_goe/map_manifest.json",
        "strategic_map_provenance": "derived_from_interim_goe_europe_theatre_crop",
        "europe_mediterranean_from_goe": True,
        "canonical": False,
        "note": "Cropped theatre from working GoE color-ID map; pack art not used.",
        "theatre_marker_bounds": dict(MARKER_THEATRE),
        "excludes": EXCLUDES,
    }
    for faction_state in state.factions.values():
        faction_state.is_human_controlled = faction_state.faction == selected_faction
    state.pending_battle = None
    state.schema_version = max(state.schema_version, 5)
    ensure_strategic_layer(state)
    state.validate()
    return state
