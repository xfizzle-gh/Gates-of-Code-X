from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.earth3_bootstrap import build_earth3_v1_campaign
from gates_of_codex.earth3_operational import (
    P3_AUTHORITY_METADATA_KEY,
    load_authenticated_p3_graph,
    validate_earth3_p3_campaign_extension,
)
from gates_of_codex.scenario import build_scenario, get_scenario


STARTING_FORMATIONS = {
    "sf_deu_berlin": "e3_0592",
    "sf_pol_vilnius": "e3_0442",
    "sf_rus_donetsk": "e3_3380",
    "sf_rus_luhansk": "e3_2794",
    "sf_rus_rostov": "e3_2793",
    "sf_ukr_kherson": "e3_1208",
    "sf_ukr_kyiv": "e3_1937",
    "sf_ukr_odesa": "e3_1749",
    "sf_ukr_zaporizhzhia": "e3_1962",
    "sf_usa_riga": "e3_0504",
    "sf_usa_tallinn": "e3_0513",
}


def _node(province_id: str) -> str:
    return f"op-node-{province_id}-anchor"


def _edge_pairs(graph: dict) -> dict[frozenset[str], str]:
    return {
        frozenset((str(edge["a"]), str(edge["b"]))): str(edge["edge_id"])
        for edge in graph["edges"]
    }


def _assert_route(graph: dict, province_ids: list[str]) -> None:
    pairs = _edge_pairs(graph)
    for left, right in zip(province_ids, province_ids[1:]):
        assert frozenset((_node(left), _node(right))) in pairs


def test_direct_p2_builder_remains_p2_only_while_production_build_is_p3() -> None:
    p2 = build_earth3_v1_campaign()
    p3 = build_scenario("earth3_v1")

    assert P3_AUTHORITY_METADATA_KEY not in p2.map_metadata
    assert p2.map_metadata["operational_graph"] is None
    assert p2.map_metadata["operational_maneuver_enabled"] is False
    assert P3_AUTHORITY_METADATA_KEY in p3.map_metadata
    assert p3.map_metadata["operational_maneuver_enabled"] is True
    validate_earth3_p3_campaign_extension(p3)

    assert set(p2.strategic_formations) == set(p3.strategic_formations) == set(
        STARTING_FORMATIONS
    )
    for formation_id, province_id in STARTING_FORMATIONS.items():
        before = p2.strategic_formations[formation_id]
        after = p3.strategic_formations[formation_id]
        assert before.province_id == after.province_id == province_id
        assert before.faction == after.faction
        assert before.actor_id == after.actor_id
        assert before.battalion_ids == after.battalion_ids
        assert before.template_formation_id == after.template_formation_id
        assert after.position is not None
        assert after.position.node_id == _node(province_id)

    assert p2.map_metadata["earth3_p2_site_intents"] == p3.map_metadata[
        "earth3_p2_site_intents"
    ]
    assert {
        key: (value.owner.value, value.metadata.get("owner_actor_id"))
        for key, value in p2.provinces.items()
    } == {
        key: (value.owner.value, value.metadata.get("owner_actor_id"))
        for key, value in p3.provinces.items()
    }


def test_production_registry_declares_p3_authority_assets() -> None:
    definition = get_scenario("earth3_v1")
    required = set(definition.required_asset_authority)
    assert "config/earth3/p3_operational_authority.json" in required
    assert (
        "godot/assets/maps/earth3_europe_mediterranean/p3_authority/"
        "p3_operational_graph.json"
    ) in required


def test_approved_graph_connects_every_start_and_preserves_reviewed_route_shape() -> None:
    graph = load_authenticated_p3_graph()
    assert len(graph["nodes"]) == 64
    assert len(graph["edges"]) == 65
    assert all(edge["authority"] == "approved" for edge in graph["edges"])
    assert all(edge["traversal_enabled"] is True for edge in graph["edges"])

    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in graph["edges"]:
        a, b = str(edge["a"]), str(edge["b"])
        adjacency[a].add(b)
        adjacency[b].add(a)
    node_ids = {str(node["node_id"]) for node in graph["nodes"]}
    start = min(node_ids)
    seen = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for neighbor in sorted(adjacency[current]):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    assert seen == node_ids

    for province_id in STARTING_FORMATIONS.values():
        assert _node(province_id) in node_ids
        assert adjacency[_node(province_id)]

    # Kyiv -> Zaporizhzhia has two reviewed arms.
    _assert_route(
        graph,
        [
            "e3_1937",
            "e3_2808",
            "e3_2809",
            "e3_2810",
            "e3_2800",
            "e3_1961",
            "e3_1962",
        ],
    )
    _assert_route(
        graph,
        [
            "e3_1937",
            "e3_1944",
            "e3_2062",
            "e3_2331",
            "e3_2330",
            "e3_1947",
            "e3_1936",
            "e3_1749",
            "e3_3480",
            "e3_1876",
            "e3_1208",
            "e3_1209",
            "e3_1943",
            "e3_1747",
            "e3_1962",
        ],
    )

    # Donetsk -> Rostov likewise has a short Luhansk arm and a rear-area arm.
    _assert_route(graph, ["e3_3380", "e3_2794", "e3_2793"])
    _assert_route(graph, ["e3_3380", "e3_1951", "e3_3379", "e3_2793"])

    # The deliberate opening battle approach is exactly three approved hops.
    _assert_route(graph, ["e3_1962", "e3_2795", "e3_2796", "e3_3380"])


def test_legacy_polygon_move_remains_blocked_for_production_p3() -> None:
    state = build_scenario("earth3_v1")
    force = state.strategic_formations["sf_usa_tallinn"]
    battalion_id = force.battalion_ids[0]
    polygon_neighbor = state.provinces[force.province_id].neighbors[0]

    with pytest.raises(ValueError, match="operational movement and attack are unavailable"):
        CampaignEngine(state).move_or_attack(battalion_id, polygon_neighbor)
