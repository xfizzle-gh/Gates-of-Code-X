from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NativePerfLogTests(unittest.TestCase):
    def test_godot_log_includes_save_and_engine_subphase_timings(self) -> None:
        source = (ROOT / "godot/scripts/main_perf_measured.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn("func _save_timing_suffix", source)
        self.assertIn("save_validate_ms", source)
        self.assertIn("save_observer_refresh_ms", source)
        self.assertIn("save_encode_ms", source)
        self.assertIn("save_write_ms", source)
        self.assertIn("engine_init_ms", source)
        self.assertIn("var save_suffix := _save_timing_suffix(payload)", source)


if __name__ == "__main__":
    unittest.main()
