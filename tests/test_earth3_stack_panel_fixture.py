from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GODOT = ROOT / "godot"
COMPACT_SNAPSHOT = GODOT / "fixtures/snapshots/earth3_stack_panel.json"
STACK_FIXTURE = GODOT / "fixtures/presentation/earth3_stack_panel.json"
OPERATIONAL_SNAPSHOT = GODOT / "fixtures/snapshots/earth3_operational.json"
STACK_PROVINCE = "e3_2108"
ARMOR_BN = "bat-nato-1"
MECH_BN = "bat-nato-2"
ARMOR_TARGET = "e3_0823"
MECH_TARGET = "e3_0845"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _option_target(option: dict) -> str:
    return str(option.get("target_province_id") or option.get("target") or "")


def _select_legal_targets(payload: dict, battalion_id: str) -> list[str]:
    presentation = payload["battalion_presentations"][battalion_id]
    from_cards = [
        _option_target(option)
        for option in presentation.get("legal_options", [])
        if _option_target(option)
    ]
    if from_cards:
        return sorted(from_cards)
    return sorted(
        _option_target(option)
        for option in payload.get("front_options", [])
        if str(option.get("battalion_id", "")) == battalion_id and _option_target(option)
    )


class Earth3StackPanelFixtureTests(unittest.TestCase):
    def test_compact_snapshot_is_earth3_frontend_with_two_battalion_stack(self) -> None:
        snapshot = _load(COMPACT_SNAPSHOT)
        self.assertEqual("gates-of-codex.frontend", snapshot["schema"])
        self.assertEqual(
            "earth3_europe_mediterranean", snapshot["campaign"]["map_id"]
        )
        self.assertEqual(
            "earth3_europe_mediterranean", snapshot["strategic_map"]["map_id"]
        )
        stack = snapshot["stack_presentations"][STACK_PROVINCE]
        self.assertEqual(2, stack["battalion_count"])
        self.assertEqual([ARMOR_BN, MECH_BN], stack["battalion_ids"])
        self.assertEqual(["sf-nato-vanguard"], stack["strategic_formation_ids"])
        self.assertEqual(
            [ARMOR_BN, MECH_BN],
            snapshot["battalion_stacks"][STACK_PROVINCE],
        )
        occupants = [
            row["id"]
            for row in snapshot["battalions"]
            if row["province_id"] == STACK_PROVINCE
        ]
        self.assertEqual([ARMOR_BN, MECH_BN], occupants)
        for province in snapshot["provinces"]:
            self.assertTrue(str(province["id"]).startswith("e3_"))

    def test_fixture_and_compact_snapshot_agree_on_disjoint_legal_targets(self) -> None:
        fixture = _load(STACK_FIXTURE)
        snapshot = _load(COMPACT_SNAPSHOT)
        self.assertEqual("gates-of-codex.presentation-fixture", fixture["schema"])
        self.assertEqual("earth3_stack_panel", fixture["id"])
        for payload in (fixture, snapshot):
            armor = _select_legal_targets(payload, ARMOR_BN)
            mechanized = _select_legal_targets(payload, MECH_BN)
            self.assertEqual([ARMOR_TARGET], armor)
            self.assertEqual([MECH_TARGET], mechanized)
            self.assertNotEqual(armor, mechanized)
            self.assertTrue(
                payload["battalion_presentations"][ARMOR_BN]["can_act"]
            )
            self.assertTrue(
                payload["battalion_presentations"][MECH_BN]["can_act"]
            )
            armor_front = [
                _option_target(option)
                for option in payload["front_options"]
                if option["battalion_id"] == ARMOR_BN
            ]
            mech_front = [
                _option_target(option)
                for option in payload["front_options"]
                if option["battalion_id"] == MECH_BN
            ]
            self.assertEqual([ARMOR_TARGET], armor_front)
            self.assertEqual([MECH_TARGET], mech_front)

    def test_selection_switch_changes_acting_identity_not_just_labels(self) -> None:
        snapshot = _load(COMPACT_SNAPSHOT)
        first = _select_legal_targets(snapshot, ARMOR_BN)
        second = _select_legal_targets(snapshot, MECH_BN)
        self.assertEqual("NATO Armor Battalion", snapshot["battalion_presentations"][ARMOR_BN]["battalion_label"])
        self.assertEqual(
            "NATO Mechanized Battalion",
            snapshot["battalion_presentations"][MECH_BN]["battalion_label"],
        )
        self.assertNotEqual(
            snapshot["battalion_presentations"][ARMOR_BN]["cards"][0]["short_name"],
            snapshot["battalion_presentations"][MECH_BN]["cards"][0]["short_name"],
        )
        self.assertEqual([ARMOR_TARGET], first)
        self.assertEqual([MECH_TARGET], second)
        # Switching the selected battalion must change the acting legal target,
        # not merely the display label on the same option row.
        self.assertNotEqual(first, second)

    def test_live_earth3_operational_snapshot_is_still_slim(self) -> None:
        snapshot = _load(OPERATIONAL_SNAPSHOT)
        self.assertNotIn("stack_presentations", snapshot)
        self.assertNotIn("battalion_presentations", snapshot)
        self.assertEqual(["bat-nato-1"], snapshot["battalion_stacks"][STACK_PROVINCE])

    def test_godot_earth3_main_can_apply_and_select_from_fixture(self) -> None:
        main_scene = (GODOT / "main.tscn").read_text(encoding="utf-8")
        stack = (GODOT / "scripts/main_stack_panel.gd").read_text(encoding="utf-8")
        color = (GODOT / "scripts/main_color_id.gd").read_text(encoding="utf-8")
        production = (
            GODOT / "scripts/main_composed_presentation_refresh_safe.gd"
        ).read_text(encoding="utf-8")
        self.assertIn("res://scripts/main_composed_presentation_refresh_safe.gd", main_scene)
        self.assertIn("res://scripts/main_stack_panel.gd", main_scene)
        self.assertIn('extends "res://scripts/main_composed_presentation.gd"', production)
        self.assertIn("func apply_stack_panel_fixture", stack)
        self.assertIn("func select_acting_battalion", stack)
        self.assertIn("func acting_battalion_legal_target_ids", stack)
        self.assertIn("apply_stack_panel_fixture(presentation_fixture)", color)
        self.assertNotIn("build_frontend_snapshot", stack)
        self.assertNotIn("authorized_roster", stack)

    def test_workflow_runs_earth3_stack_panel_godot_test(self) -> None:
        workflow = (ROOT / ".github/workflows/gates-of-codex.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("earth3_stack_panel_test.gd", workflow)
        before = workflow[: workflow.index("earth3_stack_panel_test.gd")]
        step = before[before.rfind("      - name:") :]
        self.assertIn('"$HOME/godot" --headless --path .', step)


if __name__ == "__main__":
    unittest.main()
