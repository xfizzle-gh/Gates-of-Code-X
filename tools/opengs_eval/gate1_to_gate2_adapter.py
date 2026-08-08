#!/usr/bin/env python3
"""Convert deterministic OpenGS Gate 1 label rasters to Gates polygon assets.

Gate 2 is deliberately an isolated research adapter. It consumes a verified
Gate 1 output directory plus the exact checksummed terrain raster used by that
run and emits the existing Gates polygon dataset / strategic-map manifest
contracts. It does not register a map, alter Earth3, or touch campaign code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from io import BytesIO
import math
import os
import shutil
import stat
import tempfile
import threading
from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import gate1_pipeline
from gate1_common import AUTHORITATIVE_OUTPUTS as GATE1_AUTHORITATIVE_OUTPUTS, Gate1Error

import numpy as np
from PIL import Image
from shapely import constrained_delaunay_triangles, is_valid_reason
from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon
from shapely.ops import nearest_points, unary_union

ADAPTER_SCHEMA = "gates-of-codex.opengs-gate2-config"
ADAPTER_SCHEMA_VERSION = 1
ADAPTER_MANIFEST_SCHEMA = "gates-of-codex.opengs-gate2-manifest"
ADAPTER_MANIFEST_VERSION = 2
DATASET_SCHEMA = "gates-of-codex.earth3-polygon-dataset"
DATASET_SCHEMA_VERSION = 2
MAP_SCHEMA = "gates-of-codex.strategic-map"
MAP_SCHEMA_VERSION = 1
ADAPTER_VERSION = 2
ID_PREFIX_REQUIRED = "og2_"
AREA_REL_TOL = 1e-9
COORD_ROUND = 6
PERCENT_ROUND = 8
AUTHORITATIVE_OUTPUTS = (
    "polygon_dataset.json",
    "map_manifest.json",
    "dataset_meta.json",
    "topology_audit.json",
    "adapter_manifest.json",
)

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

PointI = tuple[int, int]
SegmentI = tuple[PointI, PointI]


class Gate2Error(RuntimeError):
    pass


@dataclass(frozen=True)
class ProvinceSource:
    source_id: str
    territory_id: str
    province_type: str
    center_x: float
    center_y: float
    rgb: tuple[int, int, int]


@dataclass(frozen=True)
class Config:
    map_id: str
    id_prefix: str
    minimum_shared_edge_pixels: int
    authored_boundary_pairs: frozenset[tuple[str, str]]
    suppressed_segments: frozenset[SegmentI]


@dataclass(frozen=True)
class Gate1Snapshot:
    manifest: dict[str, Any]
    manifest_sha256: str
    output_sha256: dict[str, str]
    sources: tuple[ProvinceSource, ...]
    labels: np.ndarray


@dataclass(frozen=True)
class TerrainSnapshot:
    sha256: str
    array: np.ndarray


@dataclass(frozen=True)
class FileSetSnapshot:
    files: Mapping[str, bytes]
    sha256: Mapping[str, str]


_GATE1_INSPECTION_LOCK = threading.Lock()


def _read_open_file_once(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise Gate2Error(f"cannot capture {label} {path}: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise Gate2Error(f"{label} must be a regular file: {path.name}")
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        after = os.fstat(fd)
        identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if identity_before != identity_after:
            raise Gate2Error(f"{label} changed while being captured: {path.name}")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _capture_file_set(root: Path, expected: Sequence[str], label: str) -> FileSetSnapshot:
    if not root.is_dir():
        raise Gate2Error(f"{label} directory missing: {root}")
    expected_set = set(expected)
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        raise Gate2Error(f"cannot inspect {label} directory {root}: {exc}") from exc
    actual = {entry.name for entry in entries}
    if actual != expected_set:
        raise Gate2Error(
            f"{label} set mismatch: missing={sorted(expected_set - actual)} "
            f"extra={sorted(actual - expected_set)}"
        )
    invalid = sorted(
        entry.name for entry in entries if entry.is_symlink() or not entry.is_file()
    )
    if invalid:
        raise Gate2Error(
            f"{label} entries must be regular files: {', '.join(invalid)}"
        )
    files = {
        name: _read_open_file_once(root / name, label)
        for name in sorted(expected_set)
    }
    try:
        final_entries = list(root.iterdir())
    except OSError as exc:
        raise Gate2Error(f"cannot recheck {label} directory {root}: {exc}") from exc
    final_names = {entry.name for entry in final_entries}
    if final_names != expected_set or any(
        entry.is_symlink() or not entry.is_file() for entry in final_entries
    ):
        raise Gate2Error(f"{label} directory changed during capture")
    return FileSetSnapshot(
        files=MappingProxyType(dict(files)),
        sha256=MappingProxyType(
            {name: sha256_bytes(data) for name, data in files.items()}
        ),
    )


def _write_file_set(root: Path, snapshot: FileSetSnapshot) -> None:
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name in sorted(snapshot.files):
        path = root / name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(path, flags, 0o600)
        try:
            data = snapshot.files[name]
            offset = 0
            while offset < len(data):
                offset += os.write(fd, data[offset:])
            os.fsync(fd)
        finally:
            os.close(fd)


def _strict_inspect_gate1_snapshot(snapshot: FileSetSnapshot) -> dict[str, Any]:
    """Run Gate 1's complete inspector against the captured bytes, never paths."""

    def snapshot_bytes(path: Path, label: str) -> bytes:
        name = Path(path).name
        try:
            return snapshot.files[name]
        except KeyError as exc:
            raise Gate1Error(
                f"strict snapshot has no authoritative bytes for {label}: {name}"
            ) from exc

    def read_canonical_json(path: Path, label: str) -> Any:
        raw = snapshot_bytes(path, label)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Gate1Error(f"cannot read {label}: {exc}") from exc
        if raw != gate1_pipeline.canonical_json_bytes(parsed):
            raise Gate1Error(f"{label} is not canonical UTF-8/LF JSON")
        return parsed

    def decode_rgb_png(
        path: Path, label: str, width: int, height: int
    ) -> np.ndarray:
        raw = snapshot_bytes(path, label)
        try:
            with Image.open(BytesIO(raw)) as image:
                image.load()
                if image.format != "PNG":
                    raise Gate1Error(f"{label} must be PNG, got {image.format}")
                if image.mode != "RGB":
                    raise Gate1Error(f"{label} must use RGB mode, got {image.mode}")
                if image.size != (width, height):
                    raise Gate1Error(
                        f"{label} dimensions must be {(width, height)}, got {image.size}"
                    )
                if image.info:
                    raise Gate1Error(
                        f"{label} contains unexpected PNG metadata: {sorted(image.info)}"
                    )
                pixels = np.asarray(image, dtype=np.uint8).copy()
        except Gate1Error:
            raise
        except (OSError, ValueError) as exc:
            raise Gate1Error(f"cannot decode {label}: {exc}") from exc
        if pixels.shape != (height, width, 3):
            raise Gate1Error(f"{label} decoded shape is invalid: {pixels.shape}")
        return pixels

    def snapshot_sha256(path: Path) -> str:
        name = Path(path).name
        try:
            return snapshot.sha256[name]
        except KeyError as exc:
            raise Gate1Error(
                f"strict snapshot has no checksum authority for {name}"
            ) from exc

    with tempfile.TemporaryDirectory(prefix=".gate1-sealed-") as temp_root:
        sealed = Path(temp_root) / "output"
        _write_file_set(sealed, snapshot)
        with _GATE1_INSPECTION_LOCK:
            original_read = gate1_pipeline._read_canonical_json
            original_decode = gate1_pipeline._decode_rgb_png
            original_sha256 = gate1_pipeline.sha256_file
            gate1_pipeline._read_canonical_json = read_canonical_json
            gate1_pipeline._decode_rgb_png = decode_rgb_png
            gate1_pipeline.sha256_file = snapshot_sha256
            try:
                result = gate1_pipeline.inspect_output(sealed)
            except Gate1Error as exc:
                raise Gate2Error(f"Gate 1 strict inspection failed: {exc}") from exc
            finally:
                gate1_pipeline._read_canonical_json = original_read
                gate1_pipeline._decode_rgb_png = original_decode
                gate1_pipeline.sha256_file = original_sha256
        recaptured = _capture_file_set(
            sealed, GATE1_AUTHORITATIVE_OUTPUTS, "sealed Gate 1 snapshot"
        )
        if dict(recaptured.files) != dict(snapshot.files):
            raise Gate2Error("sealed Gate 1 snapshot changed during strict inspection")
        return result


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _require_object(
    value: Any,
    path: str,
    *,
    required: set[str],
    allowed: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Gate2Error(f"{path} must be an object")
    allowed = required if allowed is None else allowed
    missing = sorted(required - value.keys())
    extra = sorted(value.keys() - allowed)
    if missing:
        raise Gate2Error(f"{path} missing fields: {', '.join(missing)}")
    if extra:
        raise Gate2Error(f"{path} has unexpected fields: {', '.join(extra)}")
    return value


def _require_int(value: Any, path: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Gate2Error(f"{path} must be an integer")
    if minimum is not None and value < minimum:
        raise Gate2Error(f"{path} must be >= {minimum}")
    return value


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise Gate2Error(f"{path} must be a non-empty string")
    return value


def _canonical_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def _canonical_segment(a: PointI, b: PointI) -> SegmentI:
    if a == b:
        raise Gate2Error("zero-length segment is invalid")
    return (a, b) if a < b else (b, a)


def _parse_segment(value: Any, path: str) -> SegmentI:
    if not isinstance(value, list) or len(value) != 4:
        raise Gate2Error(f"{path} must be [x1,y1,x2,y2]")
    coords = [_require_int(v, f"{path}[{i}]", minimum=0) for i, v in enumerate(value)]
    a = (coords[0], coords[1])
    b = (coords[2], coords[3])
    if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
        raise Gate2Error(f"{path} must be one axis-aligned unit grid segment")
    return _canonical_segment(a, b)


def load_config(path: Path) -> tuple[Config, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Gate2Error(f"cannot read Gate 2 config {path}: {exc}") from exc
    top = _require_object(
        payload,
        "config",
        required={
            "schema",
            "schema_version",
            "map_id",
            "id_prefix",
            "minimum_shared_edge_pixels",
            "authored_boundary_pairs",
            "suppressed_segments",
        },
    )
    if top["schema"] != ADAPTER_SCHEMA:
        raise Gate2Error(f"config.schema must be {ADAPTER_SCHEMA!r}")
    if top["schema_version"] != ADAPTER_SCHEMA_VERSION or isinstance(
        top["schema_version"], bool
    ):
        raise Gate2Error(
            f"config.schema_version must be integer {ADAPTER_SCHEMA_VERSION}"
        )
    map_id = _require_string(top["map_id"], "config.map_id")
    if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for ch in map_id):
        raise Gate2Error("config.map_id must use lowercase ASCII letters, digits, '_' or '-'")
    id_prefix = _require_string(top["id_prefix"], "config.id_prefix")
    if id_prefix != ID_PREFIX_REQUIRED:
        raise Gate2Error(f"config.id_prefix must be the isolated namespace {ID_PREFIX_REQUIRED!r}")
    minimum = _require_int(
        top["minimum_shared_edge_pixels"],
        "config.minimum_shared_edge_pixels",
        minimum=1,
    )
    pairs_raw = top["authored_boundary_pairs"]
    if not isinstance(pairs_raw, list):
        raise Gate2Error("config.authored_boundary_pairs must be an array")
    pairs: set[tuple[str, str]] = set()
    for i, item in enumerate(pairs_raw):
        if not isinstance(item, list) or len(item) != 2:
            raise Gate2Error(f"config.authored_boundary_pairs[{i}] must contain two source IDs")
        left = _require_string(item[0], f"config.authored_boundary_pairs[{i}][0]")
        right = _require_string(item[1], f"config.authored_boundary_pairs[{i}][1]")
        if left == right:
            raise Gate2Error("authored boundary pair cannot reference one province twice")
        pair = _canonical_pair(left, right)
        if pair in pairs:
            raise Gate2Error(f"duplicate authored boundary pair: {pair}")
        pairs.add(pair)
    suppressed_raw = top["suppressed_segments"]
    if not isinstance(suppressed_raw, list):
        raise Gate2Error("config.suppressed_segments must be an array")
    suppressed: set[SegmentI] = set()
    for i, item in enumerate(suppressed_raw):
        segment = _parse_segment(item, f"config.suppressed_segments[{i}]")
        if segment in suppressed:
            raise Gate2Error(f"duplicate suppressed segment: {segment}")
        suppressed.add(segment)
    return (
        Config(
            map_id=map_id,
            id_prefix=id_prefix,
            minimum_shared_edge_pixels=minimum,
            authored_boundary_pairs=frozenset(pairs),
            suppressed_segments=frozenset(suppressed),
        ),
        payload,
    )


def _load_canonical_json_bytes(raw: bytes, label: str, source: Path | str) -> Any:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Gate2Error(f"cannot read {label} {source}: {exc}") from exc
    if canonical_json_bytes(value) != raw:
        raise Gate2Error(f"{label} must be canonical UTF-8/LF JSON")
    return value



def _load_gate1(gate1_dir: Path) -> Gate1Snapshot:
    gate1_dir = gate1_dir.resolve()
    captured = _capture_file_set(
        gate1_dir, GATE1_AUTHORITATIVE_OUTPUTS, "Gate 1 output"
    )
    strict_result = _strict_inspect_gate1_snapshot(captured)
    manifest = strict_result.get("manifest")
    if not isinstance(manifest, dict):
        raise Gate2Error("Gate 1 strict inspector returned no manifest")
    if manifest != _load_canonical_json_bytes(
        captured.files["run_manifest.json"],
        "Gate 1 manifest",
        gate1_dir / "run_manifest.json",
    ):
        raise Gate2Error("Gate 1 strict inspection manifest mismatch")

    output_names = tuple(name for name in GATE1_AUTHORITATIVE_OUTPUTS if name != "run_manifest.json")
    output_sha256 = {name: captured.sha256[name] for name in output_names}
    if manifest.get("outputs") != output_sha256:
        raise Gate2Error("Gate 1 strict output provenance mismatch")

    provinces_json = _load_canonical_json_bytes(
        captured.files["provinces.json"],
        "Gate 1 provinces",
        gate1_dir / "provinces.json",
    )
    if not isinstance(provinces_json, list) or not provinces_json:
        raise Gate2Error("Gate 1 provinces must be a non-empty array")
    sources: list[ProvinceSource] = []
    colors: set[tuple[int, int, int]] = set()
    source_ids: set[str] = set()
    for i, row in enumerate(provinces_json):
        if not isinstance(row, dict):
            raise Gate2Error(f"Gate 1 provinces[{i}] must be an object")
        source_id = _require_string(
            row.get("province_id"), f"Gate 1 provinces[{i}].province_id"
        )
        if source_id in source_ids:
            raise Gate2Error(f"duplicate Gate 1 province ID: {source_id}")
        source_ids.add(source_id)
        province_type = _require_string(
            row.get("province_type"), f"Gate 1 provinces[{i}].province_type"
        )
        if province_type not in {"land", "ocean", "lake"}:
            raise Gate2Error(f"unsupported Gate 1 province type: {province_type}")
        rgb = tuple(
            _require_int(
                row.get(channel),
                f"Gate 1 provinces[{i}].{channel}",
                minimum=0,
            )
            for channel in ("R", "G", "B")
        )
        if any(v > 255 for v in rgb):
            raise Gate2Error(f"Gate 1 provinces[{i}] RGB is outside 0..255")
        if rgb in colors:
            raise Gate2Error(f"duplicate Gate 1 province color: {rgb}")
        colors.add(rgb)
        sources.append(
            ProvinceSource(
                source_id=source_id,
                territory_id=_require_string(
                    row.get("territory_id"),
                    f"Gate 1 provinces[{i}].territory_id",
                ),
                province_type=province_type,
                center_x=float(row.get("x")),
                center_y=float(row.get("y")),
                rgb=rgb,
            )
        )

    try:
        with Image.open(BytesIO(captured.files["provinces.png"])) as decoded:
            image = np.asarray(decoded.convert("RGB"), dtype=np.uint8).copy()
    except Exception as exc:
        raise Gate2Error(
            f"cannot decode captured Gate 1 provinces.png: {exc}"
        ) from exc

    dims = manifest["dimensions"]
    if image.ndim != 3 or image.shape[2] != 3:
        raise Gate2Error("Gate 1 provinces.png must be RGB")
    if [int(image.shape[1]), int(image.shape[0])] != [
        dims["width"],
        dims["height"],
    ]:
        raise Gate2Error("Gate 1 provinces.png dimensions do not match manifest")
    color_to_index = {source.rgb: i for i, source in enumerate(sources)}
    labels = np.full(image.shape[:2], -1, dtype=np.int32)
    flat = image.reshape(-1, 3)
    unique = np.unique(flat, axis=0)
    for color_arr in unique:
        color = tuple(int(v) for v in color_arr)
        if color == (0, 0, 0):
            continue
        if color not in color_to_index:
            raise Gate2Error(f"provinces.png contains unknown RGB label: {color}")
        labels[np.all(image == color_arr, axis=2)] = color_to_index[color]
    present = {int(v) for v in np.unique(labels) if int(v) >= 0}
    if present != set(range(len(sources))):
        raise Gate2Error(
            "Gate 1 label raster/record mismatch: missing labels="
            f"{sorted(set(range(len(sources))) - present)}"
        )
    return Gate1Snapshot(
        manifest=manifest,
        manifest_sha256=captured.sha256["run_manifest.json"],
        output_sha256=output_sha256,
        sources=tuple(sources),
        labels=labels,
    )


def _load_terrain(
    path: Path, gate1_manifest: dict[str, Any], shape: tuple[int, int]
) -> TerrainSnapshot:
    terrain_ref = gate1_manifest.get("inputs", {}).get("terrain")
    if terrain_ref is None:
        raise Gate2Error("Gate 2 requires the exact terrain raster; Gate 1 run recorded terrain=null")
    expected = terrain_ref.get("sha256") if isinstance(terrain_ref, dict) else None
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Gate2Error(f"cannot capture terrain raster {path}: {exc}") from exc
    digest = sha256_bytes(raw)
    if expected != digest:
        raise Gate2Error("terrain raster checksum does not match the Gate 1 manifest")
    try:
        with Image.open(BytesIO(raw)) as decoded:
            arr = np.asarray(decoded.convert("RGB"), dtype=np.uint8).copy()
    except Exception as exc:
        raise Gate2Error(f"cannot decode captured terrain raster {path}: {exc}") from exc
    if arr.shape[:2] != shape or arr.shape[2] != 3:
        raise Gate2Error("terrain raster dimensions do not match provinces.png")
    return TerrainSnapshot(sha256=digest, array=arr)

def _add_directed_boundary(
    edge_map: dict[int, set[tuple[PointI, PointI]]], label: int, a: PointI, b: PointI
) -> None:
    edge_map[label].add((a, b))


def build_boundary_graph(labels: np.ndarray) -> tuple[
    dict[int, set[tuple[PointI, PointI]]],
    dict[SegmentI, tuple[int | None, int | None]],
    dict[tuple[int, int], int],
]:
    """Build the exact unit-grid boundary graph before any simplification."""
    height, width = labels.shape
    directed: dict[int, set[tuple[PointI, PointI]]] = defaultdict(set)
    segment_sides: dict[SegmentI, tuple[int | None, int | None]] = {}
    pair_lengths: dict[tuple[int, int], int] = defaultdict(int)

    for y in range(height):
        for x in range(width):
            label = int(labels[y, x])
            if label < 0:
                continue
            # Directed edges keep the province interior on the visual-right side
            # in image coordinates (y grows downward).
            neighbors = (
                ((x, y), (x + 1, y), int(labels[y - 1, x]) if y > 0 else -1),
                ((x + 1, y), (x + 1, y + 1), int(labels[y, x + 1]) if x + 1 < width else -1),
                ((x + 1, y + 1), (x, y + 1), int(labels[y + 1, x]) if y + 1 < height else -1),
                ((x, y + 1), (x, y), int(labels[y, x - 1]) if x > 0 else -1),
            )
            for a, b, other in neighbors:
                if other == label:
                    continue
                _add_directed_boundary(directed, label, a, b)
                segment = _canonical_segment(a, b)
                if segment not in segment_sides:
                    segment_sides[segment] = (label, other if other >= 0 else None)
                if other >= 0 and other != label:
                    pair = (label, other) if label < other else (other, label)
                    pair_lengths[pair] += 1
    # Every shared side was visited from both provinces.
    for pair in list(pair_lengths):
        if pair_lengths[pair] % 2:
            raise Gate2Error(f"shared boundary ledger is asymmetric for labels {pair}")
        pair_lengths[pair] //= 2
    return directed, segment_sides, dict(pair_lengths)


_DIR = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}


def _edge_direction(a: PointI, b: PointI) -> int:
    delta = (b[0] - a[0], b[1] - a[1])
    try:
        return _DIR[delta]
    except KeyError as exc:
        raise Gate2Error(f"non-unit directed boundary edge: {a}->{b}") from exc


def _next_edge(
    current: tuple[PointI, PointI], candidates: list[tuple[PointI, PointI]]
) -> tuple[PointI, PointI]:
    incoming = _edge_direction(*current)
    # Right turn, straight, left turn, reverse. This keeps diagonal-only contacts
    # as separate components instead of joining them at one vertex.
    priority = {(incoming + 1) % 4: 0, incoming: 1, (incoming + 3) % 4: 2, (incoming + 2) % 4: 3}
    return min(candidates, key=lambda edge: (priority[_edge_direction(*edge)], edge[1]))


def trace_rings(edges: set[tuple[PointI, PointI]]) -> list[list[PointI]]:
    outgoing: dict[PointI, list[tuple[PointI, PointI]]] = defaultdict(list)
    for edge in edges:
        outgoing[edge[0]].append(edge)
    for value in outgoing.values():
        value.sort()
    unused = set(edges)
    rings: list[list[PointI]] = []
    while unused:
        start = min(unused)
        current = start
        ring = [start[0]]
        limit = len(edges) + 1
        for _ in range(limit):
            if current not in unused:
                raise Gate2Error("boundary walk reused an edge before closing")
            unused.remove(current)
            ring.append(current[1])
            if current[1] == start[0]:
                break
            candidates = [edge for edge in outgoing[current[1]] if edge in unused]
            if not candidates:
                raise Gate2Error(f"open boundary chain at {current[1]}")
            current = _next_edge(current, candidates)
        else:
            raise Gate2Error("boundary walk exceeded edge count")
        if ring[-1] != ring[0]:
            raise Gate2Error("boundary ring did not close")
        rings.append(_remove_collinear(ring[:-1]))
    rings.sort(key=lambda ring: (-abs(_signed_area(ring)), ring))
    return rings


def _remove_collinear(ring: Sequence[PointI]) -> list[PointI]:
    points = list(ring)
    if len(points) < 3:
        raise Gate2Error("ring has fewer than three vertices")
    changed = True
    while changed and len(points) >= 3:
        changed = False
        out: list[PointI] = []
        n = len(points)
        for i, b in enumerate(points):
            a = points[(i - 1) % n]
            c = points[(i + 1) % n]
            if (b[0] - a[0]) * (c[1] - b[1]) == (b[1] - a[1]) * (c[0] - b[0]):
                changed = True
                continue
            out.append(b)
        points = out
    if len(points) < 3:
        raise Gate2Error("ring collapsed during exact collinear simplification")
    return points


def _signed_area(ring: Sequence[tuple[float, float]]) -> float:
    total = 0.0
    for i, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(i + 1) % len(ring)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _normalize_winding(ring: list[PointI], *, outer: bool) -> list[PointI]:
    positive = _signed_area(ring) > 0
    if positive != outer:
        ring = list(reversed(ring))
    # Canonical rotation to lexicographically smallest point.
    start = min(range(len(ring)), key=lambda i: ring[i])
    return ring[start:] + ring[:start]


def build_components(rings: list[list[PointI]], source_id: str) -> list[Polygon]:
    outers = [_normalize_winding(ring, outer=True) for ring in rings if _signed_area(ring) > 0]
    holes = [_normalize_winding(ring, outer=False) for ring in rings if _signed_area(ring) < 0]
    if not outers:
        raise Gate2Error(f"province {source_id} has no outer ring")
    outer_polys = [Polygon(ring) for ring in outers]
    for poly in outer_polys:
        if not poly.is_valid:
            raise Gate2Error(f"province {source_id} outer ring invalid: {is_valid_reason(poly)}")
    holes_by_outer: dict[int, list[list[PointI]]] = defaultdict(list)
    for hole in holes:
        hpoly = Polygon(hole)
        if not hpoly.is_valid:
            raise Gate2Error(f"province {source_id} hole invalid: {is_valid_reason(hpoly)}")
        probe = hpoly.representative_point()
        containers = [i for i, outer in enumerate(outer_polys) if outer.contains(probe)]
        if not containers:
            raise Gate2Error(f"province {source_id} hole has no containing outer ring")
        owner = min(containers, key=lambda i: outer_polys[i].area)
        holes_by_outer[owner].append(hole)
    components: list[Polygon] = []
    for i, outer in enumerate(outers):
        poly = Polygon(outer, holes_by_outer.get(i, []))
        if not poly.is_valid:
            raise Gate2Error(f"province {source_id} component invalid: {is_valid_reason(poly)}")
        if poly.area <= 0:
            raise Gate2Error(f"province {source_id} component has non-positive area")
        components.append(poly)
    components.sort(key=lambda p: (-p.area, tuple(p.exterior.coords)))
    return components


def _flatten_ring(coords: Iterable[tuple[float, float]]) -> list[float]:
    out: list[float] = []
    for x, y in coords:
        out.extend((round(float(x), COORD_ROUND), round(float(y), COORD_ROUND)))
    return out


def _extract_triangles(geom: Any) -> Iterator[Polygon]:
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, Polygon):
        coords = list(geom.exterior.coords)[:-1]
        if len(coords) == 3 and not geom.interiors:
            yield geom
            return
        # Constrained triangulation recursively handles clipped non-triangle pieces.
        nested = constrained_delaunay_triangles(geom)
        for item in getattr(nested, "geoms", []):
            if isinstance(item, Polygon) and geom.covers(item) and item.area > 0:
                yield from _extract_triangles(item)
        return
    if isinstance(geom, (MultiPolygon, GeometryCollection)):
        for child in geom.geoms:
            yield from _extract_triangles(child)


def triangulate_components(components: Sequence[Polygon], source_id: str) -> tuple[list[float], list[int], float]:
    triangles: list[Polygon] = []
    for component in components:
        collection = constrained_delaunay_triangles(component)
        for tri in collection.geoms:
            if not isinstance(tri, Polygon) or tri.area <= 0:
                continue
            if not component.covers(tri):
                clipped = component.intersection(tri)
                triangles.extend(_extract_triangles(clipped))
            else:
                triangles.append(tri)
    if not triangles:
        raise Gate2Error(f"province {source_id} produced no retained triangles")
    triangles.sort(key=lambda t: tuple(round(v, COORD_ROUND) for xy in t.exterior.coords for v in xy))
    vertex_index: dict[tuple[float, float], int] = {}
    vertices: list[tuple[float, float]] = []
    indices: list[int] = []

    def vid(coord: tuple[float, float]) -> int:
        key = (round(float(coord[0]), COORD_ROUND), round(float(coord[1]), COORD_ROUND))
        if key not in vertex_index:
            vertex_index[key] = len(vertices)
            vertices.append(key)
        return vertex_index[key]

    tri_area = 0.0
    for tri in triangles:
        coords = list(tri.exterior.coords)[:-1]
        if len(coords) != 3:
            raise Gate2Error(f"province {source_id} triangulator returned non-triangle")
        ids = [vid(coord) for coord in coords]
        if len(set(ids)) != 3:
            raise Gate2Error(f"province {source_id} triangulator returned degenerate triangle")
        cross = (
            (vertices[ids[1]][0] - vertices[ids[0]][0])
            * (vertices[ids[2]][1] - vertices[ids[0]][1])
            - (vertices[ids[1]][1] - vertices[ids[0]][1])
            * (vertices[ids[2]][0] - vertices[ids[0]][0])
        )
        if cross < 0:
            ids[1], ids[2] = ids[2], ids[1]
        indices.extend(ids)
        tri_area += tri.area
    poly_area = sum(component.area for component in components)
    rel = abs(tri_area - poly_area) / poly_area
    if rel > AREA_REL_TOL:
        raise Gate2Error(
            f"province {source_id} triangle area mismatch: rel={rel:.12g} poly={poly_area} tri={tri_area}"
        )
    union_rel, _ = _triangle_union_contract(components, triangles, source_id)
    return _flatten_ring(vertices), indices, max(rel, union_rel)


def _terrain_palette(province_type: str) -> dict[str, tuple[int, int, int]]:
    if province_type == "land":
        return LAND_TERRAINS
    if province_type == "ocean":
        return NAVAL_TERRAINS
    return LAKE_TERRAINS


def terrain_coverage(terrain: np.ndarray, mask: np.ndarray, province_type: str) -> tuple[dict[str, float], dict[str, int], str]:
    pixels = terrain[mask]
    if pixels.size == 0:
        raise Gate2Error("province mask has no terrain pixels")
    palette = _terrain_palette(province_type)
    names = sorted(palette)
    colors = np.asarray([palette[name] for name in names], dtype=np.int32)
    values = pixels.astype(np.int32)
    dist = np.sum((values[:, None, :] - colors[None, :, :]) ** 2, axis=2)
    assignments = np.argmin(dist, axis=1)
    counts = {name: int(np.count_nonzero(assignments == i)) for i, name in enumerate(names)}
    counts = {name: count for name, count in counts.items() if count > 0}
    total = sum(counts.values())
    coverage: dict[str, float] = {}
    ordered = sorted(counts)
    remaining = 1.0
    for i, name in enumerate(ordered):
        if i == len(ordered) - 1:
            value = round(remaining, PERCENT_ROUND)
        else:
            value = round(counts[name] / total, PERCENT_ROUND)
            remaining -= value
        coverage[name] = value
    dominant = min(counts, key=lambda name: (-counts[name], name))
    return coverage, {name: counts[name] for name in ordered}, dominant


def interior_anchor(components: Sequence[Polygon]) -> tuple[float, float, float]:
    # Deterministic pole-of-inaccessibility approximation: Shapely's
    # representative point is guaranteed interior; choose the component whose
    # representative point has the greatest exact boundary distance.
    candidates: list[tuple[float, float, float, float]] = []
    for component in components:
        point = component.representative_point()
        boundary_point = nearest_points(point, component.boundary)[1]
        clearance = point.distance(boundary_point)
        candidates.append((clearance, component.area, point.x, point.y))
    clearance, _area, x, y = max(candidates, key=lambda row: (row[0], row[1], -row[2], -row[3]))
    if clearance <= 0:
        raise Gate2Error("interior anchor has zero boundary clearance")
    return round(x, 4), round(y, 4), round(clearance, 4)


def _component_payload(poly: Polygon) -> dict[str, Any]:
    outer = list(poly.exterior.coords)[:-1]
    holes = [list(interior.coords)[:-1] for interior in poly.interiors]
    return {
        "outer": _flatten_ring(outer),
        "holes": [_flatten_ring(hole) for hole in holes],
        "area": round(float(poly.area), 6),
    }


def _pair_segment_class(
    left: int | None,
    right: int | None,
    sources: Sequence[ProvinceSource],
    config: Config,
    segment: SegmentI,
) -> str | None:
    if segment in config.suppressed_segments:
        return "suppression"
    if left is None and right is None:
        return None
    if left is None or right is None:
        label = right if left is None else left
        if label is None:
            return None
        return "theatre_exterior" if sources[label].province_type == "land" else None
    if left == right:
        return None
    a, b = sources[left], sources[right]
    pair = _canonical_pair(a.source_id, b.source_id)
    if pair in config.authored_boundary_pairs:
        return "authored_boundary"
    types = {a.province_type, b.province_type}
    if types == {"land"}:
        return "internal_land"
    if "land" in types and "lake" in types:
        return "lake_shore"
    if "land" in types and "ocean" in types:
        return "coast"
    return None


def _build_border_classes(
    labels: np.ndarray,
    sources: Sequence[ProvinceSource],
    id_by_label: dict[int, str],
    config: Config,
) -> tuple[list[dict[str, Any]], list[float], list[list[float]]]:
    height, width = labels.shape
    records: list[dict[str, Any]] = []
    drawn_flat: list[float] = []
    suppressed_flat: list[list[float]] = []
    seen: set[SegmentI] = set()
    # Vertical grid lines.
    for x in range(width + 1):
        for y in range(height):
            left = int(labels[y, x - 1]) if x > 0 else -1
            right = int(labels[y, x]) if x < width else -1
            if left == right:
                continue
            segment = _canonical_segment((x, y), (x, y + 1))
            seen.add(segment)
            cls = _pair_segment_class(
                left if left >= 0 else None,
                right if right >= 0 else None,
                sources,
                config,
                segment,
            )
            if cls is None:
                continue
            record = {
                "class": cls,
                "segment": [x, y, x, y + 1],
                "left_id": id_by_label.get(left),
                "right_id": id_by_label.get(right),
            }
            records.append(record)
    # Horizontal grid lines.
    for y in range(height + 1):
        for x in range(width):
            top = int(labels[y - 1, x]) if y > 0 else -1
            bottom = int(labels[y, x]) if y < height else -1
            if top == bottom:
                continue
            segment = _canonical_segment((x, y), (x + 1, y))
            seen.add(segment)
            cls = _pair_segment_class(
                top if top >= 0 else None,
                bottom if bottom >= 0 else None,
                sources,
                config,
                segment,
            )
            if cls is None:
                continue
            records.append(
                {
                    "class": cls,
                    "segment": [x, y, x + 1, y],
                    "left_id": id_by_label.get(top),
                    "right_id": id_by_label.get(bottom),
                }
            )
    records.sort(
        key=lambda row: (
            row["class"],
            row["segment"],
            row["left_id"] or "",
            row["right_id"] or "",
        )
    )
    for row in records:
        seg = row["segment"]
        if row["class"] == "suppression":
            suppressed_flat.append([float(v) for v in seg])
        elif row["class"] not in {"theatre_exterior"}:
            drawn_flat.extend(float(v) for v in seg)
    configured_missing = sorted(config.suppressed_segments - seen)
    if configured_missing:
        raise Gate2Error(f"suppressed segments do not exist in the boundary graph: {configured_missing}")
    return records, drawn_flat, suppressed_flat


def _canonical_source_digest(path: Path) -> str:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return sha256_bytes(text.encode("utf-8"))


def _build_outputs(
    gate1_dir: Path,
    terrain_path: Path,
    config_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    config, config_payload = load_config(config_path)
    gate1 = _load_gate1(gate1_dir)
    gate1_manifest = gate1.manifest
    sources = gate1.sources
    labels = gate1.labels
    terrain_snapshot = _load_terrain(terrain_path, gate1_manifest, labels.shape)
    terrain = terrain_snapshot.array
    directed, _segment_sides, pair_lengths = build_boundary_graph(labels)

    source_order = sorted(range(len(sources)), key=lambda i: sources[i].source_id)
    id_by_label = {
        label: f"{config.id_prefix}{position + 1:06d}"
        for position, label in enumerate(source_order)
    }
    source_id_by_gate = {id_by_label[label]: sources[label].source_id for label in source_order}
    source_label_by_id = {source.source_id: i for i, source in enumerate(sources)}

    authored_missing = sorted(
        pair
        for pair in config.authored_boundary_pairs
        if pair[0] not in source_label_by_id or pair[1] not in source_label_by_id
    )
    if authored_missing:
        raise Gate2Error(f"authored boundary pair references unknown source IDs: {authored_missing}")

    provinces: list[dict[str, Any]] = []
    topology_rows: list[dict[str, Any]] = []
    total_vertices = 0
    total_triangles = 0
    max_tri_error = 0.0
    for label in source_order:
        source = sources[label]
        rings = trace_rings(directed[label])
        components = build_components(rings, source.source_id)
        vertices, triangles, tri_error = triangulate_components(components, source.source_id)
        mask = labels == label
        coverage, coverage_pixels, dominant = terrain_coverage(
            terrain, mask, source.province_type
        )
        anchor_x, anchor_y, clearance = interior_anchor(components)
        largest = components[0]
        largest_ring = list(largest.exterior.coords)[:-1]
        is_water = source.province_type in {"ocean", "lake"}
        provinces.append(
            {
                "id": id_by_label[label],
                "source_id": source.source_id,
                "territory_id": source.territory_id,
                "province_type": source.province_type,
                "is_water": is_water,
                "selectable": not is_water,
                "terrain_id": dominant,
                "terrain_coverage": coverage,
                "terrain_coverage_pixels": coverage_pixels,
                "centroid": [anchor_x, anchor_y],
                "label": [anchor_x, anchor_y],
                "anchor_clearance": clearance,
                "vertices": vertices,
                "triangles": triangles,
                "ring": _flatten_ring(largest_ring),
                "components": [_component_payload(poly) for poly in components],
                "neighbors": [],
                "area": round(float(sum(poly.area for poly in components)), 6),
            }
        )
        total_vertices += len(vertices) // 2
        total_triangles += len(triangles) // 3
        max_tri_error = max(max_tri_error, tri_error)
        topology_rows.append(
            {
                "id": id_by_label[label],
                "source_id": source.source_id,
                "component_count": len(components),
                "hole_count": sum(len(poly.interiors) for poly in components),
                "pixel_count": int(np.count_nonzero(mask)),
                "polygon_area": round(float(sum(poly.area for poly in components)), 6),
                "tri_area_relative_error": tri_error,
                "anchor_clearance": clearance,
            }
        )

    row_by_id = {row["id"]: row for row in provinces}
    adjacency_edges: list[list[str]] = []
    shared_edge_audit: list[dict[str, Any]] = []
    for (left_label, right_label), length in sorted(pair_lengths.items()):
        left_id, right_id = id_by_label[left_label], id_by_label[right_label]
        qualifies = length >= config.minimum_shared_edge_pixels
        shared_edge_audit.append(
            {
                "a": left_id,
                "b": right_id,
                "shared_edge_pixels": length,
                "minimum": config.minimum_shared_edge_pixels,
                "adjacent": qualifies,
            }
        )
        if qualifies:
            edge = [left_id, right_id] if left_id < right_id else [right_id, left_id]
            adjacency_edges.append(edge)
            row_by_id[left_id]["neighbors"].append(right_id)
            row_by_id[right_id]["neighbors"].append(left_id)
    adjacency_edges.sort()
    for row in provinces:
        row["neighbors"].sort()

    border_records, borders_flat, suppressed_segments = _build_border_classes(
        labels, sources, id_by_label, config
    )
    width, height = int(labels.shape[1]), int(labels.shape[0])
    dataset = {
        "schema": DATASET_SCHEMA,
        "schema_version": DATASET_SCHEMA_VERSION,
        "map_id": config.map_id,
        "candidate_id": "opengs_gate2_geometry_adapter",
        "province_count": len(provinces),
        "land_count": sum(not row["is_water"] for row in provinces),
        "water_count": sum(row["is_water"] for row in provinces),
        "vertex_count": total_vertices,
        "triangle_count": total_triangles,
        "edge_count": len(adjacency_edges),
        "border_segment_count": len(border_records),
        "bounds": {
            "origin_source_xy": [0.0, 0.0],
            "width": float(width),
            "height": float(height),
            "source_min_xy": [0.0, 0.0],
            "source_max_xy": [float(width), float(height)],
        },
        "coordinate_space": {"unit": "gate1_label_pixels", "y_axis": "downward_positive"},
        "gate2_contract": {
            "version": 1,
            "boundary_graph": "exact_unit_grid_before_collinear_simplification",
            "minimum_shared_edge_pixels": config.minimum_shared_edge_pixels,
            "adjacency": "reciprocal_shared_edge_only",
            "winding": "outer_positive_holes_negative_in_image_coordinates",
            "triangulation": "shapely_constrained_delaunay_hole_preserving",
            "anchor": "interior_representative_point_with_boundary_clearance",
            "terrain": "full_area_nearest_palette_percentages",
            "water": "non_selectable_ocean_and_lake_records",
            "id_namespace": config.id_prefix,
        },
        "provinces": provinces,
        "edges": adjacency_edges,
        "border_segments": borders_flat,
        "border_classes": border_records,
        "exterior_border_suppress": suppressed_segments,
        "id_map": [
            {"gates_id": gate_id, "source_id": source_id_by_gate[gate_id]}
            for gate_id in sorted(source_id_by_gate)
        ],
    }
    write_canonical_json(output_dir / "polygon_dataset.json", dataset)
    dataset_sha = sha256_file(output_dir / "polygon_dataset.json")
    manifest = {
        "schema": MAP_SCHEMA,
        "schema_version": MAP_SCHEMA_VERSION,
        "map_id": config.map_id,
        "renderer": "polygon_mesh",
        "provenance": "opengs_gate1_deterministic_output_via_gate2_adapter",
        "asset_status": "experimental_gate2_fixture",
        "polygon_dataset": {
            "path": "polygon_dataset.json",
            "sha256": dataset_sha,
            "province_count": len(provinces),
        },
        "province_count": len(provinces),
        "bounds": dataset["bounds"],
        "fallback_map_id": "europe_mediterranean_from_goe",
        "runtime_contract": {
            "gameplay_key": "province_id",
            "hit_test": "point_in_polygon_spatial_index",
            "ownership_update": "immutable_geometry_shader_lookup",
        },
        "stable_id_policy": "isolated_opengs_gate2_namespace",
        "water_policy": "water_not_normally_selectable",
        "experimental": True,
        "gate": 2,
        "source_gate1_manifest_sha256": gate1.manifest_sha256,
    }
    write_canonical_json(output_dir / "map_manifest.json", manifest)
    topology_audit = {
        "schema": "gates-of-codex.opengs-gate2-topology-audit",
        "schema_version": 1,
        "ok": True,
        "province_count": len(provinces),
        "component_count": sum(row["component_count"] for row in topology_rows),
        "hole_count": sum(row["hole_count"] for row in topology_rows),
        "adjacency_edge_count": len(adjacency_edges),
        "minimum_shared_edge_pixels": config.minimum_shared_edge_pixels,
        "max_triangle_area_relative_error": max_tri_error,
        "provinces": topology_rows,
        "shared_edges": shared_edge_audit,
        "border_class_counts": {
            cls: sum(row["class"] == cls for row in border_records)
            for cls in sorted({row["class"] for row in border_records})
        },
    }
    write_canonical_json(output_dir / "topology_audit.json", topology_audit)
    meta = {
        "map_id": config.map_id,
        "province_count": len(provinces),
        "land_count": dataset["land_count"],
        "water_count": dataset["water_count"],
        "vertex_count": total_vertices,
        "triangle_count": total_triangles,
        "edge_count": len(adjacency_edges),
        "border_segment_count": len(border_records),
        "dataset_sha256": dataset_sha,
        "bounds": dataset["bounds"],
        "sample_province_ids": [row["id"] for row in provinces[:5]],
        "gate1_recipe": gate1_manifest.get("recipe"),
    }
    write_canonical_json(output_dir / "dataset_meta.json", meta)
    source_path = Path(__file__).resolve()
    output_hashes = {
        name: sha256_file(output_dir / name)
        for name in AUTHORITATIVE_OUTPUTS
        if name != "adapter_manifest.json"
    }
    adapter_manifest = {
        "schema": ADAPTER_MANIFEST_SCHEMA,
        "schema_version": ADAPTER_MANIFEST_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "adapter_source_sha256": _canonical_source_digest(source_path),
        "config": {
            "canonical_sha256": sha256_bytes(canonical_json_bytes(config_payload)),
            "payload": config_payload,
            "map_id": config.map_id,
            "id_prefix": config.id_prefix,
            "minimum_shared_edge_pixels": config.minimum_shared_edge_pixels,
        },
        "gate1": {
            "run_manifest_sha256": gate1.manifest_sha256,
            "run_manifest": gate1_manifest,
            "recipe": gate1_manifest.get("recipe"),
            "outputs": dict(gate1.output_sha256),
        },
        "terrain_sha256": terrain_snapshot.sha256,
        "outputs": output_hashes,
        "determinism": {
            "canonical_json": True,
            "stable_label_normalization": True,
            "stable_id_assignment": True,
            "exact_grid_topology": True,
            "transactional_publish": True,
        },
    }
    write_canonical_json(output_dir / "adapter_manifest.json", adapter_manifest)
    return adapter_manifest


def convert(gate1_dir: Path, terrain: Path, config: Path, output: Path) -> dict[str, Any]:
    output = output.resolve()
    if output.exists():
        raise Gate2Error(f"output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    generation = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.gate2-build-", dir=output.parent)
    )
    publication = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.gate2-publish-", dir=output.parent)
    )
    shutil.rmtree(generation)
    shutil.rmtree(publication)
    try:
        generation.mkdir()
        gate1_dir = gate1_dir.resolve()
        terrain = terrain.resolve()
        config = config.resolve()
        _build_outputs(gate1_dir, terrain, config, generation)
        snapshot = _capture_file_set(
            generation, AUTHORITATIVE_OUTPUTS, "Gate 2 generated output"
        )
        inspect_output(
            generation, gate1_dir, terrain, config, _snapshot=snapshot
        )
        _write_file_set(publication, snapshot)
        published = _capture_file_set(
            publication, AUTHORITATIVE_OUTPUTS, "Gate 2 publication snapshot"
        )
        if published.files != snapshot.files:
            raise Gate2Error(
                "Gate 2 publication bytes differ from the inspected snapshot"
            )
        publication.replace(output)
        shutil.rmtree(generation, ignore_errors=True)
        return _load_canonical_json_bytes(
            snapshot.files["adapter_manifest.json"],
            "adapter manifest",
            output / "adapter_manifest.json",
        )
    except Exception as exc:
        for candidate in (generation, publication):
            if candidate.exists():
                shutil.rmtree(candidate, ignore_errors=True)
        if isinstance(exc, Gate2Error):
            raise
        raise Gate2Error(f"Gate 2 conversion failed before publish: {exc}") from exc


def _ring_from_flat(value: Any, path: str) -> list[tuple[float, float]]:
    if not isinstance(value, list) or len(value) < 6 or len(value) % 2:
        raise Gate2Error(f"{path} must contain at least three xy pairs")
    coords: list[tuple[float, float]] = []
    for i in range(0, len(value), 2):
        x, y = value[i], value[i + 1]
        if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            raise Gate2Error(f"{path} contains a non-numeric coordinate")
        if not math.isfinite(float(x)) or not math.isfinite(float(y)):
            raise Gate2Error(f"{path} contains a non-finite coordinate")
        coords.append((float(x), float(y)))
    return coords


def _expected_determinism() -> dict[str, bool]:
    return {
        "canonical_json": True,
        "stable_label_normalization": True,
        "stable_id_assignment": True,
        "exact_grid_topology": True,
        "transactional_publish": True,
    }


def _triangle_union_contract(
    components: Sequence[Polygon],
    triangles: Sequence[Polygon],
    pid: str,
) -> tuple[float, float]:
    component_union = unary_union(list(components))
    component_sum = sum(poly.area for poly in components)
    if component_union.is_empty or component_union.area <= 0:
        raise Gate2Error(f"{pid} component union is empty")
    component_overlap = component_sum - component_union.area
    if component_overlap / component_union.area > AREA_REL_TOL:
        raise Gate2Error(f"{pid} geometry components overlap")
    triangle_sum = sum(tri.area for tri in triangles)
    triangle_union = unary_union(list(triangles))
    if triangle_union.is_empty or triangle_union.area <= 0:
        raise Gate2Error(f"{pid} triangle union is empty")
    overlap = triangle_sum - triangle_union.area
    if overlap / component_union.area > AREA_REL_TOL:
        raise Gate2Error(f"{pid} triangles overlap")
    symmetric_difference = triangle_union.symmetric_difference(component_union).area
    relative_difference = symmetric_difference / component_union.area
    if relative_difference > AREA_REL_TOL:
        raise Gate2Error(
            f"{pid} triangle union does not exactly cover geometry: rel={relative_difference:.12g}"
        )
    return abs(triangle_sum - component_union.area) / component_union.area, relative_difference


def inspect_output(
    output: Path,
    gate1_dir: Path,
    terrain_path: Path,
    config_path: Path,
    *,
    _snapshot: FileSetSnapshot | None = None,
) -> dict[str, Any]:
    snapshot = _snapshot or _capture_file_set(
        output, AUTHORITATIVE_OUTPUTS, "Gate 2 output"
    )

    config, config_payload = load_config(config_path.resolve())
    gate1 = _load_gate1(gate1_dir.resolve())
    gate1_manifest = gate1.manifest
    sources = gate1.sources
    labels = gate1.labels
    terrain_snapshot = _load_terrain(terrain_path.resolve(), gate1_manifest, labels.shape)
    terrain = terrain_snapshot.array
    source_order = sorted(range(len(sources)), key=lambda i: sources[i].source_id)
    id_by_label = {
        label: f"{config.id_prefix}{position + 1:06d}"
        for position, label in enumerate(source_order)
    }
    directed, _segment_sides, pair_lengths = build_boundary_graph(labels)

    manifest = _load_canonical_json_bytes(
        snapshot.files["adapter_manifest.json"],
        "adapter manifest",
        output / "adapter_manifest.json",
    )
    top = _require_object(
        manifest,
        "adapter_manifest",
        required={
            "schema", "schema_version", "adapter_version", "adapter_source_sha256",
            "config", "gate1", "terrain_sha256", "outputs", "determinism",
        },
    )
    if top["schema"] != ADAPTER_MANIFEST_SCHEMA or top["schema_version"] != ADAPTER_MANIFEST_VERSION:
        raise Gate2Error("adapter manifest schema mismatch")
    if top["adapter_version"] != ADAPTER_VERSION or isinstance(top["adapter_version"], bool):
        raise Gate2Error("adapter version mismatch")
    if top["adapter_source_sha256"] != _canonical_source_digest(Path(__file__).resolve()):
        raise Gate2Error("adapter source digest mismatch")

    config_record = _require_object(
        top["config"],
        "adapter_manifest.config",
        required={"canonical_sha256", "payload", "map_id", "id_prefix", "minimum_shared_edge_pixels"},
    )
    expected_config_sha = sha256_bytes(canonical_json_bytes(config_payload))
    if config_record["canonical_sha256"] != expected_config_sha:
        raise Gate2Error("adapter config digest mismatch")
    if config_record["payload"] != config_payload:
        raise Gate2Error("adapter embedded config mismatch")
    expected_config_fields = {
        "map_id": config.map_id,
        "id_prefix": config.id_prefix,
        "minimum_shared_edge_pixels": config.minimum_shared_edge_pixels,
    }
    for key, expected in expected_config_fields.items():
        if config_record[key] != expected:
            raise Gate2Error(f"adapter config field mismatch: {key}")

    gate1_record = _require_object(
        top["gate1"],
        "adapter_manifest.gate1",
        required={"run_manifest_sha256", "run_manifest", "recipe", "outputs"},
    )
    gate1_manifest_sha = gate1.manifest_sha256
    if gate1_record["run_manifest_sha256"] != gate1_manifest_sha:
        raise Gate2Error("Gate 1 manifest digest mismatch")
    if gate1_record["run_manifest"] != gate1_manifest:
        raise Gate2Error("embedded Gate 1 manifest mismatch")
    if gate1_record["recipe"] != gate1_manifest.get("recipe"):
        raise Gate2Error("Gate 1 recipe provenance mismatch")
    expected_gate1_outputs = dict(gate1.output_sha256)
    if gate1_record["outputs"] != expected_gate1_outputs:
        raise Gate2Error("Gate 1 output provenance mismatch")
    if gate1_record["outputs"] != gate1_manifest.get("outputs"):
        raise Gate2Error("Gate 1 output provenance disagrees with manifest")
    terrain_sha = terrain_snapshot.sha256
    if top["terrain_sha256"] != terrain_sha:
        raise Gate2Error("terrain provenance digest mismatch")
    if gate1_manifest.get("inputs", {}).get("terrain", {}).get("sha256") != terrain_sha:
        raise Gate2Error("terrain provenance disagrees with Gate 1 manifest")
    if top["determinism"] != _expected_determinism():
        raise Gate2Error("adapter determinism assertions mismatch")

    outputs = top["outputs"]
    if not isinstance(outputs, dict) or set(outputs) != set(AUTHORITATIVE_OUTPUTS) - {"adapter_manifest.json"}:
        raise Gate2Error("adapter manifest output set mismatch")
    for name, digest in outputs.items():
        if digest != snapshot.sha256[name]:
            raise Gate2Error(f"Gate 2 output checksum mismatch: {name}")

    dataset = _load_canonical_json_bytes(
        snapshot.files["polygon_dataset.json"],
        "polygon dataset",
        output / "polygon_dataset.json",
    )
    map_manifest = _load_canonical_json_bytes(
        snapshot.files["map_manifest.json"],
        "map manifest",
        output / "map_manifest.json",
    )
    meta = _load_canonical_json_bytes(
        snapshot.files["dataset_meta.json"],
        "dataset meta",
        output / "dataset_meta.json",
    )
    audit = _load_canonical_json_bytes(
        snapshot.files["topology_audit.json"],
        "topology audit",
        output / "topology_audit.json",
    )
    if dataset.get("schema") != DATASET_SCHEMA or dataset.get("schema_version") != DATASET_SCHEMA_VERSION:
        raise Gate2Error("polygon dataset schema mismatch")
    if dataset.get("map_id") != config.map_id:
        raise Gate2Error("polygon dataset map ID mismatch")
    expected_bounds = {
        "origin_source_xy": [0.0, 0.0],
        "width": float(labels.shape[1]),
        "height": float(labels.shape[0]),
        "source_min_xy": [0.0, 0.0],
        "source_max_xy": [float(labels.shape[1]), float(labels.shape[0])],
    }
    if dataset.get("bounds") != expected_bounds:
        raise Gate2Error("polygon dataset bounds mismatch")
    contract = dataset.get("gate2_contract")
    expected_contract = {
        "version": 1,
        "boundary_graph": "exact_unit_grid_before_collinear_simplification",
        "minimum_shared_edge_pixels": config.minimum_shared_edge_pixels,
        "adjacency": "reciprocal_shared_edge_only",
        "winding": "outer_positive_holes_negative_in_image_coordinates",
        "triangulation": "shapely_constrained_delaunay_hole_preserving",
        "anchor": "interior_representative_point_with_boundary_clearance",
        "terrain": "full_area_nearest_palette_percentages",
        "water": "non_selectable_ocean_and_lake_records",
        "id_namespace": config.id_prefix,
    }
    if contract != expected_contract:
        raise Gate2Error("Gate 2 dataset contract mismatch")
    if map_manifest.get("schema") != MAP_SCHEMA or map_manifest.get("schema_version") != MAP_SCHEMA_VERSION or map_manifest.get("renderer") != "polygon_mesh":
        raise Gate2Error("map manifest contract mismatch")
    if map_manifest.get("map_id") != config.map_id or map_manifest.get("bounds") != expected_bounds:
        raise Gate2Error("map manifest identity or bounds mismatch")
    if map_manifest.get("water_policy") != "water_not_normally_selectable":
        raise Gate2Error("map manifest water policy mismatch")
    if map_manifest.get("stable_id_policy") != "isolated_opengs_gate2_namespace":
        raise Gate2Error("map manifest stable ID policy mismatch")
    if map_manifest.get("source_gate1_manifest_sha256") != gate1_manifest_sha:
        raise Gate2Error("map manifest Gate 1 provenance mismatch")

    provinces = dataset.get("provinces")
    if not isinstance(provinces, list) or not provinces:
        raise Gate2Error("polygon dataset provinces must be a non-empty array")
    expected_ids = [id_by_label[label] for label in source_order]
    ids = [row.get("id") for row in provinces]
    if ids != expected_ids:
        raise Gate2Error("Gate 2 province IDs do not match deterministic source ordering")
    if any(not isinstance(pid, str) or not pid.startswith(ID_PREFIX_REQUIRED) or pid.startswith("e3_") for pid in ids):
        raise Gate2Error("Gate 2 province IDs are outside the isolated namespace")
    if dataset.get("province_count") != len(provinces):
        raise Gate2Error("polygon dataset province_count mismatch")

    id_set = set(ids)
    row_by_id = {row["id"]: row for row in provinces}
    topology_rows: list[dict[str, Any]] = []
    total_vertices = 0
    total_triangles = 0
    max_tri_error = 0.0
    for position, row in enumerate(provinces):
        pid = row["id"]
        label = source_order[position]
        source = sources[label]
        if row.get("source_id") != source.source_id or row.get("territory_id") != source.territory_id or row.get("province_type") != source.province_type:
            raise Gate2Error(f"{pid} source provenance mismatch")
        is_water = source.province_type in {"ocean", "lake"}
        if row.get("is_water") is not is_water or row.get("selectable") is not (not is_water):
            raise Gate2Error(f"{pid} water/selectable contract is inconsistent")
        mask = labels == label
        expected_coverage, expected_pixels, expected_terrain_id = terrain_coverage(
            terrain, mask, source.province_type
        )
        if row.get("terrain_coverage") != expected_coverage:
            raise Gate2Error(f"{pid} terrain coverage does not match the authenticated raster")
        if row.get("terrain_coverage_pixels") != expected_pixels:
            raise Gate2Error(f"{pid} terrain pixel ledger does not match the authenticated raster")
        if row.get("terrain_id") != expected_terrain_id:
            raise Gate2Error(f"{pid} terrain ID does not match the authenticated raster")

        components_raw = row.get("components")
        if not isinstance(components_raw, list) or not components_raw:
            raise Gate2Error(f"{pid} has no geometry components")
        expected_components = build_components(
            trace_rings(directed[label]), source.source_id
        )
        expected_component_payload = [
            _component_payload(poly) for poly in expected_components
        ]
        if components_raw != expected_component_payload:
            raise Gate2Error(
                f"{pid} components do not match the authenticated Gate 1 label raster"
            )
        expected_ring = _flatten_ring(
            list(expected_components[0].exterior.coords)[:-1]
        )
        if row.get("ring") != expected_ring:
            raise Gate2Error(
                f"{pid} primary ring does not match the authenticated Gate 1 label raster"
            )
        components: list[Polygon] = []
        for ci, component in enumerate(components_raw):
            if not isinstance(component, dict) or set(component) != {"outer", "holes", "area"}:
                raise Gate2Error(f"{pid}.components[{ci}] shape mismatch")
            outer = _ring_from_flat(component["outer"], f"{pid}.components[{ci}].outer")
            holes_raw = component["holes"]
            if not isinstance(holes_raw, list):
                raise Gate2Error(f"{pid}.components[{ci}].holes must be an array")
            holes = [_ring_from_flat(hole, f"{pid}.components[{ci}].holes[{hi}]") for hi, hole in enumerate(holes_raw)]
            if _signed_area(outer) <= 0 or any(_signed_area(hole) >= 0 for hole in holes):
                raise Gate2Error(f"{pid} winding normalization mismatch")
            poly = Polygon(outer, holes)
            if not poly.is_valid or poly.area <= 0:
                raise Gate2Error(f"{pid} invalid component: {is_valid_reason(poly)}")
            if abs(float(component["area"]) - poly.area) / poly.area > AREA_REL_TOL:
                raise Gate2Error(f"{pid} component area ledger mismatch")
            components.append(poly)

        vertices = _ring_from_flat(row.get("vertices"), f"{pid}.vertices")
        indices = row.get("triangles")
        if not isinstance(indices, list) or len(indices) < 3 or len(indices) % 3:
            raise Gate2Error(f"{pid} triangle index array is invalid")
        triangles: list[Polygon] = []
        for ti in range(0, len(indices), 3):
            tri_indices = indices[ti:ti + 3]
            if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 or v >= len(vertices) for v in tri_indices):
                raise Gate2Error(f"{pid} triangle index out of range")
            tri = Polygon([vertices[v] for v in tri_indices])
            if not tri.is_valid or tri.area <= 0:
                raise Gate2Error(f"{pid} has degenerate triangle")
            if not any(poly.covers(tri) for poly in components):
                raise Gate2Error(f"{pid} triangle crosses a hole or component boundary")
            triangles.append(tri)
        tri_error, _ = _triangle_union_contract(components, triangles, pid)
        max_tri_error = max(max_tri_error, tri_error)
        union_area = unary_union(components).area
        if abs(float(row.get("area", -1)) - union_area) / union_area > AREA_REL_TOL:
            raise Gate2Error(f"{pid} province area ledger mismatch")
        total_vertices += len(vertices)
        total_triangles += len(triangles)

        anchor = row.get("centroid")
        if not isinstance(anchor, list) or len(anchor) != 2 or row.get("label") != anchor:
            raise Gate2Error(f"{pid} anchor shape invalid")
        point = Point(float(anchor[0]), float(anchor[1]))
        owner = next((poly for poly in components if poly.contains(point)), None)
        if owner is None:
            raise Gate2Error(f"{pid} anchor is not strictly interior")
        clearance = float(row.get("anchor_clearance", 0))
        if clearance <= 0 or point.distance(owner.boundary) + 1e-4 < clearance:
            raise Gate2Error(f"{pid} anchor clearance is invalid")
        neighbors = row.get("neighbors")
        if not isinstance(neighbors, list) or neighbors != sorted(set(neighbors)):
            raise Gate2Error(f"{pid} neighbors must be sorted unique")
        for neighbor in neighbors:
            if neighbor not in id_set or neighbor == pid:
                raise Gate2Error(f"{pid} references invalid neighbor {neighbor}")
        topology_rows.append({
            "id": pid,
            "source_id": source.source_id,
            "component_count": len(components),
            "hole_count": sum(len(poly.interiors) for poly in components),
            "pixel_count": int(np.count_nonzero(labels == label)),
            "polygon_area": round(float(union_area), 6),
            "tri_area_relative_error": tri_error,
            "anchor_clearance": clearance,
        })

    expected_edges: list[list[str]] = []
    expected_shared_edges: list[dict[str, Any]] = []
    expected_neighbors = {pid: [] for pid in ids}
    for (left_label, right_label), length in sorted(pair_lengths.items()):
        left_id, right_id = id_by_label[left_label], id_by_label[right_label]
        qualifies = length >= config.minimum_shared_edge_pixels
        expected_shared_edges.append({
            "a": left_id,
            "b": right_id,
            "shared_edge_pixels": length,
            "minimum": config.minimum_shared_edge_pixels,
            "adjacent": qualifies,
        })
        if qualifies:
            edge = [left_id, right_id] if left_id < right_id else [right_id, left_id]
            expected_edges.append(edge)
            expected_neighbors[left_id].append(right_id)
            expected_neighbors[right_id].append(left_id)
    expected_edges.sort()
    for pid in expected_neighbors:
        expected_neighbors[pid].sort()
    if dataset.get("edges") != expected_edges:
        raise Gate2Error("dataset adjacency does not match measured shared boundaries")
    for pid, expected in expected_neighbors.items():
        if row_by_id[pid].get("neighbors") != expected:
            raise Gate2Error(f"{pid} neighbors do not match measured shared boundaries")

    expected_border_records, expected_border_flat, expected_suppressed = _build_border_classes(
        labels, sources, id_by_label, config
    )
    if dataset.get("border_classes") != expected_border_records:
        raise Gate2Error("border class ledger does not match measured boundary graph")
    if dataset.get("border_segments") != expected_border_flat:
        raise Gate2Error("drawn border ledger does not match measured boundary graph")
    if dataset.get("exterior_border_suppress") != expected_suppressed:
        raise Gate2Error("suppressed border ledger does not match configured boundary graph")

    expected_audit = {
        "schema": "gates-of-codex.opengs-gate2-topology-audit",
        "schema_version": 1,
        "ok": True,
        "province_count": len(provinces),
        "component_count": sum(row["component_count"] for row in topology_rows),
        "hole_count": sum(row["hole_count"] for row in topology_rows),
        "adjacency_edge_count": len(expected_edges),
        "minimum_shared_edge_pixels": config.minimum_shared_edge_pixels,
        "max_triangle_area_relative_error": max_tri_error,
        "provinces": topology_rows,
        "shared_edges": expected_shared_edges,
        "border_class_counts": {
            cls: sum(row["class"] == cls for row in expected_border_records)
            for cls in sorted({row["class"] for row in expected_border_records})
        },
    }
    if audit != expected_audit:
        raise Gate2Error("topology audit does not match recomputed authority")

    expected_counts = {
        "province_count": len(provinces),
        "land_count": sum(not bool(row["is_water"]) for row in provinces),
        "water_count": sum(bool(row["is_water"]) for row in provinces),
        "vertex_count": total_vertices,
        "triangle_count": total_triangles,
        "edge_count": len(expected_edges),
        "border_segment_count": len(expected_border_records),
    }
    for key, expected in expected_counts.items():
        if dataset.get(key) != expected:
            raise Gate2Error(f"polygon dataset count mismatch: {key}")
    dataset_sha = snapshot.sha256["polygon_dataset.json"]
    expected_meta = {
        "map_id": config.map_id,
        **expected_counts,
        "dataset_sha256": dataset_sha,
        "bounds": expected_bounds,
        "sample_province_ids": ids[:5],
        "gate1_recipe": gate1_manifest.get("recipe"),
    }
    if meta != expected_meta:
        raise Gate2Error("dataset metadata does not match recomputed authority")
    expected_map_dataset = {
        "path": "polygon_dataset.json",
        "sha256": dataset_sha,
        "province_count": len(provinces),
    }
    if map_manifest.get("polygon_dataset") != expected_map_dataset or map_manifest.get("province_count") != len(provinces):
        raise Gate2Error("map manifest dataset authority mismatch")
    return manifest


def compare_runs(
    left: Path,
    right: Path,
    gate1_dir: Path,
    terrain_path: Path,
    config_path: Path,
) -> dict[str, Any]:
    left_snapshot = _capture_file_set(
        left, AUTHORITATIVE_OUTPUTS, "left Gate 2 output"
    )
    right_snapshot = _capture_file_set(
        right, AUTHORITATIVE_OUTPUTS, "right Gate 2 output"
    )
    inspect_output(
        left, gate1_dir, terrain_path, config_path, _snapshot=left_snapshot
    )
    inspect_output(
        right, gate1_dir, terrain_path, config_path, _snapshot=right_snapshot
    )
    differences = [
        name
        for name in AUTHORITATIVE_OUTPUTS
        if left_snapshot.files[name] != right_snapshot.files[name]
    ]
    result = {"identical": not differences, "differences": differences}
    if differences:
        raise Gate2Error(f"Gate 2 outputs differ: {', '.join(differences)}")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    convert_parser = sub.add_parser("convert")
    convert_parser.add_argument("gate1_output", type=Path)
    convert_parser.add_argument("--terrain", type=Path, required=True)
    convert_parser.add_argument("--config", type=Path, required=True)
    convert_parser.add_argument("--output", type=Path, required=True)
    inspect_parser = sub.add_parser("inspect-output")
    inspect_parser.add_argument("output", type=Path)
    inspect_parser.add_argument("--gate1-output", type=Path, required=True)
    inspect_parser.add_argument("--terrain", type=Path, required=True)
    inspect_parser.add_argument("--config", type=Path, required=True)
    compare_parser = sub.add_parser("compare-runs")
    compare_parser.add_argument("left", type=Path)
    compare_parser.add_argument("right", type=Path)
    compare_parser.add_argument("--gate1-output", type=Path, required=True)
    compare_parser.add_argument("--terrain", type=Path, required=True)
    compare_parser.add_argument("--config", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "convert":
            result = convert(args.gate1_output, args.terrain, args.config, args.output)
        elif args.command == "inspect-output":
            result = inspect_output(args.output, args.gate1_output, args.terrain, args.config)
        else:
            result = compare_runs(
                args.left, args.right, args.gate1_output, args.terrain, args.config
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Gate2Error as exc:
        print(f"Gate 2 error: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
