"""One-shot coordinate analysis for crop design (dev helper)."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.earth3.parse import load_earth3_dataset  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True)
    args = parser.parse_args()
    ds = load_earth3_dataset(args.archive)
    print("provinces", len(ds.provinces), "canvas", ds.canvas_size)
    by_co: dict[int, list[int]] = defaultdict(list)
    for pid, p in ds.provinces.items():
        by_co[p.continent_id].append(pid)
    for co, ids in sorted(by_co.items()):
        xs = []
        ys = []
        for pid in ids:
            p = ds.provinces[pid]
            b = p.bounds
            xs.extend([b[0], b[2]])
            ys.extend([b[1], b[3]])
        print(
            f"continent {co} count={len(ids)} "
            f"x=[{min(xs):.0f},{max(xs):.0f}] y=[{min(ys):.0f},{max(ys):.0f}]"
        )

    # Sample westernmost/easternmost Europe land
    europe = [p for p in ds.provinces.values() if p.continent_id == 2 and not p.is_water]
    europe.sort(key=lambda p: p.centroid[0])
    print("europe land", len(europe))
    print("west sample", [(p.source_id, p.centroid) for p in europe[:5]])
    print("east sample", [(p.source_id, p.centroid) for p in europe[-5:]])
    europe_y = sorted(europe, key=lambda p: p.centroid[1])
    print("north sample (low y?)", [(p.source_id, p.centroid) for p in europe_y[:5]])
    print("south sample", [(p.source_id, p.centroid) for p in europe_y[-5:]])

    # Find provinces near known cities by scanning label points in EM-ish box guesses
    # Print density histogram of Europe centroids
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
