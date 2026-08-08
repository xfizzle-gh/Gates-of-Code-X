from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from gates_of_codex.effective_definitions import EffectiveDefinitionIndex
from gates_of_codex.expanded_nations import (
    activate_from_stack_config,
    deactivate_actor_projection,
    verify_actor_projection,
)
from gates_of_codex.expanded_nations_models import (
    BROAD_ROSTER_INCLUDES,
    MANIFEST_RELATIVE,
)
from gates_of_codex.expanded_nations_opponents import project_opponent_units
from gates_of_codex.faction_wiring_research import SourceResearchIndex
from gates_of_codex.faction_wiring_scan import SourceUnitIndex
from gates_of_codex.modstack import stack_signature
from tests.test_expanded_nations import _payload

_GENERATED_NAMES = {
    "roster_conquest.set",
    "goc_active_actor_units.set",
    "goc_opponent_units.set",
    "unit_research_nato.set",
    "unit_research_ukr.set",
    "unit_research_rusa.set",
    "unit_research_prc.set",
}


class ExpandedNationsCompileBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.layers = [self.root / name for name in ("vanilla", "west81", "codex", "ai", "gates")]
        for layer in self.layers:
            (layer / "resource").mkdir(parents=True)
        self.gates = self.layers[-1]
        self._write_sources()
        self.config = self.root / "stack.json"
        self.config.write_text(
            json.dumps({"layers": [str(path) for path in self.layers]}),
            encoding="utf-8",
        )
        self.payload = _payload()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_sources(self) -> None:
        rows = {
            "conquest/units_ukr.set": (
                '{"amx10rc" ("vehicle" side(ukr) crew(fr_crew:3) vehicle(amx10rc))}\n'
                '{"core_ukr(ukr)" ("squad_with1types_conquest" side(ukr) c1(ukr_rifle:5))}\n'
            ),
            "conquest/units_rusa.set": (
                '("squad_with1types_conquest" side(rusa) name(serb_line) c1(Serb_rifleman:5))\n'
                '{"core_rusa(rusa)" ("squad_with1types_conquest" side(rusa) c1(rus_rifle:5))}\n'
            ),
            "conquest/units_nato.set": (
                '{"fra_rifle(nato)" ("squad_with1types_conquest" side(nato) c1(fr_rifle:5))}\n'
                '{"deu_rifle(nato)" ("squad_with1types_conquest" side(nato) c1(deu_rifle:5))}\n'
            ),
            "conquest/units_prc_era1960.set": (
                '{"core_prc(prc)" ("squad_with1types_conquest" side(prc) c1(prc_rifle:5))}\n'
            ),
            "conquest/units_sov_era1960.set": (
                '{"core_sov(rusa)" ("squad_with1types_conquest" side(rusa) c1(sov_rifle:5))}\n'
            ),
            "conquest/units_csa_era1960.set": (
                '{"core_csa(rusa)" ("squad_with1types_conquest" side(rusa) c1(csa_rifle:5))}\n'
            ),
            "conquest/units_frg_era1960.set": (
                '{"core_frg(nato)" ("squad_with1types_conquest" side(nato) c1(frg_rifle:5))}\n'
            ),
        }
        self.assertEqual(set(rows), set(BROAD_ROSTER_INCLUDES))
        for include, text in rows.items():
            priority = 3 if include == "conquest/units_rusa.set" else 2
            path = self.layers[priority] / "resource/set/multiplayer/units" / include
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        wrapper = self.gates / "resource/set/multiplayer/units/conquest/units_goc_national_wrappers.set"
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text(
            '{"goc_ildu_rifle(ukr)" ("squad_with1types_conquest" side(ukr) c1(nato_rifleman:5))}\n',
            encoding="utf-8",
        )

    def _active_bytes(self) -> dict[str, bytes]:
        manifest_path = self.gates / MANIFEST_RELATIVE
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        values = {MANIFEST_RELATIVE.as_posix(): manifest_path.read_bytes()}
        for row in manifest["files"]:
            relative = str(row["relative_path"])
            values[relative] = (self.gates / relative).read_bytes()
        return values

    def test_direct_switch_compiles_from_clean_core_view(self) -> None:
        observations: list[dict[str, object]] = []
        base_payload = self.payload

        class RecordingCompiler:
            def __init__(inner_self, roots):
                inner_self.roots = list(roots)

            def compile(inner_self):
                generated = [
                    path
                    for root in inner_self.roots
                    for path in (root / "resource").rglob("*")
                    if path.is_file() and path.name in _GENERATED_NAMES
                ]
                if generated:
                    raise AssertionError(f"generated inputs remained visible: {generated}")
                unit_index = SourceUnitIndex.build(inner_self.roots)
                EffectiveDefinitionIndex.build(inner_self.roots, unit_index=unit_index)
                SourceResearchIndex.build(inner_self.roots)
                signature = stack_signature(inner_self.roots)
                source_files = sorted(
                    source
                    for unit in unit_index.units.values()
                    for source in unit.source_files
                )
                if any(any(name in source for name in _GENERATED_NAMES) for source in source_files):
                    raise AssertionError(f"generated source provenance remained visible: {source_files}")
                observations.append(
                    {"stack_signature": signature, "source_files": source_files}
                )
                payload = deepcopy(base_payload)
                payload["stack_signature"] = signature
                payload["wiring_signature"] = hashlib.sha256(
                    json.dumps(
                        {"stack_signature": signature, "actors": payload["actors"]},
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                return payload

        with mock.patch(
            "gates_of_codex.expanded_nations.FactionWiringCompiler",
            RecordingCompiler,
        ):
            activate_from_stack_config(self.config, "fra")
            direct = activate_from_stack_config(self.config, "srb")
            direct_bytes = self._active_bytes()
            self.assertEqual(verify_actor_projection(self.gates)["actor_id"], "srb")

            self.assertTrue(deactivate_actor_projection(self.gates))
            core = activate_from_stack_config(self.config, "srb")
            core_bytes = self._active_bytes()
            self.assertEqual(direct.projection_signature, core.projection_signature)
            self.assertEqual(direct.wiring_signature, core.wiring_signature)
            self.assertEqual(direct_bytes, core_bytes)

            repeated = activate_from_stack_config(self.config, "srb")
            repeated_bytes = self._active_bytes()
            self.assertEqual(core.projection_signature, repeated.projection_signature)
            self.assertEqual(core.wiring_signature, repeated.wiring_signature)
            self.assertEqual(core_bytes, repeated_bytes)

        self.assertGreaterEqual(len(observations), 4)
        self.assertEqual(
            {str(row["stack_signature"]) for row in observations},
            {str(observations[0]["stack_signature"])},
        )
        for row in observations:
            for source in row["source_files"]:  # type: ignore[index]
                self.assertFalse(any(name in str(source) for name in _GENERATED_NAMES))


class ExpandedNationsOpponentSideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.layers = [self.root / name for name in ("vanilla", "west81", "codex", "ai", "gates")]
        for layer in self.layers:
            (layer / "resource").mkdir(parents=True)
        self._write("conquest/units_rusa.set", (
            '{"filename_selected" ("squad_with1types_conquest" c1(rus_rifle:5))}\n'
            '(include "conquest/nested_rusa.set")\n'
        ))
        self._write("conquest/nested_rusa.set", (
            '{"nested_selected" ("squad_with1types_conquest" c1(rus_rifle:5))}\n'
            '(include "conquest/nested_nato.set")\n'
        ))
        self._write("conquest/nested_nato.set", (
            '{"nested_opponent" ("squad_with1types_conquest" c1(nato_rifle:5))}\n'
        ))
        self._write("conquest/units_nato.set", (
            '{"suffix_selected(rusa)" ("squad_with1types_conquest" c1(rus_rifle:5))}\n'
            '{"core_nato(nato)" ("squad_with1types_conquest" c1(nato_rifle:5))}\n'
        ))
        self._write("conquest/units_ukr.set", (
            '{"core_ukr(ukr)" ("squad_with1types_conquest" c1(ukr_rifle:5))}\n'
        ))
        self._write("conquest/units_prc_era1960.set", (
            '{"core_prc(prc)" ("squad_with1types_conquest" c1(prc_rifle:5))}\n'
        ))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, include: str, text: str) -> None:
        path = self.layers[2] / "resource/set/multiplayer/units" / include
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_filename_suffix_and_nested_include_filtering(self) -> None:
        projected, body = project_opponent_units("rusa", self.layers)
        names = [row.entry_name for row in projected]
        self.assertNotIn("filename_selected", names)
        self.assertNotIn("nested_selected", names)
        self.assertNotIn("suffix_selected(rusa)", names)
        self.assertIn("nested_opponent", names)
        self.assertIn("core_nato(nato)", names)
        self.assertIn("core_ukr(ukr)", names)
        self.assertIn("core_prc(prc)", names)
        self.assertNotIn("(include", body.lower())
        sides = {row.entry_name: row.tactical_side for row in projected}
        self.assertEqual(sides["nested_opponent"], "nato")
        self.assertEqual(sides["core_nato(nato)"], "nato")


if __name__ == "__main__":
    unittest.main()
