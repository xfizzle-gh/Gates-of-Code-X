"""Preview-only v7 eastward extent candidates (does not touch production authority)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.earth3.audit_artifact import included_ids_hash  # noqa: E402
from gates_of_codex.earth3.crop import (  # noqa: E402
    CropCandidate,
    CropRect,
    apply_crop,
    load_crop_candidates,
)
from gates_of_codex.earth3.export_production import triangulate_ring_validated  # noqa: E402
from gates_of_codex.earth3.parse import load_earth3_dataset  # noqa: E402
from gates_of_codex.earth3 import preview as prev  # noqa: E402
from gates_of_codex.earth3.preview import render_crop_preview  # noqa: E402

ARCHIVE = Path(r"C:\Users\paulf\Downloads\AOH3_Earth3_map_provinces.zip")
OUT = ROOT / "docs/earth3-crop/v7_eastward"
SHARED = (6700.0, 120.0, 12200.0, 4300.0)
CLOSEUPS = {
    "western_russia": (10000.0, 800.0, 11600.0, 2400.0),
    "arkhangelsk_white_sea": (10000.0, 400.0, 11000.0, 1200.0),
    "volga_corridor": (10300.0, 1500.0, 11200.0, 2500.0),
    "urals_boundary": (10800.0, 1200.0, 11600.0, 2200.0),
    "caspian_astrakhan": (10400.0, 2100.0, 11400.0, 2900.0),
}


def _estimate_tris(ds, crop) -> int | None:
    total = 0
    n = 0
    step = max(1, len(crop.included_ids) // 80)
    for i, pid in enumerate(sorted(crop.included_ids)):
        if i % step:
            continue
        p = ds.provinces[pid]
        ring = list(p.ring)
        if len(ring) >= 2 and ring[0] == ring[-1]:
            ring = ring[:-1]
        try:
            _vf, tris, _r, _a = triangulate_ring_validated(
                tuple((float(x), float(y)) for x, y in ring)
            )
            total += len(tris) // 3
            n += 1
        except Exception:
            continue
    if not n:
        return None
    return int((total / n) * len(crop.included_ids))


def main() -> int:
    if not ARCHIVE.is_file():
        print(f"LOCAL SOURCE REQUIRED: {ARCHIVE}", file=sys.stderr)
        return 2

    ds = load_earth3_dataset(ARCHIVE)
    cfg = json.loads((ROOT / "config/earth3/crop_candidates_v1.json").read_text(encoding="utf-8"))
    v6c = next(c for c in cfg["candidates"] if c["id"] == "em_reference_masked")
    rings = json.loads((OUT / "_rings.json").read_text(encoding="utf-8"))
    iceland = tuple(tuple(p) for p in rings["iceland"])
    main_a = tuple(tuple(p) for p in rings["volga"])
    main_b = tuple(tuple(p) for p in rings["urals"])

    v6_req = list(v6c["required_include_ids"])
    v6_excl = [x for x in v6c["explicit_exclude_ids"] if x != 11764]

    incl_a = [11764, 3751, 11685, 10854, 3753, 10837, 10888, 10805, 10825]
    excl_a = [
        10866,
        11326,
        11331,
        10919,
        11345,
        10934,
        11348,
        11347,
        11177,
        11180,
        10587,
        10809,
    ]
    incl_b = incl_a + [10866, 11326, 11331, 11756, 11345]
    excl_b = [10919, 11177, 11180, 10587, 10809, 10934]

    def make(cid, title, desc, main, incl_extra, excl_extra):
        req = list(dict.fromkeys(v6_req + incl_extra))
        excl = list(dict.fromkeys(v6_excl + excl_extra))
        req = [x for x in req if x not in set(excl)]
        xs = [p[0] for p in main] + [p[0] for p in iceland]
        ys = [p[1] for p in main] + [p[1] for p in iceland]
        return CropCandidate(
            id=cid,
            title=title,
            description=desc,
            rect=CropRect(min(xs) - 100, min(ys) - 100, max(xs) + 120, max(ys) + 100),
            required_include_ids=tuple(req),
            explicit_exclude_ids=tuple(excl),
            mask_rings=(iceland, main),
            inclusion_threshold=0.35,
            review_band_low=0.15,
            review_band_high=0.50,
            selection_mode="mask_overlap",
            notes="PREVIEW ONLY — not production authority.",
        )

    cands = [
        make(
            "em_v7_volga",
            "V7 Candidate A — Volga expansion",
            "v6 + Arkhangelsk/White Sea + Volga corridor to Astrakhan/NW Caspian. "
            "Excludes Perm/Bashkortostan/Orenburg and east of Volga–Ural transition.",
            main_a,
            incl_a,
            excl_a,
        ),
        make(
            "em_v7_urals",
            "V7 Candidate B — European Russia to Urals",
            "v6 + Candidate A + Komi/Perm/Bashkortostan/Orenburg and European Ural face. "
            "Excludes Siberia east of Urals and Central Asia.",
            main_b,
            incl_b,
            excl_b,
        ),
    ]

    # Persist preview candidates into a sidecar config (do not alter production crop list).
    preview_cfg = {
        "schema": "gates-of-codex.earth3-crop-candidates-preview",
        "schema_version": 1,
        "based_on": "em_reference_masked_v6",
        "status": "pending_owner_visual_approval",
        "candidates": [
            {
                "id": c.id,
                "title": c.title,
                "description": c.description,
                "selection_mode": "mask_overlap",
                "inclusion_threshold": 0.35,
                "rect": {
                    "min_x": c.rect.min_x,
                    "min_y": c.rect.min_y,
                    "max_x": c.rect.max_x,
                    "max_y": c.rect.max_y,
                },
                "mask_rings": [list(map(list, r)) for r in c.mask_rings],
                "required_include_ids": list(c.required_include_ids),
                "explicit_exclude_ids": list(c.explicit_exclude_ids),
                "notes": c.notes,
            }
            for c in cands
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "crop_candidates_v7_eastward_preview.json").write_text(
        json.dumps(preview_cfg, indent=2) + "\n", encoding="utf-8"
    )

    v6 = next(
        c
        for c in load_crop_candidates(ROOT / "config/earth3/crop_candidates_v1.json")
        if c.id == "em_reference_masked"
    )
    baseline = apply_crop(ds, v6)

    prev.DEFAULT_COMPARISON_VIEW = SHARED
    prev.KEY_LABELS = {
        **prev.KEY_LABELS,
        "Arkhangelsk": (10325, 892),
        "Vologda": (10288, 1330),
        "Kirov": (10768, 1386),
        "Kazan": (10742, 1641),
        "Samara": (10793, 1858),
        "Saratov": (10586, 1988),
        "Volgograd": (10514, 2206),
        "Astrakhan": (10687, 2374),
        "Perm": (11087, 1447),
        "Ufa": (11072, 1731),
        "Orenburg": (11029, 1973),
        "Syktyvkar": (10820, 1135),
    }

    close = OUT / "closeups"
    close.mkdir(exist_ok=True)
    results = []
    for cand in cands:
        t0 = time.perf_counter()
        crop = apply_crop(ds, cand)
        elapsed = time.perf_counter() - t0
        h = included_ids_hash(crop.included_ids)
        row = {
            "id": cand.id,
            "title": cand.title,
            "province_count": crop.province_count,
            "land_count": crop.land_count,
            "water_count": crop.water_count,
            "included_ids_sha256": h,
            "vertex_count": crop.vertex_count,
            "triangle_count_estimate": _estimate_tris(ds, crop),
            "bounds": {
                "source_min_xy": [crop.source_bounds[0], crop.source_bounds[1]],
                "source_max_xy": [crop.source_bounds[2], crop.source_bounds[3]],
                "width": crop.source_bounds[2] - crop.source_bounds[0],
                "height": crop.source_bounds[3] - crop.source_bounds[1],
            },
            "crop_apply_ms": int(elapsed * 1000),
            "estimated_godot_load_ms": int(1000 * (crop.province_count / 3345.0) * 1.05),
            "estimated_snapshot_kb": int(len(crop.included_ids) * 250 / 1024),
            "delta_vs_v6_provinces": crop.province_count - baseline.province_count,
        }
        results.append(row)
        print(cand.id, row["province_count"], row["delta_vs_v6_provinces"], h)
        render_crop_preview(
            ds, crop, OUT / f"preview_{cand.id}.png", view=SHARED, title_suffix=" [v7 shared camera]"
        )
        for name, view in CLOSEUPS.items():
            render_crop_preview(
                ds,
                crop,
                close / f"{cand.id}_{name}.png",
                width=1400,
                height=900,
                view=view,
                title_suffix=f" [{name}]",
            )

    render_crop_preview(
        ds,
        baseline,
        OUT / "preview_em_v6_baseline.png",
        view=SHARED,
        title_suffix=" [v6 baseline shared camera]",
    )

    report = {
        "schema": "gates-of-codex.earth3-v7-eastward-preview",
        "schema_version": 1,
        "status": "pending_owner_visual_approval",
        "production_authority_unchanged": {
            "map_id": "earth3_europe_mediterranean",
            "province_count": 3345,
            "land_water": [3133, 212],
            "included_ids_sha256": "4fe9d98bbf40d2588286d3d4ec5513ffa3a8f0b7b2ae5689373217b4cb569a1b",
            "merge": "b8768c9fce9a577ade7094e15a282d44219472c6",
        },
        "shared_camera": list(SHARED),
        "candidates": results,
        "recommendation": {
            "preferred": "em_v7_volga",
            "rationale": [
                "Candidate A adds the operationally meaningful Volga axis (Arkhangelsk–Kazan–Samara–Volgograd–Astrakhan) and White Sea approach without committing to the full Ural industrial belt.",
                "Smaller province delta and load/snapshot cost while still answering the eastward-extent question for European Russia’s core river corridor.",
                "Candidate B is the natural max-east European-Russia option if the Urals should be a permanent hard boundary (Perm/Bashkortostan/Orenburg depth).",
                "Neither candidate is approved; production remains v6 until owner visual sign-off.",
            ],
        },
        "federal_subjects_metadata_note": {
            "principle": "Playable cells remain Earth3 provinces (e3_*). Russian federal subjects are grouping metadata / overlay only — never replace province geometry.",
            "examples": [
                {
                    "subject": "Moscow (federal city)",
                    "vs": "Moscow Oblast",
                    "representation": "subject_id on provinces + optional boundary overlay; city provinces tagged federal_city=true",
                },
                {
                    "subject": "Saint Petersburg (federal city)",
                    "vs": "Leningrad Oblast",
                    "representation": "same pattern; do not merge oblast into city cell",
                },
                {
                    "subject": "Other oblasts/krais/republics",
                    "representation": "province.properties.federal_subject_id + name table; UI can tint/label without changing adjacency",
                },
            ],
        },
    }
    (OUT / "V7_EASTWARD_COMPARISON.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    md = ["# Earth3 v7 eastward extent — owner decision package\n\n"]
    md.append("**Status:** pending owner visual approval. **Production theatre unchanged (v6 / 3345).**\n\n")
    md.append("## Candidates\n\n")
    for r in results:
        md.append(f"### {r['title']} (`{r['id']}`)\n\n")
        md.append("| Metric | Value |\n|------|------:|\n")
        md.append(f"| Provinces | **{r['province_count']}** (Δ v6 {r['delta_vs_v6_provinces']:+d}) |\n")
        md.append(f"| Land / water | {r['land_count']} / {r['water_count']} |\n")
        md.append(f"| included_ids_sha256 | `{r['included_ids_sha256']}` |\n")
        md.append(f"| Vertices | {r['vertex_count']} |\n")
        md.append(f"| Triangles (estimate) | {r['triangle_count_estimate']} |\n")
        md.append(f"| Source bounds W×H | {r['bounds']['width']:.0f} × {r['bounds']['height']:.0f} |\n")
        md.append(f"| Est. Godot load | ~{r['estimated_godot_load_ms']} ms |\n")
        md.append(f"| Est. snapshot size | ~{r['estimated_snapshot_kb']} KB |\n\n")
        md.append(f"![full](preview_{r['id']}.png)\n\n")
    for name in CLOSEUPS:
        md.append(f"## Closeup: {name}\n\n")
        for r in results:
            md.append(f"- `{r['id']}`: `closeups/{r['id']}_{name}.png`\n")
        md.append("\n")
    md.append("## Recommendation\n\n")
    for line in report["recommendation"]["rationale"]:
        md.append(f"- {line}\n")
    md.append("\n## Federal subjects (metadata / overlay — not playable cells)\n\n")
    md.append(report["federal_subjects_metadata_note"]["principle"] + "\n\n")
    for ex in report["federal_subjects_metadata_note"]["examples"]:
        vs = ex.get("vs", "")
        if vs:
            md.append(f"- **{ex['subject']}** vs {vs}: {ex['representation']}\n")
        else:
            md.append(f"- **{ex['subject']}**: {ex['representation']}\n")
    (OUT / "README.md").write_text("".join(md), encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
