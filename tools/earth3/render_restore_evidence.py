#!/usr/bin/env python3
"""Offline before/after evidence for restored lands + crop-edge border policy."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean"
OUT = ROOT / "docs/earth3-crop/restore_excluded_lands"
HASH = "f3931d2e34558e451d02a7c49270b2071a79a628668c49228f5ff607a75315b8"
RESTORED = {"e3_3512", "e3_3513", "e3_3514", "e3_3515"}


def pair(ring):
    return [(float(ring[i]), float(ring[i + 1])) for i in range(0, len(ring) - 1, 2)]


def edge_key(a, b, snap=0.01):
    ax, ay = round(a[0] / snap) * snap, round(a[1] / snap) * snap
    bx, by = round(b[0] / snap) * snap, round(b[1] / snap) * snap
    p1, p2 = (ax, ay), (bx, by)
    return (p1, p2) if p1 <= p2 else (p2, p1)


def collect_edges(provinces, *, skip_singleton_exterior: bool):
    counts = defaultdict(lambda: [0, 0])
    for p in provinces:
        pts = pair(p.get("ring") or [])
        if len(pts) < 2:
            continue
        if pts[0] == pts[-1]:
            pts = pts[:-1]
        water = bool(p.get("is_water"))
        n = len(pts)
        for i in range(n):
            k = edge_key(pts[i], pts[(i + 1) % n])
            if water:
                counts[k][1] += 1
            else:
                counts[k][0] += 1
    drawn = []
    for k, (ln, wn) in counts.items():
        if ln <= 0:
            continue
        if skip_singleton_exterior and ln == 1 and wn == 0:
            continue
        drawn.append((k, "coast" if wn else "land"))
    return drawn


def render(path, provinces, edges, title, window, highlight=None):
    minx, maxx, miny, maxy = window
    w, h = 1400, 1000
    img = Image.new("RGB", (w, h), (16, 28, 42))
    dr = ImageDraw.Draw(img)
    s = min((w - 60) / (maxx - minx), (h - 60) / (maxy - miny))

    def px(x, y):
        return (30 + (x - minx) * s, 40 + (y - miny) * s)

    for p in provinces:
        if p.get("is_water"):
            continue
        pts = pair(p.get("ring") or [])
        if len(pts) < 3:
            continue
        cx = sum(x for x, _ in pts) / len(pts)
        cy = sum(y for _, y in pts) / len(pts)
        if not (minx - 100 <= cx <= maxx + 100 and miny - 100 <= cy <= maxy + 100):
            continue
        sp = [px(x, y) for x, y in pts]
        fill = (90, 200, 110) if highlight and p["id"] in highlight else (120, 126, 118)
        if len(sp) >= 3:
            dr.polygon(sp, fill=fill, outline=(50, 54, 50))
    for (a, b), kind in edges:
        if not (minx - 50 <= a[0] <= maxx + 50 or minx - 50 <= b[0] <= maxx + 50):
            continue
        col = (30, 90, 160) if kind == "coast" else (20, 22, 24)
        dr.line([px(*a), px(*b)], fill=col, width=1)
    dr.text((16, 10), title, fill=(240, 240, 240))
    img.save(path)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ds = json.loads((PROD / "polygon_dataset.json").read_text(encoding="utf-8"))
    assert ds["included_source_ids_sha256"] == HASH
    provinces = ds["provinces"]
    # after: new border policy
    edges_after = collect_edges(provinces, skip_singleton_exterior=True)
    # before simulation: old policy (draw singleton land edges)
    edges_before = collect_edges(provinces, skip_singleton_exterior=False)

    # full theatre
    render(
        OUT / "f5_full_after.png",
        provinces,
        edges_after,
        f"Earth3 production AFTER restore 3514 / {HASH[:12]}…",
        (0, 4306, 0, 3449),
        highlight=RESTORED,
    )
    # NE crop
    win_ne = (2500, 4306, 200, 1800)
    render(OUT / "northeast_after.png", provinces, edges_after, "Northeast AFTER restore + exterior border skip", win_ne, RESTORED)
    render(OUT / "northeast_before_border_policy.png", provinces, edges_before, "Northeast BEFORE exterior border skip (singleton land edges drawn)", win_ne, RESTORED)

    # closeups restored
    targets = {
        "NE04_Koynas_e3_3515": "e3_3515",
        "NE06_Galich_e3_3514": "e3_3514",
        "NE07_Yaransk_e3_3512": "e3_3512",
        "NE08_Tuymazy_e3_3513": "e3_3513",
    }
    by_id = {p["id"]: p for p in provinces}
    for label, gid in targets.items():
        p = by_id[gid]
        cx, cy = p["centroid"]
        win = (cx - 180, cx + 180, cy - 140, cy + 140)
        render(OUT / f"{label}_after.png", provinces, edges_after, f"{label} AFTER land restore", win, {gid})
        # before: hide restored province
        without = [x for x in provinces if x["id"] != gid]
        edges_w = collect_edges(without, skip_singleton_exterior=False)
        render(OUT / f"{label}_before.png", without, edges_w, f"{label} BEFORE (gap/ocean hole)", win, None)

    # crop-edge outline region near former 11836
    win_edge = (4000, 4306, 500, 900)
    render(OUT / "crop_edge_outline_after.png", provinces, edges_after, "Crop-edge (src11836 area) AFTER singleton exterior borders suppressed", win_edge)
    render(OUT / "crop_edge_outline_before.png", provinces, edges_before, "Crop-edge (src11836 area) BEFORE singleton exterior borders drawn", win_edge)

    meta = {
        "province_count": 3514,
        "land_count": 3299,
        "water_count": 215,
        "included_ids_sha256": HASH,
        "restored_gates": sorted(RESTORED),
        "permanent_gaps": ["e3_2830", "e3_2888"],
    }
    (OUT / "final_counts.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
