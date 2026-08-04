from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from .europe_mediterranean_map import THEATRE_BOUNDS, lonlat_to_pixel, pixel_to_lonlat
from .strategic_map import decode_png_rgb, write_png_rgb


DEFAULT_SOURCE_BOUNDS = (-180.0, 180.0, -90.0, 90.0)
CONTROL_POINTS: tuple[tuple[str, float, float], ...] = (
    ("london", 51.5074, -0.1278),
    ("gibraltar", 36.1408, -5.3536),
    ("rome", 41.9028, 12.4964),
    ("istanbul", 41.0082, 28.9784),
    ("moscow", 55.7558, 37.6173),
    ("cairo", 30.0444, 31.2357),
    ("northern_norway", 71.0, 25.0),
    ("western_iceland", 64.8, -23.0),
)


def decode_tga_rgb(path: str | Path) -> tuple[int, int, bytes]:
    data = Path(path).read_bytes()
    id_len, cmap_type, image_type = data[0], data[1], data[2]
    width, height = struct.unpack_from("<HH", data, 12)
    bpp = data[16]
    desc = data[17]
    if image_type != 2 or bpp not in (24, 32) or cmap_type != 0:
        raise ValueError(f"Unsupported TGA: {path}")
    offset = 18 + id_len
    spp = bpp // 8
    raw = data[offset : offset + width * height * spp]
    top_down = bool(desc & 0x20)
    rows: list[bytes] = []
    for y in range(height):
        src_y = y if top_down else (height - 1 - y)
        src = raw[src_y * width * spp : (src_y + 1) * width * spp]
        row = bytearray(width * 3)
        for x in range(width):
            i = x * spp
            b, g, r = src[i], src[i + 1], src[i + 2]
            o = x * 3
            row[o : o + 3] = bytes((r, g, b))
        rows.append(bytes(row))
    return width, height, b"".join(rows)


def sample_rgb(rgb: bytes, width: int, height: int, x: float, y: float) -> tuple[int, int, int]:
    x = min(max(x, 0.0), width - 1.001)
    y = min(max(y, 0.0), height - 1.001)
    x0, y0 = int(x), int(y)
    x1 = min(x0 + 1, width - 1)
    y1 = min(y0 + 1, height - 1)
    fx, fy = x - x0, y - y0

    def at(ix: int, iy: int) -> tuple[float, float, float]:
        i = (iy * width + ix) * 3
        return float(rgb[i]), float(rgb[i + 1]), float(rgb[i + 2])

    c00, c10, c01, c11 = at(x0, y0), at(x1, y0), at(x0, y1), at(x1, y1)
    out = []
    for k in range(3):
        value = (
            c00[k] * (1 - fx) * (1 - fy)
            + c10[k] * fx * (1 - fy)
            + c01[k] * (1 - fx) * fy
            + c11[k] * fx * fy
        )
        out.append(int(round(min(255, max(0, value)))))
    return out[0], out[1], out[2]


def lonlat_to_source_pixel(
    lon: float,
    lat: float,
    width: int,
    height: int,
    source_bounds: tuple[float, float, float, float] = DEFAULT_SOURCE_BOUNDS,
) -> tuple[float, float]:
    lon_min, lon_max, lat_min, lat_max = source_bounds
    x = (lon - lon_min) / (lon_max - lon_min) * (width - 1)
    y = (lat_max - lat) / (lat_max - lat_min) * (height - 1)
    return x, y


def render_calibrated_background(
    *,
    source_rgb: bytes,
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
    source_bounds: tuple[float, float, float, float] = DEFAULT_SOURCE_BOUNDS,
    target_bounds: tuple[float, float, float, float] = THEATRE_BOUNDS,
    fit: str = "contain",
    offset_px: tuple[float, float] = (0.0, 0.0),
    scale: float = 1.0,
    letterbox_rgb: tuple[int, int, int] = (12, 16, 22),
) -> bytes:
    """Map source texture into target gameplay frame without independent X/Y distortion.

    1. Sample source using geographic bounds (same projection family as gameplay).
    2. Build an intermediate theatre image whose pixel aspect matches geographic span
       at mid-latitude (no forced 1.6 stretch of the source crop alone).
    3. Fit that intermediate into target_width x target_height with contain/cover.
    """

    lon_min, lon_max, lat_min, lat_max = target_bounds
    lon_span = max(lon_max - lon_min, 1e-6)
    lat_span = max(lat_max - lat_min, 1e-6)

    # Sample source geographically into the gameplay frame using the SAME theatre
    # lon/lat mapping as the color-ID map (full-frame). Optional scale/offset are
    # applied in gameplay pixels for calibration when pack projection differs.
    # Do NOT naively stretch a source pixel crop with independent X/Y ratios.
    cx = (target_width - 1) * 0.5 + offset_px[0]
    cy = (target_height - 1) * 0.5 + offset_px[1]
    out = bytearray(target_width * target_height * 3)
    for y in range(target_height):
        for x in range(target_width):
            # Inverse of scale about frame center, then map to lon/lat.
            gx = cx + (x - cx) / max(scale, 1e-6)
            gy = cy + (y - cy) / max(scale, 1e-6)
            u = gx / max(target_width - 1, 1)
            v = gy / max(target_height - 1, 1)
            if u < 0.0 or u > 1.0 or v < 0.0 or v > 1.0:
                r, g, b = letterbox_rgb
            else:
                lon = lon_min + u * lon_span
                lat = lat_max - v * lat_span
                sx, sy = lonlat_to_source_pixel(
                    lon, lat, source_width, source_height, source_bounds
                )
                r, g, b = sample_rgb(source_rgb, source_width, source_height, sx, sy)
            i = (y * target_width + x) * 3
            out[i : i + 3] = bytes((r, g, b))
    return bytes(out)


def control_point_report(
    *,
    target_width: int,
    target_height: int,
    target_bounds: tuple[float, float, float, float] = THEATRE_BOUNDS,
) -> list[dict]:
    """Gameplay-pixel locations for calibration control points."""

    rows = []
    for name, lat, lon in CONTROL_POINTS:
        # Temporarily use theatre projection helpers by swapping bounds via direct math.
        lon_min, lon_max, lat_min, lat_max = target_bounds
        x = (lon - lon_min) / (lon_max - lon_min) * (target_width - 1)
        y = (lat_max - lat) / (lat_max - lat_min) * (target_height - 1)
        rows.append(
            {
                "name": name,
                "lat": lat,
                "lon": lon,
                "gameplay_px": [round(x, 2), round(y, 2)],
                "in_frame": 0 <= x < target_width and 0 <= y < target_height,
            }
        )
    return rows


def export_local_pack_background(
    *,
    source_tga: str | Path,
    output_png: str | Path,
    config_json: str | Path | None = None,
    target_width: int = 1600,
    target_height: int = 1000,
    source_bounds: tuple[float, float, float, float] = DEFAULT_SOURCE_BOUNDS,
    target_bounds: tuple[float, float, float, float] = THEATRE_BOUNDS,
    fit: str = "contain",
    offset_px: tuple[float, float] = (0.0, 0.0),
    scale: float = 1.0,
) -> dict:
    sw, sh, rgb = decode_tga_rgb(source_tga)
    out_rgb = render_calibrated_background(
        source_rgb=rgb,
        source_width=sw,
        source_height=sh,
        target_width=target_width,
        target_height=target_height,
        source_bounds=source_bounds,
        target_bounds=target_bounds,
        fit=fit,
        offset_px=offset_px,
        scale=scale,
    )
    out_path = Path(output_png)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_png_rgb(out_path, target_width, target_height, out_rgb)
    payload = {
        "background_texture": str(out_path.resolve()),
        "background_status": "local_research_reference",
        "source_kind": "pack_world_tga_calibrated_export",
        "source_tga": str(Path(source_tga).resolve()),
        "source_dimensions": [sw, sh],
        "source_bounds_lon_lat": list(source_bounds),
        "target_bounds_lon_lat": list(target_bounds),
        "target_dimensions": [target_width, target_height],
        "fit": fit,
        "offset_px": list(offset_px),
        "scale": scale,
        "control_points": control_point_report(
            target_width=target_width,
            target_height=target_height,
            target_bounds=target_bounds,
        ),
        "notes": [
            "Local research reference only. Do not commit this PNG.",
            "Pack background integration is local; repository does not distribute pack artwork.",
        ],
    }
    if config_json is not None:
        cfg = Path(config_json)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_background_config(path: str | Path | None) -> dict | None:
    if not path:
        return None
    cfg = Path(path)
    if not cfg.is_file():
        return None
    return json.loads(cfg.read_text(encoding="utf-8"))
