from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex.bridge.archive import CampaignSaveArchive
from gates_of_codex.frontend import FRONTEND_SCHEMA_VERSION, build_frontend_snapshot
from gates_of_codex.frontend_commands import apply_frontend_commands
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
from gates_of_codex.operational_movement import (
    activate_committed_orders,
    advance_operational_tick,
    commit_move_orders,
    issue_move_order,
)
from gates_of_codex.operational_schema import (
    COST_MILLI_UNITY,
    FormationOperationalPosition,
    FormationStance,
    PositionMode,
    stable_edge_id,
    stable_node_id,
)
from gates_of_codex.service import BattleExportManifest, GatesOfCodeXService
from gates_of_codex.state_io import load_campaign, save_campaign


def _node(province_id: str, *, pixel: list[int]) -> dict:
    return {
        "node_id": stable_node_id(province_id),
        "display_name": province_id.upper(),
        "pixel": pixel,
        "province_id": province_id,
        "site_id": None,
        "kind": "anchor",
        "terrain": "plain",
        "metadata": {},
    }


def _edge(a: str, b: str) -> dict:
    node_a, node_b = stable_node_id(a), stable_node_id(b)
    return {
        "edge_id": stable_edge_id("corridor", node_a, node_b),
        "a": node_a,
        "b": node_b,
        "kind": "corridor",
        "authority": "authored",
        "length_px": 1000,
        "base_move_points_milli": COST_MILLI_UNITY,
        "movement_cost_milli": 2000,
        "requires_port": False,
        "can_be_blockaded": False,
        "traversal_enabled": True,
        "bidirectional": True,
        "province_ids": [a, b],
        "legacy_crossing_type": None,
        "metadata": {},
    }


def _battalion(
    battalion_id: str,
    force_id: str,
    faction: Faction,
    province_id: str,
) -> Battalion:
    return Battalion(
        battalion_id=battalion_id,
        faction=faction,
        province_id=province_id,
        formation_id="toe-nato" if faction == Faction.NATO else "toe-russia",
        roster=[BattalionRosterEntry("tank", 2, category="tank")],
        authorized_roster=[BattalionRosterEntry("tank", 2, category="tank")],
        strategic_formation_id=force_id,
    )


def _force(
    force_id: str,
    battalion_ids: list[str],
    faction: Faction,
    province_id: str,
    display_name: str,
) -> StrategicFormation:
    return StrategicFormation(
        strategic_formation_id=force_id,
        display_name=display_name,
        faction=faction,
        province_id=province_id,
        echelon=ForceEchelon.BATTALION,
        battalion_ids=battalion_ids,
        template_formation_id=(
            "toe-nato" if faction == Faction.NATO else "toe-russia"
        ),
        position=FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=stable_node_id(province_id),
            progress_milli=0,
        ),
    )


def _state(root: Path) -> CampaignState:
    graph = {
        "schema": "gates-of-codex.operational-graph",
        "schema_version": 2,
        "map_id": "s10_test",
        "rules": {"ticks_per_strategic_turn": 10, "capture_hold_ticks": 2},
        "sites": [],
        "nodes": [_node("a", pixel=[0, 0]), _node("b", pixel=[1000, 0])],
        "edges": [_edge("a", "b")],
        "metadata": {},
    }
    graph_path = root / "operational_graph.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    return CampaignState(
        campaign_name="S10 presentation contract",
        map_id="s10_test",
        map_metadata={
            "operational_graph": str(graph_path.resolve()),
            "operational_maneuver_enabled": True,
        },
        factions={
            Faction.NATO.value: FactionState(
                Faction.NATO, resources=500, is_human_controlled=True
            ),
            Faction.RUSSIA.value: FactionState(Faction.RUSSIA, resources=500),
        },
        formations={
            "toe-nato": Formation(
                formation_id="toe-nato",
                display_name="NATO armored brigade",
                faction=Faction.NATO,
                nation="usa",
                kind=FormationKind.ARMORED_BRIGADE,
            ),
            "toe-russia": Formation(
                formation_id="toe-russia",
                display_name="Russian armored brigade",
                faction=Faction.RUSSIA,
                nation="rus",
                kind=FormationKind.ARMORED_BRIGADE,
            ),
        },
        provinces={
            "a": Province("a", "Alpha", owner=Faction.NATO, neighbors=["b"], x=0, y=0),
            "b": Province("b", "Bravo", owner=Faction.RUSSIA, neighbors=["a"], x=1000, y=0),
        },
        battalions={
            "bn-n": _battalion("bn-n", "sf-n", Faction.NATO, "a"),
            "bn-r-1": _battalion("bn-r-1", "sf-r", Faction.RUSSIA, "b"),
            "bn-r-2": _battalion("bn-r-2", "sf-r", Faction.RUSSIA, "b"),
        },
        strategic_formations={
            "sf-n": _force(
                "sf-n", ["bn-n"], Faction.NATO, "a", "1st Armored Group"
            ),
            "sf-r": _force(
                "sf-r",
                ["bn-r-1", "bn-r-2"],
                Faction.RUSSIA,
                "b",
                "Prepared Guards Group",
            ),
        },
        schema_version=13,
        selected_faction=Faction.NATO,
        current_faction=Faction.NATO,
    )


def _create_prepared_contact(state: CampaignState) -> None:
    defender = state.strategic_formations["sf-r"]
    defender.stance = FormationStance.AMBUSH.value
    defender.ambush_ready_tick = 0
    node_a, node_b = stable_node_id("a"), stable_node_id("b")
    issue_move_order(
        state,
        "sf-n",
        path_node_ids=[node_a, node_b],
        path_edge_ids=[stable_edge_id("corridor", node_a, node_b)],
        order_id="ord-s10-contact",
    )
    commit_move_orders(state)
    activate_committed_orders(state)
    advance_operational_tick(state)
    advance_operational_tick(state)
    if state.pending_battle is None:
        raise AssertionError("expected prepared node contact")


def _write_completed_external_battle(
    root: Path,
    state: CampaignState,
    *,
    attacker_survivors: int = 1,
    defender_survivors: int = 2,
    player_won: bool = False,
) -> tuple[Path, Path]:
    pending = state.pending_battle
    if pending is None:
        raise AssertionError("expected pending battle")
    campaign_path = root / "campaign.json"
    save_path = root / "completed.sav"
    pending.started = True
    pending.exported_save_path = str(save_path.resolve())
    save_campaign(state, campaign_path)

    rows: list[str] = []
    objects: list[str] = []
    inventories: list[str] = []
    object_id = 1
    for participant in (
        *pending.attacking_participants,
        *pending.defending_participants,
    ):
        quantity = (
            attacker_survivors
            if participant.faction == pending.attacker_faction
            else defender_survivors
        )
        for _ in range(quantity):
            object_token = f"0x{object_id:x}"
            rows.append(
                f'\t\t{{"tank" "{participant.stage}" {object_token}}}'
            )
            objects.append(
                f'\t{{Entity "tank" {object_token}\n'
                "\t\t{Position 0 0}\n"
                "\t\t{Player 0}\n"
                f"\t\t{{MID {object_id}}}\n"
                "\t}"
            )
            inventories.append(
                f"\t{{Inventory {object_token}\n"
                "\t\t{box\n"
                "\t\t\t{clear}\n"
                "\t\t}\n"
                "\t}"
            )
            object_id += 1
    CampaignSaveArchive().write(
        save_path,
        status=(
            "{saveinfo\n"
            "\t{version 9}\n"
            "\t{playedGames 1}\n"
            f"\t{{wonGames {1 if player_won else 0}}}\n"
            "}\n"
        ),
        campaign_scn=(
            "{campaign\n"
            + "\n".join(objects + inventories)
            + "\n\t{CampaignSquads\n"
            + "\n".join(rows)
            + "\n\t}\n}\n"
        ),
    )
    GatesOfCodeXService().write_manifest(
        BattleExportManifest(
            battle_id=pending.battle_id,
            campaign_path=str(campaign_path.resolve()),
            save_path=str(save_path.resolve()),
            catalog_signature="",
            played_games=0,
            won_games=0,
        )
    )
    return campaign_path, save_path


class S10FrontendPresentationContractTests(unittest.TestCase):
    def test_pending_battle_exports_exact_formation_participant_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            _create_prepared_contact(state)

            snapshot = build_frontend_snapshot(state)

        self.assertEqual(16, FRONTEND_SCHEMA_VERSION)
        self.assertEqual(16, snapshot["schema_version"])
        pending = snapshot["pending_battle"]
        self.assertEqual(["bn-n"], pending["attacking_battalions"])
        self.assertEqual(["bn-r-1", "bn-r-2"], pending["defending_battalions"])
        self.assertEqual(
            [
                {
                    "battalion_id": "bn-n",
                    "strategic_formation_id": "sf-n",
                    "formation_display_name": "1st Armored Group",
                    "faction": "nato",
                    "stage": "stage_1",
                    "is_primary": True,
                    "contact_initiator": True,
                    "ambush_eligible": False,
                    "ambush_triggered": False,
                    "ambush_strength_multiplier_milli": 1000,
                    "ambush_readiness_consumed": False,
                }
            ],
            pending["attacking_participants"],
        )
        self.assertEqual(2, len(pending["defending_participants"]))
        for row in pending["defending_participants"]:
            self.assertEqual("sf-r", row["strategic_formation_id"])
            self.assertEqual("Prepared Guards Group", row["formation_display_name"])
            self.assertEqual("rusa", row["faction"])
            self.assertFalse(row["contact_initiator"])
            self.assertTrue(row["ambush_eligible"])
            self.assertTrue(row["ambush_triggered"])
            self.assertEqual(1150, row["ambush_strength_multiplier_milli"])
            self.assertTrue(row["ambush_readiness_consumed"])

    def test_command_result_exports_transient_authoritative_movement_endpoints(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = _state(root)
            node_a, node_b = stable_node_id("a"), stable_node_id("b")
            edge_id = stable_edge_id("corridor", node_a, node_b)
            issue_move_order(
                state,
                "sf-n",
                path_node_ids=[node_a, node_b],
                path_edge_ids=[edge_id],
                order_id="ord-s10-movement",
            )
            commit_move_orders(state, faction=Faction.NATO.value)
            activate_committed_orders(state)
            campaign_path = root / "campaign.json"
            snapshot_path = root / "snapshot.json"
            save_campaign(state, campaign_path)

            result = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "advance_operational_tick"}],
                snapshot_path=snapshot_path,
            )

            movement = result["results"][0]["data"]["operational_presentation"][
                "movements"
            ]
            saved_bytes = campaign_path.read_bytes()

        self.assertEqual(
            [
                {
                    "formation_id": "sf-n",
                    "start_position": {
                        "mode": "at_node",
                        "node_id": node_a,
                        "edge_id": None,
                        "progress_milli": 0,
                        "facing_node_id": None,
                    },
                    "end_position": {
                        "mode": "on_edge",
                        "node_id": None,
                        "edge_id": edge_id,
                        "progress_milli": 500,
                        "facing_node_id": node_b,
                    },
                    "start_pixel": [0, 0],
                    "end_pixel": [500, 0],
                    "path_node_ids": [node_a, node_b],
                    "path_edge_ids": [edge_id],
                }
            ],
            movement,
        )
        self.assertNotIn(b"operational_presentation", saved_bytes)

    def test_auto_resolve_clears_pending_battle_and_rewrites_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = _state(root)
            _create_prepared_contact(state)
            campaign_path = root / "campaign.json"
            snapshot_path = root / "snapshot.json"
            save_campaign(state, campaign_path)
            self.assertIsNotNone(load_campaign(campaign_path).pending_battle)

            result = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "auto_resolve"}],
                snapshot_path=snapshot_path,
            )

            loaded = load_campaign(campaign_path)
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertTrue(result["ok"], result)
            self.assertIsNone(loaded.pending_battle)
            self.assertIsNone(snapshot.get("pending_battle"))
            self.assertEqual("auto_resolve", result["results"][0]["op"])
            self.assertIn(result["results"][0]["data"]["winner"], {"nato", "rusa"})
            loaded.validate()

    def test_auto_resolve_exports_exact_authoritative_retreat_result(self) -> None:
        def defender_wins(engine) -> Faction:
            engine.apply_battle_result(Faction.RUSSIA)
            return Faction.RUSSIA

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = _state(root)
            _create_prepared_contact(state)
            campaign_path = root / "campaign.json"
            snapshot_path = root / "snapshot.json"
            save_campaign(state, campaign_path)

            with patch(
                "gates_of_codex.frontend_commands.CampaignEngine.auto_resolve_pending_battle",
                defender_wins,
            ):
                result = apply_frontend_commands(
                    campaign_path,
                    commands=[{"op": "auto_resolve"}],
                    snapshot_path=snapshot_path,
                )

        presentation = result["results"][0]["data"]["operational_presentation"]
        self.assertEqual(
            {
                "winner": "rusa",
                "retreat_outcomes": [
                    {
                        "formation_id": "sf-n",
                        "destination_node_id": stable_node_id("a"),
                        "destination_province_id": "a",
                        "destination_pixel": [0, 0],
                        "reason": "",
                    }
                ],
            },
            presentation["battle_finalization"],
        )

    def test_auto_resolve_exports_trapped_reason_without_destination(self) -> None:
        def defender_wins(engine) -> Faction:
            engine.apply_battle_result(Faction.RUSSIA)
            return Faction.RUSSIA

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = _state(root)
            _create_prepared_contact(state)
            state.battalions["bn-r-block"] = _battalion(
                "bn-r-block", "sf-r-block", Faction.RUSSIA, "a"
            )
            state.strategic_formations["sf-r-block"] = _force(
                "sf-r-block",
                ["bn-r-block"],
                Faction.RUSSIA,
                "a",
                "Blocking Guards Group",
            )
            campaign_path = root / "campaign.json"
            snapshot_path = root / "snapshot.json"
            save_campaign(state, campaign_path)

            with patch(
                "gates_of_codex.frontend_commands.CampaignEngine.auto_resolve_pending_battle",
                defender_wins,
            ):
                result = apply_frontend_commands(
                    campaign_path,
                    commands=[{"op": "auto_resolve"}],
                    snapshot_path=snapshot_path,
                )

            saved = json.loads(campaign_path.read_text(encoding="utf-8"))

        finalization = result["results"][0]["data"]["operational_presentation"][
            "battle_finalization"
        ]
        self.assertEqual("rusa", finalization["winner"])
        self.assertEqual(
            [
                {
                    "formation_id": "sf-n",
                    "destination_node_id": None,
                    "destination_province_id": None,
                    "destination_pixel": None,
                    "reason": "trapped_no_legal_retreat",
                }
            ],
            finalization["retreat_outcomes"],
        )
        self.assertNotIn("operational_presentation", json.dumps(saved, sort_keys=True))

    def test_external_import_exports_exact_retreat_and_applies_survivors_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = _state(root)
            _create_prepared_contact(state)
            campaign_path, _ = _write_completed_external_battle(
                root,
                state,
                attacker_survivors=1,
            )
            snapshot_path = root / "snapshot.json"

            first = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "import_battle"}],
                snapshot_path=snapshot_path,
            )
            after_first = load_campaign(campaign_path)
            repeated = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "import_battle"}],
                snapshot_path=snapshot_path,
            )
            after_repeated = load_campaign(campaign_path)
            persisted = campaign_path.read_text(encoding="utf-8")

        self.assertTrue(first["ok"], first)
        self.assertEqual(1, first["commands_applied"])
        self.assertEqual(
            {
                "winner": "rusa",
                "retreat_outcomes": [
                    {
                        "formation_id": "sf-n",
                        "destination_node_id": stable_node_id("a"),
                        "destination_province_id": "a",
                        "destination_pixel": [0, 0],
                        "reason": "",
                    }
                ],
            },
            first["results"][0]["data"]["operational_presentation"][
                "battle_finalization"
            ],
        )
        self.assertEqual(1, after_first.battalions["bn-n"].unit_count)
        self.assertFalse(repeated["ok"], repeated)
        self.assertEqual(0, repeated["commands_applied"])
        self.assertEqual(1, after_repeated.battalions["bn-n"].unit_count)
        self.assertNotIn("operational_presentation", persisted)
        self.assertNotIn("battle_finalization", persisted)

    def test_external_import_generates_witnessed_removal_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = _state(root)
            state.fog_of_war_enabled = True
            _create_prepared_contact(state)
            campaign_path, _ = _write_completed_external_battle(
                root,
                state,
                attacker_survivors=2,
                defender_survivors=0,
                player_won=True,
            )

            result = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "import_battle"}],
                snapshot_path=root / "snapshot.json",
            )
            loaded = load_campaign(campaign_path)

        self.assertTrue(result["ok"], result)
        self.assertNotIn("sf-r", loaded.strategic_formations)
        self.assertNotIn(
            "formation:sf-r",
            loaded.knowledge_by_observer["faction:nato"],
        )

    def test_external_import_exports_exact_trapped_reason_without_destination(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = _state(root)
            _create_prepared_contact(state)
            state.battalions["bn-r-block"] = _battalion(
                "bn-r-block", "sf-r-block", Faction.RUSSIA, "a"
            )
            state.strategic_formations["sf-r-block"] = _force(
                "sf-r-block",
                ["bn-r-block"],
                Faction.RUSSIA,
                "a",
                "Blocking Guards Group",
            )
            campaign_path, _ = _write_completed_external_battle(root, state)

            result = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "import_battle"}],
                snapshot_path=root / "snapshot.json",
            )

        self.assertTrue(result["ok"], result)
        self.assertEqual(
            [
                {
                    "formation_id": "sf-n",
                    "destination_node_id": None,
                    "destination_province_id": None,
                    "destination_pixel": None,
                    "reason": "trapped_no_legal_retreat",
                }
            ],
            result["results"][0]["data"]["operational_presentation"][
                "battle_finalization"
            ]["retreat_outcomes"],
        )

    def test_additive_participant_fields_round_trip_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            _create_prepared_contact(state)
            snapshot = build_frontend_snapshot(state)

        encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        loaded = json.loads(encoded)
        reencoded = json.dumps(loaded, sort_keys=True, separators=(",", ":"))

        self.assertEqual(encoded, reencoded)
        self.assertEqual(
            snapshot["pending_battle"]["attacking_participants"],
            loaded["pending_battle"]["attacking_participants"],
        )
        self.assertEqual(
            snapshot["pending_battle"]["defending_participants"],
            loaded["pending_battle"]["defending_participants"],
        )


if __name__ == "__main__":
    unittest.main()
