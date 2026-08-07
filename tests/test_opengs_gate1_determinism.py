from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "tools" / "opengs_eval" / "gate1_generator.py"
FIXTURE = ROOT / "tools" / "opengs_eval" / "make_gate1_fixture.py"
OPTIONAL_MODULES = ("numpy", "PIL", "scipy")


def load_generator():
    if str(GEN.parent) not in sys.path:
        sys.path.insert(0, str(GEN.parent))
    spec = importlib.util.spec_from_file_location("gate1_generator", GEN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Gate1DeterminismTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        missing = [name for name in OPTIONAL_MODULES if importlib.util.find_spec(name) is None]
        if missing:
            raise unittest.SkipTest(
                "optional OpenGS evaluation dependencies are not installed: "
                + ", ".join(missing)
            )
        cls.g = load_generator()

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

    def test_two_clean_output_directories_are_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            left = base / "left"
            right = base / "right"
            self.g.generate(recipe, left)
            self.g.generate(recipe, right)
            comparison = self.g.compare_runs(left, right)
            self.assertTrue(comparison["identical"], comparison)
            for name in self.g.AUTHORITATIVE_OUTPUTS:
                self.assertEqual((left / name).read_bytes(), (right / name).read_bytes(), name)

    def test_root_seed_changes_authoritative_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            left = base / "left"
            right = base / "right"
            self.g.generate(recipe, left)
            payload = json.loads(recipe.read_text())
            payload["root_seed"] += 1
            recipe.write_bytes((json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
            self.g.generate(recipe, right)
            comparison = self.g.compare_runs(left, right)
            self.assertFalse(comparison["identical"])

    def test_recipe_checksum_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            payload = json.loads(recipe.read_text())
            payload["inputs"]["density"]["sha256"] = "0" * 64
            recipe.write_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            with self.assertRaises(self.g.Gate1Error):
                self.g.load_recipe(recipe)

    def test_no_implicit_rng_or_gui_dependency(self) -> None:
        source = GEN.read_text(encoding="utf-8")
        self.assertNotIn("default_rng()", source)
        self.assertNotIn("default_rng(None)", source)
        self.assertNotIn("PyQt", source)
        self.assertNotIn("QApplication", source)
        self.assertNotIn("RenderingDevice", source)
        self.assertNotIn("JFA", source)

    def test_cli_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            left = base / "left"
            right = base / "right"
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
