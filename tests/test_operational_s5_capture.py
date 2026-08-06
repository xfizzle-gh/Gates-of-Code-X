from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.force_migration import ensure_strategic_formations
from gates_of_codex.frontend import FRONTEND_SCHEMA_VERSION, build_frontend_snapshot
from gates_of_codex.models import (
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
    ForceEchelon,
    Formation,
    FormationKind,
    Province,
    StrategicFormation,
)
from gates_of_codex.operational_capture import (
    SITE_CONTROL_KEY,
    advance_site_capture,
    ensure_site_control_state,
    get_site_control_state,
    list_control_sites,
    set_site_control_state,
)
from gates_of_codex.operational_contact import ENCOUNTER_KIND_NODE_CONTACT
from gates_of_codex.operational_movement import (
    activate_committed_orders,
    advance_operational_tick,
    commit_move_orders,
    issue_move_order,
)
from gates_of_codex.operational_position import (
    clear_operational_graph_cache,
    ensure_operational_positions,
)
from gates_of_codex.operational_schema import (
    COST_MILLI_UNITY,
    FormationOperationalPosition,
    PositionMode,
    stable_edge_id,
    stable_node_id,
    stable_site_id,
)
from gates_of_codex.state_io import load_campaign, save_campaign


def _graph_with_site() -> dict:
    na, nb = stable_node_id("a"), stable_node_id("b")
    site_b = stable_site_id("b", "objective", "hub")
    return {
        "schema": "gates-of-codex.operational-graph",
        "schema_version": 2,
        "map_id": "s5_test",
        "rules": {
            "ticks_per_strategic_turn": 10,
            "capture_hold_ticks": 2,
            "max_friendly_formations_per_node": 3,
        },
        "sites": [
            {
                "site_id": site_b,
                "display_name": "B hub",
                "kind": "objective",
                "province_id": "b",
                "pixel": [100, 0],
                "route_node_id": nb,
                "control_weight_milli": COST_MILLI_UNITY,
                "capture_threshold_milli": COST_MILLI_UNITY,
                "owner_faction": "rusa",
                "metadata": {},
            }
        ],
        "nodes": [
            {
                "node_id": na,
                "display_name": "a",
                "pixel": [0, 0],
                "province_id": "a",
                "site_id": None,
                "kind": "anchor",
                "terrain": "plain",
                "metadata": {},
            },
            {
                "node_id": nb,
                "display_name": "b",
                "pixel": [100, 0],
                "province_id": "b",
                "site_id": site_b,
                "kind": "site",
                "terrain": "urban",
                "metadata": {},
            },
        ],
        "edges": [
            {
                "edge_id": stable_edge_id("corridor", na, nb),
                "a": na,
                "b": nb,
                "kind": "corridor",
                "authority": "authored",
                "length_px": 100,
                "base_move_points_milli": COST_MILLI_UNITY,
                "movement_cost_milli": COST_MILLI_UNITY,
                "requires_port": False,
                "can_be_blockaded": False,
                "traversal_enabled": True,
                "bidirectional": True,
                "province_ids": ["a", "b"],
                "legacy_crossing_type": None,
                "metadata": {},
            }
        ],
        "metadata": {},
    }


def _bn(bid: str, faction: Faction, province: str, *, force_id: str = "") -> Battalion:
    toe = "toe-nato" if faction == Faction.NATO else "toe-rusa"
    return Battalion(
        battalion_id=bid,
        faction=faction,
        province_id=province,
        formation_id=toe,
        roster=[BattalionRosterEntry("tank(x)", 1, category="tank")],
        authorized_roster=[BattalionRosterEntry("tank(x)", 1, category="tank")],
        strategic_formation_id=force_id or f"sf-{bid}",
    )


def _force(fid: str, faction: Faction, province: str, bn_ids: list[str]) -> StrategicFormation:
    return StrategicFormation(
        strategic_formation_id=fid,
        display_name=fid,
        faction=faction,
        province_id=province,
        echelon=ForceEchelon.BATTALION,
        battalion_ids=list(bn_ids),
        template_formation_id="toe-nato" if faction == Faction.NATO else "toe-rusa",
        position=FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=stable_node_id(province),
            progress_milli=0,
        ),
    )


def _state(tmp: Path, *, with_site: bool = True) -> CampaignState:
    graph = _graph_with_site() if with_site else {
        **_graph_with_site(),
        "sites": [],
        "nodes": [
            n for n in _graph_with_site()["nodes"] if n["kind"] == "anchor" or True
        ],
    }
    if not with_site:
        graph = _graph_with_site()
        graph["sites"] = []
        for node in graph["nodes"]:
            node["site_id"] = None
            node["kind"] = "anchor"
    path = tmp / "operational_graph.json"
    path.write_text(json.dumps(graph), encoding="utf-8")
    state = CampaignState(
        campaign_name="S5",
        map_id="s5_test",
        map_metadata={
            "operational_graph": str(path.resolve()),
            "operational_maneuver_enabled": True,
        },
        factions={
            Faction.NATO.value: FactionState(Faction.NATO, resources=500, is_human_controlled=True),
            Faction.RUSSIA.value: FactionState(Faction.RUSSIA, resources=500),
        },
        formations={
            "toe-nato": Formation(
                formation_id="toe-nato",
                display_name="N",
                faction=Faction.NATO,
                nation="usa",
                kind=FormationKind.ARMORED_BRIGADE,
            ),
            "toe-rusa": Formation(
                formation_id="toe-rusa",
                display_name="R",
                faction=Faction.RUSSIA,
                nation="rus",
                kind=FormationKind.ARMORED_BRIGADE,
            ),
        },
        provinces={
            "a": Province("a", "A", owner=Faction.NATO, neighbors=["b"], x=0, y=0),
            "b": Province("b", "B", owner=Faction.RUSSIA, neighbors=["a"], x=100, y=0),
        },
        battalions={
            "bn-nato": _bn("bn-nato", Faction.NATO, "a", force_id="sf-nato"),
        },
        strategic_formations={
            "sf-nato": _force("sf-nato", Faction.NATO, "a", ["bn-nato"]),
        },
        schema_version=7,
        turn_number=1,
        selected_faction=Faction.NATO,
        current_faction=Faction.NATO,
    )
    ensure_strategic_formations(state)
    ensure_operational_positions(state)
    state.strategic_formations["sf-nato"].position = FormationOperationalPosition(
        mode=PositionMode.AT_NODE.value,
        node_id=stable_node_id("a"),
        progress_milli=0,
    )
    return state


class OperationalS5CaptureTests(unittest.TestCase):
    def test_two_uncontested_ticks_capture_site_and_province(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            site_id = stable_site_id("b", "objective", "hub")
            nb = stable_node_id("b")
            # Move NATO onto site node b (no enemy present).
            state.strategic_formations["sf-nato"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=nb, progress_milli=0
            )
            state.strategic_formations["sf-nato"].province_id = "b"
            state.battalions["bn-nato"].province_id = "b"
            self.assertEqual(Faction.RUSSIA, state.provinces["b"].owner)

            r1 = advance_site_capture(state)
            self.assertTrue(r1["advanced"])
            control = get_site_control_state(state)[site_id]
            self.assertEqual("nato", control["claimant_faction"])
            self.assertEqual(1, control["progress_ticks"])
            self.assertEqual("rusa", control["controller_faction"])
            self.assertEqual(Faction.RUSSIA, state.provinces["b"].owner)

            r2 = advance_site_capture(state)
            self.assertIn(site_id, r2["flipped_sites"])
            self.assertIn("b", r2["flipped_provinces"])
            control = get_site_control_state(state)[site_id]
            self.assertEqual("nato", control["controller_faction"])
            self.assertEqual(Faction.NATO, state.provinces["b"].owner)

    def test_contest_resets_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            site_id = stable_site_id("b", "objective", "hub")
            nb = stable_node_id("b")
            state.strategic_formations["sf-nato"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=nb, progress_milli=0
            )
            state.strategic_formations["sf-nato"].province_id = "b"
            state.battalions["bn-nato"].province_id = "b"
            advance_site_capture(state)
            self.assertEqual(1, get_site_control_state(state)[site_id]["progress_ticks"])

            # Enemy arrives — contest.
            state.battalions["bn-rusa"] = _bn("bn-rusa", Faction.RUSSIA, "b", force_id="sf-rusa")
            state.strategic_formations["sf-rusa"] = _force(
                "sf-rusa", Faction.RUSSIA, "b", ["bn-rusa"]
            )
            advance_site_capture(state)
            control = get_site_control_state(state)[site_id]
            self.assertEqual(0, control["progress_ticks"])
            self.assertIsNone(control["claimant_faction"])
            self.assertEqual("rusa", control["controller_faction"])

    def test_leaving_resets_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            site_id = stable_site_id("b", "objective", "hub")
            nb = stable_node_id("b")
            state.strategic_formations["sf-nato"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=nb, progress_milli=0
            )
            state.strategic_formations["sf-nato"].province_id = "b"
            state.battalions["bn-nato"].province_id = "b"
            advance_site_capture(state)
            # Leave site.
            state.strategic_formations["sf-nato"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value,
                node_id=stable_node_id("a"),
                progress_milli=0,
            )
            state.strategic_formations["sf-nato"].province_id = "a"
            state.battalions["bn-nato"].province_id = "a"
            advance_site_capture(state)
            control = get_site_control_state(state)[site_id]
            self.assertEqual(0, control["progress_ticks"])
            self.assertIsNone(control["claimant_faction"])

    def test_ally_protects_but_does_not_steal_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            site_id = stable_site_id("b", "objective", "hub")
            nb = stable_node_id("b")
            # First claimant: sf-nato (lexicographically after sf-ally would steal if wrong).
            state.battalions["bn-ally"] = _bn("bn-ally", Faction.NATO, "b", force_id="sf-ally")
            state.strategic_formations["sf-ally"] = _force(
                "sf-ally", Faction.NATO, "b", ["bn-ally"]
            )
            # Place nato first on node alone for tick 1.
            state.strategic_formations["sf-nato"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=nb, progress_milli=0
            )
            state.strategic_formations["sf-nato"].province_id = "b"
            state.battalions["bn-nato"].province_id = "b"
            # Ally not yet on node.
            state.strategic_formations["sf-ally"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value,
                node_id=stable_node_id("a"),
                progress_milli=0,
            )
            state.strategic_formations["sf-ally"].province_id = "a"
            state.battalions["bn-ally"].province_id = "a"
            advance_site_capture(state)
            self.assertEqual(
                "sf-nato", get_site_control_state(state)[site_id]["claimant_formation_id"]
            )
            # Ally joins — claim stays with first claimant.
            state.strategic_formations["sf-ally"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=nb, progress_milli=0
            )
            state.strategic_formations["sf-ally"].province_id = "b"
            state.battalions["bn-ally"].province_id = "b"
            advance_site_capture(state)
            control = get_site_control_state(state)[site_id]
            # Claim completes under original claimant; allies did not steal mid-progress.
            self.assertEqual("nato", control["controller_faction"])
            self.assertIsNone(control["claimant_formation_id"])

    def test_mere_province_entry_does_not_flip_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            # Operational adjacency move into neutral province without site hold.
            state.provinces["b"].owner = Faction.NEUTRAL
            engine = CampaignEngine(state)
            # Place on a, legacy move to b.
            engine.move_or_attack("bn-nato", "b")
            self.assertEqual(Faction.NEUTRAL, state.provinces["b"].owner)

    def test_crossing_province_without_site_hold_no_flip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            # Presence in province b without being at site node (on edge).
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            state.strategic_formations["sf-nato"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=500,
                facing_node_id=nb,
            )
            state.strategic_formations["sf-nato"].province_id = "a"
            state.battalions["bn-nato"].province_id = "a"
            advance_site_capture(state)
            advance_site_capture(state)
            self.assertEqual(Faction.RUSSIA, state.provinces["b"].owner)

    def test_save_load_capture_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = _state(root)
            site_id = stable_site_id("b", "objective", "hub")
            nb = stable_node_id("b")
            state.strategic_formations["sf-nato"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=nb, progress_milli=0
            )
            state.strategic_formations["sf-nato"].province_id = "b"
            state.battalions["bn-nato"].province_id = "b"
            advance_site_capture(state)
            path = root / "campaign.json"
            save_campaign(state, path)
            reloaded = load_campaign(path)
            self.assertIn(SITE_CONTROL_KEY, reloaded.map_metadata)
            control = get_site_control_state(reloaded)[site_id]
            self.assertEqual(1, control["progress_ticks"])
            self.assertEqual("nato", control["claimant_faction"])

    def test_frontend_exports_site_control_before_any_tick(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            snapshot = build_frontend_snapshot(state)
            self.assertEqual(11, snapshot["schema_version"])
            self.assertEqual(FRONTEND_SCHEMA_VERSION, snapshot["schema_version"])
            rows = snapshot["campaign"]["site_control"]
            self.assertTrue(rows)
            by_id = {row["site_id"]: row for row in rows}
            site_b = stable_site_id("b", "objective", "hub")
            self.assertEqual("rusa", by_id[site_b]["controller_faction"])
            # Province a has synthetic fallback site initialized from owner.
            site_a = stable_site_id("a", "control", "anchor")
            self.assertIn(site_a, by_id)
            self.assertEqual("nato", by_id[site_a]["controller_faction"])

    def test_tick_integration_runs_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            site_id = stable_site_id("b", "objective", "hub")
            nb = stable_node_id("b")
            state.strategic_formations["sf-nato"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=nb, progress_milli=0
            )
            state.strategic_formations["sf-nato"].province_id = "b"
            state.battalions["bn-nato"].province_id = "b"
            report = advance_operational_tick(state)
            self.assertTrue(report["capture"]["advanced"])
            self.assertEqual(1, get_site_control_state(state)[site_id]["progress_ticks"])

    def test_synthetic_sites_when_graph_has_none(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_site=False)
            sites = list_control_sites(state)
            self.assertEqual(2, len(sites))
            self.assertTrue(all(s.get("metadata", {}).get("synthetic_anchor_control_site") for s in sites))

    def test_partial_authored_sites_fill_missing_provinces(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_site=True)
            sites = list_control_sites(state)
            ids = {str(s["site_id"]) for s in sites}
            self.assertIn(stable_site_id("b", "objective", "hub"), ids)
            self.assertIn(stable_site_id("a", "control", "anchor"), ids)
            authored = [s for s in sites if not s.get("metadata", {}).get("synthetic_anchor_control_site")]
            synthetic = [s for s in sites if s.get("metadata", {}).get("synthetic_anchor_control_site")]
            self.assertEqual(1, len(authored))
            self.assertEqual(1, len(synthetic))

    def test_operational_battle_win_does_not_flip_province(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            # Enemy on b; NATO enters and wins contact battle.
            state.battalions["bn-rusa"] = _bn("bn-rusa", Faction.RUSSIA, "b", force_id="sf-rusa")
            state.strategic_formations["sf-rusa"] = _force(
                "sf-rusa", Faction.RUSSIA, "b", ["bn-rusa"]
            )
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(
                state, "sf-nato", path_node_ids=[na, nb], path_edge_ids=[edge]
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            self.assertIsNotNone(state.pending_battle)
            assert state.pending_battle is not None
            self.assertEqual(ENCOUNTER_KIND_NODE_CONTACT, state.pending_battle.encounter_kind)
            CampaignEngine(state, random_seed=1).apply_battle_result(Faction.NATO)
            # Attacker may occupy b, but ownership stays with defender until capture ticks.
            self.assertEqual(Faction.RUSSIA, state.provinces["b"].owner)
            # Two capture ticks while holding the site node complete ownership.
            if "sf-nato" in state.strategic_formations:
                force = state.strategic_formations["sf-nato"]
                force.position = FormationOperationalPosition(
                    mode=PositionMode.AT_NODE.value, node_id=nb, progress_milli=0
                )
                force.province_id = "b"
                for bid in force.battalion_ids:
                    if bid in state.battalions:
                        state.battalions[bid].province_id = "b"
            advance_site_capture(state)
            self.assertEqual(Faction.RUSSIA, state.provinces["b"].owner)
            advance_site_capture(state)
            self.assertEqual(Faction.NATO, state.provinces["b"].owner)

    def test_ensure_idempotent_and_graph_missing_preserves(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            r1 = ensure_site_control_state(state)
            first = get_site_control_state(state)
            r2 = ensure_site_control_state(state)
            second = get_site_control_state(state)
            self.assertTrue(r1["ensured"])
            self.assertTrue(r2["ensured"])
            self.assertEqual(first, second)
            # Graph unavailable: leave capture data untouched.
            state.map_metadata["operational_graph"] = str(Path(temporary) / "missing.json")
            state.map_metadata.pop("operational_maneuver_enabled", None)
            before = get_site_control_state(state)
            report = ensure_site_control_state(state)
            self.assertFalse(report["ensured"])
            self.assertEqual(before, get_site_control_state(state))

    def test_equal_site_weight_tie_preserves_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            # Two sites in province b, each weight 1000; split controllers.
            site_b = stable_site_id("b", "objective", "hub")
            site_b2 = stable_site_id("b", "objective", "depot")
            ensure_site_control_state(state)
            control = get_site_control_state(state)
            control[site_b]["controller_faction"] = "nato"
            control[site_b]["control_weight_milli"] = 1000
            control[site_b2] = {
                "controller_faction": "rusa",
                "claimant_faction": None,
                "claimant_formation_id": None,
                "progress_ticks": 0,
                "required_ticks": 2,
                "province_id": "b",
                "route_node_id": stable_node_id("b"),
                "control_weight_milli": 1000,
            }
            set_site_control_state(state, control)
            # Inject second authored-like site into listing by writing graph with both.
            graph = _graph_with_site()
            graph["sites"].append(
                {
                    "site_id": site_b2,
                    "display_name": "B depot",
                    "kind": "objective",
                    "province_id": "b",
                    "pixel": [110, 0],
                    "route_node_id": stable_node_id("b"),
                    "control_weight_milli": 1000,
                    "capture_threshold_milli": 1000,
                    "owner_faction": "rusa",
                    "metadata": {},
                }
            )
            path = Path(temporary) / "operational_graph_tie.json"
            path.write_text(json.dumps(graph), encoding="utf-8")
            state.map_metadata["operational_graph"] = str(path.resolve())
            clear_operational_graph_cache()
            set_site_control_state(state, control)
            from gates_of_codex.operational_capture import _apply_province_ownership_from_sites

            flipped = _apply_province_ownership_from_sites(
                state, list_control_sites(state), get_site_control_state(state)
            )
            self.assertEqual([], flipped)
            self.assertEqual(Faction.RUSSIA, state.provinces["b"].owner)

    def test_strict_majority_flips_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            site_b = stable_site_id("b", "objective", "hub")
            site_b2 = stable_site_id("b", "objective", "depot")
            graph = _graph_with_site()
            graph["sites"].append(
                {
                    "site_id": site_b2,
                    "display_name": "B depot",
                    "kind": "objective",
                    "province_id": "b",
                    "pixel": [110, 0],
                    "route_node_id": stable_node_id("b"),
                    "control_weight_milli": 1000,
                    "capture_threshold_milli": 1000,
                    "owner_faction": "rusa",
                    "metadata": {},
                }
            )
            path = Path(temporary) / "operational_graph_majority.json"
            path.write_text(json.dumps(graph), encoding="utf-8")
            state.map_metadata["operational_graph"] = str(path.resolve())
            clear_operational_graph_cache()
            ensure_site_control_state(state)
            control = get_site_control_state(state)
            control[site_b]["controller_faction"] = "nato"
            control[site_b]["control_weight_milli"] = 1000
            control[site_b2]["controller_faction"] = "nato"
            control[site_b2]["control_weight_milli"] = 1000
            set_site_control_state(state, control)
            from gates_of_codex.operational_capture import _apply_province_ownership_from_sites

            flipped = _apply_province_ownership_from_sites(
                state, list_control_sites(state), get_site_control_state(state)
            )
            self.assertIn("b", flipped)
            self.assertEqual(Faction.NATO, state.provinces["b"].owner)

    def test_malformed_capture_numeric_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            ensure_site_control_state(state)
            site_id = stable_site_id("b", "objective", "hub")
            control = get_site_control_state(state)
            control[site_id]["progress_ticks"] = "1"
            set_site_control_state(state, control)
            with self.assertRaises(ValueError):
                ensure_site_control_state(state)
            control[site_id]["progress_ticks"] = True
            set_site_control_state(state, control)
            with self.assertRaises(ValueError):
                ensure_site_control_state(state)
            control[site_id]["progress_ticks"] = 1.0
            set_site_control_state(state, control)
            with self.assertRaises(ValueError):
                ensure_site_control_state(state)

    def test_legacy_battle_on_operational_campaign_does_not_flip_owner(self) -> None:
        """move_or_attack battle wins must not bypass site capture on op campaigns."""
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            state.battalions["bn-rusa"] = _bn(
                "bn-rusa", Faction.RUSSIA, "b", force_id="sf-rusa"
            )
            state.strategic_formations["sf-rusa"] = _force(
                "sf-rusa", Faction.RUSSIA, "b", ["bn-rusa"]
            )
            engine = CampaignEngine(state, random_seed=1)
            result = engine.move_or_attack("bn-nato", "b")
            self.assertIsNotNone(result.pending_battle)
            assert state.pending_battle is not None
            self.assertEqual("", state.pending_battle.encounter_kind)
            engine.apply_battle_result(Faction.NATO)
            self.assertEqual(Faction.RUSSIA, state.provinces["b"].owner)

    def test_malformed_capture_hold_ticks_and_root_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for bad in ("2", True, 2.0):
                state = _state(root)
                graph = _graph_with_site()
                graph["rules"]["capture_hold_ticks"] = bad
                path = root / f"graph_bad_{type(bad).__name__}.json"
                path.write_text(json.dumps(graph), encoding="utf-8")
                state.map_metadata["operational_graph"] = str(path.resolve())
                clear_operational_graph_cache()
                with self.assertRaises(ValueError):
                    ensure_site_control_state(state)
            state = _state(root)
            ensure_site_control_state(state)
            state.map_metadata[SITE_CONTROL_KEY] = "not-an-object"
            with self.assertRaises(ValueError):
                ensure_site_control_state(state)
            state.map_metadata[SITE_CONTROL_KEY] = {
                stable_site_id("b", "objective", "hub"): "not-a-row"
            }
            with self.assertRaises(ValueError):
                ensure_site_control_state(state)


if __name__ == "__main__":
    unittest.main()
