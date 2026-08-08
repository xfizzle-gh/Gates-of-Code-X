from __future__ import annotations

from pathlib import Path
import unittest
from unittest import mock

from gates_of_codex.force_migration import ensure_strategic_formations
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.models import (
    Alliance,
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
    Province,
)
from gates_of_codex.operational_schema import (
    EdgeAuthority,
    EdgeKind,
    FormationOperationalPosition,
    OperationalRouteEdge,
    PositionMode,
    stable_node_id,
)
from gates_of_codex.operational_supply import (
    OperationalSupplySource,
    assert_supply_edge_hop_legal,
    compute_operational_supply_routes,
    ensure_operational_supply_state,
    on_edge_attachment_cost,
    refresh_operational_supply,
    resolve_operational_supply_sources,
    route_for_formation,
)
from gates_of_codex.state_io import campaign_from_dict
from gates_of_codex.supply import refresh_supply_for_faction


def _state() -> CampaignState:
    state = CampaignState(
        campaign_name="S8 test",
        factions={"nato": FactionState(Faction.NATO)},
        provinces={"p1": Province("p1", "P1", Faction.NATO)},
        battalions={
            "nato-1": Battalion(
                battalion_id="nato-1",
                faction=Faction.NATO,
                province_id="p1",
                roster=[
                    BattalionRosterEntry(
                        "rifle", quantity=3, category="infantry"
                    )
                ],
            )
        },
    )
    ensure_strategic_formations(state)
    return state


def _only_force(state: CampaignState):
    return next(iter(state.strategic_formations.values()))


def _node(node_id: str, province_id: str) -> dict:
    return {
        "node_id": node_id,
        "display_name": node_id,
        "kind": "anchor",
        "pixel": [0, 0],
        "province_id": province_id,
        "site_id": None,
        "terrain": "unknown",
        "is_hub": False,
        "authority": "authored",
        "metadata": {},
    }


def _graph(*, nodes: list[dict], sites: list[dict] | None = None) -> dict:
    return {
        "schema": "gates-of-codex.operational-graph",
        "schema_version": 2,
        "map_id": "s8-test",
        "rules": {"ticks_per_strategic_turn": 10},
        "sites": list(sites or []),
        "nodes": list(nodes),
        "edges": [],
    }


def _edge_row(
    edge_id: str,
    a: str,
    b: str,
    *,
    cost: int = 1000,
    bidirectional: bool = True,
    enabled: bool = True,
    authority: str = "authored",
    kind: str = "road",
    metadata: dict | None = None,
) -> dict:
    return {
        "edge_id": edge_id,
        "a": a,
        "b": b,
        "kind": kind,
        "authority": authority,
        "length_px": 1,
        "base_move_points_milli": 1000,
        "movement_cost_milli": cost,
        "requires_port": False,
        "can_be_blockaded": False,
        "traversal_enabled": enabled,
        "bidirectional": bidirectional,
        "province_ids": [f"p-{a}", f"p-{b}"],
        "legacy_crossing_type": None,
        "metadata": dict(metadata or {}),
    }


def _routing_state(node_ids: list[str]) -> CampaignState:
    provinces = {
        f"p-{node_id}": Province(
            f"p-{node_id}", f"P {node_id}", Faction.NATO
        )
        for node_id in node_ids
    }
    start_province = f"p-{node_ids[0]}"
    state = CampaignState(
        campaign_name="S8 routing",
        factions={"nato": FactionState(Faction.NATO)},
        provinces=provinces,
        battalions={
            "nato-route": Battalion(
                battalion_id="nato-route",
                faction=Faction.NATO,
                province_id=start_province,
                roster=[BattalionRosterEntry("rifle", quantity=3)],
            )
        },
    )
    ensure_strategic_formations(state)
    _only_force(state).position = FormationOperationalPosition(
        mode=PositionMode.AT_NODE.value,
        node_id=node_ids[0],
    )
    return state


def _routing_graph(node_ids: list[str], edges: list[dict]) -> dict:
    graph = _graph(
        nodes=[_node(node_id, f"p-{node_id}") for node_id in node_ids]
    )
    graph["edges"] = edges
    return graph


def _source(source_id: str, node_id: str) -> OperationalSupplySource:
    return OperationalSupplySource(
        source_hub_id=source_id,
        source_node_id=node_id,
        province_id=f"p-{node_id}",
        eligible_factions=("nato",),
        source_kind="test",
    )


def _lifecycle_state(*, connected: bool) -> tuple[CampaignState, dict]:
    state = _routing_state(["formation", "source"])
    state.provinces["p-source"].metadata["static_supply_source_for"] = [
        "nato"
    ]
    graph = _routing_graph(
        ["formation", "source"],
        [
            _edge_row(
                "route",
                "formation",
                "source",
                enabled=connected,
            )
        ],
    )
    graph["nodes"][1]["node_id"] = stable_node_id("p-source", "anchor")
    graph["edges"][0]["b"] = stable_node_id("p-source", "anchor")
    return state, graph


def _source_by_id(sources, source_hub_id: str):
    return next(item for item in sources if item.source_hub_id == source_hub_id)


def _edge(
    *,
    kind: str = EdgeKind.ROAD.value,
    authority: str = EdgeAuthority.AUTHORED.value,
    enabled: bool = True,
    bidirectional: bool = True,
    metadata: dict | None = None,
) -> OperationalRouteEdge:
    return OperationalRouteEdge(
        edge_id="edge-1",
        a="a",
        b="b",
        kind=kind,
        authority=authority,
        traversal_enabled=enabled,
        bidirectional=bidirectional,
        province_ids=["p1", "p2"],
        metadata=dict(metadata or {}),
    )


class OperationalS8SupplyTests(unittest.TestCase):
    def test_supply_guide_documents_operational_contract(self) -> None:
        guide = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "supply-and-strategic-ai.md"
        ).read_text(encoding="utf-8")

        for phrase in (
            "province-supply-source:<province_id>",
            "one-tick grace",
            "(edge_cost * segment_milli + 999) // 1000",
            "disabled candidate corridors",
            "does not invent coalition-wide logistics",
            "Frontend schema version 13",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, guide)

    def test_s8_fields_round_trip_strictly(self) -> None:
        state = _state()
        state.schema_version = 8
        force = _only_force(state)
        force.supplied = False
        force.cut_off = True
        force.source_hub_id = None
        force.route_cost = None
        force.grace_ticks_remaining = 0
        force.last_supply_refresh_tick = 12
        force.last_supply_refresh_turn = 3
        force.last_grace_consuming_tick = 12

        loaded = campaign_from_dict(state.to_dict())
        restored = _only_force(loaded)

        self.assertFalse(restored.supplied)
        self.assertTrue(restored.cut_off)
        self.assertIsNone(restored.source_hub_id)
        self.assertIsNone(restored.route_cost)
        self.assertEqual(0, restored.grace_ticks_remaining)
        self.assertEqual(12, restored.last_supply_refresh_tick)
        self.assertEqual(3, restored.last_supply_refresh_turn)
        self.assertEqual(12, restored.last_grace_consuming_tick)

    def test_schema7_no_graph_payload_omits_s8_fields(self) -> None:
        state = _state()
        state.schema_version = 7

        row = next(iter(state.to_dict()["strategic_formations"].values()))

        self.assertNotIn("supplied", row)
        self.assertNotIn("cut_off", row)
        self.assertNotIn("source_hub_id", row)
        self.assertNotIn("route_cost", row)
        self.assertNotIn("grace_ticks_remaining", row)
        self.assertNotIn("last_supply_refresh_tick", row)
        self.assertNotIn("last_supply_refresh_turn", row)
        self.assertNotIn("last_grace_consuming_tick", row)

    def test_s8_optional_int_rejects_bool_string_and_float(self) -> None:
        for bad in (True, "1", 1.0):
            with self.subTest(bad=bad):
                state = _state()
                state.schema_version = 8
                payload = state.to_dict()
                row = next(iter(payload["strategic_formations"].values()))
                row["route_cost"] = bad

                with self.assertRaisesRegex(ValueError, "route_cost"):
                    campaign_from_dict(payload)

    def test_s8_source_hub_id_rejects_non_string_values(self) -> None:
        for bad in (7, True, ["hub"]):
            with self.subTest(bad=bad):
                state = _state()
                state.schema_version = 8
                payload = state.to_dict()
                row = next(iter(payload["strategic_formations"].values()))
                row["source_hub_id"] = bad

                with self.assertRaisesRegex(ValueError, "source_hub_id"):
                    campaign_from_dict(payload)

        state = _state()
        _only_force(state).source_hub_id = 7
        with self.assertRaisesRegex(ValueError, "source_hub_id"):
            state.validate()

    def test_authored_source_site_node_precedes_anchor(self) -> None:
        state = _state()
        state.provinces["p1"].metadata["supply_source_for"] = ["nato"]
        anchor_id = stable_node_id("p1", "anchor")
        site = {
            "site_id": "site-source",
            "display_name": "Depot",
            "kind": "depot",
            "province_id": "p1",
            "pixel": [0, 0],
            "route_node_id": "site-node",
            "tags": ["supply_source"],
            "facilities": [],
            "owner_faction": "nato",
            "authority": "authored",
            "metadata": {},
        }
        graph = _graph(
            nodes=[_node(anchor_id, "p1"), _node("site-node", "p1")],
            sites=[site],
        )

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            sources, diagnostics = resolve_operational_supply_sources(
                state, Faction.NATO
            )

        bridged = _source_by_id(sources, "province-supply-source:p1")
        self.assertEqual("site-node", bridged.source_node_id)
        self.assertEqual((), diagnostics)

    def test_constructed_hub_node_precedes_anchor(self) -> None:
        state = _state()
        state.provinces["p1"].metadata.update(
            {
                "infrastructure": {"supply_hub": 1},
                "supply_hub_node_id": "hub-node",
                "supply_source_for": ["nato"],
            }
        )
        anchor_id = stable_node_id("p1", "anchor")
        graph = _graph(
            nodes=[_node(anchor_id, "p1"), _node("hub-node", "p1")]
        )

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            sources, _ = resolve_operational_supply_sources(state, Faction.NATO)

        source = _source_by_id(sources, "constructed-supply-hub:p1")
        self.assertEqual("hub-node", source.source_node_id)

    def test_province_source_falls_back_to_canonical_anchor(self) -> None:
        state = _state()
        state.provinces["p1"].metadata["supply_source_for"] = ["nato"]
        anchor_id = stable_node_id("p1", "anchor")

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=_graph(nodes=[_node(anchor_id, "p1")]),
        ):
            sources, diagnostics = resolve_operational_supply_sources(
                state, Faction.NATO
            )

        self.assertEqual(anchor_id, sources[0].source_node_id)
        self.assertEqual((), diagnostics)

    def test_anchor_alone_does_not_create_source(self) -> None:
        state = _state()
        anchor_id = stable_node_id("p1", "anchor")

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=_graph(nodes=[_node(anchor_id, "p1")]),
        ):
            sources, diagnostics = resolve_operational_supply_sources(
                state, Faction.NATO
            )

        self.assertEqual((), sources)
        self.assertEqual((), diagnostics)

    def test_names_ports_hubs_and_geometry_do_not_infer_sources(self) -> None:
        state = _state()
        state.provinces["p1"].display_name = "Grand Supply Hub Port"
        anchor_id = stable_node_id("p1", "anchor")
        node = _node(anchor_id, "p1")
        node["is_hub"] = True
        site = {
            "site_id": "plain-port",
            "display_name": "Supply Depot by Name Only",
            "kind": "port",
            "province_id": "p1",
            "pixel": [99, 99],
            "route_node_id": anchor_id,
            "tags": [],
            "facilities": [],
            "owner_faction": "nato",
            "authority": "authored",
            "metadata": {},
        }

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=_graph(nodes=[node], sites=[site]),
        ):
            sources, _ = resolve_operational_supply_sources(state, Faction.NATO)

        self.assertEqual((), sources)

    def test_two_sources_sharing_anchor_retain_distinct_ids(self) -> None:
        state = _state()
        state.provinces["p1"].metadata["supply_source_for"] = ["nato"]
        anchor_id = stable_node_id("p1", "anchor")
        site = {
            "site_id": "site-source",
            "display_name": "Depot",
            "kind": "depot",
            "province_id": "p1",
            "pixel": [0, 0],
            "route_node_id": anchor_id,
            "tags": ["supply_source"],
            "facilities": [],
            "owner_faction": "nato",
            "authority": "authored",
            "metadata": {},
        }

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=_graph(nodes=[_node(anchor_id, "p1")], sites=[site]),
        ):
            sources, _ = resolve_operational_supply_sources(state, Faction.NATO)

        self.assertEqual(
            {"province-supply-source:p1", "site-source"},
            {item.source_hub_id for item in sources},
        )
        self.assertEqual({anchor_id}, {item.source_node_id for item in sources})

    def test_source_selection_is_insertion_order_independent(self) -> None:
        left = _state()
        right = _state()
        left.provinces["p1"].metadata["static_supply_source_for"] = ["nato"]
        right.provinces["p1"].metadata["static_supply_source_for"] = ["nato"]
        anchor_id = stable_node_id("p1", "anchor")
        nodes = [_node(anchor_id, "p1"), _node("z-node", "p1")]

        snapshots = []
        for state, ordered in ((left, nodes), (right, list(reversed(nodes)))):
            with mock.patch(
                "gates_of_codex.operational_supply.load_operational_graph_for_state",
                return_value=_graph(nodes=ordered),
            ):
                sources, diagnostics = resolve_operational_supply_sources(
                    state, Faction.NATO
                )
            snapshots.append((sources, diagnostics))

        self.assertEqual(snapshots[0], snapshots[1])

    def test_hostile_control_disables_source(self) -> None:
        state = _state()
        state.provinces["p1"].owner = Faction.RUSSIA
        state.provinces["p1"].metadata["supply_source_for"] = ["nato"]
        anchor_id = stable_node_id("p1", "anchor")

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=_graph(nodes=[_node(anchor_id, "p1")]),
        ):
            sources, _ = resolve_operational_supply_sources(state, Faction.NATO)

        self.assertEqual((), sources)

    def test_hostile_site_control_disables_source_on_next_refresh(self) -> None:
        state, graph = _lifecycle_state(connected=True)
        state.provinces["p-source"].metadata.pop(
            "static_supply_source_for", None
        )
        source_node = stable_node_id("p-source", "anchor")
        graph["sites"] = [
            {
                "site_id": "authored-depot",
                "display_name": "Authored depot",
                "kind": "depot",
                "province_id": "p-source",
                "route_node_id": source_node,
                "owner_faction": "nato",
                "metadata": {},
            }
        ]
        control = {
            "authored-depot": {
                "controller_faction": "nato",
                "province_id": "p-source",
                "route_node_id": source_node,
            }
        }
        state.map_metadata["operational_site_control"] = control

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            refresh_operational_supply(state, consume_grace=False)
            self.assertEqual("authored-depot", _only_force(state).source_hub_id)
            control["authored-depot"]["controller_faction"] = "rusa"
            before = {
                key: dict(value) for key, value in control.items()
            }
            refresh_operational_supply(
                state, consume_grace=True, completed_tick=1
            )

        force = _only_force(state)
        self.assertIsNone(force.source_hub_id)
        self.assertEqual(1, force.grace_ticks_remaining)
        self.assertEqual(before, state.map_metadata["operational_site_control"])

    def test_missing_anchor_fails_closed_with_diagnostic(self) -> None:
        state = _state()
        state.provinces["p1"].metadata["supply_source_for"] = ["nato"]

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=_graph(nodes=[]),
        ):
            sources, diagnostics = resolve_operational_supply_sources(
                state, Faction.NATO
            )

        self.assertEqual((), sources)
        self.assertEqual("province-supply-source:p1", diagnostics[0].source_hub_id)
        self.assertEqual("missing_anchor", diagnostics[0].reason)

    def test_allied_source_sharing_matches_existing_supply_model(self) -> None:
        state = _state()
        state.factions["ukr"] = FactionState(Faction.UKRAINE)
        state.alliances["western"] = Alliance(
            alliance_id="western",
            display_name="Western",
            factions=[Faction.NATO, Faction.UKRAINE],
        )
        state.provinces["p1"].owner = Faction.UKRAINE
        state.provinces["p1"].metadata["supply_source_for"] = ["ukr"]
        anchor_id = stable_node_id("p1", "anchor")

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=_graph(nodes=[_node(anchor_id, "p1")]),
        ):
            sources, _ = resolve_operational_supply_sources(state, Faction.NATO)

        self.assertEqual(("province-supply-source:p1",), tuple(
            item.source_hub_id for item in sources
        ))

    def test_supply_edge_requires_shared_traversal_eligibility(self) -> None:
        cases = (
            (_edge(enabled=False), "invalid_path"),
            (_edge(authority=EdgeAuthority.CANDIDATE.value), "candidate_edge"),
            (_edge(metadata={"blocked": True}), "metadata_blocked"),
        )
        for edge, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                assert_supply_edge_hop_legal(edge, origin="a", dest="b")

    def test_supply_edge_respects_one_way_direction(self) -> None:
        edge = _edge(bidirectional=False)
        assert_supply_edge_hop_legal(edge, origin="a", dest="b")
        with self.assertRaisesRegex(ValueError, "one_way_reverse"):
            assert_supply_edge_hop_legal(edge, origin="b", dest="a")

    def test_ferry_and_sea_edges_require_explicit_supply_capable(self) -> None:
        for kind in (
            EdgeKind.FERRY.value,
            EdgeKind.FERRY_OR_SEA_LANE.value,
            EdgeKind.SEA_LANE.value,
        ):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, "supply_opt_in_required"):
                    assert_supply_edge_hop_legal(
                        _edge(kind=kind), origin="a", dest="b"
                    )
                assert_supply_edge_hop_legal(
                    _edge(kind=kind, metadata={"supply_capable": True}),
                    origin="a",
                    dest="b",
                )

    def test_land_edge_is_supply_capable_by_default(self) -> None:
        assert_supply_edge_hop_legal(_edge(), origin="a", dest="b")

    def test_connected_formation_gets_lowest_integer_route(self) -> None:
        nodes = ["formation", "middle", "hub"]
        state = _routing_state(nodes)
        graph = _routing_graph(
            nodes,
            [
                _edge_row("edge-1", "formation", "middle", cost=1000),
                _edge_row("edge-2", "middle", "hub", cost=750),
            ],
        )

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            routes = compute_operational_supply_routes(
                state, Faction.NATO, (_source("hub-source", "hub"),)
            )
            route = route_for_formation(state, _only_force(state), routes)

        self.assertIsNotNone(route)
        self.assertEqual(1750, route.route_cost)
        self.assertEqual(("formation", "middle", "hub"), route.node_id_path)
        self.assertEqual(("edge-1", "edge-2"), route.edge_id_path)
        self.assertEqual("hub-source", route.source_hub_id)

    def test_equal_cost_route_selection_is_insertion_order_independent(self) -> None:
        nodes = ["formation", "node-a", "node-b", "hub"]
        edges = [
            _edge_row("edge-z", "formation", "node-b"),
            _edge_row("edge-z2", "node-b", "hub"),
            _edge_row("edge-a", "formation", "node-a"),
            _edge_row("edge-a2", "node-a", "hub"),
        ]
        snapshots = []
        for ordered_nodes, ordered_edges in (
            (nodes, edges),
            (list(reversed(nodes)), list(reversed(edges))),
        ):
            state = _routing_state(nodes)
            graph = _routing_graph(ordered_nodes, ordered_edges)
            with mock.patch(
                "gates_of_codex.operational_supply.load_operational_graph_for_state",
                return_value=graph,
            ):
                routes = compute_operational_supply_routes(
                    state, Faction.NATO, (_source("hub-source", "hub"),)
                )
                route = route_for_formation(state, _only_force(state), routes)
            snapshots.append(route)

        self.assertEqual(snapshots[0], snapshots[1])
        self.assertEqual(
            ("formation", "node-a", "hub"), snapshots[0].node_id_path
        )

    def test_reverse_search_preserves_one_way_gameplay_direction(self) -> None:
        nodes = ["formation", "hub"]
        outcomes = []
        for a, b in (("formation", "hub"), ("hub", "formation")):
            state = _routing_state(nodes)
            graph = _routing_graph(
                nodes,
                [_edge_row("one-way", a, b, bidirectional=False)],
            )
            with mock.patch(
                "gates_of_codex.operational_supply.load_operational_graph_for_state",
                return_value=graph,
            ):
                routes = compute_operational_supply_routes(
                    state, Faction.NATO, (_source("hub-source", "hub"),)
                )
                outcomes.append(
                    route_for_formation(state, _only_force(state), routes)
                )

        self.assertIsNotNone(outcomes[0])
        self.assertIsNone(outcomes[1])

    def test_on_edge_fixed_point_cost_rounds_up_exactly(self) -> None:
        self.assertEqual(333, on_edge_attachment_cost(1000, 333))
        self.assertEqual(500, on_edge_attachment_cost(1000, 500))
        self.assertEqual(0, on_edge_attachment_cost(1000, 0))
        self.assertEqual(667, on_edge_attachment_cost(1001, 666))

    def test_on_edge_uses_sole_reachable_endpoint(self) -> None:
        nodes = ["left", "right", "hub"]
        state = _routing_state(nodes)
        _only_force(state).position = FormationOperationalPosition(
            mode=PositionMode.ON_EDGE.value,
            edge_id="occupied",
            progress_milli=500,
            facing_node_id="right",
        )
        graph = _routing_graph(
            nodes,
            [
                _edge_row(
                    "occupied", "left", "right", bidirectional=False
                ),
                _edge_row("to-hub", "right", "hub"),
            ],
        )

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            routes = compute_operational_supply_routes(
                state, Faction.NATO, (_source("right-source", "hub"),)
            )
            route = route_for_formation(state, _only_force(state), routes)

        self.assertIsNotNone(route)
        self.assertEqual("right-source", route.source_hub_id)
        self.assertEqual(("right", "hub"), route.node_id_path)

    def test_on_edge_chooses_lower_total_endpoint_cost(self) -> None:
        nodes = ["left", "right", "left-hub", "right-hub"]
        state = _routing_state(nodes)
        _only_force(state).position = FormationOperationalPosition(
            mode=PositionMode.ON_EDGE.value,
            edge_id="occupied",
            progress_milli=500,
            facing_node_id="right",
        )
        graph = _routing_graph(
            nodes,
            [
                _edge_row("occupied", "left", "right", cost=1000),
                _edge_row("left-route", "left", "left-hub", cost=2000),
                _edge_row("right-route", "right", "right-hub", cost=500),
            ],
        )

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            routes = compute_operational_supply_routes(
                state,
                Faction.NATO,
                (
                    _source("left-source", "left-hub"),
                    _source("right-source", "right-hub"),
                ),
            )
            route = route_for_formation(state, _only_force(state), routes)

        self.assertIsNotNone(route)
        self.assertEqual("right-source", route.source_hub_id)
        self.assertEqual(1000, route.route_cost)

    def test_on_edge_equal_cost_uses_stable_node_then_edge_then_source(self) -> None:
        nodes = ["left", "right", "left-hub", "right-hub"]
        state = _routing_state(nodes)
        _only_force(state).position = FormationOperationalPosition(
            mode=PositionMode.ON_EDGE.value,
            edge_id="occupied",
            progress_milli=500,
            facing_node_id="right",
        )
        graph = _routing_graph(
            nodes,
            [
                _edge_row("occupied", "left", "right"),
                _edge_row("z-left", "left", "left-hub"),
                _edge_row("a-right", "right", "right-hub"),
            ],
        )

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            routes = compute_operational_supply_routes(
                state,
                Faction.NATO,
                (
                    _source("left-source", "left-hub"),
                    _source("right-source", "right-hub"),
                ),
            )
            route = route_for_formation(state, _only_force(state), routes)

        self.assertEqual("left-source", route.source_hub_id)
        self.assertEqual("left", route.node_id_path[0])

    def test_malformed_edge_reference_fails_closed(self) -> None:
        nodes = ["formation", "hub"]
        state = _routing_state(nodes)
        graph = _routing_graph(
            nodes,
            [_edge_row("broken", "formation", "missing")],
        )

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            routes = compute_operational_supply_routes(
                state, Faction.NATO, (_source("hub-source", "hub"),)
            )

        self.assertNotIn("formation", routes)

    def test_non_integer_edge_cost_fails_closed(self) -> None:
        nodes = ["formation", "hub"]
        state = _routing_state(nodes)
        edge = _edge_row("coerced", "formation", "hub")
        edge["movement_cost_milli"] = "1000"
        graph = _routing_graph(nodes, [edge])

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            routes = compute_operational_supply_routes(
                state, Faction.NATO, (_source("hub-source", "hub"),)
            )

        self.assertNotIn("formation", routes)

    def test_unresolved_formation_position_has_no_route(self) -> None:
        nodes = ["formation", "hub"]
        state = _routing_state(nodes)
        _only_force(state).position = None
        graph = _routing_graph(nodes, [])

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            routes = compute_operational_supply_routes(
                state, Faction.NATO, (_source("hub-source", "hub"),)
            )
            route = route_for_formation(state, _only_force(state), routes)

        self.assertIsNone(route)

    def test_first_disconnected_tick_enters_persisted_grace(self) -> None:
        state, graph = _lifecycle_state(connected=True)
        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            refresh_operational_supply(state, consume_grace=False)
            graph["edges"][0]["traversal_enabled"] = False
            refresh_operational_supply(
                state, consume_grace=True, completed_tick=1
            )

        force = _only_force(state)
        self.assertTrue(force.supplied)
        self.assertFalse(force.cut_off)
        self.assertIsNone(force.source_hub_id)
        self.assertIsNone(force.route_cost)
        self.assertEqual(1, force.grace_ticks_remaining)
        self.assertEqual(1, force.last_grace_consuming_tick)

    def test_next_disconnected_tick_becomes_cut_off(self) -> None:
        state, graph = _lifecycle_state(connected=False)
        force = _only_force(state)
        force.grace_ticks_remaining = 1
        force.last_grace_consuming_tick = 1
        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            refresh_operational_supply(
                state, consume_grace=True, completed_tick=2
            )

        self.assertFalse(force.supplied)
        self.assertTrue(force.cut_off)
        self.assertEqual(0, force.grace_ticks_remaining)
        self.assertEqual(2, force.last_grace_consuming_tick)

    def test_duplicate_tick_refresh_does_not_consume_grace_twice(self) -> None:
        state, graph = _lifecycle_state(connected=False)
        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            refresh_operational_supply(
                state, consume_grace=True, completed_tick=4
            )
            refresh_operational_supply(
                state, consume_grace=True, completed_tick=4
            )

        force = _only_force(state)
        self.assertTrue(force.supplied)
        self.assertFalse(force.cut_off)
        self.assertEqual(1, force.grace_ticks_remaining)

    def test_post_load_recompute_preserves_grace(self) -> None:
        state, graph = _lifecycle_state(connected=False)
        state.schema_version = 8
        force = _only_force(state)
        force.supplied = True
        force.cut_off = False
        force.grace_ticks_remaining = 1
        force.last_grace_consuming_tick = 7
        with mock.patch(
            "gates_of_codex.operational_position.load_operational_graph_for_state",
            return_value=graph,
        ), mock.patch(
            "gates_of_codex.operational_capture.load_operational_graph_for_state",
            return_value=graph,
        ), mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            loaded = campaign_from_dict(state.to_dict())

        restored = _only_force(loaded)
        self.assertTrue(restored.supplied)
        self.assertFalse(restored.cut_off)
        self.assertEqual(1, restored.grace_ticks_remaining)
        self.assertEqual(7, restored.last_grace_consuming_tick)

    def test_restored_route_clears_cutoff_and_grace_immediately(self) -> None:
        state, graph = _lifecycle_state(connected=True)
        force = _only_force(state)
        force.supplied = False
        force.cut_off = True
        force.grace_ticks_remaining = 0
        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            refresh_operational_supply(state, consume_grace=False)

        self.assertTrue(force.supplied)
        self.assertFalse(force.cut_off)
        self.assertEqual(0, force.grace_ticks_remaining)
        self.assertEqual("province-supply-source:p-source", force.source_hub_id)

    def test_no_graph_supply_state_is_not_migrated(self) -> None:
        state = _state()
        before_schema = state.schema_version
        before_metadata = dict(state.map_metadata)

        result = ensure_operational_supply_state(state)

        self.assertFalse(result["graph_loaded"])
        self.assertEqual(before_schema, state.schema_version)
        self.assertEqual(before_metadata, state.map_metadata)

    def test_operational_tick_refreshes_once_after_capture(self) -> None:
        from gates_of_codex.operational_movement import advance_operational_tick

        state, graph = _lifecycle_state(connected=False)
        events: list[str] = []

        def capture_side_effect(_state):
            events.append("capture")
            return {"advanced": True}

        def supply_side_effect(_state, *, consume_grace, completed_tick):
            self.assertTrue(consume_grace)
            self.assertEqual(1, completed_tick)
            events.append("supply")
            return mock.Mock(to_dict=lambda: {"authoritative": True})

        with mock.patch(
            "gates_of_codex.operational_movement.load_operational_graph_for_state",
            return_value=graph,
        ), mock.patch(
            "gates_of_codex.operational_capture.advance_site_capture",
            side_effect=capture_side_effect,
        ), mock.patch(
            "gates_of_codex.operational_supply.refresh_operational_supply",
            side_effect=supply_side_effect,
        ) as refresh:
            report = advance_operational_tick(state)

        self.assertEqual(["capture", "supply"], events)
        self.assertEqual(1, refresh.call_count)
        self.assertEqual({"authoritative": True}, report["supply"])

    def test_cut_off_formation_uses_existing_supply_drain_once(self) -> None:
        state, graph = _lifecycle_state(connected=False)
        force = _only_force(state)
        force.supplied = False
        force.cut_off = True
        battalion = state.battalions["nato-route"]
        battalion.supply = 100

        with mock.patch(
            "gates_of_codex.supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            refresh_supply_for_faction(state, Faction.NATO)

        self.assertEqual(75, battalion.supply)
        self.assertEqual(1, battalion.encircled_turns)

    def test_grace_formation_uses_existing_supply_restore_once(self) -> None:
        state, graph = _lifecycle_state(connected=False)
        force = _only_force(state)
        force.supplied = True
        force.cut_off = False
        force.grace_ticks_remaining = 1
        battalion = state.battalions["nato-route"]
        battalion.supply = 50

        with mock.patch(
            "gates_of_codex.supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            refresh_supply_for_faction(state, Faction.NATO)

        self.assertEqual(70, battalion.supply)
        self.assertEqual(0, battalion.encircled_turns)

    def test_no_graph_supply_report_and_serialization_are_unchanged(self) -> None:
        expected = _state()
        actual = _state()
        expected_payload = expected.to_dict()
        expected_report = refresh_supply_for_faction(expected, Faction.NATO)

        ensure_operational_supply_state(actual)
        actual_report = refresh_supply_for_faction(actual, Faction.NATO)

        self.assertEqual(expected_report, actual_report)
        self.assertEqual(
            expected_payload["schema_version"], actual.to_dict()["schema_version"]
        )

    def test_frontend_exports_thin_operational_supply_summary(self) -> None:
        state, graph = _lifecycle_state(connected=False)
        force = _only_force(state)
        force.supplied = False
        force.cut_off = True
        force.source_hub_id = None
        force.route_cost = None

        with mock.patch(
            "gates_of_codex.operational_position.load_operational_graph_for_state",
            return_value=graph,
        ), mock.patch(
            "gates_of_codex.operational_capture.load_operational_graph_for_state",
            return_value=graph,
        ), mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ), mock.patch(
            "gates_of_codex.supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            snapshot = build_frontend_snapshot(state)

        exported_force = snapshot["strategic_formations"][0]
        exported_battalion = snapshot["battalions"][0]
        self.assertEqual(13, snapshot["schema_version"])
        self.assertFalse(exported_force["supplied"])
        self.assertTrue(exported_force["cut_off"])
        self.assertIsNone(exported_force["source_hub_id"])
        self.assertNotIn("route_cost", exported_force)
        self.assertNotIn("grace_ticks_remaining", exported_force)
        self.assertFalse(exported_battalion["is_in_supply"])


if __name__ == "__main__":
    unittest.main()
