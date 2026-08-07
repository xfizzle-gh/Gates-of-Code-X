from __future__ import annotations
import json, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / "config/earth3/production_authority.json"
META = ROOT / "godot/assets/maps/earth3_europe_mediterranean/dataset_meta.json"
HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"

class Earth3WaterPolicyAuthorityTests(unittest.TestCase):
    def test_exact_authority_and_water_policy_flag(self):
        auth = json.loads(AUTH.read_text(encoding="utf-8"))
        meta = json.loads(META.read_text(encoding="utf-8"))
        self.assertEqual(auth["province_count"], 3510)
        self.assertEqual(auth["land_count"], 3295)
        self.assertEqual(auth["water_count"], 215)
        self.assertEqual(auth["included_ids_sha256"], HASH)
        self.assertEqual(meta["province_count"], 3510)
        self.assertEqual(meta["included_source_ids_sha256"], HASH)
        self.assertTrue(auth["water_policy"]["accepted"])
        self.assertTrue(auth.get("topology_sanitize", {}).get("land_exclusions_accepted", False))
        poly = (ROOT / "godot/scripts/polygon_map.gd").read_text(encoding="utf-8")
        self.assertIn("water is never a normal selectable hit target", poly)
        self.assertIn("water_not_normally_selectable", json.dumps(auth["water_policy"]))

if __name__ == "__main__":
    unittest.main()
