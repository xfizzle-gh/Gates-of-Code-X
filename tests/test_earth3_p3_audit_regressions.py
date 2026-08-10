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
    P3_STARTING_FORMATION_IDS,
    Earth3OperationalAuthorityError,
    load_authenticated_p3_graph,
    validate_earth3_p3_campaign_extension,
)
from gates_of_codex.models import Faction
from gates_of_codex.observation import refresh_all_observer_knowledge
from gates_of_codex.operational_ai import (
    build_operational_planning_view,
    plan_and_issue_operational_orders,
)
from gates_of_codex.operational_movement import (
    activate_committed_orders,
    advance_operational_tick,
    commit_move_orders,
    issue_move_order,
)
from gates_of_codex.scenario import build_scenario
from gates_of_codex.state_io import campaign_from_dict, load_campaign, save_campaign


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


def _normalized_p3():
    return campaign_from_dict(build_scenario("earth3_v1").to_dict())


def _pending_zaporizhzhia_donetsk_battle():
    state = _normalized_p3()
    issue_move_order(
        state,
        "sf_ukr_zaporizhzhia",
        path_node_ids=ZAP_NODES,
        path_edge_ids=ZAP_EDGES,
        order_id="audit-zap",
    )
    issue_move_order(
        state,
        "sf_rus_donetsk",
        path_node_ids=list(reversed(ZAP_NODES)),
        path_edge_ids=list(reversed(ZAP_EDGES)),
        order_id="audit-donetsk",
    )
    commit_move_orders(state)
    activate_committed_orders(state)
    advance_operational_tick(state)
    advance_operational_tick(state)
    assert state.pending_battle is not None
    return state


def test_eliminated_starting_formation_round_trips_without_recreation(
    tmp_path: Path,
) -> None:
    state = _pending_zaporizhzhia_donetsk_battle()
    russian = state.strategic_formations["sf_rus_donetsk"]
    assert len(russian.battalion_ids) == 1
    eliminated_battalion_id = russian.battalion_ids[0]

    CampaignEngine(state, random_seed=0).apply_external_battle_result(
        Faction.UKRAINE,
        {eliminated_battalion_id: []},
    )

    assert "sf_rus_donetsk" not in state.strategic_formations
    assert eliminated_battalion_id not in state.battalions
    assert set(state.strategic_formations) == (
        P3_STARTING_FORMATION_IDS - {"sf_rus_donetsk"}
    )
    validate_earth3_p3_campaign_extension(state)

    first = tmp_path / "evolved-first.json"
    second = tmp_path / "evolved-second.json"
    save_campaign(state, first)
    loaded = load_campaign(first)
    assert "sf_rus_donetsk" not in loaded.strategic_formations
    assert eliminated_battalion_id not in loaded.battalions
    validate_earth3_p3_campaign_extension(loaded)
    save_campaign(loaded, second)

    assert first.read_bytes() == second.read_bytes()


def test_authenticated_p3_rejects_unknown_replacement_formation_identity() -> None:
    payload = _normalized_p3().to_dict()
    old_id = "sf_rus_donetsk"
    new_id = "sf_rus_replacement"
    row = payload["strategic_formations"].pop(old_id)
    row["strategic_formation_id"] = new_id
    payload["strategic_formations"][new_id] = row
    for battalion_id in row["battalion_ids"]:
        payload["battalions"][battalion_id]["strategic_formation_id"] = new_id
    if row.get("commander_id"):
        payload["commanders"][row["commander_id"]][
            "assigned_strategic_formation_id"
        ] = new_id
    before = copy.deepcopy(payload)

    with pytest.raises(Earth3OperationalAuthorityError, match="formation identity"):
        campaign_from_dict(payload)

    assert payload == before


def test_fog_enabled_production_p3_ai_uses_restricted_view_and_only_approved_routes() -> None:
    state = _normalized_p3()
    state.fog_of_war_enabled = True
    refresh_all_observer_knowledge(state)

    view = build_operational_planning_view(state, Faction.RUSSIA)
    payload = json.loads(view.campaign_payload_json)
    metadata = payload["map_metadata"]
    assert view.fog_of_war_enabled is True
    assert "strategic_actor_runtime" not in metadata
    assert "actor_content_runtime" not in metadata
    assert set(payload["strategic_formations"]) == set(view.visible_subject_keys)

    before_actor_runtime = copy.deepcopy(state.map_metadata["strategic_actor_runtime"])
    before_actor_content = copy.deepcopy(state.map_metadata["actor_content_runtime"])
    actions = plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)

    assert state.map_metadata["strategic_actor_runtime"] == before_actor_runtime
    assert state.map_metadata["actor_content_runtime"] == before_actor_content
    moved = [action for action in actions if action.action == "operational_move"]
    assert moved

    approved_ids = {
        str(edge["edge_id"]) for edge in load_authenticated_p3_graph()["edges"]
    }
    for action in moved:
        formation_id = str(action.details["formation_id"])
        order = state.strategic_formations[formation_id].move_order
        assert order is not None
        assert order.path_edge_ids
        assert set(order.path_edge_ids) <= approved_ids
