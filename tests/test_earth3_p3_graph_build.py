from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_PATH = ROOT / "config/earth3/p3_operational_authority.json"
PROPOSAL_PATH = ROOT / "docs/audits/p3-first-corridor-route-inventory.json"
DATASET_PATH = (
    ROOT / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
)
SITES_PATH = ROOT / "src/gates_of_codex/data/earth3_v1/sites.json"
GRAPH_PATH = (
    ROOT
    / "godot/assets/maps/earth3_europe_mediterranean/operational/operational_graph.json"
)
BUILDER_PATH = ROOT / "tools/earth3/build_p3_operational_graph.py"

ALLOWLIST_SHA256 = "08901e371baa34688429afc9a6f06cc6361da13eac6eb9907901b47c9c233965"
DISABLED_SHA256 = "a7d52fbe2abd1d9b32349ad42e8e00876e3f4727411f58a5e640a3b8a75bbdcf"
APPROVAL_COMMENT_ID = 5234226059
ROLLBACK_BATCH_ID = "p3-batch-001"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_builder():
    spec = importlib.util.spec_from_file_location("earth3_p3_builder", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_graph_is_the_exact_approved_64_node_65_edge_projection() -> None:
    authority = _read_json(AUTHORITY_PATH)
    proposal = _read_json(PROPOSAL_PATH)
    graph = _read_json(GRAPH_PATH)

    assert graph["schema"] == "gates-of-codex.operational-graph"
    assert graph["schema_version"] == 2
    assert graph["map_id"] == "earth3_europe_mediterranean"
    assert len(graph["nodes"]) == 64
    assert len(graph["edges"]) == 65
    assert len(graph["sites"]) == 7
    assert [node["node_id"] for node in graph["nodes"]] == [
        node["node_id"] for node in proposal["proposed_nodes"]
    ]
    assert [edge["edge_id"] for edge in graph["edges"]] == proposal[
        "proposed_enabled_edge_ids"
    ]

    approved = {edge["edge_id"]: edge for edge in authority["approved_edges"]}
    graph_edges = {edge["edge_id"]: edge for edge in graph["edges"]}
    assert set(graph_edges) == set(approved)
    assert set(graph_edges).isdisjoint(proposal["disabled_candidate_edge_ids"])
    for edge_id, expected in approved.items():
        edge = graph_edges[edge_id]
        assert [edge["a"], edge["b"]] == expected["endpoint_node_ids"]
        assert edge["province_ids"] == expected["endpoint_province_ids"]
        assert edge["kind"] == "corridor"
        assert edge["authority"] == "approved"
        assert edge["traversal_enabled"] is True
        assert edge["bidirectional"] is True
        assert edge["base_move_points_milli"] == 1000
        assert edge["movement_cost_milli"] == 1000
        assert edge["requires_port"] is False
        assert edge["can_be_blockaded"] is False
        assert edge["metadata"] == {
            "approval_comment_id": APPROVAL_COMMENT_ID,
            "batch_id": authority["batch_id"],
            "rollback_batch_id": ROLLBACK_BATCH_ID,
            "source": "owner_approved_earth3_p3_corridor",
            "supply_capable": True,
        }

    p2_sites = {row["site_id"]: row for row in _read_json(SITES_PATH)["sites"]}
    graph_sites = {row["site_id"]: row for row in graph["sites"]}
    assert set(graph_sites) == set(p2_sites)
    for site_id, intent in p2_sites.items():
        site = graph_sites[site_id]
        assert site["display_name"] == intent["display_name"]
        assert site["kind"] == intent["kind"]
        assert site["province_id"] == intent["province_id"]
        assert site["owner_faction"] == intent["owner_actor_id"]
        assert site["route_node_id"] == f"op-node-{intent['province_id']}-anchor"
        assert site["facilities"] == (
            ["supply_hub"] if intent["supply_hub_intent"] else []
        )
        assert site["metadata"]["supply_hub_intent"] is intent[
            "supply_hub_intent"
        ]

    assert graph["metadata"] == {
        "allowlist_sha256": ALLOWLIST_SHA256,
        "approval_comment_id": APPROVAL_COMMENT_ID,
        "authority_schema_version": 1,
        "batch_id": authority["batch_id"],
        "disabled_candidate_edge_count": 8690,
        "disabled_candidate_ids_sha256": DISABLED_SHA256,
        "proposal_commit": authority["proposal_commit"],
        "rollback_batch_id": ROLLBACK_BATCH_ID,
    }


def test_builder_reproduces_committed_bytes_and_is_input_order_independent() -> None:
    builder = _load_builder()
    authority = _read_json(AUTHORITY_PATH)
    proposal = _read_json(PROPOSAL_PATH)
    dataset = _read_json(DATASET_PATH)
    sites = _read_json(SITES_PATH)

    first = builder.build_graph_bytes(authority, proposal, dataset, sites)
    second = builder.build_graph_bytes(authority, proposal, dataset, sites)
    assert first == second == GRAPH_PATH.read_bytes()
    assert _canonical_sha256(first) == authority["graph_raw_sha256"]

    reordered_dataset = copy.deepcopy(dataset)
    reordered_dataset["provinces"].reverse()
    reordered_dataset["edges"].reverse()
    reordered_sites = copy.deepcopy(sites)
    reordered_sites["sites"].reverse()
    assert (
        builder.build_graph_bytes(
            authority, proposal, reordered_dataset, reordered_sites
        )
        == first
    )


def test_builder_writes_identical_temporary_outputs(tmp_path: Path) -> None:
    builder = _load_builder()
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"

    builder.generate(ROOT, output_path=first_path)
    builder.generate(ROOT, output_path=second_path)

    assert first_path.read_bytes() == second_path.read_bytes() == GRAPH_PATH.read_bytes()


def test_builder_validates_explicit_pairs_instead_of_selecting_geometry_routes() -> None:
    builder = _load_builder()
    authority = _read_json(AUTHORITY_PATH)
    proposal = _read_json(PROPOSAL_PATH)
    dataset = _read_json(DATASET_PATH)
    sites = _read_json(SITES_PATH)

    unrelated_geometry_change = copy.deepcopy(dataset)
    approved_pairs = {
        frozenset(edge["endpoint_province_ids"])
        for edge in authority["approved_edges"]
    }
    replace_index = next(
        index
        for index, row in enumerate(unrelated_geometry_change["edges"])
        if frozenset(builder.topology_pair(row)) not in approved_pairs
    )
    unrelated_geometry_change["edges"][replace_index] = ["e3_0592", "e3_2793"]
    assert (
        builder.build_graph_bytes(
            authority, proposal, unrelated_geometry_change, sites
        )
        == GRAPH_PATH.read_bytes()
    )

    missing = copy.deepcopy(dataset)
    endpoint_pair = set(authority["approved_edges"][0]["endpoint_province_ids"])
    approved_index = next(
        index
        for index, row in enumerate(missing["edges"])
        if set(builder.topology_pair(row)) == endpoint_pair
    )
    missing["edges"][approved_index] = ["e3_0000", "e3_2793"]
    with pytest.raises(ValueError, match="frozen topology"):
        builder.build_graph_bytes(authority, proposal, missing, sites)


def _mutations(authority: dict, proposal: dict):
    missing = copy.deepcopy(authority)
    missing["approved_edges"].pop()
    yield "missing", missing

    extra = copy.deepcopy(authority)
    extra["approved_edges"].append(copy.deepcopy(extra["approved_edges"][-1]))
    yield "extra", extra

    reordered = copy.deepcopy(authority)
    reordered["approved_edges"][0], reordered["approved_edges"][1] = (
        reordered["approved_edges"][1],
        reordered["approved_edges"][0],
    )
    yield "reordered", reordered

    duplicate = copy.deepcopy(authority)
    duplicate["approved_edges"][1] = copy.deepcopy(duplicate["approved_edges"][0])
    yield "duplicate", duplicate

    reversed_endpoints = copy.deepcopy(authority)
    reversed_endpoints["approved_edges"][0]["endpoint_node_ids"].reverse()
    reversed_endpoints["approved_edges"][0]["endpoint_province_ids"].reverse()
    yield "reversed", reversed_endpoints

    endpoint_mutated = copy.deepcopy(authority)
    endpoint_mutated["approved_edges"][0]["endpoint_province_ids"][0] = "e3_0000"
    yield "endpoint", endpoint_mutated

    cost_mutated = copy.deepcopy(authority)
    cost_mutated["approved_edges"][0]["movement_cost_milli"] = 999
    yield "cost", cost_mutated

    supply_mutated = copy.deepcopy(authority)
    supply_mutated["approved_edges"][0]["supply_eligible"] = False
    yield "supply", supply_mutated

    rollback_mutated = copy.deepcopy(authority)
    rollback_mutated["approved_edges"][0]["rollback_batch_id"] = "p3-batch-002"
    yield "rollback", rollback_mutated

    hash_mutated = copy.deepcopy(authority)
    hash_mutated["allowlist_sha256"] = "0" * 64
    yield "hash", hash_mutated

    proposal_hash_mutated = copy.deepcopy(authority)
    proposal_hash_mutated["proposal_inventory_sha256"] = "1" * 64
    yield "proposal hash", proposal_hash_mutated

    unapproved = copy.deepcopy(authority)
    disabled_id = proposal["disabled_candidate_edge_ids"][0]
    left, right = builder_edge_endpoints(disabled_id)
    unapproved["approved_edges"][0]["edge_id"] = disabled_id
    unapproved["approved_edges"][0]["endpoint_node_ids"] = [left, right]
    unapproved["approved_edges"][0]["endpoint_province_ids"] = [
        left.removeprefix("op-node-").removesuffix("-anchor"),
        right.removeprefix("op-node-").removesuffix("-anchor"),
    ]
    yield "unapproved", unapproved


def builder_edge_endpoints(edge_id: str) -> tuple[str, str]:
    body = edge_id.removeprefix("op-edge-corridor-")
    left, right = body.split("__", maxsplit=1)
    return left, right


def test_builder_rejects_every_adversarial_authority_record() -> None:
    builder = _load_builder()
    authority = _read_json(AUTHORITY_PATH)
    proposal = _read_json(PROPOSAL_PATH)

    for label, mutated in _mutations(authority, proposal):
        with pytest.raises(ValueError, match="authority does not match approved proposal"):
            builder.validate_authority_document(mutated, proposal)


def test_builder_rejects_disabled_digest_or_count_mutation() -> None:
    builder = _load_builder()
    authority = _read_json(AUTHORITY_PATH)
    proposal = _read_json(PROPOSAL_PATH)

    for key, value in (
        ("disabled_candidate_edge_count", 8689),
        ("disabled_candidate_ids_sha256", "0" * 64),
        ("complete_candidate_ids_sha256", "f" * 64),
    ):
        mutated = copy.deepcopy(authority)
        mutated[key] = value
        with pytest.raises(ValueError, match="authority does not match approved proposal"):
            builder.validate_authority_document(mutated, proposal)


def test_builder_rejects_graph_hash_mutation() -> None:
    builder = _load_builder()
    authority = _read_json(AUTHORITY_PATH)
    proposal = _read_json(PROPOSAL_PATH)
    dataset = _read_json(DATASET_PATH)
    sites = _read_json(SITES_PATH)
    authority["graph_raw_sha256"] = "2" * 64

    with pytest.raises(ValueError, match="graph hash"):
        builder.build_graph_bytes(authority, proposal, dataset, sites)
