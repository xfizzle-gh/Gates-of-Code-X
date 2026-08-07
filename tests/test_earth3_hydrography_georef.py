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
CMP = ROOT / "docs/earth3-crop/hydrography_audit/polygon_match_old_vs_new.json"
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
                self.assertIn("NOT independent validation", reg.get("validation_note", ""))
        tol = t["fixed_control_tolerances_km"]
        loo_map = {r["label"]: r["error_km"] for r in loo["residuals"]}
        for lab, max_km in tol.items():
            if lab in loo_map:
                self.assertLessEqual(loo_map[lab], max_km, lab)

    def test_no_hardcoded_home_archive_path(self):
        txt = MAIN.read_text(encoding="utf-8")
        self.assertNotIn(r"C:\\Users\\paulf\\Downloads", txt)
        self.assertIn("GATES_EARTH3_ARCHIVE", txt)

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
            self.assertIn("polygon_matches", f)
            if f["review_label"] == "MED01_Ibiza":
                self.assertGreater(f["wgs84_lon"], 0.0)
                self.assertLess(f["wgs84_lon"], 3.5)
            if f["geographic_classification"].startswith("UNRESOLVED"):
                self.assertFalse(f.get("production_change_allowed", False))
            if f["confidence"] == "high" and f["geographic_classification"] == "CONFIRMED_REAL_WATER_KEEP":
                top = (f.get("polygon_matches") or [None])[0]
                self.assertIsNotNone(top, f["review_label"])
                self.assertEqual(top.get("metric_units"), "meters_laea", f["review_label"])
                self.assertFalse(top.get("used_degree_area", False))
                ok = (
                    float(top.get("iou") or 0) >= 0.15
                    or float(top.get("earth3_coverage_by_ref") or 0) >= 0.25
                    or (
                        float(top.get("centroid_separation_km") or 999) < 40
                        and float(top.get("iou") or 0) >= 0.05
                    )
                )
                self.assertTrue(ok, f"{f['review_label']} high-confidence below exact thresholds: {top}")

    def test_no_synthetic_or_degree_area_confirmed(self):
        inv = json.loads(INV.read_text(encoding="utf-8"))
        confirmed = {
            "CONFIRMED_REAL_WATER_KEEP",
            "CONFIRMED_MISSING_LAND_RESTORE",
            "CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP",
        }
        for f in inv["features"]:
            if f["geographic_classification"] not in confirmed:
                continue
            gm = f["geometry_meta"]
            self.assertEqual(gm["geometry_source"], "emitted_triangle_union")
            self.assertFalse(gm["used_convex_hull"])
            self.assertFalse(gm["used_synthetic_geometry"])
            for m in f.get("polygon_matches") or []:
                if f["geographic_classification"] == "CONFIRMED_REAL_WATER_KEEP":
                    self.assertEqual(m.get("metric_units"), "meters_laea")

    def test_kolguyev_preview_constraints(self):
        adj = json.loads(KOL_ADJ.read_text(encoding="utf-8"))
        self.assertEqual(adj["direct_land_neighbors"], [])
        self.assertTrue(adj["confirmation_no_mainland_land_adjacency_invented"])
        self.assertTrue(adj.get("not_centroid_radius"))
        self.assertEqual(adj.get("method"), "exact_source_ring_boundary_distance")
        self.assertTrue(adj.get("no_automatic_sea_or_ferry_adjacency"))
        val = json.loads(KOL_VAL.read_text(encoding="utf-8"))
        self.assertTrue(val.get("all_pass"), val.get("checks"))
        c = val["checks"]
        self.assertEqual(c["province_count_checked"], 3511)
        self.assertEqual(c["land_count_checked"], 3296)
        self.assertEqual(c["water_count_checked"], 215)
        self.assertEqual(c["failed_triangulations"], 0)
        self.assertEqual(c["empty_land_meshes"], 0)
        self.assertEqual(c["dangling_adjacency"], 0)
        self.assertEqual(c["retained_stable_id_mismatches"], 0)
        self.assertEqual(c["source_11836_count"], 1)
        self.assertEqual(c["e3_3512_count"], 1)
        self.assertEqual(c["e3_2830_count"], 0)
        self.assertEqual(c["e3_2888_count"], 0)
        self.assertTrue(c["production_dataset_unchanged"])
        self.assertEqual(val["summary"]["source_id"], 11836)
        self.assertNotIn(val["summary"]["gates_id"], ["e3_2830", "e3_2888"])
        bools = val.get("checks_bool") or {}
        self.assertTrue(all(bools.values()), bools)

    def test_old_vs_new_comparison_present(self):
        cmp = json.loads(CMP.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cmp), 8)
        for row in cmp:
            self.assertIn("old_iou", row)
            self.assertIn("new_iou", row)
            self.assertIn("classification_changed", row)


if __name__ == "__main__":
    unittest.main()
