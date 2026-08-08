from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "tools" / "opengs_eval"
GEN = MODULE_DIR / "gate1_generator.py"
FIXTURE = MODULE_DIR / "make_gate1_fixture.py"
GATE1_MODULES = tuple(MODULE_DIR / name for name in (
    "gate1_generator.py", "gate1_common.py", "gate1_regions.py",
    "gate1_pipeline.py", "make_gate1_fixture.py",
))
OPTIONAL_MODULES = ("numpy", "PIL", "scipy")


def load_generator():
    if str(MODULE_DIR) not in sys.path:
        sys.path.insert(0, str(MODULE_DIR))
    spec = importlib.util.spec_from_file_location("gate1_generator", GEN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: object, *, pretty: bool = False, crlf: bool = False) -> None:
    if pretty:
        text = json.dumps(value, sort_keys=True, indent=2) + "\n"
    else:
        text = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    if crlf:
        text = text.replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


def reseal_manifest(generator, output: Path, changed_output: str | None = None) -> None:
    path = output / "run_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if changed_output is not None:
        payload["outputs"][changed_output] = hashlib.sha256(
            (output / changed_output).read_bytes()
        ).hexdigest()
    payload.pop("manifest_payload_sha256", None)
    payload["manifest_payload_sha256"] = hashlib.sha256(
        generator.canonical_json_bytes(payload)
    ).hexdigest()
    write_json(path, payload)


class Gate1StaticContractTest(unittest.TestCase):
    def test_dependency_closure_has_no_gui_runtime_or_implicit_rng(self) -> None:
        expected_local = {"gate1_common", "gate1_regions", "gate1_pipeline"}
        discovered_local: set[str] = set()
        banned_import_roots = {"PyQt5", "PyQt6", "PySide2", "PySide6", "godot", "tkinter"}
        banned_names = {"QApplication", "RenderingDevice"}
        for path in GATE1_MODULES:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        self.assertNotIn(root, banned_import_roots, f"{path}: banned import {alias.name}")
                        if alias.name.startswith("gate1_"):
                            discovered_local.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    root = module.split(".")[0]
                    self.assertNotIn(root, banned_import_roots, f"{path}: banned import {module}")
                    if module.startswith("gate1_"):
                        discovered_local.add(root)
                elif isinstance(node, ast.Name):
                    self.assertNotIn(node.id, banned_names, f"{path}: banned runtime name {node.id}")
                elif isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, banned_names, f"{path}: banned runtime attribute {node.attr}")
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "default_rng":
                    self.assertTrue(node.args or node.keywords, f"{path}: default_rng requires an explicit seed")
                    if node.args:
                        self.assertFalse(isinstance(node.args[0], ast.Constant) and node.args[0].value is None)
        self.assertEqual(discovered_local, expected_local)

    def test_committed_schemas_are_strict(self) -> None:
        for name in ("gate1_recipe.schema.json", "gate1_run_manifest.schema.json"):
            schema = json.loads((MODULE_DIR / name).read_text(encoding="utf-8"))
            self.assertFalse(schema["additionalProperties"])


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in OPTIONAL_MODULES), "optional OpenGS dependencies are not installed")
class Gate1DeterminismTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.g = load_generator()
        import gate1_pipeline
        import gate1_regions
        cls.pipeline = gate1_pipeline
        cls.regions = gate1_regions

    def make_fixture(self, root: Path) -> Path:
        subprocess.run([sys.executable, str(FIXTURE), "--output", str(root)], check=True)
        return root / "recipe.json"

    def test_named_seed_ledger_is_stable_and_order_independent(self) -> None:
        a = self.g.SeedLedger(42, "fixture")
        values_a = [a.seed(name) for name in ("b", "a", "c")]
        b = self.g.SeedLedger(42, "fixture")
        values_b = [b.seed(name) for name in ("a", "b", "c")]
        self.assertEqual(values_a[0], values_b[1])
        self.assertEqual(values_a[1], values_b[0])
        self.assertEqual(a.manifest(), b.manifest())
        self.assertEqual(len(set(a.manifest().values())), 3)

    def test_lloyd_sampling_and_empty_replacement_have_independent_streams(self) -> None:
        replacement_seed = 12345
        expected = self.regions.empty_replacement_indices(replacement_seed, count=8, upper=100)
        for consumed in (0, 1, 10_000):
            sampler = __import__("numpy").random.default_rng(999)
            if consumed:
                sampler.random(consumed)
            actual = self.regions.empty_replacement_indices(replacement_seed, count=8, upper=100)
            self.assertTrue((actual == expected).all())
        with tempfile.TemporaryDirectory() as temp:
            recipe = self.make_fixture(Path(temp) / "inputs")
            manifest = self.g.generate(recipe, Path(temp) / "out")
            keys = set(manifest["derived_seeds"])
            self.assertTrue(any(".lloyd.sample.component_" in key for key in keys))
            self.assertTrue(any(".lloyd.empty_replacement.component_" in key for key in keys))

    def test_two_clean_output_directories_are_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            left, right = base / "left", base / "right"
            self.g.generate(recipe, left)
            self.g.generate(recipe, right)
            comparison = self.g.compare_runs(left, right)
            self.assertTrue(comparison["identical"], comparison)
            for name in self.g.AUTHORITATIVE_OUTPUTS:
                self.assertEqual((left / name).read_bytes(), (right / name).read_bytes(), name)

    def test_semantically_identical_recipe_formatting_has_identical_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            canonical = self.make_fixture(base / "inputs")
            payload = json.loads(canonical.read_text(encoding="utf-8"))
            pretty = canonical.parent / "pretty.json"
            crlf = canonical.parent / "crlf.json"
            write_json(pretty, payload, pretty=True)
            write_json(crlf, payload, pretty=False, crlf=True)
            outputs = []
            for index, recipe in enumerate((canonical, pretty, crlf)):
                out = base / f"out-{index}"
                self.g.generate(recipe, out)
                outputs.append(out)
            for other in outputs[1:]:
                self.assertTrue(self.g.compare_runs(outputs[0], other)["identical"])

    def test_root_seed_changes_authoritative_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            left, right = base / "left", base / "right"
            self.g.generate(recipe, left)
            payload = json.loads(recipe.read_text())
            payload["root_seed"] += 1
            write_json(recipe, payload)
            self.g.generate(recipe, right)
            self.assertFalse(self.g.compare_runs(left, right)["identical"])

    def test_recipe_schema_equivalent_validation_rejects_invalid_values(self) -> None:
        cases = []
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            original = json.loads(recipe.read_text())
            mutations = {
                "bool_schema_version": lambda p: p.__setitem__("schema_version", True),
                "extra_top": lambda p: p.__setitem__("extra", 1),
                "missing_nullable_terrain": lambda p: p["inputs"].pop("terrain"),
                "bool_density": lambda p: p["options"].__setitem__("density_strength", True),
                "counts_not_object": lambda p: p.__setitem__("counts", []),
                "options_not_object": lambda p: p.__setitem__("options", []),
                "extra_nested": lambda p: p["counts"].__setitem__("extra", 1),
            }
            for name, mutate in mutations.items():
                payload = json.loads(json.dumps(original))
                mutate(payload)
                path = recipe.parent / f"{name}.json"
                write_json(path, payload)
                with self.subTest(name=name), self.assertRaises(self.g.Gate1Error):
                    self.g.load_recipe(path)

    def test_recipe_checksum_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            recipe = self.make_fixture(Path(temp) / "inputs")
            payload = json.loads(recipe.read_text())
            payload["inputs"]["density"]["sha256"] = "0" * 64
            write_json(recipe, payload)
            with self.assertRaises(self.g.Gate1Error):
                self.g.load_recipe(recipe)

    def test_impossible_counts_and_empty_masks_fail_closed(self) -> None:
        import numpy as np
        with self.assertRaises(self.g.Gate1Error):
            self.regions.random_seeds(np.zeros((4, 4), dtype=bool), 1, 1, None, 1.0)
        with self.assertRaises(self.g.Gate1Error):
            self.regions.random_seeds(np.ones((2, 2), dtype=bool), 5, 1, None, 1.0)
        with self.assertRaises(self.g.Gate1Error):
            self.regions.largest_remainder([], 1, [])
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            payload = json.loads(recipe.read_text())
            payload["counts"]["land_territories"] = 999999
            write_json(recipe, payload)
            with self.assertRaises(self.g.Gate1Error):
                self.g.generate(recipe, base / "out")
            self.assertFalse((base / "out").exists())

    def test_generation_is_transactional_and_existing_output_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            existing = base / "existing"
            existing.mkdir()
            sentinel = existing / "run_manifest.json"
            sentinel.write_text("old", encoding="utf-8")
            with self.assertRaises(self.g.Gate1Error):
                self.g.generate(recipe, existing)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "old")

            target = base / "failed"
            original = self.pipeline.write_deterministic_rgb_png
            calls = 0
            def fail_after_first(path, pixels):
                nonlocal calls
                calls += 1
                original(path, pixels)
                if calls == 1:
                    raise RuntimeError("injected failure")
            with mock.patch.object(self.pipeline, "write_deterministic_rgb_png", side_effect=fail_after_first):
                with self.assertRaises(self.g.Gate1Error):
                    self.g.generate(recipe, target)
            self.assertFalse(target.exists())
            self.assertFalse(any(base.glob(".failed.gate1-*")))

    def test_inspect_output_enforces_complete_manifest_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            out = base / "out"
            self.g.generate(recipe, out)
            manifest_path = out / "run_manifest.json"
            for name, mutate in {
                "missing_environment": lambda p: p.pop("environment"),
                "extra_property": lambda p: p.__setitem__("extra", 1),
                "wrong_counts_type": lambda p: p.__setitem__("counts", []),
                "wrong_upstream": lambda p: p.__setitem__("upstream_repository", "other/repo"),
                "missing_replacement_seed": lambda p: p["derived_seeds"].pop(next(k for k in p["derived_seeds"] if ".lloyd.empty_replacement.component_" in k)),
            }.items():
                payload = json.loads(manifest_path.read_text())
                mutate(payload)
                payload.pop("manifest_payload_sha256", None)
                payload["manifest_payload_sha256"] = hashlib.sha256(self.g.canonical_json_bytes(payload)).hexdigest()
                write_json(manifest_path, payload)
                with self.subTest(name=name), self.assertRaises(self.g.Gate1Error):
                    self.g.inspect_output(out)
                self.g.generate(recipe, base / f"restore-{name}")
                shutil.copy2(base / f"restore-{name}" / "run_manifest.json", manifest_path)

    def test_inspect_rejects_noncanonical_manifest_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            out = base / "out"
            self.g.generate(recipe, out)
            path = out / "run_manifest.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(self.g.Gate1Error):
                self.g.inspect_output(out)

    def test_input_bytes_are_immutable_and_path_mutation_blocks_publish(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            target = base / "out"
            original_load = self.pipeline.load_images

            def mutate_after_verified_read(inputs):
                decoded = original_load(inputs)
                inputs["land"].path.write_bytes(b"replacement after checksum verification")
                return decoded

            with mock.patch.object(self.pipeline, "load_images", side_effect=mutate_after_verified_read):
                with self.assertRaises(self.g.Gate1Error):
                    self.g.generate(recipe, target)
            self.assertFalse(target.exists())
            self.assertFalse(any(base.glob(".out.gate1-*")))

            payload = json.loads(recipe.read_text(encoding="utf-8"))
            payload["inputs"]["land"]["path"] = "missing.ppm"
            write_json(recipe, payload)
            with self.assertRaises(self.g.Gate1Error):
                self.g.load_recipe(recipe)

    def test_inspect_authenticates_seed_and_environment_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            baseline = base / "baseline"
            self.g.generate(recipe, baseline)
            baseline_manifest = json.loads((baseline / "run_manifest.json").read_text(encoding="utf-8"))
            seed_name = next(iter(baseline_manifest["derived_seeds"]))
            sample_name = next(name for name in baseline_manifest["derived_seeds"] if name.endswith(".sample"))
            jagged_name = next(name for name in baseline_manifest["derived_seeds"] if name.endswith(".jagged"))
            mutations = {
                "seed_value": lambda p: p["derived_seeds"].__setitem__(seed_name, (p["derived_seeds"][seed_name] + 1) % (2**64)),
                "missing_initial": lambda p: p["derived_seeds"].pop(sample_name),
                "missing_jagged": lambda p: p["derived_seeds"].pop(jagged_name),
                "python": lambda p: p["environment"].__setitem__("python", "3.11.8"),
                "numpy": lambda p: p["environment"].__setitem__("numpy", "2.3.4"),
                "pillow": lambda p: p["environment"].__setitem__("pillow", "11.3.0"),
                "scipy": lambda p: p["environment"].__setitem__("scipy", "1.16.2"),
            }
            for name, mutate in mutations.items():
                case = base / name
                shutil.copytree(baseline, case)
                manifest_path = case / "run_manifest.json"
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                mutate(payload)
                payload.pop("manifest_payload_sha256", None)
                payload["manifest_payload_sha256"] = hashlib.sha256(
                    self.g.canonical_json_bytes(payload)
                ).hexdigest()
                write_json(manifest_path, payload)
                with self.subTest(name=name), self.assertRaises(self.g.Gate1Error):
                    self.g.inspect_output(case)

    def test_inspect_semantically_validates_authoritative_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            baseline = base / "baseline"
            self.g.generate(recipe, baseline)

            empty_provinces = base / "empty-provinces"
            shutil.copytree(baseline, empty_provinces)
            write_json(empty_provinces / "provinces.json", [])
            reseal_manifest(self.g, empty_provinces, "provinces.json")
            with self.assertRaises(self.g.Gate1Error):
                self.g.inspect_output(empty_provinces)

            bad_parent = base / "bad-parent"
            shutil.copytree(baseline, bad_parent)
            records = json.loads((bad_parent / "provinces.json").read_text(encoding="utf-8"))
            records[0]["territory_id"] = "TRT999999"
            write_json(bad_parent / "provinces.json", records)
            reseal_manifest(self.g, bad_parent, "provinces.json")
            with self.assertRaises(self.g.Gate1Error):
                self.g.inspect_output(bad_parent)

            bad_png = base / "bad-png"
            shutil.copytree(baseline, bad_png)
            (bad_png / "provinces.png").write_bytes(b"not a png")
            reseal_manifest(self.g, bad_png, "provinces.png")
            with self.assertRaises(self.g.Gate1Error):
                self.g.inspect_output(bad_png)

            extra_dir = base / "extra-dir"
            shutil.copytree(baseline, extra_dir)
            (extra_dir / "unexpected").mkdir()
            with self.assertRaises(self.g.Gate1Error):
                self.g.inspect_output(extra_dir)

    def test_cli_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            left, right = base / "left", base / "right"
            for command in (
                ["validate-recipe", str(recipe)],
                ["generate", str(recipe), "--output", str(left)],
                ["generate", str(recipe), "--output", str(right)],
                ["inspect-output", str(left)],
                ["compare-runs", str(left), str(right)],
            ):
                result = subprocess.run([sys.executable, str(GEN), *command], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
