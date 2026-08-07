from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INV = ROOT / "docs/earth3-crop/hydrography_audit/marked_features.json"
PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean"
HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"


class Earth3HydrographyAuditTests(unittest.TestCase):
    @unittest.skipUnless(INV.is_file(), "hydrography audit inventory missing")
    def test_inventory_complete_and_production_untouched(self) -> None:
        inv = json.loads(INV.read_text(encoding="utf-8"))
        self.assertEqual(inv["production_authority"]["provinces"], 3510)
        self.assertEqual(inv["production_authority"]["included_ids_sha256"], HASH)
        feats = inv["features"]
        self.assertGreaterEqual(len(feats), 10)
        labels = {f["review_label"] for f in feats}
        self.assertIn("NE01_Kolguyev", labels)
        self.assertIn("NE02_Ladoga", labels)
        self.assertIn("NE03_Onega", labels)
        self.assertIn("MED01_Ibiza", labels)
        for f in feats:
            self.assertNotEqual(f.get("recommended_action"), "")
            self.assertNotIn("a hole", (f.get("evidence") or "").lower())
            self.assertIn(f["recommended_action"], {
                "CONFIRMED_REAL_WATER_KEEP",
                "CONFIRMED_REAL_ISLAND_RESTORE_FILL",
                "CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP",
                "CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER",
                "CONFIRMED_MISSING_LAND_RESTORE",
                "CONFIRMED_RENDERER_HOLE_FIX",
                "UNRESOLVED_REQUIRES_OWNER_RULING",
            })
        # Production path still 3510
        meta = json.loads((PROD / "dataset_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["province_count"], 3510)
        self.assertEqual(meta["included_source_ids_sha256"], HASH)
        # Unresolved must not claim production_change_allowed
        for f in feats:
            if f["recommended_action"] == "UNRESOLVED_REQUIRES_OWNER_RULING":
                self.assertFalse(f.get("production_change_allowed"))
        # No empty land meshes in production
        ds = json.loads((PROD / "polygon_dataset.json").read_text(encoding="utf-8"))
        for p in ds["provinces"]:
            if p.get("is_water"):
                continue
            self.assertGreaterEqual(len(p.get("triangles") or []), 3, p["id"])
        # Simplified islands still land with fill
        for sid in (2274, 4693, 270, 3220):
            row = next(p for p in ds["provinces"] if int(p["source_id"]) == sid)
            self.assertFalse(row.get("is_water"))
            self.assertGreaterEqual(len(row.get("triangles") or []), 3)


if __name__ == "__main__":
    unittest.main()
