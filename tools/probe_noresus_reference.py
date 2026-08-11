from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


KEY_PATHS = (
    "mod.info",
    "READ ME FIRST.txt",
    "datamap_reset.sql",
    "mappoints_att.inc",
    "mappoints_def.inc",
    "mp.txt",
    "units_prod.txt",
    "player_rank_values.txt",
    "all_maps.txt",
    "new_maps.txt",
    "CE_maps.txt",
    "NORESUS CONQUEST ENHANCED.rar",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_mod_info(path: Path) -> dict[str, str | None]:
    text = path.read_text(encoding="utf-8", errors="replace")

    def match(field: str) -> str | None:
        found = re.search(rf'\{{{re.escape(field)}\s+"([^"]*)"\}}', text)
        return found.group(1) if found else None

    return {
        "name": match("name"),
        "desc": match("desc"),
        "min_game_version": match("minGameVersion"),
        "max_game_version": match("maxGameVersion"),
    }


def build_report(root: Path) -> dict[str, object]:
    root = root.resolve()
    if not root.is_dir():
        raise SystemExit(f"NORESUS reference root does not exist: {root}")

    mod_info = root / "mod.info"
    if not mod_info.is_file():
        raise SystemExit(f"Reference root is missing mod.info: {root}")

    files = sorted(path for path in root.rglob("*") if path.is_file())
    extensions: Counter[str] = Counter()
    top_level: Counter[str] = Counter()
    total_bytes = 0

    for path in files:
        relative = path.relative_to(root)
        total_bytes += path.stat().st_size
        suffix = path.suffix.lower() or "<none>"
        extensions[suffix] += 1
        top_level[relative.parts[0]] += 1

    key_files: dict[str, object] = {}
    for relative_name in KEY_PATHS:
        path = root / relative_name
        if not path.is_file():
            key_files[relative_name] = {"present": False}
            continue
        key_files[relative_name] = {
            "present": True,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }

    return {
        "reference_root": str(root),
        "identity": parse_mod_info(mod_info),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "top_level_counts": dict(top_level.most_common()),
        "extension_counts": dict(extensions.most_common()),
        "key_files": key_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a clean-room metadata report for a local NORESUS Strategic Map "
            "Workshop installation without copying its file contents into the repository."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Path to Workshop item 3180617465 or an equivalent local reference snapshot.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path. Defaults to stdout.",
    )
    args = parser.parse_args()

    report = build_report(args.root)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
