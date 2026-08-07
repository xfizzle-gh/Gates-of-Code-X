from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "godot/assets/maps/earth3_europe_mediterranean/dataset_meta.json"
MANIFEST = ROOT / "godot/assets/maps/earth3_europe_mediterranean/map_manifest.json"
DATASET = ROOT / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
AUTH = ROOT / "config/earth3/production_authority.json"
PRE_HASH = "507b0069a9572e915059ff6d21bd9f13a68cf62a26770c94a90c0b0e6a900be7"
APPROVED_HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"
APPROVED_COUNT = 3510
EXCLUDE_GATES = {"e3_2830", "e3_2888"}


@unittest.skipUnless(META.is_file(), "Earth3 production dataset meta missing")
class Earth3ProductionDatasetTests(unittest.TestCase):
    def test_counts_and_approved_hash(self) -> None:
        meta = json.loads(META.read_text(encoding="utf-8"))
        self.assertEqual(meta["province_count"], APPROVED_COUNT)
        self.assertEqual(meta["land_count"], 3295)
        self.assertEqual(meta["water_count"], 215)
        self.assertEqual(meta["included_source_ids_sha256"], APPROVED_HASH)
        self.assertEqual(meta.get("pre_sanitize_included_ids_sha256"), PRE_HASH)
        self.assertGreater(meta["triangle_count"], 100000)
        self.assertGreater(meta["edge_count"], 1000)
        if AUTH.is_file():
            auth = json.loads(AUTH.read_text(encoding="utf-8"))
            self.assertEqual(auth["included_ids_sha256"], APPROVED_HASH)
            self.assertEqual(auth["province_count"], APPROVED_COUNT)

    def test_manifest_polygon_renderer(self) -> None:
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(man["schema"], "gates-of-codex.strategic-map")
        self.assertEqual(man["renderer"], "polygon_mesh")
        self.assertEqual(man["map_id"], "earth3_europe_mediterranean")
        self.assertEqual(man["fallback_map_id"], "europe_mediterranean_from_goe")
        self.assertEqual(man["province_count"], APPROVED_COUNT)
        self.assertEqual(man.get("included_source_ids_sha256"), APPROVED_HASH)

    @unittest.skipUnless(DATASET.is_file(), "full polygon dataset missing")
    def test_dataset_adjacency_and_ids(self) -> None:
        data = json.loads(DATASET.read_text(encoding="utf-8"))
        self.assertEqual(data["province_count"], APPROVED_COUNT)
        ids = {p["id"] for p in data["provinces"]}
        self.assertEqual(len(ids), APPROVED_COUNT)
        self.assertTrue(EXCLUDE_GATES.isdisjoint(ids))
        for p in data["provinces"]:
            self.assertTrue(p["id"].startswith("e3_"))
            self.assertIn("source_id", p)
            self.assertGreaterEqual(len(p["vertices"]), 6)
            self.assertGreaterEqual(len(p["triangles"]), 3)
            for n in p.get("neighbors", []):
                self.assertIn(n, ids)
        for a, b in data.get("edges", []):
            self.assertIn(a, ids)
            self.assertIn(b, ids)


if __name__ == "__main__":
    unittest.main()
