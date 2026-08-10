from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations_cost_evidence import (
    _build_vehicle_cost_index,
    _evaluate_unit_cost,
    render_cost_evidence_markdown,
)
from gates_of_codex.expanded_nations_inf_costs import _build_effective_inf_index
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

    def test_vehicle_entity_and_offmap_cost_classification(self) -> None:
        units = self.layers[2] / "resource/set/multiplayer/units/conquest/units_ukr.set"
        units.parent.mkdir(parents=True)
        units.write_text(
            '{"ugv_mine" ("vehicle" side(ukr)) {cost 150}}\n'
            '{"mortar_barrage_light_prc"\n'
            '\t("offmap_support" side(prc) cw(0) cp(0) vehicle(82mm) crew(sup_guncrew:0))\n'
            '\t{cost_sp 1}{action "airstrike:flare_mortar_80"}\n'
            "}\n",
            encoding="utf-8",
        )
        vehicle_costs = _build_vehicle_cost_index(self.layers)
        self.assertEqual(150.0, vehicle_costs["ugv_mine"])

        index = _build_effective_inf_index(self.layers)
        ugv_raw = (
            '("squad_with2types_0vehicle" side(ukr) name(squad_nc13_ugv_mine) '
            "c1(azov3_sup:0) c2(azov3_sup:0)vehicle(ugv_mine))"
        )
        ugv = scan_source_entries(ugv_raw + "\n", "t").entries[0]
        ugv_ev = _evaluate_unit_cost(
            entry_name=ugv.name,
            entry_raw=ugv.raw,
            entry_form=ugv.form,
            entry_calls=ugv.calls,
            unit_meta=None,
            tactical_side="ukr",
            roots=self.layers,
            index=index,
            vehicle_costs=vehicle_costs,
        )
        self.assertEqual("vehicle_entity_cost", ugv_ev.economy_class)
        self.assertEqual(150.0, ugv_ev.native_recruitment_cost)
        self.assertFalse(ugv_ev.zero_cost)

        off_raw = (
            '{"mortar_barrage_light_prc"\n'
            '\t("offmap_support" side(prc) cw(0) cp(0) vehicle(82mm) crew(sup_guncrew:0))\n'
            '\t{cost_sp 1}{action "airstrike:flare_mortar_80"}\n'
            "}"
        )
        off = scan_source_entries(off_raw + "\n", "t").entries[0]
        off_ev = _evaluate_unit_cost(
            entry_name=off.name,
            entry_raw=off.raw,
            entry_form=off.form,
            entry_calls=off.calls,
            unit_meta=None,
            tactical_side="prc",
            roots=self.layers,
            index=index,
            vehicle_costs=vehicle_costs,
        )
        self.assertEqual("special_points_cost", off_ev.economy_class)
        self.assertEqual(1.0, off_ev.native_recruitment_cost)
        self.assertFalse(off_ev.zero_cost)

    def test_markdown_renderer_includes_summary_table(self) -> None:
        md = render_cost_evidence_markdown(
            {
                "schema": "gates-of-codex.expanded-nations-cost-evidence",
                "schema_version": 1,
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


if __name__ == "__main__":
    unittest.main()
