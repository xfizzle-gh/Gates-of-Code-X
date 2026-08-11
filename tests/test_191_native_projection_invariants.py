"""Regression coverage for #191 native Dynamic Conquest projection invariants."""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations_breeds import project_actor_breed_files
from gates_of_codex.expanded_nations_inf_costs import project_actor_inf_cost_rows
from gates_of_codex.expanded_nations_models import GENERATED_MARKER
from gates_of_codex.goc_native_dc_seam import (
    _replace_actor_breed_namespace,
    render_purchase_lua_from_actor,
)
from gates_of_codex.goc_tactical_army_registry import playable_goc_sides


_RESOLVED_UNIT_RE = re.compile(r"^;\s*resolved_unit=(.+?)\s*$", re.MULTILINE)
_LUA_PURCHASE_RE = re.compile(r'\bunit\s*=\s*"([^"]+)"')
_GOC_NODE_RE = re.compile(r"^;\s*goc-node\s+(\{.*\})\s*$", re.MULTILINE)


class NativePurchaseIdParityTests(unittest.TestCase):
    def test_ai_renderer_preserves_normalized_block_and_macro_ids(self) -> None:
        actor = {
            "tactical_side": "goc_cze",
            "units": [
                {"unit_name": "vz_77_dana", "category": "artillery"},
                {"unit_name": "squad_arf_rifle(goc_cze)", "category": "infantry"},
            ],
        }
        lua = render_purchase_lua_from_actor(actor)
        self.assertIn('unit = "vz_77_dana"', lua)
        self.assertNotIn('unit = "vz_77_dana(goc_cze)"', lua)
        self.assertIn('unit = "squad_arf_rifle(goc_cze)"', lua)

    def test_committed_units_research_and_ai_ids_match_exactly(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for side in playable_goc_sides():
            units_text = (
                root
                / "resource/set/multiplayer/units/conquest"
                / f"units_{side}.set"
            ).read_text(encoding="utf-8")
            research_text = (
                root
                / "resource/set/dynamic_campaign"
                / f"unit_research_{side}.set"
            ).read_text(encoding="utf-8")
            lua_text = (
                root
                / "resource/script/multiplayer/units"
                / side
                / f"conquest.{side}.lua"
            ).read_text(encoding="utf-8")

            unit_ids = set(_RESOLVED_UNIT_RE.findall(units_text))
            research_ids = {
                str(json.loads(raw)["engine_id"])
                for raw in _GOC_NODE_RE.findall(research_text)
            }
            lua_ids = set(_LUA_PURCHASE_RE.findall(lua_text))

            self.assertTrue(unit_ids, side)
            self.assertEqual(unit_ids, research_ids, side)
            self.assertEqual(unit_ids, lua_ids, side)

    def test_czech_dana_stays_bare_across_native_surfaces(self) -> None:
        root = Path(__file__).resolve().parents[1]
        units = (
            root / "resource/set/multiplayer/units/conquest/units_goc_cze.set"
        ).read_text(encoding="utf-8")
        research = (
            root / "resource/set/dynamic_campaign/unit_research_goc_cze.set"
        ).read_text(encoding="utf-8")
        lua = (
            root / "resource/script/multiplayer/units/goc_cze/conquest.goc_cze.lua"
        ).read_text(encoding="utf-8")

        self.assertIn("; resolved_unit=vz_77_dana", units)
        self.assertIn('"engine_id":"vz_77_dana"', research)
        self.assertIn('unit = "vz_77_dana"', lua)
        self.assertNotIn("vz_77_dana(goc_cze)", lua)


class CrossSideBreedNamespaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        breed_root = self.source / "resource/set/breed/mp/nato/2022s"
        breed_root.mkdir(parents=True)
        (breed_root / "shared.inc").write_text("; shared include\n", encoding="utf-8")
        (breed_root / "nato_rifleman.set").write_text(
            '(include "shared.inc")\n{breed}\n',
            encoding="utf-8",
        )
        conquest = self.source / "resource/set/multiplayer/units/conquest"
        conquest.mkdir(parents=True)
        (conquest / "inf_nato.set").write_text(
            '{"mp/nato/2022s/nato_rifleman" ("nato_rifleman" side(nato)) {cost 31.5}}\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _actor(component_id: str) -> dict[str, object]:
        return {
            "actor_id": "cze",
            "tactical_side": "goc_cze",
            "units": [
                {
                    "unit_name": "fixture(goc_cze)",
                    "component_id": component_id,
                    "source_side": "nato",
                    "period": "2022s",
                    "members": {"nato_rifleman": 1},
                    "virtual": False,
                }
            ],
        }

    def test_191_approved_components_materialize_goc_breed_namespace(self) -> None:
        for component in (
            "nato_full_fallback",
            "nato_common_infantry_bridge",
            "cze_equipment_identity",
            "svk_equipment_identity",
        ):
            with self.subTest(component=component):
                outputs = project_actor_breed_files(self._actor(component), [self.source])
                self.assertIn(
                    Path("resource/set/breed/mp/goc_cze/2022s/nato_rifleman.set"),
                    outputs,
                )
                self.assertIn(
                    Path("resource/set/breed/mp/goc_cze/2022s/shared.inc"),
                    outputs,
                )
                rendered = outputs[
                    Path("resource/set/breed/mp/goc_cze/2022s/nato_rifleman.set")
                ].decode("utf-8")
                self.assertIn(GENERATED_MARKER, rendered)
                self.assertIn("cross-side-breed-source=nato/2022s/nato_rifleman.set", rendered)

    def test_unapproved_component_does_not_materialize_breeds(self) -> None:
        outputs = project_actor_breed_files(self._actor("unapproved_component"), [self.source])
        self.assertEqual(outputs, {})

    def test_191_cross_side_cost_projects_into_goc_namespace(self) -> None:
        rows, body = project_actor_inf_cost_rows(
            self._actor("nato_common_infantry_bridge"),
            [self.source],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source_path, "mp/nato/2022s/nato_rifleman")
        self.assertEqual(rows[0].target_path, "mp/goc_cze/2022s/nato_rifleman")
        self.assertEqual(rows[0].target_side, "goc_cze")
        self.assertGreater(rows[0].cost, 0)
        self.assertIn('"mp/goc_cze/2022s/nato_rifleman"', body)
        self.assertIn("side(goc_cze)", body)

    def test_materializer_replaces_only_stale_managed_breed_files(self) -> None:
        repo = self.root / "repo"
        side_root = repo / "resource/set/breed/mp/goc_cze/2022s"
        side_root.mkdir(parents=True)
        stale = side_root / "stale.set"
        stale.write_text(f"{GENERATED_MARKER}\nold\n", encoding="utf-8")
        authored = side_root / "authored.set"
        authored.write_text("{authored}\n", encoding="utf-8")

        relative = Path("resource/set/breed/mp/goc_cze/2022s/nato_rifleman.set")
        desired = {
            relative: f"{GENERATED_MARKER}\nnew\n".encode("utf-8"),
        }
        written, removed = _replace_actor_breed_namespace(repo, "goc_cze", desired)

        self.assertEqual(removed, 1)
        self.assertFalse(stale.exists())
        self.assertTrue(authored.exists())
        self.assertEqual(written, [relative.as_posix()])
        self.assertEqual((repo / relative).read_bytes(), desired[relative])


if __name__ == "__main__":
    unittest.main()
