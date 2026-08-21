from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from gates_of_codex.actor_economy import ACTOR_CONTENT_KEY, install_actor_content
from gates_of_codex.command_cycle_perf import (
    _RUNTIME_PATCH_OPS,
    _SNAPSHOT_PATCH_OPS,
    _should_persist_runtime_snapshot,
)
from gates_of_codex.force_migration import ensure_strategic_formations
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.frontend_actor_force import (
    apply_assign_command,
    apply_recruit_command,
    apply_repair_command,
    apply_research_command,
    build_acting_actor_presentation,
    build_actor_force_panel,
)
from gates_of_codex.frontend_commands import READ_ONLY_OPS, _apply_one, apply_frontend_commands
from gates_of_codex.frontend_snapshot_slim import FRONTEND_OMITTED_BATTALION_FIELDS
from gates_of_codex.models import Faction
from gates_of_codex.persistent_backend import SUPPORTED_OPS
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.state_io import load_campaign, save_campaign
from gates_of_codex.strategic_actors import assign_strategic_formation_actor

from test_actor_economy import _force_for_side, _resolved_payload, _single_battalion_force


class FrontendActorForceCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = load_bundled_scenario("legacy_goe_europe")
        ensure_strategic_formations(self.state)
        install_actor_content(self.state, _resolved_payload(), selected_actor_id="fra")
        self.force = _single_battalion_force(self.state, Faction.NATO)
        assign_strategic_formation_actor(self.state, self.force.strategic_formation_id, "fra")
        actors = self.state.map_metadata["strategic_actor_runtime"]["actors"]
        actors["fra"]["resources"] = 50_000
        actors["deu"]["resources"] = 50_000

    def test_acting_actor_presentation_is_selected_actor_treasury_only(self) -> None:
        row = build_acting_actor_presentation(self.state)
        self.assertIsNotNone(row)
        self.assertEqual("fra", row["actor_id"])
        self.assertEqual(50_000, row["resources"])
        self.assertTrue(row["content_installed"])
        self.assertNotIn("roster", row)
        self.assertNotIn("units", row)
        self.assertNotIn("recruitment_offers", row)

    def test_snapshot_exposes_acting_actor_without_restoring_omitted_rosters(self) -> None:
        snapshot = build_frontend_snapshot(self.state)
        self.assertEqual("fra", snapshot["acting_actor"]["actor_id"])
        self.assertEqual(50_000, snapshot["acting_actor"]["resources"])
        self.assertIn("actor_force_panel", snapshot["control"]["supported_ops"])
        self.assertIn("research", snapshot["control"]["supported_ops"])
        self.assertIn("recruit", snapshot["control"]["supported_ops"])
        self.assertIn("assign", snapshot["control"]["supported_ops"])
        for battalion in snapshot["battalions"]:
            for key in FRONTEND_OMITTED_BATTALION_FIELDS:
                self.assertNotIn(key, battalion)

    def test_force_panel_is_actor_scoped_and_rejects_foreign_roster(self) -> None:
        panel = build_actor_force_panel(
            self.state,
            {
                "actor": "fra",
                "formation": self.force.strategic_formation_id,
                "battalion": self.force.battalion_ids[0],
            },
        )
        names = {offer["unit_name"] for offer in panel["recruitment_offers"]}
        self.assertEqual({"fixture_fra"}, names)
        self.assertNotIn("fixture_deu", names)
        self.assertTrue(panel["can_manage_formation"])
        self.assertEqual("fra", panel["actor_id"])
        self.assertTrue(all(offer["actor_id"] == "fra" for offer in panel["recruitment_offers"]))

    def test_force_panel_does_not_leak_foreign_formation_roster(self) -> None:
        german = _force_for_side(self.state, Faction.NATO)
        if german.strategic_formation_id == self.force.strategic_formation_id:
            german = next(
                value
                for value in self.state.strategic_formations.values()
                if value.faction == Faction.NATO
                and value.strategic_formation_id != self.force.strategic_formation_id
            )
        assign_strategic_formation_actor(self.state, german.strategic_formation_id, "deu")
        panel = build_actor_force_panel(
            self.state,
            {"actor": "fra", "formation": german.strategic_formation_id},
        )
        self.assertFalse(panel["can_manage_formation"])
        self.assertEqual([], panel["recruitment_offers"])
        self.assertEqual([], panel["reinforcement_pool"])
        self.assertIn("deu", panel["blocked_reasons"][0])

    def test_research_recruit_assign_repair_and_save_load(self) -> None:
        research = apply_research_command(
            self.state,
            {"actor": "fra", "key": "actor:fra:unit:fixture_fra"},
        )
        self.assertEqual("actor:fra:unit:fixture_fra", research["key"])
        purchase = apply_recruit_command(
            self.state,
            {
                "actor": "fra",
                "formation": self.force.strategic_formation_id,
                "unit": "fixture_fra",
                "quantity": 2,
            },
        )
        self.assertEqual(2, purchase["quantity"])
        transfer = apply_assign_command(
            self.state,
            {
                "actor": "fra",
                "formation": self.force.strategic_formation_id,
                "battalion": self.force.battalion_ids[0],
                "unit": "fixture_fra",
                "quantity": 2,
            },
        )
        self.assertEqual(2, transfer["quantity"])
        battalion = self.state.battalions[self.force.battalion_ids[0]]
        battalion.condition = 90
        battalion.supply = 80
        battalion.encircled_turns = 0
        repaired = _apply_one(
            self.state,
            "repair",
            {
                "actor": "fra",
                "formation": self.force.strategic_formation_id,
                "battalion": self.force.battalion_ids[0],
                "points": 1,
            },
        )
        self.assertTrue(repaired.ok)
        self.assertEqual(91, battalion.condition)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            save_campaign(self.state, path)
            loaded = load_campaign(path)
        actors = loaded.map_metadata["strategic_actor_runtime"]["actors"]
        self.assertIn("actor:fra:unit:fixture_fra", actors["fra"]["researched_keys"])
        pool = loaded.map_metadata[ACTOR_CONTENT_KEY]["reinforcement_pool"]
        self.assertEqual([], pool)
        loaded_bn = loaded.battalions[self.force.battalion_ids[0]]
        self.assertEqual(
            2,
            next(item.quantity for item in loaded_bn.roster if item.unit_name == "fixture_fra"),
        )
        self.assertEqual(91, loaded_bn.condition)

    def test_recruit_rejects_foreign_actor_and_foreign_unit(self) -> None:
        german = next(
            value
            for value in self.state.strategic_formations.values()
            if value.faction == Faction.NATO
            and value.strategic_formation_id != self.force.strategic_formation_id
        )
        assign_strategic_formation_actor(self.state, german.strategic_formation_id, "deu")
        with self.assertRaisesRegex(ValueError, "owned by deu"):
            apply_recruit_command(
                self.state,
                {
                    "actor": "fra",
                    "formation": german.strategic_formation_id,
                    "unit": "fixture_fra",
                },
            )
        with self.assertRaisesRegex(ValueError, "outside actor"):
            apply_recruit_command(
                self.state,
                {
                    "actor": "fra",
                    "formation": self.force.strategic_formation_id,
                    "unit": "fixture_deu",
                },
            )
        with self.assertRaisesRegex(ValueError, "not scoped to actor"):
            apply_research_command(
                self.state,
                {"actor": "fra", "key": "actor:deu:unit:fixture_deu"},
            )

    def _prepare_repairable(self, force) -> None:
        battalion = self.state.battalions[force.battalion_ids[0]]
        battalion.condition = 90
        battalion.supply = 80
        battalion.encircled_turns = 0

    def _foreign_nato_force(self):
        german = next(
            value
            for value in self.state.strategic_formations.values()
            if value.faction == Faction.NATO
            and value.strategic_formation_id != self.force.strategic_formation_id
        )
        assign_strategic_formation_actor(self.state, german.strategic_formation_id, "deu")
        return german

    def _actor_resources(self) -> dict[str, int]:
        actors = self.state.map_metadata["strategic_actor_runtime"]["actors"]
        return {key: int(actors[key]["resources"]) for key in ("fra", "deu")}

    def test_omitted_actor_repairs_selected_actors_own_formation(self) -> None:
        self._prepare_repairable(self.force)
        before = self._actor_resources()
        battalion = self.state.battalions[self.force.battalion_ids[0]]
        repaired = apply_repair_command(
            self.state,
            {
                "formation": self.force.strategic_formation_id,
                "battalion": self.force.battalion_ids[0],
                "points": 1,
            },
        )
        after = self._actor_resources()
        self.assertEqual("fra", repaired["actor_id"])
        self.assertEqual(1, repaired["points_repaired"])
        self.assertEqual(91, battalion.condition)
        self.assertEqual(before["fra"] - repaired["cost"], after["fra"])
        self.assertEqual(before["deu"], after["deu"])

    def test_omitted_actor_rejects_foreign_formation(self) -> None:
        german = self._foreign_nato_force()
        self._prepare_repairable(german)
        before = self._actor_resources()
        battalion = self.state.battalions[german.battalion_ids[0]]
        with self.assertRaisesRegex(ValueError, "owned by deu"):
            apply_repair_command(
                self.state,
                {
                    "formation": german.strategic_formation_id,
                    "battalion": german.battalion_ids[0],
                    "points": 1,
                },
            )
        after = self._actor_resources()
        self.assertEqual(90, battalion.condition)
        self.assertEqual(before, after)

    def test_explicit_wrong_actor_rejects_repair(self) -> None:
        self._prepare_repairable(self.force)
        before = self._actor_resources()
        battalion = self.state.battalions[self.force.battalion_ids[0]]
        with self.assertRaisesRegex(ValueError, "owned by fra"):
            apply_repair_command(
                self.state,
                {
                    "actor": "deu",
                    "formation": self.force.strategic_formation_id,
                    "battalion": self.force.battalion_ids[0],
                    "points": 1,
                },
            )
        after = self._actor_resources()
        self.assertEqual(90, battalion.condition)
        self.assertEqual(before, after)

    def test_selected_actor_valid_repair_succeeds(self) -> None:
        self._prepare_repairable(self.force)
        before = self._actor_resources()
        battalion = self.state.battalions[self.force.battalion_ids[0]]
        repaired = apply_repair_command(
            self.state,
            {
                "actor": "fra",
                "formation": self.force.strategic_formation_id,
                "battalion": self.force.battalion_ids[0],
                "points": 1,
            },
        )
        after = self._actor_resources()
        self.assertTrue(repaired["points_repaired"] > 0)
        self.assertEqual("fra", repaired["actor_id"])
        self.assertEqual(91, battalion.condition)
        self.assertEqual(before["fra"] - repaired["cost"], after["fra"])
        self.assertEqual(before["deu"], after["deu"])

    def test_repair_does_not_spend_foreign_actor_treasury(self) -> None:
        german = self._foreign_nato_force()
        self._prepare_repairable(self.force)
        self._prepare_repairable(german)
        before = self._actor_resources()
        fra_bn = self.state.battalions[self.force.battalion_ids[0]]
        deu_bn = self.state.battalions[german.battalion_ids[0]]
        with self.assertRaisesRegex(ValueError, "owned by deu"):
            apply_repair_command(
                self.state,
                {
                    "formation": german.strategic_formation_id,
                    "battalion": german.battalion_ids[0],
                    "points": 1,
                },
            )
        with self.assertRaisesRegex(ValueError, "owned by deu"):
            apply_repair_command(
                self.state,
                {
                    "actor": "fra",
                    "formation": german.strategic_formation_id,
                    "battalion": german.battalion_ids[0],
                    "points": 1,
                },
            )
        rejected = self._actor_resources()
        self.assertEqual(90, deu_bn.condition)
        self.assertEqual(before, rejected)
        repaired = apply_repair_command(
            self.state,
            {
                "formation": self.force.strategic_formation_id,
                "battalion": self.force.battalion_ids[0],
                "points": 1,
            },
        )
        after = self._actor_resources()
        self.assertEqual(91, fra_bn.condition)
        self.assertEqual(90, deu_bn.condition)
        self.assertEqual(before["fra"] - repaired["cost"], after["fra"])
        self.assertEqual(before["deu"], after["deu"])
        self.assertNotEqual(before["fra"], after["fra"])

    def test_apply_frontend_commands_round_trip_and_json(self) -> None:
        apply_research_command(
            self.state,
            {"actor": "fra", "key": "actor:fra:unit:fixture_fra"},
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = root / "campaign.json"
            snapshot = root / "snapshot.json"
            commands = root / "frontend_commands.json"
            save_campaign(self.state, campaign)
            commands.write_text(
                json.dumps(
                    {
                        "commands": [
                            {
                                "op": "actor_force_panel",
                                "actor": "fra",
                                "formation": self.force.strategic_formation_id,
                                "battalion": self.force.battalion_ids[0],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            report = apply_frontend_commands(
                campaign,
                commands_path=commands,
                snapshot_path=snapshot,
            )
            encoded = json.dumps(report)
            self.assertTrue(report["ok"])
            self.assertIn("fixture_fra", encoded)
            self.assertNotIn("fixture_deu", encoded)
            panel = report["results"][0]["data"]
            self.assertEqual("fra", panel["actor_id"])
            self.assertEqual({"fixture_fra"}, {row["unit_name"] for row in panel["recruitment_offers"]})

    def test_persist_seam_does_not_absorb_force_ops(self) -> None:
        self.assertIn("actor_force_panel", READ_ONLY_OPS)
        for op in ("research", "recruit", "assign", "repair", "actor_force_panel"):
            self.assertNotIn(op, _SNAPSHOT_PATCH_OPS)
            self.assertNotIn(op, _RUNTIME_PATCH_OPS)
            self.assertFalse(_should_persist_runtime_snapshot([{"op": op}]))
        # Composed-stack daemon policy (#279): only repair is warm-allowlisted.
        # Research/recruit/assign and the read-only panel stay one-shot full-refresh.
        self.assertIn("repair", SUPPORTED_OPS)
        for op in ("research", "recruit", "assign", "actor_force_panel"):
            self.assertNotIn(op, SUPPORTED_OPS)


if __name__ == "__main__":
    unittest.main()
