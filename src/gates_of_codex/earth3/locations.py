"""Exact required-location checks for the Earth3 launch theatre crop.

Final authority matching is exact only:
- city name string equality
- source province ID equality
- coordinate equality (float)

No substring or fuzzy fallback is used for pass/fail.
"""

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
    gating: bool = True  # False => informational only (does not fail the suite)


# Exact city rows from Earth3 cities.json (name + province id + coordinates).
# Coordinates and IDs taken from the licensed local Earth3 extract.
REQUIRED_LOCATIONS: tuple[RequiredLocation, ...] = (
    # Must include
    RequiredLocation("Reykjavik", "Reykjavík", 951, True, 7281.0, 930.0),
    RequiredLocation("London", "London", 825, True, 8337.0, 1992.0),
    RequiredLocation("Dublin", "Dublin", 920, True, 8040.0, 1844.0),
    RequiredLocation("Madrid", "Madrid", 6561, True, 8165.0, 2774.0),
    RequiredLocation("Lisbon", "Lisbon", 11, True, 7898.0, 2879.0),
    RequiredLocation("Paris", "Paris", 260, True, 8461.0, 2194.0),
    RequiredLocation("Berlin", "Berlin", 592, True, 9000.0, 1913.0),
    RequiredLocation("Rome", "Rome", 6881, True, 8954.0, 2678.0),
    RequiredLocation("Athens", "Athens", 2202, True, 9502.0, 2927.0),
    RequiredLocation("Kyiv", "Kyiv", 3757, True, 9832.0, 2074.0),
    RequiredLocation("Odesa", "Odesa", 3241, True, 9840.0, 2369.0),
    RequiredLocation("Kherson", "Kherson", 1271, True, 9932.0, 2352.0),
    RequiredLocation("Zaporizhzhia", "Zaporizhzhia", 3782, True, 10058.0, 2269.0),
    RequiredLocation("Donetsk", "Donetsk", 12175, True, 10188.0, 2256.0),
    RequiredLocation("Luhansk", "Luhansk", 10869, True, 10261.0, 2216.0),
    RequiredLocation("Sevastopol", "Sevastopol", 1268, True, 9983.0, 2492.0),
    RequiredLocation("Simferopol", "Simferopol", 6627, True, 10009.0, 2472.0),
    RequiredLocation("Rostov_on_Don", "Rostov on Don", 10868, True, 10278.0, 2309.0),
    RequiredLocation("Istanbul", "Istanbul", 1116, True, 9757.0, 2733.0),
    RequiredLocation("Ankara", "Ankara", 2207, True, 9945.0, 2804.0),
    RequiredLocation("Tbilisi", "Tbilisi", 10431, True, 10531.0, 2689.0),
    RequiredLocation("Yerevan", "Yerevan", 10436, True, 10517.0, 2786.0),
    RequiredLocation("Baku", "Baku", 2654, True, 10776.0, 2772.0),
    RequiredLocation("Tunis", "Tunis", 2242, True, 8845.0, 2974.0),
    RequiredLocation("Algiers", "Algiers", 1399, True, 8496.0, 2985.0),
    RequiredLocation("Tripoli", "Tripoli", 1365, True, 8989.0, 3231.0),
    RequiredLocation("Cairo", "Cairo", 2669, True, 9867.0, 3402.0),
    RequiredLocation("Alexandria", "Alexandria", 2662, True, 9806.0, 3333.0),
    RequiredLocation("Port_Said", "Port Said", 2666, True, 9919.0, 3332.0),
    RequiredLocation("Suez", "Suez", 2683, True, 9931.0, 3398.0),
    RequiredLocation("Arish_Sinai", "Arish", 3723, True, 9995.0, 3334.0),
    RequiredLocation("Jerusalem", "Jerusalem", 8065, True, 10061.0, 3296.0),
    RequiredLocation("Beirut", "Beirut", 6087, True, 10079.0, 3176.0),
    RequiredLocation("Damascus", "Damascus", 3719, True, 10115.0, 3196.0),
    RequiredLocation("Adana_southern_Turkey", "Adana", 1096, True, 10067.0, 2987.0),
    RequiredLocation("Stockholm", "Stockholm", 1049, True, 9225.0, 1315.0),
    RequiredLocation("Helsinki", "Helsinki", 1461, True, 9560.0, 1240.0),
    RequiredLocation("Tallinn", "Tallinn", 513, True, 9550.0, 1310.0),
    RequiredLocation("Riga", "Riga", 504, True, 9528.0, 1532.0),
    RequiredLocation("Vilnius", "Vilnius", 442, True, 9579.0, 1737.0),
    RequiredLocation("Narvik_northern_Norway", "Narvik", 1464, True, 9197.0, 531.0),
    RequiredLocation("Kiruna_northern_Sweden", "Kiruna", 11120, True, 9332.0, 587.0),
    RequiredLocation("Rovaniemi_northern_Finland", "Rovaniemi", 1458, True, 9599.0, 717.0),
    # Must exclude (deep Arctic Russia — not Kola approach)
    RequiredLocation("Arkhangelsk", "Arkhangelsk", 11764, False, 10325.0, 892.0),
    # Informational only (non-gating)
    RequiredLocation("Oslo", "Oslo", 1009, True, 8870.0, 1261.0, gating=False),
    RequiredLocation("Murmansk_kola_approach", "Murmansk", 11370, True, 9961.0, 474.0, gating=False),
)

GATING_LOCATION_KEYS: tuple[str, ...] = tuple(
    loc.key for loc in REQUIRED_LOCATIONS if loc.gating
)


def validate_required_locations(
    dataset: Earth3Dataset, included_ids: set[int]
) -> dict[str, object]:
    """Exact province-id / name / coordinate validation for required theatre points."""
    cities_by_key: dict[tuple[int, str, float, float], object] = {}
    for city in dataset.cities:
        cities_by_key[(city.province_id, city.name, float(city.x), float(city.y))] = city

    results: list[dict[str, object]] = []
    failures: list[str] = []
    informational: list[dict[str, object]] = []

    for loc in REQUIRED_LOCATIONS:
        province = dataset.provinces.get(loc.source_province_id)
        included = loc.source_province_id in included_ids
        point_in_poly = False
        if province is not None:
            point_in_poly = point_in_ring(loc.x, loc.y, province.ring)

        city_match = cities_by_key.get(
            (loc.source_province_id, loc.city_name_exact, float(loc.x), float(loc.y))
        )

        ok_inclusion = included if loc.must_include else (not included)
        ok_geometry = province is not None and point_in_poly
        ok_city = city_match is not None
        # Exact coordinate equality already encoded in the city key lookup.
        ok = bool(ok_inclusion and ok_geometry and ok_city)

        row = {
            "key": loc.key,
            "city_name_exact": loc.city_name_exact,
            "source_province_id": loc.source_province_id,
            "must_include": loc.must_include,
            "gating": loc.gating,
            "included": included,
            "point_in_province_polygon": point_in_poly,
            "city_row_found_exact": ok_city,
            "city_xy": (
                [float(city_match.x), float(city_match.y)]
                if city_match is not None
                else None
            ),
            "expected_xy": [loc.x, loc.y],
            "ok": ok,
        }
        results.append(row)
        if not loc.gating:
            informational.append(row)
            continue
        if not ok:
            failures.append(loc.key)

    return {
        "ok": not failures,
        "failure_keys": failures,
        "gating_key_count": len(GATING_LOCATION_KEYS),
        "gating_keys": list(GATING_LOCATION_KEYS),
        "informational": informational,
        "locations": results,
    }
