#!/usr/bin/env python3
"""Natural Earth input construction for OpenGS Gate 3."""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from gate3_core import *


def _iter_polygons(geometry: Any) -> Iterator[Any]:
    from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
    if geometry.is_empty:
        return
    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, MultiPolygon):
        yield from geometry.geoms
    elif isinstance(geometry, GeometryCollection):
        for child in geometry.geoms:
            yield from _iter_polygons(child)


def _iter_lines(geometry: Any) -> Iterator[Any]:
    from shapely.geometry import GeometryCollection, MultiLineString, MultiPolygon, Polygon
    if geometry.is_empty:
        return
    if geometry.geom_type in {"LineString", "LinearRing"}:
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


def _integer_points(coordinates: Iterable[Sequence[float]]) -> list[tuple[int, int]]:
    return [(int(round(x)), int(round(y))) for x, y in coordinates]


def _draw_polygon(draw: Any, polygon: Any, fill: Any, hole_fill: Any) -> None:
    exterior = _integer_points(polygon.exterior.coords)
    if len(exterior) >= 3:
        draw.polygon(exterior, fill=fill)
    for interior in polygon.interiors:
        points = _integer_points(interior.coords)
        if len(points) >= 3:
            draw.polygon(points, fill=hole_fill)


def _draw_land_polygon(draw: Any, polygon: Any) -> None:
    _draw_polygon(draw, polygon, LAND_COLOR, LAND_COLOR)


def _draw_lake_polygon(draw: Any, polygon: Any) -> None:
    _draw_polygon(draw, polygon, LAKE_COLOR, LAND_COLOR)


def _draw_lines(draw: Any, geometry: Any, fill: Any, width: int) -> int:
    count = 0
    for line in _iter_lines(geometry):
        points = _integer_points(line.coords)
        if len(points) >= 2:
            draw.line(points, fill=fill, width=width, joint="curve")
            count += 1
    return count


def _theatre_boundary(lon_min: float, lat_min: float, lon_max: float, lat_max: float, samples: int = 512) -> tuple[Any, Any]:
    import numpy as np
    bottom_lon = np.linspace(lon_min, lon_max, samples, endpoint=False)
    right_lat = np.linspace(lat_min, lat_max, samples, endpoint=False)
    top_lon = np.linspace(lon_max, lon_min, samples, endpoint=False)
    left_lat = np.linspace(lat_max, lat_min, samples, endpoint=False)
    lons = np.concatenate([
        bottom_lon,
        np.full(samples, lon_max),
        top_lon,
        np.full(samples, lon_min),
    ])
    lats = np.concatenate([
        np.full(samples, lat_min),
        right_lat,
        np.full(samples, lat_max),
        left_lat,
    ])
    return lons, lats


def _pixel_transformer(min_x: float, min_y: float, max_x: float, max_y: float, width: int, height: int):
    import numpy as np
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    def to_pixels(x: Any, y: Any, z: Any = None) -> tuple[Any, Any]:
        x_arr = np.asarray(x, dtype=np.float64)
        y_arr = np.asarray(y, dtype=np.float64)
        return ((x_arr - min_x) / span_x * float(width - 1), (max_y - y_arr) / span_y * float(height - 1))
    return to_pixels


def _population(properties: Mapping[str, Any]) -> float:
    for key in ("POP_MAX", "POP_MIN", "MAX_POP10", "POP1950"):
        try:
            value = float(properties.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0.0


def apply_city_density(density: Any, x: float, y: float, population: float, policy: Mapping[str, Any]) -> None:
    import numpy as np
    height, width = density.shape
    scaled = float(np.clip((math.log10(max(population, 1000.0)) - 3.0) / 4.0, 0.0, 1.0))
    radius = int(round(policy["city_radius_min"] + scaled * (policy["city_radius_max"] - policy["city_radius_min"])))
    depth = float(policy["city_depth_min"] + scaled * (policy["city_depth_max"] - policy["city_depth_min"]))
    sigma = max(radius / 2.4, 1.0)
    center_x, center_y = int(round(x)), int(round(y))
    x0, x1 = max(center_x - radius, 0), min(center_x + radius + 1, width)
    y0, y1 = max(center_y - radius, 0), min(center_y + radius + 1, height)
    if x0 >= x1 or y0 >= y1:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    influence = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * sigma * sigma))
    density[y0:y1, x0:x1] = np.minimum(density[y0:y1, x0:x1], float(policy["baseline"]) - depth * influence)


def apply_corridor_density(density: Any, mask: Any, *, baseline: float, sigma: float, depth: float) -> None:
    import numpy as np
    if not bool(np.any(mask)):
        raise Gate3Error("density corridor mask is empty")
    try:
        from scipy.ndimage import distance_transform_edt
    except ModuleNotFoundError as exc:
        if int(mask.size) > 65536:
            raise Gate3Error("scipy is required for full-scale Gate 3 corridor density") from exc
        points = np.argwhere(mask)
        yy, xx = np.indices(mask.shape)
        distance_squared = np.full(mask.shape, np.inf, dtype=np.float64)
        for py, px in points:
            distance_squared = np.minimum(distance_squared, (yy - int(py)) ** 2 + (xx - int(px)) ** 2)
        distance = np.sqrt(distance_squared)
    else:
        distance = distance_transform_edt(~mask)
    influence = np.exp(-(distance**2) / (2.0 * sigma * sigma))
    density[:] = np.minimum(density, baseline - depth * influence)


def _coast_mask(land: Any, ocean: Any) -> Any:
    import numpy as np
    mask = np.zeros_like(land, dtype=bool)
    mask[1:, :] |= land[1:, :] & ocean[:-1, :]
    mask[:-1, :] |= land[:-1, :] & ocean[1:, :]
    mask[:, 1:] |= land[:, 1:] & ocean[:, :-1]
    mask[:, :-1] |= land[:, :-1] & ocean[:, 1:]
    return mask


def _theatre_edge_mask(inside_mask: Any) -> Any:
    import numpy as np
    edge = np.zeros_like(inside_mask, dtype=bool)
    edge[0, :] |= inside_mask[0, :]
    edge[-1, :] |= inside_mask[-1, :]
    edge[:, 0] |= inside_mask[:, 0]
    edge[:, -1] |= inside_mask[:, -1]
    edge[1:, :] |= inside_mask[1:, :] & ~inside_mask[:-1, :]
    edge[:-1, :] |= inside_mask[:-1, :] & ~inside_mask[1:, :]
    edge[:, 1:] |= inside_mask[:, 1:] & ~inside_mask[:, :-1]
    edge[:, :-1] |= inside_mask[:, :-1] & ~inside_mask[:, 1:]
    return edge


def _normalize_ocean_components(
    raw_ocean_mask: Any,
    inside_mask: Any,
    ocean_anchor_pixels: Mapping[str, tuple[int, int]],
    *,
    maximum_components: int,
) -> tuple[Any, dict[str, Any]]:
    import numpy as np
    from scipy.ndimage import label as connected_components

    structure = np.asarray([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8)
    labels, raw_count = connected_components(raw_ocean_mask, structure=structure)
    raw_count = int(raw_count)
    if raw_count <= 0:
        raise Gate3Error("locked theatre contains no candidate ocean components")
    edge_mask = _theatre_edge_mask(inside_mask)
    anchors_by_label: dict[int, list[str]] = {}
    for name, (px, py) in sorted(ocean_anchor_pixels.items()):
        if not (0 <= py < raw_ocean_mask.shape[0] and 0 <= px < raw_ocean_mask.shape[1]):
            raise Gate3Error(f"locked ocean anchor is outside the raster: {name}")
        component = int(labels[py, px])
        if component <= 0:
            raise Gate3Error(f"locked ocean anchor is not in candidate ocean: {name}")
        anchors_by_label.setdefault(component, []).append(name)

    retained_labels: list[int] = []
    records: list[dict[str, Any]] = []
    retained_by_boundary = 0
    retained_by_anchor = 0
    for component in range(1, raw_count + 1):
        component_mask = labels == component
        pixel_count = int(component_mask.sum())
        touches_boundary = bool(np.any(component_mask & edge_mask))
        anchor_names = sorted(anchors_by_label.get(component, []))
        retained = touches_boundary or bool(anchor_names)
        if retained:
            retained_labels.append(component)
            retained_by_boundary += int(touches_boundary)
            retained_by_anchor += int(bool(anchor_names))
        records.append({
            "component": component,
            "pixel_count": pixel_count,
            "touches_projected_crop_boundary": touches_boundary,
            "locked_ocean_anchor_names": anchor_names,
            "retained": retained,
        })
    if len(retained_labels) > maximum_components:
        raise Gate3Error(
            "retained ocean component count exceeds locked ocean territories: "
            f"{len(retained_labels)} > {maximum_components}"
        )
    retained_mask = np.isin(labels, np.asarray(retained_labels, dtype=labels.dtype))
    reclassified_mask = raw_ocean_mask & ~retained_mask
    retained_anchor_names = sorted(name for names in anchors_by_label.values() for name in names)
    if retained_anchor_names != sorted(ocean_anchor_pixels):
        raise Gate3Error("not every locked ocean anchor was retained")
    authority = {
        "policy": "crop_boundary_or_locked_ocean_anchor",
        "unanchored_complement_policy": "reclassify_as_land",
        "connectivity": 4,
        "raw_component_count": raw_count,
        "retained_component_count": len(retained_labels),
        "reclassified_component_count": raw_count - len(retained_labels),
        "raw_pixel_count": int(raw_ocean_mask.sum()),
        "retained_pixel_count": int(retained_mask.sum()),
        "reclassified_pixel_count": int(reclassified_mask.sum()),
        "retained_by_crop_boundary_count": retained_by_boundary,
        "retained_by_locked_ocean_anchor_count": retained_by_anchor,
        "retained_anchor_names": retained_anchor_names,
        "components": records,
    }
    return retained_mask, authority


def _projected_geometry(raw_geometry: Mapping[str, Any], lon_lat_clip: Any, projection: Any, to_pixels: Any) -> Any | None:
    from shapely.geometry import shape
    from shapely.ops import transform
    geometry = shape(raw_geometry)
    if geometry.is_empty or not geometry.intersects(lon_lat_clip):
        return None
    clipped = geometry.intersection(lon_lat_clip)
    if clipped.is_empty:
        return None
    projected = transform(projection.transform, clipped)
    return None if projected.is_empty else transform(to_pixels, projected)


def build_inputs(config_path: Path, natural_earth_root: Path, output: Path) -> dict[str, Any]:
    import numpy as np
    from PIL import Image, ImageDraw
    from pyproj import CRS, Transformer
    from scipy.ndimage import label as connected_components
    from shapely.geometry import Polygon, box, shape
    from shapely.ops import transform

    config, config_sha, config_raw = load_config(config_path)
    if output.exists():
        raise Gate3Error(f"Gate 3 input output already exists: {output}")
    output.mkdir(parents=True)
    sources = capture_sources(config, natural_earth_root)
    lon_min, lat_min, lon_max, lat_max = [float(value) for value in config["theatre"]["lon_lat_bounds"]]
    width, height = int(config["raster"]["width"]), int(config["raster"]["height"])
    projection = Transformer.from_crs(CRS.from_string(config["projection"]["source_crs"]), CRS.from_proj4(config["projection"]["proj"]), always_xy=True)
    boundary_lons, boundary_lats = _theatre_boundary(lon_min, lat_min, lon_max, lat_max)
    projected_x, projected_y = projection.transform(boundary_lons, boundary_lats)
    projected_bounds = (float(np.min(projected_x)), float(np.min(projected_y)), float(np.max(projected_x)), float(np.max(projected_y)))
    to_pixels = _pixel_transformer(*projected_bounds, width, height)
    pixel_x, pixel_y = to_pixels(projected_x, projected_y)
    projected_theatre_polygon = Polygon(list(zip(pixel_x.tolist(), pixel_y.tolist())))
    if not projected_theatre_polygon.is_valid or projected_theatre_polygon.area <= 0:
        raise Gate3Error("projected theatre polygon is invalid")
    lon_lat_clip = box(lon_min, lat_min, lon_max, lat_max)

    theatre_mask_image = Image.new("L", (width, height), 0)
    theatre_mask_draw = ImageDraw.Draw(theatre_mask_image)
    theatre_mask_draw.polygon(_integer_points(projected_theatre_polygon.exterior.coords), fill=255)
    inside_mask = np.asarray(theatre_mask_image, dtype=np.uint8) == 255
    if not bool(np.any(inside_mask)) or bool(np.all(inside_mask)):
        raise Gate3Error("projected theatre mask must include both inside and outside pixels")

    land_image = Image.new("RGB", (width, height), OCEAN_COLOR)
    land_draw = ImageDraw.Draw(land_image)
    boundary_image = Image.new("RGB", (width, height), OUTSIDE_COLOR)
    boundary_draw = ImageDraw.Draw(boundary_image)
    boundary_draw.polygon(_integer_points(projected_theatre_polygon.exterior.coords), fill=BOUNDARY_BACKGROUND)
    boundary_mask_image = Image.new("1", (width, height), 0)
    boundary_mask_draw = ImageDraw.Draw(boundary_mask_image)
    river_mask_image = Image.new("1", (width, height), 0)
    river_mask_draw = ImageDraw.Draw(river_mask_image)
    feature_counts = {"land_features": 0, "land_polygon_parts": 0, "lake_features": 0, "lake_polygon_parts": 0, "boundary_features": 0, "boundary_line_parts": 0, "river_features": 0, "river_line_parts": 0, "populated_places": 0}

    for feature in _load_json_bytes(sources["land"]["data"], "Natural Earth land").get("features", []):
        pixel_geometry = _projected_geometry(feature["geometry"], lon_lat_clip, projection, to_pixels)
        if pixel_geometry is None:
            continue
        feature_counts["land_features"] += 1
        for polygon in _iter_polygons(pixel_geometry):
            _draw_land_polygon(land_draw, polygon)
            feature_counts["land_polygon_parts"] += 1

    for feature in _load_json_bytes(sources["lakes"]["data"], "Natural Earth lakes").get("features", []):
        pixel_geometry = _projected_geometry(feature["geometry"], lon_lat_clip, projection, to_pixels)
        if pixel_geometry is None:
            continue
        feature_counts["lake_features"] += 1
        for polygon in _iter_polygons(pixel_geometry):
            _draw_lake_polygon(land_draw, polygon)
            feature_counts["lake_polygon_parts"] += 1

    boundary_width = max(1, int(round(width / 1024.0)))
    for feature in _load_json_bytes(sources["national_boundaries"]["data"], "Natural Earth boundaries").get("features", []):
        pixel_geometry = _projected_geometry(feature["geometry"], lon_lat_clip, projection, to_pixels)
        if pixel_geometry is None:
            continue
        feature_counts["boundary_features"] += 1
        feature_counts["boundary_line_parts"] += _draw_lines(boundary_draw, pixel_geometry, BOUNDARY_COLOR, boundary_width)
        _draw_lines(boundary_mask_draw, pixel_geometry, 1, boundary_width)

    river_width = max(1, int(round(width / 1536.0)))
    for feature in _load_json_bytes(sources["rivers"]["data"], "Natural Earth rivers").get("features", []):
        pixel_geometry = _projected_geometry(feature["geometry"], lon_lat_clip, projection, to_pixels)
        if pixel_geometry is None:
            continue
        feature_counts["river_features"] += 1
        feature_counts["river_line_parts"] += _draw_lines(river_mask_draw, pixel_geometry, 1, river_width)

    land_array = np.asarray(land_image, dtype=np.uint8).copy()
    land_array[~inside_mask] = np.asarray(OCEAN_COLOR, dtype=np.uint8)
    land_image = Image.fromarray(land_array, mode="RGB")
    boundary_array = np.asarray(boundary_image, dtype=np.uint8).copy()
    boundary_array[~inside_mask] = np.asarray(OUTSIDE_COLOR, dtype=np.uint8)
    boundary_image = Image.fromarray(boundary_array, mode="RGB")

    raw_ocean_mask = inside_mask & np.all(land_array == np.asarray(OCEAN_COLOR, dtype=np.uint8), axis=2)
    lake_mask = inside_mask & np.all(land_array == np.asarray(LAKE_COLOR, dtype=np.uint8), axis=2)
    anchor_pixels: dict[str, tuple[int, int]] = {}
    for anchor in config["theatre"]["anchors"]:
        source_point = shape({"type": "Point", "coordinates": [anchor["longitude"], anchor["latitude"]]})
        pixel_point = transform(to_pixels, transform(projection.transform, source_point))
        px = min(max(int(round(float(pixel_point.x))), 0), width - 1)
        py = min(max(int(round(float(pixel_point.y))), 0), height - 1)
        if not inside_mask[py, px]:
            raise Gate3Error(f"geography anchor {anchor['name']} is outside the projected theatre mask")
        anchor_pixels[str(anchor["name"])] = (px, py)
    ocean_anchor_pixels = {
        str(anchor["name"]): anchor_pixels[str(anchor["name"])]
        for anchor in config["theatre"]["anchors"]
        if anchor["expected"] == "ocean"
    }
    ocean_mask, ocean_component_authority = _normalize_ocean_components(
        raw_ocean_mask,
        inside_mask,
        ocean_anchor_pixels,
        maximum_components=int(config["counts"]["ocean_territories"]),
    )
    reclassified_ocean = raw_ocean_mask & ~ocean_mask
    land_array[reclassified_ocean] = np.asarray(LAND_COLOR, dtype=np.uint8)
    land_image = Image.fromarray(land_array, mode="RGB")
    land_mask = inside_mask & ~ocean_mask & ~lake_mask
    boundary_mask = np.asarray(boundary_mask_image, dtype=bool) & inside_mask
    river_mask = np.asarray(river_mask_image, dtype=bool) & land_mask
    coast_mask = _coast_mask(land_mask, ocean_mask) & inside_mask

    density_policy = config["density"]
    density = np.full((height, width), float(density_policy["baseline"]), dtype=np.float64)
    for feature in _load_json_bytes(sources["populated_places"]["data"], "Natural Earth populated places").get("features", []):
        raw_geometry = feature.get("geometry")
        if not raw_geometry:
            continue
        geometry = shape(raw_geometry)
        if geometry.is_empty or geometry.geom_type != "Point" or not lon_lat_clip.covers(geometry):
            continue
        pixel_point = transform(to_pixels, transform(projection.transform, geometry))
        px, py = float(pixel_point.x), float(pixel_point.y)
        ix, iy = int(round(px)), int(round(py))
        if not (0 <= ix < width and 0 <= iy < height and inside_mask[iy, ix]):
            continue
        apply_city_density(density, px, py, _population(feature.get("properties", {})), density_policy)
        feature_counts["populated_places"] += 1
    for mask, sigma_key, depth_key in ((boundary_mask, "boundary_sigma", "boundary_depth"), (river_mask, "river_sigma", "river_depth"), (coast_mask, "coast_sigma", "coast_depth")):
        apply_corridor_density(density, mask, baseline=float(density_policy["baseline"]), sigma=float(density_policy[sigma_key]), depth=float(density_policy[depth_key]))
    density[~inside_mask] = 255.0
    density_image = Image.fromarray(np.clip(np.rint(density), 0, 255).astype(np.uint8), mode="L")

    terrain = np.zeros((height, width, 3), dtype=np.uint8)
    terrain[land_mask] = TERRAIN_COLORS[config["terrain"]["land"]]
    terrain[ocean_mask] = TERRAIN_COLORS[config["terrain"]["ocean"]]
    terrain[lake_mask] = TERRAIN_COLORS[config["terrain"]["lake"]]
    terrain_image = Image.fromarray(terrain, mode="RGB")

    paths = {
        "land.png": output / "land.png",
        "boundary.png": output / "boundary.png",
        "density.png": output / "density.png",
        "terrain.png": output / "terrain.png",
        "theatre_mask.png": output / "theatre_mask.png",
    }
    land_image.save(paths["land.png"], optimize=False, compress_level=9)
    boundary_image.save(paths["boundary.png"], optimize=False, compress_level=9)
    density_image.save(paths["density.png"], optimize=False, compress_level=9)
    terrain_image.save(paths["terrain.png"], optimize=False, compress_level=9)
    theatre_mask_image.save(paths["theatre_mask.png"], optimize=False, compress_level=9)

    _, land_component_count = connected_components(land_mask)
    _, ocean_component_count = connected_components(ocean_mask)
    _, lake_component_count = connected_components(lake_mask)
    geography_anchors: list[dict[str, Any]] = []
    for anchor in config["theatre"]["anchors"]:
        px, py = anchor_pixels[str(anchor["name"])]
        actual_class = "land" if bool(land_mask[py, px]) else "lake" if bool(lake_mask[py, px]) else "ocean"
        if actual_class != anchor["expected"]:
            raise Gate3Error(f"geography anchor {anchor['name']} expected {anchor['expected']}, got {actual_class} at pixel ({px}, {py})")
        geography_anchors.append({**anchor, "pixel": [px, py], "actual": actual_class, "passed": True})

    source_manifest = {role: {"path": sources[role]["relative_path"], "git_blob_sha1": sources[role]["git_blob_sha1"], "sha256": sources[role]["sha256"], "size_bytes": sources[role]["size_bytes"], "authority": "git_blob_bytes"} for role in SOURCE_ROLES}
    outputs = {name: {"sha256": sha256_file(path), "size_bytes": path.stat().st_size} for name, path in sorted(paths.items())}
    input_manifest = {
        "schema": INPUT_SCHEMA,
        "schema_version": INPUT_SCHEMA_VERSION,
        "status": "experimental_debug_only",
        "candidate_id": config["candidate_id"],
        "gate3_config_sha256": config_sha,
        "source": {"repository": config["source"]["repository"], "ref": config["source"]["ref"], "commit": config["source"]["commit"], "license": config["source"]["license"], "terms_url": config["source"]["terms_url"], "files": source_manifest},
        "projection": config["projection"],
        "lon_lat_bounds": [lon_min, lat_min, lon_max, lat_max],
        "projected_bounds": [round(value, 6) for value in projected_bounds],
        "dimensions": {"width": width, "height": height},
        "theatre_mask": {"sha256": outputs["theatre_mask.png"]["sha256"], "inside_pixels": int(inside_mask.sum()), "outside_pixels": int((~inside_mask).sum()), "outside_boundary_color": list(OUTSIDE_COLOR)},
        "feature_counts": feature_counts,
        "geography_anchors": geography_anchors,
        "pixel_counts": {"land": int(land_mask.sum()), "ocean": int(ocean_mask.sum()), "lake": int(lake_mask.sum()), "outside": int((~inside_mask).sum()), "boundary": int(boundary_mask.sum()), "river": int(river_mask.sum()), "coast": int(coast_mask.sum())},
        "component_counts": {"land": int(land_component_count), "ocean": int(ocean_component_count), "lake": int(lake_component_count)},
        "ocean_component_authority": ocean_component_authority,
        "density": {"policy": density_policy, "minimum": int(np.min(np.asarray(density_image)[inside_mask])), "maximum": int(np.max(np.asarray(density_image)[inside_mask])), "mean": round(float(np.mean(np.asarray(density_image)[inside_mask])), 6)},
        "terrain": config["terrain"],
        "outputs": outputs,
        "isolation": config["isolation"],
    }
    recipe = {
        "schema": "gates-of-codex.opengs-recipe",
        "schema_version": 1,
        "recipe_id": config["candidate_id"],
        "root_seed": config["generator"]["root_seed"],
        "inputs": {"land": {"path": "land.png", "sha256": outputs["land.png"]["sha256"]}, "boundary": {"path": "boundary.png", "sha256": outputs["boundary.png"]["sha256"]}, "density": {"path": "density.png", "sha256": outputs["density.png"]["sha256"]}, "terrain": {"path": "terrain.png", "sha256": outputs["terrain.png"]["sha256"]}},
        "counts": {key: config["counts"][key] for key in ("land_territories", "ocean_territories", "land_provinces", "ocean_provinces")},
        "options": {key: config["generator"][key] for key in ("lloyd_iterations", "density_strength", "exclude_ocean_density", "jagged_land", "jagged_ocean", "jagged_amplitude")},
    }
    gate2_config = {"schema": "gates-of-codex.opengs-gate2-config", "schema_version": 1, "map_id": config["candidate_id"], "id_prefix": config["gate2"]["id_prefix"], "minimum_shared_edge_pixels": config["gate2"]["minimum_shared_edge_pixels"], "authored_boundary_pairs": config["gate2"]["authored_boundary_pairs"], "suppressed_segments": config["gate2"]["suppressed_segments"]}
    (output / "gate3_config.json").write_bytes(config_raw)
    _write_json(output / "gate3_input_manifest.json", input_manifest)
    _write_json(output / "gate1_recipe.json", recipe)
    _write_json(output / "gate2_config.json", gate2_config)
    return input_manifest


__all__ = [name for name in globals() if not name.startswith("__")]
