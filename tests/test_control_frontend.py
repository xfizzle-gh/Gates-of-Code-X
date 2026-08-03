from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from gates_of_codex.cli import build_parser
from gates_of_codex.control import CONTROL_PROFILE_ID
from gates_of_codex.europe import build_goe_europe_campaign
from gates_of_codex.formations import FORMATION_DEPLOYMENTS
from gates_of_codex.frontend import FRONTEND_SCHEMA_VERSION, build_frontend_snapshot, write_frontend_snapshot
from gates_of_codex.models import Faction


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

    def test_frontend_snapshot_writes_valid_json(self) -> None:
        state = build_goe_europe_campaign()
        with tempfile.TemporaryDirectory() as temporary:
            destination = write_frontend_snapshot(state, Path(temporary) / "campaign_snapshot.json")
            payload = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(517, len(payload["provinces"]))
        self.assertEqual("modern_europe_v1", payload["campaign"]["map_metadata"]["modern_control_profile"])

    def test_cli_exposes_frontend_export(self) -> None:
        args = build_parser().parse_args(
            ["export-frontend", "campaign.json", "--output", "godot/campaign_snapshot.json"]
        )
        self.assertEqual("export-frontend", args.command)
        self.assertEqual("godot/campaign_snapshot.json", args.output)

    def test_godot_scaffold_is_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "godot/project.godot").is_file())
        self.assertTrue((root / "godot/main.tscn").is_file())
        script = (root / "godot/scripts/main.gd").read_text(encoding="utf-8")
        self.assertIn("gates-of-codex.frontend", script)
        self.assertIn("func _draw()", script)


if __name__ == "__main__":
    unittest.main()
