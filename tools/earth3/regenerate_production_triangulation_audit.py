"""Regenerate production triangulation_audit.json from the live 3510 dataset."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean"
HIST = ROOT / "docs/earth3-crop/topology_sanitize/historical"
AREA_REL_TOL = 1e-3
EXCLUDE = {"e3_2830", "e3_2888"}
EXPECTED_COUNT = 3510
EXPECTED_HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"


def shoelace(ring_flat: list[float]) -> float:
    pts = [(float(ring_flat[i]), float(ring_flat[i + 1])) for i in range(0, len(ring_flat) - 1, 2)]
    if len(pts) < 3:
        return 0.0
    total = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) * 0.5


def tri_area(verts: list[float], tris: list[int]) -> float:
    area = 0.0
    for t in range(0, len(tris), 3):
        i0, i1, i2 = tris[t], tris[t + 1], tris[t + 2]
        x0, y0 = verts[i0 * 2], verts[i0 * 2 + 1]
        x1, y1 = verts[i1 * 2], verts[i1 * 2 + 1]
        x2, y2 = verts[i2 * 2], verts[i2 * 2 + 1]
        area += abs((x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)) * 0.5
    return area


def main() -> int:
    ds_path = PROD / "polygon_dataset.json"
    data = json.loads(ds_path.read_text(encoding="utf-8"))
    assert int(data["province_count"]) == EXPECTED_COUNT
    assert data.get("included_source_ids_sha256") == EXPECTED_HASH

    # Preserve stale 3512 audit as historical if present and not already archived.
    old_audit_path = PROD / "triangulation_audit.json"
    if old_audit_path.is_file():
        old = json.loads(old_audit_path.read_text(encoding="utf-8"))
        if int(old.get("province_count_checked") or 0) == 3512:
            HIST.mkdir(parents=True, exist_ok=True)
            hist = {
                **old,
                "historical_note": (
                    "Pre-exclusion triangulation audit for the 3512-province dataset "
                    "(hash 507b0069…). Not production authority after Kartaly/Kulakshi removal."
                ),
                "superseded_by": "godot/assets/maps/earth3_europe_mediterranean/triangulation_audit.json",
            }
            (HIST / "triangulation_audit_3512_pre_exclusion.json").write_text(
                json.dumps(hist, indent=2) + "\n", encoding="utf-8"
            )

    failed: list[dict] = []
    poly_sum = 0.0
    tri_sum = 0.0
    max_rel = 0.0
    empty = []
    ids = []
    for p in data["provinces"]:
        pid = p["id"]
        ids.append(pid)
        if pid in EXCLUDE:
            failed.append({"id": pid, "error": "excluded_id_present_in_production"})
            continue
        verts = p.get("vertices") or []
        tris = p.get("triangles") or []
        ring = p.get("ring") or []
        if len(verts) < 6 or len(tris) < 3:
            empty.append(pid)
            failed.append({"id": pid, "error": "empty_or_degenerate_mesh"})
            continue
        pa = float(p.get("area") or shoelace(ring))
        ta = tri_area([float(v) for v in verts], [int(i) for i in tris])
        poly_sum += pa
        tri_sum += ta
        if pa > 0:
            rel = abs(ta - pa) / pa
            max_rel = max(max_rel, rel)
            if rel > AREA_REL_TOL:
                failed.append({"id": pid, "error": f"area_rel_err={rel:.6f}"})

    assert "e3_2830" not in ids and "e3_2888" not in ids
    assert len(ids) == EXPECTED_COUNT
    assert not empty

    audit = {
        "ok": len(failed) == 0,
        "province_count_checked": EXPECTED_COUNT,
        "failed_count": len(failed),
        "failed_province_ids": failed,
        "max_area_error": max_rel,
        "total_polygon_area": poly_sum,
        "total_triangle_area": tri_sum,
        "triangulator": "production_dataset_mesh_revalidation",
        "area_rel_tol": AREA_REL_TOL,
        "no_fan_fallback": True,
        "empty_mesh_count": len(empty),
        "excluded_gates_absent": sorted(EXCLUDE),
        "included_source_ids_sha256": EXPECTED_HASH,
        "regenerated_for_production_3510": True,
        "production_merge": "b5b4c14a58e54effb5875a35348576057c27ce80",
    }
    old_audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")

    # Embed into dataset_meta and polygon_dataset
    meta_path = PROD / "dataset_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["triangulation_audit"] = audit
    meta["province_count"] = EXPECTED_COUNT
    meta["land_count"] = 3295
    meta["water_count"] = 215
    meta["included_source_ids_sha256"] = EXPECTED_HASH
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    # Update in-dataset audit blob without rewriting entire huge json if possible —
    # must keep dataset_sha256 consistent: recompute after patch.
    data["triangulation_audit"] = audit
    data["province_count"] = EXPECTED_COUNT
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    import hashlib

    ds_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ds_path.write_text(text + "\n", encoding="utf-8")

    man_path = PROD / "map_manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8"))
    man["province_count"] = EXPECTED_COUNT
    man["included_source_ids_sha256"] = EXPECTED_HASH
    man["approved_included_ids_sha256"] = EXPECTED_HASH
    man["polygon_dataset"]["sha256"] = ds_sha
    man["polygon_dataset"]["province_count"] = EXPECTED_COUNT
    man["export"] = dict(man.get("export") or {})
    man["export"]["triangulation_ok"] = bool(audit["ok"])
    man["export"]["max_tri_area_error"] = max_rel
    man_path.write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")

    meta["dataset_sha256"] = ds_sha
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    auth_path = ROOT / "config/earth3/production_authority.json"
    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    auth["province_count"] = EXPECTED_COUNT
    auth["land_count"] = 3295
    auth["water_count"] = 215
    auth["selectable_province_count"] = 3295
    auth["included_ids_sha256"] = EXPECTED_HASH
    auth["dataset_sha256"] = ds_sha
    auth["excluded_gates_ids"] = sorted(EXCLUDE)
    auth["production_merge"] = "b5b4c14a58e54effb5875a35348576057c27ce80"
    auth["test_repair_merge"] = "f60e715afb2a0a2b197351422edf5fa84a28da70"
    auth_path.write_text(json.dumps(auth, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": audit["ok"],
                "province_count_checked": audit["province_count_checked"],
                "failed_count": audit["failed_count"],
                "max_area_error": audit["max_area_error"],
                "total_polygon_area": audit["total_polygon_area"],
                "total_triangle_area": audit["total_triangle_area"],
                "dataset_sha256": ds_sha,
            },
            indent=2,
        )
    )
    return 0 if audit["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
