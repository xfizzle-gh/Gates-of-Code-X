from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .europe import build_goe_europe_campaign
from .models import CampaignState, Faction
from .strategic import ensure_strategic_layer
from .strategic_map import decode_png_rgb, import_strategic_map, write_png_rgb


MAP_ID = "europe_mediterranean_from_goe"
DEFAULT_OUTPUT_DIR = "godot/assets/maps/europe_mediterranean/from_goe"
INTERIM_DIR = Path("godot/assets/maps/europe/interim_goe")

# Playable marker-space theatre (y increases north).
MARKER_THEATRE = {
    "x_min": -4.2,
    "x_max": 3.2,
    "y_min": -2.2,
    "y_max": 6.2,  # expanded Scandinavia / far north
}

# Coastal Maghreb / Egypt / Levant always playable when present.
FORCE_INCLUDE_PROVINCE_IDS: frozenset[str] = frozenset(
    {
        "province_0101",  # Casablanca
        "province_0111",  # Spanish Africa
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
        "province_0085",  # Sirte (coast)
        "province_0087",  # Matrouh (coast approach)
        "province_0093",  # El Agheila (coast approach)
    }
)

# Deep interior Africa — never playable (may still be visual land).
FORCE_EXCLUDE_PROVINCE_IDS: frozenset[str] = frozenset(
    {
        "province_0066",  # Western Desert
        "province_0081",  # Fezzan
        "province_0103",  # Algerian Desert
        "province_0080",  # Marrakech
        "province_0062",
        "province_0072",
        "province_0083",  # Jordan interior
        "province_0084",
        "province_0077",
        "Aswan",
    }
)

# Display crop expansion from the base playable pixel bbox (source pixels).
DISPLAY_EXPAND = {
    "north": 0.15,
    "south": 0.08,
    "west": 0.04,
    "east": 0.04,
}

MIN_PLAYABLE_PIXELS = 12
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
SEPARATOR_FILL_ITERS = 3

AUTHED_CROSSINGS: tuple[tuple[str, str, str], ...] = (
    ("province_0365", "province_0329", "ferry_or_sea_lane"),
    ("Sussex", "province_0329", "ferry_or_sea_lane"),
    ("province_0127", "province_0139", "strait"),
    ("province_0179", "province_0173", "strait"),
    ("province_0179", "province_0177", "strait"),
    ("Schleswig", "province_0419", "ferry_or_sea_lane"),
    ("Holstein", "province_0419", "ferry_or_sea_lane"),
)

EXCLUDES = [
    "deep Central Asia",
    "deep Sahara as playable geography",
    "far Atlantic / Americas filler",
]


def _load_interim() -> tuple[dict, object]:
    manifest_path = INTERIM_DIR / "map_manifest.json"
    texture_path = INTERIM_DIR / "province_id_map.png"
    if not manifest_path.is_file() or not texture_path.is_file():
        raise FileNotFoundError(f"Interim GoE assets missing under {INTERIM_DIR}")
    return json.loads(manifest_path.read_text(encoding="utf-8")), decode_png_rgb(texture_path)


def select_playable_provinces(province_table: list[dict]) -> tuple[list[dict], dict]:
    by_id = {str(row["province_id"]): row for row in province_table}
    selected: dict[str, dict] = {}
    marker_bound = 0
    for row in province_table:
        pid = str(row["province_id"])
        if pid in FORCE_EXCLUDE_PROVINCE_IDS:
            continue
        ax, ay = row.get("marker_anchor") or [0.0, 0.0]
        x, y = float(ax), float(ay)
        if (
            MARKER_THEATRE["x_min"] <= x <= MARKER_THEATRE["x_max"]
            and MARKER_THEATRE["y_min"] <= y <= MARKER_THEATRE["y_max"]
        ):
            selected[pid] = row
            marker_bound += 1

    forced_in = []
    for pid in sorted(FORCE_INCLUDE_PROVINCE_IDS):
        row = by_id.get(pid)
        if row is None or pid in FORCE_EXCLUDE_PROVINCE_IDS:
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

    # Far-north playable expansion: any non-excluded province whose marker is
    # in the northern band of the expanded theatre.
    scandi_added = []
    for row in province_table:
        pid = str(row["province_id"])
        if pid in selected or pid in FORCE_EXCLUDE_PROVINCE_IDS:
            continue
        ax, ay = row.get("marker_anchor") or [0.0, 0.0]
        x, y = float(ax), float(ay)
        if not (
            MARKER_THEATRE["x_min"] <= x <= MARKER_THEATRE["x_max"]
            and 3.8 <= y <= MARKER_THEATRE["y_max"]
        ):
            continue
        selected[pid] = row
        scandi_added.append(
            {
                "province_id": pid,
                "display_name": str(row.get("display_name", pid)),
                "reason": "scandinavia_north_expansion",
                "marker_y": y,
            }
        )

    forced_out = []
    for pid in sorted(FORCE_EXCLUDE_PROVINCE_IDS):
        row = selected.pop(pid, None)
        if row is not None:
            forced_out.append(
                {
                    "province_id": pid,
                    "display_name": str(row.get("display_name", pid)),
                    "reason": "force_exclude_deep_interior",
                }
            )

    kept = list(selected.values())
    if len(kept) < 80:
        raise RuntimeError(f"Playable theatre too small: {len(kept)}")
    report = {
        "marker_bound_count": marker_bound,
        "force_included": forced_in,
        "force_excluded": forced_out,
        "scandinavia_added": scandi_added,
        "final_playable_count": len(kept),
        "force_include_ids": sorted(FORCE_INCLUDE_PROVINCE_IDS),
        "force_exclude_ids": sorted(FORCE_EXCLUDE_PROVINCE_IDS),
    }
    return kept, report


def _province_pixel_stats(image) -> dict[tuple[int, int, int], dict]:
    stats: dict[tuple[int, int, int], dict] = {}
    for y in range(image.height):
        for x in range(image.width):
            color = image.color_at(x, y)
            if color in (BLACK, WHITE):
                continue
            row = stats.get(color)
            if row is None:
                row = {
                    "count": 0,
                    "sx": 0.0,
                    "sy": 0.0,
                    "min_x": x,
                    "max_x": x,
                    "min_y": y,
                    "max_y": y,
                }
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
    pairs: list[tuple[float, float, float, float]] = []
    for row in province_table:
        color = tuple(int(c) for c in row.get("rgb", []))
        stat = color_stats.get(color)
        if stat is None or stat["count"] < 8:
            continue
        ax, ay = row.get("marker_anchor") or [0.0, 0.0]
        pairs.append((float(ax), float(ay), float(stat["cx"]), float(stat["cy"])))
    if len(pairs) < 8:
        raise RuntimeError("Not enough provinces to fit marker→pixel map")

    def fit_axis(sa: list[float], sb: list[float], dst: list[float]) -> tuple[float, float, float]:
        n = float(len(dst))
        a = sum(sa)
        b = sum(sb)
        d = sum(dst)
        aa = sum(x * x for x in sa)
        bb = sum(x * x for x in sb)
        ab = sum(x * y for x, y in zip(sa, sb))
        ad = sum(x * y for x, y in zip(sa, dst))
        bd = sum(x * y for x, y in zip(sb, dst))
        m = [[aa, ab, a, ad], [ab, bb, b, bd], [a, b, n, d]]
        for col in range(3):
            pivot = max(range(col, 3), key=lambda r: abs(m[r][col]))
            m[col], m[pivot] = m[pivot], m[col]
            div = m[col][col] or 1e-12
            for j in range(col, 4):
                m[col][j] /= div
            for ri in range(3):
                if ri == col:
                    continue
                factor = m[ri][col]
                for j in range(col, 4):
                    m[ri][j] -= factor * m[col][j]
        return m[0][3], m[1][3], m[2][3]

    return (
        fit_axis([p[0] for p in pairs], [p[1] for p in pairs], [p[2] for p in pairs]),
        fit_axis([p[0] for p in pairs], [p[1] for p in pairs], [p[3] for p in pairs]),
    )


def _m2p(mx: float, my: float, xm, ym) -> tuple[float, float]:
    p, q, r = xm
    s, t, u = ym
    return p * mx + q * my + r, s * mx + t * my + u


def generate_europe_mediterranean_from_goe(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    pad_px: int = 8,
) -> dict:
    """Build expanded theatre with separate visual land vs playable color-ID."""

    manifest, image = _load_interim()
    source_table = list(manifest.get("province_table", []))
    color_stats = _province_pixel_stats(image)
    xm, ym = _fit_marker_to_pixel(source_table, color_stats)
    color_to_row = {tuple(int(c) for c in row["rgb"]): row for row in source_table}
    all_land_colors = set(color_stats)

    playable_rows, selection_report = select_playable_provinces(source_table)
    playable_ids = {str(r["province_id"]) for r in playable_rows}
    playable_colors = {tuple(int(c) for c in r["rgb"]) for r in playable_rows}

    # Base pixel bbox from all land that should be visible: playable + excluded African
    # interiors (cosmetic) + any land inside expanded marker theatre.
    visual_colors = set(playable_colors)
    cosmetic_ids: list[dict] = []
    for color, stat in color_stats.items():
        row = color_to_row.get(color)
        if row is None:
            continue
        pid = str(row["province_id"])
        ax, ay = row.get("marker_anchor") or [0.0, 0.0]
        x, y = float(ax), float(ay)
        in_wide = (
            MARKER_THEATRE["x_min"] - 0.4 <= x <= MARKER_THEATRE["x_max"] + 0.4
            and -3.2 <= y <= MARKER_THEATRE["y_max"] + 0.6
        )
        if pid in FORCE_EXCLUDE_PROVINCE_IDS or (
            in_wide and pid not in playable_ids and y < 1.0
        ):
            # Deep/excluded African or southern land: visual only.
            visual_colors.add(color)
            if pid not in playable_ids:
                cosmetic_ids.append(
                    {
                        "province_id": pid,
                        "display_name": str(row.get("display_name", pid)),
                        "role": "visual_land_only",
                        "pixels": int(stat["count"]),
                    }
                )
        elif in_wide and color in all_land_colors:
            visual_colors.add(color)

    # Pixel bbox of visual land, then expand for display crop.
    min_x = image.width
    min_y = image.height
    max_x = -1
    max_y = -1
    for color in visual_colors:
        stat = color_stats.get(color)
        if not stat:
            continue
        min_x = min(min_x, stat["min_x"])
        max_x = max(max_x, stat["max_x"])
        min_y = min(min_y, stat["min_y"])
        max_y = max(max_y, stat["max_y"])
    if max_x < 0:
        raise RuntimeError("No visual land found")

    base_w = max_x - min_x + 1
    base_h = max_y - min_y + 1
    # Source pixel Y increases south; "north expand" decreases min_y.
    exp_n = int(round(base_h * DISPLAY_EXPAND["north"]))
    exp_s = int(round(base_h * DISPLAY_EXPAND["south"]))
    exp_w = int(round(base_w * DISPLAY_EXPAND["west"]))
    exp_e = int(round(base_w * DISPLAY_EXPAND["east"]))
    min_x = max(0, min_x - exp_w - pad_px)
    max_x = min(image.width - 1, max_x + exp_e + pad_px)
    min_y = max(0, min_y - exp_n - pad_px)
    max_y = min(image.height - 1, max_y + exp_s + pad_px)
    crop_w = max_x - min_x + 1
    crop_h = max_y - min_y + 1

    # --- visual land mask (all source land in display crop) ---
    visual_mask = [False] * (crop_w * crop_h)
    for y in range(crop_h):
        for x in range(crop_w):
            color = image.color_at(min_x + x, min_y + y)
            if color != WHITE and color != BLACK and color in all_land_colors:
                visual_mask[y * crop_w + x] = True

    # --- playable ID grid ---
    playable_grid: list[tuple[int, int, int]] = [BLACK] * (crop_w * crop_h)
    pixel_counts: dict[str, int] = defaultdict(int)
    full_counts = {
        str(color_to_row[c]["province_id"]): int(color_stats[c]["count"])
        for c in playable_colors
        if c in color_stats
    }
    playable_by_color = {tuple(int(c) for c in r["rgb"]): r for r in playable_rows}
    for y in range(crop_h):
        for x in range(crop_w):
            color = image.color_at(min_x + x, min_y + y)
            if color in playable_colors:
                playable_grid[y * crop_w + x] = color
                pixel_counts[str(playable_by_color[color]["province_id"])] += 1

    # Dilate playable provinces into black separators only (not into white exterior).
    separators_filled = 0
    for _ in range(SEPARATOR_FILL_ITERS):
        claims: list[tuple[int, int, tuple[int, int, int]]] = []
        for y in range(crop_h):
            for x in range(crop_w):
                idx = y * crop_w + x
                if playable_grid[idx] != BLACK:
                    continue
                # Only dilate over original black separator, not open water outside land mask
                # unless it's between playable provinces (visual land can guide).
                src = image.color_at(min_x + x, min_y + y)
                if src == WHITE:
                    continue
                cands: list[tuple[str, tuple[int, int, int]]] = []
                seen: set[str] = set()
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if nx < 0 or ny < 0 or nx >= crop_w or ny >= crop_h:
                        continue
                    cand = playable_grid[ny * crop_w + nx]
                    if cand == BLACK or cand not in playable_colors:
                        continue
                    pid = str(playable_by_color[cand]["province_id"])
                    if pid in seen:
                        continue
                    seen.add(pid)
                    cands.append((pid, cand))
                if not cands:
                    continue
                cands.sort(key=lambda item: item[0])
                claims.append((x, y, cands[0][1]))
        if not claims:
            break
        for x, y, color in claims:
            idx = y * crop_w + x
            if playable_grid[idx] != BLACK:
                continue
            playable_grid[idx] = color
            pixel_counts[str(playable_by_color[color]["province_id"])] += 1
            separators_filled += 1

    # Drop tiny playable remnants.
    active_rows: list[dict] = []
    dropped_tiny: list[dict] = []
    scandi_report = []
    for row in playable_rows:
        pid = str(row["province_id"])
        kept = pixel_counts.get(pid, 0)
        full = max(full_counts.get(pid, 0), 1)
        if kept < MIN_PLAYABLE_PIXELS:
            dropped_tiny.append(
                {
                    "province_id": pid,
                    "display_name": str(row.get("display_name", pid)),
                    "pixels_kept": kept,
                }
            )
            continue
        entry = dict(row)
        active_rows.append(entry)
        if any(s["province_id"] == pid for s in selection_report.get("scandinavia_added", [])):
            scandi_report.append(
                {
                    "province_id": pid,
                    "display_name": str(row.get("display_name", pid)),
                    "pixel_area": kept,
                }
            )

    active_ids = {str(r["province_id"]) for r in active_rows}
    active_colors = {tuple(int(c) for c in r["rgb"]) for r in active_rows}
    # Erase dropped playable colors.
    drop_colors = {
        tuple(int(c) for c in r["rgb"])
        for r in playable_rows
        if str(r["province_id"]) not in active_ids
    }
    for idx, color in enumerate(playable_grid):
        if color in drop_colors:
            playable_grid[idx] = BLACK

    # Pack playable ID texture + rebuild stats.
    id_bytes = bytearray(crop_w * crop_h * 3)
    owners = [-1] * (crop_w * crop_h)
    pid_index = {pid: i for i, pid in enumerate(sorted(active_ids))}
    index_pid = {i: pid for pid, i in pid_index.items()}
    color_to_pid = {tuple(int(c) for c in r["rgb"]): str(r["province_id"]) for r in active_rows}
    sums: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    pixels_by_pid: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for y in range(crop_h):
        for x in range(crop_w):
            idx = y * crop_w + x
            color = playable_grid[idx]
            base = idx * 3
            id_bytes[base : base + 3] = bytes(color)
            pid = color_to_pid.get(color)
            if pid is None:
                continue
            owners[idx] = pid_index[pid]
            sums[pid][0] += x
            sums[pid][1] += y
            sums[pid][2] += 1
            pixels_by_pid[pid].append((x, y))

    # Direct-contact land adjacency.
    land_edges: set[tuple[str, str]] = set()
    for y in range(crop_h):
        for x in range(crop_w):
            a = owners[y * crop_w + x]
            if a < 0:
                continue
            for nx, ny in ((x + 1, y), (x, y + 1)):
                if nx >= crop_w or ny >= crop_h:
                    continue
                b = owners[ny * crop_w + nx]
                if b >= 0 and b != a:
                    land_edges.add(tuple(sorted((index_pid[a], index_pid[b]))))
    land_neighbors: dict[str, list[str]] = defaultdict(list)
    for a, b in sorted(land_edges):
        land_neighbors[a].append(b)
        land_neighbors[b].append(a)

    authored_edges: list[dict] = []
    authored_neighbors: dict[str, list[str]] = defaultdict(list)
    for left, right, etype in AUTHED_CROSSINGS:
        if left not in active_ids or right not in active_ids:
            continue
        key = tuple(sorted((left, right)))
        if key in land_edges:
            continue
        authored_edges.append({"a": key[0], "b": key[1], "type": etype})
        authored_neighbors[left].append(right)
        authored_neighbors[right].append(left)

    def snap(pid: str, cx: float, cy: float) -> tuple[float, float, bool]:
        ix, iy = int(round(cx)), int(round(cy))
        if 0 <= ix < crop_w and 0 <= iy < crop_h and owners[iy * crop_w + ix] == pid_index[pid]:
            return float(ix), float(iy), False
        best = min(
            pixels_by_pid[pid],
            key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2,
        )
        return float(best[0]), float(best[1]), True

    table = []
    snapped = 0
    for row in sorted(active_rows, key=lambda r: str(r["province_id"])):
        pid = str(row["province_id"])
        n = max(int(sums[pid][2]), 1)
        cx, cy = sums[pid][0] / n, sums[pid][1] / n
        ax, ay, did = snap(pid, cx, cy)
        if did:
            snapped += 1
        land = sorted(set(land_neighbors.get(pid, [])))
        auth = sorted(set(authored_neighbors.get(pid, [])))
        table.append(
            {
                "province_id": pid,
                "display_name": row.get("display_name", pid),
                "name_is_human_readable": bool(row.get("name_is_human_readable", True)),
                "rgb": list(row["rgb"]),
                "marker_anchor": [float(ax), float(crop_h - 1 - ay)],
                "source_neighbors": sorted(set(land) | set(auth)),
                "land_neighbors": land,
                "edge_types": {
                    **{n: "land" for n in land},
                    **{n: "ferry_or_sea_lane" for n in auth},
                },
                "source_province_id": row.get("source_province_id", pid),
                "mapping_method": "goe_theatre_playable",
                "provenance": {
                    "generator": "europe_mediterranean_from_goe_v5_visual_split",
                    "pixels": int(sums[pid][2]),
                    "anchor_snapped": did,
                },
            }
        )

    for row in table:
        ax = int(round(row["marker_anchor"][0]))
        ay = crop_h - 1 - int(round(row["marker_anchor"][1]))
        color = (
            id_bytes[(ay * crop_w + ax) * 3],
            id_bytes[(ay * crop_w + ax) * 3 + 1],
            id_bytes[(ay * crop_w + ax) * 3 + 2],
        )
        if color_to_pid.get(color) != row["province_id"]:
            raise RuntimeError(f"Anchor outside province {row['province_id']}")

    # Background from visual land mask (not playable ID alone).
    # water: cool near-white; playable land: light parchment; cosmetic land: muted darker
    bg = bytearray(crop_w * crop_h * 3)
    for y in range(crop_h):
        for x in range(crop_w):
            idx = y * crop_w + x
            base = idx * 3
            playable = owners[idx] >= 0
            visual = visual_mask[idx]
            if playable:
                bg[base : base + 3] = bytes((230, 224, 210))
            elif visual:
                bg[base : base + 3] = bytes((198, 196, 188))  # muted nonplayable land
            else:
                bg[base : base + 3] = bytes((236, 240, 244))

    # visual_land_mask.png: white=land any, black=water
    mask_bytes = bytearray(crop_w * crop_h * 3)
    for idx, is_land in enumerate(visual_mask):
        tone = 255 if is_land else 0
        base = idx * 3
        mask_bytes[base : base + 3] = bytes((tone, tone, tone))

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    id_png = out / "province_id_map.png"
    write_png_rgb(id_png, crop_w, crop_h, bytes(id_bytes))
    write_png_rgb(out / "visual_land_mask.png", crop_w, crop_h, bytes(mask_bytes))
    write_png_rgb(out / "background_procedural.png", crop_w, crop_h, bytes(bg))

    # Attach neighbor lists for scandi report
    by_table = {r["province_id"]: r for r in table}
    for item in scandi_report:
        item["neighbors"] = list(by_table.get(item["province_id"], {}).get("source_neighbors", []))
        item["pixel_area"] = int(by_table.get(item["province_id"], {}).get("provenance", {}).get("pixels", 0))

    selection_report["final_playable_count"] = len(table)
    selection_report["scandinavia_playable"] = scandi_report
    selection_report["cosmetic_visual_land_provinces"] = cosmetic_ids[:80]
    selection_report["cosmetic_visual_land_count"] = len(cosmetic_ids)
    selection_report["land_adjacency_edges"] = len(land_edges)
    selection_report["authored_edges"] = authored_edges
    selection_report["authored_non_land_edges"] = len(authored_edges)
    selection_report["anchors_snapped"] = snapped
    selection_report["black_separators_filled"] = separators_filled
    selection_report["land_adjacency_mode"] = "direct_4_neighbor_playable_only"
    selection_report["dropped_tiny"] = dropped_tiny
    selection_report["display_expand"] = dict(DISPLAY_EXPAND)
    selection_report["display_crop_px"] = {
        "x0": min_x,
        "y0": min_y,
        "x1": max_x,
        "y1": max_y,
        "width": crop_w,
        "height": crop_h,
    }

    result = import_strategic_map(
        id_png,
        table,
        out / "map_manifest.json",
        map_id=MAP_ID,
        provenance="derived_from_interim_goe_europe_theatre_crop",
        ignored_colors=(BLACK, WHITE),
        texture_output=id_png,
    )
    result["asset_status"] = "derived_project_theatre"
    result["theatre"] = {
        "name": "Europe-Mediterranean from GoE",
        "marker_bounds": dict(MARKER_THEATRE),
        "source_province_count": len(source_table),
        "theatre_province_count": len(table),
        "playable_province_count": len(table),
        "selection": selection_report,
        "excludes": EXCLUDES,
        "layers": {
            "visual_land_mask": "visual_land_mask.png",
            "playable_id_map": "province_id_map.png",
            "background_procedural": "background_procedural.png",
        },
    }
    result["visual_background"] = {
        "path": "background_procedural.png",
        "width": crop_w,
        "height": crop_h,
        "asset_status": "project_procedural",
        "layer_role": "presentation_underlay_from_visual_land_mask",
        "visual_land_mask": "visual_land_mask.png",
    }
    result["visual_background_policy"] = {
        "repo_stores_pack_artwork": False,
        "gameplay_authority": "color_id_province_map",
        "status_label": "project_procedural",
        "nonplayable_land": "visible_muted_unselectable",
    }
    result["provenance_table"] = {
        "visible_geography": "all_source_land_in_expanded_display_crop",
        "playable_geography": "selected_goe_provinces_only",
        "adjacency": "direct_4_neighbor_playable_plus_authored_crossings",
        "north_africa": "continuous_visual_land_coastal_playable_belt",
        "scandinavia": "expanded_playable_north",
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
                f"- playable provinces: {len(table)}",
                f"- display: {crop_w}×{crop_h}",
                "- `province_id_map.png` — playable only (selection/ownership)",
                "- `visual_land_mask.png` — full visible land silhouette",
                "- `background_procedural.png` — from visual mask (muted nonplayable land)",
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
        str(row["province_id"]): [str(n) for n in row.get("source_neighbors", [])]
        for row in manifest.get("province_table", [])
    }

    state.provinces = {pid: p for pid, p in state.provinces.items() if pid in kept_ids}
    for pid, province in state.provinces.items():
        anchor = anchors.get(pid, [province.x, province.y])
        province.x = float(anchor[0])
        province.y = float(anchor[1])
        province.neighbors = neighbors_map.get(pid, [])
        province.map_region = "europe_mediterranean"
        province.metadata["europe_mediterranean_from_goe"] = True
        province.metadata["playable"] = True

    state.battalions = {
        bid: b for bid, b in state.battalions.items() if b.province_id in state.provinces
    }
    live_fids = {b.formation_id for b in state.battalions.values() if b.formation_id}
    state.formations = {
        fid: f for fid, f in state.formations.items() if fid in live_fids or not live_fids
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
        "note": "Playable provinces subset; visual land may include unselectable Africa.",
        "theatre_marker_bounds": dict(MARKER_THEATRE),
        "excludes": EXCLUDES,
    }
    for fs in state.factions.values():
        fs.is_human_controlled = fs.faction == selected_faction
    state.pending_battle = None
    state.schema_version = max(state.schema_version, 5)
    ensure_strategic_layer(state)
    state.validate()
    return state
