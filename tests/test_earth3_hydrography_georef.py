from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "docs/earth3-crop/hydrography_audit/georeference_transform.json"
INV = ROOT / "docs/earth3-crop/hydrography_audit/marked_features.json"
MAIN = ROOT / "tools/earth3/hydrography_audit_main.py"
SRC_ADJ = ROOT / "docs/earth3-crop/hydrography_audit/src11836_adjacency_report.json"
SRC_VAL = ROOT / "docs/earth3-crop/hydrography_audit/src11836_preview_validation.json"
SRC_ID = ROOT / "docs/earth3-crop/hydrography_audit/source_11836_identity_report.json"
KOL_SEARCH = ROOT / "docs/earth3-crop/hydrography_audit/kolguyev_true_island_search.json"
CMP = ROOT / "docs/earth3-crop/hydrography_audit/polygon_match_old_vs_new.json"
HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"
PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean/dataset_meta.json"
OLD_KOL = ROOT / "godot/assets/maps/earth3_europe_mediterranean_kolguyev_preview"


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

    def test_source_11836_not_labelled_kolguyev(self):
        inv = json.loads(INV.read_text(encoding="utf-8"))
        blob = json.dumps(inv).lower()
        # feature labels/classes must not claim 11836 is the island
        ne01 = next(f for f in inv["features"] if f["review_label"].startswith("NE01_"))
        self.assertEqual(ne01["review_label"], "NE01_source11836_Fion_northern_Urals")
        self.assertEqual(ne01["exact_feature_identity"], "UNRESOLVED")
        self.assertEqual(ne01["geographic_classification"], "UNRESOLVED_MISSING_MAINLAND_OR_CROP_BOUNDARY_DEFECT")
        self.assertFalse(ne01.get("production_change_allowed", False))
        self.assertNotIn("kolguyev island", (ne01.get("exact_feature_identity") or "").lower())
        self.assertTrue(SRC_ID.is_file())
        ident = json.loads(SRC_ID.read_text(encoding="utf-8"))
        self.assertEqual(ident["rejected_identity"], "NOT_Kolguyev_island")
        self.assertFalse(ident["behaves_as_island"])
        # no old preview path
        self.assertFalse(OLD_KOL.exists())
        # main + inventory should not market 11836 as Kolguyev restore
        main = MAIN.read_text(encoding="utf-8").lower()
        self.assertIn("not kolguyev", main)
        self.assertNotIn("confirmed_missing_land_restore", ne01["geographic_classification"].lower())

    def test_true_kolguyev_search_present(self):
        ks = json.loads(KOL_SEARCH.read_text(encoding="utf-8"))
        self.assertIn("candidates", ks)
        # 11836 must not be accepted as the island
        self.assertNotEqual(ks.get("accepted_kolguyev_source_id"), 11836)

    def test_exact_geometry_and_meter_metrics(self):
        inv = json.loads(INV.read_text(encoding="utf-8"))
        self.assertEqual(inv["production_authority"]["included_ids_sha256"], HASH)
        self.assertEqual(json.loads(PROD.read_text(encoding="utf-8"))["province_count"], 3510)
        for f in inv["features"]:
            gm = f.get("geometry_meta") or {}
            self.assertEqual(gm.get("geometry_source"), "emitted_triangle_union", f["review_label"])
            self.assertFalse(gm.get("used_convex_hull", True), f["review_label"])
            self.assertFalse(gm.get("used_synthetic_geometry", True), f["review_label"])
            self.assertLessEqual(float(gm.get("reconstruction_relative_error", 1)), 1e-4, f["review_label"])
            if f["geographic_classification"].startswith("UNRESOLVED"):
                self.assertFalse(f.get("production_change_allowed", False))
            if f["confidence"] == "high" and f["geographic_classification"] == "CONFIRMED_REAL_WATER_KEEP":
                top = (f.get("polygon_matches") or [None])[0]
                self.assertIsNotNone(top, f["review_label"])
                self.assertEqual(top.get("metric_units"), "meters_laea", f["review_label"])
                ok = (
                    float(top.get("iou") or 0) >= 0.15
                    or float(top.get("earth3_coverage_by_ref") or 0) >= 0.25
                    or (
                        float(top.get("centroid_separation_km") or 999) < 40
                        and float(top.get("iou") or 0) >= 0.05
                    )
                )
                self.assertTrue(ok, f"{f['review_label']} high-confidence below thresholds: {top}")

    def test_src11836_preview_mainland_adjacency_and_full_row_audit(self):
        adj = json.loads(SRC_ADJ.read_text(encoding="utf-8"))
        self.assertTrue(adj.get("not_kolguyev"))
        self.assertTrue(adj.get("diagnostic_only"))
        self.assertTrue(adj.get("id_not_reserved_for_production"))
        self.assertTrue(adj.get("not_centroid_radius"))
        # mainland must not force empty neighbors
        self.assertIsInstance(adj.get("direct_land_neighbors"), list)
        val = json.loads(SRC_VAL.read_text(encoding="utf-8"))
        self.assertTrue(val.get("all_pass"), val.get("checks"))
        c = val["checks"]
        self.assertEqual(c["province_count_checked"], 3511)
        self.assertTrue(c["all_3511_triangle_rows_valid"])
        self.assertTrue(c["no_empty_land_meshes"])
        self.assertTrue(c["no_empty_water_meshes"])
        self.assertTrue(c["no_dangling_adjacency"])
        self.assertTrue(c["no_stable_id_mismatches"])
        self.assertEqual(c["failed_triangulations_land_and_water"], 0)
        self.assertTrue(c["production_dataset_unchanged"])
        self.assertEqual(c["source_11836_count"], 1)
        self.assertEqual(c["e3_2830_count"], 0)
        self.assertEqual(c["e3_2888_count"], 0)

    def test_old_vs_new_comparison_present(self):
        cmp = json.loads(CMP.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cmp), 8)

    def test_no_stale_kolguyev_11836_filenames(self):
        ev = ROOT / "docs/earth3-crop/hydrography_audit/evidence"
        for p in ev.glob("*"):
            name = p.name.lower()
            self.assertNotIn("kolguyev", name)
            self.assertNotIn("volga_mid_reservoir", name)
            self.assertNotIn("cheboksary_system", name)
            self.assertNotIn("kuybyshev_samara", name)


if __name__ == "__main__":
    unittest.main()
