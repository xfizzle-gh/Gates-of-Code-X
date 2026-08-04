from __future__ import annotations

import json
import re
import struct
from collections import defaultdict, deque
from pathlib import Path

from .strategic_map import import_strategic_map, write_png_rgb


# Public geographic coordinates (decimal degrees): lat, lon
SETTLEMENT_GEO: dict[str, tuple[float, float]] = {
    # British Isles / Channel
    "london": (51.5074, -0.1278),
    "dover": (51.1279, 1.3134),
    "plymouth": (50.3755, -4.1427),
    "cardiff": (51.4816, -3.1791),
    "liverpool": (53.4084, -2.9916),
    "edinburgh": (55.9533, -3.1883),
    "inverness": (57.4778, -4.2247),
    "belfast": (54.5973, -5.9301),
    "dublin": (53.3498, -6.2603),
    "cork": (51.8985, -8.4756),
    "calais": (50.9513, 1.8587),
    # France / Benelux
    "paris": (48.8566, 2.3522),
    "brest": (48.3905, -4.4860),
    "nantes": (47.2184, -1.5536),
    "bordeaux": (44.8378, -0.5792),
    "toulouse": (43.6047, 1.4442),
    "marseille": (43.2965, 5.3698),
    "lyon": (45.7640, 4.8357),
    "limoges": (45.8336, 1.2611),
    "lille": (50.6292, 3.0573),
    "metz": (49.1193, 6.1757),
    "strasbourg": (48.5734, 7.7521),
    "brussels": (50.8503, 4.3517),
    "amsterdam": (52.3676, 4.9041),
    "groningen": (53.2194, 6.5665),
    "luxemburg": (49.6116, 6.1319),
    # Iberia
    "lisbon": (38.7223, -9.1393),
    "porto": (41.1579, -8.6291),
    "algarve": (37.0194, -7.9322),
    "madrid": (40.4168, -3.7038),
    "barcelona": (41.3874, 2.1686),
    "valencia": (39.4699, -0.3763),
    "bilbao": (43.2630, -2.9350),
    "coruna": (43.3623, -8.4115),
    "badajoz": (38.8794, -6.9706),
    "granada": (37.1773, -3.5986),
    "seville": (37.3891, -5.9845),
    "gibraltar": (36.1408, -5.3536),
    "balearic": (39.5696, 2.6502),
    # Italy / Alps / islands
    "rome": (41.9028, 12.4964),
    "milan": (45.4642, 9.1900),
    "turin": (45.0703, 7.6869),
    "genoa": (44.4056, 8.9463),
    "venice": (45.4408, 12.3155),
    "florence": (43.7696, 11.2558),
    "bologna": (44.4949, 11.3426),
    "naples": (40.8518, 14.2681),
    "bari": (41.1171, 16.8719),
    "cosenza": (39.2983, 16.2537),
    "reggio": (38.1113, 15.6473),
    "palermo": (38.1157, 13.3615),
    "catania": (37.5079, 15.0830),
    "cagliari": (39.2238, 9.1217),
    "ajaccio": (41.9267, 8.7369),
    "trieste": (45.6495, 13.7768),
    # Central Europe
    "berlin": (52.5200, 13.4050),
    "hamburg": (53.5511, 9.9937),
    "bremen": (53.0793, 8.8017),
    "hannover": (52.3759, 9.7320),
    "cologne": (50.9375, 6.9603),
    "frankfurt": (50.1109, 8.6821),
    "stuttgart": (48.7758, 9.1829),
    "munich": (48.1351, 11.5820),
    "nuremberg": (49.4521, 11.0767),
    "dresden": (51.0504, 13.7373),
    "prague": (50.0755, 14.4378),
    "vienna": (48.2082, 16.3738),
    "salzburg": (47.8095, 13.0550),
    "innsbruck": (47.2692, 11.4041),
    "graz": (47.0707, 15.4395),
    "bern": (46.9480, 7.4474),
    "zurich": (47.3769, 8.5417),
    "warsaw": (52.2297, 21.0122),
    "krakow": (50.0647, 19.9450),
    "gdansk": (54.3520, 18.6466),
    # Nordics / Baltics
    "copenhagen": (55.6761, 12.5683),
    "arhus": (56.1629, 10.2039),
    "herning": (56.1389, 8.9700),
    "oslo": (59.9139, 10.7522),
    "bergen": (60.3913, 5.3221),
    "trondheim": (63.4305, 10.3951),
    "kristiansand": (58.1467, 7.9956),
    "bodo": (67.2804, 14.4049),
    "stockholm": (59.3293, 18.0686),
    "gothenburg": (57.7089, 11.9746),
    "malmo": (55.6050, 13.0038),
    "kalmar": (56.6634, 16.3566),
    "karlstad": (59.3793, 13.5036),
    "uppsala": (59.8586, 17.6389),
    "umea": (63.8258, 20.2630),
    "lulea": (65.5848, 22.1547),
    "ostersund": (63.1767, 14.6361),
    "helsinki": (60.1699, 24.9384),
    "turku": (60.4518, 22.2666),
    "tampere": (61.4978, 23.7610),
    "oulu": (65.0121, 25.4651),
    "vaasa": (63.0951, 21.6165),
    "kuopio": (62.8924, 27.6770),
    "joensuu": (62.6010, 29.7636),
    "riga": (56.9496, 24.1052),
    "tallinn": (59.4370, 24.7536),
    "vilnius": (54.6872, 25.2797),
    "kaliningrad": (54.7104, 20.4522),
    # Balkans / Greece / Turkey
    "budapest": (47.4979, 19.0402),
    "zagreb": (45.8150, 15.9819),
    "belgrade": (44.7866, 20.4489),
    "sarajevo": (43.8563, 18.4131),
    "tirana": (41.3275, 19.8187),
    "skopje": (41.9981, 21.4254),
    "sofia": (42.6977, 23.3219),
    "bucharest": (44.4268, 26.1025),
    "constanta": (44.1598, 28.6348),
    "athens": (37.9838, 23.7275),
    "thessaloniki": (40.6401, 22.9444),
    "crete": (35.3387, 25.1442),
    "istanbul": (41.0082, 28.9784),
    "ankara": (39.9334, 32.8597),
    "izmir": (38.4237, 27.1428),
    "antalya": (36.8969, 30.7133),
    "trabzon": (41.0027, 39.7168),
    "cyprus": (35.1856, 33.3823),
    # Eastern Europe / Russia (theatre west)
    "kyiv": (50.4501, 30.5234),
    "odessa": (46.4825, 30.7233),
    "kharkiv": (49.9935, 36.2304),
    "lviv": (49.8397, 24.0297),
    "minsk": (53.9006, 27.5590),
    "moscow": (55.7558, 37.6173),
    "st_petersburg": (59.9311, 30.3609),
    "smolensk": (54.7903, 32.0504),
    "rostov": (47.2357, 39.7015),
    "sevastopol": (44.6166, 33.5254),
    "krasnodar": (45.0355, 38.9753),
    # North Africa / Levant (coastal theatre)
    "casablanca": (33.5731, -7.5898),
    "tangier": (35.7595, -5.8340),
    "oran": (35.6971, -0.6337),
    "algiers": (36.7538, 3.0588),
    "tunis": (36.8065, 10.1815),
    "tripoli": (32.8872, 13.1913),
    "benghazi": (32.1167, 20.0667),
    "cairo": (30.0444, 31.2357),
    "alexandria": (31.2001, 29.9187),
    "beirut": (33.8938, 35.5018),
    "reykjavik": (64.1466, -21.9426),
}

# Explicit non-land movement links only. Raster water touches never create land edges.
AUTHED_CROSSINGS: tuple[tuple[str, str, str], ...] = (
    ("dover", "calais", "strait"),
    ("london", "calais", "ferry_or_sea_lane"),
    ("plymouth", "brest", "ferry_or_sea_lane"),
    ("copenhagen", "malmo", "strait"),
    ("stockholm", "helsinki", "ferry_or_sea_lane"),
    ("reggio", "catania", "strait"),
    ("ajaccio", "genoa", "ferry_or_sea_lane"),
    ("ajaccio", "cagliari", "ferry_or_sea_lane"),
    ("cagliari", "tunis", "ferry_or_sea_lane"),
    ("balearic", "barcelona", "ferry_or_sea_lane"),
    ("balearic", "valencia", "ferry_or_sea_lane"),
    ("gibraltar", "tangier", "strait"),
    ("crete", "athens", "ferry_or_sea_lane"),
    ("cyprus", "beirut", "ferry_or_sea_lane"),
    ("cyprus", "antalya", "ferry_or_sea_lane"),
    ("istanbul", "constanta", "ferry_or_sea_lane"),
    ("palermo", "tunis", "ferry_or_sea_lane"),
    ("naples", "palermo", "ferry_or_sea_lane"),
    ("belfast", "liverpool", "ferry_or_sea_lane"),
    ("dublin", "liverpool", "ferry_or_sea_lane"),
    ("edinburgh", "bergen", "ferry_or_sea_lane"),
)

# Europe-Mediterranean theatre only (owner ruling).
THEATRE_BOUNDS = (-25.0, 50.0, 25.0, 72.0)  # lon_min, lon_max, lat_min, lat_max
SEA_RGB = (0, 0, 0)
MAP_ID = "europe_mediterranean_prototype"
DEFAULT_OUTPUT_DIR = "godot/assets/maps/europe_mediterranean/prototype"
PROVINCE_PREFIX = "em_"
PACKAGE_DATA = Path(__file__).resolve().parent / "data"
DEFAULT_LAND_MASK = PACKAGE_DATA / "europe_mediterranean_land_mask.png"
MIN_PROVINCE_PIXELS = 40
MAX_ASPECT_WARN = 12.0


def lonlat_to_pixel(lon: float, lat: float, width: int, height: int) -> tuple[int, int]:
    lon_min, lon_max, lat_min, lat_max = THEATRE_BOUNDS
    x = int(round((lon - lon_min) / (lon_max - lon_min) * (width - 1)))
    y = int(round((lat_max - lat) / (lat_max - lat_min) * (height - 1)))
    return max(0, min(width - 1, x)), max(0, min(height - 1, y))


def pixel_to_lonlat(x: int, y: int, width: int, height: int) -> tuple[float, float]:
    lon_min, lon_max, lat_min, lat_max = THEATRE_BOUNDS
    lon = lon_min + (x / max(width - 1, 1)) * (lon_max - lon_min)
    lat = lat_max - (y / max(height - 1, 1)) * (lat_max - lat_min)
    return lon, lat


def in_theatre(lon: float, lat: float) -> bool:
    lon_min, lon_max, lat_min, lat_max = THEATRE_BOUNDS
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def rgb_for_index(index: int) -> tuple[int, int, int]:
    value = index + 1
    return value % 256, value // 256, 0


def load_settlement_labels(settlements_loc: str | Path | None = None) -> list[dict]:
    labels: dict[str, str] = {}
    if settlements_loc:
        path = Path(settlements_loc)
        if path.is_file():
            text = path.read_text(encoding="utf-16")
            for match in re.finditer(
                r"\{campaign_map_settlements_default_onscreen_name_settlement:([^:]+):([^}]+)\}\t([^\r\n]+)",
                text,
            ):
                region_key = match.group(1).strip()
                settlement_key = match.group(2).strip().lower()
                display = match.group(3).strip()
                if region_key.startswith("bos_"):
                    labels[settlement_key] = display

    rows: list[dict] = []
    for key, (lat, lon) in sorted(SETTLEMENT_GEO.items()):
        if not in_theatre(lon, lat):
            continue
        display = labels.get(key, key.replace("_", " ").title())
        confidence = "settlement_loc+public_geo" if key in labels else "public_geo_theatre_seed"
        rows.append(
            {
                "source_region_key": f"bos_{key}" if key in labels else "",
                "source_settlement_key": key,
                "display_name": display,
                "lat": lat,
                "lon": lon,
                "confidence": confidence,
            }
        )
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
    top_down = bool(data[17] & 0x20)
    rows = []
    row_bytes = width * 3
    for y in range(height):
        src_y = y if top_down else (height - 1 - y)
        row = bytearray(raw[src_y * row_bytes : (src_y + 1) * row_bytes])
        for i in range(0, len(row), 3):
            row[i], row[i + 2] = row[i + 2], row[i]
        rows.append(bytes(row))
    return width, height, b"".join(rows)


def load_land_mask_png(path: str | Path, width: int, height: int) -> list[bool]:
    from .strategic_map import decode_png_rgb

    image = decode_png_rgb(path)
    if image.width != width or image.height != height:
        # Nearest-neighbor resample.
        mask: list[bool] = []
        for y in range(height):
            sy = min(image.height - 1, int(round(y * (image.height - 1) / max(height - 1, 1))))
            for x in range(width):
                sx = min(image.width - 1, int(round(x * (image.width - 1) / max(width - 1, 1))))
                r, g, b = image.color_at(sx, sy)
                mask.append((r + g + b) >= 120)
        return mask
    return [(r + g + b) >= 120 for (r, g, b) in image.pixels]


def rasterize_land_geojson(path: str | Path, width: int, height: int) -> list[bool]:
    """Rasterize Natural Earth (or compatible) land polygons into theatre mask."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    features = payload.get("features", payload)
    mask = [False] * (width * height)
    lon_min, lon_max, lat_min, lat_max = THEATRE_BOUNDS

    def to_px(lon: float, lat: float) -> tuple[float, float]:
        x = (lon - lon_min) / (lon_max - lon_min) * (width - 1)
        y = (lat_max - lat) / (lat_max - lat_min) * (height - 1)
        return x, y

    def fill_ring(ring: list) -> None:
        if len(ring) < 3:
            return
        pts = [to_px(float(p[0]), float(p[1])) for p in ring]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        min_x = max(0, int(min(xs)) - 1)
        max_x = min(width - 1, int(max(xs)) + 1)
        min_y = max(0, int(min(ys)) - 1)
        max_y = min(height - 1, int(max(ys)) + 1)
        if min_x > max_x or min_y > max_y:
            return
        # Odd-even scanline fill.
        edges = []
        n = len(pts)
        for i in range(n - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            if abs(y1 - y0) < 1e-9:
                continue
            if y0 < y1:
                edges.append((y0, y1, x0, (x1 - x0) / (y1 - y0)))
            else:
                edges.append((y1, y0, x1, (x0 - x1) / (y0 - y1)))
        for y in range(min_y, max_y + 1):
            y_s = y + 0.5
            xs_hit: list[float] = []
            for y0, y1, x_at_y0, inv in edges:
                if y0 <= y_s < y1:
                    xs_hit.append(x_at_y0 + (y_s - y0) * inv)
            xs_hit.sort()
            for i in range(0, len(xs_hit) - 1, 2):
                x_start = max(min_x, int(xs_hit[i]) + (0 if xs_hit[i] < 0 else 0))
                x_end = min(max_x, int(xs_hit[i + 1]))
                x0i = max(min_x, int(round(xs_hit[i])))
                x1i = min(max_x, int(round(xs_hit[i + 1])))
                if x1i < x0i:
                    continue
                base = y * width
                for x in range(x0i, x1i + 1):
                    mask[base + x] = True

    def walk_coords(coords, geom_type: str) -> None:
        if geom_type == "Polygon":
            if coords:
                fill_ring(coords[0])
        elif geom_type == "MultiPolygon":
            for poly in coords:
                if poly:
                    fill_ring(poly[0])

    for feature in features:
        geom = feature.get("geometry") or feature
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if not gtype or coords is None:
            continue
        walk_coords(coords, gtype)
    return mask


def build_synthetic_land_mask(width: int, height: int) -> list[bool]:
    """Fallback only for offline tests when no Natural Earth mask is present."""

    mask: list[bool] = []
    for y in range(height):
        for x in range(width):
            lon, lat = pixel_to_lonlat(x, y, width, height)
            land = False
            # Rough continental Europe + Anatolia + Maghreb coast.
            if 36 <= lat <= 71 and -10 <= lon <= 40:
                land = True
            if 30 <= lat <= 37 and -10 <= lon <= 36:
                land = lat > 31.2 or lon > -5
            if 36 <= lat <= 42 and 26 <= lon <= 45:
                land = True
            # Hollow seas (very approximate; not production geography).
            if 30.5 < lat < 44.5 and -6 < lon < 36.5:
                # Mediterranean basin
                if lat < 43.2 and not (lon < -0.5 and lat > 36.5):
                    if not (40.5 < lat < 44.2 and 8 < lon < 18.5):  # keep Italy
                        if not (36 < lat < 40.5 and -9 < lon < 3):  # keep Iberia south tip
                            if 31 < lat < 44 and -5 < lon < 35:
                                # keep north africa strip
                                if lat > 36.8 or not (-10 < lon < 35):
                                    if lat > 33.5 and lat < 44 and lon > -5:
                                        if not (lat > 41.5 and lon < 10):
                                            if 34 < lat < 43.5 and 0 < lon < 28:
                                                land = False
            if 40.5 < lat < 46.8 and 27.5 < lon < 41.5:
                land = False  # Black Sea
            if 53 < lat < 66 and 14 < lon < 30:
                # Baltic rough hole
                if 54 < lat < 60.5 and 16 < lon < 28:
                    land = False
            # British Isles blocks
            if 50 < lat < 59 and -8 < lon < 2:
                land = True
            if 51 < lat < 55.5 and -10.5 < lon < -5.5:
                land = True
            mask.append(land)
    return mask


def label_land_components(land: list[bool], width: int, height: int) -> list[int]:
    labels = [-1] * (width * height)
    current = 0
    for y in range(height):
        for x in range(width):
            idx = y * width + x
            if not land[idx] or labels[idx] >= 0:
                continue
            queue = deque([idx])
            labels[idx] = current
            while queue:
                i = queue.popleft()
                cx, cy = i % width, i // width
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    ni = ny * width + nx
                    if land[ni] and labels[ni] < 0:
                        labels[ni] = current
                        queue.append(ni)
            current += 1
    return labels


def generate_europe_mediterranean_prototype(
    *,
    settlements_loc: str | Path | None = None,
    world_tga: str | Path | None = None,
    land_geojson: str | Path | None = None,
    land_mask_png: str | Path | None = None,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    width: int = 1600,
    height: int = 1000,
    commit_mask_copy: bool = False,
) -> dict:
    """Generate cropped Europe-Mediterranean color-ID map + typed adjacency graph."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    settlements = load_settlement_labels(settlements_loc)
    if len(settlements) < 20:
        raise RuntimeError(f"Too few theatre settlements: {len(settlements)}")

    land_source = ""
    if land_geojson and Path(land_geojson).is_file():
        land = rasterize_land_geojson(land_geojson, width, height)
        land_source = "natural_earth_land_geojson"
    elif land_mask_png and Path(land_mask_png).is_file():
        land = load_land_mask_png(land_mask_png, width, height)
        land_source = "committed_land_mask_png"
    elif DEFAULT_LAND_MASK.is_file():
        land = load_land_mask_png(DEFAULT_LAND_MASK, width, height)
        land_source = "package_land_mask_png"
    elif world_tga and Path(world_tga).is_file():
        # Legacy research path: still land-only, but not preferred geography source.
        land = _land_mask_from_world_tga(world_tga, width, height)
        land_source = "research_tga_theatre_crop_legacy"
    else:
        land = build_synthetic_land_mask(width, height)
        land_source = "synthetic_theatre_fixture"

    if sum(1 for value in land if value) < width * height * 0.08:
        raise RuntimeError("Land mask too empty for Europe-Mediterranean theatre")

    components = label_land_components(land, width, height)

    seeds: list[dict] = []
    for index, row in enumerate(settlements):
        px, py = lonlat_to_pixel(row["lon"], row["lat"], width, height)
        if not land[py * width + px]:
            found = _nearest_land(px, py, land, width, height, max_radius=40)
            if found is None:
                continue
            px, py = found
        component = components[py * width + px]
        rgb = rgb_for_index(index)
        province_id = f"{PROVINCE_PREFIX}{row['source_settlement_key']}"
        seeds.append(
            {
                "province_id": province_id,
                "display_name": row["display_name"],
                "rgb": list(rgb),
                "source_settlement_key": row["source_settlement_key"],
                "source_region_key": row["source_region_key"],
                "lat": row["lat"],
                "lon": row["lon"],
                "confidence": row["confidence"],
                "pixel": (px, py),
                "component": component,
            }
        )
    if len(seeds) < 20:
        raise RuntimeError(f"Too few land-anchored seeds: {len(seeds)}")

    seeds_by_component: dict[int, list[int]] = defaultdict(list)
    for i, seed in enumerate(seeds):
        seeds_by_component[int(seed["component"])].append(i)

    owners = [-1] * (width * height)
    pixels = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            idx = y * width + x
            base = idx * 3
            if not land[idx]:
                pixels[base : base + 3] = bytes(SEA_RGB)
                continue
            component = components[idx]
            candidates = seeds_by_component.get(component, [])
            if not candidates:
                # Unseeded landmass stays unplayable water-colored background.
                pixels[base : base + 3] = bytes(SEA_RGB)
                land[idx] = False
                continue
            best_i = candidates[0]
            best_d = 10**18
            for i in candidates:
                sx, sy = seeds[i]["pixel"]
                d = (x - sx) * (x - sx) + (y - sy) * (y - sy)
                if d < best_d:
                    best_d = d
                    best_i = i
            owners[idx] = best_i
            r, g, b = seeds[best_i]["rgb"]
            pixels[base] = r
            pixels[base + 1] = g
            pixels[base + 2] = b

    # Drop empty / tiny provinces and reindex.
    area = [0] * len(seeds)
    for owner in owners:
        if owner >= 0:
            area[owner] += 1
    active = [i for i, count in enumerate(area) if count >= MIN_PROVINCE_PIXELS]
    if len(active) < 20:
        raise RuntimeError(f"Too few active provinces: {len(active)}")
    index_map = {old: new for new, old in enumerate(active)}
    seeds = [seeds[i] for i in active]
    for new_i, seed in enumerate(seeds):
        seed["rgb"] = list(rgb_for_index(new_i))
    for idx, old in enumerate(owners):
        base = idx * 3
        if old < 0:
            continue
        if old not in index_map:
            pixels[base : base + 3] = bytes(SEA_RGB)
            owners[idx] = -1
            land[idx] = False
            continue
        new_i = index_map[old]
        owners[idx] = new_i
        r, g, b = seeds[new_i]["rgb"]
        pixels[base] = r
        pixels[base + 1] = g
        pixels[base + 2] = b

    # Marker anchors = province centroids on land.
    sums = [[0.0, 0.0, 0] for _ in seeds]
    for y in range(height):
        for x in range(width):
            owner = owners[y * width + x]
            if owner < 0:
                continue
            sums[owner][0] += x
            sums[owner][1] += y
            sums[owner][2] += 1
    for i, seed in enumerate(seeds):
        count = max(sums[i][2], 1)
        cx = sums[i][0] / count
        cy = sums[i][1] / count
        ax, ay = int(round(cx)), int(round(cy))
        if owners[ay * width + ax] != i:
            found = _nearest_owned(ax, ay, owners, i, width, height)
            if found is not None:
                ax, ay = found
        seed["marker_anchor"] = [float(ax), float(height - 1 - ay)]
        seed["pixel"] = (ax, ay)
        seed["area_px"] = sums[i][2]

    # Land adjacency: only direct 4-neighbor land pixel touches (no water gap bridging).
    land_edges: set[tuple[int, int]] = set()
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
                    land_edges.add((min(i, j), max(i, j)))

    id_by_key = {seed["source_settlement_key"]: seed["province_id"] for seed in seeds}
    typed_edges: list[dict] = []
    neighbor_map: dict[str, list[str]] = defaultdict(list)
    edge_types: dict[tuple[str, str], str] = {}

    for left, right in sorted(land_edges):
        a = seeds[left]["province_id"]
        b = seeds[right]["province_id"]
        key = tuple(sorted((a, b)))
        edge_types[key] = "land"
        neighbor_map[a].append(b)
        neighbor_map[b].append(a)
        typed_edges.append({"a": a, "b": b, "type": "land"})

    for left_key, right_key, edge_type in AUTHED_CROSSINGS:
        a = id_by_key.get(left_key)
        b = id_by_key.get(right_key)
        if not a or not b:
            continue
        key = tuple(sorted((a, b)))
        if key in edge_types and edge_types[key] == "land":
            continue
        if key not in edge_types:
            edge_types[key] = edge_type
            neighbor_map[a].append(b)
            neighbor_map[b].append(a)
            typed_edges.append({"a": a, "b": b, "type": edge_type})

    # Shape metrics / validation.
    warnings: list[str] = []
    for seed in seeds:
        bbox = _province_bbox(owners, seeds.index(seed), width, height)
        if bbox is None:
            continue
        min_x, min_y, max_x, max_y, area = bbox
        w = max(max_x - min_x + 1, 1)
        h = max(max_y - min_y + 1, 1)
        aspect = max(w / h, h / w)
        seed["bbox_aspect"] = aspect
        seed["area_px"] = area
        if area < MIN_PROVINCE_PIXELS:
            warnings.append(f"small_area:{seed['province_id']}:{area}")
        if aspect > MAX_ASPECT_WARN:
            warnings.append(f"thin_province:{seed['province_id']}:{aspect:.1f}")

    # Ocean must remain unassigned.
    for idx, is_land in enumerate(land):
        if not is_land and owners[idx] >= 0:
            raise ValueError("Ocean pixel assigned to land province")

    # Marker inside province.
    for seed in seeds:
        ax, ay = seed["pixel"]
        if owners[ay * width + ax] != seeds.index(seed):
            raise ValueError(f"Marker outside province {seed['province_id']}")

    # No multi-component province (except intentional island groups handled by component lock).
    for i, seed in enumerate(seeds):
        comps = {components[idx] for idx, owner in enumerate(owners) if owner == i}
        if len(comps) != 1:
            raise ValueError(f"Province spans multiple landmasses: {seed['province_id']}")

    table = []
    for seed in seeds:
        pid = seed["province_id"]
        land_neighbors = sorted(
            {
                edge["b"] if edge["a"] == pid else edge["a"]
                for edge in typed_edges
                if edge["type"] == "land" and pid in (edge["a"], edge["b"])
            }
        )
        all_neighbors = sorted(set(neighbor_map.get(pid, [])))
        table.append(
            {
                "province_id": pid,
                "display_name": seed["display_name"],
                "rgb": seed["rgb"],
                "marker_anchor": seed["marker_anchor"],
                "name_is_human_readable": True,
                # Campaign movement uses all traversable edges (land + authored crossings).
                "source_neighbors": all_neighbors,
                "land_neighbors": land_neighbors,
                "edge_types": {
                    (edge["b"] if edge["a"] == pid else edge["a"]): edge["type"]
                    for edge in typed_edges
                    if pid in (edge["a"], edge["b"])
                },
                "provenance": {
                    "generator": "europe_mediterranean_prototype_v2_geo",
                    "method": "natural_earth_land_mask_component_voronoi",
                    "source_settlement_key": seed["source_settlement_key"],
                    "source_region_key": seed["source_region_key"],
                    "confidence": seed["confidence"],
                    "lat": seed["lat"],
                    "lon": seed["lon"],
                    "theatre_bounds": list(THEATRE_BOUNDS),
                    "area_px": seed.get("area_px", 0),
                    "bbox_aspect": seed.get("bbox_aspect", 0.0),
                    "land_component": int(seed["component"]),
                },
            }
        )

    for row in table:
        for neighbor in row["source_neighbors"]:
            peer = next(item for item in table if item["province_id"] == neighbor)
            if row["province_id"] not in peer["source_neighbors"]:
                raise ValueError(f"Asymmetric adjacency {row['province_id']} / {neighbor}")

    id_png = out / "id_map.png"
    write_png_rgb(id_png, width, height, bytes(pixels))

    silhouette_bytes = bytearray(width * height * 3)
    mask_bytes = bytearray(width * height * 3)
    for i, is_land in enumerate(land):
        base = i * 3
        if is_land:
            silhouette_bytes[base : base + 3] = bytes((62, 64, 58))
            mask_bytes[base : base + 3] = bytes((255, 255, 255))
        else:
            silhouette_bytes[base : base + 3] = bytes((10, 14, 22))
            mask_bytes[base : base + 3] = bytes((0, 0, 0))
    silhouette = out / "land_silhouette.png"
    write_png_rgb(silhouette, width, height, bytes(silhouette_bytes))
    write_png_rgb(out / "land_mask.png", width, height, bytes(mask_bytes))

    if commit_mask_copy or land_source.startswith("natural_earth"):
        PACKAGE_DATA.mkdir(parents=True, exist_ok=True)
        write_png_rgb(DEFAULT_LAND_MASK, width, height, bytes(mask_bytes))

    # Med / Black Sea sample points must stay water.
    for name, lat, lon in (
        ("mediterranean", 35.0, 18.0),
        ("black_sea", 43.0, 34.0),
        ("baltic", 56.5, 19.5),
        ("north_sea", 56.0, 3.0),
    ):
        sx, sy = lonlat_to_pixel(lon, lat, width, height)
        if owners[sy * width + sx] >= 0:
            warnings.append(f"expected_water_landfilled:{name}")

    present = {owner for owner in owners if owner >= 0}
    if present != set(range(len(seeds))):
        raise ValueError("Not every province received land pixels")

    manifest = import_strategic_map(
        id_png,
        table,
        out / "map_manifest.json",
        map_id=MAP_ID,
        provenance="research_derived_europe_mediterranean_prototype_v2",
        ignored_colors=(SEA_RGB,),
        texture_output=id_png,
    )
    # Prefer our land-touch + authored graph over gap-bridged texture adjacency.
    manifest["adjacency"] = {
        "edge_count": len(typed_edges),
        "validated_against_graph": True,
        "missing_edges": [],
        "extra_edges": [],
        "edges": typed_edges,
        "types": ["land", "strait", "ferry_or_sea_lane"],
        "note": "Land edges from 4-neighbor land pixel touch only; crossings are authored.",
    }
    manifest["asset_status"] = "prototype_only_not_approved_for_distribution"
    manifest["theatre"] = {
        "name": "Europe-Mediterranean",
        "bounds_lon_lat": list(THEATRE_BOUNDS),
        "province_count": len(table),
        "width": width,
        "height": height,
        "land_source": land_source,
        "excludes": [
            "Americas",
            "East Asia",
            "South Asia",
            "Australia",
            "sub-Saharan Africa",
            "deep Middle East",
        ],
    }
    manifest["geography_status"] = {
        "pipeline": "accepted_checkpoint",
        "map_geometry": "provisional_project_voronoi",
        "land_mask": land_source,
        "pack_region_meshes": "not_imported",
        "pr_complete": False,
        "warnings": warnings,
    }
    placeholder = out / "background_placeholder.png"
    if not placeholder.is_file() and (out / "land_silhouette.png").is_file():
        # Ensure repo-safe fixture exists beside generated outputs.
        placeholder.write_bytes((out / "land_silhouette.png").read_bytes())
    manifest["visual_background_policy"] = {
        "repo_stores_pack_artwork": False,
        "local_config": "background_config.json",
        "example_config": "background_config.example.json",
        "placeholder": "background_placeholder.png",
        "status": (
            "Pack background integration works locally. "
            "Pack image is not stored or distributed by the repository. "
            "Province geometry remains provisional."
        ),
    }
    manifest["provenance_table"] = {
        "visual_background": "local_external_optional_not_in_repo",
        "visual_background_fixture": "background_placeholder.png",
        "gameplay_land_mask": "natural_earth_or_package_mask",
        "province_boundaries_selection": "project_color_id_texture",
        "province_boundaries_layout": "project_component_voronoi_provisional",
        "settlement_names": "title_case_seed_or_optional_pack_loc",
        "settlement_coordinates": "project_public_geo_table",
        "ports": "not_imported_from_pack",
        "terrain_gameplay": "not_imported_from_pack",
        "adjacency": "project_land_touch_plus_authored_crossings",
    }
    manifest["clean_room"] = {
        "status": "prototype-only; Natural Earth land mask is public domain; not final ship art",
        "committed_outputs": ["id_map.png", "land_silhouette.png", "map_manifest.json"],
        "geometry_method": (
            "component-locked settlement Voronoi on geographic land mask; "
            "authored strait/ferry edges; ocean unselectable; "
            "world_test_9.pack is name/ID reference only (regions.esf meshes not imported)"
        ),
        "land_mask_rights": "Natural Earth public domain when land_source is natural_earth_* / package mask derived from it",
        "pack_role": "research reference for names/IDs/future anchors; not coastline; not current province meshes",
    }
    (out / "map_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _land_mask_from_world_tga(path: str | Path, width: int, height: int) -> list[bool]:
    src_w, src_h, rgb = decode_tga_rgb(path)
    mask: list[bool] = []
    for y in range(height):
        for x in range(width):
            lon, lat = pixel_to_lonlat(x, y, width, height)
            sx = int(round((lon + 180.0) / 360.0 * (src_w - 1)))
            sy = int(round((90.0 - lat) / 180.0 * (src_h - 1)))
            sx = max(0, min(src_w - 1, sx))
            sy = max(0, min(src_h - 1, sy))
            i = (sy * src_w + sx) * 3
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            if b > r + 12 and b > g + 8:
                mask.append(False)
            elif r + g + b < 40:
                mask.append(False)
            else:
                mask.append(True)
    return mask


def _nearest_land(
    x: int,
    y: int,
    land: list[bool],
    width: int,
    height: int,
    *,
    max_radius: int = 80,
) -> tuple[int, int] | None:
    if land[y * width + x]:
        return x, y
    for radius in range(1, max_radius + 1):
        for yy in range(max(0, y - radius), min(height, y + radius + 1)):
            for xx in range(max(0, x - radius), min(width, x + radius + 1)):
                if abs(xx - x) != radius and abs(yy - y) != radius:
                    continue
                if land[yy * width + xx]:
                    return xx, yy
    return None


def _nearest_owned(
    x: int,
    y: int,
    owners: list[int],
    owner: int,
    width: int,
    height: int,
) -> tuple[int, int] | None:
    if 0 <= x < width and 0 <= y < height and owners[y * width + x] == owner:
        return x, y
    queue = deque([(x, y)])
    seen = {(x, y)}
    while queue:
        cx, cy = queue.popleft()
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if nx < 0 or ny < 0 or nx >= width or ny >= height or (nx, ny) in seen:
                continue
            seen.add((nx, ny))
            if owners[ny * width + nx] == owner:
                return nx, ny
            queue.append((nx, ny))
            if len(seen) > width * height:
                break
    return None


def _province_bbox(
    owners: list[int],
    owner: int,
    width: int,
    height: int,
) -> tuple[int, int, int, int, int] | None:
    min_x, min_y = width, height
    max_x, max_y = -1, -1
    area = 0
    for y in range(height):
        for x in range(width):
            if owners[y * width + x] != owner:
                continue
            area += 1
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
    if area == 0:
        return None
    return min_x, min_y, max_x, max_y, area
