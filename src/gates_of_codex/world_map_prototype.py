from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .strategic_map import import_strategic_map, write_png_rgb


# Public geographic coordinates (decimal degrees). Not invented province geometry.
# Keys match settlement tokens from the research pack loc tables.
SETTLEMENT_GEO: dict[str, tuple[float, float]] = {
    "ajaccio": (41.9267, 8.7369),
    "algarve": (37.0194, -7.9322),
    "amsterdam": (52.3676, 4.9041),
    "arhus": (56.1629, 10.2039),
    "badajoz": (38.8794, -6.9706),
    "balearic": (39.5696, 2.6502),
    "barcelona": (41.3874, 2.1686),
    "bari": (41.1171, 16.8719),
    "belfast": (54.5973, -5.9301),
    "bergen": (60.3913, 5.3221),
    "berlin": (52.5200, 13.4050),
    "bern": (46.9480, 7.4474),
    "bilbao": (43.2630, -2.9350),
    "bodo": (67.2804, 14.4049),
    "bologna": (44.4949, 11.3426),
    "bordeaux": (44.8378, -0.5792),
    "bremen": (53.0793, 8.8017),
    "brest": (48.3905, -4.4860),
    "brussels": (50.8503, 4.3517),
    "cagliari": (39.2238, 9.1217),
    "cardiff": (51.4816, -3.1791),
    "catania": (37.5079, 15.0830),
    "cologne": (50.9375, 6.9603),
    "copenhagen": (55.6761, 12.5683),
    "cork": (51.8985, -8.4756),
    "coruna": (43.3623, -8.4115),
    "cosenza": (39.2983, 16.2537),
    "dresden": (51.0504, 13.7373),
    "dublin": (53.3498, -6.2603),
    "edinburgh": (55.9533, -3.1883),
    "florence": (43.7696, 11.2558),
    "frankfurt": (50.1109, 8.6821),
    "genoa": (44.4056, 8.9463),
    "gibraltar": (36.1408, -5.3536),
    "gothenburg": (57.7089, 11.9746),
    "granada": (37.1773, -3.5986),
    "graz": (47.0707, 15.4395),
    "groningen": (53.2194, 6.5665),
    "hamburg": (53.5511, 9.9937),
    "hannover": (52.3759, 9.7320),
    "helsinki": (60.1699, 24.9384),
    "herning": (56.1389, 8.9700),
    "innsbruck": (47.2692, 11.4041),
    "inverness": (57.4778, -4.2247),
    "joensuu": (62.6010, 29.7636),
    "kalmar": (56.6634, 16.3566),
    "karlstad": (59.3793, 13.5036),
    "kristiansand": (58.1467, 7.9956),
    "kuopio": (62.8924, 27.6770),
    "lille": (50.6292, 3.0573),
    "limoges": (45.8336, 1.2611),
    "lisbon": (38.7223, -9.1393),
    "liverpool": (53.4084, -2.9916),
    "london": (51.5074, -0.1278),
    "lulea": (65.5848, 22.1547),
    "luxemburg": (49.6116, 6.1319),
    "lyon": (45.7640, 4.8357),
    "madrid": (40.4168, -3.7038),
    "malmo": (55.6050, 13.0038),
    "marseille": (43.2965, 5.3698),
    "metz": (49.1193, 6.1757),
    "milan": (45.4642, 9.1900),
    "munich": (48.1351, 11.5820),
    "nantes": (47.2184, -1.5536),
    "naples": (40.8518, 14.2681),
    "nuremberg": (49.4521, 11.0767),
    "oslo": (59.9139, 10.7522),
    "ostersund": (63.1767, 14.6361),
    "oulu": (65.0121, 25.4651),
    "palermo": (38.1157, 13.3615),
    "paris": (48.8566, 2.3522),
    "plymouth": (50.3755, -4.1427),
    "porto": (41.1579, -8.6291),
    "rome": (41.9028, 12.4964),
    "salzburg": (47.8095, 13.0550),
    "stockholm": (59.3293, 18.0686),
    "stuttgart": (48.7758, 9.1829),
    "toulouse": (43.6047, 1.4442),
    "trieste": (45.6495, 13.7768),
    "trondheim": (63.4305, 10.3951),
    "turin": (45.0703, 7.6869),
    "turku": (60.4518, 22.2666),
    "umea": (63.8258, 20.2630),
    "uppsala": (59.8586, 17.6389),
    "vaasa": (63.0951, 21.6165),
    "valencia": (39.4699, -0.3763),
    "venice": (45.4408, 12.3155),
    "vienna": (48.2082, 16.3738),
    "zurich": (47.3769, 8.5417),
    # Theatre extensions (public geo; not from pack names when missing)
    "algiers": (36.7538, 3.0588),
    "tunis": (36.8065, 10.1815),
    "cairo": (30.0444, 31.2357),
    "istanbul": (41.0082, 28.9784),
    "moscow": (55.7558, 37.6173),
    "kyiv": (50.4501, 30.5234),
    "warsaw": (52.2297, 21.0122),
    "athens": (37.9838, 23.7275),
    "bucharest": (44.4268, 26.1025),
    "budapest": (47.4979, 19.0402),
    "prague": (50.0755, 14.4378),
    "riga": (56.9496, 24.1052),
    "vilnius": (54.6872, 25.2797),
    "minsk": (53.9006, 27.5590),
    "ankara": (39.9334, 32.8597),
    "beirut": (33.8938, 35.5018),
    "jerusalem": (31.7683, 35.2137),
    "baghdad": (33.3152, 44.3661),
    "tehran": (35.6892, 51.3890),
    "casablanca": (33.5731, -7.5898),
    "tripoli": (32.8872, 13.1913),
}


def default_extract_root() -> Path:
    return Path(r"C:\Users\paulf\AppData\Local\Temp\opencode\world_test_9_extract\files")


def load_settlement_labels(extract_root: str | Path | None = None) -> list[dict]:
    root = Path(extract_root) if extract_root else default_extract_root()
    loc = root / "text__db__campaign_map_settlements.txt"
    if not loc.is_file():
        raise FileNotFoundError(f"Settlement loc table not found: {loc}")
    text = loc.read_text(encoding="utf-16")
    rows: list[dict] = []
    for match in re.finditer(
        r"\{campaign_map_settlements_default_onscreen_name_settlement:([^:]+):([^}]+)\}\t([^\r\n]+)",
        text,
    ):
        region_key = match.group(1).strip()
        settlement_key = match.group(2).strip().lower()
        display = match.group(3).strip()
        if not region_key.startswith("bos_"):
            continue
        if settlement_key not in SETTLEMENT_GEO:
            continue
        lat, lon = SETTLEMENT_GEO[settlement_key]
        rows.append(
            {
                "source_region_key": region_key,
                "source_settlement_key": settlement_key,
                "display_name": display,
                "lat": lat,
                "lon": lon,
                "confidence": "settlement_loc+public_geo",
            }
        )
    # Theatre extensions without pack names use stable placeholder IDs.
    present = {row["source_settlement_key"] for row in rows}
    for key, (lat, lon) in SETTLEMENT_GEO.items():
        if key in present:
            continue
        if key in {
            "algiers",
            "tunis",
            "cairo",
            "istanbul",
            "moscow",
            "kyiv",
            "warsaw",
            "athens",
            "bucharest",
            "budapest",
            "prague",
            "riga",
            "vilnius",
            "minsk",
            "ankara",
            "beirut",
            "jerusalem",
            "baghdad",
            "tehran",
            "casablanca",
            "tripoli",
        }:
            rows.append(
                {
                    "source_region_key": "",
                    "source_settlement_key": key,
                    "display_name": key.replace("_", " ").title(),
                    "lat": lat,
                    "lon": lon,
                    "confidence": "public_geo_theatre_extension",
                }
            )
    rows.sort(key=lambda row: row["source_settlement_key"])
    return rows


def decode_tga_rgb(path: str | Path) -> tuple[int, int, bytes]:
    data = Path(path).read_bytes()
    id_len, cmap_type, image_type = data[0], data[1], data[2]
    width, height = struct.unpack_from("<HH", data, 12)
    bpp = data[16]
    if image_type != 2 or bpp != 24 or cmap_type != 0:
        raise ValueError(f"Unsupported TGA layout in {path}")
    offset = 18 + id_len
    raw = data[offset : offset + width * height * 3]
    if len(raw) < width * height * 3:
        raise ValueError(f"TGA payload truncated in {path}")
    # TGA is BGR bottom-up usually; descriptor bit 5 may flip.
    descriptor = data[17]
    top_down = bool(descriptor & 0x20)
    rows = []
    row_bytes = width * 3
    for y in range(height):
        src_y = y if top_down else (height - 1 - y)
        row = bytearray(raw[src_y * row_bytes : (src_y + 1) * row_bytes])
        # BGR -> RGB
        for i in range(0, len(row), 3):
            row[i], row[i + 2] = row[i + 2], row[i]
        rows.append(bytes(row))
    return width, height, b"".join(rows)


def lonlat_to_pixel(lon: float, lat: float, width: int, height: int) -> tuple[int, int]:
    x = int(round((lon + 180.0) / 360.0 * (width - 1)))
    y = int(round((90.0 - lat) / 180.0 * (height - 1)))
    return max(0, min(width - 1, x)), max(0, min(height - 1, y))


def rgb_for_index(index: int) -> tuple[int, int, int]:
    # Unique RGB using R + G*256 packing (same style as GoE id colors).
    value = index + 1
    return value % 256, value // 256, 0


def build_land_mask(rgb: bytes, width: int, height: int) -> list[bool]:
    mask: list[bool] = []
    for i in range(0, len(rgb), 3):
        r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
        # Sea tends to be blue/dark; treat strong blue or near-black as non-land.
        if b > r + 12 and b > g + 8:
            mask.append(False)
        elif r + g + b < 40:
            mask.append(False)
        else:
            mask.append(True)
    if len(mask) != width * height:
        raise ValueError("land mask size mismatch")
    return mask


def upscale_mask(mask: list[bool], src_w: int, src_h: int, dst_w: int, dst_h: int) -> list[bool]:
    out: list[bool] = []
    for y in range(dst_h):
        sy = min(src_h - 1, int(y * src_h / dst_h))
        for x in range(dst_w):
            sx = min(src_w - 1, int(x * src_w / dst_w))
            out.append(mask[sy * src_w + sx])
    return out


def generate_world_prototype(
    *,
    extract_root: str | Path | None = None,
    output_dir: str | Path = "godot/assets/maps/world/prototype",
    width: int = 2048,
    height: int = 1024,
) -> dict:
    """Generate a clean-room world color-ID map from settlement seeds + land mask.

    Does not ship Total War binaries. Uses:
    - research pack settlement labels (names only)
    - public lat/lon for those settlements
    - world TGA only as a temporary land/sea silhouette source (not committed)
    """

    root = Path(extract_root) if extract_root else default_extract_root()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    settlements = load_settlement_labels(root)
    if len(settlements) < 20:
        raise RuntimeError(f"Too few settlements with coordinates: {len(settlements)}")

    tga = root / "campaign_maps__bos_japan__boshin_map_world.tga"
    src_w, src_h, src_rgb = decode_tga_rgb(tga)
    land = upscale_mask(build_land_mask(src_rgb, src_w, src_h), src_w, src_h, width, height)

    seeds: list[dict] = []
    for index, row in enumerate(settlements):
        px, py = lonlat_to_pixel(row["lon"], row["lat"], width, height)
        # Snap seed onto nearest land pixel if it landed in water.
        if not land[py * width + px]:
            px, py = _nearest_land(px, py, land, width, height)
        rgb = rgb_for_index(index)
        province_id = f"wp_{row['source_settlement_key']}"
        seeds.append(
            {
                "province_id": province_id,
                "display_name": row["display_name"],
                "rgb": list(rgb),
                "marker_anchor": [float(px), float(height - 1 - py)],
                "source_settlement_key": row["source_settlement_key"],
                "source_region_key": row["source_region_key"],
                "lat": row["lat"],
                "lon": row["lon"],
                "confidence": row["confidence"],
                "pixel": (px, py),
                "name_is_human_readable": True,
            }
        )

    # Assign each land pixel to nearest seed (equirectangular Voronoi).
    pixels = bytearray(width * height * 3)
    owners = [-1] * (width * height)
    seed_xy = [(int(s["pixel"][0]), int(s["pixel"][1])) for s in seeds]
    for y in range(height):
        for x in range(width):
            idx = y * width + x
            base = idx * 3
            if not land[idx]:
                pixels[base : base + 3] = bytes((0, 0, 0))
                continue
            best_i = 0
            best_d = 10**18
            for i, (sx, sy) in enumerate(seed_xy):
                dx = x - sx
                dy = y - sy
                d = dx * dx + dy * dy
                if d < best_d:
                    best_d = d
                    best_i = i
            owners[idx] = best_i
            r, g, b = seeds[best_i]["rgb"]
            pixels[base] = r
            pixels[base + 1] = g
            pixels[base + 2] = b

    # Adjacency from 4-neighbor land contacts.
    edges: set[tuple[int, int]] = set()
    for y in range(height):
        for x in range(width):
            i = owners[y * width + x]
            if i < 0:
                continue
            for nx, ny in ((x + 1, y), (x, y + 1)):
                if nx >= width or ny >= height:
                    continue
                j = owners[ny * width + nx]
                if j >= 0 and j != i:
                    edges.add((min(i, j), max(i, j)))

    neighbor_map: dict[str, list[str]] = defaultdict(list)
    for left, right in sorted(edges):
        a = seeds[left]["province_id"]
        b = seeds[right]["province_id"]
        neighbor_map[a].append(b)
        neighbor_map[b].append(a)

    table = []
    for seed in seeds:
        pid = seed["province_id"]
        table.append(
            {
                "province_id": pid,
                "display_name": seed["display_name"],
                "rgb": seed["rgb"],
                "marker_anchor": seed["marker_anchor"],
                "name_is_human_readable": True,
                "source_neighbors": sorted(set(neighbor_map.get(pid, []))),
                "provenance": {
                    "generator": "world_map_prototype_v1",
                    "method": "settlement_seeded_voronoi_equirectangular",
                    "source_settlement_key": seed["source_settlement_key"],
                    "source_region_key": seed["source_region_key"],
                    "confidence": seed["confidence"],
                    "lat": seed["lat"],
                    "lon": seed["lon"],
                },
            }
        )

    id_png = out / "world_id_map.png"
    write_png_rgb(id_png, width, height, bytes(pixels))

    # Optional neutral background silhouette (generated greyscale land), project-owned.
    bg = bytearray(width * height * 3)
    for i, is_land in enumerate(land):
        tone = 48 if is_land else 12
        base = i * 3
        bg[base : base + 3] = bytes((tone, tone, tone + 4))
    write_png_rgb(out / "world_land_silhouette.png", width, height, bytes(bg))

    manifest = import_strategic_map(
        id_png,
        table,
        out / "map_manifest.json",
        map_id="world_prototype",
        provenance="project_owned_world_prototype_v1",
        ignored_colors=((0, 0, 0),),
        texture_output=id_png,
    )
    manifest["theatre"] = {
        "description": "Full equirectangular world projection; denser seeds in Europe/N.Africa/ME/W.Russia",
        "province_count": len(table),
        "width": width,
        "height": height,
        "seed_count": len(seeds),
    }
    manifest["clean_room"] = {
        "committed_outputs": [
            "world_id_map.png",
            "world_land_silhouette.png",
            "map_manifest.json",
        ],
        "research_only_inputs": [
            "world_test_9.pack (not committed)",
            "boshin_map_world.tga land silhouette only (not committed)",
            "settlement loc labels (names only)",
        ],
        "geometry_method": "settlement-seeded Voronoi; regions.esf polygons not decoded",
    }
    (out / "map_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _nearest_land(x: int, y: int, land: list[bool], width: int, height: int) -> tuple[int, int]:
    if land[y * width + x]:
        return x, y
    best = (x, y)
    best_d = 10**18
    for yy in range(height):
        for xx in range(width):
            if not land[yy * width + xx]:
                continue
            d = (xx - x) * (xx - x) + (yy - y) * (yy - y)
            if d < best_d:
                best_d = d
                best = (xx, yy)
    return best
