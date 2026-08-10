from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.earth3_operational import load_authenticated_p3_graph
from gates_of_codex.operational_ai import _build_graph_indexes, find_operational_path
from gates_of_codex.operational_movement import issue_move_order
from gates_of_codex.scenario import build_scenario


STARTING_FORMATIONS = (
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
)
OBJECTIVE_NODES = (
    "op-node-e3_2794-anchor",
    "op-node-e3_3380-anchor",
    "op-node-e3_0442-anchor",
    "op-node-e3_1937-anchor",
)


def _node(province_id: str) -> str:
    return f"op-node-{province_id}-anchor"


def _edge_for_pair(graph: dict, left: str, right: str) -> str:
    wanted = {left, right}
    for edge in graph["edges"]:
        if {str(edge["a"]), str(edge["b"])} == wanted:
            return str(edge["edge_id"])
    raise AssertionError(f"missing reviewed edge {left} <-> {right}")


def _disabled_ids() -> list[str]:
    inventory = json.loads(
        (ROOT / "docs/audits/p3-first-corridor-route-inventory.json").read_text(
            encoding="utf-8"
        )
    )
    return [str(value) for value in inventory["disabled_candidate_edge_ids"]]


def test_every_starting_formation_can_issue_one_approved_hop() -> None:
    state = build_scenario("earth3_v1")
    graph = load_authenticated_p3_graph()
    edges_by_id, _nodes_by_id, adjacency = _build_graph_indexes(graph)

    for formation_id in STARTING_FORMATIONS:
        force = state.strategic_formations[formation_id]
        assert force.position is not None and force.position.node_id
        origin = str(force.position.node_id)
        hops = adjacency.get(origin, [])
        assert hops, formation_id
        hop = hops[0]
        order = issue_move_order(
            state,
            formation_id,
            path_node_ids=[origin, hop.dest],
            path_edge_ids=[hop.edge_id],
            order_id=f"p3-proof-{formation_id}",
        )
        assert order.path_edge_ids == [hop.edge_id]
        assert edges_by_id[hop.edge_id].authority == "approved"
        force.move_order = None


def test_all_starting_nodes_reach_both_p2_objective_clusters_on_allowlisted_edges() -> None:
    state = build_scenario("earth3_v1")
    graph = load_authenticated_p3_graph()
    edges_by_id, _nodes_by_id, adjacency = _build_graph_indexes(graph)
    allowlist = set(edges_by_id)

    for formation_id in STARTING_FORMATIONS:
        force = state.strategic_formations[formation_id]
        assert force.position is not None and force.position.node_id
        for goal in OBJECTIVE_NODES:
            path = find_operational_path(
                start_node=str(force.position.node_id),
                goal_node=goal,
                adjacency=adjacency,
            )
            assert path is not None, (formation_id, goal)
            assert set(path.edge_ids) <= allowlist


def test_ai_pathfinding_is_insertion_order_independent() -> None:
    graph = load_authenticated_p3_graph()
    shuffled = copy.deepcopy(graph)
    shuffled["nodes"] = list(reversed(shuffled["nodes"]))
    shuffled["edges"] = list(reversed(shuffled["edges"]))

    _edges_a, _nodes_a, adjacency_a = _build_graph_indexes(graph)
    _edges_b, _nodes_b, adjacency_b = _build_graph_indexes(shuffled)
    probes = [
        (_node("e3_0513"), _node("e3_3380")),
        (_node("e3_2793"), _node("e3_1937")),
        (_node("e3_0592"), _node("e3_2794")),
    ]
    for start, goal in probes:
        first = find_operational_path(
            start_node=start, goal_node=goal, adjacency=adjacency_a
        )
        second = find_operational_path(
            start_node=start, goal_node=goal, adjacency=adjacency_b
        )
        assert first == second
        assert first is not None


def test_both_reviewed_maneuver_loops_survive_one_edge_block() -> None:
    graph = load_authenticated_p3_graph()
    _edges, _nodes, adjacency = _build_graph_indexes(graph)

    kyiv = _node("e3_1937")
    zap = _node("e3_1962")
    direct_first = _edge_for_pair(graph, kyiv, _node("e3_2808"))
    alternate = find_operational_path(
        start_node=kyiv,
        goal_node=zap,
        adjacency=adjacency,
        forbidden_edges={direct_first},
    )
    assert alternate is not None
    assert direct_first not in alternate.edge_ids
    assert _node("e3_1749") in alternate.node_ids
    assert _node("e3_1208") in alternate.node_ids

    donetsk = _node("e3_3380")
    rostov = _node("e3_2793")
    short_first = _edge_for_pair(graph, donetsk, _node("e3_2794"))
    rear = find_operational_path(
        start_node=donetsk,
        goal_node=rostov,
        adjacency=adjacency,
        forbidden_edges={short_first},
    )
    assert rear is not None
    assert short_first not in rear.edge_ids
    assert _node("e3_1951") in rear.node_ids
    assert _node("e3_3379") in rear.node_ids


def test_all_8690_disabled_candidates_are_absent_and_cannot_be_injected() -> None:
    graph = load_authenticated_p3_graph()
    graph_ids = {str(edge["edge_id"]) for edge in graph["edges"]}
    disabled = _disabled_ids()
    assert len(disabled) == 8690
    assert len(set(disabled)) == 8690
    assert graph_ids.isdisjoint(disabled)

    state = build_scenario("earth3_v1")
    force = state.strategic_formations["sf_usa_tallinn"]
    assert force.position is not None and force.position.node_id
    disabled_id = disabled[0]
    with pytest.raises(ValueError):
        issue_move_order(
            state,
            force.strategic_formation_id,
            path_node_ids=[
                str(force.position.node_id),
                "op-node-e3_0000-anchor",
            ],
            path_edge_ids=[disabled_id],
            order_id="disabled-injection",
        )


def test_polygon_adjacency_never_becomes_a_direct_operational_hop() -> None:
    state = build_scenario("earth3_v1")
    graph = load_authenticated_p3_graph()
    graph_pairs = {
        frozenset((str(edge["a"]), str(edge["b"]))) for edge in graph["edges"]
    }

    chosen: tuple[str, str] | None = None
    for province_id in sorted(state.provinces):
        left = _node(province_id)
        for neighbor in state.provinces[province_id].neighbors:
            right = _node(str(neighbor))
            if left != right and frozenset((left, right)) not in graph_pairs:
                chosen = (left, right)
                break
        if chosen:
            break
    assert chosen is not None

    force = state.strategic_formations["sf_usa_tallinn"]
    # A polygon-neighbor pair has no edge ID in the authenticated graph, so a
    # direct graph order cannot be synthesized from geometry.
    with pytest.raises(ValueError):
        issue_move_order(
            state,
            force.strategic_formation_id,
            path_node_ids=[str(force.position.node_id), chosen[1]],
            path_edge_ids=["op-edge-not-authorized-from-polygon-adjacency"],
            order_id="polygon-fallback-proof",
        )
