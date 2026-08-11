"""#206 regressions: the Earth3 player movement surface is graph-native.

Native acceptance of P5 found the production Earth3 UI reporting
``No legal moves for selected battalion.`` for every starting formation. Two
independent defects produced that, and both are covered here.

* **The frontend projected the wrong authority.** ``front_options`` enumerates
  province polygon neighbours through ``CampaignEngine.move_or_attack``. Earth3
  disables that surface entirely (``earth3_p2_movement_unavailable``), so the
  list was always empty while the authenticated P3 graph had legal hops from
  every starting formation. The snapshot now carries ``operational_orders``,
  built from the graph and validated with the same gates ``commit_move_orders``
  runs.
* **Movement could not survive validation.** The P2 footprint is the eleven
  starting provinces, and ``validate_earth3_bootstrap_campaign_state`` required
  every formation and battalion to stay inside it. A P3 order that actually
  resolved therefore failed campaign validation on the next save. Occupancy is
  now bounded by the authenticated graph's node provinces for P3 campaigns; P2
  campaigns, which have no movement authority at all, are unchanged.

The assertions below deliberately never accept "the list is non-empty" as proof.
Every emitted route is required to commit, and the frozen P3 route authority is
re-asserted so a projection change can never quietly widen the allowlist.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from test_p2_earth3_campaign_bootstrap import _resolved_catalog

from gates_of_codex.earth3_bootstrap import (
    BOOTSTRAP_METADATA_KEY,
    Earth3BootstrapError,
)
from gates_of_codex.earth3_operational import (
    ALLOWLIST_SHA256,
    DISABLED_CANDIDATE_EDGE_COUNT,
    DISABLED_CANDIDATE_IDS_SHA256,
    GRAPH_RAW_SHA256,
    P3_GRAPH_RELATIVE_PATH,
    Earth3OperationalAuthorityError,
    load_authenticated_p3_graph,
    validate_earth3_p3_campaign_extension,
)
from gates_of_codex.frontend import FRONTEND_SCHEMA_VERSION, build_frontend_snapshot
from gates_of_codex.frontend_commands import _apply_one
from gates_of_codex.models import Faction
from gates_of_codex.operational_movement import (
    commit_move_orders,
    issue_move_order,
    resolve_strategic_turn_movement,
)
from gates_of_codex.operational_order_options import list_operational_move_options
from gates_of_codex.operational_schema import MoveOrderStatus
from gates_of_codex.scenario import build_scenario
from gates_of_codex.strategic_actors import ensure_strategic_actor_runtime

#: The eleven P3 starting formations, mirroring the frozen P3 movement proof.
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

#: Node the opening-sequence proof drives the player formation onto. Donetsk is
#: held by ``sf_rus_donetsk`` at scenario start, so arrival is a real contact.
CONTACT_NODE = "op-node-e3_3380-anchor"
PLAYER_FORMATION = "sf_pol_vilnius"

_ROUTE_INVENTORY = ROOT / "docs/audits/p3-first-corridor-route-inventory.json"


def _earth3_state():
    return build_scenario("earth3_v1", resolved_catalog=_resolved_catalog())


def _disabled_candidate_edge_ids() -> frozenset[str]:
    inventory = json.loads(_ROUTE_INVENTORY.read_text(encoding="utf-8"))
    return frozenset(str(value) for value in inventory["disabled_candidate_edge_ids"])


class Earth3GraphOrderProjectionTests(unittest.TestCase):
    """One production Earth3 scenario shared by the projection assertions."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.state = _earth3_state()
        cls.graph = load_authenticated_p3_graph()
        cls.options_by_faction = {
            faction: list_operational_move_options(cls.state, faction)
            for faction in (Faction.NATO, Faction.UKRAINE, Faction.RUSSIA)
        }
        cls.all_options = [
            row for rows in cls.options_by_faction.values() for row in rows
        ]

    def test_every_starting_formation_exposes_at_least_one_legal_graph_order(
        self,
    ) -> None:
        """The reported symptom, asserted directly.

        A per-faction projection covers every intended player force: the shipped
        campaign gives NATO, Ukraine and Russia four, four and three formations.
        """
        with_orders = {row["formation_id"] for row in self.all_options}
        self.assertEqual(set(STARTING_FORMATIONS), with_orders)
        for formation_id in STARTING_FORMATIONS:
            rows = [
                row for row in self.all_options if row["formation_id"] == formation_id
            ]
            self.assertTrue(rows, formation_id)

    def test_orders_carry_graph_authority_and_no_province_adjacency_payload(
        self,
    ) -> None:
        edge_ids = {str(edge["edge_id"]) for edge in self.graph["edges"]}
        node_ids = {str(node["node_id"]) for node in self.graph["nodes"]}
        for row in self.all_options:
            self.assertTrue(row["formation_id"])
            self.assertGreaterEqual(len(row["path_node_ids"]), 2)
            self.assertEqual(
                len(row["path_node_ids"]), len(row["path_edge_ids"]) + 1, row
            )
            self.assertLessEqual(set(row["path_node_ids"]), node_ids, row)
            self.assertLessEqual(set(row["path_edge_ids"]), edge_ids, row)
            self.assertEqual(row["origin_node_id"], row["path_node_ids"][0])
            self.assertEqual(row["target_node_id"], row["path_node_ids"][-1])
            # A battalion or a bare province target would be the legacy shape.
            self.assertNotIn("battalion_id", row)
            self.assertNotIn("target", row)

    def test_only_approved_traversal_enabled_edges_are_offered(self) -> None:
        by_id = {str(edge["edge_id"]): edge for edge in self.graph["edges"]}
        offered = {
            edge_id for row in self.all_options for edge_id in row["path_edge_ids"]
        }
        self.assertTrue(offered)
        for edge_id in offered:
            edge = by_id[edge_id]
            self.assertEqual("approved", str(edge["authority"]), edge_id)
            self.assertTrue(bool(edge["traversal_enabled"]), edge_id)

    def test_disabled_candidate_edges_are_never_offered_as_player_routes(self) -> None:
        disabled = _disabled_candidate_edge_ids()
        self.assertEqual(DISABLED_CANDIDATE_EDGE_COUNT, len(disabled))
        offered = {
            edge_id for row in self.all_options for edge_id in row["path_edge_ids"]
        }
        self.assertEqual(frozenset(), offered & disabled)

    def test_polygon_adjacency_without_an_approved_edge_is_never_a_target(self) -> None:
        """The defect was projecting the wrong model, so prove the models differ.

        For every starting formation, the offered destinations must be exactly
        the graph-reachable set — and there must exist at least one province
        that is a polygon neighbour of its origin yet carries no approved edge,
        so a projection that silently fell back to adjacency would be caught.
        """
        adjacency_only_rejections = 0
        for formation_id in STARTING_FORMATIONS:
            force = self.state.strategic_formations[formation_id]
            offered = {
                row["target_province_id"]
                for row in self.all_options
                if row["formation_id"] == formation_id
            }
            origin_province = self.state.provinces[force.province_id]
            for neighbour_id in origin_province.neighbors:
                if neighbour_id in offered:
                    continue
                adjacency_only_rejections += 1
                self.assertFalse(
                    self._approved_edge_exists(force.province_id, neighbour_id),
                    f"{formation_id}: {neighbour_id} has an approved edge but is "
                    "not offered",
                )
        self.assertGreater(adjacency_only_rejections, 0)

    def _approved_edge_exists(self, left_province: str, right_province: str) -> bool:
        nodes = {
            str(node["node_id"]): str(node.get("province_id") or "")
            for node in self.graph["nodes"]
        }
        wanted = {left_province, right_province}
        for edge in self.graph["edges"]:
            pair = {nodes.get(str(edge["a"]), ""), nodes.get(str(edge["b"]), "")}
            if pair == wanted and bool(edge["traversal_enabled"]):
                return True
        return False

    def test_every_offered_route_is_accepted_by_the_authoritative_commit(self) -> None:
        """No offered target may be a dead control.

        Every route is issued and committed for real. Commit touches only the
        formation's order slot, so the slot is restored between routes rather
        than copying the whole campaign hundreds of times.
        """
        state = self.state
        for row in self.all_options:
            force = state.strategic_formations[row["formation_id"]]
            saved_ambush = force.ambush_ready_tick
            order = issue_move_order(
                state,
                row["formation_id"],
                path_node_ids=list(row["path_node_ids"]),
                path_edge_ids=list(row["path_edge_ids"]),
            )
            self.assertEqual(MoveOrderStatus.DRAFT.value, order.status)
            rejections: list[dict[str, str]] = []
            committed = commit_move_orders(
                state,
                faction=row["faction"],
                locked_stance=row["locked_stance"],
                rejections_out=rejections,
            )
            self.assertIn(row["formation_id"], committed, (row, rejections))
            self.assertEqual([], rejections, row)
            force.move_order = None
            force.ambush_ready_tick = saved_ambush

    def test_a_locked_order_removes_the_formation_from_the_player_surface(self) -> None:
        state = copy.deepcopy(self.state)
        row = next(
            row
            for row in self.options_by_faction[Faction.NATO]
            if row["formation_id"] == PLAYER_FORMATION
        )
        issue_move_order(
            state,
            row["formation_id"],
            path_node_ids=list(row["path_node_ids"]),
            path_edge_ids=list(row["path_edge_ids"]),
        )
        commit_move_orders(state, faction=row["faction"])
        remaining = {
            option["formation_id"]
            for option in list_operational_move_options(state, Faction.NATO)
        }
        self.assertNotIn(PLAYER_FORMATION, remaining)
        # Other NATO formations keep their orders: the lock is per formation.
        self.assertTrue(remaining)

    def test_projection_is_empty_without_operational_graph_authority(self) -> None:
        """Fail closed: no graph means no orders, never province adjacency."""
        legacy = build_scenario("legacy_goe_europe")
        self.assertEqual([], list_operational_move_options(legacy, legacy.current_faction))

    def test_frozen_p3_route_authority_is_unchanged(self) -> None:
        inventory = json.loads(_ROUTE_INVENTORY.read_text(encoding="utf-8"))
        self.assertEqual(64, len(self.graph["nodes"]))
        self.assertEqual(64, len({str(node["node_id"]) for node in self.graph["nodes"]}))
        self.assertEqual(65, len(self.graph["edges"]))
        self.assertEqual(65, inventory["enabled_proposal_edge_count"])
        self.assertEqual(ALLOWLIST_SHA256, inventory["allowlist_sha256"])
        self.assertEqual(
            DISABLED_CANDIDATE_IDS_SHA256, inventory["disabled_candidate_ids_sha256"]
        )
        for edge in self.graph["edges"]:
            self.assertTrue(bool(edge["traversal_enabled"]))
            self.assertTrue(bool(edge["bidirectional"]))
            self.assertEqual(1000, int(edge["movement_cost_milli"]))
        # The on-disk artifact bytes, not just its parsed shape.
        graph_bytes = (ROOT / P3_GRAPH_RELATIVE_PATH).read_bytes()
        self.assertEqual(
            GRAPH_RAW_SHA256, hashlib.sha256(graph_bytes).hexdigest()
        )

    def test_graph_reuse_never_masks_a_tampered_artifact(self) -> None:
        """The authenticated load is memoised; authentication is not.

        A cache that trusted a prior success would let a modified P3 graph run
        for the rest of the process. Load once to populate it, then present a
        mutated repository root and require the same hard failure.
        """
        self.assertEqual(65, len(load_authenticated_p3_graph()["edges"]))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in (
                P3_GRAPH_RELATIVE_PATH,
                "config/earth3/p3_operational_authority.json",
                "docs/audits/p3-first-corridor-route-inventory.json",
                "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json",
                "src/gates_of_codex/data/earth3_v1/sites.json",
            ):
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT / relative).read_bytes())
            tampered = root / P3_GRAPH_RELATIVE_PATH
            payload = json.loads(tampered.read_text(encoding="utf-8"))
            payload["edges"][0]["traversal_enabled"] = True
            payload["edges"].append(dict(payload["edges"][0], edge_id="op-edge-forged"))
            tampered.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            with self.assertRaises(Earth3OperationalAuthorityError):
                load_authenticated_p3_graph(repository_root=root)
        # The genuine artifact still authenticates afterwards.
        self.assertEqual(65, len(load_authenticated_p3_graph()["edges"]))


class Earth3GraphSnapshotContractTests(unittest.TestCase):
    """The exported frontend snapshot must carry the graph movement surface."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.state = _earth3_state()
        cls.snapshot = build_frontend_snapshot(cls.state)

    def test_snapshot_exports_operational_orders_for_the_acting_faction(self) -> None:
        self.assertEqual(16, FRONTEND_SCHEMA_VERSION)
        self.assertEqual(FRONTEND_SCHEMA_VERSION, self.snapshot["schema_version"])
        rows = self.snapshot["operational_orders"]
        self.assertTrue(rows)
        self.assertEqual(
            {self.state.current_faction.value}, {row["faction"] for row in rows}
        )

    def test_legacy_province_surface_is_empty_for_earth3(self) -> None:
        """Proof the legacy list could never have driven Earth3 movement."""
        self.assertEqual([], self.snapshot["front_options"])

    def test_formation_presentation_reports_graph_orders_as_actionable(self) -> None:
        presentations = self.snapshot["strategic_formation_presentations"]
        acting = {
            row["formation_id"]
            for row in self.snapshot["operational_orders"]
        }
        self.assertTrue(acting)
        for formation_id in acting:
            row = presentations[formation_id]
            self.assertTrue(row["can_act"], formation_id)
            self.assertTrue(row["can_issue_move_order"], formation_id)
            self.assertGreater(row["operational_option_count"], 0, formation_id)

    def test_snapshot_orders_name_provinces_the_godot_map_can_select(self) -> None:
        province_ids = {row["id"] for row in self.snapshot["provinces"]}
        for row in self.snapshot["operational_orders"]:
            self.assertIn(row["origin_province_id"], province_ids, row)
            self.assertIn(row["target_province_id"], province_ids, row)


class Earth3FootprintOccupancyTests(unittest.TestCase):
    """P3 maneuver may leave the P2 footprint; P2 still may not."""

    def test_a_resolved_graph_order_survives_campaign_validation(self) -> None:
        state = _earth3_state()
        footprint = set(state.map_metadata[BOOTSTRAP_METADATA_KEY]["footprint"])
        row = next(
            option
            for option in list_operational_move_options(state, Faction.NATO)
            if option["formation_id"] == PLAYER_FORMATION
            and option["target_node_id"] == CONTACT_NODE
        )
        issue_move_order(
            state,
            row["formation_id"],
            path_node_ids=list(row["path_node_ids"]),
            path_edge_ids=list(row["path_edge_ids"]),
        )
        resolve_strategic_turn_movement(state)
        force = state.strategic_formations[PLAYER_FORMATION]
        self.assertNotIn(
            force.province_id, footprint, "formation never left its start province"
        )
        # The defect: this raised "formation ... is outside footprint".
        state.validate()

    def test_occupancy_widened_to_the_graph_and_not_to_the_whole_map(self) -> None:
        """The rule is the authenticated graph's provinces, nothing more.

        Earth3 ships 3,514 provinces; the graph anchors 64. A widening that
        admitted the map would pass the previous test just as well.
        """
        state = _earth3_state()
        graph_provinces = validate_earth3_p3_campaign_extension(state)
        self.assertEqual(64, len(graph_provinces))
        footprint = set(state.map_metadata[BOOTSTRAP_METADATA_KEY]["footprint"])
        self.assertEqual(11, len(footprint))
        self.assertLessEqual(footprint, graph_provinces)
        self.assertGreater(len(state.provinces), len(graph_provinces) * 10)

    def test_a_province_off_the_authenticated_graph_is_still_refused(self) -> None:
        """Standing anywhere the graph does not anchor still fails validation."""
        state = _earth3_state()
        graph_provinces = validate_earth3_p3_campaign_extension(state)
        stray = next(
            province_id
            for province_id in sorted(state.provinces)
            if province_id not in graph_provinces
        )
        force = state.strategic_formations[PLAYER_FORMATION]
        force.province_id = stray
        for battalion_id in force.battalion_ids:
            state.battalions[battalion_id].province_id = stray
        with self.assertRaises(Earth3OperationalAuthorityError):
            state.validate()


class Earth3OpeningSequenceTests(unittest.TestCase):
    """The owner path: order, end turns, reach a battle, hand it to GoH.

    Commands are the exact production ops ``apply_frontend_commands`` dispatches,
    applied to one in-memory campaign. The actor runtime is resynchronised
    between turns because that is what the file-backed loop does on every
    ``save_campaign``; nothing else about the sequence is simulated.
    """

    @classmethod
    def setUpClass(cls) -> None:
        state = _earth3_state()
        cls.player_faction = state.selected_faction
        cls.order_row = next(
            row
            for row in list_operational_move_options(state, cls.player_faction)
            if row["formation_id"] == PLAYER_FORMATION
            and row["target_node_id"] == CONTACT_NODE
        )
        cls.issued = _apply_one(
            state,
            "issue_move_order",
            {
                "formation": cls.order_row["formation_id"],
                "path_node_ids": list(cls.order_row["path_node_ids"]),
                "path_edge_ids": list(cls.order_row["path_edge_ids"]),
            },
        )
        cls.committed = _apply_one(
            state,
            "commit_move_orders",
            {
                "faction": cls.player_faction.value,
                "locked_stance": cls.order_row["locked_stance"],
            },
        )
        cls.steps: list[str] = []
        for _ in range(8):
            if state.pending_battle is not None:
                break
            faction = state.current_faction
            if faction == cls.player_faction:
                _apply_one(state, "end_turn", {})
            else:
                _apply_one(
                    state,
                    "run_ai",
                    {"faction": faction.value, "advance_turn": True},
                )
            cls.steps.append(faction.value)
            ensure_strategic_actor_runtime(state)
        cls.state = state
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        # Write-back is what enables the handoff control, so export the snapshot
        # exactly as the player shell does: bound to a campaign path.
        cls.snapshot = build_frontend_snapshot(
            state,
            campaign_path=root / "campaign.json",
            snapshot_path=root / "campaign_snapshot.json",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_a_single_graph_order_is_accepted_and_committed(self) -> None:
        self.assertTrue(self.issued.ok, self.issued.detail)
        self.assertTrue(self.committed.ok, self.committed.detail)
        self.assertIn(PLAYER_FORMATION, self.committed.data["formation_ids"])
        self.assertGreater(self.order_row["hop_count"], 1)

    def test_the_opening_sequence_reaches_a_real_pending_battle(self) -> None:
        battle = self.state.pending_battle
        self.assertIsNotNone(battle, f"no contact after {self.steps}")
        self.assertEqual(self.player_faction, battle.attacker_faction)
        self.assertNotEqual(self.player_faction, battle.defender_faction)
        self.assertTrue(battle.battle_id)
        # Contact came from graph maneuver, not a legacy province attack.
        self.assertTrue(str(getattr(battle, "encounter_kind", "")))

    def test_the_player_formation_reached_the_ordered_destination(self) -> None:
        force = self.state.strategic_formations[PLAYER_FORMATION]
        self.assertIsNotNone(force.position)
        self.assertEqual(CONTACT_NODE, str(force.position.node_id))

    def test_launch_battle_in_goh_becomes_available(self) -> None:
        """The handoff control is drawn on ``writeback and has_battle``.

        Both operands are snapshot facts, so asserting them is asserting the
        button. ``handoff`` must also be a supported backend op, or the control
        would be reachable and still dead.
        """
        control = self.snapshot["control"]
        writeback = bool(control["enabled"])
        has_battle = self.snapshot["pending_battle"] is not None
        self.assertTrue(writeback, control)
        self.assertTrue(has_battle)
        self.assertIn("handoff", control["supported_ops"])
        pending = self.snapshot["pending_battle"]
        self.assertTrue(pending["id"])
        self.assertTrue(pending["attacking_participants"])
        self.assertTrue(pending["defending_participants"])

    def test_the_handoff_control_source_condition_is_the_one_asserted(self) -> None:
        """Bind the Python assertion above to the actual GDScript condition.

        If the scene stops drawing ``Launch Battle in GoH`` on
        ``writeback and has_battle``, the snapshot-level proof no longer means
        the button appears, and this fails rather than passing vacuously.
        """
        source = (ROOT / "godot/scripts/main_stack_panel.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '_draw_button("handoff", "Launch Battle in GoH (H)", x, y, '
            "writeback and has_battle",
            source,
        )

    def test_the_pending_battle_is_modal_for_further_movement(self) -> None:
        """A battle awaiting handoff must not leave movement orders offered."""
        self.assertEqual(
            [], list_operational_move_options(self.state, self.player_faction)
        )


if __name__ == "__main__":
    unittest.main()
