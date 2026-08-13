from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations_inf_costs import project_actor_inf_cost_rows
from gates_of_codex.expanded_nations_models import ExpandedNationsError


class SpainIlduNativeUnpricedPzf3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.layers = [
            self.root / name
            for name in ("vanilla", "west81", "codex", "ai", "gates")
        ]
        for layer in self.layers:
            (layer / "resource").mkdir(parents=True)

        breed_root = self.layers[2] / "resource/set/breed/mp/ukr/2022s"
        breed_root.mkdir(parents=True)
        for name in ("nato_squadlead", "nato_antitank_pzf3"):
            (breed_root / f"{name}.set").write_text(
                '{breed {skin "fixture"}}\n',
                encoding="utf-8",
            )

        inf = self.layers[2] / "resource/set/multiplayer/units/conquest/inf_ukr.set"
        inf.parent.mkdir(parents=True)
        inf.write_text(
            '{"mp/ukr/2022s/nato_squadlead" '
            '("nato_leader" side(ukr)) {cost 36.5}}\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _actor(self, members: dict[str, int]) -> dict:
        return {
            "actor_id": "esp",
            "display_name": "Spain",
            "tactical_side": "goc_esp",
            "units": [
                {
                    "unit_name": "goc_ildu_at(goc_esp)",
                    "component_id": "ukraine_ildu",
                    "source_side": "ukr",
                    "tactical_side": "goc_esp",
                    "period": "2022s",
                    "virtual": True,
                    "members": members,
                    "vehicles": [],
                }
            ],
        }

    def test_pzf3_native_omission_is_preserved_when_ildu_at_has_priced_companion(self) -> None:
        rows, body = project_actor_inf_cost_rows(
            self._actor({"nato_squadlead": 1, "nato_antitank_pzf3": 1}),
            self.layers,
        )

        self.assertEqual(1, len(rows))
        self.assertEqual("mp/ukr/2022s/nato_squadlead", rows[0].source_path)
        self.assertEqual("mp/goc_esp/2022s/nato_squadlead", rows[0].target_path)
        self.assertEqual(36.5, rows[0].cost)
        self.assertNotIn("nato_antitank_pzf3", body)

    def test_pzf3_native_omission_alone_still_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            ExpandedNationsError,
            "no positive native Conquest inf cost coverage",
        ):
            project_actor_inf_cost_rows(
                self._actor({"nato_antitank_pzf3": 1}),
                self.layers,
            )


if __name__ == "__main__":
    unittest.main()
