#!/usr/bin/env python3
"""Targeted exterior border suppress for the northern src-11836 pseudo-outline only.

Contract:
  - allowlisted excluded source IDs only (default: 11836)
  - suppress only undirected local-space edges shared between those excluded rings
    and currently included land rings
  - do NOT suppress merely because an opposite province is outside the crop
  - does not change geometry, included IDs, adjacency, or province_count
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from gates_of_codex.earth3.parse import load_earth3_dataset  # noqa: E402

PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean"
AUTH = ROOT / "config/earth3/production_authority.json"
SNAP = 0.01
# Explicit allowlist — only reviewed northern pseudo-outline (Fion / src 11836).
APPROVED_EXCLUDED_SOURCE_IDS = (11836,)


def _edge_key(a, b, snap=SNAP):
    ax, ay = round(a[0] / snap) * snap, round(a[1] / snap) * snap
    bx, by = round(b[0] / snap) * snap, round(b[1] / snap) * snap
    p1, p2 = (ax, ay), (bx, by)
    return (p1, p2) if p1 <= p2 else (p2, p1)


def _resolve_archive(path: str | None) -> Path:
    p = path or os.environ.get("GATES_EARTH3_ARCHIVE") or os.environ.get("EARTH3_ARCHIVE")
    if not p:
        raise SystemExit("Pass --archive or set GATES_EARTH3_ARCHIVE")
    path_p = Path(p)
    if not path_p.is_file():
        raise SystemExit(f"Archive not found: {path_p}")
    return path_p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", default=None)
    ap.add_argument(
        "--excluded-source-ids",
        default=",".join(str(x) for x in APPROVED_EXCLUDED_SOURCE_IDS),
        help="Comma-separated allowlist of excluded source IDs (default: 11836 only)",
    )
    args = ap.parse_args(argv)
    allow = tuple(int(x.strip()) for x in str(args.excluded_source_ids).split(",") if x.strip())
    if not allow:
        raise SystemExit("empty --excluded-source-ids allowlist")

    archive = load_earth3_dataset(_resolve_archive(args.archive))
    ds_path = PROD / "polygon_dataset.json"
    body = ds_path.read_text(encoding="utf-8")
    raw = body[:-1] if body.endswith("\n") else body
    ds = json.loads(raw)
    ox, oy = ds["bounds"]["origin_source_xy"]
    inc = {int(p["source_id"]) for p in ds["provinces"]}

    for sid in allow:
        if sid in inc:
            raise SystemExit(f"allowlisted source {sid} is included in production — refuse")
        if sid not in archive.provinces:
            raise SystemExit(f"allowlisted source {sid} missing from archive")
        if archive.provinces[sid].is_water:
            raise SystemExit(f"allowlisted source {sid} is water — refuse")

    target_edges: set[tuple] = set()
    for sid in allow:
        pr = archive.provinces[sid]
        pts = [(round(float(x) - ox, 6), round(float(y) - oy, 6)) for x, y in pr.ring]
        if pts and pts[0] == pts[-1]:
            pts = pts[:-1]
        n = len(pts)
        for i in range(n):
            target_edges.add(_edge_key(pts[i], pts[(i + 1) % n]))

    suppress = []
    seen = set()
    contributors: dict[str, int] = {}
    for p in ds["provinces"]:
        if p.get("is_water"):
            continue
        r = p.get("ring") or []
        pts = [(float(r[i]), float(r[i + 1])) for i in range(0, len(r) - 1, 2)]
        if pts and pts[0] == pts[-1]:
            pts = pts[:-1]
        n = len(pts)
        hit = 0
        for i in range(n):
            k = _edge_key(pts[i], pts[(i + 1) % n])
            if k not in target_edges:
                continue
            flat = [k[0][0], k[0][1], k[1][0], k[1][1]]
            t = tuple(flat)
            if t not in seen:
                seen.add(t)
                suppress.append(flat)
            hit += 1
        if hit:
            contributors[p["id"]] = hit

    # Hard cap: allowlisted feature only — fail if suppress set explodes
    if len(suppress) > 64:
        raise SystemExit(f"suppress set too large for targeted contract: {len(suppress)}")
    if len(suppress) < 1:
        raise SystemExit("suppress set empty — reviewed outline edges not found")

    ds["exterior_border_suppress"] = suppress
    ds["exterior_border_suppress_meta"] = {
        "contract": "allowlisted_excluded_source_outline_only",
        "excluded_source_ids": list(allow),
        "edge_count": len(suppress),
        "included_land_contributors": contributors,
        "note": (
            "Only edges shared with allowlisted excluded land rings. "
            "Does not suppress general crop-exterior boundaries."
        ),
    }
    # drop stale broad note if present
    ds.pop("exterior_border_suppress_note", None)

    text = json.dumps(ds, separators=(",", ":"), ensure_ascii=False)
    ds_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ds_path.write_text(text + "\n", encoding="utf-8")

    meta = json.loads((PROD / "dataset_meta.json").read_text(encoding="utf-8"))
    meta["dataset_sha256"] = ds_sha
    (PROD / "dataset_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    man = json.loads((PROD / "map_manifest.json").read_text(encoding="utf-8"))
    if "polygon_dataset" in man:
        man["polygon_dataset"]["sha256"] = ds_sha
    (PROD / "map_manifest.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")

    if AUTH.is_file():
        auth = json.loads(AUTH.read_text(encoding="utf-8"))
        auth["dataset_sha256"] = ds_sha
        AUTH.write_text(json.dumps(auth, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "allowlisted_excluded_source_ids": list(allow),
                "suppress_edge_count": len(suppress),
                "contributors": contributors,
                "dataset_sha256": ds_sha,
                "province_count": ds["province_count"],
                "included_ids_sha256": ds["included_source_ids_sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
