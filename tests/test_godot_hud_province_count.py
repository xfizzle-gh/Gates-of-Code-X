from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "godot/scripts/main_color_id.gd"
PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean"
HASH = "f3931d2e34558e451d02a7c49270b2071a79a628668c49228f5ff607a75315b8"


class GodotHudProvinceCountTests(unittest.TestCase):
    def test_hud_uses_loaded_map_count_not_snapshot_size(self) -> None:
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn("func _loaded_province_count()", src)
        self.assertIn("_loaded_province_count()", src)
        # Must not feed HUD from snapshot province list length alone.
        self.assertNotRegex(
            src,
            r'Provinces:\s*%s".*snapshot\.get\("provinces"',
        )
        # Diag line must call loaded count helper.
        diag = re.search(
            r'var diag := "Map:.*Provinces: %s.*\n(?:.*\n){0,6}',
            src,
        )
        self.assertIsNotNone(diag)
        block = diag.group(0)
        self.assertIn("_loaded_province_count()", block)
        self.assertNotIn('snapshot.get("provinces", []).size()', block)

    def test_loaded_dataset_count_matches_authority(self) -> None:
        ds = json.loads((PROD / "polygon_dataset.json").read_text(encoding="utf-8"))
        meta = json.loads((PROD / "dataset_meta.json").read_text(encoding="utf-8"))
        auth = json.loads((ROOT / "config/earth3/production_authority.json").read_text(encoding="utf-8"))
        self.assertEqual(int(ds["province_count"]), len(ds["provinces"]))
        self.assertEqual(int(ds["province_count"]), int(meta["province_count"]))
        self.assertEqual(int(ds["province_count"]), int(auth["province_count"]))
        self.assertEqual(ds["included_source_ids_sha256"], HASH)
        self.assertEqual(int(ds["province_count"]), 3514)

    def test_exterior_border_suppress_present(self) -> None:
        ds = json.loads((PROD / "polygon_dataset.json").read_text(encoding="utf-8"))
        suppress = ds.get("exterior_border_suppress") or []
        self.assertGreater(len(suppress), 100)
        pmap = (ROOT / "godot/scripts/polygon_map.gd").read_text(encoding="utf-8")
        self.assertIn("exterior_border_suppress", pmap)
        self.assertIn("_suppress_border_keys", pmap)


if __name__ == "__main__":
    unittest.main()
