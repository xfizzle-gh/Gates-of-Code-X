"""Generate committed local crop audit + boundary review from a local Earth3 archive."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex import __version__ as PKG_VERSION  # noqa: E402
from gates_of_codex.earth3.audit_artifact import (  # noqa: E402
    build_local_crop_audit,
    write_local_crop_audit,
)
from gates_of_codex.earth3.boundary_review import (  # noqa: E402
    build_boundary_review,
    write_boundary_review_markdown,
)
from gates_of_codex.earth3.parse import load_earth3_dataset  # noqa: E402


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=str(ROOT),
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        )
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        default=r"C:\Users\paulf\Downloads\AOH3_Earth3_map_provinces.zip",
    )
    parser.add_argument(
        "--crop-config",
        default=str(ROOT / "config/earth3/crop_candidates_v1.json"),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "docs/earth3-crop/local_crop_audit.json"),
    )
    parser.add_argument(
        "--boundary-json",
        default=str(ROOT / "docs/earth3-crop/boundary_review_em_reference_masked.json"),
    )
    parser.add_argument(
        "--boundary-md",
        default=str(ROOT / "docs/earth3-crop/BOUNDARY_REVIEW.md"),
    )
    args = parser.parse_args()

    archive = Path(args.archive)
    if not archive.is_file():
        print(f"LOCAL SOURCE REQUIRED: archive not found: {archive}", file=sys.stderr)
        return 2

    commit = _git_sha()
    payload = build_local_crop_audit(
        archive_path=archive,
        crop_config_path=args.crop_config,
        commit_sha=commit,
        tool_version=str(PKG_VERSION),
    )
    out = write_local_crop_audit(args.output, payload)
    print(f"wrote {out}")
    print(
        "oracle discrepancies=",
        payload["oracle"]["discrepancy_count_abs_gt_1e-3"],
        "flips=",
        payload["oracle"]["classification_flip_count"],
    )
    print(
        "provinces=",
        payload["crop_result"]["province_count"],
        "locations_ok=",
        payload["exact_required_locations"]["ok"],
    )

    dataset = load_earth3_dataset(archive)
    decisions = (
        ROOT / "config/earth3/threshold_decisions_em_reference_masked_v1.json"
    )
    review = build_boundary_review(dataset, decisions)
    Path(args.boundary_json).write_text(
        __import__("json").dumps(review, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_boundary_review_markdown(review, args.boundary_md)
    print(f"wrote {args.boundary_json}")
    print(f"wrote {args.boundary_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
