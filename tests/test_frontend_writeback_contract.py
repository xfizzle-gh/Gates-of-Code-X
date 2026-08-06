from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex.europe import build_goe_europe_campaign
from gates_of_codex.frontend import (
    FRONTEND_SCHEMA_VERSION,
    build_frontend_apply_invocation,
    build_frontend_snapshot,
)


class FrontendWritebackContractTests(unittest.TestCase):
    def test_control_exports_exact_python_path_with_spaces(self) -> None:
        state = build_goe_europe_campaign()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Gates of Code X"
            fake_python = root / ".venv" / "Scripts" / "python executable.exe"
            campaign = root / "live campaign" / "campaign.json"
            snapshot_path = root / "godot client" / "campaign snapshot.json"
            with patch("gates_of_codex.frontend.sys.executable", str(fake_python)):
                snapshot = build_frontend_snapshot(
                    state,
                    campaign_path=campaign,
                    snapshot_path=snapshot_path,
                )

        control = snapshot["control"]
        expected_python = str(fake_python.resolve())
        self.assertEqual(expected_python, control["python_executable"])
        self.assertEqual("gates_of_codex", control["python_module"])

        executable, arguments = build_frontend_apply_invocation(control)
        self.assertEqual(expected_python, executable)
        self.assertEqual("-m", arguments[0])
        self.assertEqual("gates_of_codex", arguments[1])
        self.assertIn(str(campaign.resolve()), arguments)
        self.assertIn(str(snapshot_path.resolve()), arguments)
        self.assertIn(str(snapshot_path.resolve().with_name("frontend_commands.json")), arguments)

        round_trip = json.loads(json.dumps(snapshot))
        self.assertEqual(expected_python, round_trip["control"]["python_executable"])
        self.assertEqual("marker_non_authoritative", round_trip["strategic_map"]["fallback"])
        manifest_parts = Path(round_trip["strategic_map"]["manifest_path"]).parts
        self.assertEqual(
            ("assets", "maps", "europe", "interim_goe", "map_manifest.json"),
            manifest_parts[-5:],
        )

    def test_snapshot_preserves_two_battalions_in_one_province(self) -> None:
        state = build_goe_europe_campaign()
        battalions = sorted(state.battalions.values(), key=lambda value: value.battalion_id)
        first = battalions[0]
        second = next(value for value in battalions[1:] if value.faction == first.faction)
        second.province_id = first.province_id

        snapshot = build_frontend_snapshot(state)
        expected_ids = sorted([first.battalion_id, second.battalion_id])
        stack_ids = snapshot["battalion_stacks"][first.province_id]
        province = next(
            value for value in snapshot["provinces"] if value["id"] == first.province_id
        )

        self.assertEqual(FRONTEND_SCHEMA_VERSION, snapshot["schema_version"])
        self.assertEqual(expected_ids, stack_ids)
        self.assertEqual(expected_ids, province["occupied_by_battalions"])
        self.assertEqual(expected_ids[0], province["occupied_by"])
        self.assertEqual(
            expected_ids,
            sorted(
                value["id"]
                for value in snapshot["battalions"]
                if value["province_id"] == first.province_id
            ),
        )

    def test_campaign_validation_rejects_mixed_faction_on_legacy_maps(self) -> None:
        """Legacy maps without operational graph still forbid hostile co-presence."""
        state = build_goe_europe_campaign()
        from gates_of_codex.force_migration import ensure_strategic_formations

        ensure_strategic_formations(state)
        for force in state.strategic_formations.values():
            force.position = None
        state.map_metadata.pop("operational_graph", None)
        battalions = sorted(state.battalions.values(), key=lambda value: value.battalion_id)
        first = battalions[0]
        hostile = next(value for value in battalions[1:] if value.faction != first.faction)
        hostile.province_id = first.province_id
        force = state.strategic_formations.get(hostile.strategic_formation_id)
        if force is not None:
            force.province_id = first.province_id
            force.position = None
        with self.assertRaisesRegex(ValueError, "multiple factions"):
            state.validate()

    def test_godot_stack_fixture_and_exact_invocation_contract(self) -> None:
        root = Path(__file__).resolve().parents[1]
        fixture = json.loads(
            (root / "tests/fixtures/frontend/two_battalions_one_province.json").read_text(
                encoding="utf-8"
            )
        )
        script = (root / "godot/scripts/main_writeback.gd").read_text(encoding="utf-8")
        color_client = (root / "godot/scripts/main_color_id.gd").read_text(encoding="utf-8")
        map_contract = (root / "godot/scripts/main_map_contract.gd").read_text(encoding="utf-8")
        scene = (root / "godot/main.tscn").read_text(encoding="utf-8")

        self.assertEqual(
            ["alpha-battalion", "bravo-battalion"],
            fixture["battalion_stacks"]["Warszawa"],
        )
        self.assertEqual(
            {"alpha-battalion", "bravo-battalion"},
            {
                value["battalion_id"]
                for value in fixture["front_options"]
                if value["origin"] == "Warszawa"
            },
        )
        self.assertTrue(
            "res://scripts/main_map_contract.gd" in scene
            or "res://scripts/main_stack_panel.gd" in scene,
            msg="main.tscn must use map contract or stack panel client",
        )
        self.assertIn('extends "res://scripts/main_color_id.gd"', map_contract)
        self.assertIn('extends "res://scripts/main_writeback.gd"', color_client)
        self.assertIn("battalion_stacks_by_province", script)
        self.assertIn(".append(battalion)", script)
        self.assertIn("selected_battalion_id", script)
        self.assertIn("FileAccess.file_exists(python_executable)", script)
        self.assertIn("OS.execute(python_executable, python_args", script)


if __name__ == "__main__":
    unittest.main()
