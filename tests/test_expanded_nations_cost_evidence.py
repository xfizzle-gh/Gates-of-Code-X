from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations_cost_evidence import (
    _build_vehicle_cost_index,
    _evaluate_unit_cost,
    _lookup_vehicle_cost,
    render_cost_evidence_markdown,
)
from gates_of_codex.expanded_nations_inf_costs import _build_effective_inf_index
from gates_of_codex.expanded_nations_models import ExpandedNationsError
from gates_of_codex.goh_source import scan_source_entries


class ExpandedNationsCostEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.layers = [self.root / name for name in ("vanilla", "west81", "codex", "ai", "gates")]
        for layer in self.layers:
            (layer / "resource").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _index(self):
        return _build_effective_inf_index(self.layers)

    def _eval(self, raw: str, *, side: str = "rusa", vehicle_costs=None, conflicts=None):
        entry = scan_source_entries(raw + "\n", "t").entries[0]
        return _evaluate_unit_cost(
            entry_name=entry.name,
            entry_raw=entry.raw,
            entry_form=entry.form,
            entry_calls=entry.calls,
            unit_meta=None,
            tactical_side=side,
            roots=self.layers,
            index=self._index(),
            vehicle_costs=vehicle_costs or {},
            vehicle_conflicts=conflicts or {},
        )

    def test_vehicle_entity_cost_not_crew_only(self) -> None:
        units = self.layers[2] / "resource/set/multiplayer/units/conquest/units_rusa.set"
        units.parent.mkdir(parents=True)
        units.write_text(
            '{"t72b_rus"\n'
            '\t("vehicle" side(rusa) crew(rus_vehicleman:3) cp(19))\n'
            "\t{cost 1150}\n"
            "}\n",
            encoding="utf-8",
        )
        breed = self.layers[2] / "resource/set/breed/mp/rusa/2022s/rus_vehicleman.set"
        breed.parent.mkdir(parents=True)
        breed.write_text('{breed {skin "x"}}\n', encoding="utf-8")
        inf = self.layers[2] / "resource/set/multiplayer/units/conquest/inf_rusa.set"
        inf.write_text(
            '{"mp/rusa/2022s/rus_vehicleman" ("rusa_crew" side(rusa)) {cost 10.0}}\n',
            encoding="utf-8",
        )
        vc, conf = _build_vehicle_cost_index(self.layers)
        self.assertEqual(1150.0, vc["t72b_rus"])
        raw = (
            '{"squad_rus90_t72b(rusa)"\n'
            '\t("squad_vehicle" side(rusa) vehicle(t72b_rus) cw(0) cp(4) '
            "crew(rus_vehicleman:3))\n"
            "}"
        )
        ev = self._eval(raw, vehicle_costs=vc, conflicts=conf)
        self.assertEqual("vehicle_entity_cost", ev.economy_class)
        self.assertEqual(1150.0, ev.native_recruitment_cost)
        self.assertEqual(30.0, ev.personnel_cost)
        self.assertEqual(4.0, ev.cp)
        self.assertFalse(ev.zero_cost)

    def test_vehicle_without_money_cost_is_unpriced_even_with_crew_and_cp(self) -> None:
        breed = self.layers[2] / "resource/set/breed/mp/rusa/2022s/rus_vehicleman.set"
        breed.parent.mkdir(parents=True)
        breed.write_text('{breed {skin "x"}}\n', encoding="utf-8")
        inf = self.layers[2] / "resource/set/multiplayer/units/conquest/inf_rusa.set"
        inf.parent.mkdir(parents=True)
        inf.write_text(
            '{"mp/rusa/2022s/rus_vehicleman" ("rusa_crew" side(rusa)) {cost 10.0}}\n',
            encoding="utf-8",
        )
        raw = (
            '{"squad_missing_tank(rusa)"\n'
            '\t("squad_vehicle" side(rusa) vehicle(missing_tank) cw(0) cp(4) '
            "crew(rus_vehicleman:3))\n"
            "}"
        )
        ev = self._eval(raw, vehicle_costs={}, conflicts={})
        self.assertEqual("vehicle_unpriced", ev.economy_class)
        self.assertEqual(0.0, ev.native_recruitment_cost)
        self.assertEqual(30.0, ev.personnel_cost)
        self.assertEqual(4.0, ev.cp)
        self.assertTrue(ev.zero_cost)
        self.assertFalse(ev.intentional_zero)

    def test_cp_and_special_points_are_not_recruitment_money(self) -> None:
        raw = (
            '{"mortar_barrage_light_prc"\n'
            '\t("offmap_support" side(prc) cw(0) cp(0) vehicle(82mm) crew(sup_guncrew:0))\n'
            '\t{cost_sp 1}{action "airstrike:flare_mortar_80"}\n'
            "}"
        )
        ev = self._eval(raw, side="prc", vehicle_costs={}, conflicts={})
        self.assertEqual("offmap_special_points", ev.economy_class)
        self.assertIsNone(ev.native_recruitment_cost)
        self.assertEqual(1.0, ev.special_points_cost)
        self.assertFalse(ev.zero_cost)

    def test_vehicle_same_priority_conflict_fails_closed_when_requested(self) -> None:
        units = self.layers[2] / "resource/set/multiplayer/units/conquest/units_rusa.set"
        units.parent.mkdir(parents=True)
        units.write_text(
            '{"dup_tank"\n\t("vehicle" side(rusa))\n\t{cost 100}\n}\n'
            '{"dup_tank"\n\t("vehicle" side(rusa))\n\t{cost 200}\n}\n',
            encoding="utf-8",
        )
        vc, conf = _build_vehicle_cost_index(self.layers)
        self.assertNotIn("dup_tank", vc)
        self.assertIn("dup_tank", conf)
        with self.assertRaisesRegex(ExpandedNationsError, r"Conflicting native vehicle cost"):
            _lookup_vehicle_cost(vc, conf, "dup_tank")

    def test_markdown_renderer_includes_summary_table(self) -> None:
        md = render_cost_evidence_markdown(
            {
                "schema": "gates-of-codex.expanded-nations-cost-evidence",
                "schema_version": 2,
                "evidence_state": "complete",
                "source_head": "abc",
                "playable_actor_count": 1,
                "unintended_zero_total": 0,
                "unintended_zeros": [],
                "actors": {
                    "srb": {
                        "tactical_side": "rusa",
                        "unit_count": 18,
                        "projected_inf_cost_row_count": 0,
                        "native_recruitment_cost_min": 60.0,
                        "native_recruitment_cost_median": 400.0,
                        "native_recruitment_cost_max": 1100.0,
                        "unintended_zero_count": 0,
                        "intentional_zero_count": 0,
                    }
                },
            }
        )
        self.assertIn("| srb |", md)
        self.assertIn("unintended_zero_total: 0", md)
        self.assertIn("never counted as recruitment money", md)



    def test_purchase_text_not_wiring_meta_decides_vehicle(self) -> None:
        breed = self.layers[2] / "resource/set/breed/mp/nato/2022s/usmc_rifleman.set"
        breed.parent.mkdir(parents=True, exist_ok=True)
        breed.write_text('{breed {skin "x"}}\n', encoding="utf-8")
        inf = self.layers[2] / "resource/set/multiplayer/units/conquest/inf_nato.set"
        inf.parent.mkdir(parents=True, exist_ok=True)
        inf.write_text(
            '{"mp/nato/2022s/usmc_rifleman" ("nato_basic" side(nato)) {cost 17.5}}\n',
            encoding="utf-8",
        )
        raw = (
            '{"squad_usmc_rifle(nato)"\n'
            '\t("mp_infantry_1" side(nato) c1(usmc_rifleman:5))\n'
            '}'
        )
        entry = scan_source_entries(raw + "\n", "t").entries[0]
        ev = _evaluate_unit_cost(
            entry_name=entry.name,
            entry_raw=entry.raw,
            entry_form=entry.form,
            entry_calls=entry.calls,
            unit_meta={"vehicles": ["MAARS"], "members": {"usmc_rifleman": 5}},
            tactical_side="nato",
            roots=self.layers,
            index=self._index(),
            vehicle_costs={},
            vehicle_conflicts={},
        )
        self.assertEqual("personnel_inf_sum", ev.economy_class)
        self.assertEqual(87.5, ev.native_recruitment_cost)
        self.assertFalse(ev.has_vehicle)


    def test_vehicle2_entity_form_is_indexed(self) -> None:
        units = self.layers[2] / "resource/set/multiplayer/units/conquest/units_rusa.set"
        units.parent.mkdir(parents=True)
        units.write_text(
            '{"t80uk"\n'
            '\t("vehicle2" side(rusa) crew1(rus_vehicleman_cmd:1) crew2(rus_vehicleman:2))\n'
            '\t{cost 1950} {not_for_player_sale 1}\n'
            '}\n',
            encoding="utf-8",
        )
        vc, conf = _build_vehicle_cost_index(self.layers)
        self.assertEqual(1950.0, vc["t80uk"])
        raw = (
            '{"squad_rus4_t80uk(rusa)"\n'
            '\t("squad_vehicle" side(rusa) vehicle(t80uk) cw(0) cp(4) crew(rus_vehicleman:3))\n'
            '}'
        )
        breed = self.layers[2] / "resource/set/breed/mp/rusa/2022s/rus_vehicleman.set"
        breed.parent.mkdir(parents=True, exist_ok=True)
        breed.write_text('{breed {skin "x"}}\n', encoding="utf-8")
        inf = self.layers[2] / "resource/set/multiplayer/units/conquest/inf_rusa.set"
        inf.parent.mkdir(parents=True, exist_ok=True)
        inf.write_text(
            '{"mp/rusa/2022s/rus_vehicleman" ("rusa_crew" side(rusa)) {cost 10.0}}\n',
            encoding="utf-8",
        )
        ev = self._eval(raw, vehicle_costs=vc, conflicts=conf)
        self.assertEqual("vehicle_entity_cost", ev.economy_class)
        self.assertEqual(1950.0, ev.native_recruitment_cost)

if __name__ == "__main__":
    unittest.main()
