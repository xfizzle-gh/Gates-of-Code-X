from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.europe import build_goe_europe_campaign
from gates_of_codex.europe_mediterranean_from_goe import (
    FORCE_EXCLUDE_PROVINCE_IDS,
    FORCE_INCLUDE_PROVINCE_IDS,
    FORCE_INCLUDE_STRATEGIC_PROVINCES,
    FROZEN_DISPLAY_CROP,
    MAP_ID,
    build_europe_mediterranean_from_goe_campaign,
    generate_europe_mediterranean_from_goe,
    select_playable_provinces,
)
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.strategic_map import decode_png_rgb


ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "godot/assets/maps/europe/interim_goe"
OUT = ROOT / "godot/assets/maps/europe_mediterranean/from_goe"
MANIFEST = OUT / "map_manifest.json"
ID_MAP = OUT / "province_id_map.png"
BG = OUT / "background_procedural.png"
VISUAL = OUT / "visual_land_mask.png"


@unittest.skipUnless(
    (INTERIM / "map_manifest.json").is_file() and (INTERIM / "province_id_map.png").is_file(),
    "interim GoE assets missing",
)
class EuropeMediterraneanFromGoeTests(unittest.TestCase):
    def test_selection_applies_force_include_exclude(self) -> None:
        interim = json.loads((INTERIM / "map_manifest.json").read_text(encoding="utf-8"))
        kept, report = select_playable_provinces(interim["province_table"])
        kept_ids = {str(row["province_id"]) for row in kept}
        for pid in FORCE_EXCLUDE_PROVINCE_IDS:
            self.assertNotIn(pid, kept_ids)
        source_ids = {str(row["province_id"]) for row in interim["province_table"]}
        for pid in FORCE_INCLUDE_PROVINCE_IDS & source_ids:
            self.assertIn(pid, kept_ids)
        for pid in FORCE_INCLUDE_STRATEGIC_PROVINCES:
            if pid in source_ids:
                self.assertIn(pid, kept_ids)

    def test_generate_visual_playable_split(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "from_goe"
            manifest = generate_europe_mediterranean_from_goe(output_dir=out, pad_px=6)
            self.assertEqual(MAP_ID, manifest["map_id"])
            self.assertTrue((out / "province_id_map.png").is_file())
            self.assertTrue((out / "visual_land_mask.png").is_file())
            self.assertTrue((out / "background_procedural.png").is_file())
            id_img = decode_png_rgb(out / "province_id_map.png")
            vis = decode_png_rgb(out / "visual_land_mask.png")
            bg = decode_png_rgb(out / "background_procedural.png")
            self.assertEqual(FROZEN_DISPLAY_CROP["width"], id_img.width)
            self.assertEqual(FROZEN_DISPLAY_CROP["height"], id_img.height)
            self.assertEqual(id_img.width, vis.width)
            self.assertEqual(id_img.height, bg.height)
            playable_land = sum(1 for c in id_img.pixels if c != (0, 0, 0))
            visual_land = sum(1 for c in vis.pixels if c[0] > 127)
            self.assertGreaterEqual(visual_land, playable_land)
            ids = {r["province_id"] for r in manifest["province_table"]}
            for pid in FORCE_EXCLUDE_PROVINCE_IDS:
                self.assertNotIn(pid, ids)
            # Strategic force-includes present and clipped inside frozen frame.
            for pid, name in FORCE_INCLUDE_STRATEGIC_PROVINCES.items():
                self.assertIn(pid, ids)
                row = next(r for r in manifest["province_table"] if r["province_id"] == pid)
                self.assertEqual(name, row["display_name"])
                ax, ay_bl = row["marker_anchor"]
                self.assertGreaterEqual(ax, 0)
                self.assertLess(ax, id_img.width)
                self.assertGreaterEqual(ay_bl, 0)
                self.assertLess(ay_bl, id_img.height)

    def test_committed_campaign_and_raster_invariants(self) -> None:
        if not MANIFEST.is_file() or not ID_MAP.is_file():
            self.skipTest("from_goe assets missing")
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        state = build_europe_mediterranean_from_goe_campaign(manifest_path=MANIFEST)
        manifest_ids = {row["province_id"] for row in payload["province_table"]}
        self.assertEqual(manifest_ids, set(state.provinces))
        for pid in FORCE_EXCLUDE_PROVINCE_IDS:
            self.assertNotIn(pid, state.provinces)
        for province in state.provinces.values():
            for n in province.neighbors:
                self.assertIn(n, state.provinces)
        for b in state.battalions.values():
            self.assertIn(b.province_id, state.provinces)
        state.validate()

        image = decode_png_rgb(ID_MAP)
        tex = payload.get("id_texture") or {}
        self.assertEqual(817, int(tex.get("width", 0)))
        self.assertEqual(920, int(tex.get("height", 0)))
        self.assertEqual(817, image.width)
        self.assertEqual(920, image.height)

        color_to_pid = {tuple(r["rgb"]): r["province_id"] for r in payload["province_table"]}
        w, h = image.width, image.height
        self.assertEqual(0, sum(1 for c in image.pixels if c == (255, 255, 255)))
        owners = [
            color_to_pid.get(image.color_at(x, y), "")
            for y in range(h)
            for x in range(w)
        ]
        edges: set[tuple[str, str]] = set()
        for y in range(h):
            for x in range(w):
                a = owners[y * w + x]
                if not a:
                    continue
                for nx, ny in ((x + 1, y), (x, y + 1)):
                    if nx >= w or ny >= h:
                        continue
                    b = owners[ny * w + nx]
                    if b and b != a:
                        edges.add(tuple(sorted((a, b))))
        listed: set[tuple[str, str]] = set()
        for row in payload["province_table"]:
            for n in row.get("land_neighbors") or []:
                listed.add(tuple(sorted((row["province_id"], n))))
            ax = int(round(row["marker_anchor"][0]))
            ay = h - 1 - int(round(row["marker_anchor"][1]))
            self.assertEqual(row["province_id"], color_to_pid.get(image.color_at(ax, ay)))
        self.assertEqual(listed, edges)

        # Channel not land
        london = next(r for r in payload["province_table"] if r["province_id"] == "province_0365")
        self.assertNotIn("province_0329", set(london.get("land_neighbors") or []))
        self.assertEqual(
            "ferry_or_sea_lane",
            (london.get("edge_types") or {}).get("province_0329"),
        )

        # Required strategic names present
        by_id = {r["province_id"]: r for r in payload["province_table"]}
        self.assertEqual("Moscow", by_id["province_0408"]["display_name"])
        self.assertEqual("Donetsk", by_id["province_0284"]["display_name"])
        self.assertEqual("Luhansk", by_id["province_0327"]["display_name"])
        self.assertEqual("Lisbon", by_id["province_0156"]["display_name"])

        # Cosmetic land continuous: no separator channels inside visual land.
        self.assertTrue(VISUAL.is_file() and BG.is_file())
        vis = decode_png_rgb(VISUAL)
        bg = decode_png_rgb(BG)
        visual_only = 0
        land_tones: set[tuple[int, int, int]] = set()
        for i, vc in enumerate(vis.pixels):
            idc = image.pixels[i]
            if vc[0] > 127:
                land_tones.add(bg.pixels[i])
                if idc == (0, 0, 0):
                    visual_only += 1
        self.assertGreater(visual_only, 1000)
        # Single continuous underlay tone for all visual land (no grey province look).
        self.assertEqual(1, len(land_tones), msg=f"land tones={land_tones}")

        # No thin water cracks: non-land pixel fully surrounded by land should not exist.
        cracks = 0
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                if vis.color_at(x, y)[0] > 127:
                    continue
                if all(
                    vis.color_at(x + dx, y + dy)[0] > 127
                    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))
                ):
                    cracks += 1
        self.assertEqual(0, cracks)

        # Cosmetic pixels cannot be selected via ID map.
        for i, vc in enumerate(vis.pixels):
            if vc[0] > 127 and image.pixels[i] == (0, 0, 0):
                # already counted; ensure no province id for black id pixels
                pass
        self.assertEqual("", color_to_pid.get((0, 0, 0), ""))

        cosmetic = (payload.get("theatre") or {}).get("selection", {}).get(
            "cosmetic_visual_land_provinces", []
        )
        for item in cosmetic:
            self.assertNotIn(item["province_id"], manifest_ids)
        interaction = (payload.get("theatre") or {}).get("selection", {}).get(
            "cosmetic_interaction", {}
        )
        for key in (
            "hover",
            "selection",
            "labels",
            "counters",
            "facilities",
            "objectives",
            "adjacency",
        ):
            self.assertFalse(bool(interaction.get(key, True)))

        crop = (payload.get("theatre") or {}).get("selection", {}).get("display_crop_px", {})
        self.assertTrue(crop.get("frozen"))
        self.assertEqual(817, int(crop.get("width", 0)))
        self.assertEqual(920, int(crop.get("height", 0)))

    def test_full_interim_goe_still_loadable(self) -> None:
        state = build_goe_europe_campaign()
        self.assertEqual(517, len(state.provinces))
        state.map_metadata["strategic_map_id"] = "interim_goe_europe"
        snapshot = build_frontend_snapshot(state)
        self.assertIn(snapshot["strategic_map"]["map_id"], {"goe_europe", "interim_goe_europe"})


if __name__ == "__main__":
    unittest.main()
