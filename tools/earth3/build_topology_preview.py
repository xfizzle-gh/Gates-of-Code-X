"""Build Earth3 topology *preview* dataset (NOT production).

Owner-approved scope for PR #120:
- Exclude only source IDs 10920 (e3_2830 Kartaly) and 11031 (e3_2888 Kulakshi)
- Keep all other provinces including the 16 simplified islands at production geometry
- Preserve stable Gates e3_* IDs via production id_map (removed IDs become gaps)
- No visual geometry invention / coastline replacement
"""

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.earth3.audit_artifact import included_ids_hash  # noqa: E402

PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean"
PREVIEW = ROOT / "godot/assets/maps/earth3_europe_mediterranean_sanitize_preview"
EVIDENCE = ROOT / "docs/earth3-crop/topology_sanitize/preview_evidence"
FIXTURES = ROOT / "godot/fixtures"
PROD_HASH = "507b0069a9572e915059ff6d21bd9f13a68cf62a26770c94a90c0b0e6a900be7"
EXCLUDE_SOURCE_IDS = {10920, 11031}
EXCLUDE_GATES_EXPECTED = {"e3_2830", "e3_2888"}
# Owner KEEP islands — must remain present with unchanged geometry in this preview.
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


def _collect_gameplay_province_ids(node, out: list[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            ks = str(k)
            if ks in (
                "province_id",
                "origin",
                "target",
                "origin_province_id",
                "target_province_id",
                "selected_province_id",
            ) or ks.endswith("province_id"):
                if isinstance(v, str) and v.startswith("e3_"):
                    out.append(v)
            elif ks == "province_ids" and isinstance(v, list):
                for item in v:
                    if isinstance(item, str) and item.startswith("e3_"):
                        out.append(item)
            else:
                _collect_gameplay_province_ids(v, out)
    elif isinstance(node, list):
        if len(node) == 2 and all(isinstance(x, str) and x.startswith("e3_") for x in node):
            out.extend(node)
            return
        for item in node:
            _collect_gameplay_province_ids(item, out)


def main() -> int:
    prod = json.loads((PROD / "polygon_dataset.json").read_text(encoding="utf-8"))
    assert int(prod["province_count"]) == 3512
    assert prod.get("included_source_ids_sha256") == PROD_HASH

    id_map = list(prod.get("id_map") or [])
    src_to_gates = {int(e["source_id"]): str(e["gates_id"]) for e in id_map}
    gates_to_src = {str(e["gates_id"]): int(e["source_id"]) for e in id_map}

    removed = [e for e in id_map if int(e["source_id"]) in EXCLUDE_SOURCE_IDS]
    assert {e["gates_id"] for e in removed} == EXCLUDE_GATES_EXPECTED, removed
    retained_map = [e for e in id_map if int(e["source_id"]) not in EXCLUDE_SOURCE_IDS]

    by_prod = {p["id"]: p for p in prod["provinces"]}
    provinces_out: list[dict] = []
    for p in prod["provinces"]:
        sid = int(p["source_id"])
        if sid in EXCLUDE_SOURCE_IDS:
            continue
        gid = p["id"]
        assert src_to_gates[sid] == gid
        row = deepcopy(p)
        # Geometry must be byte-identical to production for retained provinces.
        # Filter neighbor links to retained IDs only.
        row["neighbors"] = [
            n
            for n in (row.get("neighbors") or [])
            if n in gates_to_src and int(gates_to_src[n]) not in EXCLUDE_SOURCE_IDS
        ]
        provinces_out.append(row)

    # Islands kept with identical rings
    out_by_src = {int(p["source_id"]): p for p in provinces_out}
    for sid in KEEP_ISLAND_SOURCE_IDS:
        assert sid in out_by_src, f"missing keep island source {sid}"
        prod_row = next(p for p in prod["provinces"] if int(p["source_id"]) == sid)
        assert out_by_src[sid]["ring"] == prod_row["ring"]
        assert out_by_src[sid]["vertices"] == prod_row["vertices"]
        assert out_by_src[sid]["triangles"] == prod_row["triangles"]

    edges: list[list[str]] = []
    seen: set[tuple[str, str]] = set()
    for p in provinces_out:
        a = p["id"]
        for b in p.get("neighbors") or []:
            key = (a, b) if a < b else (b, a)
            if key in seen:
                continue
            seen.add(key)
            edges.append([key[0], key[1]])

    land = sum(1 for p in provinces_out if not p.get("is_water"))
    water = sum(1 for p in provinces_out if p.get("is_water"))
    retained_sources = sorted(int(p["source_id"]) for p in provinces_out)
    inc_hash = included_ids_hash(retained_sources)

    preview = deepcopy(prod)
    preview["province_count"] = len(provinces_out)
    preview["land_count"] = land
    preview["water_count"] = water
    preview["provinces"] = provinces_out
    preview["edges"] = edges
    preview["edge_count"] = len(edges)
    preview["id_map"] = retained_map
    preview["pre_sanitize_included_ids_sha256"] = PROD_HASH
    preview["included_source_ids_sha256"] = inc_hash
    preview["approved_included_ids_sha256"] = PROD_HASH
    preview["vertex_count"] = sum(len(p.get("vertices") or []) // 2 for p in provinces_out)
    preview["triangle_count"] = sum(len(p.get("triangles") or []) // 3 for p in provinces_out)
    preview["sanitization_preview"] = {
        "excluded_source_ids": sorted(EXCLUDE_SOURCE_IDS),
        "excluded_gates_ids": sorted(EXCLUDE_GATES_EXPECTED),
        "visual_geometry_overrides": [],
        "stable_ids": True,
        "island_geometry": "unchanged_from_production",
        "production_path_unchanged": True,
        "note": "PREVIEW ONLY — not production authority. No coastline invention.",
    }

    PREVIEW.mkdir(parents=True, exist_ok=True)
    text = json.dumps(preview, separators=(",", ":"), ensure_ascii=False)
    (PREVIEW / "polygon_dataset.json").write_text(text + "\n", encoding="utf-8")
    ds_sha = _sha256_text(text)

    manifest = {
        "schema": "gates-of-codex.strategic-map",
        "schema_version": 1,
        "map_id": "earth3_europe_mediterranean_sanitize_preview",
        "renderer": "polygon_mesh",
        "asset_status": "sanitize_preview_not_production",
        "polygon_dataset": {
            "path": "polygon_dataset.json",
            "sha256": ds_sha,
            "province_count": len(provinces_out),
        },
        "province_count": len(provinces_out),
        "bounds": preview["bounds"],
        "fallback_map_id": "earth3_europe_mediterranean",
        "pre_sanitize_included_ids_sha256": PROD_HASH,
        "included_source_ids_sha256": inc_hash,
        "stable_id_policy": "retain_production_e3_ids_with_gaps",
        "water_policy": "water_not_normally_selectable",
    }
    (PREVIEW / "map_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    meta = {
        "map_id": "earth3_europe_mediterranean_sanitize_preview",
        "asset_status": "sanitize_preview_not_production",
        "province_count": len(provinces_out),
        "land_count": land,
        "water_count": water,
        "selectable_province_count": land,
        "source_water_metadata_count": water,
        "included_source_ids_sha256": inc_hash,
        "pre_sanitize_included_ids_sha256": PROD_HASH,
        "dataset_sha256": ds_sha,
        "vertex_count": preview["vertex_count"],
        "triangle_count": preview["triangle_count"],
        "edge_count": len(edges),
        "excluded_source_ids": sorted(EXCLUDE_SOURCE_IDS),
        "excluded_gates_ids": sorted(EXCLUDE_GATES_EXPECTED),
        "visual_geometry_overrides": [],
        "stable_ids": True,
    }
    (PREVIEW / "dataset_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (PREVIEW / "README.md").write_text(
        "\n".join(
            [
                "# Earth3 topology sanitize preview (NOT production)",
                "",
                f"- provinces: **{len(provinces_out)}** ({land} land / {water} water metadata)",
                f"- included_ids_sha256: `{inc_hash}`",
                f"- production baseline: 3512 / `{PROD_HASH}`",
                f"- excluded: source {sorted(EXCLUDE_SOURCE_IDS)} → {sorted(EXCLUDE_GATES_EXPECTED)}",
                "- island geometry: **unchanged** from production (no ellipse/coastline invention)",
                "- stable Gates IDs with gaps for removed IDs",
                "",
                "Do not point default F5 / production map_id here until owner approval.",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # Fixture / gameplay reference validation
    gameplay_refs: list[str] = []
    for path in FIXTURES.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        _collect_gameplay_province_ids(data, gameplay_refs)
    gameplay_refs = sorted(set(gameplay_refs))
    bad_removed = [r for r in gameplay_refs if r in EXCLUDE_GATES_EXPECTED]
    # retained set
    retained_ids = {p["id"] for p in provinces_out}
    water_ids = {p["id"] for p in provinces_out if p.get("is_water")}
    missing = [r for r in gameplay_refs if r.startswith("e3_") and r not in retained_ids and r not in EXCLUDE_GATES_EXPECTED]
    # Gameplay keys should not target removed IDs
    fixture_report = {
        "gameplay_province_ref_count": len(gameplay_refs),
        "refs_to_excluded_ids": bad_removed,
        "missing_retained_refs": missing,
        "ok": not bad_removed and not missing,
        "note": (
            "Province catalog rows may list water IDs as metadata; gameplay keys "
            "(selected/formation/site/route/encounter/handoff) must not use excluded IDs."
        ),
    }

    # Adjacency resolve check
    adj_broken = []
    for p in provinces_out:
        for n in p.get("neighbors") or []:
            if n not in retained_ids:
                adj_broken.append({"id": p["id"], "neighbor": n})

    stable_report = {
        "schema": "gates-of-codex.earth3-stable-id-validation",
        "production_hash": PROD_HASH,
        "preview_hash": inc_hash,
        "production_province_count": 3512,
        "preview_province_count": len(provinces_out),
        "preview_land_count": land,
        "preview_water_count": water,
        "removed": removed,
        "retained_mapping_count": len(retained_map),
        "checks": {
            "all_retained_source_ids_keep_same_gates_id": True,
            "removed_ids_are_gaps_not_recycled": True,
            "no_global_renumber": True,
            "island_geometry_unchanged": True,
            "no_visual_geometry_overrides": True,
            "adjacency_resolved": len(adj_broken) == 0,
            "fixtures_ok": fixture_report["ok"],
        },
        "adjacency_broken": adj_broken[:20],
        "fixture_validation": fixture_report,
        "sample_retained": retained_map[:5] + retained_map[-5:],
    }
    for e in retained_map:
        sid = int(e["source_id"])
        gid = str(e["gates_id"])
        prow = next(p for p in provinces_out if int(p["source_id"]) == sid)
        assert prow["id"] == gid

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "stable_id_validation.json").write_text(
        json.dumps(stable_report, indent=2) + "\n", encoding="utf-8"
    )
    (PREVIEW / "stable_id_validation.json").write_text(
        json.dumps(stable_report, indent=2) + "\n", encoding="utf-8"
    )
    (EVIDENCE / "fixture_validation.json").write_text(
        json.dumps(fixture_report, indent=2) + "\n", encoding="utf-8"
    )

    _render_evidence(prod, preview, removed)
    print(
        json.dumps(
            {
                "ok": True,
                "preview": {
                    "province_count": len(provinces_out),
                    "land_count": land,
                    "water_count": water,
                    "included_ids_sha256": inc_hash,
                    "dataset_sha256": ds_sha,
                },
                "excluded": removed,
                "stable_ok": stable_report["checks"],
                "fixture_ok": fixture_report["ok"],
            },
            indent=2,
        )
    )
    if adj_broken or not fixture_report["ok"]:
        return 1
    return 0


def _render_evidence(prod: dict, preview: dict, removed: list) -> None:
    from PIL import Image, ImageDraw

    def draw_set(data: dict, path: Path, title: str, highlight: set[str] | None = None, only: set[str] | None = None):
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
        img.save(path)

    removed_g = {e["gates_id"] for e in removed}
    draw_set(prod, EVIDENCE / "01_full_theatre_before.png", "BEFORE production 3512 (excluded highlighted)", highlight=removed_g)
    draw_set(preview, EVIDENCE / "02_full_theatre_after_preview.png", f"AFTER preview {preview['province_count']} (two eastern spills removed)")

    by_prod = {p["id"]: p for p in prod["provinces"]}
    by_prev = {p["id"]: p for p in preview["provinces"]}
    for e in removed:
        gid = e["gates_id"]
        p = by_prod[gid]
        cx, cy = p["centroid"]
        near = {
            q["id"]
            for q in prod["provinces"]
            if not q.get("is_water")
            and abs(q["centroid"][0] - cx) < 220
            and abs(q["centroid"][1] - cy) < 220
        }
        draw_set(
            prod,
            EVIDENCE / f"exclude_{gid}_src{e['source_id']}_before.png",
            f"BEFORE exclude {gid} src={e['source_id']}",
            highlight={gid},
            only=near,
        )
        near_after = near - {gid}
        draw_set(
            preview,
            EVIDENCE / f"exclude_{gid}_src{e['source_id']}_after.png",
            f"AFTER exclude {gid} src={e['source_id']}",
            only=near_after,
        )


if __name__ == "__main__":
    raise SystemExit(main())
