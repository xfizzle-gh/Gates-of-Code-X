from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations_actor_sources import (
    normalize_actor_purchase_ids,
    project_actor_units,
    scan_parenthesized_defines,
)
from gates_of_codex.expanded_nations_models import (
    ExpandedNationsError,
    UNITS_RELATIVE,
)
from gates_of_codex.expanded_nations_native_verify import _legacy_verification_view
from gates_of_codex.expanded_nations_render import project_research_nodes
from gates_of_codex.goh_source import scan_source_entries


class ExpandedNationsNativeSquadIdTests(unittest.TestCase):
    def test_committed_virtual_wrappers_are_top_level_native_macros(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = (
            root
            / "resource/set/multiplayer/units/conquest/units_goc_national_wrappers.set"
        )
        scan = scan_source_entries(path.read_text(encoding="utf-8"), str(path))
        self.assertFalse(scan.diagnostics)
        expected = {
            "goc_ildu_rifle",
            "goc_ildu_at",
            "goc_ildu_javelin",
            "goc_ildu_recon",
            "goc_ildu_engineer",
            "goc_ildu_manpads",
            "goc_sparta_rifle",
            "goc_sparta_recon",
            "goc_vostok_rifle",
            "goc_vostok_mortar",
            "goc_vostok_spg9",
            "goc_serb_rifle",
            "goc_serb_at",
            "goc_serb_recon",
        }
        self.assertEqual(expected, {entry.name for entry in scan.entries})
        for entry in scan.entries:
            self.assertEqual("macro", entry.form)
            self.assertTrue(entry.macro_kind.lower().startswith("squad_with"))

    def test_serbia_virtual_squad_projects_base_macro_and_effective_id(self) -> None:
        root = Path(__file__).resolve().parents[1]
        actor = {
            "actor_id": "srb",
            "tactical_side": "rusa",
            "units": [
                {
                    "unit_name": "goc_serb_rifle(rusa)",
                    "tactical_side": "rusa",
                    "source_side": "rusa",
                    "materializable": True,
                    "virtual": True,
                    "source_files": [],
                }
            ],
        }
        projected, body = project_actor_units(actor, [root], root)
        self.assertEqual(1, len(projected))
        self.assertEqual("goc_serb_rifle(rusa)", projected[0].unit_name)
        self.assertEqual("goc_serb_rifle", projected[0].source_entry_name)
        self.assertIn("name(goc_serb_rifle)", body)
        self.assertNotIn('{\"goc_serb_rifle(rusa)\"', body)
        generated = scan_source_entries(body, "generated").entries
        self.assertEqual(1, len(generated))
        self.assertEqual("macro", generated[0].form)
        self.assertEqual("goc_serb_rifle", generated[0].name)

    def test_upstream_macro_projection_normalizes_catalog_and_research_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "stack"
            source = root / "resource/set/multiplayer/units/conquest/fixture.set"
            source.parent.mkdir(parents=True)
            source.write_text(
                '("squad_with1types_conquest" side(rusa) period(2022s) '
                'min_stage(1) max_stage(99) name(fixture_rifle) '
                'c1(rus_rifleman:4))\n',
                encoding="utf-8",
            )
            actor = {
                "actor_id": "fixture",
                "tactical_side": "rusa",
                "unit_count": 1,
                "units": [
                    {
                        "unit_name": "fixture_rifle",
                        "tactical_side": "rusa",
                        "source_side": "rusa",
                        "source_priority": 0,
                        "materializable": True,
                        "virtual": False,
                        "source_files": [
                            "0:stack/set/multiplayer/units/conquest/fixture.set"
                        ],
                    }
                ],
                "research_nodes": [
                    {
                        "key": "actor:fixture:unit",
                        "cost": 1,
                        "prerequisites": [],
                        "unlock_units": ["fixture_rifle"],
                    }
                ],
            }
            projected, body = project_actor_units(actor, [root], root)
            self.assertEqual("fixture_rifle(rusa)", projected[0].unit_name)
            self.assertIn("name(fixture_rifle)", body)
            self.assertNotIn("name(fixture_rifle(rusa))", body)

            normalized = normalize_actor_purchase_ids(actor, projected)
            self.assertEqual(
                "fixture_rifle(rusa)",
                normalized["units"][0]["unit_name"],
            )
            research = project_research_nodes(normalized)
            self.assertEqual("fixture_rifle(rusa)", research[0].engine_id)
            self.assertEqual("fixture_rifle(rusa)", research[0].unlock_unit)

    def test_parenthesized_cross_file_define_closure_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "stack"
            doctrine = root / "resource/set/multiplayer/units/2022s"
            conquest = root / "resource/set/multiplayer/units/conquest"
            doctrine.mkdir(parents=True)
            conquest.mkdir(parents=True)
            (conquest / "settings.set").write_text(
                '(define "squad_with1types_conquest" {content "%c1"})\n',
                encoding="utf-8",
            )
            (doctrine / "doctrine_settings.set").write_text(
                '(define "generic_dp_unit"\n'
                '    {button "doctrine"}\n'
                ')\n'
                '(define "dp_infantry_8"\n'
                '    ("generic_dp_unit" t(%side %period))\n'
                '    {content "mp/%side/%period/%c1"}\n'
                ')\n'
                '(define "doctrine_t1"\n'
                '    {cost %cost}\n'
                ')\n',
                encoding="utf-8",
            )
            purchase = doctrine / "doctrine_units_rusa.set"
            purchase.write_text(
                '{"rus155_inf_rpg28(rusa)"\n'
                '    ("dp_infantry_8" side(rusa) period(2022s) '
                'c1(rus155_squadlead:1) c2(rus155_rifleman:7))\n'
                '    ("doctrine_t1" cool(180) d(modern_rusa_vdv) cost(3))\n'
                '}\n',
                encoding="utf-8",
            )
            actor = {
                "actor_id": "fixture",
                "tactical_side": "rusa",
                "units": [
                    {
                        "unit_name": "rus155_inf_rpg28(rusa)",
                        "tactical_side": "rusa",
                        "source_side": "rusa",
                        "source_priority": 0,
                        "materializable": True,
                        "virtual": False,
                        "source_files": [
                            "0:stack/set/multiplayer/units/2022s/"
                            "doctrine_units_rusa.set"
                        ],
                    }
                ],
            }
            projected, body = project_actor_units(actor, [root], root)
            self.assertEqual(1, len(projected))
            self.assertEqual("rus155_inf_rpg28(rusa)", projected[0].unit_name)
            self.assertLess(
                body.index('(define "generic_dp_unit"'),
                body.index('(define "dp_infantry_8"'),
            )
            self.assertLess(
                body.index('(define "dp_infantry_8"'),
                body.index('{"rus155_inf_rpg28(rusa)"'),
            )
            self.assertLess(
                body.index('(define "doctrine_t1"'),
                body.index('{"rus155_inf_rpg28(rusa)"'),
            )
            self.assertEqual(
                ["generic_dp_unit", "dp_infantry_8", "doctrine_t1"],
                [
                    row.name
                    for row in scan_parenthesized_defines(body, "generated")
                ],
            )
            scan = scan_source_entries(body, "generated")
            self.assertFalse(scan.diagnostics)
            self.assertEqual(
                ["rus155_inf_rpg28(rusa)"],
                [entry.name for entry in scan.entries],
            )

            actor_text = body.encode("utf-8")
            manifest = {
                "tactical_side": "rusa",
                "units": [{"unit_name": "rus155_inf_rpg28(rusa)"}],
                "files": [
                    {
                        "relative_path": UNITS_RELATIVE.as_posix(),
                        "sha256": "fixture",
                        "byte_count": len(actor_text),
                    }
                ],
            }
            outputs, normalized = _legacy_verification_view(
                {UNITS_RELATIVE: actor_text},
                manifest,
            )
            transformed = outputs[UNITS_RELATIVE].decode("utf-8")
            self.assertIn('(define "dp_infantry_8"', transformed)
            self.assertIn('{"rus155_inf_rpg28(rusa)"', transformed)
            self.assertEqual(1, len(normalized["units"]))

    def test_conflicting_effective_parenthesized_defines_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "stack"
            units = root / "resource/set/multiplayer/units"
            doctrine = units / "2022s"
            doctrine.mkdir(parents=True)
            (doctrine / "a_settings.set").write_text(
                '(define "dp_infantry_8" {content "a"})\n',
                encoding="utf-8",
            )
            (doctrine / "b_settings.set").write_text(
                '(define "dp_infantry_8" {content "b"})\n',
                encoding="utf-8",
            )
            (doctrine / "doctrine_units_rusa.set").write_text(
                '{"fixture(rusa)" '
                '("dp_infantry_8" side(rusa) c1(a:8))}\n',
                encoding="utf-8",
            )
            actor = {
                "actor_id": "fixture",
                "tactical_side": "rusa",
                "units": [
                    {
                        "unit_name": "fixture(rusa)",
                        "tactical_side": "rusa",
                        "source_side": "rusa",
                        "source_priority": 0,
                        "materializable": True,
                        "virtual": False,
                        "source_files": [
                            "0:stack/set/multiplayer/units/2022s/"
                            "doctrine_units_rusa.set"
                        ],
                    }
                ],
            }
            with self.assertRaisesRegex(
                ExpandedNationsError,
                "conflicting bodies",
            ):
                project_actor_units(actor, [root], root)

    def test_verification_rejects_missing_required_parenthesized_define(self) -> None:
        actor_text = (
            '{"rus155_inf_rpg28(rusa)"\n'
            '    ("dp_infantry_8" side(rusa) period(2022s) '
            'c1(rus155_squadlead:1))\n'
            '}\n'
        ).encode("utf-8")
        manifest = {
            "tactical_side": "rusa",
            "units": [{"unit_name": "rus155_inf_rpg28(rusa)"}],
            "files": [
                {
                    "relative_path": UNITS_RELATIVE.as_posix(),
                    "sha256": "fixture",
                    "byte_count": len(actor_text),
                }
            ],
        }
        with self.assertRaisesRegex(
            ExpandedNationsError,
            "missing required define 'dp_infantry_8'",
        ):
            _legacy_verification_view(
                {UNITS_RELATIVE: actor_text},
                manifest,
            )

    def test_verification_view_authenticates_effective_macro_id(self) -> None:
        actor_text = (
            "; generated\n"
            '("squad_with1types_conquest" side(rusa) period(2022s) '
            "min_stage(1) max_stage(99) name(goc_serb_rifle) "
            "c1(Serb_rifleman:4))\n"
        ).encode("utf-8")
        manifest = {
            "tactical_side": "rusa",
            "units": [{"unit_name": "goc_serb_rifle(rusa)"}],
            "files": [
                {
                    "relative_path": UNITS_RELATIVE.as_posix(),
                    "sha256": "stale-for-fixture",
                    "byte_count": len(actor_text),
                }
            ],
        }
        outputs, normalized = _legacy_verification_view(
            {UNITS_RELATIVE: actor_text},
            manifest,
        )
        transformed = outputs[UNITS_RELATIVE].decode("utf-8")
        self.assertIn("name(goc_serb_rifle(rusa))", transformed)
        self.assertNotEqual(
            "stale-for-fixture",
            normalized["files"][0]["sha256"],
        )

        bad_manifest = {
            **manifest,
            "units": [{"unit_name": "goc_serb_rifle(ukr)"}],
        }
        with self.assertRaises(ExpandedNationsError):
            _legacy_verification_view(
                {UNITS_RELATIVE: actor_text},
                bad_manifest,
            )


if __name__ == "__main__":
    unittest.main()
