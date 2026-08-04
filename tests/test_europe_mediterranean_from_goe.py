from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.europe import build_goe_europe_campaign
from gates_of_codex.europe_mediterranean_from_goe import (
    FORCE_EXCLUDE_PROVINCE_IDS,
    FORCE_INCLUDE_PROVINCE_IDS,
    MAP_ID,
    build_europe_mediterranean_from_goe_campaign,
    generate_europe_mediterranean_from_goe,
    select_theatre_provinces,
)
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.strategic_map import decode_png_rgb


ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "godot/assets/maps/europe/interim_goe"
OUT = ROOT / "godot/assets/maps/europe_mediterranean/from_goe"
MANIFEST = OUT / "map_manifest.json"
ID_MAP = OUT / "province_id_map.png"
BG = OUT / "background_procedural.png"


@unittest.skipUnless(
    (INTERIM / "map_manifest.json").is_file() and (INTERIM / "province_id_map.png").is_file(),
    "interim GoE assets missing",
)
class EuropeMediterraneanFromGoeTests(unittest.TestCase):
    def test_selection_applies_force_include_exclude(self) -> None:
        interim = json.loads((INTERIM / "map_manifest.json").read_text(encoding="utf-8"))
        kept, report = select_theatre_provinces(interim["province_table"])
        kept_ids = {str(row["province_id"]) for row in kept}
        for pid in FORCE_EXCLUDE_PROVINCE_IDS:
            self.assertNotIn(pid, kept_ids)
        source_ids = {str(row["province_id"]) for row in interim["province_table"]}
        for pid in FORCE_INCLUDE_PROVINCE_IDS & source_ids:
            self.assertIn(pid, kept_ids)
        self.assertEqual(len(kept), report["final_count"])

    def test_generate_crop_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "from_goe"
            manifest = generate_europe_mediterranean_from_goe(output_dir=out, pad_px=8)
            self.assertEqual(MAP_ID, manifest["map_id"])
            self.assertLess(manifest["province_count"], 517)
            self.assertGreaterEqual(manifest["province_count"], 80)
            ids = {row["province_id"] for row in manifest["province_table"]}
            for pid in FORCE_EXCLUDE_PROVINCE_IDS:
                self.assertNotIn(pid, ids)
            image = decode_png_rgb(out / "province_id_map.png")
            colors = {tuple(row["rgb"]): row["province_id"] for row in manifest["province_table"]}
            seen = set()
            for color in image.pixels:
                if color in colors:
                    seen.add(colors[color])
            self.assertEqual(ids, seen)
            for row in manifest["province_table"]:
                for neighbor in row.get("source_neighbors", []):
                    self.assertIn(neighbor, ids)
            bg = decode_png_rgb(out / "background_procedural.png")
            self.assertEqual(image.width, bg.width)
            self.assertEqual(image.height, bg.height)
            self.assertEqual("project_procedural", manifest["visual_background"]["asset_status"])
            self.assertIn("force_excluded", manifest["theatre"]["selection"])

    def test_committed_campaign_and_manifest_match(self) -> None:
        if not MANIFEST.is_file():
            self.skipTest("from_goe assets not generated")
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        state = build_europe_mediterranean_from_goe_campaign(manifest_path=MANIFEST)
        manifest_ids = {row["province_id"] for row in payload["province_table"]}
        self.assertEqual(manifest_ids, set(state.provinces))
        for pid in FORCE_EXCLUDE_PROVINCE_IDS:
            self.assertNotIn(pid, state.provinces)
        for province in state.provinces.values():
            for neighbor in province.neighbors:
                self.assertIn(neighbor, state.provinces)
        for battalion in state.battalions.values():
            self.assertIn(battalion.province_id, state.provinces)
        for objective in state.map_metadata.get("operational_objectives", []):
            for target in objective.get("targets", []):
                self.assertNotIn(str(target), FORCE_EXCLUDE_PROVINCE_IDS)
        state.validate()
        snapshot = build_frontend_snapshot(state)
        self.assertEqual(MAP_ID, snapshot["strategic_map"]["map_id"])
        self.assertEqual(len(state.provinces), len(snapshot["provinces"]))

    def test_background_and_id_dimensions_match(self) -> None:
        if not MANIFEST.is_file() or not ID_MAP.is_file() or not BG.is_file():
            self.skipTest("from_goe assets missing")
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        image = decode_png_rgb(ID_MAP)
        bg = decode_png_rgb(BG)
        self.assertEqual(image.width, bg.width)
        self.assertEqual(image.height, bg.height)
        self.assertEqual(payload["id_texture"]["width"], image.width)
        self.assertFalse((OUT / "background_pack_reference.png").is_file())

    def test_full_interim_goe_still_loadable(self) -> None:
        state = build_goe_europe_campaign()
        self.assertEqual(517, len(state.provinces))
        state.map_metadata["strategic_map_id"] = "interim_goe_europe"
        snapshot = build_frontend_snapshot(state)
        self.assertIn(snapshot["strategic_map"]["map_id"], {"goe_europe", "interim_goe_europe"})
        self.assertEqual(517, len(snapshot["provinces"]))


if __name__ == "__main__":
    unittest.main()
