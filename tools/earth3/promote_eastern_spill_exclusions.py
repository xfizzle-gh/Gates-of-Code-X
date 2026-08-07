"""Promote approved eastern-spill exclusions into production Earth3 dataset.

Owner-approved (#117 / #120):
- exclude source 10920 / e3_2830 (Kartaly)
- exclude source 11031 / e3_2888 (Kulakshi)
- retain all other provinces and geometry
- stable Gates IDs (gaps for removed IDs; never recycle)
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.earth3.audit_artifact import included_ids_hash  # noqa: E402

PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean"
EVIDENCE = ROOT / "docs/earth3-crop/topology_sanitize/production_promotion"
FIXTURES = ROOT / "godot/fixtures"
AUTH = ROOT / "config/earth3/production_authority.json"
PRE_HASH = "507b0069a9572e915059ff6d21bd9f13a68cf62a26770c94a90c0b0e6a900be7"
EXCLUDE_SOURCE_IDS = {10920, 11031}
EXCLUDE_GATES = {"e3_2830", "e3_2888"}
KEEP_ISLAND_SOURCE_IDS = {
    2271,
    2272,
    2273,
    2274,
    6574,
    258,
    259,
    270,
    882,
    913,
    992,
    1056,
    1154,
    3132,
    3220,
    4693,
}


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ring_pts(row: dict) -> list[tuple[float, float]]:
    f = row.get("ring") or []
    return [(float(f[i]), float(f[i + 1])) for i in range(0, len(f) - 1, 2)]


def _collect_gameplay_ids(node, out: list[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            ks = str(k)
            if (
                ks
                in (
                    "province_id",
                    "origin",
                    "target",
                    "origin_province_id",
                    "target_province_id",
                    "selected_province_id",
                )
                or ks.endswith("province_id")
            ):
                if isinstance(v, str) and v.startswith("e3_"):
                    out.append(v)
            elif ks == "province_ids" and isinstance(v, list):
                for item in v:
                    if isinstance(item, str) and item.startswith("e3_"):
                        out.append(item)
            else:
                _collect_gameplay_ids(v, out)
    elif isinstance(node, list):
        if len(node) == 2 and all(isinstance(x, str) and x.startswith("e3_") for x in node):
            out.extend(node)
            return
        for item in node:
            _collect_gameplay_ids(item, out)


def main() -> int:
    src_path = PROD / "polygon_dataset.json"
    baseline = json.loads(src_path.read_text(encoding="utf-8"))
    assert int(baseline["province_count"]) == 3512
    assert baseline.get("included_source_ids_sha256") == PRE_HASH

    id_map = list(baseline.get("id_map") or [])
    src_to_gates = {int(e["source_id"]): str(e["gates_id"]) for e in id_map}
    gates_to_src = {str(e["gates_id"]): int(e["source_id"]) for e in id_map}
    removed = [e for e in id_map if int(e["source_id"]) in EXCLUDE_SOURCE_IDS]
    assert {e["gates_id"] for e in removed} == EXCLUDE_GATES, removed
    retained_map = [e for e in id_map if int(e["source_id"]) not in EXCLUDE_SOURCE_IDS]

    # Snapshot pre-exclusion geometry for island identity checks
    baseline_by_src = {int(p["source_id"]): deepcopy(p) for p in baseline["provinces"]}

    provinces_out: list[dict] = []
    for p in baseline["provinces"]:
        sid = int(p["source_id"])
        if sid in EXCLUDE_SOURCE_IDS:
            continue
        gid = p["id"]
        assert src_to_gates[sid] == gid
        row = deepcopy(p)
        row["neighbors"] = [
            n
            for n in (row.get("neighbors") or [])
            if n in gates_to_src and int(gates_to_src[n]) not in EXCLUDE_SOURCE_IDS
        ]
        provinces_out.append(row)

    out_by_src = {int(p["source_id"]): p for p in provinces_out}
    for sid in KEEP_ISLAND_SOURCE_IDS:
        assert sid in out_by_src
        b = baseline_by_src[sid]
        assert out_by_src[sid]["ring"] == b["ring"]
        assert out_by_src[sid]["vertices"] == b["vertices"]
        assert out_by_src[sid]["triangles"] == b["triangles"]

    # Empty mesh / triangulation checks
    empty = []
    for p in provinces_out:
        if len(p.get("vertices") or []) < 6 or len(p.get("triangles") or []) < 3:
            empty.append(p["id"])
    assert not empty, empty[:10]

    edges: list[list[str]] = []
    seen: set[tuple[str, str]] = set()
    adj_broken: list[dict] = []
    retained_ids = {p["id"] for p in provinces_out}
    for p in provinces_out:
        a = p["id"]
        for b in p.get("neighbors") or []:
            if b not in retained_ids:
                adj_broken.append({"id": a, "neighbor": b})
                continue
            key = (a, b) if a < b else (b, a)
            if key in seen:
                continue
            seen.add(key)
            edges.append([key[0], key[1]])
    assert not adj_broken, adj_broken[:10]

    land = sum(1 for p in provinces_out if not p.get("is_water"))
    water = sum(1 for p in provinces_out if p.get("is_water"))
    retained_sources = sorted(int(p["source_id"]) for p in provinces_out)
    inc_hash = included_ids_hash(retained_sources)

    payload = deepcopy(baseline)
    payload["province_count"] = len(provinces_out)
    payload["land_count"] = land
    payload["water_count"] = water
    payload["provinces"] = provinces_out
    payload["edges"] = edges
    payload["edge_count"] = len(edges)
    payload["id_map"] = retained_map
    payload["pre_sanitize_included_ids_sha256"] = PRE_HASH
    payload["included_source_ids_sha256"] = inc_hash
    payload["approved_included_ids_sha256"] = inc_hash
    payload["vertex_count"] = sum(len(p.get("vertices") or []) // 2 for p in provinces_out)
    payload["triangle_count"] = sum(len(p.get("triangles") or []) // 3 for p in provinces_out)
    # Preserve triangulation_audit structure; mark promotion
    tri = dict(payload.get("triangulation_audit") or {})
    tri["promotion"] = {
        "excluded_source_ids": sorted(EXCLUDE_SOURCE_IDS),
        "excluded_gates_ids": sorted(EXCLUDE_GATES),
        "stable_ids": True,
        "island_geometry_unchanged": True,
        "empty_mesh_count": 0,
    }
    payload["triangulation_audit"] = tri
    payload["sanitization"] = {
        "enabled": True,
        "excluded_source_ids": sorted(EXCLUDE_SOURCE_IDS),
        "excluded_gates_ids": sorted(EXCLUDE_GATES),
        "stable_ids": True,
        "visual_geometry_overrides": [],
        "water_policy": "water_not_normally_selectable",
        "owner_approved_issue": 117,
        "supersedes_preview_pr": 120,
    }

    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    ds_sha = _sha256_text(text)
    src_path.write_text(text + "\n", encoding="utf-8")

    manifest = {
        "schema": "gates-of-codex.strategic-map",
        "schema_version": 1,
        "map_id": "earth3_europe_mediterranean",
        "renderer": "polygon_mesh",
        "provenance": "earth3_v7_europe_asia_boundary_minus_eastern_spill",
        "asset_status": "production_theatre",
        "polygon_dataset": {
            "path": "polygon_dataset.json",
            "sha256": ds_sha,
            "province_count": len(provinces_out),
        },
        "province_count": len(provinces_out),
        "bounds": payload["bounds"],
        "fallback_map_id": "europe_mediterranean_from_goe",
        "runtime_contract": {
            "gameplay_key": "province_id",
            "hit_test": "point_in_polygon_spatial_index",
            "ownership_update": "immutable_geometry_shader_lookup",
        },
        "pre_sanitize_included_ids_sha256": PRE_HASH,
        "included_source_ids_sha256": inc_hash,
        "approved_included_ids_sha256": inc_hash,
        "stable_id_policy": "retain_production_e3_ids_with_gaps",
        "water_policy": "water_not_normally_selectable",
        "export": {
            "excluded_source_ids": sorted(EXCLUDE_SOURCE_IDS),
            "excluded_gates_ids": sorted(EXCLUDE_GATES),
            "triangulation_ok": True,
            "empty_meshes": 0,
        },
    }
    (PROD / "map_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    meta = {
        "map_id": "earth3_europe_mediterranean",
        "province_count": len(provinces_out),
        "land_count": land,
        "water_count": water,
        "selectable_province_count": land,
        "source_water_metadata_count": water,
        "vertex_count": payload["vertex_count"],
        "triangle_count": payload["triangle_count"],
        "edge_count": len(edges),
        "border_segment_count": payload.get("border_segment_count"),
        "pre_sanitize_included_ids_sha256": PRE_HASH,
        "included_source_ids_sha256": inc_hash,
        "approved_included_ids_sha256": inc_hash,
        "dataset_sha256": ds_sha,
        "bounds": payload["bounds"],
        "triangulation_audit": tri,
        "sanitization": payload["sanitization"],
        "water_policy": "water_not_normally_selectable",
        "stable_ids": True,
        "sample_province_ids": [p["id"] for p in provinces_out[:5]],
        "sample_source_ids": [p["source_id"] for p in provinces_out[:5]],
    }
    (PROD / "dataset_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (PROD / "triangulation_audit.json").write_text(json.dumps(tri, indent=2) + "\n", encoding="utf-8")

    auth = {
        "schema": "gates-of-codex.earth3-production-authority",
        "schema_version": 2,
        "status": "production",
        "map_id": "earth3_europe_mediterranean",
        "province_count": len(provinces_out),
        "land_count": land,
        "water_count": water,
        "selectable_province_count": land,
        "source_water_metadata_count": water,
        "included_ids_sha256": inc_hash,
        "pre_sanitize_included_ids_sha256": PRE_HASH,
        "dataset_sha256": ds_sha,
        "excluded_source_ids": sorted(EXCLUDE_SOURCE_IDS),
        "excluded_gates_ids": sorted(EXCLUDE_GATES),
        "stable_id_policy": "retain_e3_ids_with_permanent_gaps",
        "water_policy": {
            "v1": "water_not_normally_selectable",
            "accepted": True,
            "normal_click_returns": "no_province",
            "source_water_ids": "import_metadata_only",
            "sea_movement": "authored_operational_nodes_edges",
        },
        "topology_sanitize": {
            "land_exclusions_accepted": True,
            "approved_exclusions": sorted(EXCLUDE_SOURCE_IDS),
            "island_geometry": "unchanged",
            "issue": 117,
        },
        "notes": [
            "Production authority after owner-approved eastern spill exclusions.",
            "e3_2830 and e3_2888 are permanent unused gaps; never recycle.",
            "Island coastline reconstruction remains #121.",
        ],
    }
    AUTH.write_text(json.dumps(auth, indent=2) + "\n", encoding="utf-8")

    (PROD / "README.md").write_text(
        "\n".join(
            [
                "# Earth3 Europe–Mediterranean production theatre",
                "",
                f"| Field | Value |",
                f"|---|---|",
                f"| provinces | **{len(provinces_out)}** |",
                f"| land / water metadata | **{land} / {water}** |",
                f"| included_ids_sha256 | `{inc_hash}` |",
                f"| pre-exclusion hash | `{PRE_HASH}` |",
                f"| excluded | source 10920 (`e3_2830`), 11031 (`e3_2888`) |",
                f"| stable IDs | retained e3_*; gaps never recycled |",
                f"| water policy | non-selectable (accepted) |",
                f"| island geometry | unchanged (coastline work: #121) |",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # Stable-ID + fixture reports
    gameplay_refs: list[str] = []
    for path in FIXTURES.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        _collect_gameplay_ids(data, gameplay_refs)
    gameplay_refs = sorted(set(gameplay_refs))
    bad = [r for r in gameplay_refs if r in EXCLUDE_GATES]
    missing = [
        r
        for r in gameplay_refs
        if r.startswith("e3_") and r not in retained_ids and r not in EXCLUDE_GATES
    ]

    stable = {
        "schema": "gates-of-codex.earth3-stable-id-validation",
        "pre_hash": PRE_HASH,
        "production_hash": inc_hash,
        "province_count": len(provinces_out),
        "land_count": land,
        "water_count": water,
        "removed": removed,
        "retained_mapping_count": len(retained_map),
        "checks": {
            "retained_source_ids_keep_same_gates_id": True,
            "removed_ids_are_permanent_gaps": True,
            "no_global_renumber": True,
            "adjacency_resolved": True,
            "empty_meshes": 0,
            "island_geometry_unchanged": True,
            "fixtures_no_excluded_gameplay_refs": not bad,
        },
        "fixture_gameplay_refs_to_excluded": bad,
        "fixture_missing_retained_refs": missing,
    }
    for e in retained_map:
        sid = int(e["source_id"])
        gid = str(e["gates_id"])
        assert next(p for p in provinces_out if int(p["source_id"]) == sid)["id"] == gid

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "stable_id_report.json").write_text(json.dumps(stable, indent=2) + "\n", encoding="utf-8")
    (EVIDENCE / "fixture_migration_report.json").write_text(
        json.dumps(
            {
                "excluded_gates": sorted(EXCLUDE_GATES),
                "gameplay_refs_scanned": len(gameplay_refs),
                "refs_to_excluded_before_rebuild": bad,
                "missing_retained_refs_before_rebuild": missing,
                "action": "rebuild snapshots/fixtures after dataset promotion",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (PROD / "stable_id_validation.json").write_text(json.dumps(stable, indent=2) + "\n", encoding="utf-8")

    _render_evidence(baseline, payload, removed)

    print(
        json.dumps(
            {
                "ok": True,
                "province_count": len(provinces_out),
                "land_count": land,
                "water_count": water,
                "included_ids_sha256": inc_hash,
                "dataset_sha256": ds_sha,
                "excluded": removed,
            },
            indent=2,
        )
    )
    return 0


def _render_evidence(before: dict, after: dict, removed: list) -> None:
    from PIL import Image, ImageDraw

    def draw(data: dict, path: Path, title: str, highlight: set[str] | None = None, only: set[str] | None = None):
        b = data["bounds"]
        bw, bh = float(b["width"]), float(b["height"])
        W, H = 1920, 1080
        margin = 24
        s = min((W - 2 * margin) / bw, (H - 2 * margin) / bh)
        ox = margin + (W - 2 * margin - bw * s) * 0.5
        oy = margin + (H - 2 * margin - bh * s) * 0.5
        img = Image.new("RGB", (W, H), (18, 32, 48))
        dr = ImageDraw.Draw(img)
        for p in data["provinces"]:
            if p.get("is_water"):
                continue
            gid = p["id"]
            if only is not None and gid not in only:
                continue
            pts = _ring_pts(p)
            if len(pts) < 3:
                continue
            sp = [(ox + x * s, oy + y * s) for x, y in pts]
            fill = (220, 70, 70) if highlight and gid in highlight else (120, 126, 132)
            dr.polygon(sp, fill=fill, outline=(40, 44, 50))
        dr.text((16, 10), title, fill=(240, 240, 240))
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path)

    removed_g = {e["gates_id"] for e in removed}
    draw(before, EVIDENCE / "full_theatre_before_3512.png", "BEFORE 3512 (excluded highlighted)", highlight=removed_g)
    draw(after, EVIDENCE / "full_theatre_after_3510.png", f"AFTER production {after['province_count']}")
    by_b = {p["id"]: p for p in before["provinces"]}
    for e in removed:
        gid = e["gates_id"]
        p = by_b[gid]
        cx, cy = p["centroid"]
        near = {
            q["id"]
            for q in before["provinces"]
            if not q.get("is_water")
            and abs(q["centroid"][0] - cx) < 220
            and abs(q["centroid"][1] - cy) < 220
        }
        draw(
            before,
            EVIDENCE / f"{gid}_before.png",
            f"BEFORE {gid} src={e['source_id']}",
            highlight={gid},
            only=near,
        )
        draw(
            after,
            EVIDENCE / f"{gid}_after.png",
            f"AFTER removed {gid}",
            only=near - {gid},
        )
    # eastern boundary crop of after
    draw(
        after,
        EVIDENCE / "eastern_boundary_after.png",
        "Eastern boundary after spill removal",
        only={
            p["id"]
            for p in after["provinces"]
            if not p.get("is_water") and float(p["centroid"][0]) > float(after["bounds"]["width"]) * 0.75
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
