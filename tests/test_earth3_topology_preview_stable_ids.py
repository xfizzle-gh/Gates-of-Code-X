from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean"
PREV = ROOT / "godot/assets/maps/earth3_europe_mediterranean_sanitize_preview"
HASH = "507b0069a9572e915059ff6d21bd9f13a68cf62a26770c94a90c0b0e6a900be7"
EXCLUDE = {10920, 11031}
EXCLUDE_GATES = {"e3_2830", "e3_2888"}
KEEP_ISLANDS = {
    2271,
    2272,
    2273,
    2274,
    6574,
    258,
    259,
    270,
    882,
    913,
    992,
    1056,
    1154,
    3132,
    3220,
    4693,
}


class TopologyPreviewStableIdTests(unittest.TestCase):
    @unittest.skipUnless(PREV.is_dir(), "preview dataset missing")
    def test_stable_ids_exclusions_only_no_visual_overrides(self) -> None:
        prod = json.loads((PROD / "polygon_dataset.json").read_text(encoding="utf-8"))
        prev = json.loads((PREV / "polygon_dataset.json").read_text(encoding="utf-8"))
        meta = json.loads((PREV / "dataset_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(prod["province_count"], 3512)
        self.assertEqual(prod["included_source_ids_sha256"], HASH)
        self.assertEqual(meta["pre_sanitize_included_ids_sha256"], HASH)
        self.assertEqual(prev["province_count"], 3510)
        self.assertEqual(meta["land_count"], 3295)
        self.assertEqual(meta["water_count"], 215)
        self.assertEqual(set(meta["excluded_source_ids"]), EXCLUDE)
        self.assertEqual(meta.get("visual_geometry_overrides"), [])
        self.assertEqual(prev.get("sanitization_preview", {}).get("visual_geometry_overrides"), [])

        prod_map = {int(e["source_id"]): e["gates_id"] for e in prod["id_map"]}
        prod_by_src = {int(p["source_id"]): p for p in prod["provinces"]}
        prev_src = set()
        for p in prev["provinces"]:
            sid = int(p["source_id"])
            prev_src.add(sid)
            self.assertNotIn(sid, EXCLUDE)
            self.assertEqual(p["id"], prod_map[sid])
            # geometry unchanged vs production
            pp = prod_by_src[sid]
            self.assertEqual(p["ring"], pp["ring"])
            self.assertEqual(p["vertices"], pp["vertices"])
            self.assertEqual(p["triangles"], pp["triangles"])
        self.assertTrue(EXCLUDE.isdisjoint(prev_src))
        for sid in KEEP_ISLANDS:
            self.assertIn(sid, prev_src)

        # removed gates absent
        prev_ids = {p["id"] for p in prev["provinces"]}
        self.assertTrue(EXCLUDE_GATES.isdisjoint(prev_ids))

        # stable validation artifact
        rep = json.loads((PREV / "stable_id_validation.json").read_text(encoding="utf-8"))
        self.assertTrue(rep["checks"]["no_global_renumber"])
        self.assertTrue(rep["checks"]["island_geometry_unchanged"])
        self.assertTrue(rep["checks"]["no_visual_geometry_overrides"])
        self.assertTrue(rep["checks"]["fixtures_ok"])

        # no visual overrides config claiming coastline correction
        vog = ROOT / "config/earth3/visual_geometry_overrides.json"
        self.assertFalse(vog.is_file(), "visual_geometry_overrides.json must not exist in this PR")


if __name__ == "__main__":
    unittest.main()
