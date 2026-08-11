from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from gates_of_codex.force_migration import ensure_strategic_formations
from gates_of_codex.cli import main as cli_main
from gates_of_codex.campaign import CampaignEngine
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
    _routing_graph_indexes,
    assert_supply_edge_hop_legal,
    compute_operational_supply_routes,
    edge_is_supply_capable,
    ensure_operational_supply_state,
    on_edge_attachment_cost,
    refresh_operational_supply,
    resolve_operational_supply_sources,
    route_for_formation,
)
from gates_of_codex.state_io import (
    campaign_from_dict,
    load_campaign,
    save_campaign,
)
from gates_of_codex.strategic import sync_province_infrastructure_owner
from gates_of_codex.supply import (
    refresh_supply_for_faction,
    supply_status_for_faction,
)


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


def _supply_site(
    site_id: str,
    node_id: str,
    *,
    province_id: str = "p1",
    owner: str = "nato",
    authority: str | None = "authored",
    disabled: bool = False,
) -> dict:
    site = {
        "site_id": site_id,
        "display_name": site_id,
        "kind": "depot",
        "province_id": province_id,
        "pixel": [0, 0],
        "route_node_id": node_id,
        "tags": ["supply_source"],
        "facilities": [],
        "owner_faction": owner,
        "metadata": {"disabled": True} if disabled else {},
    }
    if authority is not None:
        site["authority"] = authority
    return site


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
            "Frontend schema version 14",
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

    def test_only_four_operational_supply_state_shapes_are_valid(self) -> None:
        allowed = {
            (True, False, True, True, 0),
            (True, False, False, False, 0),
            (True, False, False, False, 1),
            (False, True, False, False, 0),
        }
        for supplied in (False, True):
            for cut_off in (False, True):
                for has_source in (False, True):
                    for has_cost in (False, True):
                        for grace in (0, 1):
                            shape = (
                                supplied,
                                cut_off,
                                has_source,
                                has_cost,
                                grace,
                            )
                            state = _state()
                            force = _only_force(state)
                            force.supplied = supplied
                            force.cut_off = cut_off
                            force.source_hub_id = "hub" if has_source else None
                            force.route_cost = 10 if has_cost else None
                            force.grace_ticks_remaining = grace
                            with self.subTest(shape=shape):
                                if shape in allowed:
                                    state.validate()
                                else:
                                    with self.assertRaisesRegex(
                                        ValueError,
                                        "invalid_operational_supply_state",
                                    ):
                                        state.validate()

    def test_invalid_persisted_supply_shape_is_rejected_before_recompute(self) -> None:
        state, graph = _lifecycle_state(connected=True)
        state.schema_version = 8
        payload = state.to_dict()
        row = next(iter(payload["strategic_formations"].values()))
        row.update(
            {
                "supplied": False,
                "cut_off": False,
                "source_hub_id": None,
                "route_cost": None,
                "grace_ticks_remaining": 0,
            }
        )

        with mock.patch(
            "gates_of_codex.operational_position.load_operational_graph_for_state",
            return_value=graph,
        ), mock.patch(
            "gates_of_codex.operational_capture.load_operational_graph_for_state",
            return_value=graph,
        ), mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ), self.assertRaisesRegex(
            ValueError, "invalid_operational_supply_state"
        ):
            campaign_from_dict(payload)

    def test_supply_tick_markers_reject_impossible_persisted_order(self) -> None:
        state = _state()
        force = _only_force(state)
        force.last_supply_refresh_tick = 4
        force.last_grace_consuming_tick = 5

        with self.assertRaisesRegex(ValueError, "invalid_supply_tick_order"):
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

    def test_candidate_and_disabled_sites_are_not_sources_or_bridges(self) -> None:
        state = _state()
        state.provinces["p1"].metadata["supply_source_for"] = ["nato"]
        anchor_id = stable_node_id("p1", "anchor")
        graph = _graph(
            nodes=[
                _node(anchor_id, "p1"),
                _node("candidate-node", "p1"),
                _node("disabled-node", "p1"),
            ],
            sites=[
                _supply_site(
                    "candidate-depot",
                    "candidate-node",
                    authority=EdgeAuthority.CANDIDATE.value,
                ),
                _supply_site(
                    "disabled-depot", "disabled-node", disabled=True
                ),
            ],
        )

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            sources, diagnostics = resolve_operational_supply_sources(
                state, Faction.NATO
            )

        self.assertEqual(
            ("province-supply-source:p1",),
            tuple(item.source_hub_id for item in sources),
        )
        self.assertEqual(anchor_id, sources[0].source_node_id)
        self.assertEqual((), diagnostics)

    def test_missing_site_and_node_authority_use_authored_schema_default(self) -> None:
        state = _state()
        node = _node("legacy-node", "p1")
        node.pop("authority")
        site = _supply_site("legacy-depot", "legacy-node", authority=None)

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=_graph(nodes=[node], sites=[site]),
        ):
            sources, diagnostics = resolve_operational_supply_sources(
                state, Faction.NATO
            )

        self.assertEqual(("legacy-depot",), tuple(
            item.source_hub_id for item in sources
        ))
        self.assertEqual((), diagnostics)

    def test_hostile_site_cannot_hijack_province_source_bridge(self) -> None:
        state = _state()
        state.provinces["p1"].metadata["supply_source_for"] = ["nato"]
        anchor_id = stable_node_id("p1", "anchor")
        graph = _graph(
            nodes=[_node(anchor_id, "p1"), _node("hostile-node", "p1")],
            sites=[_supply_site("hostile-depot", "hostile-node", owner="rusa")],
        )

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            sources, diagnostics = resolve_operational_supply_sources(
                state, Faction.NATO
            )

        source = _source_by_id(sources, "province-supply-source:p1")
        self.assertEqual(anchor_id, source.source_node_id)
        self.assertNotIn("hostile-depot", {
            item.source_hub_id for item in sources
        })
        self.assertEqual((), diagnostics)

    def test_authored_site_with_invalid_node_fails_closed_with_diagnostic(self) -> None:
        cases = (
            ("missing-node", [], "missing_source_node"),
            (
                "cross-province",
                [_node("cross-province", "p2")],
                "cross_province_source_node",
            ),
            (
                "candidate-node",
                [
                    {
                        **_node("candidate-node", "p1"),
                        "authority": EdgeAuthority.CANDIDATE.value,
                    }
                ],
                "non_authored_source_node",
            ),
        )
        for node_id, nodes, reason in cases:
            with self.subTest(reason=reason):
                state = _state()
                site = _supply_site("authored-depot", node_id)
                with mock.patch(
                    "gates_of_codex.operational_supply.load_operational_graph_for_state",
                    return_value=_graph(nodes=nodes, sites=[site]),
                ):
                    sources, diagnostics = resolve_operational_supply_sources(
                        state, Faction.NATO
                    )

                self.assertEqual((), sources)
                self.assertEqual(
                    (("authored-depot", "p1", reason),),
                    tuple(
                        (item.source_hub_id, item.province_id, item.reason)
                        for item in diagnostics
                    ),
                )

    def test_invalid_high_precedence_nodes_fall_back_to_authored_anchor(self) -> None:
        state = _state()
        state.provinces["p1"].metadata.update(
            {
                "infrastructure": {"supply_hub": 1},
                "supply_hub_node_id": "candidate-hub-node",
                "static_supply_source_for": ["nato"],
            }
        )
        anchor_id = stable_node_id("p1", "anchor")
        graph = _graph(
            nodes=[
                _node(anchor_id, "p1"),
                {
                    **_node("candidate-site-node", "p1"),
                    "authority": EdgeAuthority.CANDIDATE.value,
                },
                {
                    **_node("candidate-hub-node", "p1"),
                    "authority": EdgeAuthority.CANDIDATE.value,
                },
            ],
            sites=[_supply_site("candidate-node-depot", "candidate-site-node")],
        )

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            sources, diagnostics = resolve_operational_supply_sources(
                state, Faction.NATO
            )

        self.assertEqual(anchor_id, _source_by_id(
            sources, "constructed-supply-hub:p1"
        ).source_node_id)
        self.assertEqual(anchor_id, _source_by_id(
            sources, "province-supply-source:p1"
        ).source_node_id)
        self.assertEqual(
            "non_authored_source_node",
            next(
                item.reason
                for item in diagnostics
                if item.source_hub_id == "candidate-node-depot"
            ),
        )

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

    def test_supply_capable_metadata_requires_an_actual_bool(self) -> None:
        for kind in (EdgeKind.ROAD.value, EdgeKind.SEA_LANE.value):
            for bad in ("true", 1, 0, 1.0, None):
                with self.subTest(kind=kind, bad=bad), self.assertRaisesRegex(
                    ValueError, "invalid_supply_capable"
                ):
                    assert_supply_edge_hop_legal(
                        _edge(kind=kind, metadata={"supply_capable": bad}),
                        origin="a",
                        dest="b",
                    )

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

    def test_stale_completed_tick_fails_before_mutating_supply_state(self) -> None:
        state, graph = _lifecycle_state(connected=False)
        force = _only_force(state)
        force.supplied = True
        force.cut_off = False
        force.grace_ticks_remaining = 1
        force.last_supply_refresh_tick = 5
        force.last_supply_refresh_turn = 3
        force.last_grace_consuming_tick = 5
        before = (
            force.supplied,
            force.cut_off,
            force.source_hub_id,
            force.route_cost,
            force.grace_ticks_remaining,
            force.last_supply_refresh_tick,
            force.last_supply_refresh_turn,
            force.last_grace_consuming_tick,
        )

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ), self.assertRaisesRegex(ValueError, "stale_completed_tick"):
            refresh_operational_supply(
                state, consume_grace=True, completed_tick=4
            )

        self.assertEqual(
            before,
            (
                force.supplied,
                force.cut_off,
                force.source_hub_id,
                force.route_cost,
                force.grace_ticks_remaining,
                force.last_supply_refresh_tick,
                force.last_supply_refresh_turn,
                force.last_grace_consuming_tick,
            ),
        )

    def test_refresh_and_grace_tick_markers_are_monotonic(self) -> None:
        state, graph = _lifecycle_state(connected=True)
        force = _only_force(state)
        force.last_supply_refresh_tick = 10
        force.last_grace_consuming_tick = 8
        state.map_metadata["operational_clock"] = {"global_tick": 3}

        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            refresh_operational_supply(state, consume_grace=False)
            self.assertEqual(10, force.last_supply_refresh_tick)
            self.assertEqual(8, force.last_grace_consuming_tick)
            refresh_operational_supply(
                state, consume_grace=True, completed_tick=11
            )

        self.assertEqual(11, force.last_supply_refresh_tick)
        self.assertEqual(11, force.last_grace_consuming_tick)

    def test_post_load_recompute_preserves_grace(self) -> None:
        state, graph = _lifecycle_state(connected=False)
        state.schema_version = 8
        force = _only_force(state)
        force.supplied = True
        force.cut_off = False
        force.grace_ticks_remaining = 1
        force.last_supply_refresh_tick = 7
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
        self.assertEqual("province", actual_report.authority)
        self.assertEqual(
            actual_report.reachable_provinces,
            actual_report.legacy_admin_reachable_provinces,
        )

    def test_graph_supply_status_uses_formation_authority_without_refresh(self) -> None:
        state, graph = _lifecycle_state(connected=False)
        force = _only_force(state)
        force.supplied = True
        force.cut_off = False
        force.source_hub_id = None
        force.route_cost = None
        force.grace_ticks_remaining = 1

        with mock.patch(
            "gates_of_codex.supply.load_operational_graph_for_state",
            return_value=graph,
        ), mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            report = supply_status_for_faction(state, Faction.NATO)

        self.assertEqual("operational_graph", report.authority)
        self.assertIsNone(report.reachable_provinces)
        self.assertEqual(
            ("province-supply-source:p-source",), report.sources
        )
        self.assertEqual((force.strategic_formation_id,), report.grace_formations)
        self.assertEqual(("nato-route",), report.grace_battalions)
        self.assertEqual(("nato-route",), report.supplied_battalions)
        self.assertEqual((), report.isolated_battalions)

    def test_supply_status_cli_is_graph_aware_with_and_without_refresh(self) -> None:
        payloads = []
        supplies = []
        for refresh in (False, True):
            state, graph = _lifecycle_state(connected=False)
            force = _only_force(state)
            force.supplied = False
            force.cut_off = True
            force.source_hub_id = None
            force.route_cost = None
            args = ["supply-status", "campaign.json", "--faction", "nato"]
            if refresh:
                args.append("--refresh")
            output = io.StringIO()
            with mock.patch(
                "gates_of_codex.cli.load_campaign", return_value=state
            ), mock.patch(
                "gates_of_codex.cli.save_campaign"
            ), mock.patch(
                "gates_of_codex.supply.load_operational_graph_for_state",
                return_value=graph,
            ), mock.patch(
                "gates_of_codex.operational_supply.load_operational_graph_for_state",
                return_value=graph,
            ), redirect_stdout(output):
                self.assertEqual(0, cli_main(args))
            payloads.append(json.loads(output.getvalue())[0])
            supplies.append(state.battalions["nato-route"].supply)

        for payload in payloads:
            self.assertEqual("operational_graph", payload["authority"])
            self.assertIsNone(payload["reachable_provinces"])
            self.assertEqual(["nato-route"], payload["isolated_battalions"])
            self.assertEqual(
                ["province-supply-source:p-source"], payload["sources"]
            )
        self.assertEqual([100, 75], supplies)

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
        self.assertEqual(16, snapshot["schema_version"])
        self.assertFalse(exported_force["supplied"])
        self.assertTrue(exported_force["cut_off"])
        self.assertIsNone(exported_force["source_hub_id"])
        self.assertNotIn("route_cost", exported_force)
        self.assertNotIn("grace_ticks_remaining", exported_force)
        self.assertFalse(exported_battalion["is_in_supply"])
        faction = snapshot["factions"][0]
        self.assertEqual("operational_graph", faction["supply_authority"])
        self.assertIsNone(faction["supply_reachable_provinces"])
        self.assertEqual(
            1, faction["legacy_admin_supply_reachable_provinces"]
        )
        self.assertEqual(0, faction["operational_connected_formations"])
        self.assertEqual(0, faction["operational_grace_formations"])
        self.assertEqual(1, faction["operational_cut_off_formations"])
        self.assertEqual(
            ["province-supply-source:p-source"],
            faction["operational_supply_source_ids"],
        )

    def test_no_graph_save_bytes_are_unchanged_after_s8_entrypoints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_path = root / "baseline.json"
            after_path = root / "after.json"
            save_campaign(_state(), baseline_path)
            baseline = baseline_path.read_bytes()
            state = load_campaign(baseline_path)

            ensure_operational_supply_state(state)
            refresh_operational_supply(state, consume_grace=False)
            supply_status_for_faction(state, Faction.NATO)
            save_campaign(state, after_path)

            self.assertEqual(baseline, after_path.read_bytes())
            payload = json.loads(after_path.read_text(encoding="utf-8"))
            self.assertNotIn(
                "operational_supply_migration", payload["map_metadata"]
            )
            row = next(iter(payload["strategic_formations"].values()))
            self.assertTrue(row["supplied"])
            self.assertFalse(row["cut_off"])
            self.assertIsNone(row["source_hub_id"])
            self.assertIsNone(row["route_cost"])
            self.assertEqual(0, row["grace_ticks_remaining"])
            self.assertIsNone(row["last_supply_refresh_tick"])
            self.assertIsNone(row["last_supply_refresh_turn"])
            self.assertIsNone(row["last_grace_consuming_tick"])

    def test_real_graph_save_load_preserves_grace_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_path = root / "operational_graph.json"
            campaign_path = root / "campaign.json"
            state, graph = _lifecycle_state(connected=False)
            graph_path.write_text(json.dumps(graph), encoding="utf-8")
            state.map_id = "s8-test"
            state.map_metadata["operational_graph"] = str(graph_path)
            state.schema_version = 8
            force = _only_force(state)
            force.supplied = True
            force.cut_off = False
            force.source_hub_id = None
            force.route_cost = None
            force.grace_ticks_remaining = 1
            force.last_supply_refresh_tick = 7
            force.last_grace_consuming_tick = 7

            save_campaign(state, campaign_path)
            loaded = load_campaign(campaign_path)

            restored = _only_force(loaded)
            self.assertTrue(restored.supplied)
            self.assertFalse(restored.cut_off)
            self.assertIsNone(restored.source_hub_id)
            self.assertIsNone(restored.route_cost)
            self.assertEqual(1, restored.grace_ticks_remaining)
            self.assertEqual(7, restored.last_grace_consuming_tick)

    def test_frontend_and_strategic_turn_start_do_not_consume_grace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph_path = Path(temporary) / "operational_graph.json"
            state, graph = _lifecycle_state(connected=False)
            graph_path.write_text(json.dumps(graph), encoding="utf-8")
            state.map_id = "s8-test"
            state.map_metadata["operational_graph"] = str(graph_path)
            force = _only_force(state)
            force.supplied = True
            force.cut_off = False
            force.source_hub_id = None
            force.route_cost = None
            force.grace_ticks_remaining = 1
            force.last_supply_refresh_tick = 7
            force.last_grace_consuming_tick = 7

            build_frontend_snapshot(state)
            self.assertEqual(1, force.grace_ticks_remaining)
            self.assertEqual(7, force.last_grace_consuming_tick)

            with mock.patch(
                "gates_of_codex.operational_movement.resolve_strategic_turn_movement"
            ), mock.patch(
                "gates_of_codex.economy.settle_round_economy"
            ), mock.patch(
                "gates_of_codex.supply.refresh_all_supply"
            ), mock.patch(
                "gates_of_codex.strategic.evaluate_campaign_outcome"
            ):
                CampaignEngine(state).end_turn()

            self.assertEqual(1, force.grace_ticks_remaining)
            self.assertEqual(7, force.last_grace_consuming_tick)

    def test_cut_grace_cutoff_then_numeric_drain_end_to_end(self) -> None:
        state, graph = _lifecycle_state(connected=True)
        battalion = state.battalions["nato-route"]
        battalion.supply = 50
        with mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ), mock.patch(
            "gates_of_codex.supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            refresh_operational_supply(state, consume_grace=False)
            graph["edges"][0]["traversal_enabled"] = False
            refresh_operational_supply(
                state, consume_grace=True, completed_tick=1
            )
            refresh_supply_for_faction(state, Faction.NATO)
            self.assertEqual(70, battalion.supply)
            refresh_operational_supply(
                state, consume_grace=True, completed_tick=2
            )
            refresh_supply_for_faction(state, Faction.NATO)

        force = _only_force(state)
        self.assertFalse(force.supplied)
        self.assertTrue(force.cut_off)
        self.assertEqual(0, force.grace_ticks_remaining)
        self.assertEqual(45, battalion.supply)
        self.assertEqual(1, battalion.encircled_turns)

    def test_source_capture_and_recapture_disconnects_then_recovers(self) -> None:
        state, graph = _lifecycle_state(connected=True)
        state.provinces["p-source"].metadata.pop(
            "static_supply_source_for", None
        )
        source_node = stable_node_id("p-source", "anchor")
        graph["sites"] = [
            _supply_site(
                "authored-depot",
                source_node,
                province_id="p-source",
            )
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
            refresh_operational_supply(
                state, consume_grace=True, completed_tick=1
            )
            self.assertEqual(1, _only_force(state).grace_ticks_remaining)
            control["authored-depot"]["controller_faction"] = "nato"
            refresh_operational_supply(state, consume_grace=False)

        force = _only_force(state)
        self.assertTrue(force.supplied)
        self.assertFalse(force.cut_off)
        self.assertEqual(0, force.grace_ticks_remaining)
        self.assertEqual("authored-depot", force.source_hub_id)

    def test_metadata_and_constructed_source_removal_affect_next_refresh(self) -> None:
        for source_kind in ("metadata", "constructed"):
            with self.subTest(source_kind=source_kind):
                state, graph = _lifecycle_state(connected=True)
                province = state.provinces["p-source"]
                if source_kind == "constructed":
                    province.metadata.pop("static_supply_source_for", None)
                    province.metadata["infrastructure"] = {"supply_hub": 1}
                    sync_province_infrastructure_owner(province)
                with mock.patch(
                    "gates_of_codex.operational_supply.load_operational_graph_for_state",
                    return_value=graph,
                ):
                    refresh_operational_supply(state, consume_grace=False)
                    self.assertIsNotNone(_only_force(state).source_hub_id)
                    if source_kind == "metadata":
                        province.metadata.pop(
                            "static_supply_source_for", None
                        )
                    else:
                        province.metadata["infrastructure"]["supply_hub"] = 0
                        sync_province_infrastructure_owner(province)
                    refresh_operational_supply(
                        state, consume_grace=True, completed_tick=1
                    )

                force = _only_force(state)
                self.assertIsNone(force.source_hub_id)
                self.assertEqual(1, force.grace_ticks_remaining)

    def test_committed_production_candidates_remain_unavailable(self) -> None:
        graph_path = (
            Path(__file__).resolve().parents[1]
            / "godot"
            / "assets"
            / "maps"
            / "europe_mediterranean"
            / "from_goe"
            / "operational"
            / "operational_graph.json"
        )
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        _nodes, edges = _routing_graph_indexes(graph)
        candidates = tuple(
            edge
            for edge in edges.values()
            if edge.authority == EdgeAuthority.CANDIDATE.value
        )

        self.assertGreater(len(candidates), 100)
        self.assertTrue(
            all(not edge_is_supply_capable(edge) for edge in candidates)
        )


if __name__ == "__main__":
    unittest.main()
