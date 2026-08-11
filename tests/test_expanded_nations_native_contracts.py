from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations_models import (
    PORTRAIT_ROOT_RELATIVE,
    SPAIN_PRESENTATION_UNITS,
)
from gates_of_codex.expanded_nations_opponent_render import project_opponent_units
from gates_of_codex.expanded_nations_presentation import project_actor_presentation
from gates_of_codex.expanded_nations_render import project_research_nodes
from gates_of_codex.expanded_nations_sources import _project_source_raw
from gates_of_codex.expanded_nations_models import ExpandedNationsError


class ExpandedNationsNativeContractTests(unittest.TestCase):
    def test_rusa_replacement_excludes_legacy_red_family(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layers = [root / name for name in ("vanilla", "west81", "codex", "ai", "gates")]
            for layer in layers:
                (layer / "resource").mkdir(parents=True)
            self._roster(
                layers[2],
                "units_sov_era1960.set",
                '{"legacy_sov(sov)" ("squad_with1types_conquest" side(sov) c1(sov_rifle:1))}\n',
            )
            self._roster(
                layers[2],
                "units_nato.set",
                '{"legacy_nato(nato)" ("squad_with1types_conquest" side(nato) c1(nato_rifle:1))}\n',
            )
            self._roster(
                layers[2],
                "units_csa_era1960.set",
                '{"legacy_frg(frg)" ("squad_with1types_conquest" side(csa) c1(frg_rifle:1))}\n',
            )
            rows, body = project_opponent_units("rusa", layers)
            names = {row.entry_name for row in rows}
            self.assertNotIn("legacy_sov(sov)", names)
            self.assertIn("legacy_nato(nato)", names)
            self.assertIn("legacy_frg(frg)", names)
            self.assertNotIn("legacy_sov(sov)", body)

    def test_soviet_vehicle_is_normalized_to_native_rusa_contract(self) -> None:
        source = (
            '{"t72b" ("vehicle" side(sov) period(era1960) '
            'vehicle(t72b) crew(sup_tankman:3))}'
        )
        projected = _project_source_raw(
            source,
            unit_name="t72b",
            source_side="sov",
            target_side="rusa",
        )
        self.assertIn("side(rusa)", projected)
        self.assertIn("period(2022s)", projected)
        self.assertIn("crew(rus_vehicleman:3)", projected)
        self.assertNotIn("sup_tankman", projected)
        self.assertNotIn("era1960", projected)

    def test_native_research_contains_purchase_nodes_only(self) -> None:
        actor = {
            "actor_id": "fixture",
            "unit_count": 2,
            "units": [
                {"unit_name": "fixture_a(rusa)"},
                {"unit_name": "fixture_b(rusa)"},
            ],
            "research_nodes": [
                {
                    "key": "actor:fixture:root",
                    "cost": 2,
                    "prerequisites": [],
                    "unlock_units": [],
                },
                {
                    "key": "actor:fixture:branch",
                    "cost": 3,
                    "prerequisites": ["actor:fixture:root"],
                    "unlock_units": [],
                },
                {
                    "key": "actor:fixture:a",
                    "cost": 1,
                    "prerequisites": ["actor:fixture:branch"],
                    "unlock_units": ["fixture_a(rusa)"],
                },
                {
                    "key": "actor:fixture:b",
                    "cost": 4,
                    "prerequisites": ["actor:fixture:a"],
                    "unlock_units": ["fixture_b(rusa)"],
                },
            ],
        }
        projected = project_research_nodes(actor)
        self.assertEqual(
            ["fixture_a(rusa)", "fixture_b(rusa)"],
            [row.engine_id for row in projected],
        )
        self.assertTrue(all(row.unlock_unit is not None for row in projected))
        self.assertEqual("", projected[0].required_engine_id)
        self.assertEqual("fixture_a(rusa)", projected[1].required_engine_id)
        self.assertEqual(6, projected[0].cost)
        self.assertEqual(4, projected[1].cost)
        self.assertEqual(10, sum(row.cost for row in projected))

    def test_serbia_portraits_are_copied_from_installed_codex(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layers = [root / name for name in ("vanilla", "west81", "codex", "ai", "gates")]
            for layer in layers:
                (layer / "resource").mkdir(parents=True)
            portrait_root = layers[2] / "resource/interface/scene/portrait_squad"
            portrait_root.mkdir(parents=True)
            png = b"\x89PNG\r\n\x1a\nfixture"
            for source in ("rus4_inf_rifle", "rus4_inf_rifle_at", "rus4_inf_razv"):
                for index in range(4):
                    (portrait_root / f"{source}_{index:02d}.png").write_bytes(
                        png + bytes([index])
                    )
            actor = {
                "actor_id": "srb",
                "units": [
                    {"unit_name": "goc_serb_rifle(rusa)"},
                    {"unit_name": "goc_serb_at(rusa)"},
                    {"unit_name": "goc_serb_recon(rusa)"},
                ],
            }
            outputs = project_actor_presentation(actor, layers)
            self.assertEqual(12, len(outputs))
            expected = PORTRAIT_ROOT_RELATIVE / "goc_serb_rifle(rusa)_00.png"
            self.assertIn(expected, outputs)
            self.assertTrue(outputs[expected].startswith(b"\x89PNG"))

    def test_spain_3rd_assault_portraits_are_copied_from_ukraine_source_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layers = [root / name for name in ("vanilla", "west81", "codex", "ai", "gates")]
            for layer in layers:
                (layer / "resource").mkdir(parents=True)
            portrait_root = layers[2] / "resource/interface/scene/portrait_squad"
            portrait_root.mkdir(parents=True)
            png = b"\x89PNG\r\n\x1a\nspain"
            for target in SPAIN_PRESENTATION_UNITS:
                source = target.replace("(nato)", "(ukr)")
                for index in range(4):
                    (portrait_root / f"{source}_{index:02d}.png").write_bytes(
                        png + target.encode("utf-8") + bytes([index])
                    )
            actor = {
                "actor_id": "esp",
                "units": [{"unit_name": unit} for unit in SPAIN_PRESENTATION_UNITS],
            }

            outputs = project_actor_presentation(actor, layers)

            self.assertEqual(24, len(outputs))
            expected = PORTRAIT_ROOT_RELATIVE / "3rd_assault_mg3(nato)_00.png"
            self.assertIn(expected, outputs)
            self.assertTrue(outputs[expected].startswith(b"\x89PNG"))
            self.assertFalse(any("(ukr)" in path.name for path in outputs))

    def test_spain_presentation_fails_closed_on_partial_projected_family(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layers = [root / name for name in ("vanilla", "west81", "codex", "ai", "gates")]
            for layer in layers:
                (layer / "resource").mkdir(parents=True)
            actor = {
                "actor_id": "esp",
                "units": [{"unit_name": SPAIN_PRESENTATION_UNITS[0]}],
            }
            with self.assertRaisesRegex(
                ExpandedNationsError,
                "Spain presentation requires all canonical projected card families",
            ):
                project_actor_presentation(actor, layers)

    def test_expanded_nations_squad_localization_is_committed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = (
            root
            / "localizations/default/interface/text/desc/desc_squad_goc_expanded_nations.pot"
        )
        text = path.read_text(encoding="utf-8")
        for unit in (
            "goc_serb_rifle(rusa)",
            "goc_serb_at(rusa)",
            "goc_serb_recon(rusa)",
        ):
            self.assertIn(f'msgctxt "desc/squad/{unit}"', text)

        expected_spain = {
            "3rd_assault_at(nato)": "3-я OShBr SHTURMOVYKY[RPG-7]",
            "3rd_assault_decepticons(nato)": "3-я OShBr SPETSPIDROZDIL ”Decepticons”",
            "3rd_assault_javelin(nato)": "3-я OShBr SHTURMOVYKY[JAVELIN]",
            "3rd_assault_mg3(nato)": "3-я OShBr SHTURMOVYKY[MG3]",
            "3rd_assault_saperi(nato)": "3-я OShBr SAPERI",
            "3rd_assault_saperi_at(nato)": "3-я OShBr SAPERI[RSHG-2]",
        }
        for unit, label in expected_spain.items():
            self.assertIn(f'msgctxt "desc/squad/{unit}"', text)
            self.assertIn(f'msgid  "{label}"', text)

        ignore = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(
            "/resource/interface/scene/portrait_squad/goc_serb_*.png",
            ignore,
        )
        self.assertIn(
            "/resource/interface/scene/portrait_squad/3rd_assault_*(nato)_*.png",
            ignore,
        )

    @staticmethod
    def _roster(layer: Path, name: str, text: str) -> None:
        path = layer / "resource/set/multiplayer/units/conquest" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
