"""Build aligned Gate 0 OpenGS raster inputs from pinned Natural Earth GeoJSON.

The generated files are research inputs. They are not a production Gates map.
Natural Earth source files remain in the CI checkout and are not copied into
this repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageDraw
from pyproj import CRS, Transformer
from scipy.ndimage import label as connected_components
from shapely.geometry import GeometryCollection, MultiLineString, MultiPolygon
from shapely.geometry import Polygon, box, shape
from shapely.ops import transform


ROOT = Path(__file__).resolve().parents[2]
PIN_PATH = Path(__file__).with_name("natural_earth_pin.json")
OCEAN_COLOR = (5, 20, 18)
LAND_COLOR = (220, 220, 220)
LAKE_COLOR = (0, 255, 0)
BOUNDARY_COLOR = (0, 0, 0)
BOUNDARY_BACKGROUND = (255, 255, 255)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_blob_sha1(path: Path) -> str:
    completed = subprocess.run(
        ["git", "hash-object", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _git_head(repository_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_files(
    natural_earth_root: Path, pin: dict[str, Any]
) -> dict[str, Path]:
    result: dict[str, Path] = {}
    failures: list[str] = []
    for row in pin["files"]:
        role = str(row["role"])
        path = natural_earth_root / str(row["path"])
        if not path.is_file():
            failures.append(f"missing {role}: {path}")
            continue
        actual_blob = _git_blob_sha1(path)
        expected_blob = str(row["git_blob_sha1"])
        if actual_blob != expected_blob:
            failures.append(
                f"blob mismatch for {role}: expected {expected_blob}, got {actual_blob}"
            )
        result[role] = path
    if failures:
        raise RuntimeError("; ".join(failures))
    return result


def _sample_bbox_edges(
    lon_min: float,
    lat_min: float,
    lon_max: float,
    lat_max: float,
    samples: int = 256,
) -> tuple[np.ndarray, np.ndarray]:
    horizontal = np.linspace(lon_min, lon_max, samples)
    vertical = np.linspace(lat_min, lat_max, samples)
    lons = np.concatenate(
        [
            horizontal,
            horizontal,
            np.full(samples, lon_min),
            np.full(samples, lon_max),
        ]
    )
    lats = np.concatenate(
        [
            np.full(samples, lat_min),
            np.full(samples, lat_max),
            vertical,
            vertical,
        ]
    )
    return lons, lats


def _iter_polygons(geometry) -> Iterable[Polygon]:
    if geometry.is_empty:
        return
    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, MultiPolygon):
        yield from geometry.geoms
    elif isinstance(geometry, GeometryCollection):
        for child in geometry.geoms:
            yield from _iter_polygons(child)


def _iter_lines(geometry):
    if geometry.is_empty:
        return
    geometry_type = geometry.geom_type
    if geometry_type in {"LineString", "LinearRing"}:
        yield geometry
    elif isinstance(geometry, MultiLineString):
        yield from geometry.geoms
    elif isinstance(geometry, GeometryCollection):
        for child in geometry.geoms:
            yield from _iter_lines(child)
    elif isinstance(geometry, (Polygon, MultiPolygon)):
        for polygon in _iter_polygons(geometry):
            yield polygon.exterior
            yield from polygon.interiors


def _integer_points(coordinates) -> list[tuple[int, int]]:
    return [(int(round(x)), int(round(y))) for x, y in coordinates]


def _draw_polygon(
    draw: ImageDraw.ImageDraw,
    polygon: Polygon,
    fill: tuple[int, int, int],
    hole_fill: tuple[int, int, int],
) -> None:
    exterior = _integer_points(polygon.exterior.coords)
    if len(exterior) >= 3:
        draw.polygon(exterior, fill=fill)
    for interior in polygon.interiors:
        points = _integer_points(interior.coords)
        if len(points) >= 3:
            draw.polygon(points, fill=hole_fill)


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    geometry,
    fill: tuple[int, int, int],
    width: int,
) -> int:
    count = 0
    for line in _iter_lines(geometry):
        points = _integer_points(line.coords)
        if len(points) >= 2:
            draw.line(points, fill=fill, width=width, joint="curve")
            count += 1
    return count


def _project_geometry(geometry, transformer: Transformer):
    return transform(transformer.transform, geometry)


def _pixel_transformer(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    width: int,
    height: int,
):
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)

    def to_pixels(x, y, z=None):
        x_arr = np.asarray(x, dtype=np.float64)
        y_arr = np.asarray(y, dtype=np.float64)
        px = (x_arr - min_x) / span_x * float(width - 1)
        py = (max_y - y_arr) / span_y * float(height - 1)
        return px, py

    return to_pixels


def _clip_project_pixel(
    raw_geometry: dict[str, Any],
    lon_lat_clip,
    projection: Transformer,
    to_pixels,
):
    geometry = shape(raw_geometry)
    if geometry.is_empty or not geometry.intersects(lon_lat_clip):
        return None
    clipped = geometry.intersection(lon_lat_clip)
    if clipped.is_empty:
        return None
    projected = _project_geometry(clipped, projection)
    if projected.is_empty:
        return None
    return transform(to_pixels, projected)


def _population(properties: dict[str, Any]) -> float:
    for key in ("POP_MAX", "POP_MIN", "MAX_POP10", "POP1950"):
        value = properties.get(key)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return 0.0


def _apply_city_density(
    density: np.ndarray,
    x: float,
    y: float,
    population: float,
) -> None:
    height, width = density.shape
    scaled = float(np.clip((math.log10(max(population, 1000.0)) - 3.0) / 4.0, 0.0, 1.0))
    radius = int(round(5.0 + scaled * 31.0))
    depth = 45.0 + scaled * 175.0
    sigma = max(radius / 2.4, 1.0)
    center_x = int(round(x))
    center_y = int(round(y))
    x0 = max(center_x - radius, 0)
    x1 = min(center_x + radius + 1, width)
    y0 = max(center_y - radius, 0)
    y1 = min(center_y + radius + 1, height)
    if x0 >= x1 or y0 >= y1:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    distance_squared = (xx - x) ** 2 + (yy - y) ** 2
    influence = np.exp(-distance_squared / (2.0 * sigma * sigma))
    candidate = 235.0 - depth * influence
    density[y0:y1, x0:x1] = np.minimum(
        density[y0:y1, x0:x1], candidate
    )


def build_inputs(args: argparse.Namespace) -> dict[str, Any]:
    natural_earth_root = Path(args.natural_earth_root).resolve()
    output_root = Path(args.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    pin = _load_json(Path(args.pin).resolve())
    sources = _source_files(natural_earth_root, pin)
    repository_head = _git_head(natural_earth_root)

    lon_min, lat_min, lon_max, lat_max = [
        float(value) for value in pin["theatre_lon_lat_bounds"]
    ]
    width = int(args.width)
    height = int(args.height)
    if width < 64 or height < 64:
        raise ValueError("output dimensions are too small")

    projection_string = str(pin["projection"]["proj"])
    projection = Transformer.from_crs(
        CRS.from_epsg(4326), CRS.from_proj4(projection_string), always_xy=True
    )
    edge_lons, edge_lats = _sample_bbox_edges(
        lon_min, lat_min, lon_max, lat_max
    )
    edge_x, edge_y = projection.transform(edge_lons, edge_lats)
    projected_bounds = (
        float(np.min(edge_x)),
        float(np.min(edge_y)),
        float(np.max(edge_x)),
        float(np.max(edge_y)),
    )
    to_pixels = _pixel_transformer(*projected_bounds, width, height)
    lon_lat_clip = box(lon_min, lat_min, lon_max, lat_max)

    land_image = Image.new("RGB", (width, height), OCEAN_COLOR)
    land_draw = ImageDraw.Draw(land_image)
    boundary_image = Image.new("RGB", (width, height), BOUNDARY_BACKGROUND)
    boundary_draw = ImageDraw.Draw(boundary_image)
    density = np.full((height, width), 235.0, dtype=np.float32)

    counts = {
        "land_features": 0,
        "land_polygon_parts": 0,
        "lake_features": 0,
        "lake_polygon_parts": 0,
        "boundary_features": 0,
        "boundary_line_parts": 0,
        "populated_places": 0,
    }

    land_collection = _load_json(sources["land"])
    for feature in land_collection.get("features", []):
        pixel_geometry = _clip_project_pixel(
            feature["geometry"], lon_lat_clip, projection, to_pixels
        )
        if pixel_geometry is None:
            continue
        counts["land_features"] += 1
        for polygon in _iter_polygons(pixel_geometry):
            _draw_polygon(land_draw, polygon, LAND_COLOR, OCEAN_COLOR)
            counts["land_polygon_parts"] += 1

    lakes_collection = _load_json(sources["lakes"])
    for feature in lakes_collection.get("features", []):
        pixel_geometry = _clip_project_pixel(
            feature["geometry"], lon_lat_clip, projection, to_pixels
        )
        if pixel_geometry is None:
            continue
        counts["lake_features"] += 1
        for polygon in _iter_polygons(pixel_geometry):
            _draw_polygon(land_draw, polygon, LAKE_COLOR, LAND_COLOR)
            counts["lake_polygon_parts"] += 1

    boundary_collection = _load_json(sources["national_boundaries"])
    boundary_width = max(1, int(round(width / 1024.0)))
    for feature in boundary_collection.get("features", []):
        pixel_geometry = _clip_project_pixel(
            feature["geometry"], lon_lat_clip, projection, to_pixels
        )
        if pixel_geometry is None:
            continue
        counts["boundary_features"] += 1
        counts["boundary_line_parts"] += _draw_lines(
            boundary_draw,
            pixel_geometry,
            BOUNDARY_COLOR,
            boundary_width,
        )

    places_collection = _load_json(sources["populated_places"])
    for feature in places_collection.get("features", []):
        raw_geometry = feature.get("geometry")
        if not raw_geometry:
            continue
        geometry = shape(raw_geometry)
        if geometry.is_empty or geometry.geom_type != "Point":
            continue
        if not lon_lat_clip.covers(geometry):
            continue
        projected = _project_geometry(geometry, projection)
        pixel_point = transform(to_pixels, projected)
        population = _population(feature.get("properties", {}))
        _apply_city_density(density, pixel_point.x, pixel_point.y, population)
        counts["populated_places"] += 1

    density_image = Image.fromarray(
        np.clip(np.rint(density), 0, 255).astype(np.uint8), mode="L"
    )

    land_path = output_root / "land.png"
    boundary_path = output_root / "boundary.png"
    density_path = output_root / "density.png"
    land_image.save(land_path, optimize=False, compress_level=9)
    boundary_image.save(boundary_path, optimize=False, compress_level=9)
    density_image.save(density_path, optimize=False, compress_level=9)

    land_array = np.asarray(land_image)
    ocean_mask = np.all(land_array == OCEAN_COLOR, axis=2)
    lake_mask = np.all(land_array == LAKE_COLOR, axis=2)
    land_mask = ~ocean_mask & ~lake_mask
    _, lake_component_count = connected_components(lake_mask)

    source_manifest = []
    for row in pin["files"]:
        source_path = natural_earth_root / str(row["path"])
        source_manifest.append(
            {
                **row,
                "sha256": _sha256_file(source_path),
                "size_bytes": source_path.stat().st_size,
            }
        )

    manifest = {
        "schema": "gates-of-codex.opengs-natural-earth-inputs",
        "schema_version": 1,
        "status": "gate0_research_input",
        "source_repository": str(pin["repository"]),
        "source_ref": str(pin["ref"]),
        "source_commit": repository_head,
        "source_license": str(pin["license"]),
        "source_files": source_manifest,
        "projection": pin["projection"],
        "lon_lat_bounds": [lon_min, lat_min, lon_max, lat_max],
        "projected_bounds": list(projected_bounds),
        "width": width,
        "height": height,
        "colors": {
            "ocean": list(OCEAN_COLOR),
            "land": list(LAND_COLOR),
            "lake": list(LAKE_COLOR),
            "boundary": list(BOUNDARY_COLOR),
        },
        "feature_counts": counts,
        "pixel_counts": {
            "land": int(land_mask.sum()),
            "ocean": int(ocean_mask.sum()),
            "lake": int(lake_mask.sum()),
            "lake_connected_components": int(lake_component_count),
        },
        "outputs": {
            "land.png": {
                "sha256": _sha256_file(land_path),
                "size_bytes": land_path.stat().st_size,
            },
            "boundary.png": {
                "sha256": _sha256_file(boundary_path),
                "size_bytes": boundary_path.stat().st_size,
            },
            "density.png": {
                "sha256": _sha256_file(density_path),
                "size_bytes": density_path.stat().st_size,
            },
        },
        "terrain_input": None,
        "terrain_note": "Gate 0 benchmarks upstream default terrain behavior only. A legally pinned terrain source is evaluated separately.",
        "production_map_replacement_authorized": False,
    }
    manifest_path = output_root / "input_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--natural-earth-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--width", type=int, default=2048)
    parser.add_argument("--height", type=int, default=1536)
    parser.add_argument("--pin", default=str(PIN_PATH))
    return parser


def main() -> int:
    manifest = build_inputs(_parser().parse_args())
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
