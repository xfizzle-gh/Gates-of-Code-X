from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from typing import Any, TYPE_CHECKING

from .operational_schema import (
    APPROVED_CORRIDOR_BATCH_ID,
    APPROVED_CORRIDOR_COMMENT_ID,
    APPROVED_CORRIDOR_METADATA_KEYS,
    APPROVED_CORRIDOR_ROLLBACK_BATCH_ID,
    APPROVED_CORRIDOR_SOURCE,
    COST_MILLI_UNITY,
    EdgeAuthority,
    EdgeKind,
    OperationalGraph,
    OperationalRouteEdge,
    OperationalRouteNode,
    OperationalRules,
    StrategicSite,
    stable_edge_id,
    stable_node_id,
)

if TYPE_CHECKING:
    from .models import CampaignState


class Earth3OperationalAuthorityError(ValueError):
    """The exact owner-approved Earth3 P3 authority could not be authenticated."""


EARTH3_MAP_ID = "earth3_europe_mediterranean"
AUTHORITY_SCHEMA = "gates-of-codex.earth3-p3-operational-authority"
GRAPH_SCHEMA = "gates-of-codex.operational-graph"
P3_STATE_SCHEMA = "gates-of-codex.earth3-p3-state-authority"
P3_AUTHORITY_METADATA_KEY = "earth3_p3_operational_authority"
P3_MIGRATION_SCHEMA = "gates-of-codex.earth3-p2-to-p3-migration"
P3_MIGRATION_METADATA_KEY = "earth3_p3_migration"
P3_STARTING_FORMATION_IDS = frozenset(
    {
        "sf_deu_berlin",
        "sf_pol_vilnius",
        "sf_rus_donetsk",
        "sf_rus_luhansk",
        "sf_rus_rostov",
        "sf_ukr_kherson",
        "sf_ukr_kyiv",
        "sf_ukr_odesa",
        "sf_ukr_zaporizhzhia",
        "sf_usa_riga",
        "sf_usa_tallinn",
    }
)

P3_AUTHORITY_RELATIVE_PATH = "config/earth3/p3_operational_authority.json"
P3_GRAPH_RELATIVE_PATH = (
    "godot/assets/maps/earth3_europe_mediterranean/p3_authority/"
    "p3_operational_graph.json"
)
P3_PROPOSAL_RELATIVE_PATH = "docs/audits/p3-first-corridor-route-inventory.json"
P3_DATASET_RELATIVE_PATH = (
    "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
)
P3_SITES_RELATIVE_PATH = "src/gates_of_codex/data/earth3_v1/sites.json"

AUTHORITY_RAW_SHA256 = "3b3330eb90351c7751d3a582c3f4c177796e297314c6e8f5497f516926fb200f"
GRAPH_RAW_SHA256 = "c2d6ab30bfd3e2e15404242144831c5dd6ba284cd132e605e2544be8524d72cf"
AUTHORIZED_BASE_COMMIT = "d16e7b145db82180d628bc9c0a636ebbab51db3c"
ACCEPTED_P2_HEAD = "4f2eee80256b9a4c5388c88b2d2e357b883b9e6c"
PROPOSAL_COMMIT = "1c51766f4c099d3307db70cffec815772b314d21"
PROPOSAL_RAW_SHA256 = "353b19cfbd29ea30ea2881758950679892755b9e208cfd863db4510a802b9cf4"
APPROVAL_ISSUE = 141
ALLOWLIST_SHA256 = "08901e371baa34688429afc9a6f06cc6361da13eac6eb9907901b47c9c233965"
DISABLED_CANDIDATE_EDGE_COUNT = 8690
DISABLED_CANDIDATE_IDS_SHA256 = (
    "a7d52fbe2abd1d9b32349ad42e8e00876e3f4727411f58a5e640a3b8a75bbdcf"
)
COMPLETE_CANDIDATE_IDS_SHA256 = (
    "2385c49e1ddbb851f0c2d16bbcd7f112adce57b8b9aeddcab76850ab71794bad"
)
P2_SITES_RAW_SHA256 = "7fbfa2bd7fd40f97f69b5b515bb77cb7145d1299153a2263d79443692f4c2ef3"
P1_DATASET_RAW_SHA256 = "4aadab4b5106bbfa4c2d37e8173c3d1675f35a448cbd7f32a8b871c464ce1b84"
P1_DATASET_SHA256 = "8ae59bd89419a368fe9131ef7c50d94a7f1cafacd1cfae44362ac9b5d9decced"
P1_EMBEDDED_DATASET_SHA256 = (
    "8ae59c33da5094b722b1ffad61d2862cdd4805369d74d6c6298425735982a241"
)
PROPOSAL_LOGICAL_SHA256 = "8ab5127c69faf74f7a02fd554551380350ecc6cadf6ac3f5795f08ccd0ace44a"
DATASET_LOGICAL_SHA256 = "ef9ed2caf73cd18046a38c1ac26f67728dba5786a9b21471d52f69366813fb42"
P2_SITES_LOGICAL_SHA256 = "184a5e88c7f8f8dcf26da8eb3ca47588d166555f590c7ef03a8569120fa52d0e"

_AUTHORITY_KEYS = {
    "schema",
    "schema_version",
    "status",
    "map_id",
    "authorized_base_commit",
    "accepted_p2_head",
    "proposal_commit",
    "proposal_inventory_sha256",
    "approval_issue",
    "approval_comment_id",
    "batch_id",
    "rollback_batch_id",
    "allowlist_sha256",
    "approved_edge_count",
    "approved_node_count",
    "disabled_candidate_edge_count",
    "disabled_candidate_ids_sha256",
    "complete_candidate_ids_sha256",
    "excluded_structural_edge_count",
    "directionality",
    "movement_cost_milli",
    "supply_eligible",
    "graph_relative_path",
    "graph_raw_sha256",
    "p2_sites_raw_sha256",
    "frozen_p1",
    "approved_edges",
}
_AUTHORITY_EDGE_KEYS = {
    "edge_id",
    "endpoint_node_ids",
    "endpoint_province_ids",
    "directionality",
    "movement_cost_milli",
    "supply_eligible",
    "rollback_batch_id",
}
_FROZEN_P1_KEYS = {
    "source_dataset_raw_sha256",
    "source_dataset_sha256",
    "source_embedded_dataset_sha256",
    "source_topology_edge_count",
}
_GRAPH_KEYS = {
    "schema",
    "schema_version",
    "map_id",
    "rules",
    "sites",
    "nodes",
    "edges",
    "metadata",
}
_RULE_KEYS = {
    "ticks_per_strategic_turn",
    "capture_hold_ticks",
    "max_friendly_formations_per_node",
    "capture_mode",
    "interception_mode",
    "formation_is_movement_authority",
    "authored_crossings_traversable_v1",
    "enforce_port_requirements",
    "enforce_blockades",
}
_SITE_KEYS = {
    "site_id",
    "display_name",
    "kind",
    "province_id",
    "pixel",
    "route_node_id",
    "control_weight_milli",
    "capture_threshold_milli",
    "tags",
    "facilities",
    "owner_faction",
    "authority",
    "metadata",
}
_NODE_KEYS = {
    "node_id",
    "display_name",
    "kind",
    "pixel",
    "province_id",
    "site_id",
    "terrain",
    "is_hub",
    "authority",
    "metadata",
}
_GRAPH_EDGE_KEYS = {
    "edge_id",
    "a",
    "b",
    "kind",
    "authority",
    "length_px",
    "base_move_points_milli",
    "movement_cost_milli",
    "requires_port",
    "can_be_blockaded",
    "traversal_enabled",
    "bidirectional",
    "province_ids",
    "legacy_crossing_type",
    "metadata",
}
_GRAPH_METADATA_KEYS = {
    "allowlist_sha256",
    "approval_comment_id",
    "authority_schema_version",
    "batch_id",
    "disabled_candidate_edge_count",
    "disabled_candidate_ids_sha256",
    "proposal_commit",
    "rollback_batch_id",
}
_SITE_METADATA_KEYS = {"source", "supply_hub_intent"}
_NODE_METADATA_KEYS = {"role", "source"}


def authenticated_p3_state_metadata() -> dict[str, Any]:
    """Return the only serialized marker that may activate the P3 graph."""
    return {
        "schema": P3_STATE_SCHEMA,
        "schema_version": 1,
        "authority_raw_sha256": AUTHORITY_RAW_SHA256,
        "graph_raw_sha256": GRAPH_RAW_SHA256,
        "approval_comment_id": APPROVED_CORRIDOR_COMMENT_ID,
        "proposal_commit": PROPOSAL_COMMIT,
        "allowlist_sha256": ALLOWLIST_SHA256,
        "batch_id": APPROVED_CORRIDOR_BATCH_ID,
        "rollback_batch_id": APPROVED_CORRIDOR_ROLLBACK_BATCH_ID,
    }


def authenticated_p3_migration_metadata() -> dict[str, Any]:
    """Return immutable provenance for the one authorized raw-P2 migration."""
    return {
        "schema": P3_MIGRATION_SCHEMA,
        "schema_version": 1,
        "source_bootstrap_id": "earth3_v1_campaign_bootstrap",
        "placement": "exact_p2_province_anchor",
        "formation_count": len(P3_STARTING_FORMATION_IDS),
        "authority_raw_sha256": AUTHORITY_RAW_SHA256,
        "graph_raw_sha256": GRAPH_RAW_SHA256,
    }


def _strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _strict_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_list_sha256(values: list[str]) -> str:
    raw = json.dumps(values, separators=(",", ":")).encode("utf-8")
    return _sha256(raw)


def _canonical_document_sha256(value: dict[str, Any]) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(raw)


def _is_symlink_or_reparse(value: os.stat_result) -> bool:
    if stat.S_ISLNK(value.st_mode):
        return True
    attributes = getattr(value, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse)


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    if os.name == "nt":
        left_index = getattr(left, "st_ino", 0)
        right_index = getattr(right, "st_ino", 0)
        if left_index and right_index:
            return (left.st_dev, left_index) == (right.st_dev, right_index)
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _canonical_repository_root(root: Path) -> Path:
    absolute = Path(os.path.abspath(root))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current = current / component
        try:
            current_stat = os.lstat(current)
        except OSError as exc:
            raise Earth3OperationalAuthorityError(
                f"Earth3 P3 repository root missing: {absolute}"
            ) from exc
        if _is_symlink_or_reparse(current_stat):
            raise Earth3OperationalAuthorityError(
                f"Earth3 P3 repository root contains a symlink or reparse point: {current}"
            )
    try:
        before = os.lstat(absolute)
        resolved = absolute.resolve(strict=True)
        after = os.lstat(resolved)
    except OSError as exc:
        raise Earth3OperationalAuthorityError(
            f"Earth3 P3 repository root is not canonical: {absolute}"
        ) from exc
    if not stat.S_ISDIR(before.st_mode) or not stat.S_ISDIR(after.st_mode):
        raise Earth3OperationalAuthorityError(
            f"Earth3 P3 repository root is not a directory: {absolute}"
        )
    if _is_symlink_or_reparse(before) or not _same_identity(before, after):
        raise Earth3OperationalAuthorityError(
            f"Earth3 P3 repository root is path-substituted: {absolute}"
        )
    return resolved


def _fixed_path_component_stats(
    root: Path, relative: Path, *, label: str
) -> list[tuple[Path, os.stat_result]]:
    captured: list[tuple[Path, os.stat_result]] = []
    current = root
    for index, component in enumerate(relative.parts):
        current = current / component
        try:
            current_stat = os.lstat(current)
        except OSError as exc:
            location = "file" if index == len(relative.parts) - 1 else "intermediate component"
            raise Earth3OperationalAuthorityError(
                f"{label} missing {location}: {current}"
            ) from exc
        if _is_symlink_or_reparse(current_stat):
            location = "file" if index == len(relative.parts) - 1 else "intermediate component"
            raise Earth3OperationalAuthorityError(
                f"{label} {location} is a symlink, junction, or reparse point: {current}"
            )
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(current_stat.st_mode):
            raise Earth3OperationalAuthorityError(
                f"{label} intermediate component is not a directory: {current}"
            )
        captured.append((current, current_stat))
    return captured


def _capture_fixed_file(root: Path, relative_path: str, *, label: str) -> bytes:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise Earth3OperationalAuthorityError(f"{label} path is not fixed")
    path = root.joinpath(*relative.parts)
    components_before = _fixed_path_component_stats(root, relative, label=label)
    before = components_before[-1][1]
    if not stat.S_ISREG(before.st_mode):
        raise Earth3OperationalAuthorityError(f"{label} is not a regular fixed file")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        resolved_stat = os.lstat(resolved)
    except (OSError, ValueError) as exc:
        raise Earth3OperationalAuthorityError(f"{label} escapes its fixed root") from exc
    if _is_symlink_or_reparse(resolved_stat) or not _same_identity(before, resolved_stat):
        raise Earth3OperationalAuthorityError(f"{label} is path-substituted")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or not _same_identity(before, opened):
                raise Earth3OperationalAuthorityError(f"{label} changed while opening")
            raw = stream.read()
    except Earth3OperationalAuthorityError:
        raise
    except OSError as exc:
        raise Earth3OperationalAuthorityError(f"{label} cannot be read") from exc

    try:
        components_after = _fixed_path_component_stats(root, relative, label=label)
        final = components_after[-1][1]
        final_resolved = path.resolve(strict=True)
        final_resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise Earth3OperationalAuthorityError(f"{label} changed while reading") from exc
    if any(
        before_path != after_path or not _same_identity(before_stat, after_stat)
        for (before_path, before_stat), (after_path, after_stat) in zip(
            components_before, components_after
        )
    ) or (
        not _same_identity(before, final)
        or final.st_size != before.st_size
        or final.st_mtime_ns != before.st_mtime_ns
        or final_resolved != resolved
    ):
        raise Earth3OperationalAuthorityError(f"{label} changed while reading")
    return raw


def _strict_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise Earth3OperationalAuthorityError(
                    f"{label} contains duplicate JSON key: {key}"
                )
            value[key] = item
        return value

    def reject_constant(value: str) -> None:
        raise Earth3OperationalAuthorityError(
            f"{label} contains non-finite JSON number: {value}"
        )

    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs_hook,
            parse_constant=reject_constant,
        )
    except Earth3OperationalAuthorityError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Earth3OperationalAuthorityError(
            f"{label} is not strict UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise Earth3OperationalAuthorityError(f"{label} must be a JSON object")
    return parsed


def _require_exact_keys(value: Any, expected: set[str], *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise Earth3OperationalAuthorityError(f"{label} has missing or unknown fields")
    return value


def _require_list(value: Any, *, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise Earth3OperationalAuthorityError(f"{label} must be a list")
    return value


def _validate_authority(authority: dict[str, Any]) -> list[dict[str, Any]]:
    _require_exact_keys(authority, _AUTHORITY_KEYS, label="P3 authority")
    expected_scalars = {
        "schema": AUTHORITY_SCHEMA,
        "schema_version": 1,
        "status": "owner_approved_runtime_authority",
        "map_id": EARTH3_MAP_ID,
        "authorized_base_commit": AUTHORIZED_BASE_COMMIT,
        "accepted_p2_head": ACCEPTED_P2_HEAD,
        "proposal_commit": PROPOSAL_COMMIT,
        "proposal_inventory_sha256": PROPOSAL_RAW_SHA256,
        "approval_issue": APPROVAL_ISSUE,
        "approval_comment_id": APPROVED_CORRIDOR_COMMENT_ID,
        "batch_id": APPROVED_CORRIDOR_BATCH_ID,
        "rollback_batch_id": APPROVED_CORRIDOR_ROLLBACK_BATCH_ID,
        "allowlist_sha256": ALLOWLIST_SHA256,
        "approved_edge_count": 65,
        "approved_node_count": 64,
        "disabled_candidate_edge_count": DISABLED_CANDIDATE_EDGE_COUNT,
        "disabled_candidate_ids_sha256": DISABLED_CANDIDATE_IDS_SHA256,
        "complete_candidate_ids_sha256": COMPLETE_CANDIDATE_IDS_SHA256,
        "excluded_structural_edge_count": 1494,
        "directionality": "bidirectional",
        "movement_cost_milli": COST_MILLI_UNITY,
        "supply_eligible": True,
        "graph_relative_path": P3_GRAPH_RELATIVE_PATH,
        "graph_raw_sha256": GRAPH_RAW_SHA256,
        "p2_sites_raw_sha256": P2_SITES_RAW_SHA256,
    }
    if any(authority.get(key) != value for key, value in expected_scalars.items()):
        raise Earth3OperationalAuthorityError("P3 authority identity or policy mismatch")
    for key in (
        "schema_version",
        "approval_issue",
        "approval_comment_id",
        "approved_edge_count",
        "approved_node_count",
        "disabled_candidate_edge_count",
        "excluded_structural_edge_count",
        "movement_cost_milli",
    ):
        if not _strict_int(authority[key]):
            raise Earth3OperationalAuthorityError(f"P3 authority {key} must be a strict int")
    if authority["supply_eligible"] is not True:
        raise Earth3OperationalAuthorityError("P3 authority supply policy mismatch")

    frozen = _require_exact_keys(authority["frozen_p1"], _FROZEN_P1_KEYS, label="P3 frozen P1")
    if frozen != {
        "source_dataset_raw_sha256": P1_DATASET_RAW_SHA256,
        "source_dataset_sha256": P1_DATASET_SHA256,
        "source_embedded_dataset_sha256": P1_EMBEDDED_DATASET_SHA256,
        "source_topology_edge_count": 10249,
    } or not _strict_int(frozen["source_topology_edge_count"]):
        raise Earth3OperationalAuthorityError("P3 authority frozen P1 identity mismatch")

    edges = _require_list(authority["approved_edges"], label="P3 authority approved_edges")
    if len(edges) != 65:
        raise Earth3OperationalAuthorityError("P3 authority approved edge count mismatch")
    edge_ids: list[str] = []
    node_ids: set[str] = set()
    for index, value in enumerate(edges):
        edge = _require_exact_keys(value, _AUTHORITY_EDGE_KEYS, label=f"P3 authority edge {index}")
        node_pair = _require_list(
            edge["endpoint_node_ids"], label=f"P3 authority edge {index} nodes"
        )
        province_pair = _require_list(
            edge["endpoint_province_ids"], label=f"P3 authority edge {index} provinces"
        )
        if (
            len(node_pair) != 2
            or len(province_pair) != 2
            or any(not isinstance(item, str) or not item for item in node_pair + province_pair)
        ):
            raise Earth3OperationalAuthorityError("P3 authority edge endpoints are malformed")
        expected_nodes = [stable_node_id(pid) for pid in province_pair]
        edge_id = edge.get("edge_id")
        if (
            not isinstance(edge_id, str)
            or node_pair != expected_nodes
            or node_pair != sorted(node_pair)
            or edge_id != stable_edge_id(EdgeKind.CORRIDOR.value, node_pair[0], node_pair[1])
            or edge.get("directionality") != "bidirectional"
            or not _strict_int(edge.get("movement_cost_milli"))
            or edge.get("movement_cost_milli") != COST_MILLI_UNITY
            or edge.get("supply_eligible") is not True
            or edge.get("rollback_batch_id") != APPROVED_CORRIDOR_ROLLBACK_BATCH_ID
        ):
            raise Earth3OperationalAuthorityError("P3 authority approved edge policy mismatch")
        edge_ids.append(edge_id)
        node_ids.update(node_pair)
    if (
        edge_ids != sorted(edge_ids)
        or len(set(edge_ids)) != 65
        or len(node_ids) != 64
        or _canonical_list_sha256(edge_ids) != ALLOWLIST_SHA256
    ):
        raise Earth3OperationalAuthorityError("P3 authority allowlist mismatch")
    return edges


def _projection_pixel(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
    ):
        raise Earth3OperationalAuthorityError(
            "P3 frozen projection input contains an invalid centroid"
        )
    return int(math.floor(float(value) + 0.5))


def _expected_graph_projection(
    authority: dict[str, Any],
    proposal: dict[str, Any],
    dataset: dict[str, Any],
    sites_document: dict[str, Any],
) -> dict[str, Any]:
    expected_inputs = (
        (proposal, PROPOSAL_LOGICAL_SHA256, "proposal"),
        (dataset, DATASET_LOGICAL_SHA256, "dataset"),
        (sites_document, P2_SITES_LOGICAL_SHA256, "P2 sites"),
    )
    for document, expected_sha256, label in expected_inputs:
        if (
            not isinstance(document, dict)
            or _canonical_document_sha256(document) != expected_sha256
        ):
            raise Earth3OperationalAuthorityError(
                f"P3 frozen projection input mismatch: {label}"
            )

    try:
        province_by_id = {
            row["id"]: row for row in dataset["provinces"]
        }
        site_rows = sorted(sites_document["sites"], key=lambda row: row["site_id"])
        site_by_province = {row["province_id"]: row for row in site_rows}
        pixels: dict[str, list[int]] = {}
        nodes: list[dict[str, Any]] = []
        for approved_node in proposal["proposed_nodes"]:
            province_id = approved_node["province_id"]
            centroid = province_by_id[province_id]["centroid"]
            pixel = [_projection_pixel(centroid[0]), _projection_pixel(centroid[1])]
            pixels[province_id] = pixel
            p2_site = site_by_province.get(province_id)
            nodes.append(
                {
                    "node_id": approved_node["node_id"],
                    "display_name": f"{province_id} operational anchor",
                    "kind": "anchor",
                    "pixel": pixel,
                    "province_id": province_id,
                    "site_id": None,
                    "terrain": "unknown",
                    "is_hub": bool(p2_site and p2_site["supply_hub_intent"]),
                    "authority": "authored",
                    "metadata": {
                        "role": "earth3_p3_province_anchor",
                        "source": "frozen_earth3_centroid",
                    },
                }
            )

        sites: list[dict[str, Any]] = []
        for site in site_rows:
            province_id = site["province_id"]
            sites.append(
                {
                    "site_id": site["site_id"],
                    "display_name": site["display_name"],
                    "kind": site["kind"],
                    "province_id": province_id,
                    "pixel": pixels[province_id],
                    "route_node_id": stable_node_id(province_id),
                    "control_weight_milli": COST_MILLI_UNITY,
                    "capture_threshold_milli": COST_MILLI_UNITY,
                    "tags": ["earth3_p2_site_intent"],
                    "facilities": ["supply_hub"] if site["supply_hub_intent"] else [],
                    "owner_faction": site["owner_actor_id"],
                    "authority": "authored",
                    "metadata": {
                        "source": "frozen_earth3_p2_site_intent",
                        "supply_hub_intent": site["supply_hub_intent"],
                    },
                }
            )

        edges: list[dict[str, Any]] = []
        for edge in authority["approved_edges"]:
            left_pid, right_pid = edge["endpoint_province_ids"]
            left_px, right_px = pixels[left_pid], pixels[right_pid]
            length_px = max(
                1,
                int(
                    math.floor(
                        math.hypot(
                            right_px[0] - left_px[0], right_px[1] - left_px[1]
                        )
                        + 0.5
                    )
                ),
            )
            edges.append(
                {
                    "edge_id": edge["edge_id"],
                    "a": edge["endpoint_node_ids"][0],
                    "b": edge["endpoint_node_ids"][1],
                    "kind": "corridor",
                    "authority": "approved",
                    "length_px": length_px,
                    "base_move_points_milli": COST_MILLI_UNITY,
                    "movement_cost_milli": edge["movement_cost_milli"],
                    "requires_port": False,
                    "can_be_blockaded": False,
                    "traversal_enabled": True,
                    "bidirectional": edge["directionality"] == "bidirectional",
                    "province_ids": edge["endpoint_province_ids"],
                    "legacy_crossing_type": None,
                    "metadata": {
                        "approval_comment_id": APPROVED_CORRIDOR_COMMENT_ID,
                        "batch_id": authority["batch_id"],
                        "rollback_batch_id": edge["rollback_batch_id"],
                        "source": APPROVED_CORRIDOR_SOURCE,
                        "supply_capable": edge["supply_eligible"],
                    },
                }
            )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise Earth3OperationalAuthorityError(
            f"P3 frozen projection input is malformed: {exc}"
        ) from exc

    return {
        "schema": GRAPH_SCHEMA,
        "schema_version": 2,
        "map_id": EARTH3_MAP_ID,
        "rules": {
            "ticks_per_strategic_turn": 10,
            "capture_hold_ticks": 2,
            "max_friendly_formations_per_node": 3,
            "capture_mode": "control_site_node_only",
            "interception_mode": "swept_movement",
            "formation_is_movement_authority": True,
            "authored_crossings_traversable_v1": True,
            "enforce_port_requirements": False,
            "enforce_blockades": False,
        },
        "sites": sites,
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "allowlist_sha256": authority["allowlist_sha256"],
            "approval_comment_id": APPROVED_CORRIDOR_COMMENT_ID,
            "authority_schema_version": 1,
            "batch_id": authority["batch_id"],
            "disabled_candidate_edge_count": authority[
                "disabled_candidate_edge_count"
            ],
            "disabled_candidate_ids_sha256": authority[
                "disabled_candidate_ids_sha256"
            ],
            "proposal_commit": authority["proposal_commit"],
            "rollback_batch_id": authority["rollback_batch_id"],
        },
    }


def _validate_graph(authority: dict[str, Any], graph: dict[str, Any]) -> None:
    _require_exact_keys(graph, _GRAPH_KEYS, label="P3 graph")
    if (
        graph.get("schema") != GRAPH_SCHEMA
        or not _strict_int(graph.get("schema_version"))
        or graph.get("schema_version") != 2
        or graph.get("map_id") != EARTH3_MAP_ID
    ):
        raise Earth3OperationalAuthorityError("P3 graph schema, version, or map mismatch")
    rules = _require_exact_keys(graph["rules"], _RULE_KEYS, label="P3 graph rules")
    expected_rules = {
        "ticks_per_strategic_turn": 10,
        "capture_hold_ticks": 2,
        "max_friendly_formations_per_node": 3,
        "capture_mode": "control_site_node_only",
        "interception_mode": "swept_movement",
        "formation_is_movement_authority": True,
        "authored_crossings_traversable_v1": True,
        "enforce_port_requirements": False,
        "enforce_blockades": False,
    }
    if rules != expected_rules:
        raise Earth3OperationalAuthorityError("P3 graph rules mismatch")
    for key in (
        "ticks_per_strategic_turn",
        "capture_hold_ticks",
        "max_friendly_formations_per_node",
    ):
        if not _strict_int(rules[key]):
            raise Earth3OperationalAuthorityError(f"P3 graph rule {key} must be a strict int")
    for key in (
        "formation_is_movement_authority",
        "authored_crossings_traversable_v1",
        "enforce_port_requirements",
        "enforce_blockades",
    ):
        if not _strict_bool(rules[key]):
            raise Earth3OperationalAuthorityError(f"P3 graph rule {key} must be a strict bool")

    graph_metadata = _require_exact_keys(
        graph["metadata"], _GRAPH_METADATA_KEYS, label="P3 graph metadata"
    )
    expected_metadata = {
        "allowlist_sha256": ALLOWLIST_SHA256,
        "approval_comment_id": APPROVED_CORRIDOR_COMMENT_ID,
        "authority_schema_version": 1,
        "batch_id": APPROVED_CORRIDOR_BATCH_ID,
        "disabled_candidate_edge_count": DISABLED_CANDIDATE_EDGE_COUNT,
        "disabled_candidate_ids_sha256": DISABLED_CANDIDATE_IDS_SHA256,
        "proposal_commit": PROPOSAL_COMMIT,
        "rollback_batch_id": APPROVED_CORRIDOR_ROLLBACK_BATCH_ID,
    }
    if graph_metadata != expected_metadata:
        raise Earth3OperationalAuthorityError("P3 graph authority metadata mismatch")
    for key in (
        "approval_comment_id",
        "authority_schema_version",
        "disabled_candidate_edge_count",
    ):
        if not _strict_int(graph_metadata[key]):
            raise Earth3OperationalAuthorityError(f"P3 graph metadata {key} must be a strict int")

    sites = _require_list(graph["sites"], label="P3 graph sites")
    nodes = _require_list(graph["nodes"], label="P3 graph nodes")
    edges = _require_list(graph["edges"], label="P3 graph edges")
    if len(sites) != 7 or len(nodes) != 64 or len(edges) != 65:
        raise Earth3OperationalAuthorityError("P3 graph count mismatch")

    node_objects: list[OperationalRouteNode] = []
    node_ids: list[str] = []
    node_provinces: dict[str, str] = {}
    for index, value in enumerate(nodes):
        node = _require_exact_keys(value, _NODE_KEYS, label=f"P3 graph node {index}")
        metadata = _require_exact_keys(
            node["metadata"], _NODE_METADATA_KEYS, label=f"P3 graph node {index} metadata"
        )
        pixel = _require_list(node["pixel"], label=f"P3 graph node {index} pixel")
        node_id = node.get("node_id")
        province_id = node.get("province_id")
        if (
            not isinstance(node_id, str)
            or not isinstance(province_id, str)
            or node_id != stable_node_id(province_id)
            or node.get("kind") != "anchor"
            or len(pixel) != 2
            or any(not _strict_int(value) or value < 0 for value in pixel)
            or node.get("site_id") is not None
            or node.get("terrain") != "unknown"
            or not _strict_bool(node.get("is_hub"))
            or node.get("authority") != EdgeAuthority.AUTHORED.value
            or metadata
            != {"role": "earth3_p3_province_anchor", "source": "frozen_earth3_centroid"}
        ):
            raise Earth3OperationalAuthorityError("P3 graph node contract mismatch")
        node_ids.append(node_id)
        node_provinces[node_id] = province_id
        node_objects.append(OperationalRouteNode(**node))
    if node_ids != sorted(node_ids) or len(set(node_ids)) != 64:
        raise Earth3OperationalAuthorityError("P3 graph node ordering or identity mismatch")

    authority_edges = authority["approved_edges"]
    authority_edge_ids = [edge["edge_id"] for edge in authority_edges]
    edge_objects: list[OperationalRouteEdge] = []
    graph_edge_ids: list[str] = []
    for index, (value, approved) in enumerate(zip(edges, authority_edges)):
        edge = _require_exact_keys(value, _GRAPH_EDGE_KEYS, label=f"P3 graph edge {index}")
        metadata = _require_exact_keys(
            edge["metadata"],
            set(APPROVED_CORRIDOR_METADATA_KEYS),
            label=f"P3 graph edge {index} metadata",
        )
        province_ids = _require_list(
            edge["province_ids"], label=f"P3 graph edge {index} province_ids"
        )
        expected_metadata = {
            "approval_comment_id": APPROVED_CORRIDOR_COMMENT_ID,
            "batch_id": APPROVED_CORRIDOR_BATCH_ID,
            "rollback_batch_id": APPROVED_CORRIDOR_ROLLBACK_BATCH_ID,
            "source": APPROVED_CORRIDOR_SOURCE,
            "supply_capable": True,
        }
        if (
            edge.get("edge_id") != approved["edge_id"]
            or [edge.get("a"), edge.get("b")] != approved["endpoint_node_ids"]
            or province_ids != approved["endpoint_province_ids"]
            or edge.get("kind") != EdgeKind.CORRIDOR.value
            or edge.get("authority") != EdgeAuthority.APPROVED.value
            or not _strict_int(edge.get("length_px"))
            or edge.get("length_px", 0) < 1
            or not _strict_int(edge.get("base_move_points_milli"))
            or edge.get("base_move_points_milli") != COST_MILLI_UNITY
            or not _strict_int(edge.get("movement_cost_milli"))
            or edge.get("movement_cost_milli") != COST_MILLI_UNITY
            or edge.get("requires_port") is not False
            or edge.get("can_be_blockaded") is not False
            or edge.get("traversal_enabled") is not True
            or edge.get("bidirectional") is not True
            or edge.get("legacy_crossing_type") is not None
            or metadata != expected_metadata
        ):
            raise Earth3OperationalAuthorityError("P3 graph edge does not match authority")
        graph_edge_ids.append(edge["edge_id"])
        edge_objects.append(OperationalRouteEdge(**edge))
    if graph_edge_ids != authority_edge_ids:
        raise Earth3OperationalAuthorityError("P3 graph allowlist ordering mismatch")
    if set(node_ids) != {
        node_id for approved in authority_edges for node_id in approved["endpoint_node_ids"]
    }:
        raise Earth3OperationalAuthorityError("P3 graph node set does not match authority")

    site_objects: list[StrategicSite] = []
    site_ids: list[str] = []
    for index, value in enumerate(sites):
        site = _require_exact_keys(value, _SITE_KEYS, label=f"P3 graph site {index}")
        metadata = _require_exact_keys(
            site["metadata"], _SITE_METADATA_KEYS, label=f"P3 graph site {index} metadata"
        )
        pixel = _require_list(site["pixel"], label=f"P3 graph site {index} pixel")
        tags = _require_list(site["tags"], label=f"P3 graph site {index} tags")
        facilities = _require_list(site["facilities"], label=f"P3 graph site {index} facilities")
        route_node_id = site.get("route_node_id")
        if (
            not isinstance(site.get("site_id"), str)
            or not isinstance(site.get("display_name"), str)
            or not isinstance(site.get("province_id"), str)
            or route_node_id not in node_provinces
            or node_provinces[route_node_id] != site.get("province_id")
            or len(pixel) != 2
            or any(not _strict_int(value) or value < 0 for value in pixel)
            or pixel != next(node["pixel"] for node in nodes if node["node_id"] == route_node_id)
            or not _strict_int(site.get("control_weight_milli"))
            or site.get("control_weight_milli") != COST_MILLI_UNITY
            or not _strict_int(site.get("capture_threshold_milli"))
            or site.get("capture_threshold_milli") != COST_MILLI_UNITY
            or tags != ["earth3_p2_site_intent"]
            or any(not isinstance(value, str) for value in facilities)
            or facilities not in ([], ["supply_hub"])
            or not isinstance(site.get("owner_faction"), str)
            or site.get("authority") != EdgeAuthority.AUTHORED.value
            or metadata.get("source") != "frozen_earth3_p2_site_intent"
            or not _strict_bool(metadata.get("supply_hub_intent"))
            or (facilities == ["supply_hub"]) is not metadata["supply_hub_intent"]
        ):
            raise Earth3OperationalAuthorityError("P3 graph site contract mismatch")
        site_ids.append(site["site_id"])
        site_objects.append(StrategicSite(**site))
    if site_ids != sorted(site_ids) or len(set(site_ids)) != 7:
        raise Earth3OperationalAuthorityError("P3 graph site ordering or identity mismatch")

    runtime_graph = OperationalGraph(
        map_id=graph["map_id"],
        schema=graph["schema"],
        schema_version=graph["schema_version"],
        rules=OperationalRules(**rules),
        sites=site_objects,
        nodes=node_objects,
        edges=edge_objects,
        metadata=dict(graph_metadata),
    )
    try:
        runtime_graph._validate_structure(province_ids=set(node_provinces.values()))
    except (TypeError, ValueError) as exc:
        raise Earth3OperationalAuthorityError(f"P3 graph schema validation failed: {exc}") from exc


def validate_p3_documents(
    authority: dict[str, Any],
    graph: dict[str, Any],
    *,
    proposal: dict[str, Any],
    dataset: dict[str, Any],
    sites_document: dict[str, Any],
) -> None:
    """Validate closed P3 documents independently of their raw-byte authentication."""
    if not isinstance(authority, dict) or not isinstance(graph, dict):
        raise Earth3OperationalAuthorityError("P3 authority and graph must be objects")
    _validate_authority(authority)
    expected_graph = _expected_graph_projection(
        authority, proposal, dataset, sites_document
    )
    if graph != expected_graph:
        raise Earth3OperationalAuthorityError(
            "P3 graph does not match the exact frozen-input authority projection"
        )
    _validate_graph(authority, graph)


def load_authenticated_p3_graph(
    *, repository_root: Path | None = None
) -> dict[str, Any]:
    """Load only the two fixed P3 artifacts after exact-byte authentication."""
    root = _canonical_repository_root(
        Path(__file__).resolve().parents[2] if repository_root is None else repository_root
    )
    authority_raw = _capture_fixed_file(
        root, P3_AUTHORITY_RELATIVE_PATH, label="Earth3 P3 authority"
    )
    graph_raw = _capture_fixed_file(root, P3_GRAPH_RELATIVE_PATH, label="Earth3 P3 graph")
    proposal_raw = _capture_fixed_file(
        root, P3_PROPOSAL_RELATIVE_PATH, label="Earth3 P3 proposal"
    )
    dataset_raw = _capture_fixed_file(
        root, P3_DATASET_RELATIVE_PATH, label="Earth3 P1 dataset"
    )
    sites_raw = _capture_fixed_file(
        root, P3_SITES_RELATIVE_PATH, label="Earth3 P2 sites"
    )
    if _sha256(authority_raw) != AUTHORITY_RAW_SHA256:
        raise Earth3OperationalAuthorityError("Earth3 P3 authority SHA-256 mismatch")
    if _sha256(graph_raw) != GRAPH_RAW_SHA256:
        raise Earth3OperationalAuthorityError("Earth3 P3 graph SHA-256 mismatch")
    if _sha256(proposal_raw) != PROPOSAL_RAW_SHA256:
        raise Earth3OperationalAuthorityError("Earth3 P3 proposal SHA-256 mismatch")
    if _sha256(dataset_raw) != P1_DATASET_RAW_SHA256:
        raise Earth3OperationalAuthorityError("Earth3 P1 dataset SHA-256 mismatch")
    if _sha256(sites_raw) != P2_SITES_RAW_SHA256:
        raise Earth3OperationalAuthorityError("Earth3 P2 sites SHA-256 mismatch")
    authority = _strict_json_object(authority_raw, label="Earth3 P3 authority")
    graph = _strict_json_object(graph_raw, label="Earth3 P3 graph")
    proposal = _strict_json_object(proposal_raw, label="Earth3 P3 proposal")
    dataset = _strict_json_object(dataset_raw, label="Earth3 P1 dataset")
    sites_document = _strict_json_object(sites_raw, label="Earth3 P2 sites")
    validate_p3_documents(
        authority,
        graph,
        proposal=proposal,
        dataset=dataset,
        sites_document=sites_document,
    )
    return graph


def load_authenticated_p3_graph_for_state(
    state: CampaignState,
) -> dict[str, Any] | None:
    """Return the graph only for an exactly authenticated serialized P3 marker."""
    if P3_AUTHORITY_METADATA_KEY not in state.map_metadata:
        return None
    marker = state.map_metadata[P3_AUTHORITY_METADATA_KEY]
    expected = authenticated_p3_state_metadata()
    if (
        not isinstance(marker, dict)
        or set(marker) != set(expected)
        or marker != expected
        or not _strict_int(marker.get("schema_version"))
        or not _strict_int(marker.get("approval_comment_id"))
    ):
        raise Earth3OperationalAuthorityError("Earth3 P3 state authority marker mismatch")
    configured = state.map_metadata.get("operational_graph")
    if configured != P3_GRAPH_RELATIVE_PATH:
        raise Earth3OperationalAuthorityError(
            "Earth3 state must use the fixed P3 graph path"
        )
    return load_authenticated_p3_graph()


def validate_earth3_p3_campaign_extension(state: CampaignState) -> None:
    """Validate mutable P3 state against separately authenticated P2/P3 authority.

    This validator never repairs state.  The graph is authenticated inside this
    function so callers cannot supply a graph or allowlist as a trust context.
    """
    from .earth3_bootstrap import (
        is_earth3_p2_campaign,
        validate_earth3_bootstrap_provenance,
    )
    from .operational_position import _graph_indexes, _position_is_valid

    if state.map_id != EARTH3_MAP_ID or not is_earth3_p2_campaign(state):
        raise Earth3OperationalAuthorityError(
            "Earth3 P3 state must extend the exact Earth3 P2 campaign"
        )
    validate_earth3_bootstrap_provenance(state)
    if state.map_metadata.get("operational_maneuver_enabled") is not True:
        raise Earth3OperationalAuthorityError(
            "Earth3 P3 operational maneuver must be explicitly enabled"
        )
    if state.map_metadata.get(P3_MIGRATION_METADATA_KEY) != (
        authenticated_p3_migration_metadata()
    ):
        raise Earth3OperationalAuthorityError(
            "Earth3 P3 migration provenance mismatch"
        )

    graph = load_authenticated_p3_graph_for_state(state)
    if graph is None:  # Marker presence is part of the closed P3 extension.
        raise Earth3OperationalAuthorityError("Earth3 P3 state authority marker missing")
    node_ids, edge_ids, edges_by_id, nodes_by_id = _graph_indexes(graph)
    if set(state.strategic_formations) != P3_STARTING_FORMATION_IDS:
        raise Earth3OperationalAuthorityError(
            "Earth3 P3 position set must contain the exact eleven P2 formations"
        )
    for formation_id, force in sorted(state.strategic_formations.items()):
        if not _position_is_valid(
            force.position,
            province_id=force.province_id,
            node_ids=node_ids,
            edge_ids=edge_ids,
            edges_by_id=edges_by_id,
            nodes_by_id=nodes_by_id,
        ):
            raise Earth3OperationalAuthorityError(
                f"Earth3 P3 formation {formation_id} position is missing or invalid"
            )


def migrate_earth3_p2_to_p3(state: CampaignState) -> CampaignState:
    """Return an atomic deterministic P3 replacement for an exact raw P2 state.

    Raw authority and source state are validated first.  P3 authority is then
    completely authenticated and all placements are planned before the source
    is copied.  Any later failure affects only the unpublished replacement.
    """
    from .earth3_bootstrap import (
        is_earth3_p2_campaign,
        load_earth3_bootstrap,
        validate_earth3_bootstrap_campaign_state,
    )
    from .operational_position import OPERATIONAL_POSITION_SCHEMA_VERSION
    from .operational_schema import FormationOperationalPosition, PositionMode

    # Avoid importing or constructing P2 content for unrelated campaigns.
    if not is_earth3_p2_campaign(state):
        return state
    if P3_AUTHORITY_METADATA_KEY in state.map_metadata:
        validate_earth3_p3_campaign_extension(state)
        return state

    # Full raw-P2 state validation is read-only and preserves the original P2
    # prohibition against graph or maneuver enablement.
    validate_earth3_bootstrap_campaign_state(state)
    state.validate()

    # Authentication completes before deepcopy or any replacement mutation.
    graph = load_authenticated_p3_graph()
    nodes_by_id = {str(node["node_id"]): node for node in graph["nodes"]}
    bundle = load_earth3_bootstrap()
    formation_rows = bundle.documents["formations.json"]["formations"]
    expected_provinces = {
        str(row["formation_id"]): str(row["province_id"])
        for row in formation_rows
    }
    if set(expected_provinces) != set(state.strategic_formations):
        raise Earth3OperationalAuthorityError(
            "Earth3 P2 formation identity set does not match migration authority"
        )

    planned_node_ids: dict[str, str] = {}
    for formation_id, province_id in sorted(expected_provinces.items()):
        force = state.strategic_formations[formation_id]
        if force.province_id != province_id:
            raise Earth3OperationalAuthorityError(
                f"Earth3 P2 formation {formation_id} province does not match migration authority"
            )
        node_id = stable_node_id(province_id, "anchor")
        node = nodes_by_id.get(node_id)
        if node is None or str(node.get("province_id")) != province_id:
            raise Earth3OperationalAuthorityError(
                f"Earth3 P3 graph lacks the authorized anchor for {formation_id}"
            )
        planned_node_ids[formation_id] = node_id

    replacement = copy.deepcopy(state)
    replacement.map_metadata[P3_AUTHORITY_METADATA_KEY] = (
        authenticated_p3_state_metadata()
    )
    replacement.map_metadata[P3_MIGRATION_METADATA_KEY] = (
        authenticated_p3_migration_metadata()
    )
    replacement.map_metadata["operational_graph"] = P3_GRAPH_RELATIVE_PATH
    replacement.map_metadata["operational_maneuver_enabled"] = True
    replacement.schema_version = max(
        replacement.schema_version, OPERATIONAL_POSITION_SCHEMA_VERSION
    )
    for formation_id, node_id in sorted(planned_node_ids.items()):
        replacement.strategic_formations[formation_id].position = (
            FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value,
                node_id=node_id,
                edge_id=None,
                progress_milli=0,
                facing_node_id=None,
            )
        )

    validate_earth3_p3_campaign_extension(replacement)
    replacement.validate()
    return replacement
