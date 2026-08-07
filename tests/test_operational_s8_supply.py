from __future__ import annotations

import unittest
from unittest import mock

from gates_of_codex.force_migration import ensure_strategic_formations
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
    OperationalRouteEdge,
    stable_node_id,
)
from gates_of_codex.operational_supply import (
    assert_supply_edge_hop_legal,
    resolve_operational_supply_sources,
)
from gates_of_codex.state_io import campaign_from_dict


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


if __name__ == "__main__":
    unittest.main()
