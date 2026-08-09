#!/usr/bin/env python3
"""Build the owner-approved Earth3 P3 graph from explicit route authority.

This tool never chooses routes from polygon geometry. Geometry is consulted only
after the ordered, explicit authority records have matched the approved proposal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any


AUTHORITY_SCHEMA = "gates-of-codex.earth3-p3-operational-authority"
GRAPH_SCHEMA = "gates-of-codex.operational-graph"
MAP_ID = "earth3_europe_mediterranean"
AUTHORIZED_BASE_COMMIT = "d16e7b145db82180d628bc9c0a636ebbab51db3c"
ACCEPTED_P2_HEAD = "4f2eee80256b9a4c5388c88b2d2e357b883b9e6c"
PROPOSAL_COMMIT = "1c51766f4c099d3307db70cffec815772b314d21"
PROPOSAL_RAW_SHA256 = "353b19cfbd29ea30ea2881758950679892755b9e208cfd863db4510a802b9cf4"
APPROVAL_ISSUE = 141
APPROVAL_COMMENT_ID = 5234226059
GRAPH_RELATIVE_PATH = (
    "godot/assets/maps/earth3_europe_mediterranean/p3_authority/"
    "p3_operational_graph.json"
)
AUTHORITY_RELATIVE_PATH = "config/earth3/p3_operational_authority.json"
PROPOSAL_RELATIVE_PATH = "docs/audits/p3-first-corridor-route-inventory.json"
DATASET_RELATIVE_PATH = (
    "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
)
SITES_RELATIVE_PATH = "src/gates_of_codex/data/earth3_v1/sites.json"
P2_SITES_RAW_SHA256 = "7fbfa2bd7fd40f97f69b5b515bb77cb7145d1299153a2263d79443692f4c2ef3"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EDGE_KEYS = (
    "edge_id",
    "endpoint_node_ids",
    "endpoint_province_ids",
    "directionality",
    "movement_cost_milli",
    "supply_eligible",
    "rollback_batch_id",
)
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


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_list_sha256(values: list[str]) -> str:
    encoded = json.dumps(values, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


def _edge_contract(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {key: edge[key] for key in _EDGE_KEYS}
        for edge in proposal["proposed_edges"]
    ]


def authority_document_from_proposal(
    proposal: dict[str, Any], *, proposal_raw_sha256: str, graph_raw_sha256: str
) -> dict[str, Any]:
    """Project the approved proposal into the separate runtime authority record."""
    return {
        "schema": AUTHORITY_SCHEMA,
        "schema_version": 1,
        "status": "owner_approved_runtime_authority",
        "map_id": MAP_ID,
        "authorized_base_commit": AUTHORIZED_BASE_COMMIT,
        "accepted_p2_head": ACCEPTED_P2_HEAD,
        "proposal_commit": PROPOSAL_COMMIT,
        "proposal_inventory_sha256": proposal_raw_sha256,
        "approval_issue": APPROVAL_ISSUE,
        "approval_comment_id": APPROVAL_COMMENT_ID,
        "batch_id": proposal["batch_id"],
        "rollback_batch_id": proposal["rollback_batch_id"],
        "allowlist_sha256": proposal["allowlist_sha256"],
        "approved_edge_count": proposal["enabled_proposal_edge_count"],
        "approved_node_count": len(proposal["proposed_nodes"]),
        "disabled_candidate_edge_count": proposal["disabled_candidate_edge_count"],
        "disabled_candidate_ids_sha256": proposal["disabled_candidate_ids_sha256"],
        "complete_candidate_ids_sha256": proposal["complete_candidate_ids_sha256"],
        "excluded_structural_edge_count": proposal[
            "non_land_or_nonselectable_structural_edge_count"
        ],
        "directionality": "bidirectional",
        "movement_cost_milli": 1000,
        "supply_eligible": True,
        "graph_relative_path": GRAPH_RELATIVE_PATH,
        "graph_raw_sha256": graph_raw_sha256,
        "p2_sites_raw_sha256": P2_SITES_RAW_SHA256,
        "frozen_p1": {
            "source_dataset_raw_sha256": proposal["source_dataset_raw_sha256"],
            "source_dataset_sha256": proposal["source_dataset_sha256"],
            "source_embedded_dataset_sha256": proposal[
                "source_embedded_dataset_sha256"
            ],
            "source_topology_edge_count": proposal["source_topology_edge_count"],
        },
        "approved_edges": _edge_contract(proposal),
    }


def _proposal_semantics_are_valid(proposal: dict[str, Any]) -> bool:
    try:
        edge_ids = proposal["proposed_enabled_edge_ids"]
        disabled_ids = proposal["disabled_candidate_edge_ids"]
        all_ids = sorted(edge_ids + disabled_ids)
        node_rows = proposal["proposed_nodes"]
        edge_rows = proposal["proposed_edges"]
        return all(
            (
                proposal["schema"]
                == "gates-of-codex.earth3-p3-route-review-inventory",
                proposal["schema_version"] == 1,
                proposal["status"] == "proposal_only_not_runtime_authority",
                proposal["map_id"] == MAP_ID,
                proposal["exact_base_commit"] == AUTHORIZED_BASE_COMMIT,
                proposal["accepted_p2_head"] == ACCEPTED_P2_HEAD,
                len(edge_ids) == 65,
                edge_ids == sorted(edge_ids),
                len(set(edge_ids)) == 65,
                [edge["edge_id"] for edge in edge_rows] == edge_ids,
                len(node_rows) == 64,
                [row["node_id"] for row in node_rows]
                == sorted(row["node_id"] for row in node_rows),
                len(disabled_ids) == 8690,
                disabled_ids == sorted(disabled_ids),
                set(edge_ids).isdisjoint(disabled_ids),
                proposal["allowlist_sha256"] == _canonical_list_sha256(edge_ids),
                proposal["disabled_candidate_ids_sha256"]
                == _canonical_list_sha256(disabled_ids),
                proposal["complete_candidate_ids_sha256"]
                == _canonical_list_sha256(all_ids),
                proposal["land_selectable_candidate_edge_count"] == 8755,
                proposal["non_land_or_nonselectable_structural_edge_count"] == 1494,
                all(
                    edge["directionality"] == "bidirectional"
                    and edge["movement_cost_milli"] == 1000
                    and edge["supply_eligible"] is True
                    and edge["rollback_batch_id"] == "p3-batch-001"
                    for edge in edge_rows
                ),
            )
        )
    except (KeyError, TypeError, ValueError):
        return False


def validate_authority_document(
    authority: dict[str, Any], proposal: dict[str, Any]
) -> None:
    """Reject any authority record not identical to the approved projection."""
    valid = _proposal_semantics_are_valid(proposal)
    try:
        expected = authority_document_from_proposal(
            proposal,
            proposal_raw_sha256=authority["proposal_inventory_sha256"],
            graph_raw_sha256=authority["graph_raw_sha256"],
        )
        valid = valid and set(authority) == _AUTHORITY_KEYS
        valid = valid and authority == expected
        valid = valid and bool(_SHA256_RE.fullmatch(authority["proposal_inventory_sha256"]))
        valid = valid and bool(_SHA256_RE.fullmatch(authority["graph_raw_sha256"]))
        valid = valid and authority["proposal_inventory_sha256"] == PROPOSAL_RAW_SHA256
        valid = valid and len({e["edge_id"] for e in authority["approved_edges"]}) == 65
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("authority does not match approved proposal")


def topology_pair(edge: Any) -> tuple[str, str]:
    if isinstance(edge, list) and len(edge) == 2:
        return str(edge[0]), str(edge[1])
    if isinstance(edge, dict):
        for keys in (("a", "b"), ("province_a", "province_b")):
            if all(key in edge for key in keys):
                return str(edge[keys[0]]), str(edge[keys[1]])
    raise ValueError("malformed frozen topology edge")


def _round_pixel(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("province centroid must be numeric")
    if not math.isfinite(float(value)) or value < 0:
        raise ValueError("province centroid must be finite and non-negative")
    return int(math.floor(float(value) + 0.5))


def _validate_frozen_inputs(
    authority: dict[str, Any],
    proposal: dict[str, Any],
    dataset: dict[str, Any],
    sites_document: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], set[frozenset[str]]]:
    validate_authority_document(authority, proposal)
    if dataset.get("map_id") != MAP_ID:
        raise ValueError("wrong frozen Earth3 dataset")
    if len(dataset.get("edges", [])) != authority["frozen_p1"][
        "source_topology_edge_count"
    ]:
        raise ValueError("wrong frozen Earth3 topology count")

    provinces = dataset.get("provinces")
    if not isinstance(provinces, list):
        raise ValueError("frozen Earth3 provinces must be a list")
    province_by_id: dict[str, dict[str, Any]] = {}
    for row in provinces:
        province_id = str(row.get("id", "")) if isinstance(row, dict) else ""
        if not province_id or province_id in province_by_id:
            raise ValueError("duplicate or malformed frozen province")
        province_by_id[province_id] = row

    topology: set[frozenset[str]] = set()
    for edge in dataset["edges"]:
        left, right = topology_pair(edge)
        if left == right:
            raise ValueError("frozen topology contains a self-loop")
        topology.add(frozenset((left, right)))
    if len(topology) != len(dataset["edges"]):
        raise ValueError("frozen topology contains duplicate pairs")

    approved_nodes = {
        row["province_id"]: row["node_id"] for row in proposal["proposed_nodes"]
    }
    if len(approved_nodes) != 64:
        raise ValueError("approved node projection is not unique")
    for province_id, node_id in approved_nodes.items():
        if node_id != f"op-node-{province_id}-anchor":
            raise ValueError("approved stable node ID mismatch")
        if province_id not in province_by_id:
            raise ValueError("approved node missing from frozen dataset")
        if province_by_id[province_id].get("is_water") is not False:
            raise ValueError("approved node is not frozen land")

    for edge in authority["approved_edges"]:
        pair = frozenset(edge["endpoint_province_ids"])
        if pair not in topology:
            raise ValueError(
                f"approved pair is absent from frozen topology: {edge['edge_id']}"
            )

    if sites_document.get("schema_version") != 1:
        raise ValueError("wrong P2 sites schema")
    if sites_document.get("connectivity_authority") != "none_until_p3":
        raise ValueError("P2 sites already claim route authority")
    site_rows = sites_document.get("sites")
    if not isinstance(site_rows, list) or len(site_rows) != 7:
        raise ValueError("wrong P2 site intents")
    site_ids: set[str] = set()
    for site in site_rows:
        if site["site_id"] in site_ids:
            raise ValueError("duplicate P2 site intent")
        site_ids.add(site["site_id"])
        if site["province_id"] not in approved_nodes:
            raise ValueError("P2 site is outside approved P3 nodes")
    return province_by_id, topology


def build_graph_document(
    authority: dict[str, Any],
    proposal: dict[str, Any],
    dataset: dict[str, Any],
    sites_document: dict[str, Any],
) -> dict[str, Any]:
    province_by_id, _ = _validate_frozen_inputs(
        authority, proposal, dataset, sites_document
    )
    site_rows = sorted(sites_document["sites"], key=lambda row: row["site_id"])
    site_by_province = {row["province_id"]: row for row in site_rows}
    pixels: dict[str, list[int]] = {}
    nodes: list[dict[str, Any]] = []
    for approved_node in proposal["proposed_nodes"]:
        province_id = approved_node["province_id"]
        centroid = province_by_id[province_id].get("centroid")
        if not isinstance(centroid, list) or len(centroid) != 2:
            raise ValueError("approved province lacks a presentation centroid")
        pixel = [_round_pixel(centroid[0]), _round_pixel(centroid[1])]
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
        facilities = ["supply_hub"] if site["supply_hub_intent"] else []
        sites.append(
            {
                "site_id": site["site_id"],
                "display_name": site["display_name"],
                "kind": site["kind"],
                "province_id": province_id,
                "pixel": pixels[province_id],
                "route_node_id": f"op-node-{province_id}-anchor",
                "control_weight_milli": 1000,
                "capture_threshold_milli": 1000,
                "tags": ["earth3_p2_site_intent"],
                "facilities": facilities,
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
        length = max(
            1,
            int(
                math.floor(
                    math.hypot(right_px[0] - left_px[0], right_px[1] - left_px[1])
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
                "length_px": length,
                "base_move_points_milli": 1000,
                "movement_cost_milli": edge["movement_cost_milli"],
                "requires_port": False,
                "can_be_blockaded": False,
                "traversal_enabled": True,
                "bidirectional": edge["directionality"] == "bidirectional",
                "province_ids": edge["endpoint_province_ids"],
                "legacy_crossing_type": None,
                "metadata": {
                    "approval_comment_id": APPROVAL_COMMENT_ID,
                    "batch_id": authority["batch_id"],
                    "rollback_batch_id": edge["rollback_batch_id"],
                    "source": "owner_approved_earth3_p3_corridor",
                    "supply_capable": edge["supply_eligible"],
                },
            }
        )

    return {
        "schema": GRAPH_SCHEMA,
        "schema_version": 2,
        "map_id": MAP_ID,
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
            "approval_comment_id": APPROVAL_COMMENT_ID,
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


def build_graph_bytes(
    authority: dict[str, Any],
    proposal: dict[str, Any],
    dataset: dict[str, Any],
    sites_document: dict[str, Any],
    *,
    verify_graph_hash: bool = True,
) -> bytes:
    raw = _json_bytes(
        build_graph_document(authority, proposal, dataset, sites_document)
    )
    if verify_graph_hash and authority["graph_raw_sha256"] != _sha256_bytes(raw):
        raise ValueError("generated graph hash does not match P3 authority")
    return raw


def _load_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        return json.loads(raw.decode("utf-8")), raw
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid UTF-8 JSON: {path}") from exc


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def generate(
    root: Path,
    *,
    initialize_authority: bool = False,
    output_path: Path | None = None,
) -> tuple[str, str]:
    proposal, proposal_raw = _load_json(root / PROPOSAL_RELATIVE_PATH)
    dataset, dataset_raw = _load_json(root / DATASET_RELATIVE_PATH)
    sites, sites_raw = _load_json(root / SITES_RELATIVE_PATH)
    if _sha256_bytes(sites_raw) != P2_SITES_RAW_SHA256:
        raise ValueError("P2 sites bytes do not match the accepted P2 head")
    authority_path = root / AUTHORITY_RELATIVE_PATH
    graph_path = output_path if output_path is not None else root / GRAPH_RELATIVE_PATH

    if initialize_authority:
        provisional = authority_document_from_proposal(
            proposal,
            proposal_raw_sha256=_sha256_bytes(proposal_raw),
            graph_raw_sha256="0" * 64,
        )
        graph_raw = build_graph_bytes(
            provisional, proposal, dataset, sites, verify_graph_hash=False
        )
        authority = authority_document_from_proposal(
            proposal,
            proposal_raw_sha256=_sha256_bytes(proposal_raw),
            graph_raw_sha256=_sha256_bytes(graph_raw),
        )
        graph_raw = build_graph_bytes(authority, proposal, dataset, sites)
        if _sha256_bytes(dataset_raw) != authority["frozen_p1"][
            "source_dataset_raw_sha256"
        ]:
            raise ValueError("dataset bytes do not match frozen P1 authority")
        if authority["graph_raw_sha256"] != _sha256_bytes(graph_raw):
            raise ValueError("graph hash changed while finalizing authority")
        _atomic_write(authority_path, _json_bytes(authority))
    else:
        authority, _ = _load_json(authority_path)
        if authority.get("proposal_inventory_sha256") != _sha256_bytes(proposal_raw):
            raise ValueError("proposal bytes do not match P3 authority")
        if _sha256_bytes(dataset_raw) != authority["frozen_p1"][
            "source_dataset_raw_sha256"
        ]:
            raise ValueError("dataset bytes do not match frozen P1 authority")
        graph_raw = build_graph_bytes(authority, proposal, dataset, sites)
        if authority["graph_raw_sha256"] != _sha256_bytes(graph_raw):
            raise ValueError("generated graph does not match P3 authority hash")

    _atomic_write(graph_path, graph_raw)
    return _sha256_bytes(_json_bytes(authority)), _sha256_bytes(graph_raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument(
        "--initialize-authority",
        action="store_true",
        help="create the explicit authority record from the approved proposal",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write graph bytes to this path instead of the committed asset",
    )
    args = parser.parse_args()
    authority_sha, graph_sha = generate(
        args.root.resolve(),
        initialize_authority=args.initialize_authority,
        output_path=args.output.resolve() if args.output is not None else None,
    )
    print(f"authority_raw_sha256={authority_sha}")
    print(f"graph_raw_sha256={graph_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
