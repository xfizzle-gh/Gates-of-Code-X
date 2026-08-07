from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INV = ROOT / "docs/earth3-crop/hydrography_audit/marked_features.json"
PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean"
HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"
TRACE = ROOT / "docs/earth3-crop/hydrography_audit/owner_circle_render_trace.json"


class Earth3HydrographyAuditTests(unittest.TestCase):
    @unittest.skipUnless(INV.is_file(), "hydrography audit inventory missing")
    def test_inventory_complete_and_production_untouched(self) -> None:
        inv = json.loads(INV.read_text(encoding="utf-8"))
        self.assertEqual(inv["production_authority"]["provinces"], 3510)
        self.assertEqual(inv["production_authority"]["included_ids_sha256"], HASH)
        feats = inv["features"]
        self.assertGreaterEqual(len(feats), 10)
        labels = {f["review_label"] for f in feats}
        self.assertIn("NE01_northern_outline", labels)
        self.assertIn("NE02_Ladoga", labels)
        self.assertIn("NE06_Lake_Galichskoye", labels)
        for f in feats:
            self.assertIn("geographic_classification", f)
            self.assertIn("exact_feature_identity", f)
            self.assertFalse(f.get("production_change_allowed", False))
            self.assertNotIn("a hole", (f.get("evidence") or "").lower())
        meta = json.loads((PROD / "dataset_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["province_count"], 3510)
        self.assertEqual(meta["included_source_ids_sha256"], HASH)
        ds = json.loads((PROD / "polygon_dataset.json").read_text(encoding="utf-8"))
        for p in ds["provinces"]:
            if p.get("is_water"):
                continue
            self.assertGreaterEqual(len(p.get("triangles") or []), 3, p["id"])
        for sid in (2274, 4693, 270, 3220):
            row = next(p for p in ds["provinces"] if int(p["source_id"]) == sid)
            self.assertFalse(row.get("is_water"))
            self.assertGreaterEqual(len(row.get("triangles") or []), 3)
        self.assertTrue(TRACE.is_file())


if __name__ == "__main__":
    unittest.main()
