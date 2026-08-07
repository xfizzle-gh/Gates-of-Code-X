from __future__ import annotations
import json, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / "config/earth3/production_authority.json"
META = ROOT / "godot/assets/maps/earth3_europe_mediterranean/dataset_meta.json"
DS = ROOT / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
STABLE = ROOT / "docs/earth3-crop/topology_sanitize/production_promotion/stable_id_report.json"
PRE = "507b0069a9572e915059ff6d21bd9f13a68cf62a26770c94a90c0b0e6a900be7"
HASH = "f3931d2e34558e451d02a7c49270b2071a79a628668c49228f5ff607a75315b8"
EXCLUDE = {10920, 11031}
GAPS = {"e3_2830", "e3_2888"}

class Earth3ProductionSpillExclusionTests(unittest.TestCase):
    def test_authority_and_counts(self):
        auth = json.loads(AUTH.read_text(encoding="utf-8"))
        meta = json.loads(META.read_text(encoding="utf-8"))
        self.assertEqual(auth["province_count"], 3514)
        self.assertEqual(auth["land_count"], 3299)
        self.assertEqual(auth["water_count"], 215)
        self.assertEqual(auth["included_ids_sha256"], HASH)
        self.assertEqual(auth["pre_sanitize_included_ids_sha256"], PRE)
        self.assertEqual(set(auth["excluded_source_ids"]), EXCLUDE)
        self.assertTrue(auth["topology_sanitize"]["land_exclusions_accepted"])
        self.assertTrue(auth["water_policy"]["accepted"])
        self.assertEqual(meta["province_count"], 3514)
        self.assertEqual(meta["included_source_ids_sha256"], HASH)

    def test_stable_ids_and_no_excluded_provinces(self):
        data = json.loads(DS.read_text(encoding="utf-8"))
        ids = {p["id"] for p in data["provinces"]}
        srcs = {int(p["source_id"]) for p in data["provinces"]}
        self.assertTrue(GAPS.isdisjoint(ids))
        self.assertTrue(EXCLUDE.isdisjoint(srcs))
        self.assertEqual(len(ids), 3514)
        for p in data["provinces"]:
            self.assertGreaterEqual(len(p["vertices"]), 6)
            self.assertGreaterEqual(len(p["triangles"]), 3)
            for n in p.get("neighbors", []):
                self.assertIn(n, ids)
        rep = json.loads(STABLE.read_text(encoding="utf-8"))
        self.assertTrue(rep["checks"]["no_global_renumber"])
        self.assertTrue(rep["checks"]["island_geometry_unchanged"])
        self.assertEqual(rep["production_hash"], HASH)

if __name__ == "__main__":
    unittest.main()
