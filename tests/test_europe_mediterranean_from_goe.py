from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.europe_mediterranean_from_goe import (
    MAP_ID,
    MARKER_THEATRE,
    build_europe_mediterranean_from_goe_campaign,
    generate_europe_mediterranean_from_goe,
)
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.strategic_map import decode_png_rgb


ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "godot/assets/maps/europe/interim_goe"
OUT = ROOT / "godot/assets/maps/europe_mediterranean/from_goe"
MANIFEST = OUT / "map_manifest.json"


@unittest.skipUnless(
    (INTERIM / "map_manifest.json").is_file() and (INTERIM / "province_id_map.png").is_file(),
    "interim GoE assets missing",
)
class EuropeMediterraneanFromGoeTests(unittest.TestCase):
    def test_generate_crop_preserves_ids_and_shrinks_theatre(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "from_goe"
            manifest = generate_europe_mediterranean_from_goe(output_dir=out, pad_px=8)
            self.assertEqual(MAP_ID, manifest["map_id"])
            self.assertLess(manifest["province_count"], 517)
            self.assertGreaterEqual(manifest["province_count"], 80)
            self.assertEqual(517, manifest["theatre"]["source_province_count"])
            self.assertTrue((out / "province_id_map.png").is_file())
            self.assertTrue((out / "background_procedural.png").is_file())
            self.assertEqual(
                "project_owned_procedural",
                manifest["visual_background"]["asset_status"],
            )
            self.assertFalse(manifest["visual_background_policy"]["repo_stores_pack_artwork"])
            # Gameplay authority is color-ID, not pack art.
            self.assertEqual(
                "color_id_province_map",
                manifest["visual_background_policy"]["gameplay_authority"],
            )
            image = decode_png_rgb(out / "province_id_map.png")
            self.assertEqual(manifest["id_texture"]["width"], image.width)
            self.assertEqual(manifest["id_texture"]["height"], image.height)
            self.assertLess(image.width, 1314)
            self.assertLess(image.height, 1513)

    def test_committed_assets_and_campaign_match(self) -> None:
        if not MANIFEST.is_file():
            self.skipTest("from_goe assets not generated")
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(MAP_ID, payload["map_id"])
        self.assertEqual(dict(MARKER_THEATRE), payload["theatre"]["marker_bounds"])
        state = build_europe_mediterranean_from_goe_campaign(manifest_path=MANIFEST)
        self.assertEqual(MAP_ID, state.map_id)
        self.assertEqual(
            {row["province_id"] for row in payload["province_table"]},
            set(state.provinces),
        )
        self.assertTrue(all(pid in state.provinces for pid in state.provinces))
        for battalion in state.battalions.values():
            self.assertIn(battalion.province_id, state.provinces)
        state.validate()
        snapshot = build_frontend_snapshot(state)
        self.assertEqual(MAP_ID, snapshot["strategic_map"]["map_id"])
        self.assertEqual(len(state.provinces), len(snapshot["provinces"]))
        self.assertTrue(
            snapshot["strategic_map"]["manifest_path"]
            .replace("\\", "/")
            .endswith("assets/maps/europe_mediterranean/from_goe/map_manifest.json")
            or "from_goe" in snapshot["strategic_map"]["manifest_path"].replace("\\", "/")
        )

    def test_no_pack_background_in_from_goe_assets(self) -> None:
        if not OUT.is_dir():
            self.skipTest("from_goe assets missing")
        self.assertFalse((OUT / "background_pack_reference.png").is_file())
        self.assertTrue((OUT / "background_procedural.png").is_file() or not MANIFEST.is_file())


if __name__ == "__main__":
    unittest.main()
