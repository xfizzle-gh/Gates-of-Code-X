from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.map_background import (
    DEFAULT_SOURCE_PX,
    apply_affine,
    build_control_points,
    evaluate_control_points,
    fit_affine_transform,
    invert_affine,
)
from gates_of_codex.strategic_map import write_png_rgb


ROOT = Path(__file__).resolve().parents[1]
EM_DIR = ROOT / "godot/assets/maps/europe_mediterranean/prototype"


class MapBackgroundCalibrationTests(unittest.TestCase):
    def test_affine_fit_recovers_known_transform(self) -> None:
        # Known affine: scale 2, rotate 0, translate (10, -5)
        truth = [[2.0, 0.0, 10.0], [0.0, 2.0, -5.0]]
        sources = [(0.0, 0.0), (10.0, 0.0), (0.0, 10.0), (7.0, 3.0), (4.0, 8.0)]
        pairs = []
        for x, y in sources:
            u, v = apply_affine(truth, x, y)
            pairs.append(((x, y), (u, v)))
        fitted = fit_affine_transform(pairs)
        for i in range(2):
            for j in range(3):
                self.assertAlmostEqual(truth[i][j], fitted[i][j], places=6)
        inv = invert_affine(fitted)
        for x, y in sources:
            u, v = apply_affine(fitted, x, y)
            rx, ry = apply_affine(inv, u, v)
            self.assertAlmostEqual(x, rx, places=6)
            self.assertAlmostEqual(y, ry, places=6)

    def test_control_points_include_source_and_target(self) -> None:
        rows = build_control_points(source_px=DEFAULT_SOURCE_PX)
        self.assertGreaterEqual(len(rows), 8)
        for row in rows:
            self.assertIn("source_px", row)
            self.assertIn("target_px", row)
            self.assertEqual(2, len(row["source_px"]))
            self.assertEqual(2, len(row["target_px"]))
        pairs = [(tuple(r["source_px"]), tuple(r["target_px"])) for r in rows]
        matrix = fit_affine_transform(pairs)
        residuals, summary = evaluate_control_points(rows, matrix)
        self.assertEqual(len(rows), len(residuals))
        self.assertIn("median_error_px", summary)
        self.assertIn("max_error_px", summary)
        self.assertLessEqual(summary["median_error_px"], 8.0)
        self.assertLessEqual(summary["max_error_px"], 20.0)
        self.assertTrue(summary["accepted"])

    def test_pack_png_absent_from_repo_and_placeholder_present(self) -> None:
        self.assertFalse((EM_DIR / "background_pack_reference.png").is_file())
        self.assertTrue((EM_DIR / "background_placeholder.png").is_file())
        self.assertTrue((EM_DIR / "background_config.example.json").is_file())
        example = json.loads((EM_DIR / "background_config.example.json").read_text(encoding="utf-8"))
        self.assertIn("background_texture", example)

    def test_placeholder_is_loadable_rgb_png(self) -> None:
        from gates_of_codex.strategic_map import decode_png_rgb

        image = decode_png_rgb(EM_DIR / "background_placeholder.png")
        self.assertGreater(image.width, 0)
        self.assertGreater(image.height, 0)
        self.assertEqual(image.width * image.height, len(image.pixels))


if __name__ == "__main__":
    unittest.main()
