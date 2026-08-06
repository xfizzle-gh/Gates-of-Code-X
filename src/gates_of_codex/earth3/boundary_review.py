"""Boundary review sheet for frozen threshold-band provinces."""

from __future__ import annotations

import json
from pathlib import Path

from .model import Earth3Dataset

BOUNDARY_GROUPS = (
    "Europe_Scandinavia",
    "western_Russia",
    "Caucasus",
    "northwestern_Iran_fringe",
    "Turkey_northern_Levant",
    "Egypt_Sinai",
    "Arabian_interior",
    "North_African_coast",
    "Sahara",
    "Mediterranean_water",
    "Atlantic_Nordic_water",
    "Atlantic_unrelated_water",
    "Caspian_water",
    "Red_Sea_water",
    "other_water",
    "other_land",
)

# Explicit province-ID group overrides (reviewed).
_PID_GROUP_OVERRIDES: dict[int, str] = {
    1227: "Turkey_northern_Levant",  # Viranşehir
    1228: "Turkey_northern_Levant",  # Şanlıurfa
    4348: "Sahara",
    4859: "Sahara",
    4895: "Sahara",
    4796: "Sahara",
    12906: "Atlantic_unrelated_water",
    12307: "Red_Sea_water",
}

_GROUP_CITY_ANCHORS: dict[str, tuple[tuple[str, int], ...]] = {
    "Europe_Scandinavia": (
        ("Reykjavík", 951),
        ("Höfn", 956),
        ("Bakkafjörður", 6850),
        ("Stockholm", 1049),
        ("Helsinki", 1461),
        ("Oslo", 1009),
        ("London", 825),
        ("Paris", 260),
        ("Berlin", 592),
        ("Rome", 6881),
        ("Athens", 2202),
        ("Kyiv", 3757),
        ("Murmansk", 11370),
    ),
    "western_Russia": (
        ("Rostov on Don", 10868),
        ("Naberezhnye Chelny", 10857),
        ("Yaransk", 11170),
        ("Tuymazy", 11323),
        ("Galich", 11689),
        ("Orsk", 10919),
        ("Arkhangelsk", 11764),
    ),
    "Caucasus": (
        ("Tbilisi", 10431),
        ("Yerevan", 10436),
        ("Baku", 2654),
    ),
    "northwestern_Iran_fringe": (
        ("Urmia", 1194),
        ("Ahvaz", 2624),
        ("Anarak", 3507),
        ("Moalleman", 10577),
    ),
    "Turkey_northern_Levant": (
        ("Istanbul", 1116),
        ("Ankara", 2207),
        ("Viranşehir", 1227),
        ("Şanlıurfa", 1228),
    ),
    "Egypt_Sinai": (
        ("Cairo", 2669),
    ),
    "Arabian_interior": (
        ("Hail", 6162),
        ("Hegra", 6091),
        ("Ash Shamli", 6163),
        ("Turaif", 6193),
        ("An Nahidayn", 6202),
    ),
    "North_African_coast": (
        ("Tunis", 2242),
        ("Algiers", 1399),
        ("Tripoli", 1365),
    ),
    "Sahara": (
        ("Dujal", 4796),
        ("Tabelbala", 4859),
        ("In Ghar", 4895),
    ),
}


def classify_boundary_group(
    dataset: Earth3Dataset,
    *,
    pid: int,
    centroid: tuple[float, float],
    is_water: bool,
) -> str:
    if pid in _PID_GROUP_OVERRIDES:
        return _PID_GROUP_OVERRIDES[pid]

    x, y = centroid
    if is_water:
        # Water basins by reviewed geography, not residual "North Africa".
        if 9800 <= x <= 10300 and 3300 <= y <= 3700:
            return "Red_Sea_water"
        if x >= 10600 and 2400 <= y <= 3000:
            return "Caspian_water"
        # Madeira / unrelated mid-Atlantic south of Iberia.
        if x < 7700 and y >= 3000:
            return "Atlantic_unrelated_water"
        if x < 7800 or (y < 1600 and x < 9000):
            return "Atlantic_Nordic_water"
        if 7800 <= x <= 10800 and 2500 <= y <= 3600:
            return "Mediterranean_water"
        return "other_water"

    for group, anchors in _GROUP_CITY_ANCHORS.items():
        for _name, apid in anchors:
            if pid == apid:
                return group

    cx, cy = centroid
    best_group = None
    best_d2 = None
    name_to_group = {
        name: group for group, anchors in _GROUP_CITY_ANCHORS.items() for name, _pid in anchors
    }
    for city in dataset.cities:
        group = name_to_group.get(city.name)
        if group is None:
            continue
        d2 = (float(city.x) - cx) ** 2 + (float(city.y) - cy) ** 2
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best_group = group
    if best_group is not None and best_d2 is not None and best_d2 ** 0.5 < 350:
        # Never label Iraq/Saudi anchors as North Africa (anchor table already separates).
        return best_group

    # Residual geometry only after city anchors.
    if x < 7900 and y < 1200:
        return "Europe_Scandinavia"
    if y >= 3420 and x < 10000:
        return "Sahara"
    if 9800 <= x <= 10150 and 3300 <= y <= 3450:
        return "Egypt_Sinai"
    if y >= 3200 and x < 9800:
        return "North_African_coast"
    if 10000 <= x <= 10500 and y >= 3000:
        return "Arabian_interior"
    if x >= 10500 and y >= 2880:
        return "northwestern_Iran_fringe"
    if x >= 10400 and 2500 <= y <= 2900:
        return "Caucasus"
    if x >= 10300 and y < 2000:
        return "western_Russia"
    if y < 1500:
        return "Europe_Scandinavia"
    if 10000 <= x <= 10400 and 2800 <= y <= 3100:
        return "Turkey_northern_Levant"
    if 9600 <= x <= 10400 and 2600 <= y <= 3200:
        return "Turkey_northern_Levant"
    return "other_land"


def nearest_city_label(dataset: Earth3Dataset, x: float, y: float) -> dict[str, object] | None:
    best = None
    best_d2 = None
    for city in dataset.cities:
        d2 = (float(city.x) - x) ** 2 + (float(city.y) - y) ** 2
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best = city
    if best is None:
        return None
    return {
        "name": best.name,
        "source_province_id": best.province_id,
        "x": best.x,
        "y": best.y,
        "distance_px": best_d2 ** 0.5 if best_d2 is not None else None,
    }


def closeup_for_group(group: str) -> str:
    if group in {
        "Europe_Scandinavia",
        "western_Russia",
        "Atlantic_Nordic_water",
        "Atlantic_unrelated_water",
    }:
        return "closeups/em_reference_masked_scandinavia_north_russia.png"
    if group in {"Caucasus", "northwestern_Iran_fringe", "Caspian_water"}:
        return "closeups/em_reference_masked_ukraine_donbas_caucasus.png"
    if group in {
        "North_African_coast",
        "Sahara",
        "Turkey_northern_Levant",
        "Egypt_Sinai",
        "Arabian_interior",
        "Red_Sea_water",
        "Mediterranean_water",
    }:
        return "closeups/em_reference_masked_north_africa_east_med.png"
    return "preview_em_reference_masked.png"


def geographic_reason(
    *,
    group: str,
    decision: str,
    ratio: float,
    is_water: bool,
    nearest_name: str,
) -> str:
    side = "include" if decision == "include" else "exclude"
    base = (
        f"Algorithmic recommendation: {side} because overlap_ratio={ratio:.4f} "
        f"{'≥' if decision == 'include' else '<'} 0.35 threshold."
    )
    notes = {
        "Europe_Scandinavia": "European / Scandinavian theatre edge.",
        "western_Russia": "Western Russian approaches; deep-east anchors must stay out.",
        "Caucasus": "Caucasus edge; keep Tbilisi/Yerevan/Baku.",
        "northwestern_Iran_fringe": "NW Iran fringe; Urmia default excluded.",
        "Turkey_northern_Levant": "Turkey / northern Levant / upper-Mesopotamia edge (not North Africa).",
        "Egypt_Sinai": "Egypt / Sinai framing around Cairo and canal approaches.",
        "Arabian_interior": "Arabian interior; must stay out of launch theatre.",
        "North_African_coast": "Mediterranean North African coastal belt only.",
        "Sahara": "Deep Sahara / interior Maghreb; must stay out.",
        "Mediterranean_water": "Mediterranean sea province.",
        "Atlantic_Nordic_water": "Atlantic / Nordic sea province.",
        "Atlantic_unrelated_water": "Unrelated Atlantic water (e.g. Madeira/Funchal); outside reference extent.",
        "Caspian_water": "Caspian sea province.",
        "Red_Sea_water": "Red Sea water; must stay out while keeping Cairo/Sinai framing.",
        "other_water": "Other water province on mask perimeter.",
        "other_land": "Other land boundary province.",
    }
    water = " Water province." if is_water else ""
    near = f" Nearest city: {nearest_name}." if nearest_name else ""
    return f"{base} {notes.get(group, '')}{near}{water} Owner review still required."


def build_boundary_review(
    dataset: Earth3Dataset,
    decisions_path: str | Path,
) -> dict:
    decisions = json.loads(Path(decisions_path).read_text(encoding="utf-8"))
    rows = []
    for item in decisions.get("decisions", []):
        pid = int(item["source_province_id"])
        province = dataset.provinces[pid]
        cx, cy = province.centroid
        group = classify_boundary_group(
            dataset,
            pid=pid,
            centroid=(cx, cy),
            is_water=province.is_water,
        )
        decision = str(item.get("owner_decision") or item["decision"])
        ratio = float(item["overlap_ratio"])
        nearest = nearest_city_label(dataset, cx, cy)
        nearest_name = str(nearest["name"]) if nearest else ""
        # Prefer explicit group from decision file when present.
        group = str(item.get("boundary_group") or group)
        owner_status = str(
            item.get("owner_review_status")
            or decisions.get("owner_review_status")
            or "pending"
        )
        owner_reason = str(item.get("owner_reason") or "")
        rows.append(
            {
                "source_province_id": pid,
                "overlap_ratio": ratio,
                "algorithmic_recommendation": str(item.get("decision", decision)),
                "owner_decision": decision,
                "owner_review_status": owner_status,
                "owner_reason": owner_reason,
                "boundary_group": group,
                "nearest_city": nearest,
                "is_water": province.is_water,
                "continent_id": province.continent_id,
                "region_id": province.region_id,
                "centroid": [cx, cy],
                "geographic_reason": owner_reason
                or geographic_reason(
                    group=group,
                    decision=decision,
                    ratio=ratio,
                    is_water=province.is_water,
                    nearest_name=nearest_name,
                ),
                "closeup_image": closeup_for_group(group),
            }
        )

    by_group: dict[str, list] = {g: [] for g in BOUNDARY_GROUPS}
    for row in rows:
        by_group.setdefault(row["boundary_group"], []).append(row)

    return {
        "schema": "gates-of-codex.earth3-boundary-review",
        "schema_version": 3,
        "candidate_id": decisions.get("candidate_id", "em_reference_masked"),
        "status": str(decisions.get("owner_review_status") or "pending"),
        "note": (
            "Boundary threshold-band provinces carry explicit owner include/exclude "
            "decisions. Grouping uses reviewed Earth3 city anchors and basin labels "
            "(Turkey/northern Levant is not North Africa; deep Sahara and Madeira water excluded)."
        ),
        "decision_count": len(rows),
        "groups": {
            g: {
                "count": len(items),
                "include_count": sum(
                    1 for i in items if i["algorithmic_recommendation"] == "include"
                ),
                "exclude_count": sum(
                    1 for i in items if i["algorithmic_recommendation"] == "exclude"
                ),
                "provinces": items,
            }
            for g, items in by_group.items()
            if items
        },
        "provinces": rows,
    }


def write_boundary_review_markdown(review: dict, path: str | Path) -> Path:
    out = Path(path)
    lines = [
        "# Earth3 em_reference_masked boundary review sheet",
        "",
        f"**Status:** {review['status']}",
        "",
        review["note"],
        "",
        f"Total threshold-band provinces: **{review['decision_count']}**",
        "",
    ]
    for group, payload in review["groups"].items():
        lines.append(f"## {group}")
        lines.append("")
        lines.append(
            f"Count: {payload['count']} "
            f"(include rec: {payload['include_count']}, "
            f"exclude rec: {payload['exclude_count']})"
        )
        lines.append("")
        lines.append(
            "| PID | Ratio | Rec | Land/Water | Nearest city | Close-up | Reason |"
        )
        lines.append("|---:|---:|---|---|---|---|---|")
        for row in payload["provinces"]:
            city = row.get("nearest_city") or {}
            city_label = city.get("name", "")
            lw = "water" if row["is_water"] else "land"
            lines.append(
                f"| {row['source_province_id']} | {row['overlap_ratio']:.4f} | "
                f"{row['algorithmic_recommendation']} | {lw} | {city_label} | "
                f"`{row['closeup_image']}` | {row['geographic_reason']} |"
            )
        lines.append("")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
