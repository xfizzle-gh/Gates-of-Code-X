from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "godot/scripts/main_color_id.gd"
PROFILER = ROOT / "godot/scripts/tools/map_interactive_profiler.gd"


class GodotOverlayInfrastructureActiveSetTests(unittest.TestCase):
    def test_infrastructure_ids_enter_active_set(self) -> None:
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn("var _infra_province_ids", src)
        self.assertIn("func _ensure_snapshot_overlay_indexes()", src)
        self.assertIn("func _build_overlay_active_ids()", src)
        # Cache rebuild must index supply_hub / command_post / air_base.
        self.assertIn('infra.get("supply_hub", 0)', src)
        self.assertIn('infra.get("command_post", 0)', src)
        self.assertIn('infra.get("air_base", 0)', src)
        # Active set must include infrastructure IDs (not only occupied/selected/hover/targets).
        build = re.search(
            r"func _build_overlay_active_ids\(\) -> Dictionary:([\s\S]*?)\nfunc ",
            src,
        )
        self.assertIsNotNone(build)
        body = build.group(1)
        self.assertIn("_infra_province_ids", body)
        self.assertIn("battalions_by_province", body)
        self.assertIn("selected_province_id", body)
        self.assertIn("hovered_province_id", body)
        self.assertIn("legal_targets", body)
        # Icons still drawn for each kind (PR B parity, all zooms).
        self.assertIn('infrastructure.get("supply_hub", 0)', src)
        self.assertIn('infrastructure.get("command_post", 0)', src)
        self.assertIn('infrastructure.get("air_base", 0)', src)
        self.assertIn('Color("63d69f")', src)
        self.assertIn('Color("b892ff")', src)
        self.assertIn('Color("7fe7ff")', src)

    def test_profiler_checks_unoccupied_infrastructure_active_set(self) -> None:
        src = PROFILER.read_text(encoding="utf-8")
        self.assertIn("ensure_unoccupied_infrastructure_markers_for_test", src)
        self.assertIn("overlay_routes_sites_counters", src)
        self.assertIn("infrastructure_markers", src)
        self.assertIn("get_overlay_active_province_ids_for_test", src)
        self.assertIn("in_active_set", src)


if __name__ == "__main__":
    unittest.main()
