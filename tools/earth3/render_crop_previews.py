"""Generate Earth3 Europe-Mediterranean crop candidate comparison package + audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.earth3.crop import apply_crop, load_crop_candidates  # noqa: E402
from gates_of_codex.earth3.parse import load_earth3_dataset  # noqa: E402
from gates_of_codex.earth3.preview import (  # noqa: E402
    CLOSEUPS,
    load_reference_outline,
    load_shared_view,
    render_crop_preview,
    write_audit_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        default=r"C:\Users\paulf\Downloads\AOH3_Earth3_map_provinces.zip",
        help="Path to AOH3_Earth3_map_provinces.zip (not committed)",
    )
    parser.add_argument(
        "--crop-config",
        default=str(ROOT / "config/earth3/crop_candidates_v1.json"),
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "docs/earth3-crop"),
    )
    args = parser.parse_args()

    archive = Path(args.archive)
    if not archive.is_file():
        print(f"ERROR: archive not found: {archive}", file=sys.stderr)
        return 2

    config_path = Path(args.crop_config)
    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    shared_view = load_shared_view(config_path)
    reference_outline = load_reference_outline(config_path)

    print(f"loading Earth3 dataset from {archive} ...")
    dataset = load_earth3_dataset(archive)
    print(f"loaded provinces={len(dataset.provinces)} canvas={dataset.canvas_size}")

    candidates = load_crop_candidates(config_path)
    results = []
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    closeup_dir = out_dir / "closeups"
    closeup_dir.mkdir(parents=True, exist_ok=True)

    for candidate in candidates:
        print(f"applying crop {candidate.id} mode={candidate.selection_mode} ...")
        result = apply_crop(dataset, candidate)
        results.append(result)
        print(
            f"  provinces={result.province_count} land={result.land_count} "
            f"water={result.water_count} verts={result.vertex_count} "
            f"edges={result.adjacency_edges} components={result.disconnected_land_components} "
            f"review={len(result.threshold_review_ids)}"
        )

        # Same-scale overview for every candidate.
        overview = out_dir / f"preview_{candidate.id}.png"
        render_crop_preview(
            dataset,
            result,
            overview,
            view=shared_view,
            reference_outline=reference_outline,
            title_suffix=" [shared camera]",
        )
        print(f"  wrote {overview}")

        # Close-ups (all candidates, same cameras).
        for name, view in CLOSEUPS.items():
            path = closeup_dir / f"{candidate.id}_{name}.png"
            render_crop_preview(
                dataset,
                result,
                path,
                width=1400,
                height=900,
                view=view,
                reference_outline=reference_outline,
                title_suffix=f" [{name}]",
            )
            print(f"  wrote {path}")

    audit_path = out_dir / "crop_candidates_audit.json"
    write_audit_report(
        dataset,
        results,
        audit_path,
        recommended_id=None,
        config_payload=config_payload,
    )
    print(f"wrote {audit_path}")

    # Compact markdown summary for #92.
    summary_path = out_dir / "COMPARISON.md"
    _write_comparison_md(results, summary_path)
    print(f"wrote {summary_path}")
    print(
        "STATUS: awaiting owner crop approval on issue #92 — "
        "no production subset committed; no production recommendation."
    )
    return 0


def _write_comparison_md(results, path: Path) -> None:
    lines = [
        "# Earth3 crop candidate comparison",
        "",
        "**Status:** awaiting owner approval on #92. **No production recommendation.**",
        "",
        "| ID | Mode | Provinces | Land | Water | Vertices | Edges | Components | Threshold review |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    by_id = {r.candidate.id: r for r in results}
    for r in results:
        lines.append(
            f"| `{r.candidate.id}` | {r.candidate.selection_mode} | {r.province_count} | "
            f"{r.land_count} | {r.water_count} | {r.vertex_count} | {r.adjacency_edges} | "
            f"{r.disconnected_land_components} | {len(r.threshold_review_ids)} |"
        )
    tight = by_id.get("em_ref_tight")
    masked = by_id.get("em_reference_masked")
    if tight and masked:
        a = set(masked.included_ids)
        b = set(tight.included_ids)
        lines.extend(
            [
                "",
                "## em_reference_masked vs em_ref_tight",
                "",
                f"- added vs tight: **{len(a - b)}**",
                f"- removed vs tight: **{len(b - a)}**",
                f"- required includes: `{list(masked.candidate.required_include_ids)}`",
                f"- explicit excludes: `{list(masked.candidate.explicit_exclude_ids)}`",
                f"- threshold review count: **{len(masked.threshold_review_ids)}**",
                f"- source bounds: `{list(masked.source_bounds)}`",
                f"- export rect: "
                f"`({masked.export_rect.min_x:.0f},{masked.export_rect.min_y:.0f})-"
                f"({masked.export_rect.max_x:.0f},{masked.export_rect.max_y:.0f})`"
                if masked.export_rect
                else "- export rect: none",
                "",
                "### Region coverage (masked)",
                "",
            ]
        )
        for name, row in sorted(masked.region_coverage.items()):
            lines.append(f"- {'OK' if row.get('ok') else 'FAIL'} `{name}`")
    lines.extend(
        [
            "",
            "## Legend",
            "",
            "- gold outline = query rect (broad phase)",
            "- magenta outline = authored mask rings",
            "- green outline = reference extent trace",
            "- cyan outline = export bounds of included polygons",
            "- red labels = Murmansk / Arkhangelsk",
            "",
            "## Files",
            "",
            "- `preview_<id>.png` — shared-camera overviews",
            "- `closeups/<id>_*.png` — Scandinavia/N.Russia, Ukraine/Donbas/Caucasus, N.Africa/E.Med",
            "- `crop_candidates_audit.json` — machine audit",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
