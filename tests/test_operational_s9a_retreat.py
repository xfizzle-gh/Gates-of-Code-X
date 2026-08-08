from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from gates_of_codex.models import (
    Alliance,
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
    Formation,
    FormationKind,
    Province,
    StrategicFormation,
)
from gates_of_codex.operational_movement import (
    activate_committed_orders,
    advance_operational_tick,
    commit_move_orders,
    issue_move_order,
)
from gates_of_codex.operational_retreat import (
    RETREAT_ORIGIN_NODES_KEY,
    TRAPPED_NO_LEGAL_RETREAT,
    clear_retreat_origin_node,
    clear_retreat_origin_nodes,
    record_retreat_origin_node,
    resolve_operational_retreat,
    retreat_origin_node,
)
from gates_of_codex.operational_schema import (
    FormationOperationalPosition,
    FormationStance,
    PositionMode,
    stable_edge_id,
    stable_node_id,
)
from gates_of_codex.state_io import load_campaign, save_campaign


def _node(province_id: str) -> dict:
    return {
        "node_id": stable_node_id(province_id),
        "display_name": province_id,
        "pixel": [ord(province_id[0]) * 10, 0],
        "province_id": province_id,
        "site_id": None,
        "kind": "anchor",
        "terrain": "plain",
        "metadata": {},
    }


def _edge(
    a: str,
    b: str,
    *,
    edge_id: str | None = None,
    cost: int = 1000,
    enabled: bool = True,
    authority: str = "authored",
    kind: str = "road",
    bidirectional: bool = True,
    metadata: dict | None = None,
) -> dict:
    node_a, node_b = stable_node_id(a), stable_node_id(b)
    return {
        "edge_id": edge_id or stable_edge_id("corridor", node_a, node_b),
        "a": node_a,
        "b": node_b,
        "kind": kind,
        "authority": authority,
        "length_px": 100,
        "base_move_points_milli": 1000,
        "movement_cost_milli": cost,
        "requires_port": kind in {"ferry", "ferry_or_sea_lane", "sea_lane"},
        "can_be_blockaded": False,
        "traversal_enabled": enabled,
        "bidirectional": bidirectional,
        "province_ids": [a, b],
        "legacy_crossing_type": None,
        "metadata": dict(metadata or {}),
    }


def _graph(*, edges: list[dict] | None = None) -> dict:
    return {
        "schema": "gates-of-codex.operational-graph",
        "schema_version": 2,
        "map_id": "s9a-test",
        "rules": {
            "ticks_per_strategic_turn": 10,
            "max_friendly_formations_per_node": 3,
        },
        "sites": [],
        "nodes": [_node("a"), _node("b"), _node("c"), _node("d")],
        "edges": list(edges or [_edge("a", "b"), _edge("b", "c"), _edge("b", "d")]),
        "metadata": {},
    }


def _formation(
    force_id: str,
    battalion_id: str,
    faction: Faction,
    province_id: str,
) -> tuple[StrategicFormation, Battalion]:
    template = (
        "toe-nato"
        if faction == Faction.NATO
        else "toe-rusa" if faction == Faction.RUSSIA else ""
    )
    force = StrategicFormation(
        strategic_formation_id=force_id,
        display_name=force_id,
        faction=faction,
        province_id=province_id,
        battalion_ids=[battalion_id],
        template_formation_id=template,
        position=FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=stable_node_id(province_id),
            progress_milli=0,
        ),
    )
    battalion = Battalion(
        battalion_id=battalion_id,
        faction=faction,
        province_id=province_id,
        strategic_formation_id=force_id,
        formation_id=template,
        roster=[BattalionRosterEntry("tank", 2, category="tank")],
        authorized_roster=[BattalionRosterEntry("tank", 2, category="tank")],
    )
    return force, battalion


def _state(root: Path, *, graph: dict | None = None) -> CampaignState:
    graph_path = root / "operational_graph.json"
    graph_path.write_text(json.dumps(graph or _graph()), encoding="utf-8")
    nato_force, nato_bn = _formation("sf-nato", "bn-nato", Faction.NATO, "a")
    rusa_force, rusa_bn = _formation("sf-rusa", "bn-rusa", Faction.RUSSIA, "b")
    return CampaignState(
        campaign_name="S9A",
        map_id="s9a-test",
        map_metadata={
            "operational_graph": str(graph_path.resolve()),
            "operational_maneuver_enabled": True,
        },
        factions={
            Faction.NATO.value: FactionState(Faction.NATO),
            Faction.RUSSIA.value: FactionState(Faction.RUSSIA),
        },
        formations={
            "toe-nato": Formation(
                "toe-nato",
                "NATO",
                Faction.NATO,
                "usa",
                kind=FormationKind.ARMORED_BRIGADE,
            ),
            "toe-rusa": Formation(
                "toe-rusa",
                "Russia",
                Faction.RUSSIA,
                "rus",
                kind=FormationKind.ARMORED_BRIGADE,
            ),
        },
        provinces={
            "a": Province("a", "A", Faction.NATO, neighbors=["b"]),
            "b": Province("b", "B", Faction.RUSSIA, neighbors=["a", "c", "d"]),
            "c": Province("c", "C", Faction.RUSSIA, neighbors=["b"]),
            "d": Province("d", "D", Faction.RUSSIA, neighbors=["b"]),
        },
        battalions={nato_bn.battalion_id: nato_bn, rusa_bn.battalion_id: rusa_bn},
        strategic_formations={
            nato_force.strategic_formation_id: nato_force,
            rusa_force.strategic_formation_id: rusa_force,
        },
        schema_version=8,
    )


def _add_force(
    state: CampaignState,
    force_id: str,
    battalion_id: str,
    faction: Faction,
    province_id: str,
    *,
    position: FormationOperationalPosition | None = None,
) -> StrategicFormation:
    force, battalion = _formation(force_id, battalion_id, faction, province_id)
    if position is not None:
        force.position = position
    state.strategic_formations[force_id] = force
    state.battalions[battalion_id] = battalion
    return force


class OperationalS9AOriginTests(unittest.TestCase):
    def test_origin_helpers_use_existing_compatibility_key(self) -> None:
        state = CampaignState(campaign_name="S9A origin")

        record_retreat_origin_node(state, "sf-n", "node-a")

        self.assertEqual("operational_edge_retreat_nodes", RETREAT_ORIGIN_NODES_KEY)
        self.assertEqual(
            {"sf-n": "node-a"},
            state.map_metadata["operational_edge_retreat_nodes"],
        )
        self.assertEqual("node-a", retreat_origin_node(state, "sf-n"))

        clear_retreat_origin_node(state, "sf-n")
        self.assertIsNone(retreat_origin_node(state, "sf-n"))

        record_retreat_origin_node(state, "sf-a", "node-a")
        record_retreat_origin_node(state, "sf-b", "node-b")
        clear_retreat_origin_nodes(state)
        self.assertEqual({}, state.map_metadata[RETREAT_ORIGIN_NODES_KEY])

    def test_node_contact_save_load_preserves_exact_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = _state(root)
            node_a, node_b = stable_node_id("a"), stable_node_id("b")
            edge_ab = stable_edge_id("corridor", node_a, node_b)
            issue_move_order(
                state,
                "sf-nato",
                path_node_ids=[node_a, node_b],
                path_edge_ids=[edge_ab],
                order_id="ord-node-contact",
            )
            commit_move_orders(
                state,
                faction=Faction.NATO.value,
                locked_stance=FormationStance.OPERATIONAL.value,
            )
            activate_committed_orders(state)

            report = advance_operational_tick(state)

            self.assertTrue(report["battle_id"])
            self.assertEqual(node_a, retreat_origin_node(state, "sf-nato"))
            save_path = root / "campaign.json"
            save_campaign(state, save_path)
            loaded = load_campaign(save_path)
            self.assertEqual(node_a, retreat_origin_node(loaded, "sf-nato"))


class OperationalS9ACandidateTests(unittest.TestCase):
    def _resolve_node(self, state: CampaignState):
        return resolve_operational_retreat(
            state,
            "sf-nato",
            encounter_node_id=stable_node_id("b"),
            encounter_edge_id=None,
            encounter_progress_milli=None,
        )

    def _resolve_edge(self, state: CampaignState, edge_id: str):
        return resolve_operational_retreat(
            state,
            "sf-nato",
            encounter_node_id=None,
            encounter_edge_id=edge_id,
            encounter_progress_milli=500,
        )

    def test_valid_recorded_origin_is_absolute_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            state.provinces["c"].owner = Faction.NATO
            record_retreat_origin_node(state, "sf-nato", stable_node_id("a"))

            result = self._resolve_node(state)

            self.assertEqual(stable_node_id("a"), result.destination_node_id)

    def test_invalid_recorded_origin_falls_back_to_adjacent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            state.provinces["a"].owner = Faction.RUSSIA
            state.provinces["c"].owner = Faction.NATO
            record_retreat_origin_node(state, "sf-nato", stable_node_id("a"))

            result = self._resolve_node(state)

            self.assertEqual(stable_node_id("c"), result.destination_node_id)

    def test_no_multi_edge_search(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph = _graph(edges=[_edge("b", "c"), _edge("c", "d")])
            state = _state(Path(temporary), graph=graph)
            state.provinces["d"].owner = Faction.NATO

            result = self._resolve_node(state)

            self.assertEqual(TRAPPED_NO_LEGAL_RETREAT, result.reason)


class OperationalS9ARankingTests(unittest.TestCase):
    def _resolve_node(self, state: CampaignState):
        return self._resolve(state)

    def _resolve_edge(self, state: CampaignState, edge_id: str):
        return resolve_operational_retreat(
            state,
            "sf-nato",
            encounter_node_id=None,
            encounter_edge_id=edge_id,
            encounter_progress_milli=500,
        )

    def _resolve(self, state: CampaignState):
        return resolve_operational_retreat(
            state,
            "sf-nato",
            encounter_node_id=stable_node_id("b"),
            encounter_edge_id=None,
            encounter_progress_milli=None,
        )

    def test_supplied_adjacent_node_beats_unsupplied(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph = _graph(
                edges=[
                    _edge("b", "a", cost=500),
                    _edge("b", "c", cost=1500),
                ]
            )
            state = _state(Path(temporary), graph=graph)
            state.provinces["c"].owner = Faction.NATO
            state.provinces["c"].metadata["static_supply_source_for"] = ["nato"]

            result = self._resolve(state)

            self.assertEqual(stable_node_id("c"), result.destination_node_id)

    def test_grace_occupant_counts_as_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph = _graph(
                edges=[
                    _edge("b", "a", cost=500),
                    _edge("b", "c", cost=1500),
                ]
            )
            state = _state(Path(temporary), graph=graph)
            state.provinces["c"].owner = Faction.NATO
            grace = _add_force(
                state,
                "sf-nato-grace",
                "bn-nato-grace",
                Faction.NATO,
                "c",
            )
            grace.supplied = True
            grace.cut_off = False
            grace.source_hub_id = None
            grace.route_cost = None
            grace.grace_ticks_remaining = 1

            result = self._resolve(state)

            self.assertEqual(stable_node_id("c"), result.destination_node_id)

    def test_lower_integer_movement_cost_wins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph = _graph(
                edges=[
                    _edge("b", "a", cost=1100),
                    _edge("b", "c", cost=900),
                ]
            )
            state = _state(Path(temporary), graph=graph)
            state.provinces["c"].owner = Faction.NATO

            result = self._resolve(state)

            self.assertEqual(stable_node_id("c"), result.destination_node_id)

    def test_stable_node_id_breaks_equal_cost_tie(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph = _graph(
                edges=[
                    _edge("b", "c", cost=1000),
                    _edge("b", "a", cost=1000),
                ]
            )
            state = _state(Path(temporary), graph=graph)
            state.provinces["c"].owner = Faction.NATO

            result = self._resolve(state)

            self.assertEqual(stable_node_id("a"), result.destination_node_id)

    def test_candidate_selection_ignores_insertion_order(self) -> None:
        with tempfile.TemporaryDirectory() as left_temp, tempfile.TemporaryDirectory() as right_temp:
            graph = _graph(
                edges=[
                    _edge("b", "c", cost=1000),
                    _edge("b", "a", cost=1000),
                ]
            )
            reversed_graph = json.loads(json.dumps(graph))
            reversed_graph["nodes"].reverse()
            reversed_graph["edges"].reverse()
            left = _state(Path(left_temp), graph=graph)
            right = _state(Path(right_temp), graph=reversed_graph)
            left.provinces["c"].owner = Faction.NATO
            right.provinces["c"].owner = Faction.NATO
            right.provinces = dict(reversed(list(right.provinces.items())))
            right.strategic_formations = dict(
                reversed(list(right.strategic_formations.items()))
            )

            self.assertEqual(self._resolve(left), self._resolve(right))

    def test_candidate_edge_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            edge = _edge(
                "b",
                "a",
                enabled=False,
                authority="candidate",
                kind="corridor",
            )
            state = _state(Path(temporary), graph=_graph(edges=[edge]))

            result = self._resolve_node(state)

            self.assertEqual(TRAPPED_NO_LEGAL_RETREAT, result.reason)

    def test_disabled_edge_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(
                Path(temporary),
                graph=_graph(edges=[_edge("b", "a", enabled=False)]),
            )

            result = self._resolve_node(state)

            self.assertEqual(TRAPPED_NO_LEGAL_RETREAT, result.reason)

    def test_metadata_blocked_edge_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(
                Path(temporary),
                graph=_graph(edges=[_edge("b", "a", metadata={"blocked": True})]),
            )

            result = self._resolve_node(state)

            self.assertEqual(TRAPPED_NO_LEGAL_RETREAT, result.reason)

    def test_illegal_one_way_fallback_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(
                Path(temporary),
                graph=_graph(edges=[_edge("a", "b", bidirectional=False)]),
            )

            result = self._resolve_node(state)

            self.assertEqual(TRAPPED_NO_LEGAL_RETREAT, result.reason)

    def test_exact_edge_origin_rollback_ignores_reverse_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            edge = _edge("a", "b", bidirectional=False)
            state = _state(Path(temporary), graph=_graph(edges=[edge]))
            record_retreat_origin_node(state, "sf-nato", stable_node_id("a"))

            result = self._resolve_edge(state, edge["edge_id"])

            self.assertEqual(stable_node_id("a"), result.destination_node_id)

    def test_unrelated_fallback_obeys_direction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            edge = _edge("a", "b", bidirectional=False)
            state = _state(Path(temporary), graph=_graph(edges=[edge]))
            record_retreat_origin_node(state, "sf-nato", stable_node_id("c"))

            result = self._resolve_edge(state, edge["edge_id"])

            self.assertEqual(TRAPPED_NO_LEGAL_RETREAT, result.reason)

    def test_ferry_and_sea_fallbacks_are_unresolved(self) -> None:
        for kind in ("ferry", "ferry_or_sea_lane", "sea_lane"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                edge = _edge("b", "a", kind=kind)
                state = _state(Path(temporary), graph=_graph(edges=[edge]))

                result = self._resolve_node(state)

                self.assertEqual(TRAPPED_NO_LEGAL_RETREAT, result.reason)

    def test_hostile_control_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            state.provinces["a"].owner = Faction.RUSSIA
            record_retreat_origin_node(state, "sf-nato", stable_node_id("a"))

            result = self._resolve_node(state)

            self.assertEqual(TRAPPED_NO_LEGAL_RETREAT, result.reason)

    def test_hostile_occupation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            _add_force(state, "sf-rusa-a", "bn-rusa-a", Faction.RUSSIA, "a")

            result = self._resolve_node(state)

            self.assertEqual(TRAPPED_NO_LEGAL_RETREAT, result.reason)

    def test_stack_full_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph = _graph(edges=[_edge("b", "a")])
            graph["rules"]["max_friendly_formations_per_node"] = 1
            state = _state(Path(temporary), graph=graph)
            _add_force(state, "sf-nato-a", "bn-nato-a", Faction.NATO, "a")

            result = self._resolve_node(state)

            self.assertEqual(TRAPPED_NO_LEGAL_RETREAT, result.reason)

    def test_allied_control_uses_existing_diplomacy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), graph=_graph(edges=[_edge("b", "a")]))
            state.factions[Faction.UKRAINE.value] = FactionState(Faction.UKRAINE)
            state.alliances["western"] = Alliance(
                "western",
                "Western",
                [Faction.NATO, Faction.UKRAINE],
            )
            state.provinces["a"].owner = Faction.UKRAINE

            result = self._resolve_node(state)

            self.assertEqual(stable_node_id("a"), result.destination_node_id)

    def test_other_hostile_on_segment_prevents_second_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            edge = _edge("b", "a")
            state = _state(Path(temporary), graph=_graph(edges=[edge]))
            _add_force(
                state,
                "sf-rusa-edge",
                "bn-rusa-edge",
                Faction.RUSSIA,
                "b",
                position=FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id=edge["edge_id"],
                    progress_milli=500,
                    facing_node_id=stable_node_id("a"),
                ),
            )

            result = self._resolve_node(state)

            self.assertEqual(TRAPPED_NO_LEGAL_RETREAT, result.reason)


if __name__ == "__main__":
    unittest.main()
