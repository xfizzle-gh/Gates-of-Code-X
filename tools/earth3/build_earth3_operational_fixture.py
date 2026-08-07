"""Build Earth3-native operational snapshot + presentation fixtures (e3_* only)."""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
OUT_SNAP = ROOT / "godot/fixtures/snapshots/earth3_operational.json"
OUT_FIXTURE = ROOT / "godot/fixtures/presentation/e3_operational.json"
OUT_PROOF = ROOT / "godot/fixtures/presentation/e3_v7_extent_proof.json"
OUT_VALIDATOR = ROOT / "godot/scripts/tools/earth3_fixture_validate.gd"

# Source IDs (AoH3) for labelled eastern proof cities.
PROOF_CITIES = {
    "Arkhangelsk": 11764,
    "Syktyvkar": 11756,
    "Perm": 10866,
    "Kazan": 10854,
    "Ufa": 11326,
    "Samara": 10837,
    "Saratov": 10888,
    "Volgograd": 10805,
    "Astrakhan": 10825,
    "Orenburg": 11331,
}

# Conventional Europe–Asia boundary (Earth3 source xy) — same as boundary preview.
EUROPE_ASIA_BOUNDARY_SOURCE = [
    (10920, 380),
    (11040, 520),
    (11120, 700),
    (11160, 900),
    (11200, 1100),
    (11220, 1300),
    (11240, 1450),
    (11250, 1550),
    (11240, 1700),
    (11200, 1850),
    (11140, 1950),
    (11080, 2020),
    (11020, 2100),
    (10940, 2200),
    (10870, 2280),
    (10820, 2360),
    (10740, 2420),
    (10690, 2480),
]

# Home camera in image space (reduces empty ocean; keeps Iceland→Urals readable).
HOME_IMAGE_RECT = {"x": 20.0, "y": 220.0, "w": 4260.0, "h": 3000.0}


def _hull(points: list[tuple[float, float]]) -> list[list[float]]:
    pts = sorted(set((round(p[0], 2), round(p[1], 2)) for p in points))
    if len(pts) <= 2:
        return [list(p) for p in pts]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    return [list(p) for p in hull]


def _ring_points(row: dict) -> list[tuple[float, float]]:
    r = row.get("ring") or []
    return [(float(r[i]), float(r[i + 1])) for i in range(0, len(r) - 1, 2)]


def main() -> int:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    assert int(data["province_count"]) == 3514, data["province_count"]
    ox, oy = data["bounds"]["origin_source_xy"]
    width = float(data["bounds"]["width"])
    height = float(data["bounds"]["height"])
    by_id = {p["id"]: p for p in data["provinces"]}
    by_src = {int(p["source_id"]): p for p in data["provinces"]}
    e3_ids = set(by_id)

    def local_xy(src_x: float, src_y: float) -> list[float]:
        return [round(src_x - ox, 2), round(src_y - oy, 2)]

    proof_labels = []
    for name, sid in PROOF_CITIES.items():
        row = by_src[sid]
        proof_labels.append(
            {
                "id": f"proof-{name.lower()}",
                "label": name,
                "province_id": row["id"],
                "pixel": [round(row["centroid"][0], 1), round(row["centroid"][1], 1)],
            }
        )

    boundary_pixels = [local_xy(x, y) for x, y in EUROPE_ASIA_BOUNDARY_SOURCE]

    # Federal subjects as presentation metadata (hulls of seed provinces + nearby land).
    seeds = {
        "ru-mow-city": ["e3_1906"],  # Moscow city
        "ru-mos-oblast": ["e3_2345", "e3_3106", "e3_3120", "e3_3115", "e3_2836"],  # Tver/Kaluga/Ryazan/Tula/Vladimir
        "ru-spe-city": ["e3_1918"],  # St Petersburg
        "ru-len-oblast": ["e3_1913", "e3_1830", "e3_1910", "e3_1931"],  # Novgorod/Pskov/Yaroslavl/Vologda band
        "ru-ta": ["e3_2781"],  # Kazan / Tatarstan seed
        "ru-ba": ["e3_2940"],  # Ufa / Bashkortostan seed
        "ru-sam": ["e3_2768"],  # Samara
        "ru-sar": ["e3_2813"],  # Saratov
        "ru-vgg": ["e3_2746"],  # Volgograd
        "ru-ast": ["e3_2761"],  # Astrakhan
        "ru-ore": ["e3_2944"],  # Orenburg
        "ru-per": ["e3_2791"],  # Perm
        "ru-kom": ["e3_3162"],  # Syktyvkar / Komi
        "ru-ark": ["e3_3167"],  # Arkhangelsk
    }
    # Expand seeds by neighbors (1 hop) for readable outlines.
    subjects = []
    for sid, seeds_list in seeds.items():
        ids = set(seeds_list)
        for s in list(ids):
            if s in by_id:
                ids.update(by_id[s].get("neighbors") or [])
        # keep land only
        ids = {i for i in ids if i in by_id and not by_id[i].get("is_water")}
        pts: list[tuple[float, float]] = []
        for i in ids:
            pts.extend(_ring_points(by_id[i])[::3])  # decimate
            c = by_id[i]["centroid"]
            pts.append((float(c[0]), float(c[1])))
        hull = _hull(pts)
        if len(hull) >= 3:
            subjects.append(
                {
                    "id": sid,
                    "kind": "federal_subject_outline",
                    "province_ids": sorted(ids),
                    "outline_pixels": hull,
                    "label": sid,
                }
            )

    # Ownership bands for readability + opposing sides
    provinces_out = []
    for p in data["provinces"]:
        owner = "neutral"
        if not p.get("is_water"):
            x = float(p["centroid"][0])
            if x < width * 0.30:
                owner = "nato"
            elif x < width * 0.50:
                owner = "ukr"
            elif x < width * 0.72:
                owner = "rusa"
            else:
                owner = "prc"
        provinces_out.append(
            {
                "id": p["id"],
                "display_name": p["id"],
                "owner": owner,
                "x": p["centroid"][0],
                "y": p["centroid"][1],
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

    # Formations: NATO in west-central, RUSA in Volga/Kazan area
    nato_home = "e3_1906"  # Moscow area as NATO forward for demo? Better west: Paris-ish
    # Pick land provinces near proof cities for RUSA and near western Europe for NATO
    # Use Berlin-ish: find land with centroid ~ (2000, 1700)
    def nearest_land(tx, ty, owner_want=None):
        best = None
        bd = 1e18
        for p in data["provinces"]:
            if p.get("is_water"):
                continue
            if owner_want:
                # owner assigned above by band - recompute
                x = float(p["centroid"][0])
                ow = "nato" if x < width * 0.30 else "ukr" if x < width * 0.50 else "rusa" if x < width * 0.72 else "prc"
                if ow != owner_want:
                    continue
            dx = p["centroid"][0] - tx
            dy = p["centroid"][1] - ty
            d = dx * dx + dy * dy
            if d < bd:
                bd = d
                best = p["id"]
        return best

    nato_prov = nearest_land(1800, 1750, "nato") or "e3_0847"
    rusa_prov = by_src[10854]["id"]  # Kazan
    ukr_prov = nearest_land(2500, 2000, "ukr") or by_src[10868]["id"]

    # Ensure neighbors for routes
    def pick_neighbor(pid: str) -> str:
        row = by_id[pid]
        for n in row.get("neighbors") or []:
            if n in by_id and not by_id[n].get("is_water"):
                return n
        return pid

    nato_target = pick_neighbor(nato_prov)
    rusa_target = pick_neighbor(rusa_prov)

    formations = [
        {
            "id": "form-nato-1",
            "faction": "nato",
            "name": "NATO Vanguard Corps",
            "province_id": nato_prov,
        },
        {
            "id": "form-rusa-1",
            "faction": "rusa",
            "name": "RUSA Volga Combined Arms",
            "province_id": rusa_prov,
        },
        {
            "id": "form-ukr-1",
            "faction": "ukr",
            "name": "UKR Operational Group",
            "province_id": ukr_prov,
        },
    ]
    battalions = [
        {
            "id": "bat-nato-1",
            "province_id": nato_prov,
            "faction": "nato",
            "formation_id": "form-nato-1",
            "battalion_type": "armor",
            "unit_count": 24,
            "authorized_unit_count": 24,
            "is_in_supply": True,
            "encircled_turns": 0,
            "condition": 100,
            "supply": 100,
            "movement_remaining": 1,
            "combat_actions_remaining": 1,
        },
        {
            "id": "bat-rusa-1",
            "province_id": rusa_prov,
            "faction": "rusa",
            "formation_id": "form-rusa-1",
            "battalion_type": "mechanized",
            "unit_count": 28,
            "authorized_unit_count": 28,
            "is_in_supply": True,
            "encircled_turns": 0,
            "condition": 100,
            "supply": 100,
            "movement_remaining": 1,
            "combat_actions_remaining": 1,
        },
        {
            "id": "bat-ukr-1",
            "province_id": ukr_prov,
            "faction": "ukr",
            "formation_id": "form-ukr-1",
            "battalion_type": "infantry",
            "unit_count": 18,
            "authorized_unit_count": 18,
            "is_in_supply": True,
            "encircled_turns": 0,
            "condition": 100,
            "supply": 100,
            "movement_remaining": 1,
            "combat_actions_remaining": 1,
        },
    ]

    # Edges: use real adjacency pairs among featured provinces + a path
    featured = {nato_prov, nato_target, rusa_prov, rusa_target, ukr_prov}
    for lab in proof_labels:
        featured.add(lab["province_id"])
    edges = []
    seen = set()
    for pid in featured:
        for n in by_id[pid].get("neighbors") or []:
            if n not in e3_ids:
                continue
            a, b = (pid, n) if pid < n else (n, pid)
            if (a, b) in seen:
                continue
            seen.add((a, b))
            edges.append([a, b])

    front_options = [
        {
            "battalion_id": "bat-nato-1",
            "formation_id": "form-nato-1",
            "origin": nato_prov,
            "target": nato_target,
            "kind": "move",
            "command": "advance",
            "enemies": [],
        },
        {
            "battalion_id": "bat-rusa-1",
            "formation_id": "form-rusa-1",
            "origin": rusa_prov,
            "target": rusa_target,
            "kind": "attack",
            "command": "assault",
            "enemies": ["bat-ukr-1"] if ukr_prov == rusa_target else [],
        },
    ]

    # Pending battle between RUSA and UKR near ukr/rusa
    battle_origin = rusa_prov
    battle_target = rusa_target if rusa_target != rusa_prov else ukr_prov
    o_px = by_id[battle_origin]["centroid"]
    t_px = by_id[battle_target]["centroid"]
    mid = [round((o_px[0] + t_px[0]) * 0.5, 1), round((o_px[1] + t_px[1]) * 0.5, 1)]

    pending_battle = {
        "id": "e3-pending-volga-contact",
        "origin_province_id": battle_origin,
        "target_province_id": battle_target,
        "attacker_faction": "rusa",
        "defender_faction": "ukr",
        "encounter_kind": "edge_cross",
        "encounter_node_id": "",
        "encounter_edge_id": f"e3-edge-{battle_origin}-{battle_target}",
        "encounter_progress_milli": 500,
        "encounter_pixel": mid,
        "goh_handoff": {
            "enabled": True,
            "map_id": "earth3_europe_mediterranean",
            "origin_province_id": battle_origin,
            "target_province_id": battle_target,
            "encounter_pixel": mid,
            "attacker_faction": "rusa",
            "defender_faction": "ukr",
            "payload_schema": "gates-of-codex.goh-handoff",
            "payload_version": 1,
        },
    }

    # Control sites on proof cities
    site_control = {}
    control_sites_pres = []
    for lab in proof_labels[:6]:
        site_control[lab["province_id"]] = "rusa" if lab["province_id"] == rusa_prov else "neutral"
        control_sites_pres.append(
            {
                "id": f"site-{lab['province_id']}",
                "province_id": lab["province_id"],
                "pixel": lab["pixel"],
                "owned": site_control[lab["province_id"]] != "neutral",
                "owner": site_control[lab["province_id"]],
                "presentation_capture_progress_fp": 0,
                "presentation_capture_max_fp": 1000,
            }
        )

    snap = {
        "schema": "gates-of-codex.frontend",
        "schema_version": 12,
        "campaign": {
            "name": "Earth3 Europe–Urals Operational",
            "turn_number": 1,
            "current_faction": "nato",
            "selected_faction": "nato",
            "difficulty": "normal",
            "map_id": "earth3_europe_mediterranean",
            "map_metadata": {
                "strategic_map_id": "earth3_europe_mediterranean",
                "strategic_map_manifest": "assets/maps/earth3_europe_mediterranean/map_manifest.json",
            },
            "catalog_signature": "earth3-operational-v7",
            "outcome": None,
            "operational_clock": 0,
            "site_control": site_control,
        },
        "strategic_map": {
            "enabled": True,
            "configured": True,
            "map_id": "earth3_europe_mediterranean",
            "manifest_path": "res://assets/maps/earth3_europe_mediterranean/map_manifest.json",
            "available_map_ids": [
                "earth3_europe_mediterranean",
                "europe_mediterranean_from_goe",
            ],
            "provenance": "earth3_v7_europe_asia_boundary",
            "fallback": "europe_mediterranean_from_goe",
            "home_image_rect": HOME_IMAGE_RECT,
        },
        "bounds": {"min_x": 0.0, "max_x": width, "min_y": 0.0, "max_y": height},
        "provinces": provinces_out,
        "battalions": battalions,
        "battalion_stacks": {
            nato_prov: ["bat-nato-1"],
            rusa_prov: ["bat-rusa-1"],
            ukr_prov: ["bat-ukr-1"],
        },
        "formations": formations,
        "factions": [
            {
                "id": f,
                "resources": 1500,
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
        "edges": edges,
        "front_options": front_options,
        "pending_battle": pending_battle,
        "objectives": [],
        "province_names": {},
        "control": {
            "enabled": True,
            "snapshot_path": "res://fixtures/snapshots/earth3_operational.json",
            "commands_path": "",
            "campaign_path": "",
        },
    }

    # Presentation fixture: routes, battles, proof overlays
    def pix(pid: str) -> list[float]:
        c = by_id[pid]["centroid"]
        return [round(float(c[0]), 1), round(float(c[1]), 1)]

    route_pts = [pix(nato_prov)]
    # walk a short neighbor chain toward center
    cur = nato_prov
    for _ in range(4):
        nxt = pick_neighbor(cur)
        if nxt == cur:
            break
        route_pts.append(pix(nxt))
        cur = nxt
    route_pts.append(pix(rusa_prov))

    fixture = {
        "schema": "gates-of-codex.presentation-fixture",
        "schema_version": 1,
        "id": "e3_operational",
        "description": "Earth3-native operational fixture (e3_* only): routes, sites, battle, proof overlays.",
        "selected_province_id": nato_prov,
        "selected_formation_id": "form-nato-1",
        "routes": [
            {
                "id": "e3-route-nato-to-volga",
                "pixels": route_pts,
                "color": "7fe7ff",
                "province_ids": [nato_prov, rusa_prov],
            }
        ],
        "battles": [
            {
                "id": "e3-node-battle",
                "kind": "node",
                "pixel": pix(battle_target),
                "province_id": battle_target,
            },
            {
                "id": "e3-edge-battle",
                "kind": "edge",
                "presentation_edge_a_pixel": pix(battle_origin),
                "presentation_edge_b_pixel": pix(battle_target),
                "presentation_progress_fp": 500,
                "origin_province_id": battle_origin,
                "target_province_id": battle_target,
            },
        ],
        "contacts": [
            {
                "id": "e3-contact",
                "kind": "node",
                "pixel": mid,
                "province_id": battle_target,
            }
        ],
        "control_sites": control_sites_pres,
        "operational_nodes": [],
        "operational_edges": [],
        "pending_battle": pending_battle,
        "proof_labels": proof_labels,
        "europe_asia_boundary_pixels": boundary_pixels,
        "federal_subject_outlines": subjects,
        "home_image_rect": HOME_IMAGE_RECT,
        "synthetic_counters": [
            {
                "pixel": pix(nato_prov),
                "faction": "nato",
                "glyph": "A",
                "strength": 24,
                "stack": 1,
                "province_id": nato_prov,
            },
            {
                "pixel": pix(rusa_prov),
                "faction": "rusa",
                "glyph": "R",
                "strength": 28,
                "stack": 1,
                "province_id": rusa_prov,
            },
            {
                "pixel": pix(ukr_prov),
                "faction": "ukr",
                "glyph": "U",
                "strength": 18,
                "stack": 1,
                "province_id": ukr_prov,
            },
        ],
        "force_stack_badges": [
            {"pixel": pix(nato_prov), "count": 1, "province_id": nato_prov},
            {"pixel": pix(rusa_prov), "count": 1, "province_id": rusa_prov},
        ],
        "notes": [
            "e3_* IDs only — no GoE province names",
            "pair with --snapshot=res://fixtures/snapshots/earth3_operational.json",
        ],
    }

    proof_only = {
        "schema": "gates-of-codex.presentation-fixture",
        "schema_version": 1,
        "id": "e3_v7_extent_proof",
        "description": "Presentation-only eastern extent proof overlays for 3512 theatre.",
        "proof_labels": proof_labels,
        "europe_asia_boundary_pixels": boundary_pixels,
        "federal_subject_outlines": subjects,
        "home_image_rect": HOME_IMAGE_RECT,
        "routes": [],
        "battles": [],
        "contacts": [],
        "control_sites": [],
        "notes": ["presentation-only proof; does not alter crop"],
    }

    OUT_SNAP.parent.mkdir(parents=True, exist_ok=True)
    OUT_SNAP.write_text(json.dumps(snap, separators=(",", ":")) + "\n", encoding="utf-8")
    OUT_FIXTURE.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    OUT_PROOF.write_text(json.dumps(proof_only, indent=2) + "\n", encoding="utf-8")

    # Collect all referenced e3 ids for validator metadata
    refs = set()
    for p in provinces_out:
        refs.add(p["id"])
    for b in battalions:
        refs.add(b["province_id"])
    for f in formations:
        refs.add(f["province_id"])
    for a, b in edges:
        refs.add(a)
        refs.add(b)
    for o in front_options:
        refs.add(o["origin"])
        refs.add(o["target"])
    refs.add(pending_battle["origin_province_id"])
    refs.add(pending_battle["target_province_id"])
    for lab in proof_labels:
        refs.add(lab["province_id"])
    for s in control_sites_pres:
        refs.add(s["province_id"])
    missing = sorted(r for r in refs if r not in e3_ids)
    if missing:
        raise SystemExit(f"builder referenced missing ids: {missing}")

    print("wrote", OUT_SNAP, "provinces", len(provinces_out))
    print("wrote", OUT_FIXTURE)
    print("wrote", OUT_PROOF)
    print(
        "featured",
        nato_prov,
        rusa_prov,
        ukr_prov,
        "labels",
        len(proof_labels),
        "subjects",
        len(subjects),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
