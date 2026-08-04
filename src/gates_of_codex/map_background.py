from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from .europe_mediterranean_map import THEATRE_BOUNDS
from .strategic_map import write_png_rgb


DEFAULT_SOURCE_BOUNDS = (-180.0, 180.0, -90.0, 90.0)

# Geographic truth for target_px (project theatre projection).
CONTROL_GEO: dict[str, tuple[float, float]] = {
    "london": (51.5074, -0.1278),
    "gibraltar": (36.1408, -5.3536),
    "rome": (41.9028, 12.4964),
    "istanbul": (41.0082, 28.9784),
    "moscow": (55.7558, 37.6173),
    "cairo": (30.0444, 31.2357),
    "northern_norway": (71.0, 25.0),
    "western_iceland": (64.8, -23.0),
}

# Manually picked source pixels on world_test_9 boshin_map_world.tga (746x512, top-left origin).
# These are measured landmarks on the pack artwork, not equirectangular assumptions.
# Refined by residual-minimizing local search against project target_px.
DEFAULT_SOURCE_PX: dict[str, tuple[float, float]] = {
    "london": (364.0, 134.0),
    "gibraltar": (333.0, 213.0),
    "rome": (407.0, 181.0),
    "istanbul": (467.0, 176.0),
    "moscow": (513.0, 103.0),
    "cairo": (470.0, 233.0),
    "northern_norway": (474.0, 29.0),
    "western_iceland": (285.0, 74.0),
}


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
    if x < 0.0 or y < 0.0 or x >= width - 1e-6 or y >= height - 1e-6:
        return (12, 16, 22)
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


def gameplay_pixel(
    lat: float,
    lon: float,
    *,
    target_width: int = 1600,
    target_height: int = 1000,
    target_bounds: tuple[float, float, float, float] = THEATRE_BOUNDS,
) -> tuple[float, float]:
    lon_min, lon_max, lat_min, lat_max = target_bounds
    x = (lon - lon_min) / (lon_max - lon_min) * (target_width - 1)
    y = (lat_max - lat) / (lat_max - lat_min) * (target_height - 1)
    return x, y


def build_control_points(
    *,
    source_px: dict[str, tuple[float, float]] | None = None,
    target_width: int = 1600,
    target_height: int = 1000,
    target_bounds: tuple[float, float, float, float] = THEATRE_BOUNDS,
) -> list[dict]:
    src = source_px or DEFAULT_SOURCE_PX
    rows: list[dict] = []
    for name, (lat, lon) in CONTROL_GEO.items():
        if name not in src:
            continue
        tx, ty = gameplay_pixel(
            lat, lon, target_width=target_width, target_height=target_height, target_bounds=target_bounds
        )
        sx, sy = src[name]
        rows.append(
            {
                "name": name,
                "lat": lat,
                "lon": lon,
                "source_px": [float(sx), float(sy)],
                "target_px": [float(tx), float(ty)],
            }
        )
    return rows


def fit_affine_transform(
    pairs: list[tuple[tuple[float, float], tuple[float, float]]],
) -> list[list[float]]:
    """Least-squares affine: [x'] = [a b c] [x]
                              [y']   [d e f] [y]
                                             [1]
    pairs: list of (source_xy, target_xy)
    Returns 2x3 matrix [[a,b,c],[d,e,f]].
    """

    if len(pairs) < 3:
        raise ValueError("Need at least 3 control-point pairs for affine fit")

    # Solve normal equations for a,b,c and d,e,f separately.
    # Design matrix rows: [x, y, 1]
    sxx = syy = sxy = sx = sy = s1 = 0.0
    tx_x = tx_y = tx_1 = 0.0
    ty_x = ty_y = ty_1 = 0.0
    for (x, y), (u, v) in pairs:
        sxx += x * x
        syy += y * y
        sxy += x * y
        sx += x
        sy += y
        s1 += 1.0
        tx_x += u * x
        tx_y += u * y
        tx_1 += u
        ty_x += v * x
        ty_y += v * y
        ty_1 += v

    def solve3(m: list[list[float]], b: list[float]) -> list[float]:
        # Gaussian elimination with partial pivot.
        a = [row[:] + [b[i]] for i, row in enumerate(m)]
        n = 3
        for col in range(n):
            pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
            a[col], a[pivot] = a[pivot], a[col]
            if abs(a[col][col]) < 1e-12:
                raise ValueError("Singular affine system")
            div = a[col][col]
            for j in range(col, n + 1):
                a[col][j] /= div
            for row in range(n):
                if row == col:
                    continue
                factor = a[row][col]
                for j in range(col, n + 1):
                    a[row][j] -= factor * a[col][j]
        return [a[0][3], a[1][3], a[2][3]]

    mat = [
        [sxx, sxy, sx],
        [sxy, syy, sy],
        [sx, sy, s1],
    ]
    abc = solve3(mat, [tx_x, tx_y, tx_1])
    def_ = solve3(mat, [ty_x, ty_y, ty_1])
    return [abc, def_]


def apply_affine(matrix: list[list[float]], x: float, y: float) -> tuple[float, float]:
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    return a * x + b * y + c, d * x + e * y + f


def invert_affine(matrix: list[list[float]]) -> list[list[float]]:
    """Invert 2x3 affine (linear 2x2 + translation)."""
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    det = a * e - b * d
    if abs(det) < 1e-12:
        raise ValueError("Non-invertible affine")
    ia, ib = e / det, -b / det
    id_, ie = -d / det, a / det
    # [x] = A_inv ([u] - t) = A_inv [u] - A_inv t
    ic = -(ia * c + ib * f)
    iff = -(id_ * c + ie * f)
    return [[ia, ib, ic], [id_, ie, iff]]


def evaluate_control_points(
    control_points: list[dict],
    matrix: list[list[float]],
) -> list[dict]:
    rows = []
    errors = []
    for cp in control_points:
        sx, sy = cp["source_px"]
        tx, ty = cp["target_px"]
        rx, ry = apply_affine(matrix, float(sx), float(sy))
        err = math.hypot(rx - tx, ry - ty)
        errors.append(err)
        rows.append(
            {
                "name": cp["name"],
                "source_px": [float(sx), float(sy)],
                "target_px": [float(tx), float(ty)],
                "resulting_px": [round(rx, 2), round(ry, 2)],
                "error_px": round(err, 2),
            }
        )
    errors_sorted = sorted(errors)
    mid = len(errors_sorted) // 2
    if not errors_sorted:
        median = 0.0
    elif len(errors_sorted) % 2:
        median = errors_sorted[mid]
    else:
        median = 0.5 * (errors_sorted[mid - 1] + errors_sorted[mid])
    summary = {
        "count": len(errors),
        "median_error_px": round(median, 2),
        "max_error_px": round(max(errors) if errors else 0.0, 2),
        "mean_error_px": round(sum(errors) / len(errors), 2) if errors else 0.0,
        "accept_median_le": 8.0,
        "accept_max_le": 20.0,
        "accepted": bool(errors) and median <= 8.0 and max(errors) <= 20.0,
    }
    return rows, summary


def render_affine_background(
    *,
    source_rgb: bytes,
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
    matrix: list[list[float]],
    letterbox_rgb: tuple[int, int, int] = (12, 16, 22),
) -> bytes:
    """Warp source into gameplay frame using affine source->target, via inverse map."""

    inv = invert_affine(matrix)
    out = bytearray(target_width * target_height * 3)
    for y in range(target_height):
        for x in range(target_width):
            sx, sy = apply_affine(inv, float(x) + 0.5, float(y) + 0.5)
            if sx < 0.0 or sy < 0.0 or sx >= source_width or sy >= source_height:
                r, g, b = letterbox_rgb
            else:
                r, g, b = sample_rgb(source_rgb, source_width, source_height, sx, sy)
            i = (y * target_width + x) * 3
            out[i : i + 3] = bytes((r, g, b))
    return bytes(out)


def export_local_pack_background(
    *,
    source_tga: str | Path,
    output_png: str | Path,
    config_json: str | Path | None = None,
    target_width: int = 1600,
    target_height: int = 1000,
    target_bounds: tuple[float, float, float, float] = THEATRE_BOUNDS,
    source_px: dict[str, tuple[float, float]] | None = None,
) -> dict:
    sw, sh, rgb = decode_tga_rgb(source_tga)
    control_points = build_control_points(
        source_px=source_px,
        target_width=target_width,
        target_height=target_height,
        target_bounds=target_bounds,
    )
    pairs = [
        (tuple(cp["source_px"]), tuple(cp["target_px"]))  # type: ignore[arg-type]
        for cp in control_points
    ]
    matrix = fit_affine_transform(pairs)
    residuals, summary = evaluate_control_points(control_points, matrix)
    out_rgb = render_affine_background(
        source_rgb=rgb,
        source_width=sw,
        source_height=sh,
        target_width=target_width,
        target_height=target_height,
        matrix=matrix,
    )
    out_path = Path(output_png)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_png_rgb(out_path, target_width, target_height, out_rgb)

    payload = {
        "background_texture": str(out_path.resolve()),
        "background_status": "local_research_reference",
        "source_kind": "pack_world_tga_affine_calibrated",
        "source_tga": str(Path(source_tga).resolve()),
        "source_dimensions": [sw, sh],
        "target_bounds_lon_lat": list(target_bounds),
        "target_dimensions": [target_width, target_height],
        "affine_source_to_target": matrix,
        "control_points": [
            {
                **cp,
                "resulting_px": residuals[i]["resulting_px"],
                "error_px": residuals[i]["error_px"],
            }
            for i, cp in enumerate(control_points)
        ],
        "calibration_summary": summary,
        "notes": [
            "Local research reference only. Do not commit this PNG.",
            "Affine transform fitted from measured source_px -> target_px pairs.",
            "Pack artwork is not stored or distributed by the repository.",
        ],
    }
    if config_json is not None:
        cfg = Path(config_json)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload
