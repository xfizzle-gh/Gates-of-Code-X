from __future__ import annotations

import unittest
from pathlib import Path

from gates_of_codex.world_map_prototype import (
    lonlat_to_pixel,
    rgb_for_index,
    SETTLEMENT_GEO,
)


class WorldMapPrototypeTests(unittest.TestCase):
    def test_lonlat_to_pixel_corners(self) -> None:
        self.assertEqual((0, 0), lonlat_to_pixel(-180, 90, 2048, 1024))
        self.assertEqual((2047, 1023), lonlat_to_pixel(180, -90, 2048, 1024))
        x, y = lonlat_to_pixel(0, 0, 2048, 1024)
        self.assertAlmostEqual(1024, x, delta=2)
        self.assertAlmostEqual(512, y, delta=2)

    def test_rgb_ids_are_unique_for_seed_range(self) -> None:
        colors = {rgb_for_index(i) for i in range(200)}
        self.assertEqual(200, len(colors))

    def test_public_geo_table_covers_core_european_cities(self) -> None:
        for key in ("paris", "berlin", "london", "rome", "madrid"):
            self.assertIn(key, SETTLEMENT_GEO)

    def test_generated_world_assets_exist_when_committed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = root / "godot/assets/maps/world/prototype/map_manifest.json"
        texture = root / "godot/assets/maps/world/prototype/world_id_map.png"
        if not manifest.is_file():
            self.skipTest("world prototype assets not generated in this checkout")
        import json

        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual("world_prototype", payload["map_id"])
        self.assertGreaterEqual(int(payload["province_count"]), 80)
        self.assertEqual(2048, int(payload["id_texture"]["width"]))
        self.assertEqual(1024, int(payload["id_texture"]["height"]))
        self.assertTrue(texture.is_file())
        self.assertNotEqual(1314, int(payload["id_texture"]["width"]))
        self.assertNotEqual(517, int(payload["province_count"]))


if __name__ == "__main__":
    unittest.main()
