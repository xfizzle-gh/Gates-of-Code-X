"""Shapely geometry oracle for Earth3 mask-overlap validation.

Production crop code may use the stdlib path in ``geometry.py``. This module
is the independent oracle used by tests and audit tooling. Shapely is an
optional dependency (``pip install 'gates-of-codex[earth3]'``).
"""

from __future__ import annotations

from typing import Sequence

Point = tuple[float, float]
Ring = tuple[Point, ...]

try:
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from shapely.validation import make_valid

    SHAPELY_AVAILABLE = True
except ImportError:  # pragma: no cover
    SHAPELY_AVAILABLE = False


class ShapelyOracleError(RuntimeError):
    pass


def require_shapely() -> None:
    if not SHAPELY_AVAILABLE:
        raise ShapelyOracleError(
            "Shapely is required for the geometry oracle. "
            "Install with: pip install 'gates-of-codex[earth3]'"
        )


def _as_polygon(ring: Sequence[Point]) -> "Polygon":
    require_shapely()
    coords = list(ring)
    if len(coords) < 3:
        return Polygon()
    if coords[0] != coords[-1]:
        coords = coords + [coords[0]]
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = make_valid(poly)
    # make_valid may return MultiPolygon/GeometryCollection — take polygonal area union.
    if poly.geom_type == "Polygon":
        return poly
    if poly.geom_type == "MultiPolygon":
        return poly
    if hasattr(poly, "geoms"):
        parts = [g for g in poly.geoms if g.geom_type in {"Polygon", "MultiPolygon"}]
        if not parts:
            return Polygon()
        return unary_union(parts)
    return Polygon()


def mask_union(mask_rings: Sequence[Ring]):
    require_shapely()
    parts = [_as_polygon(ring) for ring in mask_rings]
    return unary_union(parts)


def shapely_overlap_ratio(subject: Sequence[Point], mask_rings: Sequence[Ring]) -> float:
    """Oracle overlap ratio using Shapely boolean intersection."""
    require_shapely()
    poly = _as_polygon(subject)
    area = float(poly.area)
    if area <= 1e-12:
        return 0.0
    mask = mask_union(mask_rings)
    inter = poly.intersection(mask)
    ratio = float(inter.area) / area
    if ratio < 0.0:
        return 0.0
    if ratio > 1.0:
        return 1.0
    return ratio


def compare_overlap_ratios(
    subject: Sequence[Point],
    mask_rings: Sequence[Ring],
    stdlib_ratio: float,
    *,
    abs_tol: float = 1e-3,
) -> dict[str, object]:
    """Compare stdlib ratio against Shapely oracle."""
    oracle = shapely_overlap_ratio(subject, mask_rings)
    delta = abs(float(stdlib_ratio) - oracle)
    return {
        "stdlib_ratio": float(stdlib_ratio),
        "shapely_ratio": oracle,
        "abs_delta": delta,
        "within_tol": delta <= abs_tol,
        "abs_tol": abs_tol,
    }
