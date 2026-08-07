"""Deterministic region algorithms adapted for OpenGS Gate 1."""
from __future__ import annotations

import hashlib
import math
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.ndimage import distance_transform_edt, label as ndlabel, zoom as ndzoom
from scipy.spatial import cKDTree

from gate1_common import (
    BOUNDARY_COLOR, DEFAULT_TERRAIN, LAND_TERRAINS, LAKE_TERRAINS,
    NAVAL_TERRAINS, OCEAN_COLOR, LAKE_COLOR, MAX_LLOYD_SAMPLE, Gate1Error, NumberSeries, SeedLedger,
)

def random_seeds(mask: np.ndarray, count: int, seed: int, density: np.ndarray | None, density_strength: float) -> list[tuple[int, int]]:
    coords_yx = np.column_stack(np.where(mask))
    if count <= 0 or len(coords_yx) == 0:
        return []
    n = min(count, len(coords_yx))
    rng = np.random.default_rng(seed)
    if density is None:
        indices = rng.choice(len(coords_yx), size=n, replace=False)
    else:
        weights = 256.0 - density[coords_yx[:, 0], coords_yx[:, 1]].astype(np.float64)
        weights = np.power(weights, density_strength)
        total = float(weights.sum())
        probabilities = weights / total if total > 0 else None
        indices = rng.choice(len(coords_yx), size=n, replace=False, p=probabilities)
    return [(int(coords_yx[i, 1]), int(coords_yx[i, 0])) for i in indices.tolist()]


def round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def lloyd_relaxation(mask: np.ndarray, point_seeds: Sequence[tuple[int, int]], seed: int, iterations: int) -> list[tuple[int, int]]:
    if iterations <= 0 or not point_seeds:
        return list(point_seeds)
    coords_yx = np.column_stack(np.where(mask))
    coords_xy = np.flip(coords_yx, axis=1).astype(np.float64)
    rng = np.random.default_rng(seed)
    if len(coords_xy) > MAX_LLOYD_SAMPLE:
        sample_indices = rng.choice(len(coords_xy), size=MAX_LLOYD_SAMPLE, replace=False)
        sample_xy = coords_xy[np.sort(sample_indices)]
    else:
        sample_xy = coords_xy
    seeds = np.asarray(point_seeds, dtype=np.float64)
    for _ in range(iterations):
        labels = nearest_labels(sample_xy, seeds)
        counts = np.bincount(labels, minlength=len(seeds))
        sx = np.bincount(labels, weights=sample_xy[:, 0], minlength=len(seeds))
        sy = np.bincount(labels, weights=sample_xy[:, 1], minlength=len(seeds))
        for idx in range(len(seeds)):
            if counts[idx] == 0:
                replacement = int(rng.integers(0, len(sample_xy)))
                seeds[idx] = sample_xy[replacement]
                continue
            x = max(0, min(round_half_up(sx[idx] / counts[idx]), mask.shape[1] - 1))
            y = max(0, min(round_half_up(sy[idx] / counts[idx]), mask.shape[0] - 1))
            if mask[y, x]:
                seeds[idx] = (x, y)
    return [(int(x), int(y)) for x, y in seeds]


def nearest_labels(points_xy: np.ndarray, seeds_xy: np.ndarray) -> np.ndarray:
    """Stable nearest-seed query with deterministic sub-pixel tie breaking."""
    stable = seeds_xy.astype(np.float64, copy=True)
    idx = np.arange(len(stable), dtype=np.float64) + 1.0
    stable[:, 0] += idx * 1e-9
    stable[:, 1] += idx * 1e-12
    tree = cKDTree(stable)
    _distance, labels = tree.query(points_xy.astype(np.float64), k=1, workers=1)
    return labels.astype(np.int64, copy=False)


def build_jitter_maps(height: int, width: int, seeds: np.ndarray, seed: int, amplitude_factor: float) -> tuple[np.ndarray | None, np.ndarray | None]:
    if len(seeds) < 2 or amplitude_factor <= 0:
        return None, None
    tree = cKDTree(seeds.astype(np.float64))
    dists, _ = tree.query(seeds.astype(np.float64), k=2, workers=1)
    average = float(dists[:, 1].mean())
    amplitude = average * amplitude_factor
    cell = max(4, int(average / 4))
    coarse_h = (height + cell - 1) // cell + 1
    coarse_w = (width + cell - 1) // cell + 1
    rng = np.random.default_rng(seed)
    jx = ndzoom(rng.uniform(-amplitude, amplitude, (coarse_h, coarse_w)), cell, order=1, prefilter=False)[:height, :width]
    jy = ndzoom(rng.uniform(-amplitude, amplitude, (coarse_h, coarse_w)), cell, order=1, prefilter=False)[:height, :width]
    return jx.astype(np.float64), jy.astype(np.float64)


def remove_enclaves(pmap: np.ndarray, mask: np.ndarray) -> None:
    cleared = np.zeros(pmap.shape, dtype=bool)
    for region_id in sorted(int(v) for v in np.unique(pmap[mask]) if int(v) >= 0):
        region = pmap == region_id
        labeled, count = ndlabel(region)
        if count <= 1:
            continue
        sizes = np.bincount(labeled.ravel())[1:]
        largest = int(np.argmax(sizes)) + 1
        small = region & (labeled != largest)
        pmap[small] = -1
        cleared |= small
    if cleared.any() and (pmap >= 0).any():
        _, indices = distance_transform_edt(pmap < 0, return_indices=True)
        ny, nx = indices
        pmap[cleared] = pmap[ny[cleared], nx[cleared]]


def assign_regions(mask: np.ndarray, seeds: Sequence[tuple[int, int]], start_index: int, *, jagged: bool, jitter_seed: int, amplitude: float) -> np.ndarray:
    height, width = mask.shape
    pmap = np.full((height, width), -1, dtype=np.int32)
    if not seeds or not mask.any():
        return pmap
    seeds_arr = np.asarray(seeds, dtype=np.float64)
    jitter_x, jitter_y = (None, None)
    if jagged:
        jitter_x, jitter_y = build_jitter_maps(height, width, seeds_arr, jitter_seed, amplitude)
    labeled, component_count = ndlabel(mask)
    seed_components: dict[int, list[int]] = {}
    for idx, (x, y) in enumerate(seeds):
        component = int(labeled[y, x])
        if component > 0:
            seed_components.setdefault(component, []).append(idx)
    for component in range(1, component_count + 1):
        component_mask = labeled == component
        coords_yx = np.column_stack(np.where(component_mask))
        if not len(coords_yx):
            continue
        seed_indices = seed_components.get(component)
        if not seed_indices:
            continue
        points = np.flip(coords_yx, axis=1).astype(np.float64)
        if jitter_x is not None and jitter_y is not None:
            points[:, 0] += jitter_x[coords_yx[:, 0], coords_yx[:, 1]]
            points[:, 1] += jitter_y[coords_yx[:, 0], coords_yx[:, 1]]
        local = seeds_arr[seed_indices]
        local_labels = nearest_labels(points, local)
        global_indices = np.asarray(seed_indices, dtype=np.int32)
        pmap[coords_yx[:, 0], coords_yx[:, 1]] = global_indices[local_labels] + start_index
    unassigned = mask & (pmap < 0)
    if unassigned.any() and (pmap >= 0).any():
        _, indices = distance_transform_edt(pmap < 0, return_indices=True)
        ny, nx = indices
        pmap[unassigned] = pmap[ny[unassigned], nx[unassigned]]
    if jagged:
        remove_enclaves(pmap, mask)
    return pmap


def assign_borders(pmap: np.ndarray, border_mask: np.ndarray) -> None:
    if not (pmap >= 0).any() or not border_mask.any():
        return
    _, indices = distance_transform_edt(pmap < 0, return_indices=True)
    ny, nx = indices
    pmap[border_mask] = pmap[ny[border_mask], nx[border_mask]]


def stable_color(index: int, province_type: str, used: set[tuple[int, int, int]]) -> tuple[int, int, int]:
    counter = 0
    while True:
        digest = hashlib.sha256(f"gate1-color\0{province_type}\0{index}\0{counter}".encode()).digest()
        if province_type == "ocean":
            color = (digest[0] % 60, digest[1] % 80, 100 + digest[2] % 80)
        elif province_type == "lake":
            color = (digest[0] % 80, 80 + digest[1] % 100, 100 + digest[2] % 100)
        else:
            color = (digest[0], digest[1], digest[2])
        if color not in used and color not in {OCEAN_COLOR, LAKE_COLOR, BOUNDARY_COLOR}:
            used.add(color)
            return color
        counter += 1


def metadata_for_map(pmap: np.ndarray, seeds: Sequence[tuple[int, int]], start_index: int, province_type: str, series: NumberSeries, id_key: str, type_key: str, used_colors: set[tuple[int, int, int]]) -> list[dict[str, Any]]:
    valid = pmap >= 0
    ys, xs = np.where(valid)
    shifted = pmap[valid].astype(np.int64) - start_index
    n = len(seeds)
    counts = np.bincount(shifted, minlength=n)
    sum_x = np.bincount(shifted, weights=xs.astype(np.float64), minlength=n)
    sum_y = np.bincount(shifted, weights=ys.astype(np.float64), minlength=n)
    result: list[dict[str, Any]] = []
    for idx in range(n):
        if counts[idx] == 0:
            continue
        global_index = start_index + idx
        r, g, b = stable_color(global_index, province_type, used_colors)
        result.append({
            id_key: series.get_id(),
            type_key: province_type,
            "R": r,
            "G": g,
            "B": b,
            "x": float(sum_x[idx] / counts[idx]),
            "y": float(sum_y[idx] / counts[idx]),
            "_pmap_index": global_index,
        })
    return result


def create_region_map(mask: np.ndarray, border: np.ndarray, count: int, start_index: int, province_type: str, series: NumberSeries, id_key: str, type_key: str, ledger: SeedLedger, seed_prefix: str, *, density: np.ndarray | None, density_strength: float, lloyd_iterations: int, jagged: bool, amplitude: float, used_colors: set[tuple[int, int, int]]) -> tuple[np.ndarray, list[dict[str, Any]], int]:
    if count <= 0 or not mask.any():
        return np.full(mask.shape, -1, dtype=np.int32), [], start_index
    seeds = random_seeds(mask, count, ledger.seed(f"{seed_prefix}.sample"), density, density_strength)
    seeds = lloyd_relaxation(mask, seeds, ledger.seed(f"{seed_prefix}.lloyd"), lloyd_iterations)
    pmap = assign_regions(mask, seeds, start_index, jagged=jagged, jitter_seed=ledger.seed(f"{seed_prefix}.jagged"), amplitude=amplitude)
    metadata = metadata_for_map(pmap, seeds, start_index, province_type, series, id_key, type_key, used_colors)
    assign_borders(pmap, border)
    return pmap, metadata, start_index + len(seeds)


def combine_maps(land_map: np.ndarray, ocean_map: np.ndarray, metadata: Sequence[Mapping[str, Any]], land_mask: np.ndarray, ocean_mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    combined = np.full(land_map.shape, -1, dtype=np.int32)
    combined[(land_map >= 0) & land_mask] = land_map[(land_map >= 0) & land_mask]
    combined[(ocean_map >= 0) & ocean_mask] = ocean_map[(ocean_map >= 0) & ocean_mask]
    missing = combined < 0
    if missing.any() and (combined >= 0).any():
        _, indices = distance_transform_edt(combined < 0, return_indices=True)
        ny, nx = indices
        combined[missing] = combined[ny[missing], nx[missing]]
    max_index = max((int(item["_pmap_index"]) for item in metadata), default=-1)
    lookup = np.zeros((max_index + 1, 3), dtype=np.uint8)
    for item in metadata:
        lookup[int(item["_pmap_index"])] = (item["R"], item["G"], item["B"])
    rgb = np.zeros((*combined.shape, 3), dtype=np.uint8)
    valid = combined >= 0
    rgb[valid] = lookup[combined[valid]]
    return rgb, combined


def largest_remainder(items: Sequence[Mapping[str, Any]], total: int, weights: Sequence[float]) -> list[int]:
    n = len(items)
    if n == 0:
        return []
    if total < n:
        raise Gate1Error(f"cannot allocate {total} regions across {n} territories with minimum one")
    total_weight = float(sum(weights))
    if total_weight <= 0:
        weights = [1.0] * n
        total_weight = float(n)
    exact = [float(w) / total_weight * total for w in weights]
    allocation = [max(1, int(math.floor(value))) for value in exact]
    current = sum(allocation)
    if current < total:
        order = sorted(range(n), key=lambda i: (-(exact[i] - math.floor(exact[i])), int(items[i]["_pmap_index"])))
        for i in order:
            if current == total:
                break
            allocation[i] += 1
            current += 1
    elif current > total:
        order = sorted(range(n), key=lambda i: (exact[i] - math.floor(exact[i]), -allocation[i], int(items[i]["_pmap_index"])))
        while current > total:
            changed = False
            for i in order:
                if allocation[i] > 1:
                    allocation[i] -= 1
                    current -= 1
                    changed = True
                    if current == total:
                        break
            if not changed:
                raise Gate1Error("allocation could not satisfy total")
    return allocation


def terrain_name(pixel: tuple[int, int, int], province_type: str) -> str:
    if province_type == "lake":
        lookup = {value: key for key, value in LAKE_TERRAINS.items()}
    elif province_type == "ocean":
        lookup = {value: key for key, value in NAVAL_TERRAINS.items()}
    else:
        lookup = {value: key for key, value in LAND_TERRAINS.items()}
    return lookup.get(pixel, DEFAULT_TERRAIN[province_type])


