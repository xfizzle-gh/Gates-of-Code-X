from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "docs/earth3-crop/hydrography_audit/georeference_transform.json"
INV = ROOT / "docs/earth3-crop/hydrography_audit/marked_features.json"
MAIN = ROOT / "tools/earth3/hydrography_audit_main.py"
TRACE = ROOT / "docs/earth3-crop/hydrography_audit/owner_circle_render_trace.json"
SRC_ID = ROOT / "docs/earth3-crop/hydrography_audit/source_11836_identity_report.json"
KOL_SEARCH = ROOT / "docs/earth3-crop/hydrography_audit/kolguyev_true_island_search.json"
CMP = ROOT / "docs/earth3-crop/hydrography_audit/polygon_match_old_vs_new.json"
HASH = "f3931d2e34558e451d02a7c49270b2071a79a628668c49228f5ff607a75315b8"
PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean/dataset_meta.json"
OLD_KOL = ROOT / "godot/assets/maps/earth3_europe_mediterranean_kolguyev_preview"
SRC_PREV = ROOT / "godot/assets/maps/earth3_europe_mediterranean_src11836_preview"


class Earth3HydrographyGeorefTests(unittest.TestCase):
    def test_loo_and_no_fake_zero_validated_rms(self):
        t = json.loads(T.read_text(encoding="utf-8"))
        self.assertTrue(t.get("source_11836_is_not_kolguyev"))
        loo = t["leave_one_out"]
        self.assertGreater(loo["rms_km"], 0.0)
        self.assertGreaterEqual(loo["by_region"].get("ne_russia_north", {}).get("n", 0), 5)
        tol = t["fixed_control_tolerances_km"]
        loo_map = {r["label"]: r["error_km"] for r in loo["residuals"]}
        for lab, max_km in tol.items():
            if lab in loo_map:
                self.assertLessEqual(loo_map[lab], max_km, lab)

    def test_no_hardcoded_home_archive_path(self):
        txt = MAIN.read_text(encoding="utf-8")
        self.assertNotIn(r"C:\\Users\\paulf\\Downloads", txt)
        self.assertIn("GATES_EARTH3_ARCHIVE", txt)

    def test_source_11836_not_kolguyev_and_no_preview_asset(self):
        self.assertTrue(SRC_ID.is_file())
        ident = json.loads(SRC_ID.read_text(encoding="utf-8"))
        self.assertEqual(ident["rejected_identity"], "NOT_Kolguyev_island")
        self.assertFalse(ident["behaves_as_island"])
        self.assertFalse(OLD_KOL.exists())
        self.assertFalse(SRC_PREV.exists())
        main = MAIN.read_text(encoding="utf-8").lower()
        self.assertIn("not kolguyev", main)

    def test_owner_circle_render_trace(self):
        tr = json.loads(TRACE.read_text(encoding="utf-8"))
        by = {c["review_label"]: c for c in tr["circles"]}
        self.assertIn("NE01_northern_outline", by)
        ne01 = by["NE01_northern_outline"]
        self.assertEqual(ne01["final_classification"], "CROP_EDGE_PRESENTATION_ARTIFACT")
        self.assertEqual(ne01.get("archive_land_at_point", {}).get("source_id"), 11836)
        self.assertFalse(ne01.get("archive_land_in_production"))
        self.assertFalse(ne01["geography_compare"].get("is_kolguyev", True))
        for lab in (
            "NE04_WhiteSea_SE_large_hole",
            "NE06_Galich_area",
            "NE07_east_volga",
            "NE08_kama_volga",
        ):
            self.assertEqual(by[lab]["final_classification"], "SOURCE_GEOMETRY_DEFECT", lab)
            self.assertTrue(by[lab].get("explicit_exclude", {}).get("is_explicit_exclude"), lab)
        for lab in ("NE02_Ladoga", "NE03_Onega", "NE05_Rybinsk"):
            self.assertEqual(by[lab]["final_classification"], "REAL_WATER_KEEP", lab)
        self.assertFalse(tr["godot_rules"]["ocean_gap_fills_meshed_in_godot"])

    def test_true_kolguyev_search_present(self):
        ks = json.loads(KOL_SEARCH.read_text(encoding="utf-8"))
        self.assertIn("candidates", ks)
        self.assertNotEqual(ks.get("accepted_kolguyev_source_id"), 11836)

    def test_exact_geometry_and_meter_metrics(self):
        inv = json.loads(INV.read_text(encoding="utf-8"))
        self.assertEqual(inv["production_authority"]["included_ids_sha256"], HASH)
        self.assertEqual(json.loads(PROD.read_text(encoding="utf-8"))["province_count"], 3514)
        for f in inv["features"]:
            self.assertFalse(f.get("production_change_allowed", False))
            if f.get("geometry_meta"):
                gm = f["geometry_meta"]
                self.assertEqual(gm.get("geometry_source"), "emitted_triangle_union", f["review_label"])
                self.assertFalse(gm.get("used_convex_hull", True), f["review_label"])
                self.assertFalse(gm.get("used_synthetic_geometry", True), f["review_label"])
            if f["confidence"] == "high" and f["geographic_classification"] == "CONFIRMED_REAL_WATER_KEEP":
                top = (f.get("polygon_matches") or [None])[0]
                self.assertIsNotNone(top, f["review_label"])
                self.assertEqual(top.get("metric_units"), "meters_laea", f["review_label"])

    def test_inventory_ne01_not_missing_land_restore(self):
        inv = json.loads(INV.read_text(encoding="utf-8"))
        ne01 = next(f for f in inv["features"] if f["review_label"].startswith("NE01"))
        self.assertEqual(ne01["review_label"], "NE01_northern_outline")
        self.assertEqual(ne01["geographic_classification"], "CROP_EDGE_PRESENTATION_ARTIFACT")
        self.assertEqual(ne01["exact_feature_identity"], "UNRESOLVED")
        self.assertNotIn("CONFIRMED_MISSING_LAND_RESTORE", ne01["geographic_classification"])

    def test_old_vs_new_comparison_present(self):
        cmp = json.loads(CMP.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cmp), 8)

    def test_no_stale_rejected_filenames(self):
        ev = ROOT / "docs/earth3-crop/hydrography_audit/evidence"
        for p in ev.glob("*"):
            name = p.name.lower()
            self.assertNotIn("kolguyev", name)
            self.assertNotIn("volga_mid_reservoir", name)
            self.assertNotIn("cheboksary_system", name)
            self.assertNotIn("kuybyshev_samara", name)


if __name__ == "__main__":
    unittest.main()
