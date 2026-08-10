from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.operational_schema import (
    EdgeAuthority,
    EdgeKind,
    OperationalRouteEdge,
)


FROZEN_HASHES = ROOT / "tests/fixtures/earth3_p3_frozen_hashes.json"
PROPOSAL = ROOT / "docs/audits/p3-first-corridor-route-inventory.json"
P3_AUTHORITY = ROOT / "config/earth3/p3_operational_authority.json"
P3_GRAPH = (
    ROOT
    / "godot/assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json"
)

AUTHORIZED_BASE_COMMIT = "d16e7b145db82180d628bc9c0a636ebbab51db3c"
ACCEPTED_P2_HEAD = "4f2eee80256b9a4c5388c88b2d2e357b883b9e6c"
PROPOSAL_COMMIT = "1c51766f4c099d3307db70cffec815772b314d21"
APPROVAL_ISSUE = 141
APPROVAL_COMMENT_ID = 5234226059
APPROVED_BATCH_ID = "earth3-p3-first-playable-corridors-v1"
APPROVED_ROLLBACK_BATCH_ID = "p3-batch-001"
APPROVED_ALLOWLIST_SHA256 = (
    "08901e371baa34688429afc9a6f06cc6361da13eac6eb9907901b47c9c233965"
)
APPROVED_EDGE_COUNT = 65
APPROVED_NODE_COUNT = 64
DISABLED_CANDIDATE_EDGE_COUNT = 8690
EXCLUDED_STRUCTURAL_EDGE_COUNT = 1494
APPROVED_MOVEMENT_COST_MILLI = 1000
APPROVED_DIRECTIONALITY = "bidirectional"

EXPECTED_P1_PATHS = {
    "config/earth3/production_authority.json",
    "godot/assets/maps/earth3_europe_mediterranean/dataset_meta.json",
    "godot/assets/maps/earth3_europe_mediterranean/map_manifest.json",
    "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json",
}
EXPECTED_PROPOSAL_PATHS = {
    "docs/audits/p3-first-corridor-route-inventory.json",
}
EXPECTED_P2_PATHS = {
    f"src/gates_of_codex/data/earth3_v1/{filename}"
    for filename in (
        "alliances.json",
        "bootstrap.json",
        "commanders.json",
        "deployment_zones.json",
        "factions.json",
        "formations.json",
        "objectives.json",
        "ownership.json",
        "province_mappings.json",
        "sites.json",
        "tactical_maps.json",
    )
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_list_sha256(values: list[str]) -> str:
    encoded = json.dumps(values, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _approved_edge_contract(proposal: dict) -> list[dict]:
    """Project the owner-approved, gameplay-authoritative fields only."""
    keys = (
        "edge_id",
        "endpoint_node_ids",
        "endpoint_province_ids",
        "directionality",
        "movement_cost_milli",
        "supply_eligible",
        "rollback_batch_id",
    )
    return [{key: edge[key] for key in keys} for edge in proposal["proposed_edges"]]


def _approved_schema_edge() -> OperationalRouteEdge:
    left = "op-node-e3_0391-anchor"
    right = "op-node-e3_2171-anchor"
    return OperationalRouteEdge(
        edge_id=f"op-edge-corridor-{left}__{right}",
        a=left,
        b=right,
        kind=EdgeKind.CORRIDOR.value,
        authority=EdgeAuthority.APPROVED.value,
        length_px=38,
        base_move_points_milli=1000,
        movement_cost_milli=1000,
        requires_port=False,
        can_be_blockaded=False,
        traversal_enabled=True,
        bidirectional=True,
        province_ids=["e3_0391", "e3_2171"],
        legacy_crossing_type=None,
        metadata={
            "approval_comment_id": APPROVAL_COMMENT_ID,
            "batch_id": APPROVED_BATCH_ID,
            "rollback_batch_id": APPROVED_ROLLBACK_BATCH_ID,
            "source": "owner_approved_earth3_p3_corridor",
            "supply_capable": True,
        },
    )


def _validate_schema_edge(edge: OperationalRouteEdge) -> None:
    edge.validate(
        node_ids={edge.a, edge.b},
        province_ids=set(edge.province_ids),
        node_province={
            edge.a: edge.province_ids[0],
            edge.b: edge.province_ids[1],
        },
    )


def test_frozen_hash_fixture_names_the_exact_authorized_inputs() -> None:
    fixture = _read_json(FROZEN_HASHES)

    assert fixture["schema"] == "gates-of-codex.earth3-p3-frozen-hashes"
    assert fixture["schema_version"] == 1
    assert fixture["authorized_base_commit"] == AUTHORIZED_BASE_COMMIT
    assert fixture["accepted_p2_head"] == ACCEPTED_P2_HEAD
    assert fixture["proposal_commit"] == PROPOSAL_COMMIT
    assert fixture["approval_issue"] == APPROVAL_ISSUE
    assert fixture["approval_comment_id"] == APPROVAL_COMMENT_ID
    assert set(fixture["frozen_files"]) == {"p1", "proposal", "p2"}
    assert set(fixture["frozen_files"]["p1"]) == EXPECTED_P1_PATHS
    assert set(fixture["frozen_files"]["proposal"]) == EXPECTED_PROPOSAL_PATHS
    assert set(fixture["frozen_files"]["p2"]) == EXPECTED_P2_PATHS


def test_frozen_p1_p2_and_proposal_bytes_match_the_authorized_base() -> None:
    fixture = _read_json(FROZEN_HASHES)

    for authority_class in ("p1", "proposal", "p2"):
        for relative_path, expected_sha256 in fixture["frozen_files"][
            authority_class
        ].items():
            path = ROOT / relative_path
            assert path.is_file(), f"missing frozen {authority_class} file: {relative_path}"
            assert _raw_sha256(path) == expected_sha256, (
                f"frozen {authority_class} bytes changed: {relative_path}"
            )


def test_proposal_records_the_exact_owner_approved_batch_without_enabling_it() -> None:
    proposal = _read_json(PROPOSAL)

    assert proposal["schema"] == "gates-of-codex.earth3-p3-route-review-inventory"
    assert proposal["schema_version"] == 1
    assert proposal["status"] == "proposal_only_not_runtime_authority"
    assert proposal["batch_id"] == APPROVED_BATCH_ID
    assert proposal["rollback_batch_id"] == APPROVED_ROLLBACK_BATCH_ID
    assert proposal["exact_base_commit"] == AUTHORIZED_BASE_COMMIT
    assert proposal["accepted_p2_head"] == ACCEPTED_P2_HEAD
    assert proposal["allowlist_sha256"] == APPROVED_ALLOWLIST_SHA256
    assert proposal["enabled_proposal_edge_count"] == APPROVED_EDGE_COUNT
    assert proposal["disabled_candidate_edge_count"] == DISABLED_CANDIDATE_EDGE_COUNT
    assert (
        proposal["non_land_or_nonselectable_structural_edge_count"]
        == EXCLUDED_STRUCTURAL_EDGE_COUNT
    )

    edge_ids = proposal["proposed_enabled_edge_ids"]
    edges = proposal["proposed_edges"]
    assert len(edge_ids) == APPROVED_EDGE_COUNT
    assert len(set(edge_ids)) == APPROVED_EDGE_COUNT
    assert edge_ids == sorted(edge_ids)
    assert _canonical_list_sha256(edge_ids) == APPROVED_ALLOWLIST_SHA256
    assert [edge["edge_id"] for edge in edges] == edge_ids
    assert len(proposal["proposed_nodes"]) == APPROVED_NODE_COUNT
    assert len(proposal["disabled_candidate_edge_ids"]) == DISABLED_CANDIDATE_EDGE_COUNT
    assert set(edge_ids).isdisjoint(proposal["disabled_candidate_edge_ids"])
    assert all(
        edge["directionality"] == APPROVED_DIRECTIONALITY
        and edge["movement_cost_milli"] == APPROVED_MOVEMENT_COST_MILLI
        and edge["supply_eligible"] is True
        and edge["rollback_batch_id"] == APPROVED_ROLLBACK_BATCH_ID
        for edge in edges
    )

    approval_gate = proposal["approval_gate"]
    assert approval_gate == {
        "issue": APPROVAL_ISSUE,
        "required": True,
        "owner_approval_comment_id": None,
        "runtime_edges_enabled": False,
    }


def test_owner_approved_p3_authority_records_the_exact_semantic_contract() -> None:
    proposal = _read_json(PROPOSAL)
    authority = _read_json(P3_AUTHORITY)

    assert authority["schema"] == "gates-of-codex.earth3-p3-operational-authority"
    assert authority["schema_version"] == 1
    assert authority["status"] == "owner_approved_runtime_authority"
    assert authority["map_id"] == proposal["map_id"]
    assert authority["authorized_base_commit"] == AUTHORIZED_BASE_COMMIT
    assert authority["accepted_p2_head"] == ACCEPTED_P2_HEAD
    assert authority["proposal_commit"] == PROPOSAL_COMMIT
    assert authority["proposal_inventory_sha256"] == _raw_sha256(PROPOSAL)
    assert authority["approval_issue"] == APPROVAL_ISSUE
    assert authority["approval_comment_id"] == APPROVAL_COMMENT_ID
    assert authority["batch_id"] == APPROVED_BATCH_ID
    assert authority["rollback_batch_id"] == APPROVED_ROLLBACK_BATCH_ID
    assert authority["allowlist_sha256"] == APPROVED_ALLOWLIST_SHA256
    assert authority["approved_edge_count"] == APPROVED_EDGE_COUNT
    assert authority["approved_node_count"] == APPROVED_NODE_COUNT
    assert authority["disabled_candidate_edge_count"] == DISABLED_CANDIDATE_EDGE_COUNT
    assert authority["disabled_candidate_ids_sha256"] == proposal["disabled_candidate_ids_sha256"]
    assert authority["complete_candidate_ids_sha256"] == proposal["complete_candidate_ids_sha256"]
    assert authority["excluded_structural_edge_count"] == EXCLUDED_STRUCTURAL_EDGE_COUNT
    assert authority["directionality"] == APPROVED_DIRECTIONALITY
    assert authority["movement_cost_milli"] == APPROVED_MOVEMENT_COST_MILLI
    assert authority["supply_eligible"] is True
    assert authority["graph_relative_path"] == str(P3_GRAPH.relative_to(ROOT)).replace("\\", "/")
    assert len(authority["graph_raw_sha256"]) == 64
    assert authority["graph_raw_sha256"] == _raw_sha256(P3_GRAPH)
    assert authority["approved_edges"] == _approved_edge_contract(proposal)
    frozen_fixture = _read_json(FROZEN_HASHES)
    assert authority["p2_sites_raw_sha256"] == frozen_fixture["frozen_files"]["p2"][
        "src/gates_of_codex/data/earth3_v1/sites.json"
    ]

    p1 = authority["frozen_p1"]
    assert p1 == {
        "source_dataset_raw_sha256": proposal["source_dataset_raw_sha256"],
        "source_dataset_sha256": proposal["source_dataset_sha256"],
        "source_embedded_dataset_sha256": proposal["source_embedded_dataset_sha256"],
        "source_topology_edge_count": proposal["source_topology_edge_count"],
    }


def test_exact_byte_p3_artifacts_are_forced_to_lf_in_git() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "config/earth3/p3_operational_authority.json text eol=lf" in attributes
    assert (
        "godot/assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json text eol=lf"
        in attributes
    )


def test_approved_corridor_schema_accepts_only_the_exact_owner_policy() -> None:
    _validate_schema_edge(_approved_schema_edge())

    mutations = {
        "disabled": lambda edge: setattr(edge, "traversal_enabled", False),
        "wrong kind": lambda edge: setattr(edge, "kind", EdgeKind.ROAD.value),
        "wrong base cost": lambda edge: setattr(edge, "base_move_points_milli", 999),
        "wrong movement cost": lambda edge: setattr(edge, "movement_cost_milli", 999),
        "one way": lambda edge: setattr(edge, "bidirectional", False),
        "requires port": lambda edge: setattr(edge, "requires_port", True),
        "blockadable": lambda edge: setattr(edge, "can_be_blockaded", True),
        "legacy crossing": lambda edge: setattr(edge, "legacy_crossing_type", "land"),
        "wrong approval": lambda edge: edge.metadata.__setitem__(
            "approval_comment_id", APPROVAL_COMMENT_ID + 1
        ),
        "wrong batch": lambda edge: edge.metadata.__setitem__("batch_id", "other"),
        "wrong rollback": lambda edge: edge.metadata.__setitem__(
            "rollback_batch_id", "p3-batch-002"
        ),
        "wrong source": lambda edge: edge.metadata.__setitem__("source", "candidate"),
        "no supply": lambda edge: edge.metadata.__setitem__("supply_capable", False),
        "missing metadata": lambda edge: edge.metadata.pop("source"),
        "unknown metadata": lambda edge: edge.metadata.__setitem__("extra", True),
    }
    for _label, mutate in mutations.items():
        edge = copy.deepcopy(_approved_schema_edge())
        mutate(edge)
        with pytest.raises(ValueError, match="approved edge"):
            _validate_schema_edge(edge)


def test_candidate_and_authored_edge_schema_behavior_is_unchanged() -> None:
    candidate = copy.deepcopy(_approved_schema_edge())
    candidate.authority = EdgeAuthority.CANDIDATE.value
    candidate.traversal_enabled = False
    candidate.metadata = {}
    _validate_schema_edge(candidate)
    candidate.traversal_enabled = True
    with pytest.raises(ValueError, match="candidate edge"):
        _validate_schema_edge(candidate)

    authored = copy.deepcopy(_approved_schema_edge())
    authored.edge_id = f"op-edge-strait-{authored.a}__{authored.b}"
    authored.kind = EdgeKind.STRAIT.value
    authored.authority = EdgeAuthority.AUTHORED.value
    authored.metadata = {}
    _validate_schema_edge(authored)
