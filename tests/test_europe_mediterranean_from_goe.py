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

    def test_raster_land_adjacency_and_anchors_inside_provinces(self) -> None:
        if not MANIFEST.is_file() or not ID_MAP.is_file():
            self.skipTest("from_goe assets missing")
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        image = decode_png_rgb(ID_MAP)
        color_to_pid = {tuple(row["rgb"]): row["province_id"] for row in payload["province_table"]}
        w, h = image.width, image.height
        white = (255, 255, 255)
        black = (0, 0, 0)
        # White exterior must be gone from repaired theatre raster.
        white_count = sum(1 for c in image.pixels if c == white)
        self.assertEqual(0, white_count)
        # Direct province-province contact must exist (separators closed).
        touch = 0
        for y in range(image.height):
            for x in range(image.width - 1):
                a = image.color_at(x, y)
                b = image.color_at(x + 1, y)
                if a not in (black, white) and b not in (black, white) and a != b:
                    touch += 1
        self.assertGreater(touch, 100)
        owners: list[str] = []
        for y in range(h):
            for x in range(w):
                owners.append(color_to_pid.get(image.color_at(x, y), ""))
        # Direct 4-neighbor land edges only (gap = 0)
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
        by_id = {row["province_id"]: row for row in payload["province_table"]}
        listed: set[tuple[str, str]] = set()
        for row in payload["province_table"]:
            land = set(row.get("land_neighbors") or [])
            for n in land:
                self.assertIn(n, by_id)
                key = tuple(sorted((row["province_id"], n)))
                self.assertIn(key, edges)
                listed.add(key)
                # Typed land
                self.assertEqual("land", (row.get("edge_types") or {}).get(n, "land"))
            for n in land:
                peer = set(by_id[n].get("land_neighbors") or [])
                self.assertIn(row["province_id"], peer)
            ax = int(round(row["marker_anchor"][0]))
            ay = h - 1 - int(round(row["marker_anchor"][1]))
            self.assertEqual(row["province_id"], color_to_pid.get(image.color_at(ax, ay)))
        self.assertEqual(listed, edges)

        # Channel / sea must not be ordinary land adjacency.
        def _ids(*names: str) -> set[str]:
            found = set()
            for row in payload["province_table"]:
                dn = str(row.get("display_name", "")).lower()
                pid = row["province_id"]
                for name in names:
                    if name.lower() in dn or name == pid:
                        found.add(pid)
            return found

        britain = _ids("Greater London Area", "Sussex", "province_0365")
        france_coast = _ids("Nord Pas De Calais", "province_0329")
        for a in britain:
            for b in france_coast:
                self.assertNotIn(b, set(by_id[a].get("land_neighbors") or []))
                # May exist as typed ferry
                et = (by_id[a].get("edge_types") or {}).get(b)
                if et is not None:
                    self.assertIn(et, {"strait", "ferry_or_sea_lane"})

        # Background land silhouette matches repaired ID land
        if BG.is_file():
            bg = decode_png_rgb(BG)
            self.assertEqual(image.width, bg.width)
            self.assertEqual(image.height, bg.height)
            for i, color in enumerate(image.pixels):
                id_land = color != black
                br, bgc, bb = bg.pixels[i]
                bg_land = (br + bgc + bb) < 700  # parchment darker than sea panel
                # sea panel ~236,240,244 sum~720; land parchment ~228,222,208 sum~658
                if id_land:
                    self.assertLess(br + bgc + bb, 700)
                else:
                    self.assertGreaterEqual(br + bgc + bb, 700)

    def test_full_interim_goe_still_loadable(self) -> None:
        state = build_goe_europe_campaign()
        self.assertEqual(517, len(state.provinces))
        state.map_metadata["strategic_map_id"] = "interim_goe_europe"
        snapshot = build_frontend_snapshot(state)
        self.assertIn(snapshot["strategic_map"]["map_id"], {"goe_europe", "interim_goe_europe"})
        self.assertEqual(517, len(snapshot["provinces"]))


if __name__ == "__main__":
    unittest.main()
