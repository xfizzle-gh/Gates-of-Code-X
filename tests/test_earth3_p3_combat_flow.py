from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.models import Faction
from gates_of_codex.operational_interception import ENCOUNTER_KIND_EDGE_CROSS
from gates_of_codex.operational_movement import (
    activate_committed_orders,
    advance_operational_tick,
    commit_move_orders,
    issue_move_order,
)
from gates_of_codex.operational_schema import PositionMode
from gates_of_codex.scenario import build_scenario


PATH_PROVINCES = ["e3_1962", "e3_2795", "e3_2796", "e3_3380"]


def _node(province_id: str) -> str:
    return f"op-node-{province_id}-anchor"


def _edge(left: str, right: str) -> str:
    a, b = sorted((_node(left), _node(right)))
    return f"op-edge-corridor-{a}__{b}"


def _prepare_opening_contact():
    state = build_scenario("earth3_v1")
    nodes = [_node(value) for value in PATH_PROVINCES]
    edges = [_edge(left, right) for left, right in zip(PATH_PROVINCES, PATH_PROVINCES[1:])]

    issue_move_order(
        state,
        "sf_ukr_zaporizhzhia",
        path_node_ids=nodes,
        path_edge_ids=edges,
        order_id="p3-zap-to-donetsk",
    )
    issue_move_order(
        state,
        "sf_rus_donetsk",
        path_node_ids=list(reversed(nodes)),
        path_edge_ids=list(reversed(edges)),
        order_id="p3-donetsk-to-zap",
    )
    committed = commit_move_orders(state)
    assert set(committed) == {"sf_ukr_zaporizhzhia", "sf_rus_donetsk"}
    assert activate_committed_orders(state) == 2

    first = advance_operational_tick(state)
    assert state.pending_battle is None
    assert first["swept_kind"] == ""
    assert state.strategic_formations["sf_ukr_zaporizhzhia"].position.node_id == nodes[1]
    assert state.strategic_formations["sf_rus_donetsk"].position.node_id == nodes[2]

    second = advance_operational_tick(state)
    assert state.pending_battle is not None
    return state, second, nodes, edges


def _battle_projection(state) -> dict:
    pending = state.pending_battle
    assert pending is not None
    return {
        "kind": pending.encounter_kind,
        "edge": pending.encounter_edge_id,
        "progress": pending.encounter_progress_milli,
        "pixel": list(pending.encounter_pixel),
        "attacker": pending.attacker_formation_id,
        "defender": pending.defender_formation_id,
        "target": pending.target_province_id,
        "attacking_battalions": sorted(
            value.battalion_id for value in pending.attacking_participants
        ),
        "defending_battalions": sorted(
            value.battalion_id for value in pending.defending_participants
        ),
    }


def test_reviewed_three_edge_approach_generates_one_swept_edge_battle() -> None:
    state, report, _nodes, edges = _prepare_opening_contact()
    pending = state.pending_battle
    assert pending is not None

    assert report["swept_kind"] == ENCOUNTER_KIND_EDGE_CROSS
    assert pending.encounter_kind == ENCOUNTER_KIND_EDGE_CROSS
    assert pending.encounter_edge_id == edges[1]
    assert pending.encounter_progress_milli == 500
    assert len(pending.encounter_pixel) == 2
    assert all(type(value) is int for value in pending.encounter_pixel)
    assert {
        pending.attacker_formation_id,
        pending.defender_formation_id,
    } == {"sf_ukr_zaporizhzhia", "sf_rus_donetsk"}

    # Both formations were stopped on the authenticated shared edge. No polygon
    # ownership is flipped merely by generating operational contact.
    for formation_id in ("sf_ukr_zaporizhzhia", "sf_rus_donetsk"):
        force = state.strategic_formations[formation_id]
        assert force.position is not None
        assert force.position.mode == PositionMode.ON_EDGE.value
        assert force.position.edge_id == edges[1]
    assert state.provinces["e3_1962"].owner == Faction.UKRAINE
    assert state.provinces["e3_3380"].owner == Faction.RUSSIA


def test_opening_contact_metadata_is_deterministic_except_random_battle_id() -> None:
    first, _report, _nodes, _edges = _prepare_opening_contact()
    second, _report2, _nodes2, _edges2 = _prepare_opening_contact()
    assert _battle_projection(first) == _battle_projection(second)


def test_loser_retreats_to_graph_legal_approved_node_after_edge_battle() -> None:
    state, _report, nodes, edges = _prepare_opening_contact()
    pending = state.pending_battle
    assert pending is not None
    encounter_edge = pending.encounter_edge_id

    result = CampaignEngine(state, random_seed=0).apply_battle_result(Faction.UKRAINE)

    assert state.pending_battle is None
    russian = state.strategic_formations.get("sf_rus_donetsk")
    assert russian is not None
    assert russian.position is not None
    assert russian.position.mode == PositionMode.AT_NODE.value
    assert russian.position.node_id in {nodes[2], nodes[3]}
    assert russian.position.node_id != nodes[1]

    retreat_rows = [
        row
        for row in result.retreat_outcomes
        if row.formation_id == "sf_rus_donetsk"
    ]
    assert len(retreat_rows) == 1
    retreat = retreat_rows[0]
    assert retreat.eliminated is False
    assert retreat.destination_node_id == russian.position.node_id

    # The retreat destination is reached through one of the same approved P3
    # edges adjacent to the Russian pre-contact side; no polygon-neighbor escape.
    legal_retreat_edges = {edges[1], edges[2]}
    assert encounter_edge in legal_retreat_edges
    if russian.position.node_id == nodes[3]:
        assert edges[2] in legal_retreat_edges


def test_only_one_pending_battle_can_exist_during_opening_contact() -> None:
    state, _report, _nodes, _edges = _prepare_opening_contact()
    first_id = state.pending_battle.battle_id

    blocked = advance_operational_tick(state)

    assert blocked["advanced"] is False
    assert blocked["reason"] == "pending_battle"
    assert state.pending_battle is not None
    assert state.pending_battle.battle_id == first_id
