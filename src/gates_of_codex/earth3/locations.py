"""Exact required-location checks for the Earth3 launch theatre crop."""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import point_in_ring
from .model import Earth3Dataset


@dataclass(frozen=True, slots=True)
class RequiredLocation:
    key: str
    city_name_exact: str
    source_province_id: int
    must_include: bool
    x: float
    y: float


# Exact city rows from Earth3 cities.json (name + province id + coordinates).
REQUIRED_LOCATIONS: tuple[RequiredLocation, ...] = (
    RequiredLocation("Reykjavik", "Reykjavík", 951, True, 7281.0, 930.0),
    RequiredLocation("Sevastopol", "Sevastopol", 1268, True, 9983.0, 2492.0),
    RequiredLocation("Simferopol", "Simferopol", 6627, True, 10009.0, 2472.0),
    RequiredLocation("Kherson", "Kherson", 1271, True, 9932.0, 2352.0),
    RequiredLocation("Zaporizhzhia", "Zaporizhzhia", 3782, True, 10058.0, 2269.0),
    RequiredLocation("Donetsk", "Donetsk", 12175, True, 10188.0, 2256.0),
    RequiredLocation("Luhansk", "Luhansk", 10869, True, 10261.0, 2216.0),
    RequiredLocation("Rostov_on_Don", "Rostov on Don", 10868, True, 10278.0, 2309.0),
    RequiredLocation("Kyiv", "Kyiv", 3757, True, 9832.0, 2074.0),
    RequiredLocation("Odesa", "Odesa", 3241, True, 9840.0, 2369.0),
    RequiredLocation("Istanbul", "Istanbul", 1116, True, 9757.0, 2733.0),
    RequiredLocation("Ankara", "Ankara", 2207, True, 9945.0, 2804.0),
    RequiredLocation("Tbilisi", "Tbilisi", 10431, True, 10531.0, 2689.0),
    RequiredLocation("Baku", "Baku", 2654, True, 10776.0, 2772.0),
    RequiredLocation("Tunis", "Tunis", 2242, True, 8845.0, 2974.0),
    RequiredLocation("Algiers", "Algiers", 1399, True, 8496.0, 2985.0),
    RequiredLocation("Cairo", "Cairo", 2669, True, 9867.0, 3402.0),
    RequiredLocation("Oslo", "Oslo", 1009, True, 8870.0, 1261.0),
    RequiredLocation("Stockholm", "Stockholm", 1049, True, 9225.0, 1315.0),
    RequiredLocation("Helsinki", "Helsinki", 1461, True, 9560.0, 1240.0),
    RequiredLocation("Murmansk", "Murmansk", 11370, False, 9961.0, 474.0),
    RequiredLocation("Arkhangelsk", "Arkhangelsk", 11764, False, 10325.0, 892.0),
)


def validate_required_locations(
    dataset: Earth3Dataset, included_ids: set[int]
) -> dict[str, object]:
    """Exact province-id and coordinate validation for required theatre points."""
    cities_by_pid_name: dict[tuple[int, str], object] = {}
    for city in dataset.cities:
        cities_by_pid_name[(city.province_id, city.name)] = city

    results: list[dict[str, object]] = []
    failures: list[str] = []
    for loc in REQUIRED_LOCATIONS:
        province = dataset.provinces.get(loc.source_province_id)
        included = loc.source_province_id in included_ids
        point_in_poly = False
        if province is not None:
            point_in_poly = point_in_ring(loc.x, loc.y, province.ring)

        # Prefer exact city name match; fall back to province id presence in cities.
        city_match = None
        for city in dataset.cities:
            if city.province_id == loc.source_province_id and (
                city.name == loc.city_name_exact
                or loc.city_name_exact.casefold() in city.name.casefold()
                or city.name.casefold() in loc.city_name_exact.casefold()
            ):
                city_match = city
                break

        ok_inclusion = included if loc.must_include else (not included)
        ok_geometry = province is not None and point_in_poly
        ok_city = city_match is not None
        ok = bool(ok_inclusion and ok_geometry and ok_city)
        row = {
            "key": loc.key,
            "city_name_exact": loc.city_name_exact,
            "source_province_id": loc.source_province_id,
            "must_include": loc.must_include,
            "included": included,
            "point_in_province_polygon": point_in_poly,
            "city_row_found": ok_city,
            "city_xy": (
                [city_match.x, city_match.y] if city_match is not None else None
            ),
            "expected_xy": [loc.x, loc.y],
            "ok": ok,
        }
        results.append(row)
        if not ok:
            failures.append(loc.key)

    return {
        "ok": not failures,
        "failure_keys": failures,
        "locations": results,
    }
