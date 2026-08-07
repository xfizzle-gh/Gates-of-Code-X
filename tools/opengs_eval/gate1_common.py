#!/usr/bin/env python3
"""Deterministic, headless OpenGS-derived map generator for Gates Gate 1.

This research tool adapts the generation approach from OpenGS Map Tool v0.3
(commit 06e7ec8517bd45872cf44d77cb8784e5ffca49bb) under the MIT license.
It does not register a Godot map, create Gates polygon geometry, or modify Earth3.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import struct
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, label as ndlabel, zoom as ndzoom
from scipy.spatial import cKDTree

SCHEMA = "gates-of-codex.opengs-recipe"
SCHEMA_VERSION = 1
RUN_SCHEMA = "gates-of-codex.opengs-run-manifest"
RUN_SCHEMA_VERSION = 1
GENERATOR_VERSION = 1
UPSTREAM_COMMIT = "06e7ec8517bd45872cf44d77cb8784e5ffca49bb"
MAX_LLOYD_SAMPLE = 100_000
OCEAN_COLOR = (5, 20, 18)
LAKE_COLOR = (0, 255, 0)
BOUNDARY_COLOR = (0, 0, 0)

LAND_TERRAINS = {
    "forest": (89, 199, 85),
    "hills": (248, 255, 153),
    "mountain": (157, 192, 208),
    "plains": (255, 129, 66),
    "urban": (120, 120, 120),
    "jungle": (127, 191, 0),
    "marsh": (76, 96, 35),
    "desert": (255, 127, 0),
}
NAVAL_TERRAINS = {
    "deep_ocean": (2, 38, 150),
    "shallow_sea": (56, 118, 217),
    "fjords": (75, 162, 198),
}
LAKE_TERRAINS = {"lakes": (58, 91, 255)}
DEFAULT_TERRAIN = {"land": "plains", "ocean": "deep_ocean", "lake": "lakes"}
AUTHORITATIVE_OUTPUTS = (
    "territories.png",
    "provinces.png",
    "territories.json",
    "provinces.json",
    "run_manifest.json",
)


class Gate1Error(RuntimeError):
    pass


@dataclass(frozen=True)
class InputSpec:
    key: str
    path: Path
    sha256: str


class SeedLedger:
    """Derives stable named 64-bit seeds from one explicit root seed."""

    def __init__(self, root_seed: int, recipe_id: str) -> None:
        if isinstance(root_seed, bool) or not isinstance(root_seed, int):
            raise Gate1Error("root_seed must be an integer")
        if root_seed < 0 or root_seed > (2**63 - 1):
            raise Gate1Error("root_seed must be in [0, 2^63-1]")
        self.root_seed = root_seed
        self.recipe_id = recipe_id
        self._values: dict[str, int] = {}

    def seed(self, name: str) -> int:
        if not name or name.strip() != name:
            raise Gate1Error(f"invalid seed name: {name!r}")
        if name not in self._values:
            payload = f"gate1\0{self.root_seed}\0{self.recipe_id}\0{name}".encode("utf-8")
            self._values[name] = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
        return self._values[name]

    def manifest(self) -> dict[str, int]:
        return {name: self._values[name] for name in sorted(self._values)}


class NumberSeries:
    def __init__(self, prefix: str, start: int = 1, end: int = 999_999) -> None:
        self.prefix = prefix
        self.next = start
        self.end = end
        self.width = len(str(end))

    def get_id(self) -> str:
        if self.next > self.end:
            raise Gate1Error(f"number series exhausted: {self.prefix}")
        value = f"{self.prefix}{self.next:0{self.width}d}"
        self.next += 1
        return value



def adler32_bytes(data: bytes) -> int:
    modulus = 65521
    a = 1
    b = 0
    for start in range(0, len(data), 5552):
        block = data[start:start + 5552]
        for value in block:
            a += value
            b += a
        a %= modulus
        b %= modulus
    return (b << 16) | a


def zlib_stored_stream(data: bytes) -> bytes:
    out = bytearray(b"\x78\x01")
    if not data:
        out.extend(b"\x01\x00\x00\xff\xff")
    else:
        offset = 0
        while offset < len(data):
            block = data[offset:offset + 65535]
            offset += len(block)
            final = 1 if offset == len(data) else 0
            out.append(final)
            length = len(block)
            out.extend(struct.pack("<HH", length, 0xFFFF ^ length))
            out.extend(block)
    out.extend(struct.pack(">I", adler32_bytes(data)))
    return bytes(out)


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    import binascii
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)


def write_deterministic_rgb_png(path: Path, pixels: np.ndarray) -> None:
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3:
        raise Gate1Error("deterministic PNG expects HxWx3 uint8")
    height, width, _ = pixels.shape
    scanlines = b"".join(b"\x00" + pixels[row].tobytes(order="C") for row in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    payload = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", ihdr) + png_chunk(b"IDAT", zlib_stored_stream(scanlines)) + png_chunk(b"IEND", b"")
    path.write_bytes(payload)

def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_under(base: Path, relative: str) -> Path:
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as exc:
        raise Gate1Error(f"input path escapes recipe directory: {relative}") from exc
    return candidate


def load_recipe(recipe_path: Path, *, verify_inputs: bool = True) -> tuple[dict[str, Any], dict[str, InputSpec]]:
    try:
        recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Gate1Error(f"cannot read recipe {recipe_path}: {exc}") from exc
    if not isinstance(recipe, dict):
        raise Gate1Error("recipe must be a JSON object")
    required = {"schema", "schema_version", "recipe_id", "root_seed", "inputs", "counts", "options"}
    missing = sorted(required - recipe.keys())
    if missing:
        raise Gate1Error(f"recipe missing fields: {', '.join(missing)}")
    if recipe["schema"] != SCHEMA or recipe["schema_version"] != SCHEMA_VERSION:
        raise Gate1Error(f"unsupported recipe schema: {recipe.get('schema')} v{recipe.get('schema_version')}")
    recipe_id = recipe["recipe_id"]
    if not isinstance(recipe_id, str) or not recipe_id or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for ch in recipe_id):
        raise Gate1Error("recipe_id must use lowercase ASCII letters, digits, '_' or '-'")
    SeedLedger(recipe["root_seed"], recipe_id)
    counts = recipe["counts"]
    for key in ("land_territories", "ocean_territories", "land_provinces", "ocean_provinces"):
        if isinstance(counts.get(key), bool) or not isinstance(counts.get(key), int) or counts[key] < 0:
            raise Gate1Error(f"counts.{key} must be a non-negative integer")
    if counts["land_territories"] <= 0 or counts["land_provinces"] <= 0:
        raise Gate1Error("land territories and provinces must be positive")
    options = recipe["options"]
    for key in ("lloyd_iterations",):
        if isinstance(options.get(key), bool) or not isinstance(options.get(key), int) or options[key] < 0:
            raise Gate1Error(f"options.{key} must be a non-negative integer")
    for key in ("density_strength", "jagged_amplitude"):
        if not isinstance(options.get(key), (int, float)) or not math.isfinite(float(options[key])) or float(options[key]) < 0:
            raise Gate1Error(f"options.{key} must be a finite non-negative number")
    for key in ("exclude_ocean_density", "jagged_land", "jagged_ocean"):
        if not isinstance(options.get(key), bool):
            raise Gate1Error(f"options.{key} must be boolean")

    base = recipe_path.parent
    inputs_obj = recipe["inputs"]
    if not isinstance(inputs_obj, dict):
        raise Gate1Error("inputs must be an object")
    input_specs: dict[str, InputSpec] = {}
    for key in ("land", "boundary", "density"):
        item = inputs_obj.get(key)
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str):
            raise Gate1Error(f"inputs.{key} must provide path and sha256")
        path = resolve_under(base, item["path"])
        if not path.is_file():
            raise Gate1Error(f"missing input {key}: {path}")
        expected = item["sha256"].lower()
        if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            raise Gate1Error(f"invalid SHA-256 for input {key}")
        if verify_inputs:
            actual = sha256_file(path)
            if actual != expected:
                raise Gate1Error(f"input checksum mismatch for {key}: expected {expected}, got {actual}")
        input_specs[key] = InputSpec(key, path, expected)
    terrain = inputs_obj.get("terrain")
    if terrain is not None:
        if not isinstance(terrain, dict) or not isinstance(terrain.get("path"), str) or not isinstance(terrain.get("sha256"), str):
            raise Gate1Error("inputs.terrain must be null or provide path and sha256")
        path = resolve_under(base, terrain["path"])
        if not path.is_file():
            raise Gate1Error(f"missing input terrain: {path}")
        expected = terrain["sha256"].lower()
        if verify_inputs:
            actual = sha256_file(path)
            if actual != expected:
                raise Gate1Error(f"input checksum mismatch for terrain: expected {expected}, got {actual}")
        input_specs["terrain"] = InputSpec("terrain", path, expected)
    return recipe, input_specs


def load_images(inputs: Mapping[str, InputSpec]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    land = np.asarray(Image.open(inputs["land"].path).convert("RGB"), dtype=np.uint8)
    boundary = np.asarray(Image.open(inputs["boundary"].path).convert("RGB"), dtype=np.uint8)
    density = np.asarray(Image.open(inputs["density"].path).convert("L"), dtype=np.uint8)
    if land.shape != boundary.shape or land.shape[:2] != density.shape:
        raise Gate1Error(f"input dimensions differ: land={land.shape}, boundary={boundary.shape}, density={density.shape}")
    terrain = None
    if "terrain" in inputs:
        terrain = np.asarray(Image.open(inputs["terrain"].path).convert("RGB"), dtype=np.uint8)
        if terrain.shape != land.shape:
            raise Gate1Error(f"terrain dimensions differ: terrain={terrain.shape}, land={land.shape}")
    return land, boundary, density, terrain


def extract_masks(land: np.ndarray, boundary: np.ndarray) -> dict[str, np.ndarray | int]:
    sea = np.all(land == np.array(OCEAN_COLOR, dtype=np.uint8), axis=2)
    lake = np.all(land == np.array(LAKE_COLOR, dtype=np.uint8), axis=2)
    land_mask = ~sea
    boundary_mask = np.all(boundary == np.array(BOUNDARY_COLOR, dtype=np.uint8), axis=2)
    return {
        "boundary_mask": boundary_mask,
        "land_mask": land_mask,
        "sea_mask": sea,
        "lake_mask": lake,
        "land_fill": land_mask & ~boundary_mask,
        "land_border": boundary_mask | sea,
        "sea_fill": sea & ~boundary_mask,
        "sea_border": boundary_mask | land_mask,
        "height": int(land.shape[0]),
        "width": int(land.shape[1]),
    }


