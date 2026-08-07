import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "tools" / "opengs_eval" / "upstream_pin.json"
NATURAL_EARTH_PIN_PATH = (
    ROOT / "tools" / "opengs_eval" / "natural_earth_pin.json"
)
SUITE_PATH = ROOT / "tools" / "opengs_eval" / "benchmark_scenarios.json"
NATURAL_EARTH_SUITE_PATH = (
    ROOT / "tools" / "opengs_eval" / "natural_earth_scenarios.json"
)
INVENTORY_PATH = (
    ROOT
    / "docs"
    / "research"
    / "opengs-evaluation"
    / "provenance_inventory.json"
)
AUTHORITY_PATH = ROOT / "config" / "earth3" / "production_authority.json"
BENCHMARK_MODULE_PATH = (
    ROOT / "tools" / "opengs_eval" / "benchmark_upstream.py"
)


class OpenGsGate0ContractTests(unittest.TestCase):
    def test_upstream_pin_is_locked(self):
        pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            pin["repository"], "Thomas-Holtvedt/opengs-maptool"
        )
        self.assertEqual(
            pin["commit"],
            "06e7ec8517bd45872cf44d77cb8784e5ffca49bb",
        )
        self.assertEqual(pin["license"], "MIT")
        self.assertFalse(pin["full_opengs_runtime_integration"])
        self.assertFalse(pin["jfa_compute_integration"])
        self.assertFalse(pin["production_map_replacement_authorized"])
        self.assertFalse(pin["earth3_production_map_modified"])
        self.assertFalse(pin["pr_128_modified"])

    def test_benchmark_module_uses_same_pin(self):
        spec = importlib.util.spec_from_file_location(
            "opengs_gate0_benchmark", BENCHMARK_MODULE_PATH
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(
            module.PINNED_COMMIT,
            "06e7ec8517bd45872cf44d77cb8784e5ffca49bb",
        )
        self.assertEqual(
            module.PINNED_REPOSITORY,
            "Thomas-Holtvedt/opengs-maptool",
        )

    def test_suite_contains_direct_earth3_count_comparison(self):
        suite = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
        scenarios = {row["id"]: row for row in suite["scenarios"]}
        earth3 = scenarios["earth3_count_3514"]
        self.assertEqual(
            earth3["land_provinces"] + earth3["ocean_provinces"],
            3514,
        )
        self.assertEqual(earth3["land_provinces"], 3299)
        self.assertEqual(earth3["ocean_provinces"], 215)
        self.assertEqual(earth3["repeats"], 3)
        self.assertIn("earth3_count_3514_jagged", scenarios)
        self.assertIn("stress_5000", scenarios)

    def test_natural_earth_inputs_are_exactly_pinned(self):
        pin = json.loads(NATURAL_EARTH_PIN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(pin["repository"], "nvkelso/natural-earth-vector")
        self.assertEqual(pin["ref"], "v5.1.2")
        self.assertEqual(pin["license"], "public_domain")
        self.assertEqual(
            pin["theatre_lon_lat_bounds"], [-25.0, 20.0, 60.0, 75.0]
        )
        files = {row["role"]: row for row in pin["files"]}
        self.assertEqual(
            files["land"]["git_blob_sha1"],
            "2d76878175b8054acd9c5a52917ee9ea59a36fc5",
        )
        self.assertEqual(
            files["lakes"]["git_blob_sha1"],
            "e48ec603e0943b62f8c81960fb990bb6bab4a4a8",
        )
        self.assertEqual(
            files["national_boundaries"]["git_blob_sha1"],
            "a4e4090820e0d95c23d55aefa6b5f1721552cc71",
        )
        self.assertEqual(
            files["populated_places"]["git_blob_sha1"],
            "4da9c6b27b5cd41d7c930ea9cd0c1f84548b65fb",
        )

    def test_natural_earth_suite_preserves_naive_lake_measurement(self):
        suite = json.loads(
            NATURAL_EARTH_SUITE_PATH.read_text(encoding="utf-8")
        )
        scenarios = {row["id"]: row for row in suite["scenarios"]}
        naive = scenarios["natural_earth_naive_3514"]
        self.assertEqual(
            naive["land_provinces"] + naive["ocean_provinces"], 3514
        )
        self.assertEqual(naive["repeats"], 3)
        self.assertFalse(naive["jagged_land"])
        self.assertTrue(scenarios["natural_earth_jagged_3514"]["jagged_land"])

    def test_provenance_inventory_does_not_treat_mit_as_data_license(self):
        inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        source_by_id = {row["id"]: row for row in inventory["sources"]}
        self.assertEqual(
            inventory["generator"]["approval_status"],
            "approved_for_gate0_evaluation_only",
        )
        self.assertEqual(
            source_by_id["natural_earth"]["published_license"],
            "Public domain",
        )
        self.assertTrue(source_by_id["openstreetmap"]["share_alike"])
        self.assertIn(
            "conditional",
            source_by_id["openstreetmap"]["approval_status"],
        )
        self.assertIn(
            "pending",
            source_by_id["copernicus_dem"]["approval_status"],
        )

    def test_earth3_authority_remains_locked(self):
        authority = json.loads(AUTHORITY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(authority["map_id"], "earth3_europe_mediterranean")
        self.assertEqual(authority["province_count"], 3514)
        self.assertEqual(authority["land_count"], 3299)
        self.assertEqual(authority["water_count"], 215)
        self.assertEqual(authority["selectable_province_count"], 3299)
        self.assertEqual(
            authority["excluded_gates_ids"], ["e3_2830", "e3_2888"]
        )
        self.assertEqual(
            authority["water_policy"]["normal_click_returns"],
            "no_province",
        )


if __name__ == "__main__":
    unittest.main()
