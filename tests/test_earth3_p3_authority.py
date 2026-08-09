from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FROZEN_HASHES = ROOT / "tests/fixtures/earth3_p3_frozen_hashes.json"
PROPOSAL = ROOT / "docs/audits/p3-first-corridor-route-inventory.json"
P3_AUTHORITY = ROOT / "config/earth3/p3_operational_authority.json"
P3_GRAPH = (
    ROOT
    / "godot/assets/maps/earth3_europe_mediterranean/operational/operational_graph.json"
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
    assert not P3_AUTHORITY.exists()
    assert not P3_GRAPH.exists()


def test_owner_approved_p3_requires_separate_authority_and_graph_artifacts() -> None:
    missing = [
        str(path.relative_to(ROOT))
        for path in (P3_AUTHORITY, P3_GRAPH)
        if not path.is_file()
    ]
    assert missing == [], (
        "owner-approved P3 artifacts are not implemented yet: " + ", ".join(missing)
    )
