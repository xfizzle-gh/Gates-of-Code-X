from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType

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

    def test_locked_config_digest_and_direct_comparison_total(self) -> None:
        config, digest, raw = self.g.load_config(CONFIG)
        self.assertEqual(digest, self.g.LOCKED_CONFIG_CANONICAL_SHA256)
        self.assertEqual(config["candidate_id"], self.g.CANDIDATE_ID)
        self.assertEqual(config["starting_commit"], self.g.STARTING_COMMIT)
        self.assertEqual(config["counts"]["land_provinces"], 3299)
        self.assertEqual(config["counts"]["ocean_provinces"], 215)
        self.assertEqual(config["counts"]["land_provinces"] + config["counts"]["ocean_provinces"], 3514)
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

    def test_exact_config_digest_locks_every_material_block(self) -> None:
        mutations = {
            "source_path": lambda v: v["source"]["files"][0].__setitem__("path", "geojson/other.geojson"),
            "source_blob": lambda v: v["source"]["files"][0].__setitem__("git_blob_sha1", "0" * 40),
            "source_sha": lambda v: v["source"]["files"][0].__setitem__("sha256", "0" * 64),
            "terms": lambda v: v["source"].__setitem__("terms_url", "https://example.invalid/terms"),
            "projection": lambda v: v["projection"].__setitem__("proj", "+proj=merc"),
            "crop": lambda v: v["theatre"].__setitem__("lon_lat_bounds", [-12.0, 27.0, 45.0, 75.0]),
            "crop_policy": lambda v: v["theatre"].__setitem__("policy", "other_policy"),
            "anchors": lambda v: v["theatre"]["anchors"][0].__setitem__("longitude", -7.9),
            "land_territories": lambda v: v["counts"].__setitem__("land_territories", 351),
            "ocean_territories": lambda v: v["counts"].__setitem__("ocean_territories", 21),
            "seed": lambda v: v["generator"].__setitem__("root_seed", 3514004),
            "lloyd": lambda v: v["generator"].__setitem__("lloyd_iterations", 5),
            "generator_option": lambda v: v["generator"].__setitem__("jagged_land", True),
            "density_radius": lambda v: v["density"].__setitem__("city_radius_max", 35),
            "density_weight": lambda v: v["density"].__setitem__("boundary_depth", 39.0),
            "terrain": lambda v: v["terrain"].__setitem__("land", "forest"),
            "gate2_threshold": lambda v: v["gate2"].__setitem__("minimum_shared_edge_pixels", 2),
            "water": lambda v: v["water_policy"].__setitem__("selectable", True),
            "registration": lambda v: v["isolation"].__setitem__("production_registration", True),
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


class Gate3SourceAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.g = load_module()

    def test_source_capture_uses_exact_git_blob_not_worktree_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "gate3@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Gate 3 Test"], cwd=root, check=True)
            source = root / "source.geojson"
            committed = b'{"type":"FeatureCollection","features":[]}\n'
            source.write_bytes(committed)
            subprocess.run(["git", "add", "source.geojson"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "source"], cwd=root, check=True, capture_output=True)
            commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
            blob = subprocess.run(["git", "rev-parse", f"{commit}:source.geojson"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
            source.write_bytes(committed.replace(b"\n", b"\r\n"))
            config = {"source": {"commit": commit, "files": [{"role": "land", "path": "source.geojson", "git_blob_sha1": blob, "sha256": self.g.sha256_bytes(committed)}]}}
            captured = self.g.capture_sources(config, root)
            self.assertEqual(captured["land"]["data"], committed)
            self.assertEqual(captured["land"]["authority"], "git_blob_bytes")


class Gate3CandidateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.g = load_module()

    @staticmethod
    def province(pid: str, *, water: bool, neighbors: list[str]) -> dict:
        return {"id": pid, "is_water": water, "selectable": not water, "province_type": "ocean" if water else "land", "neighbors": neighbors}

    def valid_dataset(self) -> dict:
        return {"map_id": self.g.CANDIDATE_ID, "provinces": [self.province("og2_000001", water=False, neighbors=["og2_000002"]), self.province("og2_000002", water=True, neighbors=["og2_000001"])], "edges": [["og2_000001", "og2_000002"]]}

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

    def test_projected_outside_pixels_are_excluded_from_both_generation_masks(self) -> None:
        land = np.full((4, 4, 3), self.g.OCEAN_COLOR, dtype=np.uint8)
        boundary = np.full((4, 4, 3), self.g.BOUNDARY_BACKGROUND, dtype=np.uint8)
        boundary[0, :] = self.g.OUTSIDE_COLOR
        boundary[-1, :] = self.g.OUTSIDE_COLOR
        boundary[:, 0] = self.g.OUTSIDE_COLOR
        boundary[:, -1] = self.g.OUTSIDE_COLOR
        land[1, 1] = self.g.LAND_COLOR
        masks = self.g._masked_extract_masks(land, boundary)
        outside = np.zeros((4, 4), dtype=bool)
        outside[0, :] = outside[-1, :] = True
        outside[:, 0] = outside[:, -1] = True
        self.assertFalse(np.any(masks["land_mask"] & outside))
        self.assertFalse(np.any(masks["sea_mask"] & outside))
        self.assertTrue(masks["land_mask"][1, 1])
        self.assertTrue(masks["sea_mask"][1, 2])

    def test_land_holes_do_not_create_ocean_and_lake_islands_remain_land(self) -> None:
        class Ring:
            def __init__(self, coords): self.coords = coords
        class Polygon:
            exterior = Ring([(0, 0), (4, 0), (4, 4), (0, 4)])
            interiors = [Ring([(1, 1), (2, 1), (2, 2), (1, 2)])]
        class Draw:
            def __init__(self): self.fills = []
            def polygon(self, points, *, fill): self.fills.append(fill)
        land_draw = Draw(); self.g._draw_land_polygon(land_draw, Polygon())
        self.assertEqual(land_draw.fills, [self.g.LAND_COLOR, self.g.LAND_COLOR])
        lake_draw = Draw(); self.g._draw_lake_polygon(lake_draw, Polygon())
        self.assertEqual(lake_draw.fills, [self.g.LAKE_COLOR, self.g.LAND_COLOR])

    def test_city_and_corridor_density_are_deterministic(self) -> None:
        policy = {"baseline": 235, "city_radius_min": 5, "city_radius_max": 36, "city_depth_min": 45, "city_depth_max": 220}
        left = np.full((32, 32), 235.0, dtype=np.float64); right = left.copy()
        self.g.apply_city_density(left, 16.0, 16.0, 1_000_000, policy)
        self.g.apply_city_density(right, 16.0, 16.0, 1_000_000, policy)
        np.testing.assert_array_equal(left, right)
        mask = np.zeros((32, 32), dtype=bool); mask[:, 16] = True
        self.g.apply_corridor_density(left, mask, baseline=235.0, sigma=4.0, depth=25.0)
        self.assertLess(left[0, 16], left[0, 0])


class Gate3PackageAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.g = load_module()
        cls.config_bytes = CONFIG.read_bytes()
        cls.config = json.loads(cls.config_bytes)
        cls.config_sha = cls.g.LOCKED_CONFIG_CANONICAL_SHA256

    def make_authority_snapshot(self):
        dummy = {name: (name + "\n").encode() for name in ("land.png", "boundary.png", "density.png", "terrain.png", "theatre_mask.png")}
        recipe = {
            "schema": "gates-of-codex.opengs-recipe", "schema_version": 1,
            "recipe_id": self.g.CANDIDATE_ID, "root_seed": 3514003,
            "inputs": {key: {"path": f"{key}.png", "sha256": self.g.sha256_bytes(dummy[f"{key}.png"])} for key in ("land", "boundary", "density", "terrain")},
            "counts": {"land_territories": 350, "ocean_territories": 20, "land_provinces": 3299, "ocean_provinces": 215},
            "options": {"lloyd_iterations": 4, "density_strength": 2.0, "exclude_ocean_density": True, "jagged_land": False, "jagged_ocean": False, "jagged_amplitude": 0.12},
        }
        recipe_bytes = self.g.canonical_json_bytes(recipe)
        gate1_manifest = {"recipe": {"recipe_id": self.g.CANDIDATE_ID, "root_seed": 3514003, "canonical_sha256": self.g.sha256_bytes(recipe_bytes)}, "inputs": recipe["inputs"]}
        gate1_bytes = self.g.canonical_json_bytes(gate1_manifest)
        input_manifest = {
            "schema": self.g.INPUT_SCHEMA, "schema_version": self.g.INPUT_SCHEMA_VERSION,
            "gate3_config_sha256": self.config_sha,
            "outputs": {name: {"sha256": self.g.sha256_bytes(data)} for name, data in dummy.items()},
            "theatre_mask": {"sha256": self.g.sha256_bytes(dummy["theatre_mask.png"])},
        }
        gate2_manifest = {"gate1": {"run_manifest_sha256": self.g.sha256_bytes(gate1_bytes), "recipe": gate1_manifest["recipe"]}, "terrain_sha256": self.g.sha256_bytes(dummy["terrain.png"])}
        files = {
            "inputs/gate3_config.json": self.config_bytes,
            "inputs/gate3_input_manifest.json": self.g.canonical_json_bytes(input_manifest),
            "inputs/gate1_recipe.json": recipe_bytes,
            "gate1/run_manifest.json": gate1_bytes,
            "candidate/adapter_manifest.json": self.g.canonical_json_bytes(gate2_manifest),
            "candidate/polygon_dataset.json": self.g.canonical_json_bytes({"map_id": self.g.CANDIDATE_ID}),
            "candidate/dataset_meta.json": self.g.canonical_json_bytes({}),
            "candidate/map_manifest.json": self.g.canonical_json_bytes({}),
            "candidate/topology_audit.json": self.g.canonical_json_bytes({}),
        }
        for name, data in dummy.items(): files[f"inputs/{name}"] = data
        return self.g.TreeSnapshot(MappingProxyType(files), MappingProxyType({name: self.g.sha256_bytes(data) for name, data in files.items()}), frozenset())

    def test_resealed_recipe_forgery_is_rejected(self) -> None:
        snapshot = self.make_authority_snapshot()
        files = dict(snapshot.files)
        recipe = json.loads(files["inputs/gate1_recipe.json"])
        recipe["root_seed"] += 1
        files["inputs/gate1_recipe.json"] = self.g.canonical_json_bytes(recipe)
        forged = self.g.TreeSnapshot(MappingProxyType(files), MappingProxyType({name: self.g.sha256_bytes(data) for name, data in files.items()}), frozenset())
        with self.assertRaisesRegex(self.g.Gate3Error, "recipe"):
            self.g._parse_authority(forged)

    def test_resealed_config_manifest_forgery_is_rejected(self) -> None:
        snapshot = self.make_authority_snapshot()
        files = dict(snapshot.files)
        manifest = json.loads(files["inputs/gate3_input_manifest.json"])
        manifest["gate3_config_sha256"] = "0" * 64
        files["inputs/gate3_input_manifest.json"] = self.g.canonical_json_bytes(manifest)
        forged = self.g.TreeSnapshot(MappingProxyType(files), MappingProxyType({name: self.g.sha256_bytes(data) for name, data in files.items()}), frozenset())
        with self.assertRaisesRegex(self.g.Gate3Error, "config digest"):
            self.g._parse_authority(forged)

    def test_resealed_report_forgery_is_rejected(self) -> None:
        dataset = {
            "map_id": self.g.CANDIDATE_ID,
            "provinces": [
                {"id": "og2_000001", "is_water": False, "selectable": True, "province_type": "land", "neighbors": ["og2_000002"], "terrain_id": "plains", "terrain_coverage_pixels": {"plains": 10}},
                {"id": "og2_000002", "is_water": True, "selectable": False, "province_type": "ocean", "neighbors": ["og2_000001"], "terrain_id": "deep_ocean", "terrain_coverage_pixels": {"deep_ocean": 10}},
            ],
            "edges": [["og2_000001", "og2_000002"]],
        }
        input_manifest = {
            "source": {}, "projection": {}, "lon_lat_bounds": [], "projected_bounds": [], "dimensions": {"width": 2, "height": 1},
            "theatre_mask": {}, "component_counts": {"land": 1, "ocean": 1, "lake": 0}, "feature_counts": {"populated_places": 0, "boundary_line_parts": 0, "river_line_parts": 0},
            "geography_anchors": [], "pixel_counts": {}, "density": {"policy": {}, "minimum": 0, "maximum": 0, "mean": 0},
        }
        gate1_manifest = {"counts": {"requested": {}, "actual": {"provinces": 2, "land_provinces": 1, "ocean_provinces": 1, "lake_provinces": 0}}}
        dataset_meta = {"province_count": 2, "vertex_count": 8, "triangle_count": 4, "border_segment_count": 6}
        map_manifest = {"map_id": self.g.CANDIDATE_ID}
        topology = {"ok": True, "province_count": 2, "component_count": 2, "hole_count": 0, "adjacency_edge_count": 1, "border_class_counts": {}, "max_triangle_area_relative_error": 0.0, "minimum_shared_edge_pixels": 1}
        file_sha = {"gate1/run_manifest.json": "1" * 64, "candidate/adapter_manifest.json": "2" * 64, "candidate/topology_audit.json": "3" * 64, "inputs/terrain.png": "4" * 64, "candidate/map_manifest.json": "5" * 64, "inputs/density.png": "6" * 64}
        authority = {"config": self.config, "config_sha": self.config_sha, "input_manifest": input_manifest, "gate1_manifest": gate1_manifest, "dataset": dataset, "dataset_meta": dataset_meta, "map_manifest": map_manifest, "topology": topology}
        reports = self.g.derive_reports(self.config, self.config_sha, input_manifest, gate1_manifest, dataset, dataset_meta, map_manifest, topology, file_sha)
        files = {f"reports/{name}": self.g.canonical_json_bytes(value) for name, value in reports.items()}
        forged_report = json.loads(files["reports/count_report.json"]); forged_report["actual"]["provinces"] = 99
        files["reports/count_report.json"] = self.g.canonical_json_bytes(forged_report)
        sha = {**file_sha, **{name: self.g.sha256_bytes(data) for name, data in files.items()}}
        snapshot = self.g.TreeSnapshot(MappingProxyType(files), MappingProxyType(sha), frozenset())
        with self.assertRaisesRegex(self.g.Gate3Error, "count_report"):
            self.g._verify_report_derivation(snapshot, authority)

    def test_package_rejects_extra_directory_before_parsing(self) -> None:
        snapshot = self.g.TreeSnapshot(MappingProxyType({}), MappingProxyType({}), frozenset({"inputs", "gate1", "candidate", "reports", "extra"}))
        with self.assertRaisesRegex(self.g.Gate3Error, "directory set mismatch"):
            self.g.inspect_snapshot(snapshot)

    def test_tree_capture_rejects_symlink_and_flat_capture_rejects_extra_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "expected.txt").write_text("authority", encoding="utf-8")
            (root / "extra").mkdir()
            with self.assertRaisesRegex(self.g.Gate3Error, "dirs"):
                self.g.capture_flat(root, ["expected.txt"], "fixture")
            (root / "extra").rmdir()
            target = root / "target.txt"
            target.write_text("target", encoding="utf-8")
            link = root / "link.txt"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlinks are unavailable")
            with self.assertRaisesRegex(self.g.Gate3Error, "symlink"):
                self.g.capture_tree(root)


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
