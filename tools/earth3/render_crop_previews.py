"""Generate three Earth3 Europe-Mediterranean crop candidate previews + audit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.earth3.crop import apply_crop, load_crop_candidates  # noqa: E402
from gates_of_codex.earth3.parse import load_earth3_dataset  # noqa: E402
from gates_of_codex.earth3.preview import render_crop_preview, write_audit_report  # noqa: E402


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
    parser.add_argument("--recommended", default="em_ref_tight")
    args = parser.parse_args()

    archive = Path(args.archive)
    if not archive.is_file():
        print(f"ERROR: archive not found: {archive}", file=sys.stderr)
        return 2

    print(f"loading Earth3 dataset from {archive} ...")
    dataset = load_earth3_dataset(archive)
    print(f"loaded provinces={len(dataset.provinces)} canvas={dataset.canvas_size}")

    candidates = load_crop_candidates(args.crop_config)
    results = []
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for candidate in candidates:
        print(f"applying crop {candidate.id} ...")
        result = apply_crop(dataset, candidate)
        results.append(result)
        preview_path = out_dir / f"preview_{candidate.id}.png"
        render_crop_preview(dataset, result, preview_path)
        print(
            f"  provinces={result.province_count} land={result.land_count} "
            f"water={result.water_count} verts={result.vertex_count} "
            f"edges={result.adjacency_edges} components={result.disconnected_land_components}"
        )
        print(f"  wrote {preview_path}")

    audit_path = out_dir / "crop_candidates_audit.json"
    write_audit_report(
        dataset,
        results,
        audit_path,
        recommended_id=args.recommended,
    )
    print(f"wrote {audit_path}")
    print("STATUS: awaiting owner crop approval on issue #92 — no production subset committed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
