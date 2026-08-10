from __future__ import annotations

import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from gates_of_codex.expanded_nations_inf_costs import (
    inject_actor_inf_cost_rows,
    project_actor_inf_cost_rows,
    verify_actor_inf_cost_rows,
)
from gates_of_codex.expanded_nations_models import ExpandedNationsError
from gates_of_codex.expanded_nations_render import render_roster_file


class ExpandedNationsInfCostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.layers = [self.root / name for name in ("vanilla", "west81", "codex", "ai", "gates")]
        for layer in self.layers:
            (layer / "resource").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _actor(self) -> dict:
        return {
            "actor_id": "esp",
            "display_name": "Spain",
            "tactical_side": "nato",
            "units": [
                {
                    "unit_name": "3rd_assault_fixture(nato)",
                    "component_id": "spain_3rd_assault_legion",
                    "source_side": "ukr",
                    "tactical_side": "nato",
                    "period": "2022s",
                    "members": {"azov3_squadlead": 1},
                }
            ],
        }

    def _write_source_breed(self) -> None:
        breed = self.layers[2] / "resource/set/breed/mp/ukr/2022s/azov3_squadlead.set"
        breed.parent.mkdir(parents=True)
        breed.write_text('{breed {skin "fixture"}}\n', encoding="utf-8")

    def _write_inf_at(self, layer_index: int, filename: str, row: str) -> None:
        path = self.layers[layer_index] / f"resource/set/multiplayer/units/conquest/{filename}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(row + "\n", encoding="utf-8")

    def _write_inf(self, side: str, row: str) -> None:
        self._write_inf_at(2, f"inf_{side}.set", row)

    def test_cross_side_cost_preserves_source_native_price(self) -> None:
        self._write_source_breed()
        self._write_inf(
            "ukr",
            '{"mp/ukr/2022s/azov3_squadlead" ("ukr_elite" side(ukr)) {cost 36.5}}',
        )

        rows, body = project_actor_inf_cost_rows(self._actor(), self.layers)

        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("mp/ukr/2022s/azov3_squadlead", row.source_path)
        self.assertEqual("mp/nato/2022s/azov3_squadlead", row.target_path)
        self.assertEqual(36.5, row.cost)
        self.assertIn('"mp/nato/2022s/azov3_squadlead"', body)
        self.assertIn('("ukr_elite" side(nato))', body)
        self.assertIn("{cost 36.5}", body)
        self.assertNotIn('"mp/ukr/2022s/azov3_squadlead" (', body)

        roster = inject_actor_inf_cost_rows(render_roster_file(self._actor()), body)
        manifest = {
            "tactical_side": "nato",
            "inf_cost_rows": [asdict(row)],
        }
        verify_actor_inf_cost_rows(roster, manifest)

    def test_existing_target_native_cost_wins_without_override(self) -> None:
        self._write_source_breed()
        self._write_inf(
            "ukr",
            '{"mp/ukr/2022s/azov3_squadlead" ("ukr_elite" side(ukr)) {cost 36.5}}',
        )
        self._write_inf(
            "nato",
            '{"mp/nato/2022s/azov3_squadlead" ("nato_elite" side(nato)) {cost 41.0}}',
        )

        rows, body = project_actor_inf_cost_rows(self._actor(), self.layers)

        self.assertEqual([], rows)
        self.assertEqual("", body)

    def test_missing_source_cost_fails_closed(self) -> None:
        self._write_source_breed()
        with self.assertRaisesRegex(ExpandedNationsError, "no native Conquest inf cost row"):
            project_actor_inf_cost_rows(self._actor(), self.layers)

    def test_zero_source_cost_fails_closed(self) -> None:
        self._write_source_breed()
        self._write_inf(
            "ukr",
            '{"mp/ukr/2022s/azov3_squadlead" ("ukr_elite" side(ukr)) {cost 0}}',
        )
        with self.assertRaisesRegex(ExpandedNationsError, "non-positive cost"):
            project_actor_inf_cost_rows(self._actor(), self.layers)

    def test_unapproved_cross_side_component_does_not_project_costs(self) -> None:
        self._write_source_breed()
        self._write_inf(
            "ukr",
            '{"mp/ukr/2022s/azov3_squadlead" ("ukr_elite" side(ukr)) {cost 36.5}}',
        )
        actor = self._actor()
        actor["units"][0]["component_id"] = "france_national"

        rows, body = project_actor_inf_cost_rows(actor, self.layers)

        self.assertEqual([], rows)
        self.assertEqual("", body)

    def test_unrelated_same_priority_conflict_does_not_block_projection(self) -> None:
        self._write_source_breed()
        self._write_inf(
            "ukr",
            '{"mp/ukr/2022s/azov3_squadlead" ("ukr_elite" side(ukr)) {cost 36.5}}',
        )
        self._write_inf_at(
            1,
            "inf_csa_a.set",
            '{"mp/csa/era1950/usmc_guncrew" ("csa_crew" side(csa)) {cost 10}}',
        )
        self._write_inf_at(
            1,
            "inf_csa_b.set",
            '{"mp/csa/era1950/usmc_guncrew" ("csa_crew" side(csa)) {cost 11}}',
        )

        rows, _ = project_actor_inf_cost_rows(self._actor(), self.layers)

        self.assertEqual(1, len(rows))
        self.assertEqual(36.5, rows[0].cost)

    def test_unrelated_parser_diagnostic_in_source_file_does_not_block_projection(self) -> None:
        self._write_source_breed()
        self._write_inf(
            "ukr",
            '{"broken\n'
            '{"mp/ukr/2022s/azov3_squadlead" ("ukr_elite" side(ukr)) {cost 36.5}}',
        )

        rows, _ = project_actor_inf_cost_rows(self._actor(), self.layers)

        self.assertEqual(1, len(rows))
        self.assertEqual(36.5, rows[0].cost)

    def test_requested_malformed_row_still_fails_closed(self) -> None:
        self._write_source_breed()
        self._write_inf(
            "ukr",
            '{"mp/ukr/2022s/azov3_squadlead\n',
        )

        with self.assertRaisesRegex(ExpandedNationsError, "no native Conquest inf cost row"):
            project_actor_inf_cost_rows(self._actor(), self.layers)

    def test_requested_same_priority_conflict_fails_closed(self) -> None:
        self._write_source_breed()
        self._write_inf_at(
            2,
            "inf_ukr_a.set",
            '{"mp/ukr/2022s/azov3_squadlead" ("ukr_elite" side(ukr)) {cost 36.5}}',
        )
        self._write_inf_at(
            2,
            "inf_ukr_b.set",
            '{"mp/ukr/2022s/azov3_squadlead" ("ukr_elite" side(ukr)) {cost 37.0}}',
        )

        with self.assertRaisesRegex(
            ExpandedNationsError,
            "Conflicting native inf metadata.*requested path mp/ukr/2022s/azov3_squadlead",
        ):
            project_actor_inf_cost_rows(self._actor(), self.layers)

    def test_higher_priority_row_replaces_lower_priority_conflict(self) -> None:
        self._write_source_breed()
        self._write_inf_at(
            1,
            "inf_ukr_a.set",
            '{"mp/ukr/2022s/azov3_squadlead" ("ukr_elite" side(ukr)) {cost 30}}',
        )
        self._write_inf_at(
            1,
            "inf_ukr_b.set",
            '{"mp/ukr/2022s/azov3_squadlead" ("ukr_elite" side(ukr)) {cost 31}}',
        )
        self._write_inf(
            "ukr",
            '{"mp/ukr/2022s/azov3_squadlead" ("ukr_elite" side(ukr)) {cost 36.5}}',
        )

        rows, _ = project_actor_inf_cost_rows(self._actor(), self.layers)

        self.assertEqual(1, len(rows))
        self.assertEqual(36.5, rows[0].cost)
        self.assertTrue(rows[0].source_reference.startswith("2:codex/"))


if __name__ == "__main__":
    unittest.main()
