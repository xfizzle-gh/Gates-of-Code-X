"""Boundary review sheet for frozen threshold-band provinces."""

from __future__ import annotations

import json
from pathlib import Path

from .model import Earth3Dataset

BOUNDARY_GROUPS = (
    "Iceland_Atlantic",
    "Scandinavia_northern_Russia",
    "eastern_Russia",
    "Caucasus",
    "North_Africa",
    "eastern_Mediterranean_Levant",
    "southern_export_boundary",
    "water_boundary",
)


def classify_boundary_group(
    *,
    centroid: tuple[float, float],
    is_water: bool,
    continent_id: int,
) -> str:
    x, y = centroid
    if is_water or continent_id == 0:
        return "water_boundary"
    # Iceland / far west Atlantic fringe
    if x < 7800 and y < 1200:
        return "Iceland_Atlantic"
    # North Africa
    if y >= 3300 and x < 10400:
        return "North_Africa"
    # Eastern Med / Levant / Egypt edge
    if y >= 3000 and x >= 9800:
        return "eastern_Mediterranean_Levant"
    # Caucasus / far SE land
    if x >= 10900 and 1800 <= y <= 3200:
        return "Caucasus"
    # Eastern Russia approaches
    if x >= 10300 and y < 1800:
        return "eastern_Russia"
    # Scandinavia / northern Russia fringe
    if y < 1400:
        return "Scandinavia_northern_Russia"
    # Deep south export edge land
    if y >= 3600:
        return "southern_export_boundary"
    # Residual southern land near Maghreb/export
    if y >= 3400:
        return "southern_export_boundary"
    return "Scandinavia_northern_Russia"


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
    if group in {"Iceland_Atlantic", "Scandinavia_northern_Russia", "eastern_Russia"}:
        return "closeups/em_reference_masked_scandinavia_north_russia.png"
    if group in {"Caucasus"}:
        return "closeups/em_reference_masked_ukraine_donbas_caucasus.png"
    if group in {
        "North_Africa",
        "eastern_Mediterranean_Levant",
        "southern_export_boundary",
    }:
        return "closeups/em_reference_masked_north_africa_east_med.png"
    if group == "water_boundary":
        return "closeups/em_reference_masked_scandinavia_north_russia.png"
    return "preview_em_reference_masked.png"


def geographic_reason(
    *,
    group: str,
    decision: str,
    ratio: float,
    is_water: bool,
) -> str:
    side = "include" if decision == "include" else "exclude"
    base = (
        f"Algorithmic recommendation: {side} because overlap_ratio={ratio:.4f} "
        f"{'≥' if decision == 'include' else '<'} 0.35 threshold."
    )
    notes = {
        "Iceland_Atlantic": "Atlantic/Iceland fringe boundary.",
        "Scandinavia_northern_Russia": "Northern Scandinavian / N-Russia mask edge.",
        "eastern_Russia": "Eastern Russian depth edge beyond Donbas approaches.",
        "Caucasus": "Caucasus / SE theatre edge.",
        "North_Africa": "North African coastal depth edge.",
        "eastern_Mediterranean_Levant": "E.Med / Levant coastal edge.",
        "southern_export_boundary": "Southern export/mask depth edge.",
        "water_boundary": "Water/sea province on mask perimeter.",
    }
    water = " Water province." if is_water else ""
    return f"{base} {notes.get(group, '')}{water} Owner review still required."


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
            centroid=(cx, cy),
            is_water=province.is_water,
            continent_id=province.continent_id,
        )
        decision = str(item["decision"])
        ratio = float(item["overlap_ratio"])
        nearest = nearest_city_label(dataset, cx, cy)
        rows.append(
            {
                "source_province_id": pid,
                "overlap_ratio": ratio,
                "algorithmic_recommendation": decision,
                "owner_review_status": "pending",
                "boundary_group": group,
                "nearest_city": nearest,
                "is_water": province.is_water,
                "continent_id": province.continent_id,
                "centroid": [cx, cy],
                "geographic_reason": geographic_reason(
                    group=group,
                    decision=decision,
                    ratio=ratio,
                    is_water=province.is_water,
                ),
                "closeup_image": closeup_for_group(group),
            }
        )

    by_group: dict[str, list] = {g: [] for g in BOUNDARY_GROUPS}
    for row in rows:
        by_group.setdefault(row["boundary_group"], []).append(row)

    return {
        "schema": "gates-of-codex.earth3-boundary-review",
        "schema_version": 1,
        "candidate_id": decisions.get("candidate_id", "em_reference_masked"),
        "status": "algorithmic_recommendation_pending_owner_review",
        "note": (
            "Automatic threshold outcomes are algorithmic recommendations only. "
            "They are not completed owner boundary review."
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
        f"Total formerly threshold-band provinces: **{review['decision_count']}**",
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
