from __future__ import annotations
import json, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "docs/earth3-crop/hydrography_audit/georeference_transform.json"
INV = ROOT / "docs/earth3-crop/hydrography_audit/marked_features.json"
HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"

class Earth3HydrographyGeorefTests(unittest.TestCase):
    def test_georef_critical_points_within_threshold(self):
        t = json.loads(T.read_text(encoding="utf-8"))
        thr = float(t["high_confidence_position_threshold_km"])
        crit = t["piecewise_validation"]["critical_point_errors_km"]
        for k in ("Ibiza", "Valletta", "Myrina_Lemnos", "Pantelleria"):
            self.assertIn(k, crit)
            self.assertLessEqual(float(crit[k]), thr, k)
        # Med residual should be tight
        self.assertLessEqual(t["regions"]["mediterranean_na"]["rms_km"], 20.0)

    def test_inventory_has_split_identity_fields_and_valid_coords(self):
        inv = json.loads(INV.read_text(encoding="utf-8"))
        self.assertEqual(inv["production_authority"]["included_ids_sha256"], HASH)
        for f in inv["features"]:
            self.assertIn("geographic_classification", f)
            self.assertIn("exact_feature_identity", f)
            self.assertIn("wgs84_lon", f)
            self.assertIn("wgs84_lat", f)
            # Reject old broken coords for Ibiza (was ~-9,28)
            if f["review_label"] == "MED01_Ibiza":
                self.assertGreater(f["wgs84_lon"], -5.0)
                self.assertLess(f["wgs84_lon"], 5.0)
                self.assertGreater(f["wgs84_lat"], 35.0)
                self.assertLess(f["wgs84_lat"], 42.0)
            if f["review_label"] == "MED03_Malta":
                self.assertGreater(f["wgs84_lon"], 10.0)
                self.assertLess(f["wgs84_lon"], 18.0)
                self.assertGreater(f["wgs84_lat"], 34.0)
                self.assertLess(f["wgs84_lat"], 37.5)
            if f["review_label"] == "NE06_Lake_Galichskoye":
                self.assertNotIn("Volga mid reservoir", f.get("hypothesis") or "")
            if f["review_label"] in ("NE07_east_volga_candidate", "NE08_kama_volga_candidate", "NE04_WhiteSea_SE_large_hole"):
                self.assertIn(f["geographic_classification"], ('UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH', 'UNRESOLVED_REQUIRES_OWNER_RULING', 'CONFIRMED_REAL_WATER_KEEP'))
                if f["geographic_classification"].startswith("UNRESOLVED"):
                    self.assertEqual(f["exact_feature_identity"], "UNRESOLVED")

if __name__ == "__main__":
    unittest.main()
