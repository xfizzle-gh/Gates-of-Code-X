from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import CampaignState, Faction, FactionState, Province


EARTH3_SCENARIO_ID = "earth3_v1"
EARTH3_MAP_ID = "earth3_europe_mediterranean"
EARTH3_ASSET_DIRECTORY = Path("godot/assets/maps/earth3_europe_mediterranean")
EARTH3_MANIFEST_PATH = EARTH3_ASSET_DIRECTORY / "map_manifest.json"
EARTH3_DATASET_PATH = EARTH3_ASSET_DIRECTORY / "polygon_dataset.json"
EARTH3_METADATA_PATH = EARTH3_ASSET_DIRECTORY / "dataset_meta.json"
EARTH3_PRODUCTION_AUTHORITY_PATH = Path("config/earth3/production_authority.json")
CAMPAIGN_MANIFEST_IDENTIFIER = "assets/maps/earth3_europe_mediterranean/map_manifest.json"
CAMPAIGN_DATASET_IDENTIFIER = "assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
PRODUCTION_AUTHORITY_IDENTIFIER = "config/earth3/production_authority.json"

APPROVED_MANIFEST_SHA256 = "614a926e79f11e3cfac8c867c7bacce107fc69344b17fabb6b4545cdeaa6a357"
APPROVED_DATASET_SHA256 = "8ae59bd89419a368fe9131ef7c50d94a7f1cafacd1cfae44362ac9b5d9decced"
APPROVED_EMBEDDED_DATASET_SHA256 = (
    "8ae59c33da5094b722b1ffad61d2862cdd4805369d74d6c6298425735982a241"
)
APPROVED_GEOMETRY_SHA256 = "7715807367932662642ff6d0c52faf8657b379abf6f67978a9acece3d18f2678"
APPROVED_PRODUCTION_ASSET_VERSION = "earth3_production_v1"
APPROVED_INCLUDED_IDS_SHA256 = "f3931d2e34558e451d02a7c49270b2071a79a628668c49228f5ff607a75315b8"
APPROVED_PROVINCE_COUNT = 3514
APPROVED_LAND_COUNT = 3299
APPROVED_WATER_COUNT = 215
APPROVED_SELECTABLE_COUNT = 3299
APPROVED_VERTEX_COUNT = 332838
APPROVED_TRIANGLE_COUNT = 325818
APPROVED_BORDER_SEGMENT_COUNT = 183689
APPROVED_TOPOLOGY_EDGE_COUNT = 10249
STALE_EMBEDDED_EDGE_COUNT = 10223
STALE_METADATA_SELECTABLE_COUNT = 3295

_STABLE_ID = re.compile(r"^e3_[0-9]{4}$")


class Earth3AuthorityError(ValueError):
    """Committed Earth3 production authority is missing or inconsistent."""


@dataclass(frozen=True, slots=True)
class Earth3Authority:
    root: Path
    manifest: dict[str, Any]
    dataset: dict[str, Any]
    metadata: dict[str, Any]
    production: dict[str, Any]
    provinces: tuple[dict[str, Any], ...]
    manifest_sha256: str
    dataset_sha256: str
    embedded_dataset_sha256: str
    geometry_sha256: str
    production_asset_version: str
    topology_edge_count: int
    included_ids_sha256: str


def _default_authority_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalized_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _sha256_text(path: Path, *, strip_one_trailing_newline: bool = False) -> str:
    text = _normalized_text(path)
    if strip_one_trailing_newline and text.endswith("\n"):
        text = text[:-1]
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_required_json(path: Path, *, label: str, identifier: str) -> dict[str, Any]:
    if not path.is_file():
        raise Earth3AuthorityError(f"{label} missing: {identifier}")
    try:
        value = json.loads(_normalized_text(path))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Earth3AuthorityError(f"{label} is not valid UTF-8 JSON: {identifier}: {exc}") from exc
    if not isinstance(value, dict):
        raise Earth3AuthorityError(f"{label} must be a JSON object: {identifier}")
    return value


def _require_equal(actual: Any, expected: Any, *, field: str, source: str) -> None:
    if actual != expected:
        raise Earth3AuthorityError(
            f"Earth3 {source} {field} mismatch: expected {expected!r}, got {actual!r}"
        )


def _require_int(value: Any, *, field: str, source: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Earth3AuthorityError(f"Earth3 {source} {field} must be an integer")
    return value


def _require_coordinate_pair(value: Any, *, field: str, province_id: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise Earth3AuthorityError(f"Earth3 province {province_id} {field} must contain two coordinates")
    coordinates: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise Earth3AuthorityError(f"Earth3 province {province_id} {field} must be numeric")
        coordinate = float(item)
        if not math.isfinite(coordinate):
            raise Earth3AuthorityError(f"Earth3 province {province_id} {field} must be finite")
        coordinates.append(coordinate)
    return coordinates[0], coordinates[1]


def _require_numeric_sequence(
    value: Any,
    *,
    field: str,
    province_id: str,
    multiple: int,
) -> list[int | float]:
    if not isinstance(value, list) or not value or len(value) % multiple:
        raise Earth3AuthorityError(
            f"Earth3 province {province_id} {field} must be a non-empty "
            f"array with length divisible by {multiple}"
        )
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise Earth3AuthorityError(f"Earth3 province {province_id} {field} must be numeric")
        if not math.isfinite(float(item)):
            raise Earth3AuthorityError(f"Earth3 province {province_id} {field} must be finite")
    return value


def _validate_count_authority(
    manifest: dict[str, Any],
    dataset: dict[str, Any],
    metadata: dict[str, Any],
    production: dict[str, Any],
) -> None:
    strict_counts = (
        (
            "province_count",
            APPROVED_PROVINCE_COUNT,
            (
                ("manifest", manifest),
                ("polygon dataset", dataset),
                ("dataset metadata", metadata),
                ("production authority", production),
            ),
        ),
        (
            "land_count",
            APPROVED_LAND_COUNT,
            (
                ("polygon dataset", dataset),
                ("dataset metadata", metadata),
                ("production authority", production),
            ),
        ),
        (
            "water_count",
            APPROVED_WATER_COUNT,
            (
                ("polygon dataset", dataset),
                ("dataset metadata", metadata),
                ("production authority", production),
            ),
        ),
        (
            "selectable_province_count",
            APPROVED_SELECTABLE_COUNT,
            (("production authority", production),),
        ),
        (
            "source_water_metadata_count",
            APPROVED_WATER_COUNT,
            (
                ("dataset metadata", metadata),
                ("production authority", production),
            ),
        ),
        (
            "vertex_count",
            APPROVED_VERTEX_COUNT,
            (("polygon dataset", dataset), ("dataset metadata", metadata)),
        ),
        (
            "triangle_count",
            APPROVED_TRIANGLE_COUNT,
            (("polygon dataset", dataset), ("dataset metadata", metadata)),
        ),
        (
            "border_segment_count",
            APPROVED_BORDER_SEGMENT_COUNT,
            (("polygon dataset", dataset), ("dataset metadata", metadata)),
        ),
    )
    for field, approved, sources in strict_counts:
        for source_name, source in sources:
            actual = _require_int(source.get(field), field=field, source=source_name)
            _require_equal(actual, approved, field=field, source=source_name)

    # Issue #176 identifies exactly these two summaries as stale. Keep their
    # committed values pinned so this exception cannot widen to other metadata.
    _require_equal(
        _require_int(dataset.get("edge_count"), field="edge_count", source="polygon dataset"),
        STALE_EMBEDDED_EDGE_COUNT,
        field="stale edge_count summary",
        source="polygon dataset",
    )
    _require_equal(
        _require_int(metadata.get("edge_count"), field="edge_count", source="dataset metadata"),
        STALE_EMBEDDED_EDGE_COUNT,
        field="stale edge_count summary",
        source="dataset metadata",
    )
    _require_equal(
        _require_int(
            metadata.get("selectable_province_count"),
            field="selectable_province_count",
            source="dataset metadata",
        ),
        STALE_METADATA_SELECTABLE_COUNT,
        field="stale selectable_province_count summary",
        source="dataset metadata",
    )


def _validate_identity_and_hash_authority(
    manifest: dict[str, Any],
    dataset: dict[str, Any],
    metadata: dict[str, Any],
    production: dict[str, Any],
    *,
    embedded_dataset_sha256: str,
) -> None:
    _require_equal(
        manifest.get("schema"),
        "gates-of-codex.strategic-map",
        field="schema",
        source="manifest",
    )
    _require_equal(manifest.get("renderer"), "polygon_mesh", field="renderer", source="manifest")
    _require_equal(manifest.get("schema_version"), 1, field="schema_version", source="manifest")
    _require_equal(
        manifest.get("asset_status"),
        "production_theatre",
        field="asset_status",
        source="manifest",
    )
    _require_equal(
        dataset.get("schema"),
        "gates-of-codex.earth3-polygon-dataset",
        field="schema",
        source="polygon dataset",
    )
    _require_equal(dataset.get("schema_version"), 2, field="schema_version", source="polygon dataset")
    _require_equal(
        production.get("schema"),
        "gates-of-codex.earth3-production-authority",
        field="schema",
        source="production authority",
    )
    _require_equal(
        production.get("schema_version"), 3, field="schema_version", source="production authority"
    )
    _require_equal(
        production.get("status"), "production", field="status", source="production authority"
    )
    for source_name, source in (
        ("manifest", manifest),
        ("polygon dataset", dataset),
        ("dataset metadata", metadata),
        ("production authority", production),
    ):
        _require_equal(source.get("map_id"), EARTH3_MAP_ID, field="map_id", source=source_name)

    polygon_authority = manifest.get("polygon_dataset")
    if not isinstance(polygon_authority, dict):
        raise Earth3AuthorityError("Earth3 manifest polygon_dataset must be an object")
    _require_equal(
        polygon_authority.get("path"),
        "polygon_dataset.json",
        field="polygon_dataset.path",
        source="manifest",
    )
    _require_equal(
        polygon_authority.get("sha256"),
        embedded_dataset_sha256,
        field="polygon_dataset.sha256",
        source="manifest",
    )
    _require_equal(
        polygon_authority.get("province_count"),
        APPROVED_PROVINCE_COUNT,
        field="polygon_dataset.province_count",
        source="manifest",
    )
    for source_name, actual in (
        ("manifest", manifest.get("included_source_ids_sha256")),
        ("polygon dataset", dataset.get("included_source_ids_sha256")),
        ("dataset metadata", metadata.get("included_source_ids_sha256")),
        ("production authority", production.get("included_ids_sha256")),
    ):
        _require_equal(
            actual,
            APPROVED_INCLUDED_IDS_SHA256,
            field="included_ids_sha256",
            source=source_name,
        )
    for source_name, actual in (
        ("dataset metadata", metadata.get("dataset_sha256")),
        ("production authority", production.get("dataset_sha256")),
    ):
        _require_equal(
            actual,
            embedded_dataset_sha256,
            field="dataset_sha256",
            source=source_name,
        )

    # This frozen manifest field is validated but never followed by the Earth3
    # builder or frontend resolver. P1 removes fallback behavior, not authority bytes.
    _require_equal(
        manifest.get("fallback_map_id"),
        "europe_mediterranean_from_goe",
        field="fallback_map_id",
        source="manifest",
    )
    _require_equal(
        manifest.get("bounds"), dataset.get("bounds"), field="bounds", source="manifest"
    )
    _require_equal(
        metadata.get("bounds"), dataset.get("bounds"), field="bounds", source="dataset metadata"
    )
    _require_equal(
        manifest.get("water_policy"),
        "water_not_normally_selectable",
        field="water_policy",
        source="manifest",
    )
    _require_equal(
        metadata.get("water_policy"),
        "water_not_normally_selectable",
        field="water_policy",
        source="dataset metadata",
    )
    _require_equal(
        production.get("stable_id_policy"),
        "retain_e3_ids_with_permanent_gaps_append_restores",
        field="stable_id_policy",
        source="production authority",
    )
    _require_equal(
        manifest.get("stable_id_policy"),
        "retain_production_e3_ids_with_gaps",
        field="stable_id_policy",
        source="manifest",
    )
    _require_equal(metadata.get("stable_ids"), True, field="stable_ids", source="dataset metadata")
    expected_excluded_source_ids = [10920, 11031]
    expected_excluded_gates_ids = ["e3_2830", "e3_2888"]
    expected_restored_source_ids = [11170, 11323, 11689, 11790]
    expected_restored_gates_ids = ["e3_3512", "e3_3513", "e3_3514", "e3_3515"]
    for source_name, source in (
        ("dataset metadata sanitization", metadata.get("sanitization")),
        ("production authority", production),
    ):
        if not isinstance(source, dict):
            raise Earth3AuthorityError(f"Earth3 {source_name} must be an object")
        _require_equal(
            source.get("excluded_source_ids"),
            expected_excluded_source_ids,
            field="excluded_source_ids",
            source=source_name,
        )
        _require_equal(
            source.get("excluded_gates_ids"),
            expected_excluded_gates_ids,
            field="excluded_gates_ids",
            source=source_name,
        )
    for source_name, source in (
        ("dataset metadata", metadata),
        ("production authority", production),
    ):
        _require_equal(
            source.get("restored_source_ids"),
            expected_restored_source_ids,
            field="restored_source_ids",
            source=source_name,
        )
        _require_equal(
            source.get("restored_gates_ids"),
            expected_restored_gates_ids,
            field="restored_gates_ids",
            source=source_name,
        )
    _require_equal(
        metadata.get("permanent_unused_gaps"),
        expected_excluded_gates_ids,
        field="permanent_unused_gaps",
        source="dataset metadata",
    )
    water_policy = production.get("water_policy")
    if not isinstance(water_policy, dict):
        raise Earth3AuthorityError("Earth3 production authority water_policy must be an object")
    _require_equal(water_policy.get("accepted"), True, field="water_policy.accepted", source="production authority")
    _require_equal(
        water_policy.get("v1"),
        "water_not_normally_selectable",
        field="water_policy.v1",
        source="production authority",
    )
    _require_equal(
        water_policy.get("normal_click_returns"),
        "no_province",
        field="water_policy.normal_click_returns",
        source="production authority",
    )
    _require_equal(
        water_policy.get("source_water_ids"),
        "import_metadata_only",
        field="water_policy.source_water_ids",
        source="production authority",
    )
    _require_equal(
        water_policy.get("sea_movement"),
        "authored_operational_nodes_edges",
        field="water_policy.sea_movement",
        source="production authority",
    )


def _validate_provinces_and_adjacency(
    dataset: dict[str, Any],
    production: dict[str, Any],
) -> tuple[tuple[dict[str, Any], ...], int]:
    raw_rows = dataset.get("provinces")
    if not isinstance(raw_rows, list):
        raise Earth3AuthorityError("Earth3 polygon dataset provinces must be an array")
    if len(raw_rows) != APPROVED_PROVINCE_COUNT:
        raise Earth3AuthorityError(
            f"Earth3 polygon dataset province rows mismatch: expected {APPROVED_PROVINCE_COUNT}, "
            f"got {len(raw_rows)}"
        )

    rows: list[dict[str, Any]] = []
    province_ids: list[str] = []
    source_ids: list[int] = []
    water_count = 0
    for index, raw_row in enumerate(raw_rows):
        if not isinstance(raw_row, dict):
            raise Earth3AuthorityError(f"Earth3 province row {index} must be an object")
        province_id = raw_row.get("id")
        if not isinstance(province_id, str) or _STABLE_ID.fullmatch(province_id) is None:
            raise Earth3AuthorityError(f"Earth3 province row {index} has invalid stable ID {province_id!r}")
        source_id = _require_int(raw_row.get("source_id"), field="source_id", source=province_id)
        is_water = raw_row.get("is_water")
        if not isinstance(is_water, bool):
            raise Earth3AuthorityError(f"Earth3 province {province_id} is_water must be bool")
        _require_int(raw_row.get("terrain_id"), field="terrain_id", source=province_id)
        _require_int(raw_row.get("continent_id"), field="continent_id", source=province_id)
        _require_coordinate_pair(raw_row.get("centroid"), field="centroid", province_id=province_id)
        _require_coordinate_pair(raw_row.get("label"), field="label", province_id=province_id)
        vertices = _require_numeric_sequence(
            raw_row.get("vertices"), field="vertices", province_id=province_id, multiple=2
        )
        _require_numeric_sequence(
            raw_row.get("ring"), field="ring", province_id=province_id, multiple=2
        )
        triangles = _require_numeric_sequence(
            raw_row.get("triangles"), field="triangles", province_id=province_id, multiple=3
        )
        if any(not isinstance(item, int) for item in triangles):
            raise Earth3AuthorityError(f"Earth3 province {province_id} triangles must be integer indices")
        point_count = len(vertices) // 2
        if any(item < 0 or item >= point_count for item in triangles):
            raise Earth3AuthorityError(
                f"Earth3 province {province_id} triangles reference an invalid vertex"
            )
        area = raw_row.get("area")
        if isinstance(area, bool) or not isinstance(area, (int, float)) or not math.isfinite(float(area)):
            raise Earth3AuthorityError(f"Earth3 province {province_id} area must be finite and numeric")
        if float(area) <= 0:
            raise Earth3AuthorityError(f"Earth3 province {province_id} area must be positive")
        neighbors = raw_row.get("neighbors")
        if not isinstance(neighbors, list) or any(not isinstance(item, str) for item in neighbors):
            raise Earth3AuthorityError(f"Earth3 province {province_id} neighbors must be an array of IDs")
        if province_id in neighbors:
            raise Earth3AuthorityError(f"Earth3 province {province_id} cannot neighbor itself")
        if len(neighbors) != len(set(neighbors)):
            raise Earth3AuthorityError(f"Earth3 province {province_id} has duplicate adjacency")
        province_ids.append(province_id)
        source_ids.append(source_id)
        water_count += int(is_water)
        rows.append(raw_row)

    if len(province_ids) != len(set(province_ids)):
        raise Earth3AuthorityError("Earth3 stable province IDs must be unique")
    if len(source_ids) != len(set(source_ids)):
        raise Earth3AuthorityError("Earth3 source province IDs must be unique")
    if province_ids != sorted(province_ids):
        raise Earth3AuthorityError("Earth3 stable province IDs must be deterministic and sorted")
    included_payload = ",".join(str(value) for value in sorted(source_ids))
    included_hash = hashlib.sha256(included_payload.encode("utf-8")).hexdigest()
    _require_equal(
        included_hash,
        APPROVED_INCLUDED_IDS_SHA256,
        field="included_ids_sha256",
        source="province rows",
    )
    if water_count != APPROVED_WATER_COUNT:
        raise Earth3AuthorityError(
            f"Earth3 province water count mismatch: expected {APPROVED_WATER_COUNT}, got {water_count}"
        )
    land_count = len(rows) - water_count
    if land_count != APPROVED_LAND_COUNT:
        raise Earth3AuthorityError(
            f"Earth3 province land count mismatch: expected {APPROVED_LAND_COUNT}, got {land_count}"
        )
    border_segments = dataset.get("border_segments")
    if not isinstance(border_segments, list) or len(border_segments) % 4:
        raise Earth3AuthorityError(
            "Earth3 polygon dataset border_segments must be a flat x1/y1/x2/y2 array"
        )
    _require_equal(
        len(border_segments) // 4,
        APPROVED_BORDER_SEGMENT_COUNT,
        field="derived border_segment_count",
        source="polygon dataset",
    )

    id_set = set(province_ids)
    by_id = {str(row["id"]): row for row in rows}
    row_edges: set[tuple[str, str]] = set()
    for province_id, row in by_id.items():
        for neighbor_id in row["neighbors"]:
            if neighbor_id not in id_set:
                raise Earth3AuthorityError(
                    f"Earth3 province {province_id} references missing neighbor {neighbor_id}"
                )
            if province_id not in by_id[neighbor_id]["neighbors"]:
                raise Earth3AuthorityError(
                    f"Earth3 committed adjacency is not reciprocal: {province_id} -> {neighbor_id}"
                )
            row_edges.add(tuple(sorted((province_id, neighbor_id))))

    raw_edges = dataset.get("edges")
    if not isinstance(raw_edges, list):
        raise Earth3AuthorityError("Earth3 polygon dataset edges must be an array")
    declared_edges: set[tuple[str, str]] = set()
    for index, edge in enumerate(raw_edges):
        if (
            not isinstance(edge, list)
            or len(edge) != 2
            or any(not isinstance(item, str) for item in edge)
        ):
            raise Earth3AuthorityError(f"Earth3 committed edge row {index} must contain two IDs")
        a, b = edge
        if a == b or a not in id_set or b not in id_set:
            raise Earth3AuthorityError(f"Earth3 committed edge row {index} is invalid: {edge!r}")
        normalized = tuple(sorted((a, b)))
        if normalized in declared_edges:
            raise Earth3AuthorityError(f"Earth3 committed edge row {index} is duplicated: {edge!r}")
        declared_edges.add(normalized)
    if declared_edges != row_edges:
        raise Earth3AuthorityError("Earth3 committed edge list does not match province adjacency")
    _require_equal(
        len(declared_edges),
        APPROVED_TOPOLOGY_EDGE_COUNT,
        field="derived topology edge count",
        source="committed edge list",
    )

    raw_id_map = dataset.get("id_map")
    expected_id_map = [
        {"gates_id": province_id, "source_id": source_id}
        for province_id, source_id in zip(province_ids, source_ids, strict=True)
    ]
    _require_equal(raw_id_map, expected_id_map, field="id_map", source="polygon dataset")
    for gap in production.get("excluded_gates_ids", []):
        if gap in id_set:
            raise Earth3AuthorityError(f"Earth3 permanently excluded stable ID is present: {gap}")
    for restored in production.get("restored_gates_ids", []):
        if restored not in id_set:
            raise Earth3AuthorityError(f"Earth3 restored stable ID is missing: {restored}")
    return tuple(rows), len(declared_edges)


def load_earth3_authority(authority_root: str | Path | None = None) -> Earth3Authority:
    root = Path(authority_root) if authority_root is not None else _default_authority_root()
    manifest_path = root / EARTH3_MANIFEST_PATH
    dataset_path = root / EARTH3_DATASET_PATH
    metadata_path = root / EARTH3_METADATA_PATH
    production_path = root / EARTH3_PRODUCTION_AUTHORITY_PATH

    manifest = _read_required_json(
        manifest_path,
        label="Earth3 manifest",
        identifier=EARTH3_MANIFEST_PATH.as_posix(),
    )
    if not dataset_path.is_file():
        raise Earth3AuthorityError(
            f"Earth3 production dataset missing: {EARTH3_DATASET_PATH.as_posix()}"
        )
    embedded_dataset_sha256 = _sha256_text(
        dataset_path, strip_one_trailing_newline=True
    )
    if embedded_dataset_sha256 != APPROVED_EMBEDDED_DATASET_SHA256:
        raise Earth3AuthorityError(
            "Earth3 production dataset bytes/SHA-256 mismatch: "
            f"expected embedded digest {APPROVED_EMBEDDED_DATASET_SHA256}, "
            f"got {embedded_dataset_sha256}"
        )
    manifest_sha256 = _sha256_text(manifest_path)
    if manifest_sha256 != APPROVED_MANIFEST_SHA256:
        raise Earth3AuthorityError(
            "Earth3 manifest SHA-256 mismatch: "
            f"expected {APPROVED_MANIFEST_SHA256}, got {manifest_sha256}"
        )
    dataset = _read_required_json(
        dataset_path,
        label="Earth3 production dataset",
        identifier=EARTH3_DATASET_PATH.as_posix(),
    )
    metadata = _read_required_json(
        metadata_path,
        label="Earth3 dataset metadata",
        identifier=EARTH3_METADATA_PATH.as_posix(),
    )
    production = _read_required_json(
        production_path,
        label="Earth3 production authority",
        identifier=EARTH3_PRODUCTION_AUTHORITY_PATH.as_posix(),
    )
    _validate_count_authority(manifest, dataset, metadata, production)
    _validate_identity_and_hash_authority(
        manifest,
        dataset,
        metadata,
        production,
        embedded_dataset_sha256=embedded_dataset_sha256,
    )
    provinces, topology_edge_count = _validate_provinces_and_adjacency(dataset, production)
    # The owner-ruling dataset and geometry digests are provenance contracts.
    # They are attached only after the frozen export bytes, its embedded digest,
    # and the independently checked structural authority all validate.
    return Earth3Authority(
        root=root,
        manifest=manifest,
        dataset=dataset,
        metadata=metadata,
        production=production,
        provinces=provinces,
        manifest_sha256=manifest_sha256,
        dataset_sha256=APPROVED_DATASET_SHA256,
        embedded_dataset_sha256=embedded_dataset_sha256,
        geometry_sha256=APPROVED_GEOMETRY_SHA256,
        production_asset_version=APPROVED_PRODUCTION_ASSET_VERSION,
        topology_edge_count=topology_edge_count,
        included_ids_sha256=APPROVED_INCLUDED_IDS_SHA256,
    )


def build_earth3_campaign(authority_root: str | Path | None = None) -> CampaignState:
    authority = load_earth3_authority(authority_root)
    provinces: dict[str, Province] = {}
    for row in authority.provinces:
        province_id = str(row["id"])
        is_water = bool(row["is_water"])
        label_x, label_y = _require_coordinate_pair(
            row["label"], field="label", province_id=province_id
        )
        centroid_x, centroid_y = _require_coordinate_pair(
            row["centroid"], field="centroid", province_id=province_id
        )
        terrain_id = int(row["terrain_id"])
        provinces[province_id] = Province(
            province_id=province_id,
            display_name=province_id,
            owner=Faction.NEUTRAL,
            neighbors=sorted(str(value) for value in row["neighbors"]),
            terrain="water" if is_water else f"earth3_{terrain_id}",
            map_region=EARTH3_MAP_ID,
            x=label_x,
            y=label_y,
            resource_yield=0,
            metadata={
                "source_id": int(row["source_id"]),
                "centroid": [centroid_x, centroid_y],
                "terrain_id": terrain_id,
                "continent_id": int(row["continent_id"]),
                "is_water": is_water,
                "selectable": not is_water,
                "display_anchor_source": "earth3_label",
                "name_is_human_readable": False,
            },
        )

    production = authority.production
    state = CampaignState(
        campaign_name="Gates of CodeX: Earth3 v1 (P1 authority skeleton)",
        selected_faction=Faction.NATO,
        current_faction=Faction.NATO,
        map_id=EARTH3_MAP_ID,
        map_metadata={
            "scenario_id": EARTH3_SCENARIO_ID,
            "scenario_status": "production",
            "scenario_content_phase": "p1_map_authority_only",
            "strategic_map_id": EARTH3_MAP_ID,
            "strategic_map_manifest": CAMPAIGN_MANIFEST_IDENTIFIER,
            "strategic_map_provenance": "earth3_production_authority",
            "manifest_identifier": CAMPAIGN_MANIFEST_IDENTIFIER,
            "manifest_sha256": authority.manifest_sha256,
            "dataset_identifier": CAMPAIGN_DATASET_IDENTIFIER,
            "dataset_sha256": authority.dataset_sha256,
            "embedded_dataset_sha256": authority.embedded_dataset_sha256,
            "geometry_sha256": authority.geometry_sha256,
            "production_asset_version": authority.production_asset_version,
            "production_authority_identifier": PRODUCTION_AUTHORITY_IDENTIFIER,
            "production_authority_schema_version": int(production["schema_version"]),
            "province_count": APPROVED_PROVINCE_COUNT,
            "land_count": APPROVED_LAND_COUNT,
            "water_count": APPROVED_WATER_COUNT,
            "selectable_province_count": APPROVED_SELECTABLE_COUNT,
            "topology_edge_count": authority.topology_edge_count,
            "included_ids_sha256": authority.included_ids_sha256,
            "stable_id_policy": str(production["stable_id_policy"]),
            "water_policy": str(production["water_policy"]["v1"]),
            "adjacency_authority": [
                f"{CAMPAIGN_DATASET_IDENTIFIER}#edges",
                f"{CAMPAIGN_DATASET_IDENTIFIER}#provinces[].neighbors",
            ],
            "approved_operational_assets": [],
            "operational_graph": None,
            "operational_maneuver_enabled": False,
            "operational_objectives": [],
            "coalition_capitals": {},
            "runtime_faction_state": "p1_schema_compatibility_only",
        },
        # P1 compatibility only: use the existing schema default resources and
        # leave research, recruitment, reinforcements, ownership, and forces empty.
        factions={
            Faction.NATO.value: FactionState(
                faction=Faction.NATO,
                is_human_controlled=True,
            ),
        },
        provinces=provinces,
        schema_version=11,
    )
    state.validate()
    return state
