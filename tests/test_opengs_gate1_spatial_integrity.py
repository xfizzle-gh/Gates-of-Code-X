from __future__ import annotations

import importlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_opengs_gate1_determinism import (
    FIXTURE,
    load_generator,
    reseal_manifest,
    write_json,
)

OPTIONAL_MODULES = ("numpy", "PIL", "scipy")


@unittest.skipUnless(
    all(importlib.util.find_spec(name) for name in OPTIONAL_MODULES),
    "optional OpenGS dependencies are not installed",
)
class Gate1SpatialIntegrityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.g = load_generator()
        import gate1_pipeline
        cls.pipeline = gate1_pipeline

    def make_fixture(self, root: Path) -> Path:
        subprocess.run([sys.executable, str(FIXTURE), "--output", str(root)], check=True)
        return root / "recipe.json"

    def test_component_ledger_rejects_extra_deterministically_valid_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            output = base / "output"
            self.g.generate(recipe, output)
            manifest_path = output / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            sample_names = [
                name for name in manifest["derived_seeds"]
                if ".lloyd.sample.component_" in name
            ]
            prefixes: dict[str, list[int]] = {}
            for name in sample_names:
                prefix, component_text = name.rsplit(".component_", 1)
                prefix = prefix.removesuffix(".lloyd.sample")
                prefixes.setdefault(prefix, []).append(int(component_text))
            prefix = next(
                candidate for candidate, components in sorted(prefixes.items())
                if components == [1]
            )
            sample_name = f"{prefix}.lloyd.sample.component_0002"
            replacement_name = f"{prefix}.lloyd.empty_replacement.component_0002"
            authority = self.g.SeedLedger(
                manifest["recipe"]["root_seed"], manifest["recipe"]["recipe_id"]
            )
            manifest["derived_seeds"][sample_name] = authority.seed(sample_name)
            manifest["derived_seeds"][replacement_name] = authority.seed(replacement_name)
            manifest.pop("manifest_payload_sha256", None)
            import hashlib
            manifest["manifest_payload_sha256"] = hashlib.sha256(
                self.g.canonical_json_bytes(manifest)
            ).hexdigest()
            write_json(manifest_path, manifest)

            with self.assertRaises(self.g.Gate1Error):
                self.g.inspect_output(output)

    def test_png_and_record_geometry_are_spatially_authenticated(self) -> None:
        np = importlib.import_module("numpy")
        Image = importlib.import_module("PIL.Image")

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = self.make_fixture(base / "inputs")
            baseline = base / "baseline"
            self.g.generate(recipe, baseline)

            swapped = base / "swapped-regions"
            shutil.copytree(baseline, swapped)
            territories = json.loads((swapped / "territories.json").read_text(encoding="utf-8"))
            first = territories[0]
            second = next(
                item for item in territories[1:]
                if item["territory_type"] == first["territory_type"]
            )
            color_a = np.asarray([first["R"], first["G"], first["B"]], dtype=np.uint8)
            color_b = np.asarray([second["R"], second["G"], second["B"]], dtype=np.uint8)
            with Image.open(swapped / "territories.png") as image:
                pixels = np.asarray(image.convert("RGB"), dtype=np.uint8).copy()
            mask_a = np.all(pixels == color_a, axis=2)
            mask_b = np.all(pixels == color_b, axis=2)
            pixels[mask_a] = color_b
            pixels[mask_b] = color_a
            self.pipeline.write_deterministic_rgb_png(swapped / "territories.png", pixels)
            reseal_manifest(self.g, swapped, "territories.png")
            with self.subTest(case="two-color-pixel-swap"), self.assertRaises(self.g.Gate1Error):
                self.g.inspect_output(swapped)

            moved_center = base / "moved-center"
            shutil.copytree(baseline, moved_center)
            provinces = json.loads((moved_center / "provinces.json").read_text(encoding="utf-8"))
            manifest = json.loads((moved_center / "run_manifest.json").read_text(encoding="utf-8"))
            width = manifest["dimensions"]["width"]
            provinces[0]["x"] = float((float(provinces[0]["x"]) + 1.0) % width)
            write_json(moved_center / "provinces.json", provinces)
            reseal_manifest(self.g, moved_center, "provinces.json")
            with self.subTest(case="in-bounds-center-mutation"), self.assertRaises(self.g.Gate1Error):
                self.g.inspect_output(moved_center)

            reassigned = base / "reassigned-parent"
            shutil.copytree(baseline, reassigned)
            territories = json.loads((reassigned / "territories.json").read_text(encoding="utf-8"))
            provinces = json.loads((reassigned / "provinces.json").read_text(encoding="utf-8"))
            pair = None
            for left_index, left in enumerate(provinces):
                if left["province_type"] == "lake":
                    continue
                for right_index, right in enumerate(provinces[left_index + 1:], start=left_index + 1):
                    if (
                        right["province_type"] == left["province_type"]
                        and right["territory_id"] != left["territory_id"]
                    ):
                        pair = (left_index, right_index)
                        break
                if pair is not None:
                    break
            self.assertIsNotNone(pair)
            left_index, right_index = pair
            provinces[left_index]["territory_id"], provinces[right_index]["territory_id"] = (
                provinces[right_index]["territory_id"],
                provinces[left_index]["territory_id"],
            )
            territory_by_id = {item["territory_id"]: item for item in territories}
            for territory in territories:
                territory["province_ids"] = []
            for province in provinces:
                territory_by_id[province["territory_id"]]["province_ids"].append(
                    province["province_id"]
                )
            write_json(reassigned / "territories.json", territories)
            write_json(reassigned / "provinces.json", provinces)
            reseal_manifest(self.g, reassigned, "territories.json")
            reseal_manifest(self.g, reassigned, "provinces.json")
            with self.subTest(case="coherent-parent-child-reassignment"), self.assertRaises(self.g.Gate1Error):
                self.g.inspect_output(reassigned)


if __name__ == "__main__":
    unittest.main()
