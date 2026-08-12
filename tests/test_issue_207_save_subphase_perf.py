from __future__ import annotations

import unittest
from pathlib import Path

from gates_of_codex import command_cycle_perf


ROOT = Path(__file__).resolve().parents[1]


class SaveSubphasePerfTests(unittest.TestCase):
    def test_runtime_save_does_not_repeat_formation_normalization(self) -> None:
        source = (ROOT / "src/gates_of_codex/command_cycle_perf.py").read_text(
            encoding="utf-8"
        )
        block = source.split("def _compact_save_campaign(", 1)[1].split(
            "def _bulk_formation_presentation_rows(", 1
        )[0]
        self.assertEqual(1, block.count("ensure_strategic_layer(state)"))
        self.assertNotIn("ensure_strategic_formations(state)", block)

    def test_runtime_save_reports_authoritative_subphases(self) -> None:
        source = (ROOT / "src/gates_of_codex/command_cycle_perf.py").read_text(
            encoding="utf-8"
        )
        for name in (
            '"strategic"',
            '"positions"',
            '"orders"',
            '"site_control"',
            '"supply"',
            '"s11_schema"',
            '"observer_refresh"',
            '"validate"',
            '"encode"',
            '"write"',
        ):
            self.assertIn(name, source)
        self.assertIn('f"save_{name}_ms"', source)

    def test_stable_public_timing_key_contract_is_unchanged(self) -> None:
        self.assertEqual(
            (
                "load_ms",
                "mutate_ms",
                "save_ms",
                "snapshot_ms",
                "total_ms",
                "campaign_bytes",
                "snapshot_bytes",
                "read_only_fast_path",
                "snapshot_fast_path",
                "compact_save_path",
            ),
            command_cycle_perf.timing_keys(),
        )


if __name__ == "__main__":
    unittest.main()
