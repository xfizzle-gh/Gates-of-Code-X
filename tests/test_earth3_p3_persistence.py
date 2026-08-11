from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.earth3_operational import (
    P3_AUTHORITY_METADATA_KEY,
    P3_MIGRATION_METADATA_KEY,
    Earth3OperationalAuthorityError,
    validate_earth3_p3_campaign_extension,
)
from gates_of_codex.models import Faction
from gates_of_codex.operational_movement import (
    activate_committed_orders,
    advance_operational_tick,
    commit_move_orders,
    issue_move_order,
)
from gates_of_codex.operational_schema import FormationOperationalPosition, PositionMode
from gates_of_codex.operational_supply import refresh_operational_supply
from gates_of_codex.scenario import build_scenario
from gates_of_codex.state_io import campaign_from_dict, load_campaign, save_campaign
from test_p2_earth3_campaign_bootstrap import _campaign


ZAP_NODES = [
    "op-node-e3_1962-anchor",
    "op-node-e3_2795-anchor",
    "op-node-e3_2796-anchor",
    "op-node-e3_3380-anchor",
]
ZAP_EDGES = [
    "op-edge-corridor-op-node-e3_1962-anchor__op-node-e3_2795-anchor",
    "op-edge-corridor-op-node-e3_2795-anchor__op-node-e3_2796-anchor",
    "op-edge-corridor-op-node-e3_2796-anchor__op-node-e3_3380-anchor",
]


def _normalized_initial_state():
    return campaign_from_dict(build_scenario("earth3_v1").to_dict())


def _round_trip(state, tmp_path: Path, name: str):
    first = tmp_path / f"{name}-first.json"
    second = tmp_path / f"{name}-second.json"
    save_campaign(state, first)
    loaded = load_campaign(first)
    save_campaign(loaded, second)
    assert first.read_bytes() == second.read_bytes()
    validate_earth3_p3_campaign_extension(loaded)
    return loaded


def _prepare_pending_battle():
    state = _normalized_initial_state()
    issue_move_order(
        state,
        "sf_ukr_zaporizhzhia",
        path_node_ids=ZAP_NODES,
        path_edge_ids=ZAP_EDGES,
        order_id="persist-zap",
    )
    issue_move_order(
        state,
        "sf_rus_donetsk",
        path_node_ids=list(reversed(ZAP_NODES)),
        path_edge_ids=list(reversed(ZAP_EDGES)),
        order_id="persist-donetsk",
    )
    commit_move_orders(state)
    activate_committed_orders(state)
    advance_operational_tick(state)
    advance_operational_tick(state)
    assert state.pending_battle is not None
    return state


def test_initial_p3_state_round_trip_is_byte_stable(tmp_path: Path) -> None:
    state = _normalized_initial_state()
    loaded = _round_trip(state, tmp_path, "initial")

    assert loaded.map_metadata[P3_AUTHORITY_METADATA_KEY] == state.map_metadata[
        P3_AUTHORITY_METADATA_KEY
    ]
    assert loaded.map_metadata[P3_MIGRATION_METADATA_KEY] == state.map_metadata[
        P3_MIGRATION_METADATA_KEY
    ]
    assert set(loaded.strategic_formations) == set(state.strategic_formations)


def test_in_transit_order_round_trip_preserves_exact_route_and_progress(
    tmp_path: Path,
) -> None:
    state = _normalized_initial_state()
    force = state.strategic_formations["sf_ukr_zaporizhzhia"]
    issue_move_order(
        state,
        force.strategic_formation_id,
        path_node_ids=ZAP_NODES,
        path_edge_ids=ZAP_EDGES,
        order_id="persist-in-transit",
    )
    commit_move_orders(state, faction=Faction.UKRAINE.value)
    activate_committed_orders(state)
    force.position = FormationOperationalPosition(
        mode=PositionMode.ON_EDGE.value,
        node_id=None,
        edge_id=ZAP_EDGES[0],
        progress_milli=375,
        facing_node_id=ZAP_NODES[1],
    )

    loaded = _round_trip(state, tmp_path, "transit")
    after = loaded.strategic_formations[force.strategic_formation_id]
    assert after.position is not None
    assert after.position.mode == PositionMode.ON_EDGE.value
    assert after.position.edge_id == ZAP_EDGES[0]
    assert after.position.progress_milli == 375
    assert after.position.facing_node_id == ZAP_NODES[1]
    assert after.move_order is not None
    assert after.move_order.path_node_ids == ZAP_NODES
    assert after.move_order.path_edge_ids == ZAP_EDGES


def test_pending_edge_battle_round_trip_preserves_contact_metadata(
    tmp_path: Path,
) -> None:
    state = _prepare_pending_battle()
    pending = state.pending_battle
    assert pending is not None
    expected = (
        pending.encounter_kind,
        pending.encounter_edge_id,
        pending.encounter_progress_milli,
        list(pending.encounter_pixel),
        pending.attacker_formation_id,
        pending.defender_formation_id,
    )

    loaded = _round_trip(state, tmp_path, "pending")
    after = loaded.pending_battle
    assert after is not None
    assert (
        after.encounter_kind,
        after.encounter_edge_id,
        after.encounter_progress_milli,
        list(after.encounter_pixel),
        after.attacker_formation_id,
        after.defender_formation_id,
    ) == expected


def test_resolved_retreat_round_trip_preserves_post_battle_position(
    tmp_path: Path,
) -> None:
    state = _prepare_pending_battle()
    CampaignEngine(state, random_seed=0).apply_battle_result(Faction.UKRAINE)
    russian = state.strategic_formations["sf_rus_donetsk"]
    assert russian.position is not None
    expected_position = copy.deepcopy(russian.position)

    loaded = _round_trip(state, tmp_path, "retreat")
    after = loaded.strategic_formations["sf_rus_donetsk"]
    assert after.position == expected_position
    assert loaded.pending_battle is None


def test_supply_state_round_trip_preserves_sources_and_routes(tmp_path: Path) -> None:
    state = _normalized_initial_state()
    report = refresh_operational_supply(state, consume_grace=False)
    assert len(report.connected) == 11
    expected = {
        key: (
            force.supplied,
            force.cut_off,
            force.source_hub_id,
            force.route_cost,
            force.grace_ticks_remaining,
        )
        for key, force in sorted(state.strategic_formations.items())
    }

    loaded = _round_trip(state, tmp_path, "supply")
    actual = {
        key: (
            force.supplied,
            force.cut_off,
            force.source_hub_id,
            force.route_cost,
            force.grace_ticks_remaining,
        )
        for key, force in sorted(loaded.strategic_formations.items())
    }
    assert actual == expected


def test_raw_p2_load_migrates_once_and_subsequent_load_does_not_reinitialize(
    tmp_path: Path,
) -> None:
    first = campaign_from_dict(_campaign().to_dict())
    migration = copy.deepcopy(first.map_metadata[P3_MIGRATION_METADATA_KEY])
    force = first.strategic_formations["sf_ukr_zaporizhzhia"]
    force.position = FormationOperationalPosition(
        mode=PositionMode.ON_EDGE.value,
        node_id=None,
        edge_id=ZAP_EDGES[0],
        progress_milli=625,
        facing_node_id=ZAP_NODES[1],
    )

    path = tmp_path / "migrated.json"
    save_campaign(first, path)
    second = load_campaign(path)

    assert second.map_metadata[P3_MIGRATION_METADATA_KEY] == migration
    after = second.strategic_formations[force.strategic_formation_id]
    assert after.position is not None
    assert after.position.progress_milli == 625
    assert after.position.edge_id == ZAP_EDGES[0]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload["map_metadata"][P3_AUTHORITY_METADATA_KEY].__setitem__(
            "allowlist_sha256", "0" * 64
        ),
        lambda payload: payload["strategic_formations"]["sf_ukr_zaporizhzhia"][
            "position"
        ].__setitem__("node_id", "op-node-e3_unknown-anchor"),
        lambda payload: payload["map_metadata"].__setitem__(
            "operational_graph", "godot/assets/maps/not-authorized.json"
        ),
    ],
)
def test_authenticated_p3_tampering_fails_before_state_is_returned(mutator) -> None:
    payload = _normalized_initial_state().to_dict()
    mutator(payload)
    before = copy.deepcopy(payload)

    with pytest.raises((Earth3OperationalAuthorityError, ValueError)):
        campaign_from_dict(payload)

    assert payload == before


def test_failed_tampered_file_load_preserves_source_bytes(tmp_path: Path) -> None:
    payload = _normalized_initial_state().to_dict()
    payload["map_metadata"][P3_AUTHORITY_METADATA_KEY]["graph_raw_sha256"] = "f" * 64
    path = tmp_path / "tampered.json"
    original = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode()
    path.write_bytes(original)

    with pytest.raises((Earth3OperationalAuthorityError, ValueError)):
        load_campaign(path)

    assert path.read_bytes() == original
