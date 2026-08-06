"""Deterministic 2D polygon helpers for Earth3 crop masks (stdlib only)."""

from __future__ import annotations

from typing import Sequence

Point = tuple[float, float]
Ring = tuple[Point, ...]


def shoelace_area(ring: Sequence[Point]) -> float:
    n = len(ring)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) * 0.5


def ring_bounds(ring: Sequence[Point]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def bounds_intersect(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def point_in_ring(x: float, y: float, ring: Sequence[Point]) -> bool:
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (xi - x) * (xi - x) + (yi - y) * (yi - y) < 1e-12:
            return True
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) if (yj - yi) != 0 else 1e-15) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def point_in_any_ring(x: float, y: float, rings: Sequence[Ring]) -> bool:
    return any(point_in_ring(x, y, ring) for ring in rings)


def _is_left(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _line_intersection(p1: Point, p2: Point, p3: Point, p4: Point) -> Point | None:
    """Intersection of infinite lines p1-p2 and p3-p4 (Sutherland–Hodgman)."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-15:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def sutherland_hodgman(subject: Sequence[Point], clip: Sequence[Point]) -> list[Point]:
    """Clip subject polygon by convex clip polygon.

    Clip winding must place the interior to the left of each directed edge in
    the coordinate system used (Earth3 y-down with positive-shoelace rings).
    """
    if len(subject) < 3 or len(clip) < 3:
        return []
    # Normalize clip to positive shoelace winding so left-of-edge == interior.
    clip_pts = list(clip)
    area2 = 0.0
    for i in range(len(clip_pts)):
        x1, y1 = clip_pts[i]
        x2, y2 = clip_pts[(i + 1) % len(clip_pts)]
        area2 += x1 * y2 - x2 * y1
    if area2 < 0:
        clip_pts.reverse()

    output = list(subject)
    clip_n = len(clip_pts)
    for i in range(clip_n):
        if len(output) == 0:
            return []
        input_list = output
        output = []
        a = clip_pts[i]
        b = clip_pts[(i + 1) % clip_n]

        def inside(p: Point, aa: Point = a, bb: Point = b) -> bool:
            return _is_left(aa, bb, p) >= -1e-9

        s = input_list[-1]
        for e in input_list:
            if inside(e):
                if not inside(s):
                    hit = _line_intersection(s, e, a, b)
                    if hit is not None:
                        output.append(hit)
                output.append(e)
            elif inside(s):
                hit = _line_intersection(s, e, a, b)
                if hit is not None:
                    output.append(hit)
            s = e
    return output


def ear_clip_triangles(ring: Sequence[Point]) -> list[tuple[Point, Point, Point]]:
    """Ear-clip a simple polygon into triangles. Deterministic vertex order."""
    pts = list(ring)
    if len(pts) < 3:
        return []
    # Remove closing duplicate if present.
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        return []
    # Force CCW for consistent ear tests.
    area2 = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        area2 += x1 * y2 - x2 * y1
    if area2 < 0:
        pts.reverse()

    indices = list(range(len(pts)))
    triangles: list[tuple[Point, Point, Point]] = []
    guard = 0
    max_guard = len(pts) * len(pts) + 8
    while len(indices) > 3 and guard < max_guard:
        guard += 1
        ear_found = False
        n = len(indices)
        for i in range(n):
            i0 = indices[(i - 1) % n]
            i1 = indices[i]
            i2 = indices[(i + 1) % n]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if _is_left(a, b, c) <= 1e-12:
                continue  # not a convex ear at b
            # No other point inside triangle abc.
            inside = False
            for j in indices:
                if j in (i0, i1, i2):
                    continue
                p = pts[j]
                if (
                    _is_left(a, b, p) >= -1e-12
                    and _is_left(b, c, p) >= -1e-12
                    and _is_left(c, a, p) >= -1e-12
                ):
                    inside = True
                    break
            if inside:
                continue
            triangles.append((a, b, c))
            del indices[i]
            ear_found = True
            break
        if not ear_found:
            break
    if len(indices) == 3:
        triangles.append((pts[indices[0]], pts[indices[1]], pts[indices[2]]))
    return triangles


def intersection_area(subject: Sequence[Point], clip_ring: Sequence[Point]) -> float:
    """Area of subject ∩ clip_ring. Clip may be concave (ear-clipped)."""
    if len(subject) < 3 or len(clip_ring) < 3:
        return 0.0
    sb = ring_bounds(subject)
    cb = ring_bounds(clip_ring)
    if not bounds_intersect(sb, cb):
        return 0.0
    total = 0.0
    for tri in ear_clip_triangles(clip_ring):
        clipped = sutherland_hodgman(subject, tri)
        if len(clipped) >= 3:
            total += shoelace_area(clipped)
    return total


def union_intersection_area(subject: Sequence[Point], mask_rings: Sequence[Ring]) -> float:
    """Area of subject ∩ (union of mask rings). Rings must be pairwise non-overlapping."""
    return sum(intersection_area(subject, ring) for ring in mask_rings)


def overlap_ratio(subject: Sequence[Point], mask_rings: Sequence[Ring]) -> float:
    area = shoelace_area(subject)
    if area <= 1e-9:
        return 0.0
    inter = union_intersection_area(subject, mask_rings)
    # Clamp numerical overshoot.
    ratio = inter / area
    if ratio < 0.0:
        return 0.0
    if ratio > 1.0:
        return 1.0
    return ratio
