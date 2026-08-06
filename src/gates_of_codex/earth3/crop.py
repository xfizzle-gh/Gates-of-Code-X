"""Authored Earth3 theatre crop candidates (complete-polygon inclusion only)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .geometry import (
    Ring,
    bounds_intersect,
    overlap_ratio,
    point_in_any_ring,
    ring_bounds,
    shoelace_area,
)
from .model import Earth3Dataset, Earth3Province


@dataclass(frozen=True, slots=True)
class CropRect:
    """Axis-aligned broad query bound in Earth3 map pixels (origin top-left)."""

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

    def as_ring(self) -> Ring:
        return (
            (self.min_x, self.min_y),
            (self.max_x, self.min_y),
            (self.max_x, self.max_y),
            (self.min_x, self.max_y),
        )


@dataclass(frozen=True, slots=True)
class CropCandidate:
    id: str
    title: str
    description: str
    rect: CropRect
    required_include_ids: tuple[int, ...] = ()
    explicit_exclude_ids: tuple[int, ...] = ()
    mask_rings: tuple[Ring, ...] = ()
    inclusion_threshold: float = 0.35
    review_band_low: float = 0.15
    review_band_high: float = 0.50
    selection_mode: str = "rect_centroid"  # or "mask_overlap"
    notes: str = ""

    @property
    def uses_mask(self) -> bool:
        return self.selection_mode == "mask_overlap" and bool(self.mask_rings)

    def effective_mask_rings(self) -> tuple[Ring, ...]:
        if self.mask_rings:
            return self.mask_rings
        return (self.rect.as_ring(),)


@dataclass(slots=True)
class CropResult:
    candidate: CropCandidate
    included_ids: list[int] = field(default_factory=list)
    inclusion_reason: dict[int, str] = field(default_factory=dict)
    overlap_ratios: dict[int, float] = field(default_factory=dict)
    threshold_review_ids: list[int] = field(default_factory=list)
    excluded_boundary_ids: list[int] = field(default_factory=list)
    missing_required_ids: list[int] = field(default_factory=list)
    land_count: int = 0
    water_count: int = 0
    vertex_count: int = 0
    adjacency_edges: int = 0
    disconnected_land_components: int = 0
    label_outside_polygon: list[int] = field(default_factory=list)
    source_bounds: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    region_coverage: dict[str, dict[str, object]] = field(default_factory=dict)
    far_north_excluded_sample: list[int] = field(default_factory=list)
    export_rect: CropRect | None = None

    @property
    def province_count(self) -> int:
        return len(self.included_ids)


# City-name anchors used only for crop audit coverage (not political ownership).
_REGION_CITY_ANCHORS: dict[str, tuple[str, ...]] = {
    "Iceland": ("Reykjav", "Akureyri"),
    "Britain_Ireland": ("London", "Dublin", "Edinburgh", "Cardiff"),
    "Iberia": ("Madrid", "Lisbon", "Barcelona"),
    "France_Benelux_Germany": ("Paris", "Brussels", "Amsterdam", "Berlin", "Munich"),
    "Italy": ("Rome", "Milan", "Naples", "Palermo"),
    "Balkans_Greece": ("Athens", "Belgrade", "Sofia", "Bucharest", "Zagreb"),
    "Ukraine_Crimea_Donbas": (
        "Kyiv",
        "Kherson",
        "Zaporizhzhia",
        "Donetsk",
        "Luhansk",
        "Sevastopol",
        "Simferopol",
        "Odesa",
    ),
    "Rostov_approach": ("Rostov on Don",),
    "Turkey": ("Istanbul", "Ankara", "Izmir"),
    "Caucasus_edge": ("Tbilisi", "Baku", "Yerevan"),
    "North_Africa_coast": ("Tunis", "Algiers", "Cairo", "Tripoli"),
    "Baltic": ("Stockholm", "Helsinki", "Riga", "Tallinn", "Vilnius"),
    "Far_north_should_exclude": ("Murmansk", "Arkhangelsk"),
}


def load_crop_candidates(path: str | Path) -> list[CropCandidate]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "candidates" not in payload:
        raise ValueError("crop config must contain candidates array")
    defaults = payload.get("mask_defaults", {})
    default_threshold = float(defaults.get("inclusion_threshold", 0.35))
    default_low = float(defaults.get("review_band_low", 0.15))
    default_high = float(defaults.get("review_band_high", 0.50))

    out: list[CropCandidate] = []
    for row in payload["candidates"]:
        rect = row["rect"]
        rings_raw = row.get("mask_rings") or []
        mask_rings: list[Ring] = []
        for ring in rings_raw:
            pts = tuple((float(p[0]), float(p[1])) for p in ring)
            if len(pts) < 3:
                raise ValueError(f"mask ring too small in candidate {row.get('id')}")
            mask_rings.append(pts)
        mode = str(row.get("selection_mode", "rect_centroid"))
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
                mask_rings=tuple(mask_rings),
                inclusion_threshold=float(row.get("inclusion_threshold", default_threshold)),
                review_band_low=float(row.get("review_band_low", default_low)),
                review_band_high=float(row.get("review_band_high", default_high)),
                selection_mode=mode,
                notes=str(row.get("notes", "")),
            )
        )
    return out


def apply_crop(dataset: Earth3Dataset, candidate: CropCandidate) -> CropResult:
    """Include whole polygons only. Never clip province rings."""
    if candidate.uses_mask:
        return _apply_mask_overlap_crop(dataset, candidate)
    return _apply_rect_centroid_crop(dataset, candidate)


def _apply_rect_centroid_crop(dataset: Earth3Dataset, candidate: CropCandidate) -> CropResult:
    exclude = set(candidate.explicit_exclude_ids)
    required = set(candidate.required_include_ids)
    included: dict[int, str] = {}
    boundary_touched: list[int] = []
    ratios: dict[int, float] = {}

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
            ratios[pid] = 1.0
            continue
        if intersects and centroid_in:
            included[pid] = "centroid_inside_boundary_spill_allowed"
            boundary_touched.append(pid)
            ratios[pid] = 0.5
            continue
        if intersects and not fully:
            boundary_touched.append(pid)

    return _finalize_result(
        dataset,
        candidate,
        included=included,
        ratios=ratios,
        boundary_touched=boundary_touched,
        threshold_review=[],
        required=required,
        exclude=exclude,
    )


def _apply_mask_overlap_crop(dataset: Earth3Dataset, candidate: CropCandidate) -> CropResult:
    """Mask-overlap inclusion with documented threshold; whole polygons only."""
    exclude = set(candidate.explicit_exclude_ids)
    required = set(candidate.required_include_ids)
    mask = candidate.effective_mask_rings()
    mask_bounds = _union_ring_bounds(mask)
    query = candidate.rect
    # Broad phase: AABB of query rect ∩ mask bounds.
    broad = CropRect(
        min_x=max(query.min_x, mask_bounds[0]),
        min_y=max(query.min_y, mask_bounds[1]),
        max_x=min(query.max_x, mask_bounds[2]),
        max_y=min(query.max_y, mask_bounds[3]),
    )

    included: dict[int, str] = {}
    ratios: dict[int, float] = {}
    threshold_review: list[int] = []
    boundary_touched: list[int] = []
    thr = candidate.inclusion_threshold
    lo = candidate.review_band_low
    hi = candidate.review_band_high

    for pid in sorted(dataset.provinces):
        province = dataset.provinces[pid]
        if pid in exclude:
            continue
        if pid in required:
            included[pid] = "required_include"
            # Still compute ratio for audit when cheap enough.
            if broad.intersects_bounds(province.bounds):
                ratios[pid] = round(overlap_ratio(province.ring, mask), 6)
            continue

        bounds = province.bounds
        if not broad.intersects_bounds(bounds):
            continue
        if not any(bounds_intersect(bounds, ring_bounds(ring)) for ring in mask):
            continue

        # Fast accept: all vertices inside mask → ratio 1.
        if all(point_in_any_ring(x, y, mask) for x, y in province.ring):
            ratio = 1.0
        else:
            ratio = overlap_ratio(province.ring, mask)
        ratios[pid] = round(ratio, 6)

        if lo <= ratio <= hi:
            threshold_review.append(pid)

        if ratio + 1e-12 >= thr:
            if ratio >= 0.999:
                included[pid] = "mask_overlap_full"
            else:
                included[pid] = "mask_overlap_threshold"
                boundary_touched.append(pid)
        elif ratio > 1e-9:
            boundary_touched.append(pid)

    return _finalize_result(
        dataset,
        candidate,
        included=included,
        ratios=ratios,
        boundary_touched=boundary_touched,
        threshold_review=sorted(set(threshold_review)),
        required=required,
        exclude=exclude,
    )


def _finalize_result(
    dataset: Earth3Dataset,
    candidate: CropCandidate,
    *,
    included: dict[int, str],
    ratios: dict[int, float],
    boundary_touched: list[int],
    threshold_review: list[int],
    required: set[int],
    exclude: set[int],
) -> CropResult:
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
        if not _point_in_ring_local(
            dataset.provinces[pid].label_x,
            dataset.provinces[pid].label_y,
            dataset.provinces[pid].ring,
        )
    ]

    components = _land_components(dataset, included_ids)
    source_bounds = _union_bounds([dataset.provinces[pid] for pid in included_ids])
    region_coverage = _region_coverage(dataset, included_set)

    # Far-north land excluded relative to mask/query northern fringe.
    north_y = candidate.rect.min_y + (candidate.rect.max_y - candidate.rect.min_y) * 0.22
    far_north = [
        pid
        for pid, province in dataset.provinces.items()
        if (not province.is_water)
        and province.centroid[1] < north_y
        and candidate.rect.min_x <= province.centroid[0] <= candidate.rect.max_x
        and pid not in included_set
    ]

    export_rect = None
    if included_ids:
        min_x, min_y, max_x, max_y = source_bounds
        pad = 20.0
        export_rect = CropRect(min_x - pad, min_y - pad, max_x + pad, max_y + pad)

    return CropResult(
        candidate=candidate,
        included_ids=included_ids,
        inclusion_reason=included,
        overlap_ratios=ratios,
        threshold_review_ids=threshold_review,
        excluded_boundary_ids=sorted(set(boundary_touched) - included_set),
        missing_required_ids=missing_required,
        land_count=land_count,
        water_count=water_count,
        vertex_count=vertex_count,
        adjacency_edges=edge_count,
        disconnected_land_components=components,
        label_outside_polygon=label_outside,
        source_bounds=source_bounds,
        region_coverage=region_coverage,
        far_north_excluded_sample=sorted(far_north)[:40],
        export_rect=export_rect,
    )


def _union_ring_bounds(rings: tuple[Ring, ...]) -> tuple[float, float, float, float]:
    bounds = [ring_bounds(ring) for ring in rings]
    return (
        min(b[0] for b in bounds),
        min(b[1] for b in bounds),
        max(b[2] for b in bounds),
        max(b[3] for b in bounds),
    )


def _region_coverage(
    dataset: Earth3Dataset, included: set[int]
) -> dict[str, dict[str, object]]:
    """Map required theatre regions to city-anchor inclusion results."""
    out: dict[str, dict[str, object]] = {}
    cities = list(dataset.cities)
    for region, needles in _REGION_CITY_ANCHORS.items():
        hits: list[dict[str, object]] = []
        for needle in needles:
            needle_l = needle.casefold()
            matched = False
            for city in cities:
                if needle_l not in city.name.casefold():
                    continue
                matched = True
                hits.append(
                    {
                        "city": city.name,
                        "source_province_id": city.province_id,
                        "included": city.province_id in included,
                        "x": city.x,
                        "y": city.y,
                    }
                )
            if not matched:
                hits.append(
                    {
                        "city": needle,
                        "source_province_id": None,
                        "included": False,
                        "missing_from_source_cities": True,
                    }
                )
        if region == "Far_north_should_exclude":
            ok = all(
                not bool(h.get("included"))
                for h in hits
                if "missing_from_source_cities" not in h
            )
        else:
            ok = any(bool(h.get("included")) for h in hits)
        out[region] = {"ok": ok, "anchors": hits}
    return out


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


def _point_in_ring_local(x: float, y: float, ring: tuple[tuple[float, float], ...]) -> bool:
    from .geometry import point_in_ring

    return point_in_ring(x, y, ring)


# Re-export for tests / tooling.
__all__ = [
    "CropCandidate",
    "CropRect",
    "CropResult",
    "apply_crop",
    "load_crop_candidates",
    "shoelace_area",
]
