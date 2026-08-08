from __future__ import annotations

import ast
import hashlib
import io
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock
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
        cls._fixture_temp = None
        fixture_names = ("GATE2_GATE1_OUTPUT", "GATE2_TERRAIN", "GATE2_CONFIG")
        if all(os.environ.get(name) for name in fixture_names):
            cls._fixture_temp = tempfile.TemporaryDirectory()
            cls.fixture_gate1 = Path(os.environ["GATE2_GATE1_OUTPUT"]).resolve()
            cls.fixture_terrain = Path(os.environ["GATE2_TERRAIN"]).resolve()
            cls.fixture_config = Path(os.environ["GATE2_CONFIG"]).resolve()
            cls.fixture_output = Path(cls._fixture_temp.name) / "pristine"
            cls.g.convert(
                cls.fixture_gate1,
                cls.fixture_terrain,
                cls.fixture_config,
                cls.fixture_output,
            )

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._fixture_temp is not None:
            cls._fixture_temp.cleanup()

    def png_bytes(self, image) -> bytes:
        buffer = io.BytesIO()
        self.Image.fromarray(image, "RGB").save(buffer, format="PNG")
        return buffer.getvalue()

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

    def real_fixture(self) -> tuple[Path, Path, Path]:
        if self._fixture_temp is None:
            self.skipTest("dedicated workflow fixture not supplied")
        return self.fixture_gate1, self.fixture_terrain, self.fixture_config

    def convert_real(self, root: Path, name: str = "output"):
        gate1, terrain, config = self.real_fixture()
        output = root / name
        shutil.copytree(self.fixture_output, output)
        return gate1, terrain, config, output

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
        for name in (
            "polygon_dataset.json",
            "dataset_meta.json",
            "map_manifest.json",
            "topology_audit.json",
        ):
            adapter["outputs"][name] = hashlib.sha256(
                (output / name).read_bytes()
            ).hexdigest()
        adapter_path.write_bytes(canonical(adapter))

    def test_end_to_end_deterministic_ids_water_and_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate1, terrain, config, out_a = self.convert_real(root, "a")
            out_b = root / "b"
            self.g.convert(gate1, terrain, config, out_b)
            self.assertTrue(
                self.g.compare_runs(out_a, out_b, gate1, terrain, config)["identical"]
            )
            dataset = json.loads((out_a / "polygon_dataset.json").read_text())
            self.assertEqual(dataset["province_count"], len(dataset["provinces"]))
            self.assertEqual(dataset["provinces"][0]["source_id"], "PRV000001")
            self.assertEqual(dataset["provinces"][0]["id"], "og2_000001")
            waters = [row for row in dataset["provinces"] if row["is_water"]]
            self.assertTrue(waters)
            self.assertTrue(all(not row["selectable"] for row in waters))
            self.assertFalse(any(row["id"].startswith("e3_") for row in dataset["provinces"]))

    def test_inspection_rejects_resealed_hole_filling_triangle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate1, terrain, config, output = self.convert_real(root)
            dataset_path = output / "polygon_dataset.json"
            dataset = json.loads(dataset_path.read_text())
            land = next(
                row
                for row in dataset["provinces"]
                if any(component["holes"] for component in row["components"])
            )
            outer = land["components"][0]["outer"]
            land["vertices"] = outer[:6]
            land["triangles"] = [0, 1, 2]
            dataset_path.write_bytes(canonical(dataset))
            self.reseal_dataset_outputs(output)
            with self.assertRaises(self.g.Gate2Error):
                self.g.inspect_output(output, gate1, terrain, config)

    def test_inspection_authenticates_all_provenance_classes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate1, terrain, config, pristine = self.convert_real(root, "pristine")
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
                        self.g.inspect_output(candidate, gate1, terrain, config)

    def test_inspection_rejects_equal_area_duplicate_and_omission(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate1, terrain, config, output = self.convert_real(root)
            dataset_path = output / "polygon_dataset.json"
            dataset = json.loads(dataset_path.read_text())
            chosen = None
            pair = None
            for row in dataset["provinces"]:
                vertices = list(zip(row["vertices"][::2], row["vertices"][1::2]))
                triples = [
                    row["triangles"][i : i + 3]
                    for i in range(0, len(row["triangles"]), 3)
                ]
                areas = [
                    self.g.Polygon([vertices[index] for index in tri]).area
                    for tri in triples
                ]
                found = next(
                    (
                        (i, j)
                        for i in range(len(triples))
                        for j in range(i + 1, len(triples))
                        if triples[i] != triples[j]
                        and abs(areas[i] - areas[j]) < 1e-12
                    ),
                    None,
                )
                if found:
                    chosen, pair = row, found
                    break
            self.assertIsNotNone(chosen)
            assert chosen is not None and pair is not None
            triples = [
                chosen["triangles"][i : i + 3]
                for i in range(0, len(chosen["triangles"]), 3)
            ]
            triples[pair[1]] = list(triples[pair[0]])
            chosen["triangles"] = [index for tri in triples for index in tri]
            dataset_path.write_bytes(canonical(dataset))
            self.reseal_dataset_outputs(output)
            with self.assertRaisesRegex(self.g.Gate2Error, "overlap|exactly cover"):
                self.g.inspect_output(output, gate1, terrain, config)

    def test_inspection_rejects_coherent_adjacency_forgery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate1, terrain, config, output = self.convert_real(root)
            dataset_path = output / "polygon_dataset.json"
            dataset = json.loads(dataset_path.read_text())
            edge_set = {tuple(edge) for edge in dataset["edges"]}
            ids = [row["id"] for row in dataset["provinces"]]
            original = next(iter(sorted(edge_set)))
            a, b = original
            c = next(
                pid
                for pid in ids
                if pid not in {a, b} and tuple(sorted((a, pid))) not in edge_set
            )
            forged = tuple(sorted((a, c)))
            dataset["edges"] = sorted(
                [list(edge) for edge in edge_set if edge != original] + [list(forged)]
            )
            rows = {row["id"]: row for row in dataset["provinces"]}
            rows[a]["neighbors"] = sorted(
                [pid for pid in rows[a]["neighbors"] if pid != b] + [c]
            )
            rows[b]["neighbors"] = [pid for pid in rows[b]["neighbors"] if pid != a]
            rows[c]["neighbors"] = sorted(rows[c]["neighbors"] + [a])
            dataset_path.write_bytes(canonical(dataset))
            audit_path = output / "topology_audit.json"
            audit = json.loads(audit_path.read_text())
            for entry in audit["shared_edges"]:
                if {entry["a"], entry["b"]} == {a, b}:
                    entry["adjacent"] = False
            audit["shared_edges"].append(
                {
                    "a": forged[0],
                    "b": forged[1],
                    "shared_edge_pixels": 1,
                    "minimum": 1,
                    "adjacent": True,
                }
            )
            audit["shared_edges"].sort(key=lambda row: (row["a"], row["b"]))
            audit_path.write_bytes(canonical(audit))
            self.reseal_dataset_outputs(output)
            with self.assertRaisesRegex(self.g.Gate2Error, "measured shared boundaries"):
                self.g.inspect_output(output, gate1, terrain, config)

    def test_inspection_rejects_border_ledger_forgery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate1, terrain, config, output = self.convert_real(root)
            dataset_path = output / "polygon_dataset.json"
            dataset = json.loads(dataset_path.read_text())
            record = next(row for row in dataset["border_classes"] if row["class"] == "internal_land")
            record["class"] = "authored_boundary"
            dataset["border_classes"].sort(
                key=lambda row: (
                    row["class"],
                    row["segment"],
                    row["left_id"] or "",
                    row["right_id"] or "",
                )
            )
            dataset_path.write_bytes(canonical(dataset))
            audit_path = output / "topology_audit.json"
            audit = json.loads(audit_path.read_text())
            audit["border_class_counts"]["internal_land"] -= 1
            audit["border_class_counts"]["authored_boundary"] = 1
            audit_path.write_bytes(canonical(audit))
            self.reseal_dataset_outputs(output)
            with self.assertRaisesRegex(self.g.Gate2Error, "border class ledger"):
                self.g.inspect_output(output, gate1, terrain, config)

    def test_province_raster_decode_uses_captured_bytes(self) -> None:
        gate1, _terrain, _config = self.real_fixture()
        baseline = self.g._load_gate1(gate1)
        province_path = gate1 / "provinces.png"
        original_bytes = province_path.read_bytes()
        with self.Image.open(io.BytesIO(original_bytes)) as image:
            replacement = self.np.flip(
                self.np.asarray(image.convert("RGB"), dtype=self.np.uint8), axis=1
            ).copy()
        replacement_bytes = self.png_bytes(replacement)
        original_open = self.g.Image.open
        triggered = False

        def racing_open(source, *args, **kwargs):
            nonlocal triggered
            if isinstance(source, io.BytesIO) and not triggered:
                triggered = True
                province_path.write_bytes(replacement_bytes)
            return original_open(source, *args, **kwargs)

        try:
            with mock.patch.object(self.g.Image, "open", side_effect=racing_open):
                snapshot = self.g._load_gate1(gate1)
        finally:
            province_path.write_bytes(original_bytes)
        self.assertTrue(triggered)
        self.assertEqual(
            snapshot.output_sha256["provinces.png"],
            hashlib.sha256(original_bytes).hexdigest(),
        )
        self.np.testing.assert_array_equal(snapshot.labels, baseline.labels)

    def test_terrain_raster_decode_uses_captured_bytes(self) -> None:
        gate1, terrain_path, _config = self.real_fixture()
        manifest = json.loads((gate1 / "run_manifest.json").read_text())
        baseline = self.g._load_terrain(
            terrain_path,
            manifest,
            (manifest["dimensions"]["height"], manifest["dimensions"]["width"]),
        )
        original_bytes = terrain_path.read_bytes()
        replacement = self.np.flip(baseline.array, axis=0).copy()
        replacement_bytes = self.png_bytes(replacement)
        original_open = self.g.Image.open
        triggered = False

        def racing_open(source, *args, **kwargs):
            nonlocal triggered
            if isinstance(source, io.BytesIO) and not triggered:
                triggered = True
                terrain_path.write_bytes(replacement_bytes)
            return original_open(source, *args, **kwargs)

        try:
            with mock.patch.object(self.g.Image, "open", side_effect=racing_open):
                snapshot = self.g._load_terrain(
                    terrain_path,
                    manifest,
                    baseline.array.shape[:2],
                )
        finally:
            terrain_path.write_bytes(original_bytes)
        self.assertTrue(triggered)
        self.assertEqual(snapshot.sha256, hashlib.sha256(original_bytes).hexdigest())
        self.np.testing.assert_array_equal(snapshot.array, baseline.array)

    def test_inspection_rejects_coherently_resealed_terrain_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate1, terrain, config, output = self.convert_real(root)
            dataset_path = output / "polygon_dataset.json"
            dataset = json.loads(dataset_path.read_text())
            row = next(row for row in dataset["provinces"] if not row["is_water"])
            total = sum(row["terrain_coverage_pixels"].values())
            forged = next(name for name in self.g.LAND_TERRAINS if name != row["terrain_id"])
            row["terrain_coverage"] = {forged: 1.0}
            row["terrain_coverage_pixels"] = {forged: total}
            row["terrain_id"] = forged
            dataset_path.write_bytes(canonical(dataset))
            self.reseal_dataset_outputs(output)
            with self.assertRaisesRegex(self.g.Gate2Error, "terrain .*authenticated raster"):
                self.g.inspect_output(output, gate1, terrain, config)

    def test_inspection_rejects_resealed_geometry_not_matching_raster(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate1, terrain, config, output = self.convert_real(root)
            dataset_path = output / "polygon_dataset.json"
            dataset = json.loads(dataset_path.read_text())
            row = next(row for row in dataset["provinces"] if not row["is_water"])

            def shift_flat(values):
                return [
                    value + (0.5 if index % 2 == 0 else 0.25)
                    for index, value in enumerate(values)
                ]

            row["ring"] = shift_flat(row["ring"])
            row["vertices"] = shift_flat(row["vertices"])
            for component in row["components"]:
                component["outer"] = shift_flat(component["outer"])
                component["holes"] = [shift_flat(hole) for hole in component["holes"]]
            row["centroid"] = [row["centroid"][0] + 0.5, row["centroid"][1] + 0.25]
            row["label"] = list(row["centroid"])
            dataset_path.write_bytes(canonical(dataset))
            self.reseal_dataset_outputs(output)
            with self.assertRaisesRegex(self.g.Gate2Error, "components do not match .*label raster"):
                self.g.inspect_output(output, gate1, terrain, config)

    def test_output_inspection_hashes_and_parses_one_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate1, terrain, config, output = self.convert_real(root)
            dataset_path = output / "polygon_dataset.json"
            original = dataset_path.read_bytes()
            malicious = json.loads(original.decode("utf-8"))
            malicious["schema"] = "forged-after-capture"
            malicious_bytes = canonical(malicious)
            original_loader = self.g._load_canonical_json_bytes
            triggered = False

            def racing_loader(raw, label, source):
                nonlocal triggered
                if label == "adapter manifest" and not triggered:
                    triggered = True
                    dataset_path.write_bytes(malicious_bytes)
                return original_loader(raw, label, source)

            try:
                with mock.patch.object(
                    self.g, "_load_canonical_json_bytes", side_effect=racing_loader
                ):
                    inspected = self.g.inspect_output(output, gate1, terrain, config)
            finally:
                dataset_path.write_bytes(original)
            self.assertTrue(triggered)
            self.assertEqual(inspected["schema"], self.g.ADAPTER_MANIFEST_SCHEMA)

    def test_conversion_publishes_the_inspected_snapshot_after_path_replacement(self) -> None:
        gate1, terrain, config = self.real_fixture()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "published"
            original_inspect = self.g.inspect_output
            triggered = False

            def racing_inspect(candidate, *args, **kwargs):
                nonlocal triggered
                result = original_inspect(candidate, *args, **kwargs)
                triggered = True
                (candidate / "polygon_dataset.json").write_bytes(b"replaced-before-publish")
                return result

            with mock.patch.object(self.g, "inspect_output", side_effect=racing_inspect):
                self.g.convert(gate1, terrain, config, output)
            self.assertTrue(triggered)
            self.assertNotEqual(
                (output / "polygon_dataset.json").read_bytes(),
                b"replaced-before-publish",
            )
            self.g.inspect_output(output, gate1, terrain, config)

    def test_gate1_strict_inspector_rejects_resealed_semantic_forgery(self) -> None:
        gate1, terrain, config = self.real_fixture()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            valid_output = root / "valid-gate2"
            self.g.convert(gate1, terrain, config, valid_output)
            forged = root / "forged-gate1"
            shutil.copytree(gate1, forged)
            territories_path = forged / "territories.json"
            territories_path.write_bytes(canonical([]))
            manifest_path = forged / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["outputs"]["territories.json"] = hashlib.sha256(
                territories_path.read_bytes()
            ).hexdigest()
            payload = dict(manifest)
            payload.pop("manifest_payload_sha256")
            manifest["manifest_payload_sha256"] = hashlib.sha256(
                canonical(payload)
            ).hexdigest()
            manifest_path.write_bytes(canonical(manifest))
            with self.assertRaisesRegex(self.g.Gate2Error, "Gate 1 strict inspection failed"):
                self.g.convert(forged, terrain, config, root / "must-not-publish")
            with self.assertRaisesRegex(self.g.Gate2Error, "Gate 1 strict inspection failed"):
                self.g.inspect_output(valid_output, forged, terrain, config)

    def test_gate1_capture_rejects_extra_directory_and_symlink(self) -> None:
        gate1, _terrain, _config = self.real_fixture()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            extra = root / "extra"
            shutil.copytree(gate1, extra)
            (extra / "unexpected").mkdir()
            with self.assertRaisesRegex(self.g.Gate2Error, "extra=.*unexpected"):
                self.g._load_gate1(extra)

            linked = root / "linked"
            shutil.copytree(gate1, linked)
            target = linked / "provinces.json"
            backup = root / "provinces.backup"
            target.rename(backup)
            try:
                target.symlink_to(backup)
            except OSError:
                self.skipTest("symlink creation is unavailable on this runner")
            with self.assertRaisesRegex(self.g.Gate2Error, "regular files"):
                self.g._load_gate1(linked)

    def test_real_gate1_fixture_two_runs_byte_identical(self) -> None:
        gate1, terrain, config = self.real_fixture()
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
