#!/usr/bin/env python3
"""Shared contracts and deterministic serialization for OpenGS Gate 1."""
from __future__ import annotations

import hashlib
import json
import math
import struct
from io import BytesIO
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image

SCHEMA = "gates-of-codex.opengs-recipe"
SCHEMA_VERSION = 1
RUN_SCHEMA = "gates-of-codex.opengs-run-manifest"
RUN_SCHEMA_VERSION = 1
GENERATOR_VERSION = 3
PINNED_ENVIRONMENT = {
    "python": "3.11.9",
    "numpy": "2.3.5",
    "pillow": "12.0.0",
    "scipy": "1.16.3",
}
UPSTREAM_REPOSITORY = "Thomas-Holtvedt/opengs-maptool"
UPSTREAM_COMMIT = "06e7ec8517bd45872cf44d77cb8784e5ffca49bb"
MAX_LLOYD_SAMPLE = 100_000
OCEAN_COLOR = (5, 20, 18)
LAKE_COLOR = (0, 255, 0)
BOUNDARY_COLOR = (0, 0, 0)
SHA256_KEYS = frozenset("0123456789abcdef")

LAND_TERRAINS = {
    "forest": (89, 199, 85), "hills": (248, 255, 153),
    "mountain": (157, 192, 208), "plains": (255, 129, 66),
    "urban": (120, 120, 120), "jungle": (127, 191, 0),
    "marsh": (76, 96, 35), "desert": (255, 127, 0),
}
NAVAL_TERRAINS = {
    "deep_ocean": (2, 38, 150), "shallow_sea": (56, 118, 217),
    "fjords": (75, 162, 198),
}
LAKE_TERRAINS = {"lakes": (58, 91, 255)}
DEFAULT_TERRAIN = {"land": "plains", "ocean": "deep_ocean", "lake": "lakes"}
AUTHORITATIVE_OUTPUTS = (
    "territories.png", "provinces.png", "territories.json",
    "provinces.json", "run_manifest.json",
)
DATA_OUTPUTS = AUTHORITATIVE_OUTPUTS[:-1]
GATE1_SOURCE_FILES = (
    "gate1_common.py", "gate1_regions.py", "gate1_pipeline.py", "gate1_generator.py",
)


class Gate1Error(RuntimeError):
    pass


@dataclass(frozen=True)
class InputSpec:
    key: str
    path: Path
    sha256: str
    data: bytes


class SeedLedger:
    """Derive stable named 64-bit seeds from one explicit root seed."""

    def __init__(self, root_seed: int, recipe_id: str) -> None:
        require_int(root_seed, "root_seed", minimum=0, maximum=2**63 - 1)
        self.root_seed = root_seed
        self.recipe_id = recipe_id
        self._values: dict[str, int] = {}

    def seed(self, name: str) -> int:
        if not isinstance(name, str) or not name or name.strip() != name:
            raise Gate1Error(f"invalid seed name: {name!r}")
        if name not in self._values:
            payload = f"gate1\0{self.root_seed}\0{self.recipe_id}\0{name}".encode("utf-8")
            self._values[name] = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
        return self._values[name]

    def manifest(self) -> dict[str, int]:
        return {name: self._values[name] for name in sorted(self._values)}


class NumberSeries:
    def __init__(self, prefix: str, start: int = 1, end: int = 999_999) -> None:
        self.prefix, self.next, self.end = prefix, start, end
        self.width = len(str(end))

    def get_id(self) -> str:
        if self.next > self.end:
            raise Gate1Error(f"number series exhausted: {self.prefix}")
        value = f"{self.prefix}{self.next:0{self.width}d}"
        self.next += 1
        return value


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= SHA256_KEYS


def require_object(value: Any, path: str, *, required: set[str], allowed: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Gate1Error(f"{path} must be an object")
    allowed = required if allowed is None else allowed
    missing = sorted(required - value.keys())
    extra = sorted(value.keys() - allowed)
    if missing:
        raise Gate1Error(f"{path} missing fields: {', '.join(missing)}")
    if extra:
        raise Gate1Error(f"{path} has unexpected fields: {', '.join(extra)}")
    return value


def require_int(value: Any, path: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Gate1Error(f"{path} must be an integer")
    if minimum is not None and value < minimum:
        raise Gate1Error(f"{path} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise Gate1Error(f"{path} must be <= {maximum}")
    return value


def require_number(value: Any, path: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Gate1Error(f"{path} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise Gate1Error(f"{path} must be finite")
    if minimum is not None and number < minimum:
        raise Gate1Error(f"{path} must be >= {minimum}")
    return number


def require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise Gate1Error(f"{path} must be boolean")
    return value


def require_string(value: Any, path: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise Gate1Error(f"{path} must be a non-empty string")
    return value


def validate_input_ref(value: Any, path: str) -> dict[str, str]:
    obj = require_object(value, path, required={"path", "sha256"})
    relative = require_string(obj["path"], f"{path}.path")
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise Gate1Error(f"{path}.path must be a contained relative path")
    digest = obj["sha256"]
    if not is_sha256(digest):
        raise Gate1Error(f"{path}.sha256 must be a lowercase SHA-256")
    return {"path": relative, "sha256": digest}


def validate_recipe_shape(recipe: Any) -> dict[str, Any]:
    top = require_object(
        recipe,
        "recipe",
        required={"schema", "schema_version", "recipe_id", "root_seed", "inputs", "counts", "options"},
    )
    if top["schema"] != SCHEMA:
        raise Gate1Error(f"recipe.schema must be {SCHEMA!r}")
    if isinstance(top["schema_version"], bool) or top["schema_version"] != SCHEMA_VERSION:
        raise Gate1Error(f"recipe.schema_version must be integer {SCHEMA_VERSION}")
    recipe_id = require_string(top["recipe_id"], "recipe.recipe_id")
    if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for ch in recipe_id):
        raise Gate1Error("recipe.recipe_id must use lowercase ASCII letters, digits, '_' or '-'")
    require_int(top["root_seed"], "recipe.root_seed", minimum=0, maximum=2**63 - 1)

    inputs = require_object(top["inputs"], "recipe.inputs", required={"land", "boundary", "density", "terrain"})
    for key in ("land", "boundary", "density"):
        validate_input_ref(inputs[key], f"recipe.inputs.{key}")
    if inputs["terrain"] is not None:
        validate_input_ref(inputs["terrain"], "recipe.inputs.terrain")

    counts = require_object(
        top["counts"], "recipe.counts",
        required={"land_territories", "ocean_territories", "land_provinces", "ocean_provinces"},
    )
    require_int(counts["land_territories"], "recipe.counts.land_territories", minimum=1)
    require_int(counts["ocean_territories"], "recipe.counts.ocean_territories", minimum=0)
    require_int(counts["land_provinces"], "recipe.counts.land_provinces", minimum=1)
    require_int(counts["ocean_provinces"], "recipe.counts.ocean_provinces", minimum=0)

    options = require_object(
        top["options"], "recipe.options",
        required={"lloyd_iterations", "density_strength", "exclude_ocean_density", "jagged_land", "jagged_ocean", "jagged_amplitude"},
    )
    require_int(options["lloyd_iterations"], "recipe.options.lloyd_iterations", minimum=0)
    require_number(options["density_strength"], "recipe.options.density_strength", minimum=0)
    require_bool(options["exclude_ocean_density"], "recipe.options.exclude_ocean_density")
    require_bool(options["jagged_land"], "recipe.options.jagged_land")
    require_bool(options["jagged_ocean"], "recipe.options.jagged_ocean")
    require_number(options["jagged_amplitude"], "recipe.options.jagged_amplitude", minimum=0)
    return top


def resolve_under(base: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute():
        raise Gate1Error(f"input path must be relative: {relative}")
    candidate = (base / relative_path).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as exc:
        raise Gate1Error(f"input path escapes recipe directory: {relative}") from exc
    return candidate


def load_recipe(recipe_path: Path, *, verify_inputs: bool = True) -> tuple[dict[str, Any], dict[str, InputSpec]]:
    try:
        raw = recipe_path.read_bytes()
        recipe = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Gate1Error(f"cannot read recipe {recipe_path}: {exc}") from exc
    recipe = validate_recipe_shape(recipe)
    SeedLedger(recipe["root_seed"], recipe["recipe_id"])

    base = recipe_path.parent
    input_specs: dict[str, InputSpec] = {}
    for key in ("land", "boundary", "density", "terrain"):
        item = recipe["inputs"][key]
        if item is None:
            continue
        try:
            path = resolve_under(base, item["path"])
            data = path.read_bytes()
        except (OSError, RuntimeError) as exc:
            raise Gate1Error(f"cannot read input {key} at {item['path']!r}: {exc}") from exc
        expected = item["sha256"]
        actual = sha256_bytes(data)
        if verify_inputs and actual != expected:
            raise Gate1Error(f"input checksum mismatch for {key}: expected {expected}, got {actual}")
        input_specs[key] = InputSpec(key, path, expected, data)
    return recipe, input_specs


def assert_inputs_unchanged(inputs: Mapping[str, InputSpec]) -> None:
    """Fail publication if an input path changed after its verified bytes were captured."""
    for key, spec in sorted(inputs.items()):
        try:
            current = spec.path.read_bytes()
        except OSError as exc:
            raise Gate1Error(f"input {key} became unreadable before publish: {exc}") from exc
        actual = sha256_bytes(current)
        if actual != spec.sha256:
            raise Gate1Error(
                f"input {key} changed after verification: expected {spec.sha256}, got {actual}"
            )


def validate_count_block(value: Any, path: str, keys: set[str]) -> dict[str, int]:
    obj = require_object(value, path, required=keys)
    for key in keys:
        require_int(obj[key], f"{path}.{key}", minimum=0)
    return obj


def validate_manifest_shape(manifest: Any) -> dict[str, Any]:
    top_keys = {
        "schema", "schema_version", "generator_version", "generator_identity",
        "upstream_repository", "upstream_commit", "recipe", "inputs",
        "derived_seeds", "counts", "dimensions", "outputs", "determinism",
        "environment", "manifest_payload_sha256",
    }
    top = require_object(manifest, "run_manifest", required=top_keys)
    if top["schema"] != RUN_SCHEMA:
        raise Gate1Error(f"run_manifest.schema must be {RUN_SCHEMA!r}")
    if isinstance(top["schema_version"], bool) or top["schema_version"] != RUN_SCHEMA_VERSION:
        raise Gate1Error(f"run_manifest.schema_version must be integer {RUN_SCHEMA_VERSION}")
    if isinstance(top["generator_version"], bool) or top["generator_version"] != GENERATOR_VERSION:
        raise Gate1Error(f"run_manifest.generator_version must be integer {GENERATOR_VERSION}")
    if top["upstream_repository"] != UPSTREAM_REPOSITORY or top["upstream_commit"] != UPSTREAM_COMMIT:
        raise Gate1Error("run_manifest upstream provenance is not pinned")

    identity = require_object(top["generator_identity"], "run_manifest.generator_identity", required={"source_files", "source_tree_sha256"})
    source_files = require_object(identity["source_files"], "run_manifest.generator_identity.source_files", required=set(GATE1_SOURCE_FILES))
    for key, digest in source_files.items():
        if not is_sha256(digest):
            raise Gate1Error(f"run_manifest.generator_identity.source_files.{key} must be a SHA-256")
    if not is_sha256(identity["source_tree_sha256"]):
        raise Gate1Error("run_manifest.generator_identity.source_tree_sha256 must be a SHA-256")
    if sha256_bytes(canonical_json_bytes(source_files)) != identity["source_tree_sha256"]:
        raise Gate1Error("run_manifest generator source tree checksum is inconsistent")

    recipe = require_object(top["recipe"], "run_manifest.recipe", required={"recipe_id", "root_seed", "canonical_sha256"})
    require_string(recipe["recipe_id"], "run_manifest.recipe.recipe_id")
    require_int(recipe["root_seed"], "run_manifest.recipe.root_seed", minimum=0, maximum=2**63 - 1)
    if not is_sha256(recipe["canonical_sha256"]):
        raise Gate1Error("run_manifest.recipe.canonical_sha256 must be a SHA-256")

    inputs = require_object(top["inputs"], "run_manifest.inputs", required={"land", "boundary", "density", "terrain"})
    for key in ("land", "boundary", "density"):
        validate_input_ref(inputs[key], f"run_manifest.inputs.{key}")
    if inputs["terrain"] is not None:
        validate_input_ref(inputs["terrain"], "run_manifest.inputs.terrain")

    seeds = top["derived_seeds"]
    if not isinstance(seeds, dict) or not seeds:
        raise Gate1Error("run_manifest.derived_seeds must be a non-empty object")
    seed_authority = SeedLedger(recipe["root_seed"], recipe["recipe_id"])
    for key, value in seeds.items():
        require_string(key, "run_manifest.derived_seeds key")
        require_int(value, f"run_manifest.derived_seeds.{key}", minimum=0, maximum=2**64 - 1)
        expected_seed = seed_authority.seed(key)
        if value != expected_seed:
            raise Gate1Error(
                f"run_manifest.derived_seeds.{key} does not match deterministic authority: "
                f"expected {expected_seed}, got {value}"
            )

    counts = require_object(top["counts"], "run_manifest.counts", required={"requested", "actual"})
    validate_count_block(counts["requested"], "run_manifest.counts.requested", {"land_territories", "ocean_territories", "land_provinces", "ocean_provinces"})
    validate_count_block(counts["actual"], "run_manifest.counts.actual", {"territories", "land_territories", "ocean_territories", "provinces", "land_provinces", "ocean_provinces", "lake_provinces"})

    dimensions = require_object(top["dimensions"], "run_manifest.dimensions", required={"width", "height"})
    require_int(dimensions["width"], "run_manifest.dimensions.width", minimum=1)
    require_int(dimensions["height"], "run_manifest.dimensions.height", minimum=1)

    outputs = require_object(top["outputs"], "run_manifest.outputs", required=set(DATA_OUTPUTS))
    for key, digest in outputs.items():
        if not is_sha256(digest):
            raise Gate1Error(f"run_manifest.outputs.{key} must be a SHA-256")

    determinism_keys = {
        "implicit_randomness", "json_canonical", "png_metadata",
        "stable_color_assignment", "stable_iteration_order",
        "canonical_recipe_identity", "transactional_publish",
    }
    determinism = require_object(top["determinism"], "run_manifest.determinism", required=determinism_keys)
    for key in determinism_keys:
        require_bool(determinism[key], f"run_manifest.determinism.{key}")
    expected_flags = {
        "implicit_randomness": False, "json_canonical": True, "png_metadata": False,
        "stable_color_assignment": True, "stable_iteration_order": True,
        "canonical_recipe_identity": True, "transactional_publish": True,
    }
    if determinism != expected_flags:
        raise Gate1Error("run_manifest determinism flags do not match the Gate 1 contract")

    environment = require_object(top["environment"], "run_manifest.environment", required={"python", "numpy", "pillow", "scipy"})
    for key in ("python", "numpy", "pillow", "scipy"):
        require_string(environment[key], f"run_manifest.environment.{key}")
    if environment != PINNED_ENVIRONMENT:
        raise Gate1Error(
            "run_manifest environment does not match the pinned Gate 1 profile: "
            f"expected {PINNED_ENVIRONMENT}, got {environment}"
        )
    requested = counts["requested"]
    actual = counts["actual"]
    if actual["land_territories"] != requested["land_territories"] or actual["ocean_territories"] != requested["ocean_territories"]:
        raise Gate1Error("run_manifest territory counts do not satisfy the requested counts")
    if actual["land_provinces"] != requested["land_provinces"] or actual["ocean_provinces"] != requested["ocean_provinces"]:
        raise Gate1Error("run_manifest province counts do not satisfy the requested counts")
    if actual["territories"] != actual["land_territories"] + actual["ocean_territories"]:
        raise Gate1Error("run_manifest total territory count is inconsistent")
    if actual["provinces"] != actual["land_provinces"] + actual["ocean_provinces"] + actual["lake_provinces"]:
        raise Gate1Error("run_manifest total province count is inconsistent")
    sample_keys = {key for key in seeds if ".lloyd.sample.component_" in key}
    replacement_keys = {key.replace(".lloyd.empty_replacement.component_", ".lloyd.sample.component_") for key in seeds if ".lloyd.empty_replacement.component_" in key}
    if not sample_keys or sample_keys != replacement_keys:
        raise Gate1Error("run_manifest Lloyd sample and empty-replacement seed streams are incomplete or unpaired")
    if not is_sha256(top["manifest_payload_sha256"]):
        raise Gate1Error("run_manifest.manifest_payload_sha256 must be a SHA-256")
    return top


def load_images(inputs: Mapping[str, InputSpec]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    def decode(key: str, mode: str) -> np.ndarray:
        try:
            with Image.open(BytesIO(inputs[key].data)) as image:
                image.load()
                return np.asarray(image.convert(mode), dtype=np.uint8)
        except (OSError, KeyError, ValueError) as exc:
            raise Gate1Error(f"cannot decode verified input image {key}: {exc}") from exc

    land = decode("land", "RGB")
    boundary = decode("boundary", "RGB")
    density = decode("density", "L")
    terrain = decode("terrain", "RGB") if "terrain" in inputs else None
    if land.shape != boundary.shape or land.shape[:2] != density.shape:
        raise Gate1Error(f"input dimensions differ: land={land.shape}, boundary={boundary.shape}, density={density.shape}")
    if terrain is not None and terrain.shape != land.shape:
        raise Gate1Error(f"terrain dimensions differ: terrain={terrain.shape}, land={land.shape}")
    return land, boundary, density, terrain


def extract_masks(land: np.ndarray, boundary: np.ndarray) -> dict[str, np.ndarray | int]:
    sea = np.all(land == np.array(OCEAN_COLOR, dtype=np.uint8), axis=2)
    lake = np.all(land == np.array(LAKE_COLOR, dtype=np.uint8), axis=2)
    land_mask = ~sea
    boundary_mask = np.all(boundary == np.array(BOUNDARY_COLOR, dtype=np.uint8), axis=2)
    return {
        "boundary_mask": boundary_mask, "land_mask": land_mask, "sea_mask": sea,
        "lake_mask": lake, "land_fill": land_mask & ~boundary_mask,
        "land_border": boundary_mask | sea, "sea_fill": sea & ~boundary_mask,
        "sea_border": boundary_mask | land_mask,
        "height": int(land.shape[0]), "width": int(land.shape[1]),
    }


def adler32_bytes(data: bytes) -> int:
    modulus, a, b = 65521, 1, 0
    for start in range(0, len(data), 5552):
        for value in data[start:start + 5552]:
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
            out.append(1 if offset == len(data) else 0)
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
    payload = (
        b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib_stored_stream(scanlines)) + png_chunk(b"IEND", b"")
    )
    path.write_bytes(payload)
