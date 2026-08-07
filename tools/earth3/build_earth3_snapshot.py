"""Build a Godot campaign_snapshot that forces the Earth3 polygon theatre."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default=str(ROOT / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "godot/campaign_snapshot.json"),
    )
    parser.add_argument(
        "--fixture-output",
        default=str(ROOT / "godot/fixtures/snapshots/earth3_theatre.json"),
    )
    parser.add_argument(
        "--owned",
        action="store_true",
        help="Legacy banded multi-faction ownership (default is neutral readability).",
    )
    args = parser.parse_args()
    data = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    width = float(data["bounds"]["width"])
    height = float(data["bounds"]["height"])
    provinces = []
    for row in data["provinces"]:
        owner = "neutral"
        if args.owned and not row.get("is_water"):
            cx = float(row["centroid"][0])
            if cx < width * 0.28:
                owner = "nato"
            elif cx < width * 0.48:
                owner = "ukr"
            elif cx < width * 0.70:
                owner = "rusa"
            else:
                owner = "prc"
        provinces.append(
            {
                "id": row["id"],
                "display_name": row["id"],
                "owner": owner,
                "x": row["centroid"][0],
                "y": row["centroid"][1],
                "infrastructure": {
                    "fortification": 0,
                    "supply_hub": 0,
                    "recruitment_center": 0,
                    "command_post": 0,
                },
                "name_is_human_readable": False,
                "resource_yield": 10,
                "fortification": 0,
            }
        )
    land = [p for p in provinces if not any(
        r.get("id") == p["id"] and r.get("is_water") for r in data["provinces"]
    )]
    # Prefer dataset is_water flag.
    water_ids = {r["id"] for r in data["provinces"] if r.get("is_water")}
    land = [p for p in provinces if p["id"] not in water_ids]

    battalions = []
    formations = []
    if args.owned:
        for i, faction in enumerate(["nato", "ukr", "rusa", "prc"]):
            if not land:
                break
            pid = land[min(i * max(1, len(land) // 4), len(land) - 1)]["id"]
            fid = f"{faction}-demo"
            formations.append(
                {
                    "id": fid,
                    "faction": faction,
                    "name": f"{faction.upper()} Demo Formation",
                    "province_id": pid,
                }
            )
            battalions.append(
                {
                    "id": f"bat-{faction}-1",
                    "province_id": pid,
                    "faction": faction,
                    "formation_id": fid,
                    "battalion_type": "infantry",
                    "unit_count": 12,
                    "authorized_unit_count": 12,
                    "is_in_supply": True,
                    "encircled_turns": 0,
                    "condition": 100,
                    "supply": 100,
                    "movement_remaining": 1,
                    "combat_actions_remaining": 1,
                }
            )
    elif land:
        # Single neutral marker so UI still has a selectable land province.
        pid = land[len(land) // 2]["id"]
        formations.append(
            {
                "id": "neutral-marker",
                "faction": "nato",
                "name": "Readability Marker",
                "province_id": pid,
            }
        )
        battalions.append(
            {
                "id": "bat-marker-1",
                "province_id": pid,
                "faction": "nato",
                "formation_id": "neutral-marker",
                "battalion_type": "infantry",
                "unit_count": 1,
                "authorized_unit_count": 1,
                "is_in_supply": True,
                "encircled_turns": 0,
                "condition": 100,
                "supply": 100,
                "movement_remaining": 1,
                "combat_actions_remaining": 1,
            }
        )

    snap = {
        "schema": "gates-of-codex.frontend",
        "schema_version": 12,
        "campaign": {
            "name": "Earth3 Europe-Mediterranean",
            "turn_number": 1,
            "current_faction": "nato",
            "selected_faction": "nato",
            "difficulty": "normal",
            "map_id": "earth3_europe_mediterranean",
            "map_metadata": {
                "strategic_map_id": "earth3_europe_mediterranean",
                "strategic_map_manifest": "assets/maps/earth3_europe_mediterranean/map_manifest.json",
            },
            "catalog_signature": "earth3-readability",
            "outcome": None,
            "operational_clock": 0,
            "site_control": {},
        },
        "strategic_map": {
            "enabled": True,
            "configured": True,
            "map_id": "earth3_europe_mediterranean",
            "manifest_path": "res://assets/maps/earth3_europe_mediterranean/map_manifest.json",
            "available_map_ids": [
                "earth3_europe_mediterranean",
                "europe_mediterranean_from_goe",
                "interim_goe_europe",
            ],
            "provenance": "earth3_em_reference_masked_approved",
            "fallback": "europe_mediterranean_from_goe",
        },
        "bounds": {
            "min_x": 0.0,
            "max_x": width,
            "min_y": 0.0,
            "max_y": height,
        },
        "provinces": provinces,
        "battalions": battalions,
        "battalion_stacks": [],
        "formations": formations,
        "factions": [
            {
                "id": f,
                "resources": 1200,
                "researched_keys": [],
                "available_research": [],
                "reinforcement_pool": [],
                "income_last_round": 0,
                "maintenance_last_round": 0,
                "is_human_controlled": f == "nato",
                "is_eliminated": False,
                "supply_reachable_provinces": 0,
            }
            for f in ["nato", "ukr", "rusa", "prc"]
        ],
        "alliances": [],
        "edges": [],
        "front_options": [],
        "pending_battle": None,
        "objectives": [],
        "province_names": {},
        "control": {},
    }
    text = json.dumps(snap, separators=(",", ":")) + "\n"
    Path(args.output).write_text(text, encoding="utf-8")
    Path(args.fixture_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.fixture_output).write_text(text, encoding="utf-8")
    print(f"wrote {args.output} provinces={len(provinces)} owned={args.owned}")
    print(f"wrote {args.fixture_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
