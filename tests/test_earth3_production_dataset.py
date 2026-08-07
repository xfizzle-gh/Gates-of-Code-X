from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "godot/assets/maps/earth3_europe_mediterranean/dataset_meta.json"
MANIFEST = ROOT / "godot/assets/maps/earth3_europe_mediterranean/map_manifest.json"
DATASET = ROOT / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
# Mask v6 provisional (pending owner visual approval).
PROVISIONAL_HASH = "4fe9d98bbf40d2588286d3d4ec5513ffa3a8f0b7b2ae5689373217b4cb569a1b"
PROVISIONAL_COUNT = 3345


@unittest.skipUnless(META.is_file(), "Earth3 production dataset meta missing")
class Earth3ProductionDatasetTests(unittest.TestCase):
    def test_counts_and_approved_hash(self) -> None:
        meta = json.loads(META.read_text(encoding="utf-8"))
        self.assertEqual(meta["province_count"], PROVISIONAL_COUNT)
        self.assertEqual(meta["land_count"], 3133)
        self.assertEqual(meta["water_count"], 212)
        self.assertEqual(meta["approved_included_ids_sha256"], PROVISIONAL_HASH)
        self.assertEqual(meta["included_source_ids_sha256"], PROVISIONAL_HASH)
        self.assertGreater(meta["triangle_count"], 100000)
        self.assertGreater(meta["edge_count"], 1000)

    def test_manifest_polygon_renderer(self) -> None:
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(man["schema"], "gates-of-codex.strategic-map")
        self.assertEqual(man["renderer"], "polygon_mesh")
        self.assertEqual(man["map_id"], "earth3_europe_mediterranean")
        self.assertEqual(man["fallback_map_id"], "europe_mediterranean_from_goe")
        self.assertEqual(man["province_count"], PROVISIONAL_COUNT)

    @unittest.skipUnless(DATASET.is_file(), "full polygon dataset missing")
    def test_dataset_adjacency_and_ids(self) -> None:
        data = json.loads(DATASET.read_text(encoding="utf-8"))
        self.assertEqual(data["province_count"], PROVISIONAL_COUNT)
        ids = {p["id"] for p in data["provinces"]}
        self.assertEqual(len(ids), PROVISIONAL_COUNT)
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
