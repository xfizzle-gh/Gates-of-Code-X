"""Export approved Earth3 crop to Godot polygon dataset assets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.earth3.export_production import export_production_dataset  # noqa: E402


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
        "--output-dir",
        default=str(ROOT / "godot/assets/maps/earth3_europe_mediterranean"),
    )
    args = parser.parse_args()
    if not Path(args.archive).is_file():
        print(f"LOCAL SOURCE REQUIRED: archive not found: {args.archive}", file=sys.stderr)
        return 2
    result = export_production_dataset(
        archive_path=args.archive,
        crop_config_path=args.crop_config,
        output_dir=args.output_dir,
    )
    print(json.dumps({k: v for k, v in result.items() if k != "meta"}, indent=2))
    print("meta:", json.dumps(result["meta"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
