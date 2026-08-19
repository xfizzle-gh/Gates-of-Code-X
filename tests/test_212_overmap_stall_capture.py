from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OvermapStallCaptureContractTests(unittest.TestCase):
    def test_profiler_accepts_owner_snapshot_and_stays_read_only(self) -> None:
        script = (ROOT / "godot/scripts/tools/map_overmap_stall_capture.gd").read_text(
            encoding="utf-8"
        )
        wrapper = (ROOT / "tools/run_overmap_stall_capture.ps1").read_text(encoding="utf-8")
        self.assertIn("--snapshot=", script)
        self.assertIn("--campaign=", script)
        self.assertIn("Does not write the owner campaign", script)
        self.assertIn("read_only", script)
        self.assertIn("comparison", script)
        self.assertIn("input_to_visible_ms", script)
        self.assertIn("max_ms", script)
        self.assertIn("Owner campaign files are not written.", wrapper)
        self.assertIn("last_campaign.json", wrapper)
        self.assertNotIn("save_campaign", script)
        self.assertNotIn("auto_resolve", script)

    def test_wrapper_defaults_to_last_campaign_snapshot(self) -> None:
        wrapper = (ROOT / "tools/run_overmap_stall_capture.ps1").read_text(encoding="utf-8")
        self.assertIn("campaign_snapshot.json", wrapper)
        self.assertIn("map_overmap_stall_capture.gd", wrapper)

    def test_byte_attribution_is_read_only_and_ranks_top_keys(self) -> None:
        script = (ROOT / "tools/attribute_snapshot_bytes.py").read_text(encoding="utf-8")
        self.assertIn("overmap-snapshot-bytes", script)
        self.assertIn("operational_orders", script)
        self.assertIn("compact_bytes", script)
        self.assertNotIn("write_text(snapshot", script)

    def test_owner_ablation_covers_requested_layers_and_stays_read_only(self) -> None:
        script = (ROOT / "godot/scripts/tools/map_overmap_owner_ablation.gd").read_text(
            encoding="utf-8"
        )
        wrapper = (ROOT / "tools/run_overmap_owner_ablation.ps1").read_text(encoding="utf-8")
        for probe in (
            "land_fill",
            "ocean_mesh",
            "shared_borders",
            "labels",
            "formation_counters",
            "infrastructure_sites",
            "routes",
            "legal_targets_focus",
            "operational_orders",
            "map_debug",
        ):
            self.assertIn(probe, script)
        self.assertIn("Does not write the owner campaign", script)
        self.assertIn("Owner campaign files are not written.", wrapper)
        self.assertNotIn("save_campaign", script)
        self.assertNotIn("auto_resolve", script)


if __name__ == "__main__":
    unittest.main()
