from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "tools" / "opengs_eval"
ADAPTER = MODULE_DIR / "gate1_to_gate2_adapter.py"
CONFIG_SCHEMA = MODULE_DIR / "gate2_config.schema.json"
OPTIONAL = ("numpy", "PIL", "shapely")


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


class Gate2StaticContractTests(unittest.TestCase):
    def test_adapter_dependency_boundary_and_no_runtime_imports(self) -> None:
        tree = ast.parse(ADAPTER.read_text(encoding="utf-8"), filename=str(ADAPTER))
        banned_roots = {"godot", "PyQt5", "PyQt6", "PySide2", "PySide6", "tkinter"}
        banned_names = {"RenderingDevice", "QApplication"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], banned_roots)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], banned_roots)
            elif isinstance(node, ast.Name):
                self.assertNotIn(node.id, banned_names)
            elif isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, banned_names)

    def test_config_schema_is_strict_and_isolated(self) -> None:
        schema = json.loads(CONFIG_SCHEMA.read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["id_prefix"]["const"], "og2_")
        self.assertEqual(schema["properties"]["minimum_shared_edge_pixels"]["minimum"], 1)


@unittest.skipUnless(
    all(importlib.util.find_spec(name) for name in OPTIONAL),
    "optional Gate 2 geometry dependencies are not installed",
)
class Gate2GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if str(MODULE_DIR) not in sys.path:
            sys.path.insert(0, str(MODULE_DIR))
        spec = importlib.util.spec_from_file_location("gate1_to_gate2_adapter", ADAPTER)
        assert spec and spec.loader
        cls.g = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.g
        spec.loader.exec_module(cls.g)
        import numpy as np
        cls.np = np
        from PIL import Image
        cls.Image = Image

    def source(self, sid: str, ptype: str = "land", rgb=(10, 20, 30)):
        return self.g.ProvinceSource(sid, "TRT000001", ptype, 0.0, 0.0, rgb)

    def components_for(self, labels, label: int, sid: str = "PRV000001"):
        directed, _, _ = self.g.build_boundary_graph(labels)
        rings = self.g.trace_rings(directed[label])
        return rings, self.g.build_components(rings, sid)

    def test_single_polygon_fixture(self) -> None:
        labels = self.np.full((6, 7), -1, dtype=self.np.int32)
        labels[1:5, 2:6] = 0
        rings, components = self.components_for(labels, 0)
        self.assertEqual(len(rings), 1)
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].area, 16.0)
        verts, tris, error = self.g.triangulate_components(components, "PRV000001")
        self.assertGreaterEqual(len(verts), 8)
        self.assertGreaterEqual(len(tris), 6)
        self.assertLessEqual(error, self.g.AREA_REL_TOL)

    def test_hole_and_multiple_holes_fixtures(self) -> None:
        labels = self.np.full((12, 16), -1, dtype=self.np.int32)
        labels[1:11, 1:15] = 0
        labels[3:5, 3:6] = -1
        labels[6:9, 9:13] = -1
        rings, components = self.components_for(labels, 0)
        self.assertEqual(len(rings), 3)
        self.assertEqual(len(components), 1)
        self.assertEqual(len(components[0].interiors), 2)
        _verts, _tris, error = self.g.triangulate_components(components, "PRV000001")
        self.assertLessEqual(error, self.g.AREA_REL_TOL)

    def test_multipart_islands_fixture(self) -> None:
        labels = self.np.full((10, 14), -1, dtype=self.np.int32)
        labels[1:4, 1:5] = 0
        labels[6:9, 9:13] = 0
        rings, components = self.components_for(labels, 0)
        self.assertEqual(len(rings), 2)
        self.assertEqual(len(components), 2)
        self.assertEqual(sum(poly.area for poly in components), 24.0)

    def test_nested_lake_and_water_policy_fixture(self) -> None:
        labels = self.np.full((10, 10), -1, dtype=self.np.int32)
        labels[1:9, 1:9] = 0
        labels[3:7, 3:7] = 1
        directed, _segments, pairs = self.g.build_boundary_graph(labels)
        land = self.g.build_components(self.g.trace_rings(directed[0]), "LAND")
        lake = self.g.build_components(self.g.trace_rings(directed[1]), "LAKE")
        self.assertEqual(len(land[0].interiors), 1)
        self.assertEqual(len(lake), 1)
        self.assertEqual(pairs[(0, 1)], 16)

    def test_corner_only_contact_is_not_adjacency(self) -> None:
        labels = self.np.full((4, 4), -1, dtype=self.np.int32)
        labels[1, 1] = 0
        labels[2, 2] = 1
        _directed, _segments, pairs = self.g.build_boundary_graph(labels)
        self.assertNotIn((0, 1), pairs)

    def test_one_pixel_edge_respects_versioned_threshold(self) -> None:
        labels = self.np.full((4, 5), -1, dtype=self.np.int32)
        labels[1, 1] = 0
        labels[1, 2] = 1
        _directed, _segments, pairs = self.g.build_boundary_graph(labels)
        self.assertEqual(pairs[(0, 1)], 1)
        self.assertFalse(pairs[(0, 1)] >= 2)
        self.assertTrue(pairs[(0, 1)] >= 1)

    def test_multipart_coast_and_exterior_border_classes(self) -> None:
        labels = self.np.full((6, 8), -1, dtype=self.np.int32)
        labels[0:3, 0:3] = 0
        labels[4:6, 5:8] = 0
        labels[1:5, 3:5] = 1
        sources = [self.source("LAND", "land", (1, 2, 3)), self.source("SEA", "ocean", (4, 5, 6))]
        config = self.g.Config("opengs_gate2_test", "og2_", 1, frozenset(), frozenset())
        records, _flat, _supp = self.g._build_border_classes(labels, sources, {0: "og2_000001", 1: "og2_000002"}, config)
        classes = {row["class"] for row in records}
        self.assertIn("coast", classes)
        self.assertIn("theatre_exterior", classes)

    def test_invalid_self_intersection_is_rejected(self) -> None:
        bowtie = [[(0, 0), (3, 3), (0, 3), (3, 0)]]
        with self.assertRaises(self.g.Gate2Error):
            self.g.build_components(bowtie, "BAD")

    def test_interior_anchor_has_measured_clearance(self) -> None:
        labels = self.np.full((9, 9), -1, dtype=self.np.int32)
        labels[1:8, 1:8] = 0
        labels[3:6, 3:6] = -1
        _, components = self.components_for(labels, 0)
        x, y, clearance = self.g.interior_anchor(components)
        self.assertGreater(clearance, 0)
        point = self.g.Point(x, y)
        self.assertTrue(components[0].contains(point))
        self.assertGreaterEqual(point.distance(components[0].boundary) + 1e-4, clearance)

    def test_full_area_terrain_percentages(self) -> None:
        terrain = self.np.zeros((2, 4, 3), dtype=self.np.uint8)
        terrain[:, :3] = self.g.LAND_TERRAINS["forest"]
        terrain[:, 3:] = self.g.LAND_TERRAINS["mountain"]
        coverage, pixels, dominant = self.g.terrain_coverage(
            terrain, self.np.ones((2, 4), dtype=bool), "land"
        )
        self.assertEqual(pixels, {"forest": 6, "mountain": 2})
        self.assertEqual(coverage, {"forest": 0.75, "mountain": 0.25})
        self.assertEqual(dominant, "forest")

    def make_gate1_output(self, root: Path, labels, sources, terrain) -> tuple[Path, Path]:
        gate1 = root / "gate1"
        gate1.mkdir()
        image = self.np.zeros((*labels.shape, 3), dtype=self.np.uint8)
        rows = []
        for index, source in enumerate(sources):
            image[labels == index] = source.rgb
            ys, xs = self.np.where(labels == index)
            rows.append({
                "B": source.rgb[2], "G": source.rgb[1], "R": source.rgb[0],
                "province_id": source.source_id,
                "province_terrain": "plains" if source.province_type == "land" else ("lakes" if source.province_type == "lake" else "deep_ocean"),
                "province_type": source.province_type,
                "territory_id": source.territory_id,
                "x": float(xs.mean()), "y": float(ys.mean()),
            })
        self.Image.fromarray(image, "RGB").save(gate1 / "provinces.png")
        self.Image.fromarray(self.np.zeros_like(image), "RGB").save(gate1 / "territories.png")
        (gate1 / "provinces.json").write_bytes(canonical(rows))
        (gate1 / "territories.json").write_bytes(canonical([]))
        terrain_path = root / "terrain.png"
        self.Image.fromarray(terrain, "RGB").save(terrain_path)
        outputs = {
            name: hashlib.sha256((gate1 / name).read_bytes()).hexdigest()
            for name in ("territories.png", "provinces.png", "territories.json", "provinces.json")
        }
        manifest = {
            "schema": "gates-of-codex.opengs-run-manifest",
            "schema_version": 1,
            "dimensions": {"width": int(labels.shape[1]), "height": int(labels.shape[0])},
            "inputs": {"terrain": {"path": "terrain.png", "sha256": hashlib.sha256(terrain_path.read_bytes()).hexdigest()}},
            "outputs": outputs,
            "recipe": {"recipe_id": "test", "root_seed": 1, "canonical_sha256": "0" * 64},
        }
        (gate1 / "run_manifest.json").write_bytes(canonical(manifest))
        return gate1, terrain_path

    def config_file(self, root: Path, threshold: int = 1) -> Path:
        path = root / "config.json"
        path.write_bytes(canonical({
            "authored_boundary_pairs": [],
            "id_prefix": "og2_",
            "map_id": "opengs_gate2_test",
            "minimum_shared_edge_pixels": threshold,
            "schema": "gates-of-codex.opengs-gate2-config",
            "schema_version": 1,
            "suppressed_segments": [],
        }))
        return path

    def test_end_to_end_deterministic_ids_water_and_inspection(self) -> None:
        labels = self.np.full((12, 16), -1, dtype=self.np.int32)
        labels[1:11, 1:15] = 0
        labels[4:8, 6:10] = 1
        labels[1:3, 13:15] = 2
        sources = [
            self.source("PRV000010", "land", (10, 20, 30)),
            self.source("PRV000002", "lake", (40, 50, 60)),
            self.source("PRV000005", "land", (70, 80, 90)),
        ]
        terrain = self.np.zeros((*labels.shape, 3), dtype=self.np.uint8)
        terrain[:] = self.g.LAND_TERRAINS["plains"]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate1, terrain_path = self.make_gate1_output(root, labels, sources, terrain)
            config = self.config_file(root)
            out_a, out_b = root / "a", root / "b"
            self.g.convert(gate1, terrain_path, config, out_a)
            self.g.convert(gate1, terrain_path, config, out_b)
            self.assertTrue(self.g.compare_runs(out_a, out_b, gate1, terrain_path, config)["identical"])
            dataset = json.loads((out_a / "polygon_dataset.json").read_text())
            self.assertEqual([row["source_id"] for row in dataset["provinces"]], ["PRV000002", "PRV000005", "PRV000010"])
            self.assertEqual([row["id"] for row in dataset["provinces"]], ["og2_000001", "og2_000002", "og2_000003"])
            lake = next(row for row in dataset["provinces"] if row["source_id"] == "PRV000002")
            self.assertTrue(lake["is_water"])
            self.assertFalse(lake["selectable"])
            self.assertFalse(any(row["id"].startswith("e3_") for row in dataset["provinces"]))

    def test_inspection_rejects_resealed_hole_filling_triangle(self) -> None:
        labels = self.np.full((10, 10), -1, dtype=self.np.int32)
        labels[1:9, 1:9] = 0
        labels[3:7, 3:7] = 1
        sources = [self.source("LAND", "land", (10, 20, 30)), self.source("LAKE", "lake", (40, 50, 60))]
        terrain = self.np.zeros((*labels.shape, 3), dtype=self.np.uint8)
        terrain[:] = self.g.LAND_TERRAINS["plains"]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate1, terrain_path = self.make_gate1_output(root, labels, sources, terrain)
            output = root / "output"
            config = self.config_file(root)
            self.g.convert(gate1, terrain_path, config, output)
            dataset_path = output / "polygon_dataset.json"
            dataset = json.loads(dataset_path.read_text())
            land = next(row for row in dataset["provinces"] if not row["is_water"])
            # Replace with a triangle spanning the hole, then reseal every reported hash.
            land["vertices"] = [1.0, 1.0, 9.0, 1.0, 1.0, 9.0]
            land["triangles"] = [0, 1, 2]
            dataset_path.write_bytes(canonical(dataset))
            ds_sha = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
            meta_path = output / "dataset_meta.json"
            meta = json.loads(meta_path.read_text())
            meta["dataset_sha256"] = ds_sha
            meta_path.write_bytes(canonical(meta))
            map_path = output / "map_manifest.json"
            map_manifest = json.loads(map_path.read_text())
            map_manifest["polygon_dataset"]["sha256"] = ds_sha
            map_path.write_bytes(canonical(map_manifest))
            adapter_path = output / "adapter_manifest.json"
            adapter = json.loads(adapter_path.read_text())
            for name in ("polygon_dataset.json", "dataset_meta.json", "map_manifest.json"):
                adapter["outputs"][name] = hashlib.sha256((output / name).read_bytes()).hexdigest()
            adapter_path.write_bytes(canonical(adapter))
            with self.assertRaises(self.g.Gate2Error):
                self.g.inspect_output(output, gate1, terrain_path, config)

    def reseal_dataset_outputs(self, output: Path) -> None:
        dataset_sha = hashlib.sha256((output / "polygon_dataset.json").read_bytes()).hexdigest()
        meta_path = output / "dataset_meta.json"
        meta = json.loads(meta_path.read_text())
        meta["dataset_sha256"] = dataset_sha
        meta_path.write_bytes(canonical(meta))
        map_path = output / "map_manifest.json"
        map_manifest = json.loads(map_path.read_text())
        map_manifest["polygon_dataset"]["sha256"] = dataset_sha
        map_path.write_bytes(canonical(map_manifest))
        adapter_path = output / "adapter_manifest.json"
        adapter = json.loads(adapter_path.read_text())
        for name in ("polygon_dataset.json", "dataset_meta.json", "map_manifest.json", "topology_audit.json"):
            adapter["outputs"][name] = hashlib.sha256((output / name).read_bytes()).hexdigest()
        adapter_path.write_bytes(canonical(adapter))

    def make_three_province_chain(self, root: Path):
        labels = self.np.full((6, 12), -1, dtype=self.np.int32)
        labels[1:5, 1:4] = 0
        labels[1:5, 4:7] = 1
        labels[1:5, 7:10] = 2
        sources = [
            self.source("A", "land", (10, 20, 30)),
            self.source("B", "land", (40, 50, 60)),
            self.source("C", "land", (70, 80, 90)),
        ]
        terrain = self.np.zeros((*labels.shape, 3), dtype=self.np.uint8)
        terrain[:] = self.g.LAND_TERRAINS["plains"]
        gate1, terrain_path = self.make_gate1_output(root, labels, sources, terrain)
        config = self.config_file(root)
        output = root / "output"
        self.g.convert(gate1, terrain_path, config, output)
        return gate1, terrain_path, config, output

    def test_inspection_authenticates_all_provenance_classes(self) -> None:
        labels = self.np.full((6, 7), -1, dtype=self.np.int32)
        labels[1:5, 1:6] = 0
        sources = [self.source("ONLY", "land", (10, 20, 30))]
        terrain = self.np.zeros((*labels.shape, 3), dtype=self.np.uint8)
        terrain[:] = self.g.LAND_TERRAINS["plains"]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate1, terrain_path = self.make_gate1_output(root, labels, sources, terrain)
            config = self.config_file(root)
            pristine = root / "pristine"
            self.g.convert(gate1, terrain_path, config, pristine)
            mutations = {
                "adapter_version": lambda m: m.__setitem__("adapter_version", 999),
                "adapter_source": lambda m: m.__setitem__("adapter_source_sha256", "f" * 64),
                "config_digest": lambda m: m["config"].__setitem__("canonical_sha256", "f" * 64),
                "config_payload": lambda m: m["config"]["payload"].__setitem__("minimum_shared_edge_pixels", 9),
                "gate1_manifest": lambda m: m["gate1"].__setitem__("run_manifest_sha256", "f" * 64),
                "gate1_outputs": lambda m: m["gate1"]["outputs"].__setitem__("provinces.png", "f" * 64),
                "terrain": lambda m: m.__setitem__("terrain_sha256", "f" * 64),
                "determinism": lambda m: m["determinism"].__setitem__("exact_grid_topology", False),
            }
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    candidate = root / name
                    shutil.copytree(pristine, candidate)
                    manifest_path = candidate / "adapter_manifest.json"
                    manifest = json.loads(manifest_path.read_text())
                    mutate(manifest)
                    manifest_path.write_bytes(canonical(manifest))
                    with self.assertRaises(self.g.Gate2Error):
                        self.g.inspect_output(candidate, gate1, terrain_path, config)

    def test_inspection_rejects_equal_area_duplicate_and_omission(self) -> None:
        labels = self.np.full((8, 8), -1, dtype=self.np.int32)
        labels[1:7, 1:7] = 0
        sources = [self.source("LAND", "land", (10, 20, 30))]
        terrain = self.np.zeros((*labels.shape, 3), dtype=self.np.uint8)
        terrain[:] = self.g.LAND_TERRAINS["plains"]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate1, terrain_path = self.make_gate1_output(root, labels, sources, terrain)
            config = self.config_file(root)
            output = root / "output"
            self.g.convert(gate1, terrain_path, config, output)
            dataset_path = output / "polygon_dataset.json"
            dataset = json.loads(dataset_path.read_text())
            row = dataset["provinces"][0]
            vertices = list(zip(row["vertices"][::2], row["vertices"][1::2]))
            triples = [row["triangles"][i:i+3] for i in range(0, len(row["triangles"]), 3)]
            areas = []
            for tri in triples:
                poly = self.g.Polygon([vertices[index] for index in tri])
                areas.append(poly.area)
            pair = next((i, j) for i in range(len(triples)) for j in range(i + 1, len(triples)) if triples[i] != triples[j] and abs(areas[i] - areas[j]) < 1e-12)
            triples[pair[1]] = list(triples[pair[0]])
            row["triangles"] = [index for tri in triples for index in tri]
            dataset_path.write_bytes(canonical(dataset))
            self.reseal_dataset_outputs(output)
            with self.assertRaisesRegex(self.g.Gate2Error, "overlap|exactly cover"):
                self.g.inspect_output(output, gate1, terrain_path, config)

    def test_inspection_rejects_coherent_adjacency_forgery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate1, terrain_path, config, output = self.make_three_province_chain(root)
            dataset_path = output / "polygon_dataset.json"
            dataset = json.loads(dataset_path.read_text())
            rows = {row["source_id"]: row for row in dataset["provinces"]}
            a, b, c = rows["A"]["id"], rows["B"]["id"], rows["C"]["id"]
            dataset["edges"] = sorted([[a, c], [b, c]])
            rows["A"]["neighbors"] = [c]
            rows["B"]["neighbors"] = [c]
            rows["C"]["neighbors"] = sorted([a, b])
            dataset_path.write_bytes(canonical(dataset))
            audit_path = output / "topology_audit.json"
            audit = json.loads(audit_path.read_text())
            for entry in audit["shared_edges"]:
                if {entry["a"], entry["b"]} == {a, b}:
                    entry["adjacent"] = False
            audit["shared_edges"].append({"a": a, "b": c, "shared_edge_pixels": 1, "minimum": 1, "adjacent": True})
            audit["shared_edges"].sort(key=lambda row: (row["a"], row["b"]))
            audit_path.write_bytes(canonical(audit))
            self.reseal_dataset_outputs(output)
            with self.assertRaisesRegex(self.g.Gate2Error, "measured shared boundaries"):
                self.g.inspect_output(output, gate1, terrain_path, config)

    def test_inspection_rejects_border_ledger_forgery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate1, terrain_path, config, output = self.make_three_province_chain(root)
            dataset_path = output / "polygon_dataset.json"
            dataset = json.loads(dataset_path.read_text())
            record = next(row for row in dataset["border_classes"] if row["class"] == "internal_land")
            record["class"] = "authored_boundary"
            dataset["border_classes"].sort(key=lambda row: (row["class"], row["segment"], row["left_id"] or "", row["right_id"] or ""))
            dataset_path.write_bytes(canonical(dataset))
            audit_path = output / "topology_audit.json"
            audit = json.loads(audit_path.read_text())
            audit["border_class_counts"]["internal_land"] -= 1
            audit["border_class_counts"]["authored_boundary"] = 1
            audit_path.write_bytes(canonical(audit))
            self.reseal_dataset_outputs(output)
            with self.assertRaisesRegex(self.g.Gate2Error, "border class ledger"):
                self.g.inspect_output(output, gate1, terrain_path, config)

    @unittest.skipUnless(os.environ.get("GATE2_GATE1_OUTPUT"), "dedicated workflow Gate 1 fixture not supplied")
    def test_real_gate1_fixture_two_runs_byte_identical(self) -> None:
        gate1 = Path(os.environ["GATE2_GATE1_OUTPUT"])
        terrain = Path(os.environ["GATE2_TERRAIN"])
        config = Path(os.environ["GATE2_CONFIG"])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a, b = root / "a", root / "b"
            self.g.convert(gate1, terrain, config, a)
            self.g.convert(gate1, terrain, config, b)
            self.assertTrue(self.g.compare_runs(a, b, gate1, terrain, config)["identical"])
            dataset = json.loads((a / "polygon_dataset.json").read_text())
            self.assertEqual(dataset["province_count"], 123)
            self.assertEqual(dataset["land_count"], 96)
            self.assertEqual(dataset["water_count"], 27)


if __name__ == "__main__":
    unittest.main()
