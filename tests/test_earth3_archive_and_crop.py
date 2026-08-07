from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from gates_of_codex.earth3.aoh_json import parse_aoh_json
from gates_of_codex.earth3.archive import Earth3ArchiveError, open_earth3_archive
from gates_of_codex.earth3.crop import CropCandidate, CropRect, apply_crop
from gates_of_codex.earth3.geometry import (
    ear_clip_triangles,
    overlap_ratio,
    shoelace_area,
    sutherland_hodgman,
)
from gates_of_codex.earth3.model import Earth3City, Earth3Dataset, Earth3Province


class AohJsonTests(unittest.TestCase):
    def test_parses_unquoted_keys_and_trailing_commas(self) -> None:
        text = """
        {
            Name: "Earth",
            NumOfProvinces: 3,
            Flags: [true, false,],
        }
        """
        data = parse_aoh_json(text)
        self.assertEqual(data["Name"], "Earth")
        self.assertEqual(data["NumOfProvinces"], 3)
        self.assertEqual(data["Flags"], [True, False])

    def test_parses_data_wrapper(self) -> None:
        text = """
        {
        Age_of_History: Data,
        Data: [
          {pX:[0,1,1,0], pY:[0,0,1,1],},
        ],
        }
        """
        data = parse_aoh_json(text)
        self.assertIn("Data", data)
        self.assertEqual(len(data["Data"]), 1)


class ArchiveSafetyTests(unittest.TestCase):
    def test_rejects_path_traversal_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evil.zip"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("Earth3/Config.json", '{"Name":"x","NumOfProvinces":0}')
                try:
                    zf.writestr("../escape.txt", "nope")
                except ValueError:
                    info = zipfile.ZipInfo("../escape.txt")
                    zf.writestr(info, "nope")
            try:
                with open_earth3_archive(path) as archive:
                    names = archive.names
                self.assertTrue(all(".." not in n for n in names))
            except Earth3ArchiveError as exc:
                self.assertIn("unsafe", str(exc).lower())

    def test_normalizes_separators_and_reads_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.zip"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("Earth3/Config.json", '{"Name":"Earth","NumOfProvinces":0}')
            with open_earth3_archive(path) as archive:
                text = archive.read_text("Earth3\\Config.json")
            self.assertIn("Earth", text)


class GeometryTests(unittest.TestCase):
    def test_shoelace_unit_square(self) -> None:
        ring = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        self.assertAlmostEqual(shoelace_area(ring), 100.0)

    def test_overlap_ratio_full_and_partial(self) -> None:
        subject = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        mask_full = (((-1.0, -1.0), (11.0, -1.0), (11.0, 11.0), (-1.0, 11.0)),)
        mask_half = (((5.0, -1.0), (11.0, -1.0), (11.0, 11.0), (5.0, 11.0)),)
        self.assertAlmostEqual(overlap_ratio(subject, mask_full), 1.0, places=5)
        self.assertAlmostEqual(overlap_ratio(subject, mask_half), 0.5, places=5)

    def test_sutherland_and_earclip_stable(self) -> None:
        square = ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0))
        clip = ((1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0))
        clipped = sutherland_hodgman(square, clip)
        self.assertGreaterEqual(len(clipped), 3)
        tris = ear_clip_triangles(square)
        self.assertEqual(len(tris), 2)


class CropWholePolygonTests(unittest.TestCase):
    def _dataset(self) -> Earth3Dataset:
        provinces = {
            1: Earth3Province(
                source_id=1,
                ring=((10, 10), (20, 10), (20, 20), (10, 20)),
                label_x=15,
                label_y=15,
                continent_id=2,
                terrain_id=1,
                region_id=0,
                growth=1.0,
                base_development=1,
            ),
            2: Earth3Province(
                source_id=2,
                ring=((18, 18), (30, 18), (30, 30), (18, 30)),
                label_x=22,
                label_y=22,
                continent_id=2,
                terrain_id=1,
                region_id=0,
                growth=1.0,
                base_development=1,
            ),
            3: Earth3Province(
                source_id=3,
                ring=((40, 40), (50, 40), (50, 50), (40, 50)),
                label_x=45,
                label_y=45,
                continent_id=2,
                terrain_id=1,
                region_id=0,
                growth=1.0,
                base_development=1,
            ),
            4: Earth3Province(
                source_id=4,
                ring=((0, 0), (5, 0), (5, 5), (0, 5)),
                label_x=2,
                label_y=2,
                continent_id=0,
                terrain_id=0,
                region_id=0,
                growth=0.0,
                base_development=0,
            ),
        }
        adjacency = {1: {2}, 2: {1}, 3: set(), 4: set()}
        return Earth3Dataset(provinces=provinces, adjacency=adjacency)

    def test_includes_whole_polygon_when_centroid_inside_even_if_bounds_spill(self) -> None:
        ds = self._dataset()
        candidate = CropCandidate(
            id="t",
            title="t",
            description="t",
            rect=CropRect(0, 0, 25, 25),
            selection_mode="rect_centroid",
        )
        result = apply_crop(ds, candidate)
        self.assertIn(1, result.included_ids)
        self.assertIn(2, result.included_ids)
        self.assertNotIn(3, result.included_ids)
        self.assertEqual(len(ds.provinces[2].ring), 4)

    def test_required_include_and_explicit_exclude(self) -> None:
        ds = self._dataset()
        candidate = CropCandidate(
            id="t",
            title="t",
            description="t",
            rect=CropRect(0, 0, 25, 25),
            required_include_ids=(3,),
            explicit_exclude_ids=(2,),
            selection_mode="rect_centroid",
        )
        result = apply_crop(ds, candidate)
        self.assertIn(3, result.included_ids)
        self.assertNotIn(2, result.included_ids)
        self.assertEqual(result.inclusion_reason[3], "required_include")

    def test_mask_overlap_threshold_and_review_band(self) -> None:
        ds = self._dataset()
        # Mask fully covers province 1; covers ~75% of province 2 (x 18-30 → 18-27).
        mask = (
            ((0.0, 0.0), (27.0, 0.0), (27.0, 27.0), (0.0, 27.0)),
        )
        candidate = CropCandidate(
            id="mask",
            title="mask",
            description="mask",
            rect=CropRect(0, 0, 60, 60),
            mask_rings=mask,
            selection_mode="mask_overlap",
            inclusion_threshold=0.35,
            review_band_low=0.15,
            review_band_high=0.80,
            explicit_exclude_ids=(3,),
        )
        result = apply_crop(ds, candidate)
        self.assertIn(1, result.included_ids)
        self.assertIn(2, result.included_ids)
        self.assertNotIn(3, result.included_ids)
        self.assertGreaterEqual(result.overlap_ratios[1], 0.99)
        # Province 2 is 18..30 in x/y; mask to 27 clips both axes → 9/12 * 9/12 = 0.5625.
        self.assertAlmostEqual(result.overlap_ratios[2], 0.5625, places=3)
        self.assertIn(2, result.threshold_review_ids)
        self.assertEqual(len(ds.provinces[2].ring), 4)

    def test_crop_config_file_loads(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = root / "config/earth3/crop_candidates_v1.json"
        data = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], "gates-of-codex.earth3-crop-candidates")
        self.assertEqual(len(data["candidates"]), 4)
        self.assertTrue(data["rules"]["no_sliver_clipping"])
        self.assertTrue(data["rules"]["not_continent_equals_europe"])
        self.assertTrue(data["rules"].get("no_all_vertices_inside_fast_path"))
        self.assertEqual(data["permission"]["status"], "OWNER_ASSERTED_GRANT")
        self.assertIn("signed license instrument", data["permission"]["not_present_in_repo"])
        masked = next(c for c in data["candidates"] if c["id"] == "em_reference_masked")
        self.assertEqual(masked["selection_mode"], "mask_overlap")
        self.assertGreaterEqual(len(masked["mask_rings"]), 2)
        self.assertNotIn(11370, masked["explicit_exclude_ids"])  # Kola approach allowed in v6
        self.assertIn(11764, masked["explicit_exclude_ids"])
        self.assertIn(956, masked["required_include_ids"])  # Höfn
        self.assertIn(6850, masked["required_include_ids"])  # Bakkafjörður
        self.assertEqual(
            masked.get("threshold_decisions_file"),
            "threshold_decisions_em_reference_masked_v1.json",
        )
        self.assertGreaterEqual(len(data.get("exclusion_city_anchors", [])), 14)

    def test_region_coverage_requires_included_city_anchors(self) -> None:
        ds = self._dataset()
        ds.cities = (
            Earth3City("Kherson", 15, 15, 1, 0),
            Earth3City("Murmansk", 45, 45, 3, 1),
            Earth3City("Arkhangelsk", 45, 45, 3, 2),
        )
        candidate = CropCandidate(
            id="t",
            title="t",
            description="t",
            rect=CropRect(0, 0, 25, 25),
            selection_mode="rect_centroid",
        )
        result = apply_crop(ds, candidate)
        self.assertTrue(result.region_coverage["Ukraine_Crimea_Donbas"]["ok"])
        self.assertTrue(result.region_coverage["Far_north_should_exclude"]["ok"])


if __name__ == "__main__":
    unittest.main()
