from __future__ import annotations

import json
import unittest

from gates_of_codex.europe import build_goe_europe_campaign
from gates_of_codex.force_migration import ensure_strategic_formations
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.models import BattalionRosterEntry, Faction, UnitEconomy
from gates_of_codex.presentation import build_stack_presentations


class StackPresentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = build_goe_europe_campaign()
        battalions = sorted(self.state.battalions.values(), key=lambda value: value.battalion_id)
        self.first = battalions[0]
        self.second = next(
            value for value in battalions[1:] if value.faction == self.first.faction
        )
        self.second.province_id = self.first.province_id
        self.state.current_faction = self.first.faction
        self.state.selected_faction = self.first.faction
        for faction_state in self.state.factions.values():
            faction_state.is_human_controlled = faction_state.faction == self.first.faction
        for battalion in self.state.battalions.values():
            battalion.is_player_controlled = battalion.faction == self.first.faction
        # Hierarchy presentations require strategic formations (migration bridge).
        ensure_strategic_formations(self.state)
        # Keep both battalions co-located after formation location sync.
        force_a = self.state.strategic_formations[self.first.strategic_formation_id]
        force_b = self.state.strategic_formations[self.second.strategic_formation_id]
        force_a.province_id = self.first.province_id
        force_b.province_id = self.first.province_id
        self.first.province_id = force_a.province_id
        self.second.province_id = force_b.province_id

    def test_two_battalion_stack_preserves_explicit_selection_rows(self) -> None:
        front_options = [
            {
                "battalion_id": self.first.battalion_id,
                "origin": self.first.province_id,
                "target": "target-b",
                "kind": "move",
            },
            {
                "battalion_id": self.first.battalion_id,
                "origin": self.first.province_id,
                "target": "target-a",
                "kind": "battle",
            },
        ]
        payload = build_stack_presentations(self.state, front_options)
        stack = payload["stacks"][self.first.province_id]

        self.assertEqual(2, stack["battalion_count"])
        self.assertEqual(
            sorted([self.first.battalion_id, self.second.battalion_id]),
            stack["battalion_ids"],
        )
        self.assertTrue(payload["battalions"][self.first.battalion_id]["can_act"])
        self.assertFalse(payload["battalions"][self.second.battalion_id]["can_act"])
        self.assertEqual(
            ["target-a", "target-b"],
            [
                row["target"]
                for row in payload["battalions"][self.first.battalion_id]["legal_options"]
            ],
        )
        # Hierarchy: stack counts strategic formations separately from battalions.
        self.assertIn("strategic_formation_ids", stack)
        self.assertEqual(2, stack["formation_count"])
        self.assertIn("formations", stack["summary_label"])
        self.assertIn("battalions", stack["summary_label"])
        self.assertIn("tactical units", stack["summary_label"])
        forces = payload["strategic_formations"]
        self.assertEqual(2, len(stack["strategic_formation_ids"]))
        for force_id in stack["strategic_formation_ids"]:
            self.assertIn(force_id, forces)
            self.assertTrue(str(forces[force_id]["display_name"]).strip())
            self.assertNotEqual(forces[force_id]["display_name"], force_id)
            self.assertIn("tab_label", forces[force_id])
            self.assertEqual("Unassigned Commander", forces[force_id]["commander_label"])

    def test_unit_cards_expose_readable_names_tooltips_costs_and_source(self) -> None:
        long_name = "west81_legacy_motorized_rifle_company_with_exceptionally_long_name"
        self.first.roster = [
            BattalionRosterEntry(
                unit_name=long_name,
                quantity=3,
                stage="1980s",
                category="infantry",
            )
        ]
        self.first.authorized_roster = [
            BattalionRosterEntry(
                unit_name=long_name,
                quantity=5,
                stage="1980s",
                category="infantry",
            )
        ]
        self.first.condition = 80
        self.first.supply = 65
        self.first.experience = 7
        self.state.unit_economy[long_name] = UnitEconomy(
            unit_name=long_name,
            faction=self.first.faction,
            category="infantry",
            purchase_cost=12,
            maintenance_cost=1,
            repair_cost_per_point=2,
        )
        self.state.map_metadata.setdefault("unit_presentations", {})[long_name] = {
            "display_name": "West81 Legacy Motorized Rifle Company With Exceptionally Long Name",
            "portrait_key": "west81_legacy_motorized_rifle_company",
            "category_icon": "INF",
            "source": {
                "label": "West81",
                "marker": "W81",
                "role": "legacy_reserve",
                "priority": 0,
                "path": "set/multiplayer/units/legacy.set",
            },
        }

        payload = build_stack_presentations(self.state, [])
        battalion = payload["battalions"][self.first.battalion_id]
        card = battalion["cards"][0]

        self.assertTrue(card["short_name"].endswith("…"))
        self.assertIn(card["display_name"], card["tooltip"])
        self.assertEqual("west81_legacy_motorized_rifle_company", card["portrait_key"])
        self.assertEqual("INF", card["portrait_fallback"])
        self.assertEqual("W81", card["source"]["marker"])
        self.assertEqual("legacy_reserve", card["source"]["role"])
        self.assertEqual("battalion_inherited", card["condition_source"])
        self.assertEqual("battalion_inherited", card["supply_source"])
        self.assertEqual("battalion_inherited", card["experience_source"])
        self.assertEqual(2, card["replacement_deficit"])
        self.assertEqual(24, card["replacement_cost"])
        self.assertEqual(120, card["repair_cost"])
        self.assertEqual(24, battalion["reinforcement_cost"])
        self.assertEqual(120, battalion["repair_cost"])
        json.dumps(payload)

    def test_unknown_source_and_portrait_fallback_are_explicit(self) -> None:
        self.first.roster = [
            BattalionRosterEntry(
                unit_name="unmapped_object_name",
                quantity=1,
                category="air_defense",
            )
        ]
        self.first.authorized_roster = list(self.first.roster)
        card = build_stack_presentations(self.state, [])["battalions"][
            self.first.battalion_id
        ]["cards"][0]

        self.assertEqual("Unmapped Object Name", card["display_name"])
        self.assertEqual("unmapped_object_name", card["portrait_key"])
        self.assertEqual("AD", card["portrait_fallback"])
        self.assertEqual("Unknown source", card["source"]["label"])
        self.assertEqual("?", card["source"]["marker"])

    def test_frontend_snapshot_exports_stack_and_battalion_presentations(self) -> None:
        snapshot = build_frontend_snapshot(self.state)
        stack = snapshot["stack_presentations"][self.first.province_id]
        first = snapshot["battalion_presentations"][self.first.battalion_id]
        second = snapshot["battalion_presentations"][self.second.battalion_id]

        self.assertEqual(9, snapshot["schema_version"])
        self.assertEqual(2, stack["battalion_count"])
        self.assertEqual(
            snapshot["battalion_stacks"][self.first.province_id],
            stack["battalion_ids"],
        )
        self.assertEqual(self.first.battalion_id, first["id"])
        self.assertEqual(self.second.battalion_id, second["id"])
        rows = {
            row["id"]: row["presentation"]
            for row in snapshot["battalions"]
            if row["id"] in {self.first.battalion_id, self.second.battalion_id}
        }
        self.assertEqual(first, rows[self.first.battalion_id])
        self.assertEqual(second, rows[self.second.battalion_id])

    def test_frontend_snapshot_hierarchy_is_coherent(self) -> None:
        """Regression: stale snapshots showed 0 formations while rendering tabs.

        A fresh export must include strategic_formation_presentations and matching
        stack.strategic_formation_ids with non-empty battalion membership.
        """
        snapshot = build_frontend_snapshot(self.state)
        stack = snapshot["stack_presentations"][self.first.province_id]
        forces = snapshot["strategic_formation_presentations"]
        self.assertIn("strategic_formation_ids", stack)
        self.assertEqual(2, stack["formation_count"])
        self.assertEqual(2, len(stack["strategic_formation_ids"]))
        self.assertEqual(
            "2 formations | 2 battalions | 2 tactical units",
            stack["summary_label"],
        )
        for force_id in stack["strategic_formation_ids"]:
            self.assertIn(force_id, forces)
            force = forces[force_id]
            self.assertEqual(self.first.province_id, force["province_id"])
            self.assertEqual(1, force["battalion_count"])
            self.assertEqual(1, len(force["battalion_ids"]))
            self.assertTrue(str(force["display_name"]).strip())
            self.assertFalse(str(force["display_name"]).lower().startswith("formation-0"))
            member = force["battalion_ids"][0]
            self.assertIn(member, snapshot["battalion_presentations"])
            bn = snapshot["battalion_presentations"][member]
            self.assertEqual(self.first.province_id, bn["province_id"])
            # Placeholders are hidden in normal mode; unit_count may still be > 0.
            for card in bn.get("cards") or []:
                self.assertNotIn("placeholder", str(card.get("unit_name", "")).lower())
                self.assertNotEqual("Placeholder", str(card.get("display_name", "")))


if __name__ == "__main__":
    unittest.main()

