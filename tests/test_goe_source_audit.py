from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from gates_of_codex.entrypoint import main as entrypoint_main
from gates_of_codex.goe_source_audit import (
    build_goe_source_audit,
    write_goe_source_audit,
)
from gates_of_codex.map_layout import load_marker_layout


class GoEProvinceSourceAuditTests(unittest.TestCase):
    def test_extracted_marker_database_records_all_ids_and_anchors(self) -> None:
        marker = load_marker_layout()
        rows = marker["provinces"]
        colors = {
            (
                int(row["id_color"]["r"]),
                int(row["id_color"]["g"]),
                int(row["id_color"]["b"]),
            )
            for row in rows
        }
        self.assertEqual(517, marker["province_count"])
        self.assertEqual(517, len(rows))
        self.assertEqual(517, len(colors))
        self.assertTrue(all("x" in row and "y" in row for row in rows))
        self.assertTrue(all("id_color" in row for row in rows))

    def test_audit_separates_exact_source_data_from_scenario_design(self) -> None:
        payload = build_goe_source_audit()
        coverage = payload["mapping_coverage"]
        self.assertEqual(517, payload["province_count"])
        self.assertEqual(517, len(payload["province_mappings"]))
        self.assertEqual(302, coverage["mapped_graph_records"])
        self.assertEqual(215, coverage["unmapped_graph_records"])
        self.assertEqual(
            517,
            payload["source_inventory"]["marker_id_database"]["unique_rgb_count"],
        )
        self.assertEqual(1314, payload["source_inventory"]["id_texture"]["width"])
        self.assertEqual(1513, payload["source_inventory"]["id_texture"]["height"])
        self.assertEqual("RGB24", payload["source_inventory"]["id_texture"]["format"])
        self.assertEqual(
            "not_found",
            payload["field_availability"]["country_ownership"]["status"],
        )
        self.assertFalse(
            payload["scenario_design_separation"]["modern_control_profile"]["goe_ownership_claimed"]
        )
        self.assertTrue(
            all(row["country_id"] is None for row in payload["province_mappings"])
        )
        mapped = [row for row in payload["province_mappings"] if row["marker_province_id"]]
        unmapped = [row for row in payload["province_mappings"] if not row["marker_province_id"]]
        self.assertTrue(all(row["id_color"] is not None for row in mapped))
        self.assertTrue(all(row["id_color"] is None for row in unmapped))
        self.assertTrue(
            all(row["marker_mapping_method"] == "unmapped_neighbor_average" for row in unmapped)
        )

    def test_committed_manifest_matches_computed_source_counts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (root / "docs/audits/goe-province-metadata.json").read_text(encoding="utf-8")
        )
        payload = build_goe_source_audit(include_mappings=False)
        self.assertEqual(payload["province_count"], manifest["province_count"])
        self.assertEqual(
            payload["source_inventory"]["marker_id_database"]["record_count"],
            manifest["canonical_province_records"]["marker_id_database"]["record_count"],
        )
        self.assertEqual(
            payload["source_inventory"]["marker_id_database"]["unique_rgb_count"],
            manifest["canonical_province_records"]["marker_id_database"]["unique_rgb_count"],
        )
        self.assertEqual(
            payload["mapping_coverage"]["mapped_graph_records"],
            manifest["mapping_coverage"]["mapped_graph_records"],
        )
        self.assertEqual(
            payload["mapping_coverage"]["unmapped_graph_records"],
            manifest["mapping_coverage"]["unmapped_graph_records"],
        )

    def test_detailed_output_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "second"
            write_goe_source_audit(
                first / "goe-province-detailed.json",
                first / "goe-province-detailed.md",
            )
            write_goe_source_audit(
                second / "goe-province-detailed.json",
                second / "goe-province-detailed.md",
            )
            self.assertEqual(
                (first / "goe-province-detailed.json").read_bytes(),
                (second / "goe-province-detailed.json").read_bytes(),
            )
            self.assertEqual(
                (first / "goe-province-detailed.md").read_bytes(),
                (second / "goe-province-detailed.md").read_bytes(),
            )

    def test_cli_writes_paths_containing_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "GoE Audit Output"
            output = root / "goe province detailed.json"
            summary = root / "goe province detailed.md"
            with redirect_stdout(io.StringIO()) as stdout:
                code = entrypoint_main([
                    "audit-goe-provinces",
                    "--output",
                    str(output),
                    "--summary",
                    str(summary),
                ])
            self.assertEqual(0, code)
            self.assertTrue(output.is_file())
            self.assertTrue(summary.is_file())
            result = json.loads(stdout.getvalue())
            self.assertEqual(517, result["province_count"])
            self.assertEqual(517, result["unique_rgb_count"])
            self.assertEqual(302, result["mapped_graph_records"])
            self.assertEqual(215, result["unmapped_graph_records"])


if __name__ == "__main__":
    unittest.main()
