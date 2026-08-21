from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.cli import build_parser
from gates_of_codex.command_cycle_perf import _should_persist_runtime_snapshot
from gates_of_codex.economy import repair_formation
from gates_of_codex.frontend import FRONTEND_SCHEMA_VERSION, build_frontend_snapshot
from gates_of_codex.frontend_commands import apply_frontend_commands
from gates_of_codex.frontend_runtime_patch import RUNTIME_PATCH_SCHEMA_VERSION
from gates_of_codex.models import (
    Alliance,
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
    Formation,
    Province,
    ResearchNode,
    UnitEconomy,
)
from gates_of_codex.site_upgrade import (
    FORWARD_DEPOT_BUILD_TURNS,
    FORWARD_DEPOT_COST,
    FORWARD_DEPOT_ID,
    FORWARD_DEPOT_SLOT_CAP,
    SITE_UPGRADE_KEY,
    advance_site_upgrades,
    province_has_completed_forward_depot,
    province_site_upgrades,
    run_ai_site_upgrade,
    start_site_upgrade,
)
from gates_of_codex.state_io import load_campaign, save_campaign
from gates_of_codex.strategic import sync_province_infrastructure_owner
from gates_of_codex.strategic_actors import (
    ACTOR_RUNTIME_KEY,
    ACTOR_RUNTIME_SCHEMA_VERSION,
    EngineTacticalSide,
    StrategicActorState,
)
from gates_of_codex.supply import SUPPLY_RESTORE, refresh_supply_for_faction


class SiteUpgradeTests(unittest.TestCase):
    def test_player_can_buy_forward_depot_from_actor_treasury(self) -> None:
        state = self._state(actor_id="usa", actor_resources=2000)
        result = start_site_upgrade(state, "a", actor_id="usa")
        self.assertEqual(FORWARD_DEPOT_ID, result.upgrade_id)
        self.assertEqual("building", result.status)
        self.assertEqual(FORWARD_DEPOT_BUILD_TURNS, result.turns_remaining)
        self.assertEqual(FORWARD_DEPOT_COST, result.cost)
        self.assertEqual(2000 - FORWARD_DEPOT_COST, result.resources_remaining)
        self.assertEqual(1, FORWARD_DEPOT_SLOT_CAP)
        records = province_site_upgrades(state.provinces["a"])
        self.assertEqual(1, len(records))
        self.assertEqual("usa", records[0]["owner_actor_id"])
        self.assertFalse(province_has_completed_forward_depot(state, "a"))

    def test_legacy_faction_treasury_path_still_spends(self) -> None:
        state = self._state()
        before = state.factions["nato"].resources
        start_site_upgrade(state, "a")
        self.assertEqual(before - FORWARD_DEPOT_COST, state.factions["nato"].resources)

    def test_unknown_upgrade_and_unknown_fields_fail_closed(self) -> None:
        state = self._state()
        with self.assertRaises(ValueError):
            start_site_upgrade(state, "a", upgrade_id="barracks")
        state.provinces["a"].metadata[SITE_UPGRADE_KEY] = [
            {
                "upgrade_id": FORWARD_DEPOT_ID,
                "status": "complete",
                "turns_remaining": 0,
                "owner_actor_id": "",
                "owner_faction": "nato",
                "started_turn": 1,
                "oil_output": 12,
            }
        ]
        with self.assertRaises(ValueError):
            province_site_upgrades(state.provinces["a"])

    def test_ownership_and_supply_and_slot_cap_are_fail_closed(self) -> None:
        state = self._state(actor_id="usa", actor_resources=2000)
        with self.assertRaises(ValueError):
            start_site_upgrade(state, "x", actor_id="usa", faction=Faction.NATO)
        with self.assertRaises(ValueError):
            start_site_upgrade(state, "b", actor_id="usa")
        start_site_upgrade(state, "a", actor_id="usa")
        with self.assertRaises(ValueError):
            start_site_upgrade(state, "a", actor_id="usa")
        isolated = self._state()
        isolated.provinces["a"].metadata.pop("static_supply_source_for", None)
        isolated.provinces["a"].metadata.pop("supply_source_for", None)
        with self.assertRaises(ValueError):
            start_site_upgrade(isolated, "a")

    def test_insufficient_treasury_is_rejected(self) -> None:
        state = self._state(actor_id="usa", actor_resources=10)
        with self.assertRaises(ValueError):
            start_site_upgrade(state, "a", actor_id="usa")

    def test_completes_after_two_weekly_turns_and_does_not_complete_twice(self) -> None:
        state = self._state()
        start_site_upgrade(state, "a")
        first = advance_site_upgrades(state)
        self.assertEqual([], first)
        self.assertEqual(1, province_site_upgrades(state.provinces["a"])[0]["turns_remaining"])
        second = advance_site_upgrades(state)
        self.assertEqual([{"province_id": "a", "upgrade_id": FORWARD_DEPOT_ID, "status": "complete"}], second)
        self.assertTrue(province_has_completed_forward_depot(state, "a"))
        self.assertEqual([], advance_site_upgrades(state))

    def test_weekly_end_turn_wrap_advances_construction(self) -> None:
        state = self._state()
        start_site_upgrade(state, "a")
        engine = CampaignEngine(state)
        for _ in range(4):
            engine.end_turn()
        self.assertEqual(2, state.turn_number)
        self.assertEqual(1, province_site_upgrades(state.provinces["a"])[0]["turns_remaining"])
        for _ in range(4):
            engine.end_turn()
        self.assertTrue(province_has_completed_forward_depot(state, "a"))

    def test_completed_depot_halves_repair_cost(self) -> None:
        state = self._state()
        state.battalions["nato-1"].condition = 80
        baseline = repair_formation(state, "nato-formation", 4)
        damaged = self._state()
        damaged.battalions["nato-1"].condition = 80
        start_site_upgrade(damaged, "a")
        advance_site_upgrades(damaged)
        advance_site_upgrades(damaged)
        discounted = repair_formation(damaged, "nato-formation", 4)
        self.assertEqual(12, baseline.cost)
        self.assertEqual(4, discounted.cost)
        self.assertEqual(84, discounted.condition)

    def test_completed_depot_increases_local_supply_restore(self) -> None:
        state = self._state()
        state.battalions["nato-1"].supply = 40
        refresh_supply_for_faction(state, Faction.NATO)
        self.assertEqual(40 + SUPPLY_RESTORE, state.battalions["nato-1"].supply)
        upgraded = self._state()
        upgraded.battalions["nato-1"].supply = 40
        start_site_upgrade(upgraded, "a")
        advance_site_upgrades(upgraded)
        advance_site_upgrades(upgraded)
        refresh_supply_for_faction(upgraded, Faction.NATO)
        self.assertEqual(40 + SUPPLY_RESTORE + 10, upgraded.battalions["nato-1"].supply)

    def test_owner_change_destroys_upgrade(self) -> None:
        state = self._state()
        start_site_upgrade(state, "a")
        advance_site_upgrades(state)
        advance_site_upgrades(state)
        self.assertTrue(province_has_completed_forward_depot(state, "a"))
        state.provinces["a"].owner = Faction.RUSSIA
        sync_province_infrastructure_owner(state.provinces["a"])
        self.assertNotIn(SITE_UPGRADE_KEY, state.provinces["a"].metadata)
        self.assertFalse(province_has_completed_forward_depot(state, "a"))

    def test_save_load_preserves_building_and_complete_records(self) -> None:
        state = self._state(actor_id="usa", actor_resources=2000)
        start_site_upgrade(state, "a", actor_id="usa")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            save_campaign(state, path)
            loaded = load_campaign(path)
        records = province_site_upgrades(loaded.provinces["a"])
        self.assertEqual("building", records[0]["status"])
        self.assertEqual("usa", records[0]["owner_actor_id"])
        advance_site_upgrades(loaded)
        advance_site_upgrades(loaded)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            save_campaign(loaded, path)
            finished = load_campaign(path)
        self.assertTrue(province_has_completed_forward_depot(finished, "a"))

    def test_ai_issues_the_same_upgrade_command(self) -> None:
        state = self._state()
        action = run_ai_site_upgrade(state, Faction.NATO)
        self.assertIsNotNone(action)
        self.assertEqual("upgrade_site", action["action"])
        self.assertEqual(FORWARD_DEPOT_ID, action["upgrade_id"])
        self.assertEqual("a", action["province_id"])
        self.assertEqual("building", province_site_upgrades(state.provinces["a"])[0]["status"])

    def test_frontend_command_and_snapshot_expose_upgrade_site(self) -> None:
        state = self._state()
        snapshot = build_frontend_snapshot(state)
        self.assertEqual(FRONTEND_SCHEMA_VERSION, snapshot["schema_version"])
        self.assertIn("upgrade_site", snapshot["control"]["supported_ops"])
        province = next(row for row in snapshot["provinces"] if row["id"] == "a")
        self.assertEqual(FORWARD_DEPOT_ID, province["site_upgrade"]["upgrade_id"])
        self.assertTrue(province["site_upgrade"]["available"])
        with tempfile.TemporaryDirectory() as directory:
            campaign = Path(directory) / "campaign.json"
            save_campaign(state, campaign)
            applied = apply_frontend_commands(
                campaign,
                commands=[
                    {
                        "op": "upgrade_site",
                        "province": "a",
                        "upgrade_id": FORWARD_DEPOT_ID,
                        "faction": "nato",
                    }
                ],
            )
            self.assertTrue(applied["results"][0]["ok"])
            loaded = load_campaign(campaign)
        self.assertEqual("building", province_site_upgrades(loaded.provinces["a"])[0]["status"])

    def test_persist_gate_and_runtime_patch_schema_stay_unchanged(self) -> None:
        self.assertEqual(1, RUNTIME_PATCH_SCHEMA_VERSION)
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "upgrade_site"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "refresh"}]))
        self.assertTrue(_should_persist_runtime_snapshot([{"op": "auto_resolve"}]))

    def test_cli_exposes_upgrade_site(self) -> None:
        parsed = build_parser().parse_args(["upgrade-site", "campaign.json", "a"])
        self.assertEqual("upgrade-site", parsed.command)
        self.assertEqual(FORWARD_DEPOT_ID, parsed.upgrade)

    @staticmethod
    def _state(*, actor_id: str | None = None, actor_resources: int = 2000) -> CampaignState:
        state = CampaignState(
            campaign_name="Site upgrade test",
            selected_faction=Faction.NATO,
            current_faction=Faction.NATO,
            factions={
                "nato": FactionState(Faction.NATO, resources=2000, researched_keys=["core-nato"]),
                "ukr": FactionState(Faction.UKRAINE, resources=2000),
                "rusa": FactionState(Faction.RUSSIA, resources=2000, researched_keys=["core-rusa"]),
                "prc": FactionState(Faction.PRC, resources=2000),
            },
            alliances={
                "western-coalition": Alliance("western-coalition", "Western", [Faction.NATO, Faction.UKRAINE]),
                "eastern-coalition": Alliance("eastern-coalition", "Eastern", [Faction.RUSSIA, Faction.PRC]),
            },
            formations={
                "nato-formation": Formation(
                    "nato-formation", "NATO Formation", Faction.NATO, "US", preferred_categories=["infantry"]
                ),
                "rusa-formation": Formation(
                    "rusa-formation", "Russian Formation", Faction.RUSSIA, "RU", preferred_categories=["infantry"]
                ),
            },
            research_nodes={
                "core-nato": ResearchNode("core-nato", Faction.NATO, "Core", 0),
                "core-rusa": ResearchNode("core-rusa", Faction.RUSSIA, "Core", 0),
            },
            unit_economy={
                "rifle(nato)": UnitEconomy("rifle(nato)", Faction.NATO, "infantry", 100, 3, 1, ["core-nato"]),
                "rifle(rusa)": UnitEconomy("rifle(rusa)", Faction.RUSSIA, "infantry", 100, 3, 1, ["core-rusa"]),
            },
            provinces={
                "a": Province("a", "A", Faction.NATO, ["b", "x"], metadata={"static_supply_source_for": ["nato"]}),
                "b": Province("b", "B", Faction.NATO, ["a"]),
                "x": Province("x", "X", Faction.RUSSIA, ["a", "y"], metadata={"static_supply_source_for": ["rusa"]}),
                "y": Province("y", "Y", Faction.RUSSIA, ["x"]),
            },
            battalions={
                "nato-1": Battalion(
                    "nato-1",
                    Faction.NATO,
                    "a",
                    roster=[BattalionRosterEntry("rifle(nato)", 3, category="infantry")],
                    authorized_roster=[BattalionRosterEntry("rifle(nato)", 3, category="infantry")],
                    formation_id="nato-formation",
                ),
                "rusa-1": Battalion(
                    "rusa-1",
                    Faction.RUSSIA,
                    "x",
                    roster=[BattalionRosterEntry("rifle(rusa)", 3, category="infantry")],
                    authorized_roster=[BattalionRosterEntry("rifle(rusa)", 3, category="infantry")],
                    formation_id="rusa-formation",
                ),
            },
        )
        if actor_id is not None:
            actor = StrategicActorState(
                actor_id=actor_id,
                display_name="United States",
                short_name="USA",
                actor_type="sovereign",
                coalition_id="western-coalition",
                tactical_side=EngineTacticalSide(Faction.NATO),
                playable=True,
                roster_class="full_national",
                resources=actor_resources,
                is_human_controlled=True,
            )
            state.map_metadata[ACTOR_RUNTIME_KEY] = {
                "schema_version": ACTOR_RUNTIME_SCHEMA_VERSION,
                "selected_actor_id": actor_id,
                "current_actor_id": actor_id,
                "actors": {actor_id: actor.to_dict()},
            }
            state.provinces["a"].metadata["owner_actor_id"] = actor_id
        return state


if __name__ == "__main__":
    unittest.main()
