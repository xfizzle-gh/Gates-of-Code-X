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

# GoE marker-space theatre (not lon/lat). Keeps Europe + Med + limited N Africa / Near East.
# Excludes deep Atlantic west, deep Russia east, deep Africa south, arctic filler extremes.
MARKER_THEATRE = {
    "x_min": -4.2,
    "x_max": 3.2,
    "y_min": -2.2,
    "y_max": 5.0,
}

EXCLUDES = [
    "deep Central Asia / far Russia east of theatre",
    "deep sub-Saharan Africa",
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


def select_theatre_provinces(province_table: list[dict]) -> list[dict]:
    kept = []
    for row in province_table:
        anchor = row.get("marker_anchor") or [0.0, 0.0]
        x, y = float(anchor[0]), float(anchor[1])
        if (
            MARKER_THEATRE["x_min"] <= x <= MARKER_THEATRE["x_max"]
            and MARKER_THEATRE["y_min"] <= y <= MARKER_THEATRE["y_max"]
        ):
            kept.append(row)
    if len(kept) < 80:
        raise RuntimeError(f"Theatre selection too small: {len(kept)} provinces")
    return kept


def _province_pixel_bbox(
    image,
    kept_colors: set[tuple[int, int, int]],
) -> tuple[int, int, int, int]:
    min_x, min_y = image.width, image.height
    max_x, max_y = -1, -1
    for y in range(image.height):
        for x in range(image.width):
            if image.color_at(x, y) not in kept_colors:
                continue
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
    if max_x < 0:
        raise RuntimeError("No theatre province pixels found in ID map")
    return min_x, min_y, max_x, max_y


def generate_europe_mediterranean_from_goe(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    pad_px: int = 12,
) -> dict:
    """Crop the working interim GoE color-ID map to a Europe–Mediterranean theatre."""

    manifest, image = _load_interim()
    source_table = list(manifest.get("province_table", []))
    kept_rows = select_theatre_provinces(source_table)
    kept_ids = {str(row["province_id"]) for row in kept_rows}
    kept_colors = {tuple(int(c) for c in row["rgb"]) for row in kept_rows}

    min_x, min_y, max_x, max_y = _province_pixel_bbox(image, kept_colors)
    min_x = max(0, min_x - pad_px)
    min_y = max(0, min_y - pad_px)
    max_x = min(image.width - 1, max_x + pad_px)
    max_y = min(image.height - 1, max_y + pad_px)
    crop_w = max_x - min_x + 1
    crop_h = max_y - min_y + 1

    # Crop ID texture; drop pixels whose colors are outside the theatre set.
    sea = (0, 0, 0)
    cropped = bytearray(crop_w * crop_h * 3)
    present_colors: set[tuple[int, int, int]] = set()
    for y in range(crop_h):
        for x in range(crop_w):
            color = image.color_at(min_x + x, min_y + y)
            if color not in kept_colors:
                color = sea
            else:
                present_colors.add(color)
            i = (y * crop_w + x) * 3
            cropped[i : i + 3] = bytes(color)

    # Keep only provinces that still have pixels after crop.
    color_to_row = {tuple(int(c) for c in row["rgb"]): row for row in kept_rows}
    active_rows = []
    for color in sorted(present_colors):
        row = dict(color_to_row[color])
        active_rows.append(row)
    active_ids = {str(row["province_id"]) for row in active_rows}

    # Remap anchors into cropped pixel space (bottom-left Y for Godot marker helper).
    # Prefer pixel centroid inside crop for stable click anchors.
    sums: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for y in range(crop_h):
        for x in range(crop_w):
            i = (y * crop_w + x) * 3
            color = (cropped[i], cropped[i + 1], cropped[i + 2])
            if color == sea:
                continue
            pid = str(color_to_row[color]["province_id"])
            sums[pid][0] += x
            sums[pid][1] += y
            sums[pid][2] += 1

    table = []
    for row in sorted(active_rows, key=lambda item: str(item["province_id"])):
        pid = str(row["province_id"])
        count = max(int(sums[pid][2]), 1)
        cx = sums[pid][0] / count
        cy = sums[pid][1] / count
        neighbors = [
            str(n)
            for n in row.get("source_neighbors", [])
            if str(n) in active_ids
        ]
        table.append(
            {
                "province_id": pid,
                "display_name": row.get("display_name", pid),
                "name_is_human_readable": bool(row.get("name_is_human_readable", True)),
                "rgb": list(row["rgb"]),
                "marker_anchor": [float(cx), float(crop_h - 1 - cy)],
                "source_neighbors": sorted(set(neighbors)),
                "source_province_id": row.get("source_province_id", pid),
                "mapping_method": "goe_theatre_crop",
                "provenance": {
                    "generator": "europe_mediterranean_from_goe_v1",
                    "source_map_id": manifest.get("map_id", "goe_europe"),
                    "marker_theatre": dict(MARKER_THEATRE),
                    "crop_px": [min_x, min_y, max_x, max_y],
                },
            }
        )

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
        "excludes": EXCLUDES,
    }
    result["visual_background_policy"] = {
        "repo_stores_pack_artwork": False,
        "default_background": "background_procedural.png",
        "role": "presentation_underlay_only",
        "gameplay_authority": "color_id_province_map",
    }
    result["visual_background"] = {
        "path": "background_procedural.png",
        "width": crop_w,
        "height": crop_h,
        "asset_status": "project_owned_procedural",
        "layer_role": "presentation_underlay_only",
    }
    result["provenance_table"] = {
        "province_geometry": "interim_goe_color_id_crop",
        "province_ids": "preserved_from_goe_graph_where_in_theatre",
        "adjacency": "filtered_source_neighbors_within_theatre",
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
        str(row["province_id"]): [str(n) for n in row.get("source_neighbors", [])]
        for row in manifest.get("province_table", [])
    }

    state.provinces = {
        pid: province for pid, province in state.provinces.items() if pid in kept_ids
    }
    for pid, province in state.provinces.items():
        anchor = anchors.get(pid, [province.x, province.y])
        province.x = float(anchor[0])
        province.y = float(anchor[1])
        province.neighbors = neighbors_map.get(
            pid, [n for n in province.neighbors if n in kept_ids]
        )
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
