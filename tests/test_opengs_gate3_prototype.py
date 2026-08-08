from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "opengs_eval" / "gate3_prototype.py"
CONFIG = ROOT / "tools" / "opengs_eval" / "gate3_natural_earth_config.json"
WORKFLOW = ROOT / ".github" / "workflows" / "opengs-gate3-prototype.yml"


def load_module():
    spec = importlib.util.spec_from_file_location("gate3_prototype", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Gate3ConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.g = load_module()
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def write_config(self, root: Path, value: dict) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / "config.json"
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        return path

    def test_locked_config_is_valid_and_direct_comparison_total_is_3514(self) -> None:
        config, digest, raw = self.g.load_config(CONFIG)
        self.assertEqual(config["candidate_id"], self.g.CANDIDATE_ID)
        self.assertEqual(config["starting_commit"], self.g.STARTING_COMMIT)
        self.assertEqual(config["counts"]["land_provinces"], 3299)
        self.assertEqual(config["counts"]["ocean_provinces"], 215)
        self.assertEqual(config["counts"]["land_provinces"] + config["counts"]["ocean_provinces"], 3514)
        self.assertEqual(len(digest), 64)
        self.assertGreaterEqual(len(config["theatre"]["anchors"]), 10)
        self.assertEqual({anchor["expected"] for anchor in config["theatre"]["anchors"]}, {"land", "ocean"})
        self.assertTrue(raw.endswith(b"\n"))

    def test_only_pinned_public_domain_natural_earth_is_authorized(self) -> None:
        source = self.config["source"]
        self.assertEqual(source["repository"], "nvkelso/natural-earth-vector")
        self.assertEqual(source["commit"], self.g.NATURAL_EARTH_COMMIT)
        self.assertEqual(source["license"], "public_domain")
        self.assertEqual({row["role"] for row in source["files"]}, set(self.g.SOURCE_ROLES))
        for row in source["files"]:
            self.assertEqual(len(row["git_blob_sha1"]), 40)
            self.assertEqual(len(row["sha256"]), 64)

    def test_material_config_changes_fail_closed(self) -> None:
        mutations = {
            "source": lambda value: value["source"].__setitem__("repository", "other/source"),
            "projection": lambda value: value["projection"].__setitem__("proj", "+proj=merc"),
            "count": lambda value: value["counts"].__setitem__("land_provinces", 3300),
            "registration": lambda value: value["isolation"].__setitem__("production_registration", True),
            "water": lambda value: value["water_policy"].__setitem__("selectable", True),
            "extra": lambda value: value.__setitem__("undeclared", True),
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    value = json.loads(json.dumps(self.config))
                    mutate(value)
                    path = self.write_config(root / name, value)
                    with self.assertRaises(self.g.Gate3Error):
                        self.g.load_config(path)

    def test_schema_is_strict_for_every_material_block(self) -> None:
        schema = json.loads((ROOT / "tools" / "opengs_eval" / "gate3_config.schema.json").read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        for key in ("source", "projection", "theatre", "raster", "counts", "generator", "density", "terrain", "gate2", "water_policy", "isolation"):
            self.assertFalse(schema["properties"][key]["additionalProperties"], key)

    def test_source_file_set_cannot_expand(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            value = json.loads(json.dumps(self.config))
            value["source"]["files"].append({"role": "terrain", "path": "terrain.geojson", "git_blob_sha1": "0" * 40, "sha256": "0" * 64})
            path = Path(td) / "config.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(self.g.Gate3Error):
                self.g.load_config(path)


class Gate3CandidateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.g = load_module()

    @staticmethod
    def province(pid: str, *, water: bool, neighbors: list[str]) -> dict:
        return {"id": pid, "is_water": water, "selectable": not water, "province_type": "ocean" if water else "land", "neighbors": neighbors}

    def valid_dataset(self) -> dict:
        return {
            "map_id": self.g.CANDIDATE_ID,
            "provinces": [self.province("og2_000001", water=False, neighbors=["og2_000002"]), self.province("og2_000002", water=True, neighbors=["og2_000001"])],
            "edges": [["og2_000001", "og2_000002"]],
        }

    def test_candidate_namespace_water_and_reciprocal_adjacency(self) -> None:
        summary = self.g._validate_candidate_dataset(self.valid_dataset(), self.g.CANDIDATE_ID)
        self.assertEqual(summary["province_count"], 2)
        self.assertEqual(summary["land_count"], 1)
        self.assertEqual(summary["water_count"], 1)
        self.assertEqual(summary["edge_count"], 1)

    def test_selectable_water_is_rejected(self) -> None:
        dataset = self.valid_dataset()
        dataset["provinces"][1]["selectable"] = True
        with self.assertRaisesRegex(self.g.Gate3Error, "water province is selectable"):
            self.g._validate_candidate_dataset(dataset, self.g.CANDIDATE_ID)

    def test_nonreciprocal_adjacency_is_rejected(self) -> None:
        dataset = self.valid_dataset()
        dataset["provinces"][1]["neighbors"] = []
        with self.assertRaisesRegex(self.g.Gate3Error, "nonreciprocal adjacency"):
            self.g._validate_candidate_dataset(dataset, self.g.CANDIDATE_ID)

    def test_wrong_namespace_or_map_id_is_rejected(self) -> None:
        dataset = self.valid_dataset()
        dataset["map_id"] = "earth3_europe_mediterranean"
        with self.assertRaises(self.g.Gate3Error):
            self.g._validate_candidate_dataset(dataset, self.g.CANDIDATE_ID)
        dataset = self.valid_dataset()
        dataset["provinces"][0]["id"] = "e3_0001"
        with self.assertRaises(self.g.Gate3Error):
            self.g._validate_candidate_dataset(dataset, self.g.CANDIDATE_ID)

    def test_land_holes_do_not_create_ocean_and_lake_islands_remain_land(self) -> None:
        class Ring:
            def __init__(self, coords):
                self.coords = coords

        class Polygon:
            exterior = Ring([(0, 0), (4, 0), (4, 4), (0, 4)])
            interiors = [Ring([(1, 1), (2, 1), (2, 2), (1, 2)])]

        class Draw:
            def __init__(self):
                self.fills = []

            def polygon(self, points, *, fill):
                self.fills.append(fill)

        land_draw = Draw()
        self.g._draw_land_polygon(land_draw, Polygon())
        self.assertEqual(land_draw.fills, [self.g.LAND_COLOR, self.g.LAND_COLOR])

        lake_draw = Draw()
        self.g._draw_lake_polygon(lake_draw, Polygon())
        self.assertEqual(lake_draw.fills, [self.g.LAKE_COLOR, self.g.LAND_COLOR])

    def test_city_and_corridor_density_are_deterministic(self) -> None:
        policy = {"baseline": 235, "city_radius_min": 5, "city_radius_max": 36, "city_depth_min": 45, "city_depth_max": 220}
        left = np.full((32, 32), 235.0, dtype=np.float64)
        right = left.copy()
        self.g.apply_city_density(left, 16.0, 16.0, 1_000_000, policy)
        self.g.apply_city_density(right, 16.0, 16.0, 1_000_000, policy)
        np.testing.assert_array_equal(left, right)
        self.assertLess(left[16, 16], left[0, 0])
        mask = np.zeros((32, 32), dtype=bool)
        mask[:, 16] = True
        self.g.apply_corridor_density(left, mask, baseline=235.0, sigma=4.0, depth=25.0)
        self.assertLess(left[0, 16], left[0, 0])

    def test_empty_density_corridor_is_rejected(self) -> None:
        density = np.full((8, 8), 235.0, dtype=np.float64)
        with self.assertRaisesRegex(self.g.Gate3Error, "corridor mask is empty"):
            self.g.apply_corridor_density(density, np.zeros((8, 8), dtype=bool), baseline=235.0, sigma=4.0, depth=25.0)

    def test_regular_file_capture_rejects_directory_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(self.g.Gate3Error):
                self.g._read_regular_file(root, "directory")
            target = root / "target.txt"
            target.write_text("authority", encoding="utf-8")
            link = root / "link.txt"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlinks are unavailable")
            with self.assertRaises(self.g.Gate3Error):
                self.g._read_regular_file(link, "symlink")


class Gate3StaticBoundaryTests(unittest.TestCase):
    def test_workflow_pins_natural_earth_and_stops_at_gate3(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("f1890d9f152c896d250a77557a5751a93d494776", text)
        self.assertIn("gate3_prototype.py run", text)
        self.assertNotIn("config/earth3/", text)
        self.assertNotIn("godot/assets/maps/earth3_europe_mediterranean/", text)
        self.assertNotIn("Gate 4", text)

    def test_gate3_code_has_no_production_write_target(self) -> None:
        paths = [SCRIPT, SCRIPT.with_name("gate3_core.py"), SCRIPT.with_name("gate3_inputs.py"), SCRIPT.with_name("gate3_reports.py"), SCRIPT.with_name("gate3_package.py")]
        text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        self.assertNotIn("godot/assets/maps/earth3_europe_mediterranean", text)
        self.assertNotIn("config/earth3/production_authority.json", text)
        self.assertIn("production_registration", text)
        self.assertIn("debug_only", text)


if __name__ == "__main__":
    unittest.main()
