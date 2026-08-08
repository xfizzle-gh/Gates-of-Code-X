#!/usr/bin/env python3
"""Create a deterministic Gate 1 fixture and checksummed recipe."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

OCEAN = (5, 20, 18)
LAKE = (0, 255, 0)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output
    if out.exists():
        raise SystemExit(f"fixture output already exists: {out}")
    out.mkdir(parents=True)
    width, height = 320, 220

    land = Image.new("RGB", (width, height), OCEAN)
    draw = ImageDraw.Draw(land)
    draw.polygon([(18, 24), (130, 12), (176, 48), (158, 104), (210, 128), (192, 202), (84, 208), (30, 160)], fill=(230, 230, 230))
    draw.polygon([(220, 22), (300, 35), (309, 102), (276, 155), (234, 132), (244, 78)], fill=(230, 230, 230))
    draw.ellipse((96, 72, 122, 94), fill=LAKE)
    draw.ellipse((250, 76, 262, 88), fill=LAKE)
    land_path = out / "land.ppm"
    land_arr = np.asarray(land, dtype=np.uint8)
    land_path.write_bytes(f"P6\n{width} {height}\n255\n".encode("ascii") + land_arr.tobytes(order="C"))

    boundary = Image.new("RGB", (width, height), (255, 255, 255))
    bdraw = ImageDraw.Draw(boundary)
    bdraw.line([(112, 18), (116, 65), (146, 114), (142, 204)], fill=(0, 0, 0), width=2)
    bdraw.line([(236, 26), (264, 72), (274, 145)], fill=(0, 0, 0), width=2)
    boundary_path = out / "boundary.ppm"
    boundary_arr = np.asarray(boundary, dtype=np.uint8)
    boundary_path.write_bytes(f"P6\n{width} {height}\n255\n".encode("ascii") + boundary_arr.tobytes(order="C"))

    yy, xx = np.mgrid[0:height, 0:width]
    density = np.clip(210 - 150 * np.exp(-((xx - 138) ** 2 + (yy - 118) ** 2) / 6000), 0, 255).astype(np.uint8)
    density_path = out / "density.pgm"
    density_path.write_bytes(f"P5\n{width} {height}\n255\n".encode("ascii") + density.tobytes(order="C"))

    terrain = np.zeros((height, width, 3), dtype=np.uint8)
    terrain[:] = (255, 129, 66)
    terrain[yy < 80] = (89, 199, 85)
    terrain[(xx > 130) & (xx < 180)] = (157, 192, 208)
    terrain_path = out / "terrain.ppm"
    terrain_path.write_bytes(f"P6\n{width} {height}\n255\n".encode("ascii") + terrain.tobytes(order="C"))

    recipe = {
        "schema": "gates-of-codex.opengs-recipe",
        "schema_version": 1,
        "recipe_id": "gate1_ci_fixture",
        "root_seed": 8675309,
        "inputs": {
            "land": {"path": "land.ppm", "sha256": sha256(land_path)},
            "boundary": {"path": "boundary.ppm", "sha256": sha256(boundary_path)},
            "density": {"path": "density.pgm", "sha256": sha256(density_path)},
            "terrain": {"path": "terrain.ppm", "sha256": sha256(terrain_path)},
        },
        "counts": {"land_territories": 12, "ocean_territories": 5, "land_provinces": 96, "ocean_provinces": 24},
        "options": {
            "lloyd_iterations": 3, "density_strength": 2.0,
            "exclude_ocean_density": True, "jagged_land": True,
            "jagged_ocean": False, "jagged_amplitude": 0.12,
        },
    }
    recipe_path = out / "recipe.json"
    recipe_path.write_bytes((json.dumps(recipe, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    print(recipe_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
