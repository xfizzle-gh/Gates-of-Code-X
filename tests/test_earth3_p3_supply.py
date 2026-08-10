from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
import sys
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.models import Faction
from gates_of_codex.earth3_operational import load_authenticated_p3_graph
from gates_of_codex.operational_schema import FormationOperationalPosition, PositionMode
from gates_of_codex.operational_supply import (
    _node_is_supply_transit_legal,
    _routing_graph_indexes,
    assert_supply_edge_hop_legal,
    compute_operational_supply_routes,
    refresh_operational_supply,
    resolve_operational_supply_sources,
)
from gates_of_codex.scenario import build_scenario


EXPECTED_SOURCE_SITES = {
    Faction.NATO: {"site_berlin_command", "site_riga_depot"},
    Faction.UKRAINE: {"site_kyiv_command", "site_odesa_port"},
    Faction.RUSSIA: {"site_rostov_depot"},
}
EXPECTED_FORMATIONS = {
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


def _node(province_id: str) -> str:
    return f"op-node-{province_id}-anchor"


def test_p2_supply_hub_intents_bind_to_authenticated_graph_nodes() -> None:
    state = build_scenario("earth3_v1")
    graph = load_authenticated_p3_graph()
    nodes = {str(row["node_id"]): row for row in graph["nodes"]}

    for faction, expected_site_ids in EXPECTED_SOURCE_SITES.items():
        sources, diagnostics = resolve_operational_supply_sources(state, faction)
        by_id = {source.source_hub_id: source for source in sources}
        assert expected_site_ids <= set(by_id)
        assert not [item for item in diagnostics if item.source_hub_id in expected_site_ids]
        for site_id in expected_site_ids:
            source = by_id[site_id]
            assert source.source_node_id in nodes
            assert nodes[source.source_node_id]["province_id"] == source.province_id


def test_all_eleven_opening_formations_are_connected_to_supply() -> None:
    state = build_scenario("earth3_v1")

    report = refresh_operational_supply(state, consume_grace=False)

    assert report.authoritative is True
    assert set(report.connected) == EXPECTED_FORMATIONS
    assert report.grace == ()
    assert report.cut_off == ()
    for formation_id in EXPECTED_FORMATIONS:
        force = state.strategic_formations[formation_id]
        assert force.supplied is True
        assert force.cut_off is False
        assert force.source_hub_id
        assert force.route_cost is not None and force.route_cost >= 0


def test_neutral_unoccupied_transit_is_legal_but_hostile_transit_is_not() -> None:
    state = build_scenario("earth3_v1")
    graph = load_authenticated_p3_graph()
    nodes, _edges = _routing_graph_indexes(graph)

    neutral_node_id = next(
        node_id
        for node_id, node in sorted(nodes.items())
        if state.provinces[str(node["province_id"])].owner == Faction.NEUTRAL
    )
    node = nodes[neutral_node_id]
    province_id = str(node["province_id"])
    assert _node_is_supply_transit_legal(state, Faction.UKRAINE, node) is True

    hostile_owned = copy.deepcopy(state)
    hostile_owned.provinces[province_id].owner = Faction.RUSSIA
    assert (
        _node_is_supply_transit_legal(hostile_owned, Faction.UKRAINE, node)
        is False
    )

    hostile_occupied = copy.deepcopy(state)
    russian = hostile_occupied.strategic_formations["sf_rus_rostov"]
    russian.position = FormationOperationalPosition(
        mode=PositionMode.AT_NODE.value,
        node_id=neutral_node_id,
        edge_id=None,
        progress_milli=0,
        facing_node_id=None,
    )
    assert (
        _node_is_supply_transit_legal(hostile_occupied, Faction.UKRAINE, node)
        is False
    )


def test_supply_rejects_disabled_candidate_unapproved_and_opted_out_edges() -> None:
    graph = load_authenticated_p3_graph()
    _nodes, edges = _routing_graph_indexes(graph)
    edge = edges[min(edges)]

    assert_supply_edge_hop_legal(edge, origin=edge.a, dest=edge.b)

    with pytest.raises(ValueError):
        assert_supply_edge_hop_legal(
            replace(edge, traversal_enabled=False), origin=edge.a, dest=edge.b
        )
    with pytest.raises(ValueError, match="candidate"):
        assert_supply_edge_hop_legal(
            replace(edge, authority="candidate"), origin=edge.a, dest=edge.b
        )
    blocked_meta = dict(edge.metadata)
    blocked_meta["blocked"] = True
    with pytest.raises(ValueError):
        assert_supply_edge_hop_legal(
            replace(edge, metadata=blocked_meta), origin=edge.a, dest=edge.b
        )
    no_supply = dict(edge.metadata)
    no_supply["supply_capable"] = False
    with pytest.raises(ValueError, match="supply_blocked"):
        assert_supply_edge_hop_legal(
            replace(edge, metadata=no_supply), origin=edge.a, dest=edge.b
        )


def test_supply_routes_are_deterministic_under_repeat_and_graph_reordering() -> None:
    state = build_scenario("earth3_v1")
    first_report = refresh_operational_supply(state, consume_grace=False).to_dict()
    first_projection = {
        key: (
            force.supplied,
            force.cut_off,
            force.source_hub_id,
            force.route_cost,
        )
        for key, force in sorted(state.strategic_formations.items())
    }
    second_report = refresh_operational_supply(state, consume_grace=False).to_dict()
    second_projection = {
        key: (
            force.supplied,
            force.cut_off,
            force.source_hub_id,
            force.route_cost,
        )
        for key, force in sorted(state.strategic_formations.items())
    }
    assert first_report == second_report
    assert first_projection == second_projection

    graph = load_authenticated_p3_graph()
    shuffled = copy.deepcopy(graph)
    shuffled["nodes"] = list(reversed(shuffled["nodes"]))
    shuffled["edges"] = list(reversed(shuffled["edges"]))
    sources, _diagnostics = resolve_operational_supply_sources(state, Faction.UKRAINE)
    normal = compute_operational_supply_routes(state, Faction.UKRAINE, sources)
    with patch(
        "gates_of_codex.operational_supply.load_operational_graph_for_state",
        return_value=shuffled,
    ):
        reordered = compute_operational_supply_routes(
            state, Faction.UKRAINE, sources
        )
    assert normal == reordered


def test_zaporizhzhia_supply_route_uses_only_authenticated_approved_edges() -> None:
    state = build_scenario("earth3_v1")
    graph = load_authenticated_p3_graph()
    approved = {str(edge["edge_id"]) for edge in graph["edges"]}
    sources, _ = resolve_operational_supply_sources(state, Faction.UKRAINE)
    routes = compute_operational_supply_routes(state, Faction.UKRAINE, sources)

    route = routes[_node("e3_1962")]
    assert route.edge_id_path
    assert set(route.edge_id_path) <= approved
    assert all(
        next(edge for edge in graph["edges"] if edge["edge_id"] == edge_id)[
            "metadata"
        ]["supply_capable"]
        is True
        for edge_id in route.edge_id_path
    )
