from __future__ import annotations

import unittest

from gates_of_codex.play_context import select_tactical_map


class MapRotationTests(unittest.TestCase):
    def test_explicit_map_wins(self) -> None:
        chosen = select_tactical_map(
            ["multi/dcg_a", "multi/dcg_b"],
            preferred="multi/dcg_a",
            used=["multi/dcg_a"],
            explicit="multi/dcg_b",
        )
        self.assertEqual("multi/dcg_b", chosen)

    def test_skips_recently_used_maps(self) -> None:
        chosen = select_tactical_map(
            [
                "multi/dcg_[cwa71]_fulda",
                "multi/dcg_[cwa71]_border",
                "multi/dcg_[cwa71]_fields",
            ],
            preferred="multi/dcg_[cwa71]_fulda",
            used=["multi/dcg_[cwa71]_fulda"],
            battle_id="goc-1-aaaa",
        )
        self.assertNotEqual("multi/dcg_[cwa71]_fulda", chosen)
        self.assertIn("dcg_", chosen)

    def test_falls_back_when_all_used(self) -> None:
        maps = ["multi/dcg_a", "multi/dcg_b"]
        chosen = select_tactical_map(maps, used=maps, battle_id="x")
        self.assertIn(chosen, maps)


if __name__ == "__main__":
    unittest.main()
