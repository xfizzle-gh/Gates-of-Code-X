from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from gates_of_codex.earth3.aoh_json import parse_aoh_json
from gates_of_codex.earth3.archive import Earth3ArchiveError, open_earth3_archive
from gates_of_codex.earth3.crop import CropCandidate, CropRect, apply_crop
from gates_of_codex.earth3.model import Earth3Dataset, Earth3Province


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
                # Some zip tools allow writing odd names; open should reject unsafe norms.
                try:
                    zf.writestr("../escape.txt", "nope")
                except ValueError:
                    # Python zipfile may already block; synthesize via ZipInfo.
                    info = zipfile.ZipInfo("../escape.txt")
                    zf.writestr(info, "nope")
            # Opening scans members and must not raise unless unsafe path slips in.
            # If Python stored ../escape.txt, open_earth3_archive must reject.
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


class CropWholePolygonTests(unittest.TestCase):
    def _dataset(self) -> Earth3Dataset:
        # Three squares: inside, boundary spill, outside.
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
        adjacency = {
            1: {2},
            2: {1},
            3: set(),
            4: set(),
        }
        return Earth3Dataset(provinces=provinces, adjacency=adjacency)

    def test_includes_whole_polygon_when_centroid_inside_even_if_bounds_spill(self) -> None:
        ds = self._dataset()
        candidate = CropCandidate(
            id="t",
            title="t",
            description="t",
            rect=CropRect(0, 0, 25, 25),
        )
        result = apply_crop(ds, candidate)
        self.assertIn(1, result.included_ids)
        self.assertIn(2, result.included_ids)  # spills outside but centroid inside
        self.assertNotIn(3, result.included_ids)
        # No clipped rings: original vertex counts preserved in dataset.
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
        )
        result = apply_crop(ds, candidate)
        self.assertIn(3, result.included_ids)
        self.assertNotIn(2, result.included_ids)
        self.assertEqual(result.inclusion_reason[3], "required_include")

    def test_crop_config_file_loads(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = root / "config/earth3/crop_candidates_v1.json"
        data = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], "gates-of-codex.earth3-crop-candidates")
        self.assertEqual(len(data["candidates"]), 3)
        self.assertTrue(data["rules"]["no_sliver_clipping"])
        self.assertTrue(data["rules"]["not_continent_equals_europe"])


if __name__ == "__main__":
    unittest.main()
