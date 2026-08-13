"""Regression: committed #191 personnel-cost packs stay in their goc_* namespace."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from gates_of_codex.goc_tactical_army_registry import playable_goc_sides


_GOC_INF_COST_RE = re.compile(r"^;\s*goc-inf-cost\s+(\{.*\})\s*$", re.MULTILINE)
_TARGET_ROW_RE = re.compile(r'^\{"(mp/[^\"]+)"', re.MULTILINE)
_SIDE_CALL_RE = re.compile(r"\bside\(([^)]+)\)")


class CommittedPersonnelCostNamespaceTests(unittest.TestCase):
    def test_all_committed_191_inf_packs_match_their_goc_namespace(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sides = tuple(playable_goc_sides())

        # Explicit family controls requested by the independent review:
        # BEL = coalition fallback, CZE = national hybrid.
        self.assertIn("goc_bel", sides)
        self.assertIn("goc_cze", sides)

        for side in sides:
            with self.subTest(side=side):
                path = (
                    root
                    / "resource/set/multiplayer/units/conquest"
                    / f"inf_{side}.set"
                )
                self.assertTrue(path.is_file(), side)
                text = path.read_text(encoding="utf-8")

                metadata = [json.loads(raw) for raw in _GOC_INF_COST_RE.findall(text)]
                self.assertTrue(metadata, f"{side} has no committed personnel-cost rows")

                expected_targets = [str(row["target_path"]) for row in metadata]
                rendered_targets = _TARGET_ROW_RE.findall(text)
                self.assertEqual(rendered_targets, expected_targets, side)

                for row in metadata:
                    target = str(row["target_path"])
                    self.assertTrue(
                        target.startswith(f"mp/{side}/"),
                        msg=f"{side} metadata escapes its namespace: {target}",
                    )
                    self.assertGreater(float(row["cost"]), 0.0, side)

                side_calls = _SIDE_CALL_RE.findall(text)
                self.assertEqual(len(side_calls), len(metadata), side)
                self.assertEqual(set(side_calls), {side}, side)

                # Lock out the exact stale-snapshot defect that reached c5221aa.
                self.assertNotIn('"target_path":"mp/nato/', text, side)
                self.assertNotIn("side(nato)", text, side)


if __name__ == "__main__":
    unittest.main()
