from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.europe_mediterranean_campaign import (
    build_europe_mediterranean_prototype_campaign,
)
from gates_of_codex.europe_mediterranean_map import (
    SETTLEMENT_GEO,
    THEATRE_BOUNDS,
    generate_europe_mediterranean_prototype,
    in_theatre,
    lonlat_to_pixel,
    rgb_for_index,
)
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.strategic_map import decode_png_rgb


ROOT = Path(__file__).resolve().parents[1]
EM_DIR = ROOT / "godot/assets/maps/europe_mediterranean/prototype"
MANIFEST = EM_DIR / "map_manifest.json"
ID_MAP = EM_DIR / "id_map.png"


class EuropeMediterraneanPrototypeTests(unittest.TestCase):
    def test_lonlat_to_pixel_theatre_corners(self) -> None:
        lon_min, lon_max, lat_min, lat_max = THEATRE_BOUNDS
        self.assertEqual((0, 0), lonlat_to_pixel(lon_min, lat_max, 1600, 1000))
        self.assertEqual((1599, 999), lonlat_to_pixel(lon_max, lat_min, 1600, 1000))

    def test_rgb_ids_are_unique(self) -> None:
        self.assertEqual(200, len({rgb_for_index(i) for i in range(200)}))

    def test_theatre_bounds_include_europe_exclude_americas_asia(self) -> None:
        self.assertTrue(in_theatre(2.35, 48.85))  # Paris
        self.assertTrue(in_theatre(31.24, 30.04))  # Cairo
        self.assertFalse(in_theatre(-74.0, 40.7))  # NYC
        self.assertFalse(in_theatre(139.7, 35.7))  # Tokyo
        self.assertFalse(in_theatre(77.2, 28.6))  # Delhi

    def test_generate_with_synthetic_land(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "em"
            manifest = generate_europe_mediterranean_prototype(
                output_dir=out, width=320, height=200
            )
            self.assertEqual("europe_mediterranean_prototype", manifest["map_id"])
            self.assertGreaterEqual(manifest["province_count"], 20)
            self.assertEqual(
                "prototype-only; Natural Earth land mask is public domain; not final ship art",
                manifest["clean_room"]["status"],
            )
            self.assertEqual(list(THEATRE_BOUNDS), manifest["theatre"]["bounds_lon_lat"])
            self.assertTrue((out / "id_map.png").is_file())
            self.assertTrue((out / "land_silhouette.png").is_file())
            self.assertTrue((out / "map_manifest.json").is_file())
            self.assertIn(
                manifest["theatre"]["land_source"],
                {
                    "synthetic_theatre_fixture",
                    "package_land_mask_png",
                    "committed_land_mask_png",
                    "natural_earth_land_geojson",
                },
            )
            edge_types = {edge["type"] for edge in manifest["adjacency"]["edges"]}
            self.assertIn("land", edge_types)

    def test_no_ocean_pixel_assigned_on_generate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "em"
            generate_europe_mediterranean_prototype(output_dir=out, width=240, height=150)
            image = decode_png_rgb(out / "id_map.png")
            mask = decode_png_rgb(out / "land_mask.png")
            for idx, (r, g, b) in enumerate(image.pixels):
                mr, mg, mb = mask.pixels[idx]
                is_land = (mr + mg + mb) >= 120
                is_province = (r, g, b) != (0, 0, 0)
                if is_province:
                    self.assertTrue(is_land)

    def test_committed_em_assets_match_contract(self) -> None:
        if not MANIFEST.is_file():
            self.skipTest("europe-mediterranean prototype assets missing")
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual("europe_mediterranean_prototype", payload["map_id"])
        self.assertEqual(1600, payload["id_texture"]["width"])
        self.assertEqual(1000, payload["id_texture"]["height"])
        self.assertNotEqual(517, payload["province_count"])
        self.assertNotEqual(1314, payload["id_texture"]["width"])
        self.assertTrue(all(row["province_id"].startswith("em_") for row in payload["province_table"]))
        self.assertEqual(
            "prototype_only_not_approved_for_distribution",
            payload["asset_status"],
        )
        self.assertIn("land", payload["adjacency"]["types"])
        self.assertIn("strait", payload["adjacency"]["types"])
        self.assertIn("ferry_or_sea_lane", payload["adjacency"]["types"])

    def test_committed_seas_remain_water(self) -> None:
        if not ID_MAP.is_file():
            self.skipTest("europe-mediterranean prototype assets missing")
        image = decode_png_rgb(ID_MAP)
        samples = {
            "mediterranean": lonlat_to_pixel(18.0, 35.0, image.width, image.height),
            "black_sea": lonlat_to_pixel(34.0, 43.0, image.width, image.height),
            "baltic": lonlat_to_pixel(19.5, 56.5, image.width, image.height),
            "north_sea": lonlat_to_pixel(3.0, 56.0, image.width, image.height),
        }
        for name, (x, y) in samples.items():
            self.assertEqual((0, 0, 0), image.color_at(x, y), msg=name)

    def test_no_accidental_paris_london_land_edge(self) -> None:
        if not MANIFEST.is_file():
            self.skipTest("europe-mediterranean prototype assets missing")
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        land_edges = {
            tuple(sorted((edge["a"], edge["b"])))
            for edge in payload["adjacency"]["edges"]
            if edge["type"] == "land"
        }
        self.assertNotIn(tuple(sorted(("em_paris", "em_london"))), land_edges)
        paris = next(row for row in payload["province_table"] if row["province_id"] == "em_paris")
        self.assertNotEqual("land", paris.get("edge_types", {}).get("em_london"))

    def test_markers_inside_provinces(self) -> None:
        if not MANIFEST.is_file() or not ID_MAP.is_file():
            self.skipTest("europe-mediterranean prototype assets missing")
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        image = decode_png_rgb(ID_MAP)
        color_to_id = {tuple(row["rgb"]): row["province_id"] for row in payload["province_table"]}
        for row in payload["province_table"]:
            ax, ay_bottom = row["marker_anchor"]
            x = int(round(ax))
            y = image.height - 1 - int(round(ay_bottom))
            color = image.color_at(x, y)
            self.assertEqual(row["province_id"], color_to_id.get(color), msg=row["province_id"])

    def test_adjacency_symmetric_and_nonzero_area(self) -> None:
        if not MANIFEST.is_file():
            self.skipTest("europe-mediterranean prototype assets missing")
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        by_id = {row["province_id"]: row for row in payload["province_table"]}
        for row in payload["province_table"]:
            self.assertGreater(int(row["provenance"]["area_px"]), 0)
            for neighbor in row["source_neighbors"]:
                self.assertIn(row["province_id"], by_id[neighbor]["source_neighbors"])

    def test_em_campaign_matches_manifest_ids(self) -> None:
        if not MANIFEST.is_file():
            self.skipTest("europe-mediterranean prototype assets missing")
        state = build_europe_mediterranean_prototype_campaign(manifest_path=MANIFEST)
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest_ids = {row["province_id"] for row in manifest["province_table"]}
        campaign_ids = set(state.provinces)
        self.assertEqual(manifest_ids, campaign_ids)
        self.assertEqual("europe_mediterranean_prototype", state.map_id)
        self.assertEqual(
            "europe_mediterranean_prototype",
            state.map_metadata["strategic_map_id"],
        )
        self.assertTrue(
            state.campaign_name.startswith("Gates of CodeX: Europe-Mediterranean Prototype")
        )
        self.assertGreaterEqual(len(state.battalions), 1)
        state.validate()

    def test_em_export_selects_em_manifest(self) -> None:
        if not MANIFEST.is_file():
            self.skipTest("europe-mediterranean prototype assets missing")
        state = build_europe_mediterranean_prototype_campaign(manifest_path=MANIFEST)
        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "campaign_snapshot.json"
            assets = Path(temporary) / "assets/maps/europe_mediterranean/prototype"
            assets.mkdir(parents=True)
            (assets / "map_manifest.json").write_text(
                MANIFEST.read_text(encoding="utf-8"), encoding="utf-8"
            )
            state.map_metadata["strategic_map_manifest"] = (
                "assets/maps/europe_mediterranean/prototype/map_manifest.json"
            )
            snapshot = build_frontend_snapshot(
                state,
                campaign_path=Path(temporary) / "campaign.json",
                snapshot_path=snapshot_path,
            )
        self.assertEqual("europe_mediterranean_prototype", snapshot["strategic_map"]["map_id"])
        self.assertTrue(
            snapshot["strategic_map"]["manifest_path"]
            .replace("\\", "/")
            .endswith("assets/maps/europe_mediterranean/prototype/map_manifest.json")
        )
        self.assertEqual(len(state.provinces), len(snapshot["provinces"]))
        self.assertTrue(all(row["id"].startswith("em_") for row in snapshot["provinces"]))

    def test_europe_campaign_still_exports_europe_map_id(self) -> None:
        from gates_of_codex.europe import build_goe_europe_campaign

        state = build_goe_europe_campaign()
        state.map_metadata["strategic_map_id"] = "interim_goe_europe"
        snapshot = build_frontend_snapshot(state)
        self.assertIn(snapshot["strategic_map"]["map_id"], {"goe_europe", "interim_goe_europe"})
        self.assertEqual(517, len(snapshot["provinces"]))

    def test_em_movement_between_adjacent_provinces(self) -> None:
        if not MANIFEST.is_file():
            self.skipTest("europe-mediterranean prototype assets missing")
        state = build_europe_mediterranean_prototype_campaign(manifest_path=MANIFEST)
        battalion = next(iter(state.battalions.values()))
        origin = state.provinces[battalion.province_id]
        if not origin.neighbors:
            self.skipTest("starter province has no neighbors")
        target = origin.neighbors[0]
        for other in list(state.battalions.values()):
            if other.province_id == target:
                other.province_id = battalion.province_id
        state.current_faction = battalion.faction
        result = CampaignEngine(state).move_or_attack(battalion.battalion_id, target)
        self.assertTrue(result.moved or result.pending_battle is not None)

    def test_public_geo_core_cities_present(self) -> None:
        for key in ("paris", "berlin", "london", "rome", "madrid", "cairo", "moscow"):
            self.assertIn(key, SETTLEMENT_GEO)
            lat, lon = SETTLEMENT_GEO[key]
            self.assertTrue(in_theatre(lon, lat), msg=key)


if __name__ == "__main__":
    unittest.main()
