from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.earth3_operational import (
    AUTHORITY_RAW_SHA256,
    GRAPH_RAW_SHA256,
    P3_AUTHORITY_METADATA_KEY,
    P3_AUTHORITY_RELATIVE_PATH,
    P3_GRAPH_RELATIVE_PATH,
    Earth3OperationalAuthorityError,
    authenticated_p3_state_metadata,
    load_authenticated_p3_graph,
    validate_p3_documents,
)
from gates_of_codex.operational_position import load_operational_graph_for_state


AUTHORITY_PATH = ROOT / P3_AUTHORITY_RELATIVE_PATH
GRAPH_PATH = ROOT / P3_GRAPH_RELATIVE_PATH
PROPOSAL_PATH = ROOT / "docs/audits/p3-first-corridor-route-inventory.json"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _install_exact_artifacts(root: Path) -> None:
    authority = root / P3_AUTHORITY_RELATIVE_PATH
    graph = root / P3_GRAPH_RELATIVE_PATH
    authority.parent.mkdir(parents=True, exist_ok=True)
    graph.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(AUTHORITY_PATH, authority)
    shutil.copyfile(GRAPH_PATH, graph)


def _disabled_edge_record(authority: dict, proposal: dict) -> dict:
    edge_id = proposal["disabled_candidate_edge_ids"][0]
    left, right = edge_id.removeprefix("op-edge-corridor-").split("__", 1)
    return {
        "edge_id": edge_id,
        "endpoint_node_ids": [left, right],
        "endpoint_province_ids": [
            left.removeprefix("op-node-").removesuffix("-anchor"),
            right.removeprefix("op-node-").removesuffix("-anchor"),
        ],
        "directionality": "bidirectional",
        "movement_cost_milli": 1000,
        "supply_eligible": True,
        "rollback_batch_id": "p3-batch-001",
    }


def _raw_p2_state() -> SimpleNamespace:
    return SimpleNamespace(
        map_id="earth3_europe_mediterranean",
        map_metadata={
            "scenario_content_phase": "p2_campaign_bootstrap",
            "operational_graph": None,
            "operational_maneuver_enabled": False,
        },
    )


def _authority_mutations(authority: dict, proposal: dict):
    version = copy.deepcopy(authority)
    version["schema_version"] = 2
    yield "version", version

    provenance = copy.deepcopy(authority)
    provenance["proposal_commit"] = "0" * 40
    yield "provenance", provenance

    count = copy.deepcopy(authority)
    count["approved_edge_count"] = 64
    yield "count", count

    disabled_count = copy.deepcopy(authority)
    disabled_count["disabled_candidate_edge_count"] = 8689
    yield "disabled count", disabled_count

    fixed_path = copy.deepcopy(authority)
    fixed_path["graph_relative_path"] = "../p3_operational_graph.json"
    yield "fixed path", fixed_path

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

    endpoint = copy.deepcopy(authority)
    endpoint["approved_edges"][0]["endpoint_province_ids"][0] = "e3_0000"
    yield "endpoint", endpoint

    cost = copy.deepcopy(authority)
    cost["approved_edges"][0]["movement_cost_milli"] = 999
    yield "cost", cost

    supply = copy.deepcopy(authority)
    supply["approved_edges"][0]["supply_eligible"] = False
    yield "supply", supply

    rollback = copy.deepcopy(authority)
    rollback["approved_edges"][0]["rollback_batch_id"] = "p3-batch-002"
    yield "rollback", rollback

    allowlist_hash = copy.deepcopy(authority)
    allowlist_hash["allowlist_sha256"] = "0" * 64
    yield "allowlist hash", allowlist_hash

    graph_hash = copy.deepcopy(authority)
    graph_hash["graph_raw_sha256"] = "1" * 64
    yield "graph hash", graph_hash

    unapproved = copy.deepcopy(authority)
    unapproved["approved_edges"][0] = _disabled_edge_record(authority, proposal)
    yield "unapproved", unapproved

    unknown = copy.deepcopy(authority)
    unknown["unexpected"] = True
    yield "unknown", unknown

    nested_unknown = copy.deepcopy(authority)
    nested_unknown["approved_edges"][0]["unexpected"] = True
    yield "nested unknown", nested_unknown


def _graph_mutations(graph: dict, proposal: dict):
    version = copy.deepcopy(graph)
    version["schema_version"] = 3
    yield "version", version

    provenance = copy.deepcopy(graph)
    provenance["metadata"]["proposal_commit"] = "0" * 40
    yield "provenance", provenance

    missing = copy.deepcopy(graph)
    missing["edges"].pop()
    yield "missing", missing

    extra = copy.deepcopy(graph)
    extra["edges"].append(copy.deepcopy(extra["edges"][-1]))
    yield "extra", extra

    reordered = copy.deepcopy(graph)
    reordered["edges"][0], reordered["edges"][1] = (
        reordered["edges"][1],
        reordered["edges"][0],
    )
    yield "reordered", reordered

    duplicate = copy.deepcopy(graph)
    duplicate["edges"][1] = copy.deepcopy(duplicate["edges"][0])
    yield "duplicate", duplicate

    reversed_endpoints = copy.deepcopy(graph)
    reversed_endpoints["edges"][0]["a"], reversed_endpoints["edges"][0]["b"] = (
        reversed_endpoints["edges"][0]["b"],
        reversed_endpoints["edges"][0]["a"],
    )
    reversed_endpoints["edges"][0]["province_ids"].reverse()
    yield "reversed", reversed_endpoints

    endpoint = copy.deepcopy(graph)
    endpoint["edges"][0]["province_ids"][0] = "e3_0000"
    yield "endpoint", endpoint

    cost = copy.deepcopy(graph)
    cost["edges"][0]["movement_cost_milli"] = 999
    yield "cost", cost

    supply = copy.deepcopy(graph)
    supply["edges"][0]["metadata"]["supply_capable"] = False
    yield "supply", supply

    rollback = copy.deepcopy(graph)
    rollback["edges"][0]["metadata"]["rollback_batch_id"] = "p3-batch-002"
    yield "rollback", rollback

    hash_mutation = copy.deepcopy(graph)
    hash_mutation["metadata"]["allowlist_sha256"] = "0" * 64
    yield "hash", hash_mutation

    unapproved = copy.deepcopy(graph)
    disabled = _disabled_edge_record({}, proposal)
    edge = unapproved["edges"][0]
    edge["edge_id"] = disabled["edge_id"]
    edge["a"], edge["b"] = disabled["endpoint_node_ids"]
    edge["province_ids"] = disabled["endpoint_province_ids"]
    yield "unapproved", unapproved

    unknown = copy.deepcopy(graph)
    unknown["unexpected"] = True
    yield "unknown", unknown

    nested_unknown = copy.deepcopy(graph)
    nested_unknown["edges"][0]["metadata"]["unexpected"] = True
    yield "nested unknown", nested_unknown


def test_loader_pins_exact_bytes_and_returns_only_the_approved_graph() -> None:
    graph = load_authenticated_p3_graph()

    assert AUTHORITY_RAW_SHA256 == (
        "3b3330eb90351c7751d3a582c3f4c177796e297314c6e8f5497f516926fb200f"
    )
    assert GRAPH_RAW_SHA256 == (
        "c2d6ab30bfd3e2e15404242144831c5dd6ba284cd132e605e2544be8524d72cf"
    )
    assert graph == _read_json(GRAPH_PATH)
    assert len(graph["nodes"]) == 64
    assert len(graph["edges"]) == 65
    assert all(edge["authority"] == "approved" for edge in graph["edges"])


def test_loader_rejects_missing_or_byte_changed_fixed_artifacts(tmp_path: Path) -> None:
    with pytest.raises(Earth3OperationalAuthorityError, match="missing"):
        load_authenticated_p3_graph(repository_root=tmp_path)

    authority_path = tmp_path / P3_AUTHORITY_RELATIVE_PATH
    authority_path.parent.mkdir(parents=True)
    shutil.copyfile(AUTHORITY_PATH, authority_path)
    with pytest.raises(Earth3OperationalAuthorityError, match="graph missing"):
        load_authenticated_p3_graph(repository_root=tmp_path)

    _install_exact_artifacts(tmp_path)
    assert load_authenticated_p3_graph(repository_root=tmp_path) == _read_json(GRAPH_PATH)

    authority_path.write_bytes(authority_path.read_bytes() + b" ")
    with pytest.raises(Earth3OperationalAuthorityError, match="SHA-256"):
        load_authenticated_p3_graph(repository_root=tmp_path)

    _install_exact_artifacts(tmp_path)
    graph_path = tmp_path / P3_GRAPH_RELATIVE_PATH
    graph_path.write_bytes(graph_path.read_bytes() + b" ")
    with pytest.raises(Earth3OperationalAuthorityError, match="SHA-256"):
        load_authenticated_p3_graph(repository_root=tmp_path)


@pytest.mark.parametrize(
    "bad_bytes",
    [
        b"{",
        b'{"schema":"first","schema":"second"}',
        b"\xff",
        json.dumps({"unexpected": True}).encode("utf-8"),
    ],
    ids=["malformed", "duplicate-key", "non-utf8", "unknown-fields"],
)
def test_loader_rejects_malformed_duplicate_or_unknown_authority_bytes(
    tmp_path: Path, bad_bytes: bytes
) -> None:
    _install_exact_artifacts(tmp_path)
    (tmp_path / P3_AUTHORITY_RELATIVE_PATH).write_bytes(bad_bytes)
    with pytest.raises(Earth3OperationalAuthorityError):
        load_authenticated_p3_graph(repository_root=tmp_path)


def test_semantic_validator_rejects_every_task2_authority_mutation() -> None:
    authority = _read_json(AUTHORITY_PATH)
    graph = _read_json(GRAPH_PATH)
    proposal = _read_json(PROPOSAL_PATH)

    for label, mutated in _authority_mutations(authority, proposal):
        with pytest.raises(Earth3OperationalAuthorityError, match="authority|graph"):
            validate_p3_documents(mutated, graph)


def test_semantic_validator_rejects_every_graph_projection_mutation() -> None:
    authority = _read_json(AUTHORITY_PATH)
    graph = _read_json(GRAPH_PATH)
    proposal = _read_json(PROPOSAL_PATH)

    for label, mutated in _graph_mutations(graph, proposal):
        with pytest.raises(Earth3OperationalAuthorityError, match="authority|graph"):
            validate_p3_documents(authority, mutated)


def test_raw_p2_state_is_inert_and_cannot_select_an_arbitrary_graph() -> None:
    state = _raw_p2_state()
    assert load_operational_graph_for_state(state) is None

    state.map_metadata["operational_graph"] = "../unapproved/operational_graph.json"
    assert load_operational_graph_for_state(state) is None


def test_authenticated_p3_state_loads_only_the_fixed_graph_path() -> None:
    state = _raw_p2_state()
    state.map_metadata[P3_AUTHORITY_METADATA_KEY] = authenticated_p3_state_metadata()
    state.map_metadata["operational_graph"] = P3_GRAPH_RELATIVE_PATH

    assert load_operational_graph_for_state(state) == _read_json(GRAPH_PATH)

    for configured in (
        "../p3_authority/p3_operational_graph.json",
        str(GRAPH_PATH.resolve()),
        "godot/assets/maps/earth3_europe_mediterranean/operational/operational_graph.json",
    ):
        state.map_metadata["operational_graph"] = configured
        before = copy.deepcopy(state.map_metadata)
        with pytest.raises(Earth3OperationalAuthorityError, match="fixed P3 graph path"):
            load_operational_graph_for_state(state)
        assert state.map_metadata == before


def test_p3_state_metadata_is_closed_and_exactly_authenticated() -> None:
    state = _raw_p2_state()
    state.map_metadata["operational_graph"] = P3_GRAPH_RELATIVE_PATH

    mutations: list[dict] = []
    expected = authenticated_p3_state_metadata()
    missing = copy.deepcopy(expected)
    missing.pop("graph_raw_sha256")
    mutations.append(missing)
    extra = copy.deepcopy(expected)
    extra["unexpected"] = True
    mutations.append(extra)
    wrong_hash = copy.deepcopy(expected)
    wrong_hash["authority_raw_sha256"] = "0" * 64
    mutations.append(wrong_hash)
    wrong_version = copy.deepcopy(expected)
    wrong_version["schema_version"] = 2
    mutations.append(wrong_version)

    for marker in mutations:
        state.map_metadata[P3_AUTHORITY_METADATA_KEY] = marker
        before = copy.deepcopy(state.map_metadata)
        with pytest.raises(Earth3OperationalAuthorityError, match="P3 state authority"):
            load_operational_graph_for_state(state)
        assert state.map_metadata == before
