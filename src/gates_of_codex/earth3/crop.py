"""Authored Earth3 theatre crop candidates (complete-polygon inclusion only)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .model import Earth3Dataset, Earth3Province


@dataclass(frozen=True, slots=True)
class CropRect:
    """Axis-aligned crop in Earth3 map pixel coordinates (origin top-left of world canvas)."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def contains_point(self, x: float, y: float) -> bool:
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y

    def intersects_bounds(self, bounds: tuple[float, float, float, float]) -> bool:
        min_x, min_y, max_x, max_y = bounds
        return not (
            max_x < self.min_x
            or min_x > self.max_x
            or max_y < self.min_y
            or min_y > self.max_y
        )

    def fully_contains_bounds(self, bounds: tuple[float, float, float, float]) -> bool:
        min_x, min_y, max_x, max_y = bounds
        return (
            min_x >= self.min_x
            and max_x <= self.max_x
            and min_y >= self.min_y
            and max_y <= self.max_y
        )


@dataclass(frozen=True, slots=True)
class CropCandidate:
    id: str
    title: str
    description: str
    rect: CropRect
    required_include_ids: tuple[int, ...] = ()
    explicit_exclude_ids: tuple[int, ...] = ()
    # Optional secondary inclusion: province centroid must lie in this expanded rect
    # used only when primary rect intersects but does not fully contain (still whole poly).
    notes: str = ""


@dataclass(slots=True)
class CropResult:
    candidate: CropCandidate
    included_ids: list[int] = field(default_factory=list)
    inclusion_reason: dict[int, str] = field(default_factory=dict)
    excluded_boundary_ids: list[int] = field(default_factory=list)
    missing_required_ids: list[int] = field(default_factory=list)
    land_count: int = 0
    water_count: int = 0
    vertex_count: int = 0
    adjacency_edges: int = 0
    disconnected_land_components: int = 0
    label_outside_polygon: list[int] = field(default_factory=list)
    source_bounds: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    @property
    def province_count(self) -> int:
        return len(self.included_ids)


def load_crop_candidates(path: str | Path) -> list[CropCandidate]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "candidates" not in payload:
        raise ValueError("crop config must contain candidates array")
    out: list[CropCandidate] = []
    for row in payload["candidates"]:
        rect = row["rect"]
        out.append(
            CropCandidate(
                id=str(row["id"]),
                title=str(row["title"]),
                description=str(row.get("description", "")),
                rect=CropRect(
                    min_x=float(rect["min_x"]),
                    min_y=float(rect["min_y"]),
                    max_x=float(rect["max_x"]),
                    max_y=float(rect["max_y"]),
                ),
                required_include_ids=tuple(int(v) for v in row.get("required_include_ids", [])),
                explicit_exclude_ids=tuple(int(v) for v in row.get("explicit_exclude_ids", [])),
                notes=str(row.get("notes", "")),
            )
        )
    return out


def apply_crop(dataset: Earth3Dataset, candidate: CropCandidate) -> CropResult:
    """Include whole polygons only. Never clip province rings."""
    exclude = set(candidate.explicit_exclude_ids)
    required = set(candidate.required_include_ids)
    included: dict[int, str] = {}
    boundary_touched: list[int] = []

    for pid, province in dataset.provinces.items():
        if pid in exclude:
            continue
        bounds = province.bounds
        fully = candidate.rect.fully_contains_bounds(bounds)
        intersects = candidate.rect.intersects_bounds(bounds)
        centroid_in = candidate.rect.contains_point(*province.centroid)
        if pid in required:
            included[pid] = "required_include"
            continue
        if fully:
            included[pid] = "fully_inside_rect"
            continue
        if intersects and centroid_in:
            # Whole polygon kept even if it spills slightly outside the rect.
            included[pid] = "centroid_inside_boundary_spill_allowed"
            boundary_touched.append(pid)
            continue
        if intersects and not fully:
            boundary_touched.append(pid)

    # Required IDs missing from dataset.
    missing_required = sorted(pid for pid in required if pid not in dataset.provinces)
    for pid in required:
        if pid in dataset.provinces and pid not in included and pid not in exclude:
            included[pid] = "required_include"

    included_ids = sorted(included)
    land_count = sum(1 for pid in included_ids if not dataset.provinces[pid].is_water)
    water_count = len(included_ids) - land_count
    vertex_count = sum(len(dataset.provinces[pid].ring) for pid in included_ids)

    included_set = set(included_ids)
    edge_count = 0
    for pid in included_ids:
        for nb in dataset.neighbors(pid):
            if nb in included_set and pid < nb:
                edge_count += 1

    label_outside = [
        pid
        for pid in included_ids
        if not _point_in_ring(
            dataset.provinces[pid].label_x,
            dataset.provinces[pid].label_y,
            dataset.provinces[pid].ring,
        )
    ]

    components = _land_components(dataset, included_ids)
    source_bounds = _union_bounds([dataset.provinces[pid] for pid in included_ids])

    return CropResult(
        candidate=candidate,
        included_ids=included_ids,
        inclusion_reason=included,
        excluded_boundary_ids=sorted(set(boundary_touched) - included_set),
        missing_required_ids=missing_required,
        land_count=land_count,
        water_count=water_count,
        vertex_count=vertex_count,
        adjacency_edges=edge_count,
        disconnected_land_components=components,
        label_outside_polygon=label_outside,
        source_bounds=source_bounds,
    )


def _union_bounds(provinces: list[Earth3Province]) -> tuple[float, float, float, float]:
    if not provinces:
        return 0.0, 0.0, 0.0, 0.0
    mins_x = []
    mins_y = []
    maxs_x = []
    maxs_y = []
    for province in provinces:
        min_x, min_y, max_x, max_y = province.bounds
        mins_x.append(min_x)
        mins_y.append(min_y)
        maxs_x.append(max_x)
        maxs_y.append(max_y)
    return min(mins_x), min(mins_y), max(maxs_x), max(maxs_y)


def _land_components(dataset: Earth3Dataset, included_ids: list[int]) -> int:
    land = {pid for pid in included_ids if not dataset.provinces[pid].is_water}
    seen: set[int] = set()
    components = 0
    for start in sorted(land):
        if start in seen:
            continue
        components += 1
        stack = [start]
        seen.add(start)
        while stack:
            pid = stack.pop()
            for nb in dataset.neighbors(pid):
                if nb in land and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
    return components


def _point_in_ring(x: float, y: float, ring: tuple[tuple[float, float], ...]) -> bool:
    # Ray casting; boundary counts as inside.
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (xi - x) ** 2 + (yi - y) ** 2 < 1e-9:
            return True
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside
