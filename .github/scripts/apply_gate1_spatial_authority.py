from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "tools/opengs_eval/gate1_pipeline.py"
DOC = ROOT / "docs/research/opengs-evaluation/gate_1_implementation.md"
WORKFLOW = ROOT / ".github/workflows/opengs-gate1-determinism.yml"
PROVENANCE = ROOT / "tools/opengs_eval/gate1_upstream_modules.json"
NEW_TEST = ROOT / "tests/test_opengs_gate1_spatial_integrity.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_block(text: str, start: str, end: str, replacement: str, label: str) -> str:
    begin = text.find(start)
    if begin < 0:
        raise RuntimeError(f"{label}: start marker not found")
    finish = text.find(end, begin)
    if finish < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return text[:begin] + replacement + text[finish:]


pipeline = PIPELINE.read_text(encoding="utf-8")
pipeline = replace_once(
    pipeline,
    '        masks["land_fill"], masks["land_border"], counts["land_territories"], 0,\n',
    '        masks["land_mask"], np.zeros_like(masks["land_mask"], dtype=bool), counts["land_territories"], 0,\n',
    "land territory reconstructable mask",
)
pipeline = replace_once(
    pipeline,
    '        masks["sea_fill"], masks["sea_border"], counts["ocean_territories"], next_index,\n',
    '        masks["sea_mask"], np.zeros_like(masks["sea_mask"], dtype=bool), counts["ocean_territories"], next_index,\n',
    "ocean territory reconstructable mask",
)
pipeline = replace_once(
    pipeline,
    '    boundary_mask = masks["boundary_mask"]\n    lake_mask = masks["lake_mask"]\n',
    '    lake_mask = masks["lake_mask"]\n',
    "remove hidden boundary authority",
)
pipeline = replace_once(
    pipeline,
    '        fill = territory_mask & ~lake_mask & ~boundary_mask\n        border = (territory_mask & boundary_mask) | (territory_mask & lake_mask)\n',
    '        fill = territory_mask & ~lake_mask\n        border = np.zeros_like(territory_mask, dtype=bool)\n',
    "province reconstructable mask",
)

ledger_block = '''def _pixel_mask(pixels: np.ndarray, color: tuple[int, int, int]) -> np.ndarray:
    return np.all(pixels == np.asarray(color, dtype=np.uint8), axis=2)


def _mask_centroid(mask: np.ndarray, label: str) -> tuple[float, float]:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        raise Gate1Error(f"{label} has no pixels")
    count = len(xs)
    return (
        float(int(xs.sum(dtype=np.int64)) / count),
        float(int(ys.sum(dtype=np.int64)) / count),
    )


def _connected_component_count(mask: np.ndarray, label: str) -> int:
    _labels, count = ndlabel(mask)
    count = int(count)
    if count <= 0:
        raise Gate1Error(f"{label} has no connected components")
    return count


def _validate_seed_ledger(
    manifest: dict[str, Any],
    territories: list[dict[str, Any]],
    provinces: list[dict[str, Any]],
    territory_masks: dict[str, np.ndarray],
    province_masks: dict[str, np.ndarray],
) -> None:
    seeds = manifest["derived_seeds"]
    requested = manifest["counts"]["requested"]
    expected_components: dict[str, int] = {}

    for territory_type, requested_key in (
        ("land", "land_territories"),
        ("ocean", "ocean_territories"),
    ):
        if not requested[requested_key]:
            continue
        masks = [
            territory_masks[item["territory_id"]]
            for item in territories
            if item["territory_type"] == territory_type
        ]
        if not masks:
            raise Gate1Error(f"no {territory_type} territory pixels exist for seed authority")
        combined = np.logical_or.reduce(masks)
        expected_components[f"territory.{territory_type}"] = _connected_component_count(
            combined, f"territory.{territory_type} seed mask"
        )

    province_by_id = {item["province_id"]: item for item in provinces}
    for index, territory in enumerate(territories):
        child_masks = [
            province_masks[province_id]
            for province_id in territory["province_ids"]
            if province_by_id[province_id]["province_type"] != "lake"
        ]
        if not child_masks:
            raise Gate1Error(
                f"territory {territory['territory_id']} has no non-lake province pixels for seed authority"
            )
        combined = np.logical_or.reduce(child_masks)
        prefix = f"province.{territory['territory_type']}.{index:06d}"
        expected_components[prefix] = _connected_component_count(
            combined, f"{prefix} seed mask"
        )

    expected_names: set[str] = set()
    for prefix, component_count in sorted(expected_components.items()):
        expected_names.add(f"{prefix}.sample")
        expected_names.add(f"{prefix}.jagged")
        expected_names.update(
            f"{prefix}.lloyd.sample.component_{component:04d}"
            for component in range(1, component_count + 1)
        )
        expected_names.update(
            f"{prefix}.lloyd.empty_replacement.component_{component:04d}"
            for component in range(1, component_count + 1)
        )

    actual_names = set(seeds)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise Gate1Error(f"derived seed ledger mismatch: missing={missing}, extra={extra}")


'''
pipeline = replace_block(
    pipeline,
    "def _validate_seed_ledger(",
    "def _validate_artifact_semantics(",
    ledger_block,
    "seed ledger authority",
)

artifact_function = '''def _validate_artifact_semantics(output_dir: Path, manifest: dict[str, Any]) -> None:
    width = manifest["dimensions"]["width"]
    height = manifest["dimensions"]["height"]
    territories = _read_canonical_json(output_dir / "territories.json", "territories.json")
    provinces = _read_canonical_json(output_dir / "provinces.json", "provinces.json")
    if not isinstance(territories, list) or not isinstance(provinces, list):
        raise Gate1Error("territories.json and provinces.json must contain arrays")

    territory_keys = {"territory_id", "territory_type", "R", "G", "B", "x", "y", "province_ids"}
    province_keys = {"province_id", "province_type", "R", "G", "B", "x", "y", "territory_id", "province_terrain"}
    territory_ids: set[str] = set()
    province_ids: set[str] = set()
    territory_colors: set[tuple[int, int, int]] = set()
    province_colors: set[tuple[int, int, int]] = set()
    territory_by_id: dict[str, dict[str, Any]] = {}
    province_by_id: dict[str, dict[str, Any]] = {}
    expected_color_authority: set[tuple[int, int, int]] = set()

    for index, item in enumerate(territories, start=1):
        path = f"territories[{index - 1}]"
        if not isinstance(item, dict) or set(item) != territory_keys:
            raise Gate1Error(f"{path} has an invalid record shape")
        expected_id = f"TRT{index:06d}"
        if item["territory_id"] != expected_id:
            raise Gate1Error(f"{path}.territory_id must be {expected_id}")
        territory_type = item["territory_type"]
        if territory_type not in {"land", "ocean"}:
            raise Gate1Error(f"{path}.territory_type is invalid")
        color = tuple(_record_int(item[key], f"{path}.{key}") for key in ("R", "G", "B"))
        expected_color = stable_color(index - 1, territory_type, expected_color_authority)
        if color != expected_color:
            raise Gate1Error(
                f"{path} color does not match stable index authority: expected {expected_color}, got {color}"
            )
        if color in territory_colors or color in {OCEAN_COLOR, LAKE_COLOR, BOUNDARY_COLOR}:
            raise Gate1Error(f"{path} has a duplicate or reserved color {color}")
        x = _record_number(item["x"], f"{path}.x")
        y = _record_number(item["y"], f"{path}.y")
        if not (0 <= x < width and 0 <= y < height):
            raise Gate1Error(f"{path} center is outside declared dimensions")
        if not isinstance(item["province_ids"], list) or not all(
            isinstance(value, str) for value in item["province_ids"]
        ):
            raise Gate1Error(f"{path}.province_ids must be an array of strings")
        if len(item["province_ids"]) != len(set(item["province_ids"])):
            raise Gate1Error(f"{path}.province_ids contains duplicates")
        territory_ids.add(item["territory_id"])
        territory_colors.add(color)
        territory_by_id[item["territory_id"]] = item

    expected_children: dict[str, list[str]] = {territory_id: [] for territory_id in territory_ids}
    terrain_by_type = {
        "land": set(LAND_TERRAINS),
        "ocean": set(NAVAL_TERRAINS),
        "lake": set(LAKE_TERRAINS),
    }
    for index, item in enumerate(provinces, start=1):
        path = f"provinces[{index - 1}]"
        if not isinstance(item, dict) or set(item) != province_keys:
            raise Gate1Error(f"{path} has an invalid record shape")
        expected_id = f"PRV{index:06d}"
        if item["province_id"] != expected_id:
            raise Gate1Error(f"{path}.province_id must be {expected_id}")
        province_type = item["province_type"]
        if province_type not in {"land", "ocean", "lake"}:
            raise Gate1Error(f"{path}.province_type is invalid")
        color = tuple(_record_int(item[key], f"{path}.{key}") for key in ("R", "G", "B"))
        expected_color = stable_color(index - 1, province_type, expected_color_authority)
        if color != expected_color:
            raise Gate1Error(
                f"{path} color does not match stable index authority: expected {expected_color}, got {color}"
            )
        if color in province_colors or color in territory_colors or color in {OCEAN_COLOR, LAKE_COLOR, BOUNDARY_COLOR}:
            raise Gate1Error(f"{path} has a duplicate or reserved color {color}")
        x = _record_number(item["x"], f"{path}.x")
        y = _record_number(item["y"], f"{path}.y")
        if not (0 <= x < width and 0 <= y < height):
            raise Gate1Error(f"{path} center is outside declared dimensions")
        parent_id = item["territory_id"]
        if parent_id not in territory_by_id:
            raise Gate1Error(f"{path}.territory_id references unknown territory {parent_id!r}")
        parent_type = territory_by_id[parent_id]["territory_type"]
        if province_type == "lake":
            if parent_type != "land":
                raise Gate1Error(f"{path} lake province must belong to a land territory")
        elif province_type != parent_type:
            raise Gate1Error(f"{path} type does not match parent territory")
        if item["province_terrain"] not in terrain_by_type[province_type]:
            raise Gate1Error(f"{path}.province_terrain is invalid for {province_type}")
        province_ids.add(item["province_id"])
        province_colors.add(color)
        province_by_id[item["province_id"]] = item
        expected_children[parent_id].append(item["province_id"])

    for territory_id, expected in expected_children.items():
        actual_children = territory_by_id[territory_id]["province_ids"]
        if actual_children != expected:
            raise Gate1Error(
                f"territory {territory_id} province_ids do not match province parent relationships"
            )

    actual = manifest["counts"]["actual"]
    land_territories = sum(item["territory_type"] == "land" for item in territories)
    ocean_territories = sum(item["territory_type"] == "ocean" for item in territories)
    land_provinces = sum(item["province_type"] == "land" for item in provinces)
    ocean_provinces = sum(item["province_type"] == "ocean" for item in provinces)
    lake_provinces = sum(item["province_type"] == "lake" for item in provinces)
    expected_counts = {
        "territories": len(territories),
        "land_territories": land_territories,
        "ocean_territories": ocean_territories,
        "provinces": len(provinces),
        "land_provinces": land_provinces,
        "ocean_provinces": ocean_provinces,
        "lake_provinces": lake_provinces,
    }
    if actual != expected_counts:
        raise Gate1Error(f"artifact records do not match manifest counts: {expected_counts}")

    territory_pixels = _decode_rgb_png(output_dir / "territories.png", "territories.png", width, height)
    province_pixels = _decode_rgb_png(output_dir / "provinces.png", "provinces.png", width, height)
    territory_png_colors = {tuple(int(v) for v in row) for row in np.unique(territory_pixels.reshape(-1, 3), axis=0)}
    province_png_colors = {tuple(int(v) for v in row) for row in np.unique(province_pixels.reshape(-1, 3), axis=0)}
    if territory_png_colors != territory_colors:
        raise Gate1Error(
            f"territories.png colors do not match territories.json: "
            f"missing={sorted(territory_colors - territory_png_colors)}, "
            f"extra={sorted(territory_png_colors - territory_colors)}"
        )
    if province_png_colors != province_colors:
        raise Gate1Error(
            f"provinces.png colors do not match provinces.json: "
            f"missing={sorted(province_colors - province_png_colors)}, "
            f"extra={sorted(province_png_colors - province_colors)}"
        )

    territory_masks: dict[str, np.ndarray] = {}
    for index, item in enumerate(territories):
        path = f"territories[{index}]"
        color = tuple(int(item[key]) for key in ("R", "G", "B"))
        mask = _pixel_mask(territory_pixels, color)
        territory_masks[item["territory_id"]] = mask
        expected_x, expected_y = _mask_centroid(mask, path)
        if not math.isclose(float(item["x"]), expected_x, rel_tol=0.0, abs_tol=1e-12) or not math.isclose(
            float(item["y"]), expected_y, rel_tol=0.0, abs_tol=1e-12
        ):
            raise Gate1Error(
                f"{path} center does not match raster centroid: "
                f"expected ({expected_x}, {expected_y}), got ({item['x']}, {item['y']})"
            )

    province_masks: dict[str, np.ndarray] = {}
    for index, item in enumerate(provinces):
        path = f"provinces[{index}]"
        color = tuple(int(item[key]) for key in ("R", "G", "B"))
        mask = _pixel_mask(province_pixels, color)
        province_masks[item["province_id"]] = mask
        expected_x, expected_y = _mask_centroid(mask, path)
        if not math.isclose(float(item["x"]), expected_x, rel_tol=0.0, abs_tol=1e-12) or not math.isclose(
            float(item["y"]), expected_y, rel_tol=0.0, abs_tol=1e-12
        ):
            raise Gate1Error(
                f"{path} center does not match raster centroid: "
                f"expected ({expected_x}, {expected_y}), got ({item['x']}, {item['y']})"
            )
        parent_mask = territory_masks[item["territory_id"]]
        if np.any(mask & ~parent_mask):
            raise Gate1Error(
                f"{path} pixels are not contained by declared parent {item['territory_id']}"
            )

    for territory in territories:
        child_masks = [province_masks[province_id] for province_id in territory["province_ids"]]
        if not child_masks:
            raise Gate1Error(f"territory {territory['territory_id']} has no province pixels")
        child_union = np.logical_or.reduce(child_masks)
        if not np.array_equal(child_union, territory_masks[territory["territory_id"]]):
            raise Gate1Error(
                f"territory {territory['territory_id']} pixels do not equal the union of declared children"
            )

    _validate_seed_ledger(
        manifest, territories, provinces, territory_masks, province_masks
    )


'''
pipeline = replace_block(
    pipeline,
    "def _validate_artifact_semantics(",
    "def inspect_output(",
    artifact_function,
    "artifact spatial authority",
)
PIPELINE.write_text(pipeline, encoding="utf-8", newline="\n")

new_test = '''from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from tests.test_opengs_gate1_determinism import (
    FIXTURE,
    MODULE_DIR,
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
'''
NEW_TEST.write_text(new_test, encoding="utf-8", newline="\n")

workflow = WORKFLOW.read_text(encoding="utf-8")
workflow = replace_once(
    workflow,
    '      - "tests/test_opengs_gate1_determinism.py"\n',
    '      - "tests/test_opengs_gate1_*.py"\n',
    "workflow test path",
)
workflow = replace_once(
    workflow,
    '        run: python -m py_compile tools/opengs_eval/gate1_generator.py tools/opengs_eval/make_gate1_fixture.py\n',
    '        run: python -m py_compile tools/opengs_eval/gate1_generator.py tools/opengs_eval/make_gate1_fixture.py tests/test_opengs_gate1_spatial_integrity.py\n',
    "workflow compile",
)
workflow = replace_once(
    workflow,
    '        run: python -m unittest tests.test_opengs_gate1_determinism -v\n',
    '        run: python -m unittest tests.test_opengs_gate1_determinism tests.test_opengs_gate1_spatial_integrity -v\n',
    "workflow unit tests",
)
WORKFLOW.write_text(workflow, encoding="utf-8", newline="\n")

doc = DOC.read_text(encoding="utf-8")
doc = replace_once(
    doc,
    '- Lloyd streams are additionally named per connected component, so sampling consumption cannot perturb empty-cell replacement.\n- Every non-empty connected component receives a seed, and impossible count requests fail before publication.\n',
    '- Lloyd streams are additionally named per connected component, so sampling consumption cannot perturb empty-cell replacement.\n- Territory and province generation use output-reconstructable masks; inspection independently recomputes each connected-component count from decoded raster geometry before accepting the stage ledger.\n- Every non-empty connected component receives exactly one paired Lloyd stream, and impossible count requests fail before publication.\n',
    "document component authority",
)
doc = replace_once(
    doc,
    '`inspect-output` recomputes every named seed from the root authority, enforces the complete stage ledger and pinned environment, validates the exact regular-file output set, parses territory/province relationships and counts, and decodes both RGB PNGs to verify dimensions and exact metadata color correspondence. Recomputing self-reported hashes cannot make semantically invalid artifacts pass.\n',
    '`inspect-output` recomputes every named seed from the root authority, derives the exact component-stage ledger from output-reconstructable raster masks, and enforces the pinned environment. It validates stable index-derived colors, exact record centroids, province-to-territory pixel containment, complete child coverage, dimensions, relationships, counts, and the exact regular-file output set. Recomputing self-reported hashes cannot make an extra component stream, swapped pixel region, moved center, or coherent parent reassignment pass.\n',
    "document spatial authority",
)
doc = replace_once(
    doc,
    '9. Linux-to-Windows byte parity across every authoritative artifact.\n',
    '9. Linux-to-Windows byte parity across every authoritative artifact;\n10. rejection of extra deterministically valid component streams;\n11. rejection of pixel-region swaps, in-bounds center mutation, and coherent parent reassignment.\n',
    "document added tests",
)
DOC.write_text(doc, encoding="utf-8", newline="\n")

provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
for relative in sorted(provenance["destination_canonical_utf8_lf_sha256"]):
    path = ROOT / relative
    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    provenance["destination_canonical_utf8_lf_sha256"][relative] = hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()
PROVENANCE.write_text(
    json.dumps(provenance, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
    newline="\n",
)

print("Applied Gate 1 component-ledger and raster-spatial authority corrections")
