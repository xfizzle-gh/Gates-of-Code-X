from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "docs/earth3-crop/hydrography_audit/georeference_transform.json"
INV = ROOT / "docs/earth3-crop/hydrography_audit/marked_features.json"
MAIN = ROOT / "tools/earth3/hydrography_audit_main.py"
KOL_ADJ = ROOT / "docs/earth3-crop/hydrography_audit/kolguyev_adjacency_report.json"
KOL_VAL = ROOT / "docs/earth3-crop/hydrography_audit/kolguyev_preview_validation.json"
HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"
PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean/dataset_meta.json"


class Earth3HydrographyGeorefTests(unittest.TestCase):
    def test_loo_and_no_fake_zero_validated_rms(self):
        t = json.loads(T.read_text(encoding="utf-8"))
        self.assertFalse(t.get("kolguyev_is_control_point", True))
        loo = t["leave_one_out"]
        self.assertGreater(loo["rms_km"], 0.0)
        self.assertGreaterEqual(loo["by_region"].get("ne_russia_north", {}).get("n", 0), 5)
        for _rname, reg in t["regions"].items():
            if reg.get("n", 99) <= 3:
                note = reg.get("validation_note", "")
                self.assertIn("NOT independent validation", note)
        tol = t["fixed_control_tolerances_km"]
        loo_map = {r["label"]: r["error_km"] for r in loo["residuals"]}
        for lab, max_km in tol.items():
            if lab in loo_map:
                self.assertLessEqual(loo_map[lab], max_km, lab)

    def test_no_hardcoded_home_archive_path(self):
        txt = MAIN.read_text(encoding="utf-8")
        self.assertNotIn(r"C:\Users\paulf\Downloads", txt)
        self.assertIn("GATES_EARTH3_ARCHIVE", txt)

    def test_inventory_and_production_inert(self):
        inv = json.loads(INV.read_text(encoding="utf-8"))
        self.assertEqual(inv["production_authority"]["included_ids_sha256"], HASH)
        self.assertEqual(json.loads(PROD.read_text(encoding="utf-8"))["province_count"], 3510)
        for f in inv["features"]:
            self.assertIn("polygon_matches", f)
            if f["review_label"] == "MED01_Ibiza":
                self.assertGreater(f["wgs84_lon"], 0.0)
                self.assertLess(f["wgs84_lon"], 3.5)
                self.assertGreater(f["wgs84_lat"], 37.0)
            if f["geographic_classification"].startswith("UNRESOLVED"):
                self.assertFalse(f.get("production_change_allowed", False))
            if f["confidence"] == "high" and f["exact_feature_identity"] not in (
                "UNRESOLVED",
                "Kolguyev Island",
                "Ibiza",
                "Pantelleria",
                "Malta",
                "Lemnos",
            ):
                self.assertTrue(f.get("polygon_matches"), f["review_label"])

    def test_kolguyev_preview_constraints(self):
        adj = json.loads(KOL_ADJ.read_text(encoding="utf-8"))
        self.assertEqual(adj["direct_land_neighbors"], [])
        self.assertTrue(adj["confirmation_no_mainland_land_adjacency_invented"])
        val = json.loads(KOL_VAL.read_text(encoding="utf-8"))
        self.assertTrue(all(val["checks"].values()), val["checks"])
        self.assertEqual(val["summary"]["source_id"], 11836)
        self.assertNotIn(val["summary"]["gates_id"], ["e3_2830", "e3_2888"])


if __name__ == "__main__":
    unittest.main()
