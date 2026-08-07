"""Final labelled Europe–Asia boundary preview for v7 Urals (preview only).

Does not change production dataset. Documents whole-province decisions along
the conventional geographic boundary:
  Kara Sea → Ural Mountains → Ural River → NW Caspian.
"""

from __future__ import annotations

import json
import sys
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
from gates_of_codex.earth3.parse import load_earth3_dataset  # noqa: E402
from gates_of_codex.earth3.preview import render_crop_preview  # noqa: E402
from gates_of_codex.earth3 import preview as prev  # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Pillow required") from exc

ARCHIVE = Path(r"C:\Users\paulf\Downloads\AOH3_Earth3_map_provinces.zip")
OUT = ROOT / "docs/earth3-crop/v7_europe_boundary"

# Conventional geographic Europe–Asia divide in Earth3 map pixels (authored polyline).
# North → south: Kara Sea / Polar Urals → Northern/Central Urals → Southern Urals →
# Ural River → NW Caspian.
EUROPE_ASIA_BOUNDARY: list[tuple[float, float]] = [
    (10920, 380),   # Kara Sea / northern Ural approach (west of Salekhard)
    (11040, 520),   # Polar Urals
    (11120, 700),   # near Pechora approach (west)
    (11160, 900),   # northern Urals
    (11200, 1100),  # Serov latitude, European face
    (11220, 1300),  # Nizhny Tagil west
    (11240, 1450),  # Perm east face / crest west
    (11250, 1550),  # Yekaterinburg crest (on-line)
    (11240, 1700),  # south of crest, west of Chelyabinsk
    (11200, 1850),  # Magnitogorsk west / river headwaters
    (11140, 1950),  # Orenburg east approach
    (11080, 2020),  # Ural River north of Oral
    (11020, 2100),  # Ural River
    (10940, 2200),  # Ural River toward Caspian
    (10870, 2280),  # NW Caspian / river mouth west of Atyrau
    (10820, 2360),  # Caspian shoreline west
    (10740, 2420),  # toward Astrakhan east water
    (10690, 2480),  # Astrakhan Caspian endpoint
]


def _load_current_masked() -> CropCandidate:
    return next(
        c
        for c in load_crop_candidates(ROOT / "config/earth3/crop_candidates_v1.json")
        if c.id == "em_reference_masked"
    )


def _refine_mask_to_boundary(base: CropCandidate) -> tuple[tuple, tuple]:
    """Keep v6 west/south; replace NE arm to hug EUROPE_ASIA_BOUNDARY from south Caspian up."""
    iceland = base.mask_rings[0]
    main = list(base.mask_rings[1])

    def idx_near(pts, x, y):
        best, bd = 0, 1e18
        for i, p in enumerate(pts):
            d = (p[0] - x) ** 2 + (p[1] - y) ** 2
            if d < bd:
                bd = d
                best = i
        return best

    # Current production may already be v7; rebuild from v6 structure if needed.
    # Find Caucasus east tip and north scandinavia join in the ring.
    i_cau = idx_near(main, 10880, 2620)
    i_nsk = idx_near(main, 10020, 450)
    keep_pre = main[: i_cau + 1]
    keep_post = main[i_nsk:]

    # Eastern arm: from Caucasus northward along Caspian/Ural River/Urals then to Kara approach,
    # then west to rejoin Scandinavia north. Boundary polyline is N→S; reverse for S→N arm.
    east_arm = list(reversed(EUROPE_ASIA_BOUNDARY))
    # Slight inward (west) offset so crest cities on the line can be decided by whole-polygon rule.
    east_arm = [(x - 15.0, y) for x, y in east_arm]
    # Ensure join continuity
    ring: list[tuple[float, float]] = []
    for p in list(keep_pre) + east_arm + list(keep_post):
        pt = (float(p[0]), float(p[1]))
        if not ring or ring[-1] != pt:
            ring.append(pt)
    return iceland, tuple(ring)


def _crosses_boundary(bounds, line_xs: list[float]) -> bool:
    min_x, _min_y, max_x, _max_y = bounds
    # Crude: province spans across median boundary x at its latitude band.
    return min_x < max(line_xs) and max_x > min(line_xs) and (max_x - min_x) > 40


def main() -> int:
    if not ARCHIVE.is_file():
        print(f"LOCAL SOURCE REQUIRED: {ARCHIVE}", file=sys.stderr)
        return 2

    ds = load_earth3_dataset(ARCHIVE)
    base = _load_current_masked()
    iceland, main = _refine_mask_to_boundary(base)

    # Required includes for conventional Europe (owner list)
    must_in = [
        11764,
        11756,
        10866,
        10854,
        11326,
        10837,
        10888,
        10805,
        10825,
        11331,
        3751,
        11685,
        3753,
    ]
    # Hard excludes east of line / Kazakhstan
    must_out = [
        10934,  # Chelyabinsk
        10919,  # Orsk (if present as that id)
        10809,  # Atyrau
        11345,  # Yekaterinburg — on Asian side of crest in conventional split (document)
        11348,  # Nizhny Tagil — often Europe; leave to polygon rule unless forced
        11835,  # Vorkuta
        11776,  # Salekhard
        11177,
        11180,
        10587,
    ]
    # Keep prior deep excludes from base that are not overridden
    excl = list(dict.fromkeys(list(base.explicit_exclude_ids) + must_out))
    # Arkhangelsk must not be excluded
    excl = [x for x in excl if x not in (11764, *must_in)]
    req = list(dict.fromkeys(list(base.required_include_ids) + must_in))
    req = [x for x in req if x not in set(excl)]

    xs = [p[0] for p in main] + [p[0] for p in iceland]
    ys = [p[1] for p in main] + [p[1] for p in iceland]
    cand = CropCandidate(
        id="em_v7_europe_boundary",
        title="V7 Europe–Asia conventional boundary (preview)",
        description="Hugs Kara Sea → Urals → Ural River → NW Caspian. Preview only.",
        rect=CropRect(min(xs) - 80, min(ys) - 80, max(xs) + 100, max(ys) + 80),
        required_include_ids=tuple(req),
        explicit_exclude_ids=tuple(excl),
        mask_rings=(tuple(tuple(p) for p in iceland), main),
        inclusion_threshold=0.35,
        review_band_low=0.15,
        review_band_high=0.50,
        selection_mode="mask_overlap",
        notes="PREVIEW ONLY — await owner approval of labelled boundary.",
    )
    crop = apply_crop(ds, cand)
    inc = set(crop.included_ids)
    h = included_ids_hash(crop.included_ids)
    print(
        "preview count",
        crop.province_count,
        crop.land_count,
        crop.water_count,
        h,
    )

    # Boundary-crossing province report
    line_xs = [p[0] for p in EUROPE_ASIA_BOUNDARY]
    crossings = []
    for pid in sorted(ds.provinces):
        p = ds.provinces[pid]
        if not cand.rect.intersects_bounds(p.bounds):
            continue
        min_x, min_y, max_x, max_y = p.bounds
        # Near the corridor
        if max_x < 10600 or min_x > 11600:
            continue
        if min_y > 2600 or max_y < 300:
            continue
        spans = min_x < 11280 and max_x > 11000 and (max_x - min_x) > 30
        if not spans and not _crosses_boundary(p.bounds, line_xs):
            continue
        # Distance of centroid to boundary polyline (approx min dx to line x at y)
        cx, cy = p.centroid
        # interpolate boundary x at cy
        bx = line_xs[0]
        for (x0, y0), (x1, y1) in zip(EUROPE_ASIA_BOUNDARY, EUROPE_ASIA_BOUNDARY[1:]):
            if (y0 <= cy <= y1) or (y1 <= cy <= y0):
                t = 0.0 if y1 == y0 else (cy - y0) / (y1 - y0)
                bx = x0 + t * (x1 - x0)
                break
        side = "west_europe" if cx < bx else "east_asia"
        included = pid in inc
        # recommend
        if included and side == "east_asia":
            rec = "include_whole_polygon_despite_east_centroid"
        elif (not included) and side == "west_europe":
            rec = "exclude_whole_polygon_despite_west_centroid"
        elif included:
            rec = "include"
        else:
            rec = "exclude"
        name = ""
        for c in ds.cities:
            if c.province_id == pid:
                name = c.name
                break
        crossings.append(
            {
                "source_province_id": pid,
                "name": name or f"province_{pid}",
                "centroid": [round(cx, 2), round(cy, 2)],
                "bounds": [min_x, min_y, max_x, max_y],
                "is_water": bool(p.is_water),
                "boundary_x_at_centroid_y": round(bx, 2),
                "centroid_side": side,
                "included_in_preview_crop": included,
                "recommend": rec,
            }
        )

    # Key city checks
    keys = {
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
        "Yekaterinburg": 11345,
        "Chelyabinsk": 10934,
        "Atyrau": 10809,
        "Vorkuta": 11835,
        "Salekhard": 11776,
        "Uralsk": 10829,
        "Nizhny_Tagil": 11348,
    }
    key_status = {
        n: {"source_id": pid, "included": pid in inc} for n, pid in keys.items()
    }

    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "gates-of-codex.earth3-v7-europe-boundary-preview",
        "schema_version": 1,
        "status": "pending_owner_visual_approval",
        "production_authority_unchanged_until_approval": True,
        "conventional_boundary": {
            "description": "Kara Sea / northern Ural → Ural Mountains → Ural River → NW Caspian",
            "polyline_earth3_xy": EUROPE_ASIA_BOUNDARY,
        },
        "preview_crop": {
            "id": cand.id,
            "province_count": crop.province_count,
            "land_count": crop.land_count,
            "water_count": crop.water_count,
            "included_ids_sha256": h,
            "bounds": list(crop.source_bounds),
        },
        "required_city_status": key_status,
        "boundary_crossing_provinces": crossings,
        "boundary_crossing_count": len(crossings),
        "notes": [
            "Whole Earth3 polygons only — no sliver clips.",
            "Provinces straddling the conventional line are listed with include/exclude recommendation.",
            "Yekaterinburg is conventionally on/east of the crest; preview forces exclude.",
            "Chelyabinsk, Atyrau, Vorkuta, Salekhard forced exclude.",
            "Await owner approval before replacing production theatre.",
        ],
    }
    (OUT / "BOUNDARY_CROSSINGS.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Render base preview then annotate
    shared = (6700.0, 120.0, 12200.0, 4300.0)
    prev.DEFAULT_COMPARISON_VIEW = shared
    prev.KEY_LABELS = {
        **prev.KEY_LABELS,
        "Arkhangelsk": (10325, 892),
        "Syktyvkar": (10820, 1135),
        "Perm": (11087, 1447),
        "Kazan": (10742, 1641),
        "Ufa": (11072, 1731),
        "Orenburg": (11029, 1973),
        "Astrakhan": (10687, 2374),
        "Samara": (10793, 1858),
        "Volgograd": (10514, 2206),
        "Yekaterinburg": (11302, 1549),
        "Chelyabinsk": (11339, 1693),
        "Atyrau": (10878, 2323),
        "Kara Sea": (10920, 380),
        "Ural Mts": (11240, 1500),
        "Ural River": (11020, 2100),
        "Caspian": (10690, 2480),
    }
    raw_path = OUT / "preview_raw.png"
    render_crop_preview(
        ds,
        crop,
        raw_path,
        view=shared,
        title_suffix=" [Europe–Asia boundary preview]",
    )

    # Annotate boundary polyline + callouts
    img = Image.open(raw_path).convert("RGBA")
    draw = ImageDraw.Draw(img)
    w, h = img.size
    min_x, min_y, max_x, max_y = shared

    def tx(x, y):
        px = int((x - min_x) / (max_x - min_x) * (w - 1))
        py = int((y - min_y) / (max_y - min_y) * (h - 1))
        return px, py

    poly = [tx(x, y) for x, y in EUROPE_ASIA_BOUNDARY]
    # thick gold line for conventional boundary
    draw.line(poly, fill=(255, 215, 0, 255), width=4)
    # second outline
    draw.line(poly, fill=(255, 80, 0, 220), width=2)

    callouts = [
        ((10920, 380), "Kara Sea / N Ural"),
        ((11240, 1500), "Ural Mountains"),
        ((11020, 2100), "Ural River"),
        ((10690, 2480), "Caspian endpoint"),
        ((11029, 1973), "Orenburg"),
        ((10687, 2374), "Astrakhan"),
        ((11339, 1693), "Chelyabinsk (exclude)"),
        ((10878, 2323), "Atyrau KZ (exclude)"),
        ((11468, 623), "Vorkuta (exclude)"),
    ]
    try:
        font = ImageFont.truetype("arial.ttf", 16)
        font_sm = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()
        font_sm = font

    for (x, y), label in callouts:
        px, py = tx(x, y)
        draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=(255, 255, 0, 255))
        draw.text((px + 8, py - 8), label, fill=(255, 255, 220, 255), font=font_sm)

    # Legend
    draw.rectangle((12, h - 88, 520, h - 12), fill=(0, 0, 0, 180))
    draw.text(
        (20, h - 80),
        "Gold/orange line = conventional Europe–Asia boundary",
        fill=(255, 215, 0, 255),
        font=font,
    )
    draw.text(
        (20, h - 58),
        "Olive = included preview crop  |  Red muted = excluded",
        fill=(200, 220, 200, 255),
        font=font,
    )
    draw.text(
        (20, h - 36),
        f"Preview provinces={crop.province_count}  NOT production until approved",
        fill=(255, 180, 180, 255),
        font=font,
    )

    labelled = OUT / "labelled_europe_asia_boundary.png"
    img.convert("RGB").save(labelled)
    print("wrote", labelled)

    # Closeups
    close = OUT / "closeups"
    close.mkdir(exist_ok=True)
    views = {
        "urals_crest": (10800.0, 1100.0, 11600.0, 1900.0),
        "ural_river_caspian": (10500.0, 1900.0, 11300.0, 2600.0),
        "kara_northern_ural": (10600.0, 300.0, 11600.0, 1000.0),
        "orenburg_astrakhan": (10500.0, 1850.0, 11250.0, 2500.0),
    }
    for name, view in views.items():
        p = close / f"{name}.png"
        render_crop_preview(ds, crop, p, width=1400, height=900, view=view, title_suffix=f" [{name}]")
        # light boundary overlay on closeups too
        cimg = Image.open(p).convert("RGBA")
        cd = ImageDraw.Draw(cimg)
        cw, ch = cimg.size
        vx0, vy0, vx1, vy1 = view

        def ctx(x, y, _vx0=vx0, _vy0=vy0, _vx1=vx1, _vy1=vy1, _cw=cw, _ch=ch):
            return (
                int((x - _vx0) / (_vx1 - _vx0) * (_cw - 1)),
                int((y - _vy0) / (_vy1 - _vy0) * (_ch - 1)),
            )

        pts = [ctx(x, y) for x, y in EUROPE_ASIA_BOUNDARY]
        # clip-ish draw full line (may go outside)
        cd.line(pts, fill=(255, 200, 0, 255), width=3)
        cimg.convert("RGB").save(p)
        print("wrote", p)

    md = f"""# v7 Europe–Asia boundary preview (awaiting owner approval)

**Status:** pending owner visual approval of this labelled boundary.  
**Do not replace production** until approved.

## Conventional boundary
Kara Sea / northern Ural → **Ural Mountains** → **Ural River** → northwestern **Caspian**.

## Labelled preview
![boundary](labelled_europe_asia_boundary.png)

## Preview crop metrics (not production)
| Metric | Value |
|------|------:|
| Provinces | {crop.province_count} |
| Land / water | {crop.land_count} / {crop.water_count} |
| included_ids_sha256 | `{h}` |

## Required city inclusion (preview)
"""
    for n, st in key_status.items():
        md += f"- **{n}**: included={st['included']} (source_id={st['source_id']})\n"
    md += f"""
## Boundary-crossing provinces
See `BOUNDARY_CROSSINGS.json` ({len(crossings)} rows). Each straddling whole polygon is recommended include/exclude individually (no sliver clips).

## Closeups
"""
    for name in views:
        md += f"- `closeups/{name}.png`\n"
    (OUT / "README.md").write_text(md, encoding="utf-8")
    print("wrote report", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
