from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations_inf_costs import project_actor_inf_cost_rows
from gates_of_codex.expanded_nations_models import ExpandedNationsError


class SpainIlduCostAuthorityTests(unittest.TestCase):
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
        for name in (
            "nato_atassist",
            "nato_mgassist",
            "nato_manpad_operator",
            "nato_manpad_supporter",
            "nato_medic",
            "nato_antitank_pzf3",
        ):
            (breed_root / f"{name}.set").write_text(
                '{breed {skin "fixture"}}\n',
                encoding="utf-8",
            )

        conquest = self.layers[3] / "resource/set/multiplayer/units/conquest"
        conquest.mkdir(parents=True)
        (conquest / "inf_ukr.set").write_text(
            '\n'.join(
                (
                    '{"mp/ukr/2022s/ukr_atassist" '
                    '("ukr_regular" side(ukr)) {cost 7.0}}',
                    '{"mp/ukr/2022s/ukr_lmgassist" '
                    '("ukr_regular" side(ukr)) {cost 7.0}}',
                    '{"mp/ukr/2022s/ukr_manpad_operator" '
                    '("ukr_radioman" side(ukr)) {cost 17.5}}',
                    '{"mp/ukr/2022s/ukr_manpad_supporter" '
                    '("ukr_radioman" side(ukr)) {cost 17.5}}',
                )
            )
            + '\n',
            encoding="utf-8",
        )
        (conquest / "inf_nato.set").write_text(
            '{"mp/nato/2022s/nato_medic" '
            '("nato_basic" side(nato)) {cost 28.0}}\n',
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
                    "unit_name": "goc_ildu_fixture(goc_esp)",
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

    def test_exact_installed_stack_ildu_equivalents_project_expected_costs(self) -> None:
        expected = {
            "nato_atassist": ("mp/ukr/2022s/ukr_atassist", 7.0),
            "nato_mgassist": ("mp/ukr/2022s/ukr_lmgassist", 7.0),
            "nato_manpad_operator": ("mp/ukr/2022s/ukr_manpad_operator", 17.5),
            "nato_manpad_supporter": ("mp/ukr/2022s/ukr_manpad_supporter", 17.5),
            "nato_medic": ("mp/nato/2022s/nato_medic", 28.0),
        }

        rows, body = project_actor_inf_cost_rows(
            self._actor({name: 1 for name in expected}),
            self.layers,
        )

        actual = {
            row.target_path.rsplit("/", 1)[-1]: (row.source_path, row.cost)
            for row in rows
        }
        self.assertEqual(expected, actual)
        for breed in expected:
            self.assertIn(f"mp/goc_esp/2022s/{breed}", body)

    def test_pzf3_remains_unpriced_but_is_allowed_with_priced_at_companion(self) -> None:
        rows, body = project_actor_inf_cost_rows(
            self._actor({"nato_atassist": 1, "nato_antitank_pzf3": 1}),
            self.layers,
        )

        self.assertEqual(1, len(rows))
        self.assertEqual("mp/ukr/2022s/ukr_atassist", rows[0].source_path)
        self.assertEqual("mp/goc_esp/2022s/nato_atassist", rows[0].target_path)
        self.assertEqual(7.0, rows[0].cost)
        self.assertNotIn("nato_antitank_pzf3", body)

    def test_unmapped_ildu_member_still_fails_closed(self) -> None:
        extra = self.layers[2] / "resource/set/breed/mp/ukr/2022s/nato_unknown_ildu.set"
        extra.write_text('{breed {skin "fixture"}}\n', encoding="utf-8")

        with self.assertRaisesRegex(
            ExpandedNationsError,
            "has no native Conquest inf cost row",
        ):
            project_actor_inf_cost_rows(
                self._actor({"nato_unknown_ildu": 1}),
                self.layers,
            )


if __name__ == "__main__":
    unittest.main()
