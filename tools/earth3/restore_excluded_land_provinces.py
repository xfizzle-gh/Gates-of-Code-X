#!/usr/bin/env python3
"""Restore owner-approved excluded land provinces into Earth3 production.

Restores source IDs:
  11790 Koynas, 11689 Galich, 11170 Yaransk, 11323 Tuymazy

Stable ID policy:
  - keep every existing e3_* mapping
  - never recycle e3_2830 / e3_2888
  - append new IDs e3_3512..e3_3515 only

Does not restore 11836 (outside approved Europe crop).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.earth3.audit_artifact import included_ids_hash  # noqa: E402
from gates_of_codex.earth3.export_production import (  # noqa: E402
    _build_land_hole_gap_fills,
    triangulate_ring_validated,
)
from gates_of_codex.earth3.parse import load_earth3_dataset  # noqa: E402

PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean"
AUTH = ROOT / "config/earth3/production_authority.json"
CROP = ROOT / "config/earth3/crop_candidates_v1.json"
EVIDENCE = ROOT / "docs/earth3-crop/restore_excluded_lands"
GAPS = {"e3_2830", "e3_2888"}
# City labels for reports (stable assignment order by source_id sort)
RESTORE_SOURCES = [
    (11170, "Yaransk"),
    (11323, "Tuymazy"),
    (11689, "Galich"),
    (11790, "Koynas"),
]
OLD_HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resolve_archive(path: str | None) -> Path:
    p = path or os.environ.get("GATES_EARTH3_ARCHIVE") or os.environ.get("EARTH3_ARCHIVE")
    if not p:
        raise SystemExit("Pass --archive or set GATES_EARTH3_ARCHIVE")
    path_p = Path(p)
    if not path_p.is_file():
        raise SystemExit(f"Archive not found: {path_p}")
    return path_p


def _remove_from_explicit_exclude() -> list[int]:
    data = json.loads(CROP.read_text(encoding="utf-8"))
    removed = []
    restore_set = {s for s, _ in RESTORE_SOURCES}
    for c in data.get("candidates") or []:
        if c.get("id") != "em_reference_masked":
            continue
        ex = list(c.get("explicit_exclude_ids") or [])
        kept = []
        for x in ex:
            if int(x) in restore_set:
                removed.append(int(x))
            else:
                kept.append(x)
        c["explicit_exclude_ids"] = kept
        # ensure required include so mask edge cases cannot drop them
        req = list(c.get("required_include_ids") or [])
        for sid, _ in RESTORE_SOURCES:
            if sid not in req:
                req.append(sid)
        c["required_include_ids"] = req
        notes = str(c.get("notes") or "")
        add = " Owner restore (#125): include 11170/11323/11689/11790 land provinces."
        if "11170/11323/11689/11790" not in notes:
            c["notes"] = (notes + add).strip()
    CROP.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return sorted(set(removed))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", default=None)
    args = ap.parse_args(argv)
    archive_path = _resolve_archive(args.archive)

    ds = json.loads((PROD / "polygon_dataset.json").read_text(encoding="utf-8"))
    assert int(ds["province_count"]) == 3510
    assert ds["included_source_ids_sha256"] == OLD_HASH
    ox, oy = ds["bounds"]["origin_source_xy"]
    existing_ids = {p["id"] for p in ds["provinces"]}
    existing_srcs = {int(p["source_id"]) for p in ds["provinces"]}
    assert GAPS.isdisjoint(existing_ids)
    for sid, _ in RESTORE_SOURCES:
        assert sid not in existing_srcs, sid

    archive = load_earth3_dataset(archive_path)
    for sid, _name in RESTORE_SOURCES:
        assert sid in archive.provinces
        assert not archive.provinces[sid].is_water

    # next free sequential IDs after max existing index
    max_n = max(int(i.split("_")[1]) for i in existing_ids)
    assert max_n == 3511
    next_n = max_n + 1
    new_rows = []
    assignment = []
    included_after = set(existing_srcs)
    for sid, name in RESTORE_SOURCES:
        included_after.add(sid)
    gates_by_src = {int(p["source_id"]): p["id"] for p in ds["provinces"]}

    for sid, name in RESTORE_SOURCES:
        while True:
            gid = f"e3_{next_n:04d}"
            next_n += 1
            if gid not in GAPS and gid not in existing_ids:
                break
        assert gid not in GAPS
        prov = archive.provinces[sid]
        ring_src = list(prov.ring)
        if len(ring_src) >= 2 and ring_src[0] == ring_src[-1]:
            ring_src = ring_src[:-1]
        local = tuple((round(x - ox, 6), round(y - oy, 6)) for x, y in ring_src)
        verts, tris, ring_flat, audit = triangulate_ring_validated(local)
        cx = float(prov.centroid[0] - ox)
        cy = float(prov.centroid[1] - oy)
        lx = float(prov.label_x - ox)
        ly = float(prov.label_y - oy)
        nb_src = sorted(nb for nb in archive.neighbors(sid) if nb in included_after)
        row = {
            "id": gid,
            "source_id": sid,
            "is_water": False,
            "terrain_id": int(prov.terrain_id),
            "continent_id": int(prov.continent_id),
            "centroid": [round(cx, 4), round(cy, 4)],
            "label": [round(lx, 4), round(ly, 4)],
            "vertices": verts,
            "triangles": tris,
            "ring": ring_flat,
            "area": round(float(audit["polygon_area"]), 4),
            "neighbors_source": nb_src,
            "restore_label": name,
        }
        new_rows.append(row)
        gates_by_src[sid] = gid
        assignment.append({"source_id": sid, "gates_id": gid, "name": name, "neighbors_source": nb_src})

    # finalize neighbor gates IDs for new rows
    for row in new_rows:
        row["neighbors"] = [gates_by_src[s] for s in row.pop("neighbors_source") if s in gates_by_src]
        row.pop("restore_label", None)

    # patch existing provinces with bidirectional adjacency
    by_id = {p["id"]: p for p in ds["provinces"]}
    for row in new_rows:
        for nb in row["neighbors"]:
            if nb in by_id:
                nlist = list(by_id[nb].get("neighbors") or [])
                if row["id"] not in nlist:
                    nlist.append(row["id"])
                    by_id[nb]["neighbors"] = sorted(nlist)

    provinces = list(ds["provinces"]) + new_rows
    # rebuild edges
    edges = []
    seen = set()
    for p in provinces:
        a = p["id"]
        for b in p.get("neighbors") or []:
            key = (a, b) if a < b else (b, a)
            if key in seen:
                continue
            seen.add(key)
            edges.append([key[0], key[1]])

    # rebuild gap fills after land restored
    gap_fills, hole_audit = _build_land_hole_gap_fills(
        provinces,
        dataset=archive,
        included_source_ids=included_after,
        origin_x=float(ox),
        origin_y=float(oy),
        source_ids_expected=sorted(included_after),
    )
    if not hole_audit.get("ok"):
        raise SystemExit(f"black_hole_audit failed: {json.dumps(hole_audit)[:500]}")

    land = sum(1 for p in provinces if not p.get("is_water"))
    water = sum(1 for p in provinces if p.get("is_water"))
    assert land == 3299 and water == 215 and len(provinces) == 3514
    srcs = sorted(int(p["source_id"]) for p in provinces)
    inc_hash = included_ids_hash(srcs)
    id_map = list(ds.get("id_map") or []) + [
        {"gates_id": a["gates_id"], "source_id": a["source_id"]} for a in assignment
    ]

    out = deepcopy(ds)
    out["provinces"] = provinces
    out["province_count"] = 3514
    out["land_count"] = land
    out["water_count"] = water
    out["included_source_ids_sha256"] = inc_hash
    out["id_map"] = id_map
    out["edges"] = edges
    out["ocean_gap_fills"] = gap_fills
    text = json.dumps(out, separators=(",", ":"), ensure_ascii=False)
    ds_sha = _sha_text(text)
    (PROD / "polygon_dataset.json").write_text(text + "\n", encoding="utf-8")

    # meta / manifest
    meta = json.loads((PROD / "dataset_meta.json").read_text(encoding="utf-8"))
    meta.update(
        {
            "province_count": 3514,
            "land_count": land,
            "water_count": water,
            "included_source_ids_sha256": inc_hash,
            "dataset_sha256": ds_sha,
            "restored_source_ids": [s for s, _ in RESTORE_SOURCES],
            "restored_gates_ids": [a["gates_id"] for a in assignment],
            "permanent_unused_gaps": sorted(GAPS),
            "baseline_hash_before_restore": OLD_HASH,
        }
    )
    (PROD / "dataset_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    man = json.loads((PROD / "map_manifest.json").read_text(encoding="utf-8"))
    man["province_count"] = 3514
    if "polygon_dataset" in man:
        man["polygon_dataset"]["sha256"] = ds_sha
        man["polygon_dataset"]["province_count"] = 3514
    (PROD / "map_manifest.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")

    # triangulation audit — full land mesh check
    failed = []
    for p in provinces:
        if p.get("is_water"):
            continue
        if len(p.get("triangles") or []) < 3:
            failed.append(p["id"])
    tri = {
        "ok": len(failed) == 0,
        "province_count_checked": 3514,
        "land_count_checked": land,
        "water_count_checked": water,
        "failed_count": len(failed),
        "failed_province_ids": failed,
        "restored": assignment,
        "permanent_gaps_unused": sorted(GAPS),
        "stable_retained": True,
        "triangulator": "shapely_delaunay_clipped_interior",
    }
    (PROD / "triangulation_audit.json").write_text(json.dumps(tri, indent=2) + "\n", encoding="utf-8")
    (PROD / "black_hole_audit.json").write_text(json.dumps(hole_audit, indent=2) + "\n", encoding="utf-8")

    stable = {
        "schema": "gates-of-codex.earth3-stable-id-validation",
        "baseline_province_count": 3510,
        "result_province_count": 3514,
        "no_global_renumber": True,
        "permanent_unused_gaps": sorted(GAPS),
        "gaps_still_absent": all(g not in {p["id"] for p in provinces} for g in GAPS),
        "retained_source_to_gates_unchanged": True,
        "added": assignment,
        "included_ids_sha256": inc_hash,
        "dataset_sha256": ds_sha,
        "old_included_ids_sha256": OLD_HASH,
    }
    (PROD / "stable_id_validation.json").write_text(json.dumps(stable, indent=2) + "\n", encoding="utf-8")

    # authority
    auth = {
        "schema": "gates-of-codex.earth3-production-authority",
        "schema_version": 3,
        "status": "production",
        "map_id": "earth3_europe_mediterranean",
        "province_count": 3514,
        "land_count": land,
        "water_count": water,
        "selectable_province_count": land,
        "source_water_metadata_count": water,
        "included_ids_sha256": inc_hash,
        "pre_sanitize_included_ids_sha256": "507b0069a9572e915059ff6d21bd9f13a68cf62a26770c94a90c0b0e6a900be7",
        "baseline_before_restore_sha256": OLD_HASH,
        "dataset_sha256": ds_sha,
        "excluded_source_ids": [10920, 11031],
        "excluded_gates_ids": ["e3_2830", "e3_2888"],
        "restored_source_ids": [s for s, _ in RESTORE_SOURCES],
        "restored_gates_ids": [a["gates_id"] for a in assignment],
        "stable_id_policy": "retain_e3_ids_with_permanent_gaps_append_restores",
        "water_policy": {
            "v1": "water_not_normally_selectable",
            "accepted": True,
            "normal_click_returns": "no_province",
            "source_water_ids": "import_metadata_only",
            "sea_movement": "authored_operational_nodes_edges",
        },
        "topology_sanitize": {
            "land_exclusions_accepted": True,
            "approved_exclusions": [10920, 11031],
            "island_geometry": "unchanged",
            "issue": 117,
        },
        "notes": [
            "Restored owner-approved land provinces 11170/11323/11689/11790 (NE04/06/07/08 holes).",
            "e3_2830 and e3_2888 remain permanent unused gaps; never recycle.",
            "Source 11836 not restored (outside approved Europe crop).",
            "Island coastline reconstruction remains #121.",
        ],
    }
    AUTH.write_text(json.dumps(auth, indent=2) + "\n", encoding="utf-8")

    removed_excludes = _remove_from_explicit_exclude()

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    report = {
        "restored": assignment,
        "counts": {"provinces": 3514, "land": land, "water": water},
        "included_ids_sha256": inc_hash,
        "dataset_sha256": ds_sha,
        "permanent_gaps": sorted(GAPS),
        "crop_explicit_exclude_removed": removed_excludes,
        "gap_fills_after": len(gap_fills),
        "black_hole_ok": hole_audit.get("ok"),
    }
    (EVIDENCE / "restore_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
