from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations_actor_sources import (
    normalize_actor_purchase_ids,
    project_actor_units,
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

    def test_verification_view_authenticates_effective_macro_id(self) -> None:
        actor_text = (
            "; generated\n"
            '("squad_with1types_conquest" side(rusa) period(2022s) '
            'min_stage(1) max_stage(99) name(goc_serb_rifle) '
            'c1(Serb_rifleman:4))\n'
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
