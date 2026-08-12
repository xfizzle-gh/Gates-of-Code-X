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

    def _write_source_breed_named(self, name: str) -> None:
        breed = self.layers[2] / f"resource/set/breed/mp/ukr/2022s/{name}.set"
        breed.parent.mkdir(parents=True, exist_ok=True)
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

    def test_proven_demo_h_typo_uses_demon_h_cost_row(self) -> None:
        self._write_source_breed_named("azov3_demo_h")
        self._write_inf(
            "ukr",
            '{"mp/ukr/2022s/azov3_demon_h" ("ukr_specops" side(ukr)) {cost 40.0}}',
        )
        actor = self._actor()
        actor["units"][0]["members"] = {"azov3_demo_h": 1}

        rows, body = project_actor_inf_cost_rows(actor, self.layers)

        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("mp/ukr/2022s/azov3_demon_h", row.source_path)
        self.assertEqual("mp/nato/2022s/azov3_demo_h", row.target_path)
        self.assertEqual(40.0, row.cost)
        self.assertIn('"mp/nato/2022s/azov3_demo_h"', body)
        self.assertNotIn('"mp/nato/2022s/azov3_demon_h"', body)
        self.assertIn("{cost 40.0}", body)

    def test_proven_mg_mg3_typo_uses_mg3_cost_row(self) -> None:
        self._write_source_breed_named("azov3_mg_mg3")
        self._write_inf(
            "ukr",
            '{"mp/ukr/2022s/azov3_mg3" ("ukr_specops" side(ukr)) {cost 44.5}}',
        )
        actor = self._actor()
        actor["units"][0]["members"] = {"azov3_mg_mg3": 2}

        rows, body = project_actor_inf_cost_rows(actor, self.layers)

        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("mp/ukr/2022s/azov3_mg3", row.source_path)
        self.assertEqual("mp/nato/2022s/azov3_mg_mg3", row.target_path)
        self.assertEqual(44.5, row.cost)
        self.assertIn('"mp/nato/2022s/azov3_mg_mg3"', body)
        self.assertNotIn('"mp/nato/2022s/azov3_mg3"', body)
        self.assertIn("{cost 44.5}", body)

    def test_proven_saperi_native_conflict_uses_observed_specops_price(self) -> None:
        self._write_source_breed_named("azov3_saperi")
        self._write_inf_at(
            2,
            "inf_ukr_a.set",
            '{"mp/ukr/2022s/azov3_saperi" ("ukr_radioman" side(ukr)) {cost 21.5}}',
        )
        self._write_inf_at(
            2,
            "inf_ukr_b.set",
            '{"mp/ukr/2022s/azov3_saperi" ("ukr_specops" side(ukr)) {cost 26.0}}',
        )
        actor = self._actor()
        actor["units"][0]["members"] = {"azov3_saperi": 7}

        rows, body = project_actor_inf_cost_rows(actor, self.layers)

        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("mp/ukr/2022s/azov3_saperi", row.source_path)
        self.assertEqual("mp/nato/2022s/azov3_saperi", row.target_path)
        self.assertEqual(26.0, row.cost)
        self.assertIn('("ukr_specops" side(nato))', body)
        self.assertIn("{cost 26.0}", body)
        self.assertNotIn("{cost 21.5}", body)

    def test_proven_saperi_disposition_fails_if_expected_row_disappears(self) -> None:
        self._write_source_breed_named("azov3_saperi")
        self._write_inf_at(
            2,
            "inf_ukr_a.set",
            '{"mp/ukr/2022s/azov3_saperi" ("ukr_radioman" side(ukr)) {cost 21.5}}',
        )
        self._write_inf_at(
            2,
            "inf_ukr_b.set",
            '{"mp/ukr/2022s/azov3_saperi" ("ukr_specops" side(ukr)) {cost 25.0}}',
        )
        actor = self._actor()
        actor["units"][0]["members"] = {"azov3_saperi": 7}

        with self.assertRaisesRegex(
            ExpandedNationsError,
            "Proven native inf disposition no longer resolves uniquely",
        ):
            project_actor_inf_cost_rows(actor, self.layers)

    def test_source_native_unpriced_member_preserves_omission_with_positive_unit_coverage(self) -> None:
        self._write_source_breed()
        self._write_source_breed_named("azov3_antitank_javelin")
        self._write_inf(
            "ukr",
            '{"mp/ukr/2022s/azov3_squadlead" ("ukr_elite" side(ukr)) {cost 36.5}}',
        )
        actor = self._actor()
        actor["units"][0]["members"] = {
            "azov3_squadlead": 1,
            "azov3_antitank_javelin": 2,
        }

        rows, body = project_actor_inf_cost_rows(actor, self.layers)

        self.assertEqual(1, len(rows))
        self.assertEqual("mp/nato/2022s/azov3_squadlead", rows[0].target_path)
        self.assertNotIn("azov3_antitank_javelin", body)

    def test_source_native_unpriced_member_alone_fails_closed(self) -> None:
        self._write_source_breed_named("azov3_antitank_javelin")
        actor = self._actor()
        actor["units"][0]["members"] = {"azov3_antitank_javelin": 2}

        with self.assertRaisesRegex(
            ExpandedNationsError,
            "no positive native Conquest inf cost coverage",
        ):
            project_actor_inf_cost_rows(actor, self.layers)

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

    def test_source_family_projects_into_registered_goc_namespace(self) -> None:
        breed = self.layers[2] / "resource/set/breed/mp/nato/2022s/nato_rifleman.set"
        breed.parent.mkdir(parents=True, exist_ok=True)
        breed.write_text('{breed {skin "fixture"}}\n', encoding="utf-8")
        self._write_inf(
            "nato",
            '{"mp/nato/2022s/nato_rifleman" ("nato_rifle" side(nato)) {cost 31.5}}',
        )
        actor = {
            "actor_id": "usa",
            "display_name": "United States",
            "tactical_side": "goc_usa",
            "units": [
                {
                    "unit_name": "rifle(goc_usa)",
                    "component_id": "nato_us_forces",
                    "source_side": "nato",
                    "tactical_side": "goc_usa",
                    "period": "2022s",
                    "members": {"nato_rifleman": 1},
                }
            ],
        }
        rows, body = project_actor_inf_cost_rows(actor, self.layers)
        self.assertEqual(1, len(rows))
        self.assertEqual("mp/nato/2022s/nato_rifleman", rows[0].source_path)
        self.assertEqual("mp/goc_usa/2022s/nato_rifleman", rows[0].target_path)
        self.assertEqual("goc_usa", rows[0].target_side)
        self.assertIn('"mp/goc_usa/2022s/nato_rifleman"', body)
        self.assertIn("side(goc_usa)", body)

    def test_unauthorized_core_cross_side_into_goc_is_blocked(self) -> None:
        self._write_source_breed()
        self._write_inf(
            "ukr",
            '{"mp/ukr/2022s/azov3_squadlead" ("ukr_elite" side(ukr)) {cost 36.5}}',
        )
        actor = {
            "actor_id": "usa",
            "display_name": "United States",
            "tactical_side": "goc_usa",
            "units": [
                {
                    "unit_name": "stolen(goc_usa)",
                    "component_id": "nato_us_forces",
                    "source_side": "ukr",
                    "tactical_side": "goc_usa",
                    "period": "2022s",
                    "members": {"azov3_squadlead": 1},
                }
            ],
        }
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

    def test_vostok_role_map_projects_same_side_costs(self) -> None:
        breed = self.layers[2] / "resource/set/breed/mp/rusa/2022s/vostok_rifleman.set"
        breed.parent.mkdir(parents=True, exist_ok=True)
        breed.write_text('{breed {skin "vostok"}}\n', encoding="utf-8")
        self._write_inf(
            "rusa",
            '{"mp/rusa/2022s/spd_rifleman" ("rusa_basic" side(rusa)) {cost 17.5}}',
        )
        actor = {
            "actor_id": "donbas",
            "display_name": "Donbas",
            "tactical_side": "rusa",
            "units": [
                {
                    "unit_name": "goc_vostok_rifle(rusa)",
                    "component_id": "donbas_latent",
                    "source_side": "rusa",
                    "tactical_side": "rusa",
                    "period": "2022s",
                    "virtual": True,
                    "members": {"vostok_rifleman": 4},
                    "vehicles": [],
                }
            ],
        }
        rows, body = project_actor_inf_cost_rows(actor, self.layers)
        self.assertEqual(1, len(rows))
        self.assertEqual("mp/rusa/2022s/spd_rifleman", rows[0].source_path)
        self.assertEqual("mp/rusa/2022s/vostok_rifleman", rows[0].target_path)
        self.assertEqual(17.5, rows[0].cost)
        self.assertIn('"mp/rusa/2022s/vostok_rifleman"', body)
        self.assertIn("{cost 17.5}", body)
        roster = inject_actor_inf_cost_rows(render_roster_file(actor), body)
        verify_actor_inf_cost_rows(
            roster,
            {"tactical_side": "rusa", "inf_cost_rows": [asdict(rows[0])]},
        )

    def test_fj_eng_typo_alias_projects_same_side_cost(self) -> None:
        breed = self.layers[2] / "resource/set/breed/mp/nato/2022s/fj_eng.set"
        breed.parent.mkdir(parents=True, exist_ok=True)
        breed.write_text('{breed {skin "fj"}}\n', encoding="utf-8")
        self._write_inf(
            "nato",
            '{"mp/nato/2022s/fj_engineer" ("nato_radioman" side(nato)) {cost 35.5}}',
        )
        actor = {
            "actor_id": "fra",
            "display_name": "France",
            "tactical_side": "nato",
            "units": [
                {
                    "unit_name": "squad_dsk_eng(nato)",
                    "component_id": "france_national",
                    "source_side": "nato",
                    "tactical_side": "nato",
                    "period": "2022s",
                    "virtual": False,
                    "members": {"fj_eng": 4},
                    "vehicles": [],
                }
            ],
        }
        rows, body = project_actor_inf_cost_rows(actor, self.layers)
        self.assertEqual(1, len(rows))
        self.assertEqual("mp/nato/2022s/fj_engineer", rows[0].source_path)
        self.assertEqual("mp/nato/2022s/fj_eng", rows[0].target_path)
        self.assertEqual(35.5, rows[0].cost)

    def test_kor_unpriced_crew_allowed_with_priced_companions(self) -> None:
        for name in ("kor_crew", "kor_squadlead"):
            breed = self.layers[2] / f"resource/set/breed/mp/rusa/2022s/{name}.set"
            breed.parent.mkdir(parents=True, exist_ok=True)
            breed.write_text('{breed {skin "kor"}}\n', encoding="utf-8")
        self._write_inf(
            "rusa",
            '{"mp/rusa/2022s/kor_squadlead" ("rusa_spetsnaz" side(rusa)) {cost 36.0}}',
        )
        actor = {
            "actor_id": "dprk",
            "display_name": "DPRK",
            "tactical_side": "rusa",
            "units": [
                {
                    "unit_name": "kor_inf_spg",
                    "component_id": "dprk_national",
                    "source_side": "rusa",
                    "period": "2022s",
                    "members": {"kor_crew": 2, "kor_squadlead": 1},
                    "vehicles": [],
                }
            ],
        }
        rows, body = project_actor_inf_cost_rows(actor, self.layers)
        self.assertEqual(0, len(rows))
        self.assertEqual("", body)

    def test_period_fallback_projects_onto_exact_breed_path(self) -> None:
        breed = self.layers[2] / "resource/set/breed/mp/nato/era2022/fr_spotter.set"
        breed.parent.mkdir(parents=True, exist_ok=True)
        breed.write_text('{breed {skin "fr"}}\n', encoding="utf-8")
        self._write_inf(
            "nato",
            '{"mp/nato/2022s/fr_spotter" ("nato_fernspah" side(nato)) {cost 32.4}}',
        )
        actor = {
            "actor_id": "fra",
            "display_name": "France",
            "tactical_side": "nato",
            "units": [
                {
                    "unit_name": "squad_fr_recon(nato)",
                    "component_id": "france_national",
                    "source_side": "nato",
                    "period": "2022s",
                    "members": {"fr_spotter": 1},
                    "vehicles": [],
                }
            ],
        }
        rows, body = project_actor_inf_cost_rows(actor, self.layers)
        self.assertEqual(1, len(rows))
        self.assertEqual("mp/nato/2022s/fr_spotter", rows[0].source_path)
        self.assertEqual("mp/nato/era2022/fr_spotter", rows[0].target_path)
        self.assertEqual(32.4, rows[0].cost)
        self.assertIn('"mp/nato/era2022/fr_spotter"', body)



    def test_kor_allowlisted_unpriced_alone_fails_closed_even_if_not_virtual(self) -> None:
        breed = self.layers[2] / "resource/set/breed/mp/rusa/2022s/kor_saperi.set"
        breed.parent.mkdir(parents=True, exist_ok=True)
        breed.write_text('{breed {skin "kor"}}\n', encoding="utf-8")
        actor = {
            "actor_id": "dprk",
            "display_name": "DPRK",
            "tactical_side": "rusa",
            "units": [
                {
                    "unit_name": "kor_inf_saperi",
                    "component_id": "dprk_national",
                    "source_side": "rusa",
                    "period": "2022s",
                    "virtual": False,
                    "members": {"kor_saperi": 5},
                    "vehicles": [],
                }
            ],
        }
        with self.assertRaisesRegex(
            ExpandedNationsError,
            r"kor_inf_saperi.*no positive native Conquest inf cost coverage",
        ):
            project_actor_inf_cost_rows(actor, self.layers)

    def test_virtual_unit_with_unresolvable_members_fails_closed(self) -> None:
        actor = {
            "actor_id": "donbas",
            "display_name": "Donbas",
            "tactical_side": "rusa",
            "units": [
                {
                    "unit_name": "goc_missing(rusa)",
                    "component_id": "donbas_latent",
                    "source_side": "rusa",
                    "period": "2022s",
                    "virtual": True,
                    "members": {"missing_breed": 1},
                    "vehicles": [],
                }
            ],
        }
        with self.assertRaisesRegex(
            ExpandedNationsError,
            r"missing_breed|Cross-side breed source is missing",
        ):
            project_actor_inf_cost_rows(actor, self.layers)

    def test_vostok_crew_uses_same_equipment_native_authority(self) -> None:
        breed = self.layers[2] / "resource/set/breed/mp/rusa/2022s/vostok_2b14crew.set"
        breed.parent.mkdir(parents=True, exist_ok=True)
        breed.write_text('{breed {skin "vostok"}}\n', encoding="utf-8")
        self._write_inf(
            "rusa",
            '{"mp/rusa/2022s/rus114_rez_2b14crew" ("rusa_radioman" side(rusa)) {cost 136.5}}',
        )
        actor = {
            "actor_id": "donbas",
            "display_name": "Donbas",
            "tactical_side": "rusa",
            "units": [
                {
                    "unit_name": "goc_vostok_mortar(rusa)",
                    "component_id": "donbas_latent",
                    "source_side": "rusa",
                    "period": "2022s",
                    "virtual": True,
                    "members": {"vostok_2b14crew": 2},
                    "vehicles": [],
                }
            ],
        }
        rows, body = project_actor_inf_cost_rows(actor, self.layers)
        self.assertEqual(1, len(rows))
        self.assertEqual("mp/rusa/2022s/rus114_rez_2b14crew", rows[0].source_path)
        self.assertEqual("mp/rusa/2022s/vostok_2b14crew", rows[0].target_path)
        self.assertEqual(136.5, rows[0].cost)


if __name__ == "__main__":
    unittest.main()
