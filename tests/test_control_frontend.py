from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from gates_of_codex.cli import build_parser, main as cli_main
from gates_of_codex.control import CONTROL_PROFILE_ID
from gates_of_codex.europe import build_goe_europe_campaign
from gates_of_codex.formations import FORMATION_DEPLOYMENTS
from gates_of_codex.frontend import FRONTEND_SCHEMA_VERSION, build_frontend_snapshot, write_frontend_snapshot
from gates_of_codex.frontend_commands import apply_frontend_commands, write_commands
from gates_of_codex.map_layout import apply_marker_layout
from gates_of_codex.models import Faction
from gates_of_codex.state_io import save_campaign


class ModernControlAndFrontendTests(unittest.TestCase):
    def test_modern_profile_assigns_every_province(self) -> None:
        state = build_goe_europe_campaign()
        counts = Counter(province.owner for province in state.provinces.values())
        self.assertEqual(517, sum(counts.values()))
        self.assertNotIn(Faction.NEUTRAL, counts)
        for faction in (Faction.NATO, Faction.UKRAINE, Faction.RUSSIA, Faction.PRC):
            self.assertGreater(counts[faction], 0)
        self.assertEqual(CONTROL_PROFILE_ID, state.map_metadata["modern_control_profile"])
        self.assertEqual(517, sum(state.map_metadata["modern_control_counts"].values()))

    def test_alliance_and_formation_anchors_are_preserved(self) -> None:
        state = build_goe_europe_campaign()
        self.assertEqual(
            {Faction.NATO, Faction.UKRAINE},
            set(state.alliances["western-coalition"].factions),
        )
        self.assertEqual(
            {Faction.RUSSIA, Faction.PRC},
            set(state.alliances["eastern-coalition"].factions),
        )
        for formation_id, province_id in FORMATION_DEPLOYMENTS.items():
            formation = state.formations[formation_id]
            self.assertEqual(formation.faction, state.provinces[province_id].owner)
            self.assertEqual(formation_id, state.provinces[province_id].metadata["formation_anchor"])
        self.assertEqual(Faction.RUSSIA, state.formations["rusa-prk-expeditionary"].faction)

    def test_frontend_snapshot_is_complete_and_deduplicated(self) -> None:
        state = build_goe_europe_campaign()
        snapshot = build_frontend_snapshot(state)
        self.assertEqual("gates-of-codex.frontend", snapshot["schema"])
        self.assertEqual(FRONTEND_SCHEMA_VERSION, snapshot["schema_version"])
        self.assertEqual(517, len(snapshot["provinces"]))
        self.assertEqual(len(state.battalions), len(snapshot["battalions"]))
        self.assertEqual(len(state.formations), len(snapshot["formations"]))
        edges = [tuple(edge) for edge in snapshot["edges"]]
        self.assertEqual(len(edges), len(set(edges)))
        self.assertTrue(all(left < right for left, right in edges))
        self.assertLess(snapshot["bounds"]["min_x"], snapshot["bounds"]["max_x"])
        self.assertLess(snapshot["bounds"]["min_y"], snapshot["bounds"]["max_y"])
        self.assertGreater(int(snapshot["campaign"]["map_metadata"]["marker_layout"]["matched"]), 100)

    def test_marker_layout_remaps_known_provinces(self) -> None:
        state = build_goe_europe_campaign()
        matched = apply_marker_layout(state)
        self.assertGreater(matched, 100)
        warsaw = state.provinces.get("Warszawa")
        self.assertIsNotNone(warsaw)
        self.assertEqual("goe_marker_layout", warsaw.metadata.get("layout_source"))

    def test_frontend_snapshot_writes_valid_json(self) -> None:
        state = build_goe_europe_campaign()
        with tempfile.TemporaryDirectory() as temporary:
            destination = write_frontend_snapshot(
                state,
                Path(temporary) / "campaign_snapshot.json",
                campaign_path=Path(temporary) / "campaign.json",
            )
            payload = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(517, len(payload["provinces"]))
        self.assertEqual("modern_europe_v1", payload["campaign"]["map_metadata"]["modern_control_profile"])
        self.assertIn("front_options", payload)
        self.assertTrue(payload["control"]["enabled"])
        self.assertTrue(payload["control"]["commands_path"].endswith("frontend_commands.json"))

    def test_cli_exposes_frontend_export(self) -> None:
        args = build_parser().parse_args(
            ["export-frontend", "campaign.json", "--output", "godot/campaign_snapshot.json"]
        )
        self.assertEqual("export-frontend", args.command)
        self.assertEqual("godot/campaign_snapshot.json", args.output)
        apply_args = build_parser().parse_args(
            [
                "apply-frontend",
                "campaign.json",
                "--snapshot",
                "godot/campaign_snapshot.json",
                "--commands",
                "godot/frontend_commands.json",
            ]
        )
        self.assertEqual("apply-frontend", apply_args.command)

    def test_apply_frontend_commands_moves_and_refreshes_snapshot(self) -> None:
        state = build_goe_europe_campaign()
        option = next(
            (
                row
                for row in build_frontend_snapshot(state)["front_options"]
                if row["kind"] in {"move", "neutral", "capture"}
            ),
            None,
        )
        self.assertIsNotNone(option)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            commands = root / "frontend_commands.json"
            save_campaign(state, campaign)
            write_frontend_snapshot(state, snapshot, campaign_path=campaign)
            write_commands(
                commands,
                [
                    {
                        "op": "move",
                        "battalion": option["battalion_id"],
                        "province": option["target"],
                    }
                ],
            )
            result = apply_frontend_commands(
                campaign,
                commands_path=commands,
                snapshot_path=snapshot,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(1, result["commands_applied"])
            refreshed = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertEqual(FRONTEND_SCHEMA_VERSION, refreshed["schema_version"])
            moved = next(
                item for item in refreshed["battalions"] if item["id"] == option["battalion_id"]
            )
            self.assertEqual(option["target"], moved["province_id"])
            self.assertEqual([], json.loads(commands.read_text(encoding="utf-8"))["commands"])

    def test_cli_apply_frontend_end_to_end(self) -> None:
        state = build_goe_europe_campaign()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            commands = root / "frontend_commands.json"
            save_campaign(state, campaign)
            write_frontend_snapshot(state, snapshot, campaign_path=campaign)
            write_commands(commands, [{"op": "end_turn"}])
            code = cli_main(
                [
                    "apply-frontend",
                    str(campaign),
                    "--snapshot",
                    str(snapshot),
                    "--commands",
                    str(commands),
                ]
            )
            self.assertEqual(0, code)
            refreshed = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertNotEqual(
                state.current_faction.value,
                refreshed["campaign"]["current_faction"],
            )

    def test_godot_scaffold_is_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "godot/project.godot").is_file())
        self.assertTrue((root / "godot/main.tscn").is_file())
        script = (root / "godot/scripts/main.gd").read_text(encoding="utf-8")
        self.assertIn("gates-of-codex.frontend", script)
        self.assertIn("func _draw()", script)
        self.assertIn("apply-frontend", script)
        self.assertIn("_queue_and_apply", script)
        self.assertIn("_fit_to_focus", script)
        self.assertIn("handoff", script)


if __name__ == "__main__":
    unittest.main()
